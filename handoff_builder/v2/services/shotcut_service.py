from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..common import utc_now_iso
from ..errors import InvalidQueueTransitionError, UnsafePackageError
from ..plans.semantic import (
    ValidatedPreviewPlan,
    load_and_validate_edit_plan_3,
    load_and_validate_preview_plan,
)
from ..render.ffmpeg_backend import FFmpegBackend
from ..render.shotcut_backend import (
    ShotcutBackendError,
    ShotcutBackendPaths,
    ShotcutClipIntent,
    ShotcutMcpBackend,
    ShotcutProfile,
    ShotcutTrackIntent,
)
from ..shotcut_settings import ShotcutAppSettings
from ..storage import connect_workspace_db
from ..storage.repositories import SqliteRenderQueueRepository, WorkspaceRepository
from ..timeline.compiler import compile_normalized_timeline
from ...utils import file_sha256


ProgressCallback = Callable[[dict], None]


@dataclass(frozen=True, slots=True)
class ShotcutServicePaths:
    output_dir: Path
    shotcut_dir: Path
    project_path: Path
    preview_path: Path
    contact_sheet_path: Path
    runtime_status_path: Path
    build_summary_path: Path
    render_summary_path: Path
    first_frame_path: Path
    reel_path: Path


def describe_shotcut_runtime(
    settings: ShotcutAppSettings,
    *,
    workspace_root: Path | None = None,
) -> dict:
    normalized = settings.with_defaults()
    runtime_dir = normalized.runtime_path()
    server_script = normalized.server_script_path()
    if runtime_dir is None or server_script is None:
        missing = []
        if runtime_dir is None:
            missing.append("runtime folder")
        if server_script is None:
            missing.append("MCP server script")
        return {
            "ready": False,
            "status": f"Shotcut setup incomplete: choose {' and '.join(missing)}.",
            "settings": {
                "runtime_dir": normalized.runtime_dir,
                "server_script": normalized.server_script,
            },
        }
    backend = _create_backend(
        normalized,
        allowed_roots=_doctor_allowed_roots(workspace_root, runtime_dir),
    )
    status = backend.status()
    doctor = backend.doctor()
    payload = {
        "ready": bool(status.get("ready")) and bool(doctor.get("compatible")),
        "status": status,
        "doctor": doctor,
        "settings": {
            "runtime_dir": str(runtime_dir),
            "server_script": str(server_script),
        },
    }
    if workspace_root is not None:
        report_path = workspace_root / "shotcut_runtime_status.json"
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build_editable_shotcut_project(
    workspace: Path,
    render_job_id: str,
    *,
    settings: ShotcutAppSettings,
) -> dict:
    workspace_root = workspace.resolve()
    job_context = _load_job_context(workspace_root, render_job_id)
    backend = _create_backend(
        settings.with_defaults(),
        allowed_roots=_build_allowed_roots(workspace_root, job_context.package_root, job_context.paths.output_dir),
    )
    ffmpeg_backend = FFmpegBackend(
        project_root=Path(__file__).resolve().parents[3],
        ffmpeg_path=str((settings.runtime_path() / "ffmpeg.exe").resolve()) if settings.runtime_path() else None,
        ffprobe_path=str((settings.runtime_path() / "ffprobe.exe").resolve()) if settings.runtime_path() else None,
    )
    plan_payload = json.loads(job_context.plan_path.read_text(encoding="utf-8"))
    if str(plan_payload.get("schema_version")) == "3.0":
        validated = load_and_validate_edit_plan_3(job_context.plan_path, workspace_root, ffmpeg_backend)
        resolved_assets = _resolved_assets_from_validated(validated)
        normalized = compile_normalized_timeline(
            validated.payload,
            resolved_assets,
            source_package_content_hash=str(plan_payload["handoff_content_hash"]),
        )
        build_summary = build_shotcut_project_from_timeline(
            normalized.payload,
            backend=backend,
            artifacts=job_context.paths,
            project_name=str(plan_payload.get("project_name") or plan_payload["project_id"]),
        )
    else:
        validated = load_and_validate_preview_plan(job_context.plan_path, job_context.package_root, ffmpeg_backend)
        build_summary = build_shotcut_project_from_validated_plan(
            validated,
            backend=backend,
            artifacts=job_context.paths,
        )
    _update_report_status(
        job_context.report_path,
        status="pending",
        renderer_status="shotcut_editable_ready",
        warnings=["shotcut_editable_project_ready"],
    )
    job_context.paths.runtime_status_path.write_text(
        json.dumps(describe_shotcut_runtime(settings, workspace_root=workspace_root), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    job_context.paths.build_summary_path.write_text(json.dumps(build_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return show_render_job(workspace_root, render_job_id)


def render_shotcut_job(
    workspace: Path,
    render_job_id: str,
    *,
    settings: ShotcutAppSettings,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    workspace_root = workspace.resolve()
    job_context = _load_job_context(workspace_root, render_job_id)
    backend = _create_backend(
        settings.with_defaults(),
        allowed_roots=_build_allowed_roots(workspace_root, job_context.package_root, job_context.paths.output_dir),
    )
    ffmpeg_backend = FFmpegBackend(
        project_root=Path(__file__).resolve().parents[3],
        ffmpeg_path=str((settings.runtime_path() / "ffmpeg.exe").resolve()) if settings.runtime_path() else None,
        ffprobe_path=str((settings.runtime_path() / "ffprobe.exe").resolve()) if settings.runtime_path() else None,
    )
    queue_controlled = _mark_job_running(workspace_root, render_job_id)
    try:
        if not job_context.paths.project_path.exists():
            plan_payload = json.loads(job_context.plan_path.read_text(encoding="utf-8"))
            if str(plan_payload.get("schema_version")) == "3.0":
                validated = load_and_validate_edit_plan_3(job_context.plan_path, workspace_root, ffmpeg_backend)
                normalized = compile_normalized_timeline(
                    validated.payload,
                    _resolved_assets_from_validated(validated),
                    source_package_content_hash=str(plan_payload["handoff_content_hash"]),
                )
                build_summary = build_shotcut_project_from_timeline(
                    normalized.payload,
                    backend=backend,
                    artifacts=job_context.paths,
                    project_name=str(plan_payload.get("project_name") or plan_payload["project_id"]),
                )
            else:
                validated = load_and_validate_preview_plan(job_context.plan_path, job_context.package_root, ffmpeg_backend)
                build_summary = build_shotcut_project_from_validated_plan(
                    validated,
                    backend=backend,
                    artifacts=job_context.paths,
                )
            job_context.paths.build_summary_path.write_text(
                json.dumps(build_summary, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

        render_summary = render_built_shotcut_project(
            backend=backend,
            ffmpeg_backend=ffmpeg_backend,
            artifacts=job_context.paths,
            cancel_event=cancel_event,
            progress_callback=progress_callback,
        )
        _update_report_completed(job_context.report_path, render_summary)
        _mark_job_completed(
            workspace_root,
            render_job_id,
            output_path=job_context.paths.reel_path,
            queue_controlled=queue_controlled,
        )
        job_context.paths.render_summary_path.write_text(
            json.dumps(render_summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return show_render_job(workspace_root, render_job_id)
    except Exception as exc:
        cancelled = isinstance(exc, ShotcutBackendError) and "cancel" in str(exc).lower()
        _update_report_failed(
            job_context.report_path,
            error_message=str(exc),
            failed_stage="shotcut_render",
            error_code="cancelled" if cancelled else "shotcut_render_failed",
            renderer_status="shotcut_cancelled" if cancelled else "shotcut_failed",
            status="cancelled" if cancelled else "failed",
        )
        _mark_job_failed(
            workspace_root,
            render_job_id,
            str(exc),
            cancelled=cancelled,
            queue_controlled=queue_controlled,
        )
        raise


def open_shotcut_project(
    workspace: Path,
    render_job_id: str,
    *,
    settings: ShotcutAppSettings,
) -> dict:
    workspace_root = workspace.resolve()
    job_context = _load_job_context(workspace_root, render_job_id)
    if not job_context.paths.project_path.exists():
        raise UnsafePackageError("Editable Shotcut project is missing. Build it first.")
    backend = _create_backend(
        settings.with_defaults(),
        allowed_roots=_build_allowed_roots(workspace_root, job_context.package_root, job_context.paths.output_dir),
    )
    result = backend.open_in_shotcut(job_context.paths.project_path)
    job_context.paths.runtime_status_path.write_text(
        json.dumps({"opened": result, "updated_at": utc_now_iso()}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return result


def build_shotcut_project_from_validated_plan(
    validated: ValidatedPreviewPlan,
    *,
    backend: ShotcutMcpBackend,
    artifacts: ShotcutServicePaths,
) -> dict:
    artifacts.shotcut_dir.mkdir(parents=True, exist_ok=True)
    probe_cache: dict[str, dict] = {}
    first_asset = validated.assets[validated.operations[0].asset_id]
    first_probe = _probe_once(backend, probe_cache, first_asset.path)
    first_video = _primary_video_stream(first_probe)
    fps = _rounded_fps(first_probe)
    has_audio = any(validated.assets[operation.asset_id].has_audio for operation in validated.operations)
    tracks = [ShotcutTrackIntent(kind="audio", name="A1")] if has_audio else []
    clips: list[ShotcutClipIntent] = []
    cursor_frames = 0
    sequence_summary: list[dict] = []
    for operation in validated.operations:
        asset = validated.assets[operation.asset_id]
        probe = _probe_once(backend, probe_cache, asset.path)
        asset_fps = _rounded_fps(probe)
        in_frame = round(operation.source_in_ms * asset_fps / 1000)
        out_frame = max(in_frame, round(operation.source_out_ms * asset_fps / 1000) - 1)
        duration_frames = max(1, round(operation.duration_ms * fps / 1000))
        clips.append(
            ShotcutClipIntent(
                media_path=asset.path,
                track="V1",
                position_frame=cursor_frames,
                in_frame=in_frame,
                out_frame=out_frame,
            )
        )
        if asset.has_audio:
            clips.append(
                ShotcutClipIntent(
                    media_path=asset.path,
                    track="A1",
                    position_frame=cursor_frames,
                    in_frame=in_frame,
                    out_frame=out_frame,
                )
            )
        sequence_summary.append(
            {
                "asset_id": asset.asset_id,
                "track": "V1",
                "position_frame": cursor_frames,
                "in_frame": in_frame,
                "out_frame": out_frame,
                "duration_frames": duration_frames,
                "has_audio": asset.has_audio,
            }
        )
        cursor_frames += duration_frames
    create_result = backend.create_disposable_project(
        artifacts.project_path,
        profile=ShotcutProfile(
            width=int(first_video["width"]),
            height=int(first_video["height"]),
            fps_num=fps,
            fps_den=1,
        ),
        clips=clips,
        tracks=tracks,
        overwrite=True,
    )
    inspect_result = backend.inspect_project(artifacts.project_path)
    validate_result = backend.validate_project(artifacts.project_path)
    return {
        "project_path": str(artifacts.project_path),
        "created_at": utc_now_iso(),
        "fps": fps,
        "width": int(first_video["width"]),
        "height": int(first_video["height"]),
        "create_result": create_result,
        "inspect_result": inspect_result,
        "validate_result": validate_result,
        "clip_summary": sequence_summary,
    }


def build_shotcut_project_from_timeline(
    timeline: dict,
    *,
    backend: ShotcutMcpBackend,
    artifacts: ShotcutServicePaths,
    project_name: str,
) -> dict:
    artifacts.shotcut_dir.mkdir(parents=True, exist_ok=True)
    clips: list[ShotcutClipIntent] = []
    tracks: list[ShotcutTrackIntent] = []
    probe_cache: dict[str, dict] = {}
    visual_items = sorted(timeline.get("visual_items", []), key=lambda item: (int(item["timeline_start_frame"]), str(item["item_id"])))
    if not visual_items:
        raise UnsafePackageError("Normalized Timeline contains no visual items.")

    first_path = Path(str(visual_items[0]["resolved_source_path"]))
    first_probe = _probe_once(backend, probe_cache, first_path)
    first_video = _primary_video_stream(first_probe)
    fps_num = int(timeline["timebase"]["fps_num"])
    fps_den = int(timeline["timebase"]["fps_den"])

    declared_track_ids = {str(item["track_id"]) for item in visual_items}
    declared_track_ids.update(str(item["track_id"]) for item in timeline.get("audio_items", []))
    for track in timeline.get("tracks", []):
        track_id = str(track["track_id"])
        if track_id not in declared_track_ids:
            continue
        kind = "audio" if str(track["track_type"]) == "audio" else "video"
        tracks.append(ShotcutTrackIntent(kind=kind, name=track_id))

    clip_summary: list[dict] = []
    for item in visual_items:
        media_path = Path(str(item["resolved_source_path"]))
        media_type = str(item["media_type"])
        if media_type == "video":
            probe = _probe_once(backend, probe_cache, media_path)
            asset_fps = _rounded_fps(probe)
            in_frame = round(int(item["source_in_us"]) * asset_fps / 1_000_000)
            out_frame = max(in_frame, round(int(item["source_out_us"]) * asset_fps / 1_000_000) - 1)
        else:
            in_frame = None
            out_frame = None
        track_name = str(item["track_id"])
        clips.append(
            ShotcutClipIntent(
                media_path=media_path,
                track=track_name,
                position_frame=int(item["timeline_start_frame"]),
                in_frame=in_frame,
                out_frame=out_frame,
                caption=str(item["item_id"]),
            )
        )
        clip_summary.append(
            {
                "item_id": str(item["item_id"]),
                "track": track_name,
                "position_frame": int(item["timeline_start_frame"]),
                "duration_frames": int(item["duration_frames"]),
                "source_in_us": int(item["source_in_us"]),
                "source_out_us": int(item["source_out_us"]),
            }
        )
    for item in timeline.get("audio_items", []):
        media_path = Path(str(item["resolved_audio_path"]))
        clips.append(
            ShotcutClipIntent(
                media_path=media_path,
                track=str(item["track_id"]),
                position_frame=int(item["timeline_start_frame"]),
                in_frame=round(int(item.get("source_in_us", 0)) * fps_num / fps_den / 1_000_000),
                out_frame=max(
                    round(int(item.get("source_in_us", 0)) * fps_num / fps_den / 1_000_000),
                    round(int(item.get("source_out_us", 0)) * fps_num / fps_den / 1_000_000) - 1,
                ) if int(item.get("source_out_us", 0)) > 0 else None,
                caption=str(item["item_id"]),
            )
        )
    create_result = backend.create_disposable_project(
        artifacts.project_path,
        profile=ShotcutProfile(
            width=int(timeline["canvas"]["width"]),
            height=int(timeline["canvas"]["height"]),
            fps_num=fps_num,
            fps_den=fps_den,
        ),
        clips=clips,
        tracks=tracks,
        overwrite=True,
    )
    inspect_result = backend.inspect_project(artifacts.project_path)
    validate_result = backend.validate_project(artifacts.project_path)
    return {
        "project_name": project_name,
        "project_path": str(artifacts.project_path),
        "created_at": utc_now_iso(),
        "fps": fps_num / fps_den,
        "width": int(timeline["canvas"]["width"]),
        "height": int(timeline["canvas"]["height"]),
        "create_result": create_result,
        "inspect_result": inspect_result,
        "validate_result": validate_result,
        "clip_summary": clip_summary,
        "normalized_timeline_hash": str(timeline["normalized_timeline_hash"]),
        "track_count": len(timeline.get("tracks", [])),
        "target_mlt_filename": f"{project_name}.mlt",
    }


def render_built_shotcut_project(
    *,
    backend: ShotcutMcpBackend,
    ffmpeg_backend: FFmpegBackend,
    artifacts: ShotcutServicePaths,
    cancel_event: threading.Event | None = None,
    progress_callback: ProgressCallback | None = None,
) -> dict:
    if not artifacts.project_path.exists():
        raise UnsafePackageError("Editable Shotcut project is missing.")
    artifacts.shotcut_dir.mkdir(parents=True, exist_ok=True)
    preview = backend.render_preview(artifacts.project_path, artifacts.preview_path, frame=0, overwrite=True)
    contact_sheet = backend.render_contact_sheet(
        artifacts.project_path,
        artifacts.contact_sheet_path,
        sample_count=6,
        columns=3,
        cell_width=320,
        overwrite=True,
    )
    job = backend.start_render(
        artifacts.project_path,
        artifacts.reel_path,
        preset="h264-web",
        overwrite=True,
    )
    cancel_requested = False
    final_status: dict | None = None
    while True:
        if cancel_event is not None and cancel_event.is_set() and not cancel_requested:
            backend.cancel_render(job.job_id)
            cancel_requested = True
        final_status = backend.render_status(job.job_id)
        if progress_callback is not None:
            progress_callback(final_status)
        if final_status.get("status") != "running":
            break
        time.sleep(1.0)
    if final_status is None:
        raise ShotcutBackendError("Shotcut render returned no status.")
    if final_status.get("status") == "cancelled":
        raise ShotcutBackendError("Shotcut render cancelled.")
    if final_status.get("status") != "completed":
        raise ShotcutBackendError(
            final_status.get("status_note")
            or final_status.get("log_tail")
            or f"Shotcut render did not complete successfully: {final_status.get('status')}"
        )
    if not artifacts.reel_path.exists():
        raise UnsafePackageError("Shotcut render reported success but reel.mp4 is missing.")
    probe = backend.verify_rendered_media(artifacts.reel_path)
    if not _probe_has_video(probe):
        raise UnsafePackageError("Shotcut render output is missing a decodable video stream.")
    ffmpeg_backend.extract_first_frame(artifacts.reel_path, artifacts.first_frame_path)
    return {
        "render_preview": preview,
        "render_contact_sheet": contact_sheet,
        "render_status": final_status,
        "probe": probe,
    }


def show_render_job(workspace: Path, render_job_id: str) -> dict:
    from .query_service import show_render_job as query_show_render_job

    return query_show_render_job(workspace, render_job_id)


@dataclass(frozen=True, slots=True)
class _JobContext:
    workspace_root: Path
    package_root: Path
    plan_path: Path
    report_path: Path
    project_id: str
    package_id: str
    paths: ShotcutServicePaths


def _load_job_context(workspace_root: Path, render_job_id: str) -> _JobContext:
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        queue_repo = SqliteRenderQueueRepository(connection)
        workspace_repo = WorkspaceRepository(connection)
        job = queue_repo.get_by_id(render_job_id)
        plan = workspace_repo.get_plan(job["edit_plan_id"])
        package_row = connection.execute(
            "SELECT * FROM ai_packages WHERE package_id = ?",
            (job["package_id"],),
        ).fetchone()
        if package_row is None:
            raise UnsafePackageError(f"Missing package row for {job['package_id']}")
        report_row = queue_repo.get_render_output(render_job_id)
        report_path = Path(report_row["report_path"])
        plan_payload = json.loads(Path(plan["plan_path"]).read_text(encoding="utf-8"))
        project_name = str(plan_payload.get("project_name") or plan["project_id"])
        return _JobContext(
            workspace_root=workspace_root,
            package_root=Path(package_row["extracted_root"]),
            plan_path=Path(plan["plan_path"]),
            report_path=report_path,
            project_id=str(job["project_id"]),
            package_id=str(job["package_id"]),
            paths=_artifact_paths(report_path.parent, project_name),
        )
    finally:
        connection.close()


def _artifact_paths(output_dir: Path, project_name: str) -> ShotcutServicePaths:
    shotcut_dir = output_dir / "shotcut"
    safe_name = "".join("_" if ch in '<>:"/\\|?*' else ch for ch in project_name).strip() or "project"
    return ShotcutServicePaths(
        output_dir=output_dir,
        shotcut_dir=shotcut_dir,
        project_path=shotcut_dir / f"{safe_name}.mlt",
        preview_path=shotcut_dir / "preview.png",
        contact_sheet_path=shotcut_dir / "contact_sheet.png",
        runtime_status_path=shotcut_dir / "runtime_status.json",
        build_summary_path=shotcut_dir / "build_summary.json",
        render_summary_path=shotcut_dir / "render_summary.json",
        first_frame_path=output_dir / "first_frame.jpg",
        reel_path=output_dir / "reel.mp4",
    )


def _resolved_assets_from_validated(validated) -> list[dict]:
    assets: list[dict] = []
    for collection in (validated.assets, getattr(validated, "audio_assets", {})):
        for asset in collection.values():
            if asset.path is None:
                continue
            assets.append(
                {
                    "asset_id": asset.asset_id,
                    "source_path": str(asset.path),
                    "sha256": file_sha256(asset.path),
                    "size_bytes": asset.path.stat().st_size,
                }
            )
    return assets


def _build_allowed_roots(workspace_root: Path, package_root: Path, output_dir: Path) -> tuple[Path, ...]:
    roots = []
    for candidate in (workspace_root, package_root, output_dir):
        resolved = candidate.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def _doctor_allowed_roots(workspace_root: Path | None, runtime_dir: Path) -> tuple[Path, ...]:
    roots = [runtime_dir.resolve()]
    if workspace_root is not None:
        roots.append(workspace_root.resolve())
    return tuple(roots)


def _create_backend(settings: ShotcutAppSettings, *, allowed_roots: tuple[Path, ...]) -> ShotcutMcpBackend:
    runtime_dir = settings.runtime_path()
    server_script = settings.server_script_path()
    if runtime_dir is None or server_script is None:
        raise UnsafePackageError("Shotcut settings are incomplete. Choose runtime folder and MCP script first.")
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


def _probe_once(backend: ShotcutMcpBackend, cache: dict[str, dict], path: Path) -> dict:
    key = str(path.resolve())
    if key not in cache:
        cache[key] = backend.probe_media(path)
    return cache[key]


def _rounded_fps(probe: dict) -> int:
    video_stream = _primary_video_stream(probe)
    frame_rate = float(video_stream.get("frame_rate") or 30.0)
    return max(1, round(frame_rate))


def _probe_has_video(probe: dict) -> bool:
    streams = probe.get("streams") or []
    return any(item.get("type") == "video" for item in streams)


def _primary_video_stream(probe: dict) -> dict:
    streams = probe.get("streams") or []
    video_stream = next((item for item in streams if item.get("type") == "video"), None)
    if not isinstance(video_stream, dict):
        raise UnsafePackageError("Shotcut probe did not return a video stream.")
    return video_stream


def _update_report_status(report_path: Path, *, status: str, renderer_status: str, warnings: list[str] | None = None) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report["status"] = status
    report["renderer_status"] = renderer_status
    report["updated_at"] = utc_now_iso()
    if warnings:
        report["warnings"] = sorted(set(report.get("warnings", [])) | set(warnings))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_report_completed(report_path: Path, render_summary: dict) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    probe = render_summary["probe"]
    video_stream = next(item for item in probe.get("streams", []) if item.get("type") == "video")
    audio_present = 1 if any(item.get("type") == "audio" for item in probe.get("streams", [])) else 0
    output_path = Path(render_summary["render_status"]["output_path"]).resolve()
    report.update(
        {
            "status": "completed",
            "renderer_status": "completed",
            "updated_at": utc_now_iso(),
            "qc_checks": ["shotcut_project_built", "shotcut_preview_rendered", "shotcut_render_verified"],
            "warnings": sorted(set(report.get("warnings", [])) | {"shotcut_mcp_render"}),
            "outputs": [
                {
                    "path": str(output_path),
                    "sha256": file_sha256(output_path),
                    "duration_seconds": float(probe["duration_seconds"]),
                    "width": int(video_stream["width"]),
                    "height": int(video_stream["height"]),
                    "fps": float(video_stream["frame_rate"]),
                    "audio_present": audio_present,
                }
            ],
        }
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _update_report_failed(
    report_path: Path,
    *,
    error_message: str,
    failed_stage: str,
    error_code: str,
    renderer_status: str,
    status: str,
) -> None:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    report.update(
        {
            "status": status,
            "renderer_status": renderer_status,
            "updated_at": utc_now_iso(),
            "failed_stage": failed_stage,
            "error_code": error_code,
            "error_message": error_message,
        }
    )
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def _mark_job_running(workspace_root: Path, render_job_id: str) -> bool:
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        queue_repo = SqliteRenderQueueRepository(connection)
        job = queue_repo.get_by_id(render_job_id)
        if job["status"] == "pending":
            queue_repo.mark_running(render_job_id)
            connection.commit()
            return True
        if job["status"] == "running":
            return True
        if job["status"] in {"completed", "failed", "cancelled"}:
            return False
        if job["status"] != "running":
            raise InvalidQueueTransitionError(f"Job cannot be rendered from status {job['status']}")
        return True
    finally:
        connection.close()


def _mark_job_completed(
    workspace_root: Path,
    render_job_id: str,
    *,
    output_path: Path,
    queue_controlled: bool,
) -> None:
    if not queue_controlled:
        return
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        queue_repo = SqliteRenderQueueRepository(connection)
        workspace_repo = WorkspaceRepository(connection)
        job = queue_repo.get_by_id(render_job_id)
        queue_repo.mark_completed(render_job_id)
        workspace_repo.add_event(
            project_id=job["project_id"],
            package_id=job["package_id"],
            render_job_id=render_job_id,
            event_type="render_completed",
            payload={"render_job_id": render_job_id, "output_path": str(output_path)},
        )
        connection.execute(
            "UPDATE render_outputs SET renderer_status = ? WHERE render_job_id = ?",
            ("completed", render_job_id),
        )
        connection.commit()
    finally:
        connection.close()


def _mark_job_failed(
    workspace_root: Path,
    render_job_id: str,
    message: str,
    *,
    cancelled: bool,
    queue_controlled: bool,
) -> None:
    if not queue_controlled:
        return
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        queue_repo = SqliteRenderQueueRepository(connection)
        workspace_repo = WorkspaceRepository(connection)
        job = queue_repo.get_by_id(render_job_id)
        if cancelled:
            queue_repo.mark_cancelled(render_job_id)
            event_type = "render_cancelled"
            renderer_status = "cancelled"
        else:
            queue_repo.mark_failed(
                render_job_id,
                failed_stage="shotcut_render",
                error_code="shotcut_render_failed",
                error_message=message,
            )
            event_type = "render_failed"
            renderer_status = "failed"
        workspace_repo.add_event(
            project_id=job["project_id"],
            package_id=job["package_id"],
            render_job_id=render_job_id,
            event_type=event_type,
            payload={"render_job_id": render_job_id, "error_message": message},
        )
        connection.execute(
            "UPDATE render_outputs SET renderer_status = ? WHERE render_job_id = ?",
            (renderer_status, render_job_id),
        )
        connection.commit()
    finally:
        connection.close()
