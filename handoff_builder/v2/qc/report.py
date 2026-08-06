from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class QCReport:
    render_id: str
    project_id: str
    handoff_id: str
    passed: bool
    warnings: tuple[str, ...] = field(default_factory=tuple)
    missing_outputs: tuple[str, ...] = field(default_factory=tuple)
