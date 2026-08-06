from __future__ import annotations

import json
import queue
import threading
from pathlib import Path

from .services import (
    apply_patch_in_workspace,
    import_plan_into_workspace,
    import_package_into_workspace,
    list_plans,
    list_render_jobs,
    render_job,
    render_next_pending_job,
    request_cancel_render_job,
    retry_render_job,
    show_plan,
    show_render_job,
)
from .services.import_service import resolve_workspace_for_package, resolve_workspace_for_plan
from .workspace import init_project_workspace, load_project_config


ControllerEvent = tuple[str, object]


class V2RunnerController:
    def __init__(self, events: queue.Queue[ControllerEvent]) -> None:
        self.events = events
        self.state = "no_workspace"
        self.workspace: Path | None = None
        self.project_id: str | None = None
        self.current_render_cancel_event: threading.Event | None = None
        self.current_render_job_id: str | None = None

    def start_open_workspace(self, workspace: Path, *, project_id: str | None = None, create: bool = False) -> None:
        self._start_worker("workspace_opening", self._open_workspace, workspace, project_id, create)

    def start_import_package(self, package_zip: Path, *, fallback_path: Path | None = None) -> None:
        self._start_worker("package_validating", self._import_package, package_zip, fallback_path)

    def start_import_plan(self, plan_json: Path, *, fallback_path: Path | None = None) -> None:
        self._start_worker("package_validating", self._import_plan, plan_json, fallback_path)

    def start_render_next(self) -> None:
        self._start_worker("render_running", self._render_next)

    def start_render_job(self, render_job_id: str) -> None:
        self._start_worker("render_running", self._render_job, render_job_id)

    def start_apply_patch(self, patch_source: Path) -> None:
        self._start_worker("patch_validating", self._apply_patch, patch_source)

    def start_refresh(self) -> None:
        self._start_worker(None, self._refresh_workspace)

    def start_retry_job(self, render_job_id: str) -> None:
        self._start_worker("render_pending", self._retry_job, render_job_id)

    def request_cancel(self, render_job_id: str) -> None:
        if self.current_render_job_id == render_job_id and self.current_render_cancel_event is not None:
            self.current_render_cancel_event.set()
        if self.workspace is None:
            return
        try:
            row = request_cancel_render_job(self.workspace, render_job_id)
            self.events.put(("render_cancel_requested", row))
        except Exception as exc:
            self.events.put(("v2_error", str(exc)))

    def _start_worker(self, state_before: str | None, fn, *args) -> None:
        if state_before is not None:
            self.state = state_before
            self.events.put(("v2_state", state_before))
        thread = threading.Thread(target=self._run_worker, args=(fn, args), daemon=True)
        thread.start()

    def _run_worker(self, fn, args: tuple[object, ...]) -> None:
        try:
            result = fn(*args)
            event_name, payload = result
            self.events.put((event_name, payload))
        except Exception as exc:
            self.events.put(("v2_error", str(exc)))

    def _open_workspace(self, workspace: Path, project_id: str | None, create: bool) -> tuple[str, object]:
        if create:
            if not project_id:
                raise ValueError("project_id is required when creating a workspace.")
            project_root = init_project_workspace(workspace, project_id)
        else:
            project_root = workspace.resolve()
            config = load_project_config(project_root)
            project_id = str(config["project_id"])
        self.workspace = project_root
        self.project_id = project_id
        self.state = "workspace_ready"
        snapshot = self._collect_workspace_snapshot(project_root)
        return "workspace_ready", snapshot

    def _import_package(self, package_zip: Path, fallback_path: Path | None) -> tuple[str, object]:
        workspace = self.workspace
        if workspace is None:
            workspace = resolve_workspace_for_package(package_zip, fallback_path=fallback_path)
            config = load_project_config(workspace)
            self.workspace = workspace
            self.project_id = str(config["project_id"])
        result = import_package_into_workspace(package_zip, workspace)
        summary = self._summarize_import(result.edit_plan_id, result.render_job_id)
        self.state = "render_pending"
        return "package_imported", summary

    def _import_plan(self, plan_json: Path, fallback_path: Path | None) -> tuple[str, object]:
        workspace = self.workspace
        if workspace is None:
            workspace = resolve_workspace_for_plan(plan_json, fallback_path=fallback_path)
            config = load_project_config(workspace)
            self.workspace = workspace
            self.project_id = str(config["project_id"])
        result = import_plan_into_workspace(plan_json, workspace)
        summary = self._summarize_import(result.edit_plan_id, result.render_job_id)
        self.state = "render_pending"
        return "package_imported", summary

    def _render_next(self) -> tuple[str, object]:
        workspace = self._require_workspace()
        jobs = list_render_jobs(workspace, project_id=self.project_id)
        next_pending = next((job for job in jobs if job["status"] == "pending"), None)
        cancel_event = threading.Event()
        self.current_render_cancel_event = cancel_event
        self.current_render_job_id = next_pending["render_job_id"] if next_pending else None
        try:
            result = render_next_pending_job(workspace, cancel_event=cancel_event)
        finally:
            self.current_render_cancel_event = None
        if result.get("status") == "no_pending_jobs":
            self.state = "workspace_ready"
            return "workspace_refreshed", self._collect_workspace_snapshot(workspace)
        return self._finish_render(result["job_id"])

    def _render_job(self, render_job_id: str) -> tuple[str, object]:
        workspace = self._require_workspace()
        cancel_event = threading.Event()
        self.current_render_cancel_event = cancel_event
        self.current_render_job_id = render_job_id
        try:
            render_job(workspace, render_job_id, cancel_event=cancel_event)
        finally:
            self.current_render_cancel_event = None
            self.current_render_job_id = None
        return self._finish_render(render_job_id)

    def _finish_render(self, render_job_id: str) -> tuple[str, object]:
        details = show_render_job(self._require_workspace(), render_job_id)
        status = str(details["job"]["status"])
        if status == "completed":
            self.state = "render_completed"
            return "render_completed", details
        if status == "failed":
            self.state = "render_failed"
            return "render_failed", details
        if status == "cancelled":
            self.state = "workspace_ready"
            return "render_cancelled", details
        self.state = "workspace_ready"
        return "render_updated", details

    def _apply_patch(self, patch_source: Path) -> tuple[str, object]:
        workspace = self._require_workspace()
        result = apply_patch_in_workspace(patch_source, workspace)
        summary = self._summarize_import(result.new_plan_id, result.render_job_id)
        summary["patch"] = {
            "patch_id": result.patch_id,
            "patch_sha256": result.patch_sha256,
            "base_plan_id": result.base_plan_id,
            "base_plan_hash": result.base_plan_hash,
            "duplicate": result.duplicate,
        }
        self.state = "patch_applied"
        return "patch_applied", summary

    def _refresh_workspace(self) -> tuple[str, object]:
        workspace = self._require_workspace()
        snapshot = self._collect_workspace_snapshot(workspace)
        latest_job = snapshot.get("latest_job")
        if latest_job:
            latest_status = str(latest_job["status"])
            self.state = {
                "pending": "render_pending",
                "running": "render_running",
                "completed": "render_completed",
                "failed": "render_failed",
            }.get(latest_status, "workspace_ready")
        else:
            self.state = "workspace_ready"
        return "workspace_refreshed", snapshot

    def _retry_job(self, render_job_id: str) -> tuple[str, object]:
        workspace = self._require_workspace()
        row = retry_render_job(workspace, render_job_id)
        self.state = "render_pending"
        return "render_retried", row

    def _collect_workspace_snapshot(self, workspace: Path) -> dict:
        config = load_project_config(workspace)
        plans = list_plans(workspace, project_id=str(config["project_id"]))
        jobs = list_render_jobs(workspace, project_id=str(config["project_id"]))
        latest_job = jobs[-1] if jobs else None
        latest_plan = plans[-1] if plans else None
        details = show_render_job(workspace, latest_job["render_job_id"]) if latest_job else None
        return {
            "workspace": str(workspace),
            "project_id": str(config["project_id"]),
            "plans": plans,
            "jobs": jobs,
            "latest_plan": latest_plan,
            "latest_job": latest_job,
            "latest_details": details,
        }

    def _summarize_import(self, plan_id: str, render_job_id: str) -> dict:
        workspace = self._require_workspace()
        plan = show_plan(workspace, plan_id)
        details = show_render_job(workspace, render_job_id)
        payload = plan["payload"]
        report = details["report"] or {}
        return {
            "workspace": str(workspace),
            "project_id": plan["metadata"]["project_id"],
            "project_name": payload.get("project_name") or plan["metadata"]["project_id"],
            "package_id": plan["metadata"]["package_id"],
            "handoff_id": plan["metadata"]["handoff_id"],
            "schema_version": plan["metadata"]["schema_version"],
            "plan_id": plan["metadata"]["edit_plan_id"],
            "plan_hash": plan["metadata"]["plan_hash"],
            "plan_version": plan["metadata"]["plan_version"],
            "parent_plan_id": plan["metadata"]["parent_plan_id"],
            "asset_count": len(payload.get("assets", [])),
            "operation_count": len(payload.get("operations", [])) or len(payload.get("visual_items", [])),
            "warnings": list(report.get("warnings", [])),
            "validation_summary": report.get("validation_summary", {}),
            "render_job_id": render_job_id,
            "job_details": details,
            "plan_payload": payload,
        }

    def _require_workspace(self) -> Path:
        if self.workspace is None:
            raise ValueError("Workspace is not open.")
        return self.workspace
