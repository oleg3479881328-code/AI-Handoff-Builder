from __future__ import annotations


class HandoffBuilderV2Error(RuntimeError):
    """Base class for v2 local edit runner errors."""


class UnsafePackageError(HandoffBuilderV2Error):
    """Raised when an import package violates safety boundaries."""


class UnsupportedSchemaVersionError(HandoffBuilderV2Error):
    """Raised when a schema version is not supported by the importer."""


class ProjectMismatchError(HandoffBuilderV2Error):
    """Raised when a package does not belong to the target project."""


class ChecksumMismatchError(HandoffBuilderV2Error):
    """Raised when package file hashes do not match manifest claims."""


class InternalRenderBoundaryError(HandoffBuilderV2Error):
    """Raised when a renderer/compiler boundary is crossed unsafely."""


class InvalidQueueTransitionError(HandoffBuilderV2Error):
    """Raised when a queue job transition is invalid."""
