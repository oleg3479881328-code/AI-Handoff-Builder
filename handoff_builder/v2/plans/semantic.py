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
MIXED_MEDIA_SCHEMA_VERSIONS = {"3.0"}


@dataclass(frozen=True, slots=True)
class ValidatedMixedMediaAsset:
    asset_id: str
    path: Path
    media_type: str
    duration_ms: int
    width: int
    height: int
    rotation: int
    has_audio: bool


@dataclass(frozen=True, slots=True)
class ValidatedMixedMediaOperation:
    asset_id: str
    op: str
    duration_ms: int
    source_in_ms: int | None
    source_out_ms: int | None
    mute_original_audio: bool


@dataclass(frozen=True, slots=True)
class ValidatedMixedMediaPlan:
    payload: dict
    assets: dict[str, ValidatedMixedMediaAsset]
    operations: tuple[ValidatedMixedMediaOperation, ...]
    planned_duration_ms: int
    output_width: int
    output_height: int
    output_fps: int
    audio_track: dict | None
    audio_gain: float


def load_and_validate_mixed_media_plan(
    plan_path: Path,
    workspace: Path,
    package_root: Path,
    backend: FFmpegBackend,
    manifest: dict,
) -> ValidatedMixedMediaPlan:
    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_payload("edit_plan", str(payload["schema_version"]), payload)
    _reject_forbidden_keys(payload)
    if payload.get("mode") != "preview":
        raise UnsafePackageError("Only preview mode is supported in edit plan 3.0.")

    registry_payload = json.loads(
        (workspace.resolve() / "analysis" / "local_asset_registry.json").read_text(encoding="utf-8")
    )
    resolution_report = resolve_plan_assets_against_registry(
        list(payload["assets"]),
        registry_payload,
        require_declared_integrity=False,
    )

    assets: dict[str, ValidatedMixedMediaAsset] = {}
    for item in resolution_report["assets"]:
        asset_id = str(item["asset_id"])
        source_path = Path(str(item["source_path"]))
        media_type = str(item["media_type"])
        if media_type == "video":
            meta = backend.probe(source_path)
            if meta["codec"] is None:
                raise UnsafePackageError(f"Asset is not a decodable video file: {asset_id}")
            assets[asset_id] = ValidatedMixedMediaAsset(
                asset_id=asset_id,
                path=source_path,
                media_type=media_type,
                duration_ms=round(float(meta["duration"]) * 1000),
                width=int(meta["width"]),
                height=int(meta["height"]),
                rotation=int(meta["rotation"]),
                has_audio=bool(meta["has_audio"]),
            )
        elif media_type == "photo":
            try:
                with Image.open(source_path) as image:
                    width, height = image.size
            except Exception as exc:
                raise UnsafePackageError(f"Asset resolution failed: unreadable image for {asset_id}: {exc}") from exc
            assets[asset_id] = ValidatedMixedMediaAsset(
                asset_id=asset_id,
                path=source_path,
                media_type=media_type,
                duration_ms=0,
                width=width,
                height=height,
                rotation=0,
                has_audio=False,
            )
        else:
            raise UnsafePackageError(f"Unsupported media_type in mixed media plan: {media_type}")

    if not payload["operations"]:
        raise UnsafePackageError("Mixed media plan timeline is empty.")

    operations: list[ValidatedMixedMediaOperation] = []
    for op in payload["operations"]:
        op_name = str(op["op"])
        asset_id = str(op["asset_id"])
        if asset_id not in assets:
            raise UnsafePackageError(f"Operation references unknown asset_id: {asset_id}")
        asset = assets[asset_id]

        if op_name == "image_hold":
            if asset.media_type != "photo":
                raise UnsafePackageError(f"image_hold operation requires a photo asset, got {asset.media_type}: {asset_id}")
            duration_ms = int(op["duration_ms"])
            if duration_ms <= 0:
                raise UnsafePackageError("image_hold duration_ms must be positive.")
            operations.append(ValidatedMixedMediaOperation(
                asset_id=asset_id,
                op=op_name,
                duration_ms=duration_ms,
                source_in_ms=None,
                source_out_ms=None,
                mute_original_audio=False,
            ))
        elif op_name == "video_segment":
            if asset.media_type != "video":
                raise UnsafePackageError(f"video_segment operation requires a video asset, got {asset.media_type}: {asset_id}")
            source_in_ms = int(op["source_in_ms"])
            source_out_ms = int(op["source_out_ms"])
            if source_in_ms < 0 or source_out_ms < 0:
                raise UnsafePackageError("Negative source trim values are not allowed.")
            if source_out_ms <= source_in_ms:
                raise UnsafePackageError("source_out_ms must be greater than source_in_ms.")
            if source_out_ms > asset.duration_ms + SOURCE_OUT_TOLERANCE_MS:
                raise UnsafePackageError(
                    f"Requested trim exceeds source duration for {asset_id}: {source_out_ms} > {asset.duration_ms}"
                )
            clamped_out = min(source_out_ms, asset.duration_ms)
            duration_ms = clamped_out - source_in_ms
            mute = bool(op.get("mute_original_audio", False))
            operations.append(ValidatedMixedMediaOperation(
                asset_id=asset_id,
                op=op_name,
                duration_ms=duration_ms,
                source_in_ms=source_in_ms,
                source_out_ms=clamped_out,
                mute_original_audio=mute,
            ))
        else:
            raise UnsafePackageError(f"Unsupported operation type in mixed media plan: {op_name}")

    planned_duration_ms = sum(op.duration_ms for op in operations)
    if planned_duration_ms <= 0:
        raise UnsafePackageError("Planned duration must be positive.")

    output = payload["output"]
    audio_track = manifest.get("audio_track")
    audio_gain = float(audio_track["gain"]) if audio_track else 1.0

    return ValidatedMixedMediaPlan(
        payload=payload,
        assets=assets,
        operations=tuple(operations),
        planned_duration_ms=planned_duration_ms,
        output_width=int(output["width"]),
        output_height=int(output["height"]),
        output_fps=int(output["fps"]),
        audio_track=audio_track,
        audio_gain=audio_gain,
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
