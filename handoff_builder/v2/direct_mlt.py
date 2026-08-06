from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..utils import file_sha256
from .errors import UnsafePackageError
from .render.shotcut_backend import (
    ShotcutBackendPaths,
    ShotcutClipIntent,
    ShotcutMcpBackend,
    ShotcutProfile,
)
from .shotcut_settings import ShotcutAppSettings


def load_assistant_context(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise UnsafePackageError("ASSISTANT_CONTEXT.json must contain one JSON object.")
    if str(payload.get("document_type") or "") != "assistant_context":
        raise UnsafePackageError("ASSISTANT_CONTEXT.json has an unexpected document_type.")
    return payload


def build_direct_shotcut_mlt_from_context(
    context_path: Path,
    *,
    settings: ShotcutAppSettings,
    output_path: Path,
    selected_asset_ids: list[str] | None = None,
    image_duration_seconds: float = 3.0,
) -> dict[str, Any]:
    context = load_assistant_context(context_path)
    backend = _backend_for_context(context, settings=settings, output_path=output_path)
    return build_direct_shotcut_mlt_from_context_payload(
        context,
        backend=backend,
        output_path=output_path,
        selected_asset_ids=selected_asset_ids,
        image_duration_seconds=image_duration_seconds,
    )


def open_direct_shotcut_mlt_from_context(
    context_path: Path,
    *,
    settings: ShotcutAppSettings,
    project_path: Path,
) -> dict[str, Any]:
    context = load_assistant_context(context_path)
    backend = _backend_for_context(context, settings=settings, output_path=project_path)
    return backend.open_in_shotcut(project_path)


def build_direct_shotcut_mlt_from_context_payload(
    context: dict[str, Any],
    *,
    backend: ShotcutMcpBackend | Any,
    output_path: Path,
    selected_asset_ids: list[str] | None = None,
    image_duration_seconds: float = 3.0,
) -> dict[str, Any]:
    direct_support = dict(context.get("direct_mlt_support") or {})
    if not bool(direct_support.get("available")):
        raise UnsafePackageError(
            str(direct_support.get("reason_unavailable") or "Direct Shotcut MLT mode is unavailable.")
        )
    if str(context.get("preferred_edit_source") or "") != "originals":
        raise UnsafePackageError("Direct Shotcut MLT mode requires preferred_edit_source=originals.")
    asset_map = context.get("asset_map")
    if not isinstance(asset_map, dict) or not asset_map:
        raise UnsafePackageError("ASSISTANT_CONTEXT.json is missing asset_map.")

    asset_ids = selected_asset_ids or sorted(str(asset_id) for asset_id in asset_map.keys())
    if not asset_ids:
        raise UnsafePackageError("Direct Shotcut MLT mode requires at least one mapped asset.")

    resolved_assets: list[dict[str, Any]] = []
    for asset_id in asset_ids:
        entry = asset_map.get(asset_id)
        if not isinstance(entry, dict):
            raise UnsafePackageError(f"Selected asset has no mapped original path: {asset_id}")
        original_path_raw = str(entry.get("original_path") or "").strip()
        if not original_path_raw:
            raise UnsafePackageError(f"Selected asset has no mapped original path: {asset_id}")
        original_path = Path(original_path_raw).expanduser()
        if not original_path.exists():
            raise UnsafePackageError(f"Mapped original path does not exist for {asset_id}: {original_path}")
        resolved_assets.append(
            {
                "asset_id": asset_id,
                "media_type": str(entry.get("media_type") or "photo"),
                "original_name": str(entry.get("original_name") or entry.get("original_filename") or original_path.name),
                "original_path": original_path.resolve(),
            }
        )

    first_probe = backend.probe_media(resolved_assets[0]["original_path"])
    first_video = _primary_video_stream(first_probe)
    fps = _rounded_fps(first_probe)
    clips: list[ShotcutClipIntent] = []
    cursor_frames = 0
    sequence_summary: list[dict[str, Any]] = []
    for item in resolved_assets:
        media_path = item["original_path"]
        media_type = str(item["media_type"])
        if media_type == "photo":
            duration_frames = max(1, round(image_duration_seconds * fps))
            clip = ShotcutClipIntent(
                media_path=media_path,
                track="V1",
                position_frame=cursor_frames,
                in_frame=0,
                out_frame=0,
                image_duration_seconds=image_duration_seconds,
                caption=str(item["asset_id"]),
            )
        else:
            probe = backend.probe_media(media_path)
            asset_fps = _rounded_fps(probe)
            duration_seconds = float(probe.get("duration_seconds") or 0.0)
            source_out_frame = max(0, round(duration_seconds * asset_fps) - 1)
            duration_frames = max(1, round(duration_seconds * fps))
            clip = ShotcutClipIntent(
                media_path=media_path,
                track="V1",
                position_frame=cursor_frames,
                in_frame=0,
                out_frame=source_out_frame,
                caption=str(item["asset_id"]),
            )
        clips.append(clip)
        sequence_summary.append(
            {
                "asset_id": str(item["asset_id"]),
                "media_type": media_type,
                "original_path": str(media_path),
                "position_frame": cursor_frames,
                "duration_frames": duration_frames,
            }
        )
        cursor_frames += duration_frames

    output_path.parent.mkdir(parents=True, exist_ok=True)
    create_result = backend.create_disposable_project(
        output_path,
        profile=ShotcutProfile(
            width=int(first_video["width"]),
            height=int(first_video["height"]),
            fps_num=fps,
            fps_den=1,
        ),
        clips=clips,
        overwrite=True,
    )
    inspect_result = backend.inspect_project(output_path)
    validate_result = backend.validate_project(output_path)
    validation = validate_direct_mlt_resources(context, inspect_result=inspect_result, output_path=output_path)
    return {
        "project_path": str(output_path.resolve()),
        "project_sha256": file_sha256(output_path),
        "create_result": create_result,
        "inspect_result": inspect_result,
        "validate_result": validate_result,
        "resource_validation": validation,
        "sequence_summary": sequence_summary,
    }


def validate_direct_mlt_resources(
    context: dict[str, Any],
    *,
    inspect_result: dict[str, Any],
    output_path: Path,
) -> dict[str, Any]:
    if "%20" in output_path.name:
        raise UnsafePackageError("Direct Shotcut MLT filename must not contain literal %20.")
    asset_map = context.get("asset_map")
    if not isinstance(asset_map, dict):
        raise UnsafePackageError("ASSISTANT_CONTEXT.json is missing asset_map.")
    expected_originals = {
        str(Path(str(item.get("original_path") or "")).resolve())
        for item in asset_map.values()
        if isinstance(item, dict) and item.get("original_path")
    }
    proxy_paths = {
        str(Path(str(item.get("proxy_path") or "")).resolve())
        for item in asset_map.values()
        if isinstance(item, dict) and item.get("proxy_path")
    }
    resolved_resources: list[str] = []
    for resource in inspect_result.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        resolved = str(resource.get("resolved_path") or "")
        if not resolved:
            continue
        resolved_resources.append(resolved)
        if resolved in proxy_paths:
            raise UnsafePackageError("Direct Shotcut MLT mode must not use proxy media resources.")
        if resolved not in expected_originals:
            raise UnsafePackageError(f"Direct Shotcut MLT resource escaped the original asset map: {resolved}")
    missing_resources = list(inspect_result.get("missing_resources") or [])
    if missing_resources:
        raise UnsafePackageError(f"Direct Shotcut MLT has missing resources: {missing_resources}")
    return {
        "resource_count": len(resolved_resources),
        "resources": resolved_resources,
        "missing_resources": missing_resources,
        "uses_only_originals": True,
        "filename_contains_percent20": False,
    }


def _backend_for_context(
    context: dict[str, Any],
    *,
    settings: ShotcutAppSettings,
    output_path: Path,
) -> ShotcutMcpBackend:
    runtime_dir = settings.with_defaults().runtime_path()
    server_script = settings.with_defaults().server_script_path()
    if runtime_dir is None or server_script is None:
        raise UnsafePackageError("Shotcut settings are incomplete. Runtime folder and MCP script are required.")
    project_root = Path(str(context.get("project_root") or "")).expanduser()
    originals_root = Path(str(context.get("originals_root") or "")).expanduser()
    proxies_root = Path(str(context.get("proxies_root") or "")).expanduser()
    allowed_roots = tuple(
        root.resolve()
        for root in (project_root, originals_root, proxies_root, output_path.parent)
        if str(root)
    )
    return ShotcutMcpBackend(
        ShotcutBackendPaths(
            server_script=server_script,
            allowed_roots=allowed_roots,
            shotcut_path=runtime_dir / "shotcut.exe",
            melt_path=runtime_dir / "melt.exe",
            ffmpeg_path=runtime_dir / "ffmpeg.exe",
            ffprobe_path=runtime_dir / "ffprobe.exe",
        )
    )


def _primary_video_stream(probe: dict[str, Any]) -> dict[str, Any]:
    streams = probe.get("streams") or []
    video_stream = next((item for item in streams if item.get("type") == "video"), None)
    if not isinstance(video_stream, dict):
        raise UnsafePackageError("Shotcut probe did not return a video stream.")
    return video_stream


def _rounded_fps(probe: dict[str, Any]) -> int:
    return max(1, round(float(_primary_video_stream(probe).get("frame_rate") or 30.0)))
