from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..assets import resolve_plan_assets_against_registry
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


@dataclass(frozen=True, slots=True)
class ResolvedPhotoAsset:
    asset_id: str
    path: Path
    width: int
    height: int
    sha256: str
    size_bytes: int
    original_name: str | None


@dataclass(frozen=True, slots=True)
class ValidatedPhotoSegment:
    asset_id: str
    duration_ms: int
    overlay_text: str | None


@dataclass(frozen=True, slots=True)
class ValidatedLocalPhotoPlan:
    payload: dict
    assets: dict[str, ResolvedPhotoAsset]
    segments: tuple[ValidatedPhotoSegment, ...]
    planned_duration_ms: int
    output_width: int
    output_height: int
    output_fps: int
    resolution_report: dict


LOCAL_PHOTO_SCHEMA_VERSIONS = {"2.0", "2.1"}
EDIT_PLAN_3_SCHEMA_VERSIONS = {"3.0"}


@dataclass(frozen=True, slots=True)
class ValidatedEditPlan3:
    """Validated edit_plan 3.0 with resolved assets and rational timebase."""
    payload: dict
    assets: dict[str, ValidatedAsset]
    audio_assets: dict[str, dict]
    tracks: tuple[dict, ...]
    fps_num: int
    fps_den: int
    total_duration_frames: int


def load_and_validate_edit_plan_3(
    plan_path: Path,
    package_root: Path,
    backend: FFmpegBackend,
) -> ValidatedEditPlan3:
    """Validate an edit_plan 3.0 with DaVinci-first rational timebase.

    Validates:
    - Schema conformance (3.0)
    - source_audio_policy enum (discard, keep, duck_under_music, replace)
    - Rational timebase (fps_num/fps_den from timebase object)
    - Integer frame positions, microsecond source positions
    - Asset existence and probe
    - No forbidden keys (executable payloads)
    """
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_payload("edit_plan", "3.0", payload)
    _reject_forbidden_keys(payload)

    timebase = payload.get("timebase", {})
    fps_num = int(timebase.get("fps_num", 30))
    fps_den = int(timebase.get("fps_den", 1))
    if fps_num <= 0 or fps_den <= 0:
        raise UnsafePackageError(f"Invalid rational timebase: {fps_num}/{fps_den}")

    # Validate source_audio_policy in visual_items
    for item in payload.get("visual_items", []):
        sap = str(item.get("source_audio_policy", "discard"))
        if sap not in ("discard", "keep", "duck_under_music", "replace"):
            raise UnsafePackageError(
                f"Invalid source_audio_policy '{sap}' in visual_item "
                f"{item.get('item_id', '?')}"
            )

    # Validate assets
    assets: dict[str, ValidatedAsset] = {}
    for asset in payload["assets"]:
        asset_id = str(asset["asset_id"])
        # 3.0 assets may not have a path (registry-resolved)
        if asset.get("path"):
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

    # Validate visual_items
    validated_tracks: list[dict] = []
    total_duration_frames = 0
    validated_items: list[dict] = []
    for item in payload.get("visual_items", []):
        asset_id = str(item["asset_id"])
        if asset_id not in assets:
            raise UnsafePackageError(
                f"Visual item references unknown asset_id: {asset_id}"
            )
        source_in_us = int(item["source_in_us"])
        source_out_us = int(item["source_out_us"])
        if source_in_us < 0 or source_out_us < 0:
            raise UnsafePackageError(
                f"Negative source position: {source_in_us}, {source_out_us}"
            )
        if source_out_us <= source_in_us:
            raise UnsafePackageError(
                f"source_out_us must be > source_in_us"
            )
        duration_frames = int(item["duration_frames"])
        if duration_frames <= 0:
            raise UnsafePackageError(
                f"duration_frames must be positive"
            )
        total_duration_frames += duration_frames
        validated_items.append({
            "asset_id": asset_id,
            "source_in_us": source_in_us,
            "source_out_us": source_out_us,
            "duration_frames": duration_frames,
            "source_audio_policy": str(item.get("source_audio_policy", "discard")),
        })
    validated_tracks.append({
        "track_index": 0,
        "track_type": "video",
        "items": tuple(validated_items),
    })

    if total_duration_frames <= 0:
        raise UnsafePackageError("Total timeline duration must be positive.")

    return ValidatedEditPlan3(
        payload=payload,
        assets=assets,
        audio_assets={},
        tracks=tuple(validated_tracks),
        fps_num=fps_num,
        fps_den=fps_den,
        total_duration_frames=total_duration_frames,
    )


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


def load_and_validate_local_photo_plan(
    plan_path: Path,
    workspace: Path,
) -> ValidatedLocalPhotoPlan:
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_payload("edit_plan", str(payload["schema_version"]), payload)
    _reject_forbidden_keys(payload)
    schema_version = str(payload.get("schema_version"))
    if schema_version not in LOCAL_PHOTO_SCHEMA_VERSIONS:
        raise UnsafePackageError("Local photo plan validation expects edit_plan schema 2.0 or 2.1.")
    if payload.get("mode") != "preview":
        raise UnsafePackageError("Only preview mode is supported in AI edit package 2.x.")

    registry_payload = json.loads(
        (workspace.resolve() / "analysis" / "local_asset_registry.json").read_text(encoding="utf-8")
    )
    resolution_report = resolve_plan_assets_against_registry(
        list(payload["assets"]),
        registry_payload,
        require_declared_integrity=schema_version == "2.0",
    )
    assets: dict[str, ResolvedPhotoAsset] = {}
    for item in resolution_report["assets"]:
        source_path = Path(str(item["source_path"]))
        try:
            with Image.open(source_path) as image:
                width, height = image.size
        except Exception as exc:
            raise UnsafePackageError(f"Asset resolution failed: unreadable image for {item['asset_id']}: {exc}") from exc
        assets[str(item["asset_id"])] = ResolvedPhotoAsset(
            asset_id=str(item["asset_id"]),
            path=source_path,
            width=width,
            height=height,
            sha256=str(item["sha256"]),
            size_bytes=int(item["size_bytes"]),
            original_name=str(item["original_name"]) if item.get("original_name") else None,
        )

    overlays_by_asset_id: dict[str, str] = {}
    for op in payload["operations"]:
        if str(op["op"]) == "text_overlay":
            overlays_by_asset_id[str(op["asset_id"])] = str(op["text"])

    ordered_segments: list[ValidatedPhotoSegment] = []
    for op in payload["operations"]:
        op_name = str(op["op"])
        asset_id = str(op["asset_id"])
        if asset_id not in assets:
            raise UnsafePackageError(f"Operation references unknown asset_id: {asset_id}")
        if op_name == "text_overlay":
            continue
        if op_name != "image_hold":
            raise UnsafePackageError(f"Unsupported operation type: {op_name}")
        duration_ms = int(op["duration_ms"])
        if duration_ms <= 0:
            raise UnsafePackageError("image_hold duration_ms must be positive.")
        ordered_segments.append(
            ValidatedPhotoSegment(
                asset_id=asset_id,
                duration_ms=duration_ms,
                overlay_text=overlays_by_asset_id.get(asset_id),
            )
        )

    if not ordered_segments:
        raise UnsafePackageError("Preview plan timeline is empty.")

    planned_duration_ms = sum(segment.duration_ms for segment in ordered_segments)
    output = payload["output"]
    return ValidatedLocalPhotoPlan(
        payload=payload,
        assets=assets,
        segments=tuple(ordered_segments),
        planned_duration_ms=planned_duration_ms,
        output_width=int(output["width"]),
        output_height=int(output["height"]),
        output_fps=int(output["fps"]),
        resolution_report=resolution_report,
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
