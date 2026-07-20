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
    project_id: str
    handoff_id: str
    handoff_sha256: str
    schema_version: str
    source_zip: Path
    extracted_root: Path
    files: tuple[PackageFile, ...]
    plan_ids: tuple[str, ...] = ()
    status: PackageImportStatus = PackageImportStatus.VALIDATED


@dataclass(frozen=True, slots=True)
class RenderQueueItem:
    render_id: str
    project_id: str
    handoff_id: str
    plan_id: str
    patch_ids: tuple[str, ...] = field(default_factory=tuple)
    status: QueueItemStatus = QueueItemStatus.PENDING
