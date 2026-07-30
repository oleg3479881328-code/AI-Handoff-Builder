from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from ..assets import resolve_plan_assets_against_registry
from ..errors import UnsafePackageError
from ..packages.guards import ensure_allowed_package_path
from ..plans.schema import load_bounded_json_object, validate_payload
from ..render.ffmpeg_backend import FFmpegBackend


FORBIDDEN_KEYS = {"ffmpeg", "ffmpeg_args", "ffmpeg_filter", "filter_complex", "command", "shell"}
SOURCE_OUT_TOLERANCE_MS = 50


@dataclass(frozen=True, slots=True)
class ValidatedAsset:
    asset_id: str
    path: Path | None
    duration_ms: int | None
    width: int | None
    height: int | None
    rotation: int | None
    has_audio: bool | None
    media_type: str = "video"


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
    payload: dict
    assets: dict[str, ValidatedAsset]
    audio_assets: dict[str, ValidatedAsset]
    tracks: tuple[dict, ...]
    fps_num: int
    fps_den: int
    total_duration_frames: int


def load_and_validate_edit_plan_3(
    plan_path: Path,
    workspace: Path,
    backend: FFmpegBackend,
) -> ValidatedEditPlan3:
    payload = load_bounded_json_object(plan_path)
    validate_payload("edit_plan", "3.0", payload)
    _reject_forbidden_keys(payload)
    if str(payload.get("document_type")) != "edit_plan":
        raise UnsafePackageError("edit_plan 3.0 must declare document_type=edit_plan.")
    renderer = payload.get("renderer") or {}
    if str(renderer.get("primary_renderer")) != "shotcut":
        raise UnsafePackageError("edit_plan 3.0 must target renderer.primary_renderer=shotcut.")
    timebase = payload.get("timebase", {})
    fps_num = int(timebase.get("fps_num", 0))
    fps_den = int(timebase.get("fps_den", 0))
    if fps_num <= 0 or fps_den <= 0:
        raise UnsafePackageError(f"Invalid rational timebase: {fps_num}/{fps_den}")

    assets: dict[str, ValidatedAsset] = {}
    audio_assets: dict[str, ValidatedAsset] = {}
    seen_asset_ids: set[str] = set()
    resolution_report = resolve_plan_assets_against_registry(
        list(payload.get("assets") or []),
        json.loads((workspace.resolve() / "analysis" / "local_asset_registry.json").read_text(encoding="utf-8")),
        require_declared_integrity=False,
        workspace=workspace,
    )
    for resolved in resolution_report["assets"]:
        asset_id = str(resolved["asset_id"])
        if asset_id in seen_asset_ids:
            raise UnsafePackageError(f"Duplicate asset_id in assets: {asset_id}")
        seen_asset_ids.add(asset_id)
        source_path = Path(str(resolved["source_path"]))
        media_type = str(resolved["media_type"])
        duration_ms: int | None = None
        width: int | None = None
        height: int | None = None
        rotation: int | None = None
        has_audio: bool | None = None
        if media_type in {"video", "audio"}:
            meta = backend.probe(source_path)
            duration_ms = round(float(meta["duration"]) * 1000)
            width = int(meta["width"]) if meta.get("width") is not None else None
            height = int(meta["height"]) if meta.get("height") is not None else None
            rotation = int(meta["rotation"]) if meta.get("rotation") is not None else 0
            has_audio = bool(meta.get("audio_present"))
        elif media_type == "photo":
            with Image.open(source_path) as image:
                width, height = image.size
            rotation = 0
            has_audio = False
            duration_ms = None
        else:
            raise UnsafePackageError(f"Unsupported asset media_type: {media_type}")

        validated = ValidatedAsset(
            asset_id=asset_id,
            path=source_path,
            duration_ms=duration_ms,
            width=width,
            height=height,
            rotation=rotation,
            has_audio=has_audio,
            media_type=media_type,
        )
        if media_type == "audio":
            audio_assets[asset_id] = validated
        else:
            assets[asset_id] = validated

    track_ids: list[str] = []
    validated_items: list[dict] = []
    total_duration_frames = 0
    seen_item_ids: set[str] = set()
    for item in payload.get("visual_items", []):
        item_id = str(item["item_id"])
        if item_id in seen_item_ids:
            raise UnsafePackageError(f"Duplicate visual item_id: {item_id}")
        seen_item_ids.add(item_id)
        asset_id = str(item["asset_id"])
        if asset_id not in assets:
            raise UnsafePackageError(f"Visual item references unknown asset_id: {asset_id}")
        media_type = str(item["media_type"])
        if media_type != assets[asset_id].media_type:
            raise UnsafePackageError(
                f"Visual item media_type does not match asset media_type for {asset_id}"
            )
        sap = str(item["source_audio_policy"])
        if sap != "discard":
            raise UnsafePackageError(
                f"Unsupported source_audio_policy for current Shotcut compiler: {sap}"
            )
        source_in_us = int(item["source_in_us"])
        source_out_us = int(item["source_out_us"])
        if media_type == "photo":
            if source_in_us != 0 or source_out_us != 0:
                raise UnsafePackageError("Photo items must use source_in_us=0 and source_out_us=0.")
        else:
            if source_out_us <= source_in_us:
                raise UnsafePackageError("source_out_us must be > source_in_us")
        duration_frames = int(item["duration_frames"])
        timeline_start_frame = int(item["timeline_start_frame"])
        track_id = str(item["track_id"])
        track_ids.append(track_id)
        total_duration_frames = max(total_duration_frames, timeline_start_frame + duration_frames)
        validated_items.append(dict(item))

    validated_tracks: list[dict] = []
    for track_id in sorted(set(track_ids)):
        validated_tracks.append(
            {
                "track_id": track_id,
                "track_type": "video",
                "items": tuple(item for item in validated_items if item["track_id"] == track_id),
            }
        )
    for audio_item in payload.get("audio_items", []):
        audio_id = str(audio_item["audio_id"])
        if audio_id not in audio_assets:
            raise UnsafePackageError(f"Audio item references unknown audio asset_id: {audio_id}")
        duration_frames = int(audio_item["duration_frames"])
        timeline_start_frame = int(audio_item["timeline_start_frame"])
        total_duration_frames = max(total_duration_frames, timeline_start_frame + duration_frames)
    if total_duration_frames <= 0:
        raise UnsafePackageError("Total timeline duration must be positive.")
    return ValidatedEditPlan3(
        payload=payload,
        assets=assets,
        audio_assets=audio_assets,
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
            has_audio=bool(meta.get("audio_present")),
            media_type=str(asset.get("media_type") or "video"),
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
        workspace=workspace,
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
