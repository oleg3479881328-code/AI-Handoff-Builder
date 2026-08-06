from __future__ import annotations

from enum import StrEnum


class PackageImportStatus(StrEnum):
    STAGED = "staged"
    VALIDATED = "validated"
    REJECTED = "rejected"


class QueueItemStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCEL_REQUESTED = "cancel_requested"
    CANCELLED = "cancelled"
