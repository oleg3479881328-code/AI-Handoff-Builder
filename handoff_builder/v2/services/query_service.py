from __future__ import annotations

import json
from pathlib import Path

from ..storage import connect_workspace_db
from ..storage.repositories import SqliteRenderQueueRepository, WorkspaceRepository
from ..workspace import load_project_config


def list_plans(workspace: Path, *, project_id: str | None = None) -> list[dict]:
    project_root = workspace.resolve()
    config = load_project_config(project_root)
    target_project_id = project_id or str(config["project_id"])
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        repo = WorkspaceRepository(connection)
        rows = repo.list_plans(target_project_id)
        return [
            {
                "edit_plan_id": row.edit_plan_id,
                "project_id": row.project_id,
                "package_id": row.package_id,
                "handoff_id": row.handoff_id,
                "schema_version": row.schema_version,
                "plan_sha256": row.plan_sha256,
                "plan_hash": row.plan_hash,
                "plan_path": str(row.plan_path),
                "created_at": row.created_at,
                "plan_version": row.plan_version,
                "parent_plan_id": row.parent_plan_id,
                "patch_id": row.patch_id,
                "base_plan_hash": row.base_plan_hash,
            }
            for row in rows
        ]
    finally:
        connection.close()


def show_plan(workspace: Path, plan_id: str) -> dict:
    project_root = workspace.resolve()
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        repo = WorkspaceRepository(connection)
        row = repo.get_plan(plan_id)
        payload = json.loads(Path(row["plan_path"]).read_text(encoding="utf-8"))
        return {
            "metadata": {
                "edit_plan_id": row["edit_plan_id"],
                "project_id": row["project_id"],
                "package_id": row["package_id"],
                "handoff_id": row["handoff_id"],
                "schema_version": row["schema_version"],
                "plan_sha256": row["plan_sha256"],
                "plan_hash": row["plan_hash"],
                "plan_path": row["plan_path"],
                "created_at": row["created_at"],
                "plan_version": int(row["plan_version"] or 1),
                "parent_plan_id": row["parent_plan_id"],
                "patch_id": row["patch_id"],
                "base_plan_hash": row["base_plan_hash"],
            },
            "payload": payload,
        }
    finally:
        connection.close()


def list_render_jobs(workspace: Path, *, project_id: str | None = None) -> list[dict]:
    project_root = workspace.resolve()
    config = load_project_config(project_root)
    target_project_id = project_id or str(config["project_id"])
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        repo = SqliteRenderQueueRepository(connection)
        return [dict(row) for row in repo.list_by_project(target_project_id)]
    finally:
        connection.close()


def show_render_job(workspace: Path, render_job_id: str) -> dict:
    project_root = workspace.resolve()
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        queue_repo = SqliteRenderQueueRepository(connection)
        workspace_repo = WorkspaceRepository(connection)
        job = dict(queue_repo.get_by_id(render_job_id))
        report_row = dict(queue_repo.get_render_output(render_job_id))
        plan = dict(workspace_repo.get_plan(job["edit_plan_id"]))
        report_path = Path(report_row["report_path"])
        report_json = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        output_dir = report_path.parent
        ffmpeg_command_path = output_dir / "ffmpeg_command.json"
        first_frame_path = output_dir / "first_frame.jpg"
        reel_path = output_dir / "reel.mp4"
        return {
            "job": job,
            "plan": plan,
            "report": report_json,
            "report_path": str(report_path),
            "output_directory": str(output_dir),
            "ffmpeg_command_path": str(ffmpeg_command_path),
            "first_frame_path": str(first_frame_path),
            "reel_path": str(reel_path),
            "ffmpeg_command_exists": ffmpeg_command_path.exists(),
            "first_frame_exists": first_frame_path.exists(),
            "reel_exists": reel_path.exists(),
        }
    finally:
        connection.close()


def retry_render_job(workspace: Path, render_job_id: str) -> dict:
    project_root = workspace.resolve()
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        repo = SqliteRenderQueueRepository(connection)
        connection.execute("BEGIN")
        row = repo.retry_job(render_job_id)
        connection.commit()
        return dict(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def request_cancel_render_job(workspace: Path, render_job_id: str) -> dict:
    project_root = workspace.resolve()
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        repo = SqliteRenderQueueRepository(connection)
        connection.execute("BEGIN")
        repo.request_cancel(render_job_id)
        row = repo.get_by_id(render_job_id)
        connection.commit()
        return dict(row)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
