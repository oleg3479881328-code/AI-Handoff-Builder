from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class BuilderConfig:
    project_name: str
    output_dir: Path
    include_video_proxies: bool = True
    gps_export_mode: str = "rounded"
    worker_count: int = 2
    photo_long_side: int = 1280
    photo_quality: int = 85
    proxy_height: int = 720
    preview_seconds: float = 3.0
    scene_threshold: float = 0.35
    short_video_seconds: float = 12.0
    fallback_segment_seconds: float = 10.0
    max_segments_per_video: int = 30
    storyboard_frames: int = 11
    overwrite: bool = False

    def __post_init__(self) -> None:
        allowed = {"exact", "rounded", "venue_label_only", "excluded"}
        if self.gps_export_mode not in allowed:
            raise ValueError(
                "gps_export_mode must be one of: exact, rounded, venue_label_only, excluded"
            )


@dataclass(slots=True)
class AssetRecord:
    asset_id: str
    media_type: str
    original_name: str
    source_path: str
    relative_source_path: str
    extension: str
    size_bytes: int
    status: str = "pending"
    error: str | None = None
    duration_ms: int | None = None
    width: int | None = None
    height: int | None = None
    rotation: int | None = None
    folder_category: str | None = None
    metadata_status: str = "pending"
    capture_time_iso: str | None = None
    capture_time_source: str | None = None
    capture_time_confidence: float | None = None
    timezone_source: str | None = None
    gps_present: bool = False
    location_confidence: float | None = None
    device_id: str | None = None
    fps: float | None = None
    audio_present: bool | None = None
    chronology_rank: int | None = None
    location_cluster_id: str | None = None
    analysis_copy: str | None = None
    proxy: str | None = None
    storyboard: str | None = None
    scene_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload.pop("source_path", None)
        return payload


@dataclass(slots=True)
class SceneRecord:
    scene_id: str
    asset_id: str
    scene_index: int
    start_ms: int
    end_ms: int
    duration_ms: int
    detection_mode: str
    keyframe_time_ms: int
    keyframe_path: str
    preview_path: str
    chronology_rank: int | None = None
    location_cluster_id: str | None = None
    capture_time_iso: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BuildResult:
    archive_path: Path
    job_root: Path
    package_root: Path
    validation_path: Path
    validation: dict[str, Any]
    failed_sources: list[str]
    metadata_warnings_path: Path | None = None
    local_asset_registry_path: Path | None = None
    canceled: bool = False
