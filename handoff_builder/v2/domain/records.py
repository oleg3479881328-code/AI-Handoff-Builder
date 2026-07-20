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


@dataclass(frozen=True, slots=True)
class PatchApplyResult:
    project_id: str
    package_id: str
    handoff_id: str
    patch_id: str
    patch_sha256: str
    base_plan_id: str
    base_plan_hash: str
    new_plan_id: str
    new_plan_hash: str
    render_job_id: str
    render_report_path: Path
    patch_root: Path
    duplicate: bool = False


@dataclass(frozen=True, slots=True)
class PlanSummary:
    edit_plan_id: str
    project_id: str
    package_id: str
    handoff_id: str
    schema_version: str
    plan_sha256: str
    plan_hash: str
    plan_path: Path
    created_at: str
    plan_version: int = 1
    parent_plan_id: str | None = None
    patch_id: str | None = None
    base_plan_hash: str | None = None
