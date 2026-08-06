from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..domain.records import RenderQueueItem


class RenderQueueRepository(Protocol):
    def enqueue(self, item: RenderQueueItem) -> None:
        ...

    def get_by_id(self, render_job_id: str) -> object:
        ...

    def list_by_project(self, project_id: str) -> list[object]:
        ...

    def claim_next_pending_job(self, project_id: str) -> object | None:
        ...

    def mark_running(self, render_job_id: str) -> None:
        ...

    def mark_completed(self, render_job_id: str) -> None:
        ...

    def mark_failed(self, render_job_id: str) -> None:
        ...

    def request_cancel(self, render_job_id: str) -> None:
        ...

    def mark_cancelled(self, render_job_id: str) -> None:
        ...

    def retry_job(self, render_job_id: str) -> object:
        ...


class RenderCompiler(Protocol):
    def compile_plan(self, plan_path: Path) -> list[list[str]]:
        """Compile a validated plan into allowlisted FFmpeg argument arrays."""
