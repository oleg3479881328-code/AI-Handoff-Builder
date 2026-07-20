from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from ..common import stable_v2_id, utc_now_iso
from ..domain.enums import QueueItemStatus
from ..domain.records import ProjectRecord, RenderQueueItem
from ..errors import InvalidQueueTransitionError, UnsafePackageError


class WorkspaceRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def create_project(self, project_id: str, workspace_path: Path) -> ProjectRecord:
        timestamp = utc_now_iso()
        self.connection.execute(
            """
            INSERT OR IGNORE INTO projects (project_id, workspace_path, created_at)
            VALUES (?, ?, ?)
            """,
            (project_id, str(workspace_path), timestamp),
        )
        return self.get_project(project_id)

    def get_project(self, project_id: str) -> ProjectRecord:
        row = self.connection.execute(
            "SELECT project_id, workspace_path, created_at FROM projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
        if row is None:
            raise UnsafePackageError(f"Project is not initialized: {project_id}")
        return ProjectRecord(
            project_id=row["project_id"],
            workspace_path=Path(row["workspace_path"]),
            database_path=Path(row["workspace_path"]) / "project.sqlite",
            created_at=row["created_at"],
        )

    def get_package_by_sha(self, project_id: str, package_sha256: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM ai_packages WHERE project_id = ? AND package_sha256 = ?",
            (project_id, package_sha256),
        ).fetchone()

    def insert_package(
        self,
        *,
        package_id: str,
        project_id: str,
        handoff_id: str,
        handoff_sha256: str,
        schema_version: str,
        package_sha256: str,
        source_zip_name: str,
        extracted_root: Path,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO ai_packages (
                package_id, project_id, handoff_id, handoff_sha256, schema_version,
                package_sha256, source_zip_name, extracted_root, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                package_id,
                project_id,
                handoff_id,
                handoff_sha256,
                schema_version,
                package_sha256,
                source_zip_name,
                str(extracted_root),
                utc_now_iso(),
            ),
        )

    def insert_plan(
        self,
        *,
        edit_plan_id: str,
        project_id: str,
        package_id: str,
        handoff_id: str,
        schema_version: str,
        plan_sha256: str,
        plan_hash: str,
        plan_path: Path,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO edit_plans (
                edit_plan_id, project_id, package_id, handoff_id, schema_version,
                plan_sha256, plan_hash, plan_path, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                edit_plan_id,
                project_id,
                package_id,
                handoff_id,
                schema_version,
                plan_sha256,
                plan_hash,
                str(plan_path),
                utc_now_iso(),
            ),
        )

    def get_plan(self, edit_plan_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM edit_plans WHERE edit_plan_id = ?",
            (edit_plan_id,),
        ).fetchone()
        if row is None:
            raise UnsafePackageError(f"Unknown edit plan: {edit_plan_id}")
        return row

    def add_event(
        self,
        *,
        project_id: str,
        event_type: str,
        payload: dict,
        package_id: str | None = None,
        render_job_id: str | None = None,
    ) -> str:
        event_id = stable_v2_id(project_id, event_type, utc_now_iso(), length=20)
        self.connection.execute(
            """
            INSERT INTO events (event_id, project_id, package_id, render_job_id, event_type, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                project_id,
                package_id,
                render_job_id,
                event_type,
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                utc_now_iso(),
            ),
        )
        return event_id

    def list_events(self, project_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM events WHERE project_id = ? ORDER BY created_at, event_id",
                (project_id,),
            )
        )

    def get_existing_import_result(self, project_id: str, package_sha256: str) -> sqlite3.Row | None:
        return self.connection.execute(
            """
            SELECT
                p.project_id,
                ap.package_id,
                ap.handoff_id,
                ep.edit_plan_id,
                rj.render_job_id,
                ro.report_path,
                ap.extracted_root,
                ap.package_sha256,
                ep.plan_hash
            FROM ai_packages ap
            JOIN edit_plans ep ON ep.package_id = ap.package_id
            JOIN render_jobs rj ON rj.package_id = ap.package_id AND rj.edit_plan_id = ep.edit_plan_id
            JOIN render_outputs ro ON ro.render_job_id = rj.render_job_id
            JOIN projects p ON p.project_id = ap.project_id
            WHERE ap.project_id = ? AND ap.package_sha256 = ?
            ORDER BY rj.attempt_number
            LIMIT 1
            """,
            (project_id, package_sha256),
        ).fetchone()


class SqliteRenderQueueRepository:
    VALID_TRANSITIONS: dict[str, set[str]] = {
        QueueItemStatus.PENDING: {QueueItemStatus.RUNNING, QueueItemStatus.CANCEL_REQUESTED, QueueItemStatus.FAILED},
        QueueItemStatus.RUNNING: {QueueItemStatus.COMPLETED, QueueItemStatus.FAILED, QueueItemStatus.CANCEL_REQUESTED},
        QueueItemStatus.CANCEL_REQUESTED: {QueueItemStatus.CANCELLED, QueueItemStatus.FAILED},
        QueueItemStatus.FAILED: set(),
        QueueItemStatus.CANCELLED: set(),
        QueueItemStatus.COMPLETED: set(),
    }

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def enqueue(self, item: RenderQueueItem) -> None:
        now = utc_now_iso()
        self.connection.execute(
            """
            INSERT INTO render_jobs (
                render_job_id, project_id, package_id, edit_plan_id, status,
                attempt_number, parent_render_job_id, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item.render_job_id,
                item.project_id,
                item.package_id,
                item.edit_plan_id,
                item.status,
                item.attempt_number,
                item.parent_render_job_id,
                now,
                now,
            ),
        )

    def get_by_id(self, render_job_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM render_jobs WHERE render_job_id = ?",
            (render_job_id,),
        ).fetchone()
        if row is None:
            raise UnsafePackageError(f"Unknown render job: {render_job_id}")
        return row

    def list_by_project(self, project_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM render_jobs WHERE project_id = ? ORDER BY created_at, render_job_id",
                (project_id,),
            )
        )

    def claim_next_pending_job(self, project_id: str) -> sqlite3.Row | None:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                """
                SELECT render_job_id
                FROM render_jobs
                WHERE project_id = ? AND status = ?
                ORDER BY created_at, render_job_id
                LIMIT 1
                """,
                (project_id, QueueItemStatus.PENDING),
            ).fetchone()
            if row is None:
                self.connection.commit()
                return None
            self._transition(render_job_id=row["render_job_id"], new_status=QueueItemStatus.RUNNING)
            claimed = self.get_by_id(row["render_job_id"])
            self.connection.commit()
            return claimed
        except Exception:
            self.connection.rollback()
            raise

    def mark_running(self, render_job_id: str) -> None:
        self._transition(render_job_id=render_job_id, new_status=QueueItemStatus.RUNNING)

    def mark_completed(self, render_job_id: str) -> None:
        self._transition(render_job_id=render_job_id, new_status=QueueItemStatus.COMPLETED)

    def mark_failed(self, render_job_id: str) -> None:
        self._transition(render_job_id=render_job_id, new_status=QueueItemStatus.FAILED)

    def request_cancel(self, render_job_id: str) -> None:
        self._transition(render_job_id=render_job_id, new_status=QueueItemStatus.CANCEL_REQUESTED)

    def mark_cancelled(self, render_job_id: str) -> None:
        self._transition(render_job_id=render_job_id, new_status=QueueItemStatus.CANCELLED)

    def retry_job(self, render_job_id: str) -> sqlite3.Row:
        source = self.get_by_id(render_job_id)
        if source["status"] not in {QueueItemStatus.FAILED, QueueItemStatus.CANCELLED}:
            raise InvalidQueueTransitionError(
                f"Retry is allowed only for failed/cancelled jobs, not {source['status']}"
            )
        attempt_number = int(source["attempt_number"]) + 1
        new_job_id = stable_v2_id(source["render_job_id"], "retry", str(attempt_number), length=20)
        self.enqueue(
            RenderQueueItem(
                render_job_id=new_job_id,
                project_id=source["project_id"],
                package_id=source["package_id"],
                edit_plan_id=source["edit_plan_id"],
                attempt_number=attempt_number,
                parent_render_job_id=source["render_job_id"],
                status=QueueItemStatus.PENDING,
            )
        )
        return self.get_by_id(new_job_id)

    def insert_render_output(self, *, output_id: str, render_job_id: str, report_path: Path, renderer_status: str) -> None:
        self.connection.execute(
            """
            INSERT INTO render_outputs (output_id, render_job_id, report_path, renderer_status, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (output_id, render_job_id, str(report_path), renderer_status, utc_now_iso()),
        )

    def get_render_output(self, render_job_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM render_outputs WHERE render_job_id = ?",
            (render_job_id,),
        ).fetchone()
        if row is None:
            raise UnsafePackageError(f"No render output registered for {render_job_id}")
        return row

    def _transition(self, *, render_job_id: str, new_status: str) -> None:
        current = self.get_by_id(render_job_id)
        current_status = current["status"]
        if current_status == new_status:
            return
        allowed = self.VALID_TRANSITIONS.get(current_status, set())
        if new_status not in allowed:
            raise InvalidQueueTransitionError(f"Invalid queue transition: {current_status} -> {new_status}")
        self.connection.execute(
            "UPDATE render_jobs SET status = ?, updated_at = ? WHERE render_job_id = ?",
            (new_status, utc_now_iso(), render_job_id),
        )
