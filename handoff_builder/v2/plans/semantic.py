from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ..errors import UnsafePackageError
from ..packages.guards import ensure_allowed_package_path
from ..plans.schema import validate_payload
from ..render.ffmpeg_backend import FFmpegBackend


FORBIDDEN_KEYS = {"ffmpeg", "ffmpeg_args", "ffmpeg_filter", "filter_complex", "command", "shell"}
SOURCE_OUT_TOLERANCE_MS = 50


@dataclass(frozen=True, slots=True)
class ValidatedAsset:
    asset_id: str
    path: Path
    duration_ms: int
    width: int
    height: int
    rotation: int
    has_audio: bool


@dataclass(frozen=True, slots=True)
class ValidatedOperation:
    asset_id: str
    source_in_ms: int
    source_out_ms: int
    duration_ms: int


@dataclass(frozen=True, slots=True)
class ValidatedPreviewPlan:
    payload: dict
    assets: dict[str, ValidatedAsset]
    operations: tuple[ValidatedOperation, ...]
    planned_duration_ms: int


def load_and_validate_preview_plan(
    plan_path: Path,
    package_root: Path,
    backend: FFmpegBackend,
) -> ValidatedPreviewPlan:
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_payload("edit_plan", str(payload["schema_version"]), payload)
    _reject_forbidden_keys(payload)
    if payload.get("mode") != "preview":
        raise UnsafePackageError("Only preview mode is supported in milestone 4.")

    assets: dict[str, ValidatedAsset] = {}
    for asset in payload["assets"]:
        asset_id = str(asset["asset_id"])
        rel_path = str(asset["path"])
        ensure_allowed_package_path(rel_path)
        resolved = (package_root / rel_path).resolve()
        if package_root.resolve() not in resolved.parents and resolved != package_root.resolve():
            raise UnsafePackageError(f"Asset path escapes package root: {rel_path}")
        if not resolved.exists():
            raise UnsafePackageError(f"Asset file does not exist: {rel_path}")
        meta = backend.probe(resolved)
        if meta["codec"] is None:
            raise UnsafePackageError(f"Asset is not a decodable video file: {rel_path}")
        assets[asset_id] = ValidatedAsset(
            asset_id=asset_id,
            path=resolved,
            duration_ms=round(float(meta["duration"]) * 1000),
            width=int(meta["width"]),
            height=int(meta["height"]),
            rotation=int(meta["rotation"]),
            has_audio=bool(meta["has_audio"]),
        )

    if not payload["operations"]:
        raise UnsafePackageError("Preview plan timeline is empty.")

    operations: list[ValidatedOperation] = []
    for op in payload["operations"]:
        if op["op"] != "video_segment":
            raise UnsafePackageError(f"Unsupported operation type: {op['op']}")
        asset_id = str(op["asset_id"])
        if asset_id not in assets:
            raise UnsafePackageError(f"Operation references unknown asset_id: {asset_id}")
        source_in_ms = int(op["source_in_ms"])
        source_out_ms = int(op["source_out_ms"])
        if source_in_ms < 0 or source_out_ms < 0:
            raise UnsafePackageError("Negative source trim values are not allowed.")
        if source_out_ms <= source_in_ms:
            raise UnsafePackageError("source_out_ms must be greater than source_in_ms.")
        asset_meta = assets[asset_id]
        if source_out_ms > asset_meta.duration_ms + SOURCE_OUT_TOLERANCE_MS:
            raise UnsafePackageError(
                f"Requested trim exceeds source duration for {asset_id}: {source_out_ms} > {asset_meta.duration_ms}"
            )
        operations.append(
            ValidatedOperation(
                asset_id=asset_id,
                source_in_ms=source_in_ms,
                source_out_ms=min(source_out_ms, asset_meta.duration_ms),
                duration_ms=min(source_out_ms, asset_meta.duration_ms) - source_in_ms,
            )
        )

    planned_duration_ms = sum(op.duration_ms for op in operations)
    if planned_duration_ms <= 0:
        raise UnsafePackageError("Planned duration must be positive.")
    return ValidatedPreviewPlan(
        payload=payload,
        assets=assets,
        operations=tuple(operations),
        planned_duration_ms=planned_duration_ms,
    )


def _reject_forbidden_keys(node: object) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            key_normalized = str(key).lower()
            if key_normalized in FORBIDDEN_KEYS:
                raise UnsafePackageError(f"Forbidden raw command/filter field found: {key}")
            _reject_forbidden_keys(value)
    elif isinstance(node, list):
        for value in node:
            _reject_forbidden_keys(value)
