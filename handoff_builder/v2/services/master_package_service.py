from __future__ import annotations

import csv
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...ffmpeg_tools import FFmpegTools, run_command
from ...models import AssetRecord, MasterPackageResult
from ...utils import file_sha256, json_dump
from ..errors import UnsafePackageError
from ..packages.guards import compute_content_hash
from ..render.shotcut_backend import (
    ShotcutBackendPaths,
    ShotcutClipIntent,
    ShotcutMcpBackend,
    ShotcutProfile,
    ShotcutTrackIntent,
)
from ..shotcut_settings import ShotcutAppSettings


PHOTO_DURATION_MS = 500


@dataclass(frozen=True, slots=True)
class MasterTimelineBuild:
    items: list[dict[str, Any]]
    video_count: int
    photo_count: int
    total_duration_ms: int
    fps: int
    width: int
    height: int


def prepare_master_package(
    *,
    project_root: Path,
    project_id: str,
    project_name: str,
    assets: list[AssetRecord],
    metadata_records: list[dict[str, Any]],
    ffmpeg_tools: FFmpegTools,
    shotcut_settings: ShotcutAppSettings,
    create_visual_master: bool = False,
    shotcut_backend: ShotcutMcpBackend | None = None,
) -> MasterPackageResult:
    resolved_root = project_root.resolve()
    handoffs_root = resolved_root / "handoffs"
    handoffs_root.mkdir(parents=True, exist_ok=True)
    safe_name = _owner_safe_name(project_name)
    master_dir = handoffs_root / f"{safe_name}_MASTER_PACKAGE"
    master_dir.mkdir(parents=True, exist_ok=True)
    transcript_import_dir = master_dir / "TRANSCRIPT_IMPORT"
    transcript_import_dir.mkdir(parents=True, exist_ok=True)

    registry_payload = json.loads((resolved_root / "analysis" / "local_asset_registry.json").read_text(encoding="utf-8"))
    registry_by_asset_id = {
        str(item["asset_id"]): dict(item)
        for item in registry_payload.get("assets", [])
        if item.get("asset_id")
    }
    metadata_by_asset_id = {
        str(item["asset_id"]): dict(item)
        for item in metadata_records
        if item.get("asset_id")
    }

    timeline = _build_master_timeline(
        project_root=resolved_root,
        assets=assets,
        metadata_by_asset_id=metadata_by_asset_id,
        registry_by_asset_id=registry_by_asset_id,
    )
    versioned_mlt_name = _allocate_versioned_mlt_name(master_dir, safe_name)
    master_mlt_path = master_dir / versioned_mlt_name
    master_audio_path = master_dir / f"{safe_name}_MASTER_AUDIO.mp3"
    timeline_map_path = master_dir / f"{safe_name}_MASTER_TIMELINE_MAP.json"
    edit_plan_json_path = master_dir / f"{safe_name}_MASTER_EDIT_PLAN.json"
    edit_plan_csv_path = master_dir / f"{safe_name}_MASTER_EDIT_PLAN.csv"
    prompt_path = master_dir / f"{safe_name}_GEMINI_AUDIO_TRANSCRIPTION_PROMPT.md"
    readme_path = master_dir / "README.md"
    start_here_path = master_dir / "00_START_HERE.md"
    project_brief_path = master_dir / "PROJECT_BRIEF.md"
    output_contract_path = master_dir / "OUTPUT_CONTRACT.md"
    handoff_manifest_path = resolved_root / "analysis" / "handoff_manifest.json"

    _write_master_audio(ffmpeg_tools, timeline.items, master_audio_path)
    mp3_probe = _probe_audio(ffmpeg_tools, master_audio_path)
    mp3_duration_ms = int(round(float(mp3_probe.get("duration_seconds") or 0.0) * 1000))
    duration_delta_ms = abs(mp3_duration_ms - timeline.total_duration_ms)
    fps_ms = int(round(1000 / max(1, timeline.fps)))
    tolerance_ms = max(fps_ms, 50)
    if duration_delta_ms > tolerance_ms:
        raise UnsafePackageError(
            f"MASTER_AUDIO duration mismatch exceeds tolerance: timeline={timeline.total_duration_ms} ms, "
            f"mp3={mp3_duration_ms} ms, delta={duration_delta_ms} ms, tolerance={tolerance_ms} ms."
        )

    backend = shotcut_backend or _create_backend(
        shotcut_settings,
        allowed_roots=(resolved_root, master_dir, resolved_root / "originals", resolved_root / "proxies"),
    )
    _write_master_mlt(
        backend=backend,
        project_name=project_name,
        master_mlt_path=master_mlt_path,
        timeline=timeline,
    )

    json_dump(timeline_map_path, {"schema_version": "1.0", "project_id": project_id, "project_name": project_name, "items": timeline.items})
    _write_master_edit_plan_json(edit_plan_json_path, project_id=project_id, project_name=project_name, items=timeline.items)
    _write_master_edit_plan_csv(edit_plan_csv_path, timeline.items)
    prompt_path.write_text(_gemini_prompt(project_name), encoding="utf-8")
    readme_path.write_text(_master_readme(project_name), encoding="utf-8")
    start_here_path.write_text(_master_start_here(project_name), encoding="utf-8")
    project_brief_path.write_text(_master_project_brief(project_id, project_name, timeline), encoding="utf-8")
    output_contract_path.write_text(_master_output_contract(project_name), encoding="utf-8")
    _write_master_handoff_manifest(
        handoff_manifest_path,
        project_id=project_id,
        project_name=project_name,
        master_dir=master_dir,
        timeline=timeline,
    )

    visual_master_path: Path | None = None
    if create_visual_master:
        visual_master_path = master_dir / f"{safe_name}_MASTER_LIGHT.mp4"
        # Keep this optional and derived from the same editable project instead of inventing a second pipeline.
        render_job = backend.start_render(master_mlt_path, visual_master_path, preset="h264-web", overwrite=True)
        final_status = _wait_for_render(backend, render_job.job_id, timeout_seconds=180.0)
        if str(final_status.get("status")) != "completed" or not visual_master_path.exists():
            raise UnsafePackageError("Optional visual master MP4 render did not complete successfully.")

    return MasterPackageResult(
        project_root=resolved_root,
        project_id=project_id,
        project_name=project_name,
        master_package_dir=master_dir,
        master_mlt_path=master_mlt_path,
        master_audio_path=master_audio_path,
        timeline_map_path=timeline_map_path,
        edit_plan_json_path=edit_plan_json_path,
        edit_plan_csv_path=edit_plan_csv_path,
        prompt_path=prompt_path,
        transcript_import_dir=transcript_import_dir,
        state="WAITING_FOR_TRANSCRIPT",
        timeline_item_count=len(timeline.items),
        video_count=timeline.video_count,
        photo_count=timeline.photo_count,
        master_duration_ms=timeline.total_duration_ms,
        mp3_duration_ms=mp3_duration_ms,
        duration_delta_ms=duration_delta_ms,
        visual_master_path=visual_master_path,
    )


def _build_master_timeline(
    *,
    project_root: Path,
    assets: list[AssetRecord],
    metadata_by_asset_id: dict[str, dict[str, Any]],
    registry_by_asset_id: dict[str, dict[str, Any]],
) -> MasterTimelineBuild:
    ordered_assets = sorted(
        assets,
        key=lambda item: (
            item.chronology_rank if item.chronology_rank is not None else 10**9,
            item.capture_time_iso or "",
            item.asset_id,
        ),
    )
    if not ordered_assets:
        raise UnsafePackageError("No assets are available for the master package.")

    first_visual = next((item for item in ordered_assets if (item.width or 0) > 0 and (item.height or 0) > 0), None)
    width = int(first_visual.width if first_visual and first_visual.width else 1080)
    height = int(first_visual.height if first_visual and first_visual.height else 1920)
    first_video_fps = next((item.fps for item in ordered_assets if item.media_type == "video" and item.fps), None)
    fps = int(round(float(first_video_fps))) if first_video_fps else 30

    items: list[dict[str, Any]] = []
    current_start_ms = 0
    video_count = 0
    photo_count = 0
    for index, asset in enumerate(ordered_assets):
        registry_row = registry_by_asset_id.get(asset.asset_id) or {}
        metadata_row = metadata_by_asset_id.get(asset.asset_id) or {}
        duration_ms = int(asset.duration_ms or PHOTO_DURATION_MS if asset.media_type == "video" else PHOTO_DURATION_MS)
        if asset.media_type == "photo":
            duration_ms = PHOTO_DURATION_MS
            photo_count += 1
        else:
            video_count += 1
        current_end_ms = current_start_ms + duration_ms
        item = {
            "timeline_index": index,
            "asset_id": asset.asset_id,
            "asset_type": asset.media_type,
            "source_file_name": asset.original_name,
            "source_absolute_path": str((project_root / str(asset.original_project_path)).resolve()) if asset.original_project_path else asset.source_path,
            "proxy_relative_path": asset.proxy_project_path,
            "master_start": _ms_to_tc(current_start_ms),
            "master_end": _ms_to_tc(current_end_ms),
            "source_in": _ms_to_tc(0),
            "source_out": _ms_to_tc(duration_ms),
            "duration_ms": duration_ms,
            "has_audio": bool(asset.audio_present) if asset.media_type == "video" else False,
            "capture_time": metadata_row.get("normalized_capture_time"),
            "shotcut_producer_id": f"producer_{index:04d}",
            "checksum": registry_row.get("sha256"),
            "width": asset.width,
            "height": asset.height,
            "fps": asset.fps,
            "audio_sample_rate": 48000 if asset.media_type == "video" and asset.audio_present else None,
            "audio_channels": 2 if asset.media_type == "video" and asset.audio_present else None,
        }
        items.append(item)
        current_start_ms = current_end_ms

    return MasterTimelineBuild(
        items=items,
        video_count=video_count,
        photo_count=photo_count,
        total_duration_ms=current_start_ms,
        fps=fps,
        width=width,
        height=height,
    )


def _write_master_audio(ffmpeg_tools: FFmpegTools, items: list[dict[str, Any]], output_path: Path) -> None:
    ffmpeg_path = ffmpeg_tools.ffmpeg
    args = [ffmpeg_path, "-y"]
    filter_parts: list[str] = []
    concat_inputs: list[str] = []
    for input_index, item in enumerate(items):
        duration_seconds = max(0.001, int(item["duration_ms"]) / 1000)
        if item.get("asset_type") == "video" and item.get("has_audio"):
            args.extend(["-i", str(item["source_absolute_path"])])
        else:
            args.extend(["-f", "lavfi", "-t", f"{duration_seconds:.3f}", "-i", "anullsrc=r=48000:cl=stereo"])
        filter_parts.append(
            f"[{input_index}:a]aresample=48000,"
            "aformat=sample_rates=48000:channel_layouts=stereo"
            f"[a{input_index}]"
        )
        concat_inputs.append(f"[a{input_index}]")
    filter_parts.append(f"{''.join(concat_inputs)}concat=n={len(items)}:v=0:a=1[outa]")
    args.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[outa]",
            "-ar",
            "48000",
            "-ac",
            "2",
            "-b:a",
            "192k",
            str(output_path),
        ]
    )
    run_command(args, cancel_event=ffmpeg_tools.cancel_event)


def _write_master_mlt(
    *,
    backend: ShotcutMcpBackend,
    project_name: str,
    master_mlt_path: Path,
    timeline: MasterTimelineBuild,
) -> None:
    tracks: list[ShotcutTrackIntent] = []
    if any(item.get("has_audio") for item in timeline.items):
        tracks.append(ShotcutTrackIntent(kind="audio", name="A1"))
    clips: list[ShotcutClipIntent] = []
    for item in timeline.items:
        position_frame = round(int(item["timeline_index"]) * 0)  # deterministic zero-op keeps mypy happy
        position_frame = round(_tc_to_ms(item["master_start"]) * timeline.fps / 1000)
        source_path = Path(str(item["source_absolute_path"]))
        if item["asset_type"] == "photo":
            clips.append(
                ShotcutClipIntent(
                    media_path=source_path,
                    track="V1",
                    position_frame=position_frame,
                    image_duration_seconds=float(item["duration_ms"]) / 1000,
                )
            )
            continue
        source_duration_frames = max(1, round(int(item["duration_ms"]) * timeline.fps / 1000))
        clips.append(
            ShotcutClipIntent(
                media_path=source_path,
                track="V1",
                position_frame=position_frame,
                in_frame=0,
                out_frame=max(0, source_duration_frames - 1),
            )
        )
        if item.get("has_audio"):
            clips.append(
                ShotcutClipIntent(
                    media_path=source_path,
                    track="A1",
                    position_frame=position_frame,
                    in_frame=0,
                    out_frame=max(0, source_duration_frames - 1),
                )
            )
    backend.create_disposable_project(
        master_mlt_path,
        profile=ShotcutProfile(width=timeline.width, height=timeline.height, fps_num=timeline.fps, fps_den=1),
        clips=clips,
        tracks=tracks,
        overwrite=True,
    )
    backend.validate_project(master_mlt_path)


def _write_master_edit_plan_json(path: Path, *, project_id: str, project_name: str, items: list[dict[str, Any]]) -> None:
    payload = {
        "schema_version": "1.0",
        "document_type": "master_edit_plan",
        "project_id": project_id,
        "project_name": project_name,
        "items": [
            {
                "timeline_index": item["timeline_index"],
                "asset_id": item["asset_id"],
                "asset_type": item["asset_type"],
                "source_file_name": item["source_file_name"],
                "master_start": item["master_start"],
                "master_end": item["master_end"],
                "source_in": item["source_in"],
                "source_out": item["source_out"],
                "duration_ms": item["duration_ms"],
                "has_audio": item["has_audio"],
            }
            for item in items
        ],
    }
    json_dump(path, payload)


def _write_master_edit_plan_csv(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "timeline_index",
                "asset_id",
                "asset_type",
                "source_file_name",
                "master_start",
                "master_end",
                "source_in",
                "source_out",
                "duration_ms",
                "has_audio",
            ],
        )
        writer.writeheader()
        for item in items:
            writer.writerow(
                {
                    "timeline_index": item["timeline_index"],
                    "asset_id": item["asset_id"],
                    "asset_type": item["asset_type"],
                    "source_file_name": item["source_file_name"],
                    "master_start": item["master_start"],
                    "master_end": item["master_end"],
                    "source_in": item["source_in"],
                    "source_out": item["source_out"],
                    "duration_ms": item["duration_ms"],
                    "has_audio": item["has_audio"],
                }
            )


def _gemini_prompt(project_name: str) -> str:
    safe_name = _owner_safe_name(project_name)
    return f"""# Gemini Audio Transcription Prompt

Return exactly one UTF-8 JSON file named:

`{safe_name}_MASTER_AUDIO_TRANSCRIPT.json`

Use timeline timestamps in `HH:MM:SS.mmm`.

Capture these event types when present:
- speech
- overlapping speech
- whisper/quiet speech
- laughter
- applause
- exclamations
- cough
- footsteps
- clothes rustle
- camera shutter
- bottle opening
- drink pouring
- glassware
- wind
- water/waves
- boats
- vehicles
- birds
- crowd
- background music
- music start/end
- silence
- clipping/distortion
- noise covering speech

Each event must contain:
- start_time
- end_time
- event_type
- speaker
- original_text
- normalized_text
- description
- emotion
- confidence
- intensity
- foreground_or_background
- possible_hook
- possible_edit_use
"""


def _master_readme(project_name: str) -> str:
    return (
        f"{project_name} master package\n\n"
        "Workflow:\n"
        "1. Open the MLT in Shotcut if needed.\n"
        "2. Send MASTER_AUDIO.mp3 to Gemini with the prompt file.\n"
        "3. Save the returned JSON into TRANSCRIPT_IMPORT.\n"
        "4. Import the transcript in AI Handoff Builder.\n"
        "5. Only then create the final ANALYSIS_HANDOFF.zip.\n"
    )


def _master_start_here(project_name: str) -> str:
    return (
        f"# START HERE - {project_name} MASTER PACKAGE\n\n"
        "This folder is the intermediate owner workflow package.\n\n"
        "Read order:\n"
        "1. MASTER_TIMELINE_MAP.json\n"
        "2. MASTER_EDIT_PLAN.json / .csv\n"
        "3. GEMINI prompt\n"
        "4. import the returned transcript JSON back into AI Handoff Builder\n"
    )


def _master_project_brief(project_id: str, project_name: str, timeline: MasterTimelineBuild) -> str:
    return (
        f"# Project Brief\n\n"
        f"- Project ID: `{project_id}`\n"
        f"- Project Name: `{project_name}`\n"
        f"- Timeline items: `{len(timeline.items)}`\n"
        f"- Videos: `{timeline.video_count}`\n"
        f"- Photos: `{timeline.photo_count}`\n"
        f"- Master timeline duration: `{timeline.total_duration_ms} ms`\n"
    )


def _master_output_contract(project_name: str) -> str:
    safe_name = _owner_safe_name(project_name)
    return (
        "# Output Contract\n\n"
        "Gemini must return exactly one JSON transcript file named:\n\n"
        f"`{safe_name}_MASTER_AUDIO_TRANSCRIPT.json`\n\n"
        "The local app will validate timestamps and will not create the final ANALYSIS_HANDOFF.zip until the transcript passes validation.\n"
    )


def _write_master_handoff_manifest(
    path: Path,
    *,
    project_id: str,
    project_name: str,
    master_dir: Path,
    timeline: MasterTimelineBuild,
) -> None:
    payload = {
        "schema_version": "1.0",
        "package_type": "analysis_handoff",
        "project_id": project_id,
        "project_name": project_name,
        "workflow_stage": "master_package_ready",
        "master_package_dir": str(master_dir),
        "timeline_item_count": len(timeline.items),
        "video_count": timeline.video_count,
        "photo_count": timeline.photo_count,
        "content_hash": "0" * 64,
    }
    payload["content_hash"] = compute_content_hash(payload, self_hash_field="content_hash")
    json_dump(path, payload)


def _probe_audio(ffmpeg_tools: FFmpegTools, audio_path: Path) -> dict[str, Any]:
    payload = json.loads(
        run_command(
            [
                ffmpeg_tools.ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(audio_path),
            ],
            cancel_event=ffmpeg_tools.cancel_event,
        ).stdout
        or "{}"
    )
    audio_stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "audio"), {})
    return {
        "duration_seconds": float(audio_stream.get("duration") or payload.get("format", {}).get("duration") or 0.0),
        "sample_rate": int(audio_stream.get("sample_rate") or 0) or None,
        "channels": int(audio_stream.get("channels") or 0) or None,
    }


def _create_backend(settings: ShotcutAppSettings, *, allowed_roots: tuple[Path, ...]) -> ShotcutMcpBackend:
    runtime = settings.runtime_path()
    server_script = settings.server_script_path()
    if runtime is None or server_script is None:
        raise UnsafePackageError("Shotcut settings are incomplete. Choose runtime folder and MCP script first.")
    return ShotcutMcpBackend(
        ShotcutBackendPaths(
            server_script=server_script.resolve(),
            allowed_roots=tuple(path.resolve() for path in allowed_roots),
            shotcut_path=(runtime / "shotcut.exe").resolve(),
            melt_path=(runtime / "melt.exe").resolve(),
            ffmpeg_path=(runtime / "ffmpeg.exe").resolve(),
            ffprobe_path=(runtime / "ffprobe.exe").resolve(),
        ),
    )


def _wait_for_render(backend: ShotcutMcpBackend, job_id: str, *, timeout_seconds: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_status: dict[str, Any] = {"job_id": job_id, "status": "unknown"}
    while time.time() < deadline:
        last_status = backend.render_status(job_id)
        if str(last_status.get("status")) in {"completed", "failed", "cancelled"}:
            return last_status
        time.sleep(1.0)
    raise UnsafePackageError(f"Visual master render did not reach a terminal state before timeout for job {job_id}.")


def _owner_safe_name(name: str) -> str:
    return ("".join("_" if ch in '<>:\"/\\\\|?*' else ch for ch in name).rstrip(" .") or "PROJECT").strip()


def _allocate_versioned_mlt_name(master_dir: Path, safe_name: str) -> str:
    prefix = f"V"
    suffix = f"_{safe_name}_MASTER_ALL_MEDIA.mlt"
    existing = []
    for candidate in master_dir.glob(f"V*_{safe_name}_MASTER_ALL_MEDIA.mlt"):
        stem = candidate.name
        try:
            number = int(stem.split("_", 1)[0][1:])
            existing.append(number)
        except Exception:
            continue
    next_number = max(existing, default=0) + 1
    return f"{prefix}{next_number}_{safe_name}_MASTER_ALL_MEDIA.mlt"


def _ms_to_tc(value_ms: int) -> str:
    total_ms = max(0, int(value_ms))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _tc_to_ms(tc: str) -> int:
    hours, minutes, rest = tc.split(":")
    seconds, millis = rest.split(".")
    return ((int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000) + int(millis)
