from __future__ import annotations

from enum import StrEnum


class PackageImportStatus(StrEnum):
    STAGED = "staged"
    VALIDATED = "validated"
    REJECTED = "rejected"


class QueueItemStatus(StrEnum):
    PENDING = "pending"
    VALIDATING = "validating"
    READY = "ready"
    RENDERING = "rendering"
    QC_PENDING = "qc_pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"
