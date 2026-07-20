from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .enums import PackageImportStatus, QueueItemStatus


@dataclass(frozen=True, slots=True)
class PackageFile:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class ImportedPackage:
    package_id: str
    project_id: str
    handoff_id: str
    handoff_sha256: str
    package_sha256: str
    schema_version: str
    source_zip: Path
    extracted_root: Path
    files: tuple[PackageFile, ...]
    plan_ids: tuple[str, ...] = ()
    status: PackageImportStatus = PackageImportStatus.VALIDATED


@dataclass(frozen=True, slots=True)
class RenderQueueItem:
    render_job_id: str
    project_id: str
    package_id: str
    edit_plan_id: str
    attempt_number: int = 1
    parent_render_job_id: str | None = None
    status: QueueItemStatus = QueueItemStatus.PENDING


@dataclass(frozen=True, slots=True)
class ProjectRecord:
    project_id: str
    workspace_path: Path
    database_path: Path
    created_at: str


@dataclass(frozen=True, slots=True)
class ImportResult:
    project_id: str
    package_id: str
    handoff_id: str
    edit_plan_id: str
    render_job_id: str
    render_report_path: Path
    package_root: Path
    package_sha256: str
    plan_hash: str
    duplicate: bool = False
