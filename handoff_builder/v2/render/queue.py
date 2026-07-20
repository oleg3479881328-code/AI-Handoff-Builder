from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..domain.records import RenderQueueItem


class RenderQueueRepository(Protocol):
    def enqueue(self, item: RenderQueueItem) -> None:
        ...

    def mark_status(self, render_id: str, status: str) -> None:
        ...


class RenderCompiler(Protocol):
    def compile_plan(self, plan_path: Path) -> list[list[str]]:
        """Compile a validated plan into allowlisted FFmpeg argument arrays."""
