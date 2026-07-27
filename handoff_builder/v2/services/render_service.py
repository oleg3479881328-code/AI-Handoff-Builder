from __future__ import annotations

import json
import threading
from pathlib import Path

from handoff_builder.ffmpeg_tools import FFmpegError

from ..common import utc_now_iso
from ..errors import InvalidQueueTransitionError, UnsafePackageError
from ..plans.semantic import (
    load_and_validate_edit_plan_3,
    load_and_validate_local_photo_plan,
    load_and_validate_preview_plan,
)
from ..qc.inspect import inspect_preview_output
from ..render.compiler import compile_local_photo_render_plan, compile_preview_render_plan
from ..render.ffmpeg_backend import FFmpegBackend
from ..timeline.compiler import compile_normalized_timeline
from ..storage import connect_workspace_db
from ..storage.repositories import SqliteRenderQueueRepository, WorkspaceRepository


def render_next_pending_job(
    workspace: Path,
    *,
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    project_root = workspace.resolve()
    project_id = json.loads((project_root / "project.json").read_text(encoding="utf-8"))["project_id"]
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        queue_repo = SqliteRenderQueueRepository(connection)
        claimed = queue_repo.claim_next_pending_job(project_id)
        if claimed is None:
            return {"status": "no_pending_jobs", "project_id": project_id}
        return _process_job_row(
            project_root,
            claimed["render_job_id"],
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            cancel_event=cancel_event,
        )
    finally:
        connection.close()


def render_job(
    workspace: Path,
    render_job_id: str,
    *,
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    project_root = workspace.resolve()
    return _process_job_row(
        project_root,
        render_job_id,
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        cancel_event=cancel_event,
    )


def _process_job_row(
    project_root: Path,
    render_job_id: str,
    *,
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
    cancel_event: threading.Event | None = None,
) -> dict:
    backend = FFmpegBackend(
        project_root=Path(__file__).resolve().parents[3],
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        cancel_event=cancel_event,
    )
    connection = connect_workspace_db(project_root / "project.sqlite")
    workspace_repo = WorkspaceRepository(connection)
    queue_repo = SqliteRenderQueueRepository(connection)
    job = queue_repo.get_by_id(render_job_id)
    if job["status"] == "completed":
        render_output = queue_repo.get_render_output(render_job_id)
        return {
            "job_id": render_job_id,
            "status": "completed",
            "already_completed": True,
            "output_directory": str(Path(render_output["report_path"]).parent),
            "report_path": render_output["report_path"],
        }
    if job["status"] == "pending":
        queue_repo.mark_running(render_job_id)
        connection.commit()
        job = queue_repo.get_by_id(render_job_id)
    elif job["status"] != "running":
        raise InvalidQueueTransitionError(f"Job cannot be rendered from status {job['status']}")

    plan_row = workspace_repo.get_plan(job["edit_plan_id"])
    package_row = workspace_repo.connection.execute(
        "SELECT * FROM ai_packages WHERE package_id = ?",
        (job["package_id"],),
    ).fetchone()
    if package_row is None:
        raise UnsafePackageError(f"Missing package row for {job['package_id']}")
    report_row = queue_repo.get_render_output(render_job_id)
    report_path = Path(report_row["report_path"])
    output_dir = report_path.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    reel_path = output_dir / "reel.mp4"
    render_plan_path = output_dir / "render_plan.json"
    ffmpeg_command_path = output_dir / "ffmpeg_command.json"
    first_frame_path = output_dir / "first_frame.jpg"

    try:
        plan_payload = json.loads(Path(plan_row["plan_path"]).read_text(encoding="utf-8"))
        plan_schema_version = str(plan_payload["schema_version"])
        if plan_schema_version == "3.0":
            # 3.0 uses Package Compiler → Normalized Timeline path
            validated = load_and_validate_edit_plan_3(
                Path(plan_row["plan_path"]),
                Path(package_row["extracted_root"]),
                backend,
            )
            # Compile Normalized Timeline (renderer-agnostic)
            from ..assets import load_active_local_registry, resolve_plan_assets_against_registry
            registry_payload = load_active_local_registry(project_root)
            resolution_report = resolve_plan_assets_against_registry(
                list(plan_payload["assets"]),
                registry_payload,
                require_declared_integrity=True,
            )
            normalized_timeline = compile_normalized_timeline(
                plan_payload,
                resolution_report["assets"],
                fps_num=validated.fps_num,
                fps_den=validated.fps_den,
            )
            # Write Normalized Timeline to output directory
            normalized_timeline_path = output_dir / "normalized_timeline.json"
            normalized_timeline_path.write_text(
                json.dumps(normalized_timeline.payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            # For now, fall through to preview render for FFmpeg-based preview
            validated = load_and_validate_preview_plan(
                Path(plan_row["plan_path"]),
                Path(package_row["extracted_root"]),
                backend,
            )
            compiled = compile_preview_render_plan(validated, ffmpeg_path=backend.ffmpeg, output_path=reel_path)
        elif plan_schema_version in {"2.0", "2.1"}:
            validated = load_and_validate_local_photo_plan(
                Path(plan_row["plan_path"]),
                project_root,
            )
            compiled = compile_local_photo_render_plan(validated, ffmpeg_path=backend.ffmpeg, output_path=reel_path)
        else:
            validated = load_and_validate_preview_plan(
                Path(plan_row["plan_path"]),
                Path(package_row["extracted_root"]),
                backend,
            )
            compiled = compile_preview_render_plan(validated, ffmpeg_path=backend.ffmpeg, output_path=reel_path)
        render_plan_path.write_text(json.dumps(compiled.render_plan, ensure_ascii=False, indent=2), encoding="utf-8")
        ffmpeg_command_path.write_text(
            json.dumps(compiled.command_metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        workspace_repo.add_event(
            project_id=job["project_id"],
            package_id=job["package_id"],
            render_job_id=render_job_id,
            event_type="render_started",
            payload={"render_job_id": render_job_id, "started_at": utc_now_iso()},
        )
        connection.commit()

        exit_code, _stdout, stderr = backend.run_ffmpeg(compiled.ffmpeg_args)
        if exit_code != 0:
            raise UnsafePackageError(f"FFmpeg preview render failed with exit code {exit_code}.\n{stderr[-4000:]}")

        qc = inspect_preview_output(
            backend,
            reel_path,
            expected_duration_ms=validated.planned_duration_ms,
            expected_width=compiled.render_plan["output"]["width"],
            expected_height=compiled.render_plan["output"]["height"],
            expected_fps=float(compiled.render_plan["output"]["fps"]),
            first_frame_path=first_frame_path,
        )
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report.update(
            {
                "status": "completed",
                "renderer_status": "completed",
                "ffmpeg_exit_code": 0,
                "qc_checks": list(qc.checks),
                "warnings": sorted(set(report.get("warnings", [])) | set(qc.warnings)),
                "outputs": [
                    {
                        "path": str(reel_path),
                        "sha256": qc.output_sha256,
                        "duration_seconds": qc.duration_seconds,
                        "width": qc.width,
                        "height": qc.height,
                        "fps": qc.fps,
                        "audio_present": 1 if qc.audio_present else 0,
                    }
                ],
                "updated_at": utc_now_iso(),
            }
        )
        if plan_schema_version in {"2.0", "2.1"}:
            report["warnings"] = sorted(set(report.get("warnings", [])) | {"local_originals_resolved"})
        connection.execute(
            "UPDATE render_outputs SET renderer_status = ? WHERE render_job_id = ?",
            ("completed", render_job_id),
        )
        queue_repo.mark_completed(render_job_id)
        workspace_repo.add_event(
            project_id=job["project_id"],
            package_id=job["package_id"],
            render_job_id=render_job_id,
            event_type="render_completed",
            payload={"render_job_id": render_job_id, "output_path": str(reel_path)},
        )
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        connection.commit()
        return {
            "job_id": render_job_id,
            "status": "completed",
            "output_directory": str(output_dir),
            "report_path": str(report_path),
        }
    except Exception as exc:
        failed_stage = _classify_failure_stage(exc)
        error_code = _classify_error_code(exc)
        cancelled = error_code == "cancelled"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report.update(
            {
                "status": "cancelled" if cancelled else "failed",
                "renderer_status": "cancelled" if cancelled else "failed",
                "failed_stage": failed_stage,
                "error_code": error_code,
                "error_message": str(exc),
                "updated_at": utc_now_iso(),
            }
        )
        if "FFmpeg preview render failed" in str(exc):
            report["ffmpeg_stderr_tail"] = str(exc)[-4000:]
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            if cancelled:
                queue_repo.mark_cancelled(render_job_id)
            else:
                queue_repo.mark_failed(
                    render_job_id,
                    failed_stage=failed_stage,
                    error_code=error_code,
                    error_message=str(exc),
                )
            connection.execute(
                "UPDATE render_outputs SET renderer_status = ? WHERE render_job_id = ?",
                ("cancelled" if cancelled else "failed", render_job_id),
            )
            workspace_repo.add_event(
                project_id=job["project_id"],
                package_id=job["package_id"],
                render_job_id=render_job_id,
                event_type="render_cancelled" if cancelled else "render_failed",
                payload={
                    "render_job_id": render_job_id,
                    "error_code": error_code,
                    "failed_stage": failed_stage,
                },
            )
            connection.commit()
        finally:
            connection.close()
        raise
    finally:
        if connection:
            try:
                connection.close()
            except Exception:
                pass


def _classify_failure_stage(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, FFmpegError) and "canceled by the user" in message:
        return "cancel_requested"
    if "FFmpeg preview render failed" in message:
        return "ffmpeg_execute"
    if "duration" in message or "Unsupported operation" in message or "Forbidden" in message:
        return "semantic_validation"
    return "compile_or_qc"


def _classify_error_code(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, FFmpegError) and "canceled by the user" in message:
        return "cancelled"
    if "Unsupported operation" in message or "Forbidden" in message:
        return "unsupported_operation"
    if (
        "Asset file does not exist" in message
        or "unknown asset_id" in message
        or "Asset resolution failed: missing asset_id" in message
        or "Asset resolution failed: source file missing" in message
    ):
        return "missing_source"
    if "Asset resolution failed: ambiguous asset_id" in message:
        return "ambiguous_source"
    if "Asset resolution failed: checksum mismatch" in message:
        return "checksum_mismatch"
    if "Asset resolution failed: size mismatch" in message:
        return "size_mismatch"
    if "Asset resolution failed: unreadable" in message:
        return "unreadable_source"
    if "duration" in message or "source_out_ms" in message:
        return "invalid_trim_range"
    if "FFmpeg preview render failed" in message:
        return "ffmpeg_failed"
    return "render_worker_error"
