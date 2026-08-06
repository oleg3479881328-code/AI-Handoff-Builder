from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


PACKAGE_SCHEMA_VERSION = "1.0"


@dataclass(slots=True)
class IngestLimits:
    max_archive_depth: int = 20
    max_discovered_files: int = 100000
    max_expanded_bytes: int = 2 * 1024 * 1024 * 1024
    max_compression_ratio: float = 200.0


@dataclass(slots=True)
class DiscoveredFile:
    path: Path
    stable_source_path: Path
    source_chain: list[str]
    archive_depth: int
    extracted_from_archive: bool = False


@dataclass(slots=True)
class AssetRecord:
    asset_id: str
    original_name: str
    media_type: str
    size_bytes: int
    sha256: str
    source_path: str
    source_chain: list[str]
    archive_depth: int
    added_after_handoff_version: int
    created_at: str
    local_copy_path: str | None = None
    proxy_path: str | None = None
    metadata_path: str | None = None
    package_path: str | None = None
    metadata_package_path: str | None = None
    missing: bool = False
    damaged: bool = False
    unsupported_reason: str | None = None
    inspection: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class IngestReport:
    added_assets: list[dict[str, object]] = field(default_factory=list)
    duplicate_assets: list[dict[str, object]] = field(default_factory=list)
    missing_assets: list[dict[str, object]] = field(default_factory=list)
    damaged_files: list[dict[str, object]] = field(default_factory=list)
    unsupported_files: list[dict[str, object]] = field(default_factory=list)
    discovered_file_count: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "added_assets": self.added_assets,
            "duplicate_assets": self.duplicate_assets,
            "missing_assets": self.missing_assets,
            "damaged_files": self.damaged_files,
            "unsupported_files": self.unsupported_files,
            "discovered_file_count": self.discovered_file_count,
        }


@dataclass(slots=True)
class ProjectState:
    project_id: str
    project_name: str
    project_slug: str
    root: Path
    created_at: str
    updated_at: str
    last_handoff_version: int = 0
    last_handoff_filename: str | None = None
    assets: list[AssetRecord] = field(default_factory=list)
    ingestion_history: list[dict[str, object]] = field(default_factory=list)
    last_ingest_report: dict[str, object] = field(default_factory=dict)

    @property
    def project_file(self) -> Path:
        return self.root / "project.json"

    @property
    def asset_registry_file(self) -> Path:
        return self.root / "asset_registry.json"

    @property
    def ingestion_history_file(self) -> Path:
        return self.root / "ingestion_history.json"

    @property
    def handoffs_dir(self) -> Path:
        return self.root / "handoffs"

    @property
    def photos_dir(self) -> Path:
        return self.root / "photos"

    @property
    def audio_dir(self) -> Path:
        return self.root / "audio"

    @property
    def proxies_dir(self) -> Path:
        return self.root / "proxies"

    @property
    def metadata_dir(self) -> Path:
        return self.root / "metadata"

    @property
    def reports_dir(self) -> Path:
        return self.root / "reports"

    @property
    def cache_dir(self) -> Path:
        return self.root / "cache"
