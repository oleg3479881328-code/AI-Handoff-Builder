from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from handoff_builder.ffmpeg_tools import FFmpegTools
from handoff_builder.metadata import AssetMetadataBuilder
from handoff_builder.models import AssetRecord, BuilderConfig
from handoff_builder.pipeline import HandoffBuilder


class FakeFFmpegTools:
    def probe(self, source: Path) -> dict:
        return {
            "duration": 20.0,
            "width": 1920,
            "height": 1080,
            "rotation": 0,
            "codec": "h264",
        }

    def make_proxy(self, source: Path, destination: Path, target_height: int = 720) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"proxy")

    def scene_segments(
        self,
        source: Path,
        duration: float,
        *,
        threshold: float,
        short_seconds: float,
        fallback_segment_seconds: float,
        max_segments: int,
    ) -> tuple[list[tuple[float, float]], str]:
        return ([(0.0, 7.5), (7.5, duration)], "uniform_coverage")

    def extract_frame(
        self,
        source: Path,
        at_seconds: float,
        destination: Path,
        max_width: int = 720,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (640, 360), color="blue").save(destination, "JPEG")

    def make_preview(
        self,
        source: Path,
        start_seconds: float,
        duration_seconds: float,
        destination: Path,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"preview")


class FailingFFmpegTools(FakeFFmpegTools):
    def make_preview(
        self,
        source: Path,
        start_seconds: float,
        duration_seconds: float,
        destination: Path,
    ) -> None:
        raise RuntimeError(f"preview failed for {source.name}")


def _make_photo(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1800, 1200), color="red").save(path, "JPEG")


def _make_video_placeholder(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-a-real-video-but-good-enough-for-fakes")


def test_short_video_single_scene():
    tools = FFmpegTools.__new__(FFmpegTools)
    tools.detect_scene_cuts = lambda source, threshold, duration: []  # type: ignore[attr-defined]
    segments, mode = FFmpegTools.scene_segments(
        tools,
        Path("clip.mp4"),
        8.0,
        threshold=0.35,
        short_seconds=12.0,
        fallback_segment_seconds=10.0,
        max_segments=30,
    )
    assert segments == [(0.0, 8.0)]
    assert mode == "short_full_video"


def test_long_video_no_cut_uses_uniform_coverage():
    tools = FFmpegTools.__new__(FFmpegTools)
    tools.detect_scene_cuts = lambda source, threshold, duration: []  # type: ignore[attr-defined]
    segments, mode = FFmpegTools.scene_segments(
        tools,
        Path("long.mp4"),
        26.0,
        threshold=0.35,
        short_seconds=12.0,
        fallback_segment_seconds=10.0,
        max_segments=30,
    )
    assert len(segments) >= 2
    assert segments[0][0] == 0.0
    assert round(segments[-1][1], 3) == 26.0
    assert mode == "uniform_coverage"


def test_failed_file_remains_visible_in_validation(tmp_path: Path):
    source = tmp_path / "source"
    _make_video_placeholder(source / "сломанное видео.mp4")

    builder = HandoffBuilder(
        BuilderConfig(project_name="FAIL_CASE", output_dir=tmp_path / "out", include_video_proxies=False),
        project_root=tmp_path,
    )
    builder.ffmpeg = FailingFFmpegTools()

    result = builder.build([source])

    assert result.validation["coverage_ok"] is False
    assert result.validation["failed_asset_count"] == 1
    assert "сломанное видео.mp4" in result.validation["failed_assets"][0]["source_path"]


def test_all_artifact_paths_exist_and_unicode_windows_paths_work(tmp_path: Path):
    source = tmp_path / "источник с пробелом"
    _make_photo(source / "невеста.jpg")
    _make_video_placeholder(source / "жених.mp4")

    builder = HandoffBuilder(
        BuilderConfig(project_name="Юникод", output_dir=tmp_path / "out", include_video_proxies=True),
        project_root=tmp_path,
    )
    builder.ffmpeg = FakeFFmpegTools()

    result = builder.build([source])

    assert result.validation["coverage_ok"] is True
    assert result.validation["missing_artifact_paths"] == []

    manifest = json.loads((result.package_root / "handoff_manifest.json").read_text(encoding="utf-8"))
    scene_manifest = json.loads((result.package_root / "scene_manifest.json").read_text(encoding="utf-8"))

    for asset in manifest["assets"]:
        for key in ("analysis_copy", "proxy", "storyboard"):
            rel = asset.get(key)
            if rel:
                assert (result.package_root / rel).exists()

    for scene in scene_manifest["scenes"]:
        assert (result.package_root / scene["keyframe_path"]).exists()
        assert (result.package_root / scene["preview_path"]).exists()

    assert any("источник с пробелом" in asset["source_path"] for asset in manifest["assets"])
    assert any("невеста.jpg" in asset["source_path"] for asset in manifest["assets"])


def test_process_photo_handles_unicode_windows_paths(tmp_path: Path):
    source = tmp_path / "папка" / "кадр.jpg"
    _make_photo(source)
    package_root = tmp_path / "package"

    builder = HandoffBuilder(
        BuilderConfig(project_name="PHOTO_ONLY", output_dir=tmp_path / "out"),
        project_root=tmp_path,
    )
    asset = AssetRecord(
        asset_id="abc123",
        media_type="photo",
        original_name=source.name,
        source_path=str(source),
        relative_source_path="кадр.jpg",
        extension=".jpg",
        size_bytes=source.stat().st_size,
    )

    builder._process_photo(source, asset, package_root)

    assert asset.analysis_copy is not None
    assert (package_root / asset.analysis_copy).exists()


def test_pipeline_writes_metadata_artifacts_and_keeps_one_record_per_asset(tmp_path: Path):
    source = tmp_path / "source"
    _make_photo(source / "IMG-20240716-WA0001.jpg")
    _make_video_placeholder(source / "clip.mp4")

    builder = HandoffBuilder(
        BuilderConfig(project_name="META_CASE", output_dir=tmp_path / "out", include_video_proxies=False),
        project_root=tmp_path,
    )
    builder.ffmpeg = FakeFFmpegTools()

    result = builder.build([source])

    expected_paths = [
        result.package_root / "metadata" / "asset_metadata_raw.json",
        result.package_root / "metadata" / "asset_metadata_normalized.json",
        result.package_root / "metadata" / "device_clock_profiles.json",
        result.package_root / "metadata" / "chronology_report.json",
        result.package_root / "metadata" / "location_clusters.json",
        result.package_root / "metadata_warnings.json",
    ]
    for path in expected_paths:
        assert path.exists(), path

    normalized = json.loads((result.package_root / "metadata" / "asset_metadata_normalized.json").read_text(encoding="utf-8"))
    assert normalized["schema_version"] == "1.0"
    assert len(normalized["assets"]) == result.validation["source_asset_count"] == 2
    assert {item["asset_id"] for item in normalized["assets"]} == {
        item["asset_id"] for item in json.loads((result.package_root / "handoff_manifest.json").read_text(encoding="utf-8"))["assets"]
    }


def test_metadata_builder_normalizes_exif_time_timezone_and_gps(tmp_path: Path):
    source = tmp_path / "photo.jpg"
    _make_photo(source)
    asset = AssetRecord(
        asset_id="asset1",
        media_type="photo",
        original_name=source.name,
        source_path=str(source),
        relative_source_path=source.name,
        extension=".jpg",
        size_bytes=source.stat().st_size,
    )
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path))
    normalized = builder._normalize_asset_record(
        asset,
        raw_record={
            "exiftool": {
                "[EXIF]:DateTimeOriginal": "2024:07:16 14:22:11",
                "[EXIF]:OffsetTimeOriginal": "+03:00",
                "[EXIF]:GPSLatitude": 40.7128,
                "[EXIF]:GPSLongitude": -74.0060,
                "[IFD0]:Make": "Canon",
                "[IFD0]:Model": "R6",
            },
            "pillow": {},
            "ffprobe": {},
            "filesystem": {"modified_at": "2024-07-16T11:22:11+00:00", "created_at": "2024-07-16T11:22:11+00:00"},
            "tool_sources": {"exiftool": True, "pillow": False, "ffprobe": False, "filesystem": True},
        },
        source_index=0,
        warnings=[],
    )

    assert normalized["normalized_capture_time"] == "2024-07-16T14:22:11+03:00"
    assert normalized["gps_raw"] == {"latitude": 40.7128, "longitude": -74.006, "altitude": None}
    assert normalized["metadata_status"] == "ok"
    assert normalized["device_id"] is not None


def test_metadata_builder_uses_ffprobe_quicktime_time_for_video(tmp_path: Path):
    source = tmp_path / "clip.mp4"
    _make_video_placeholder(source)
    asset = AssetRecord(
        asset_id="asset2",
        media_type="video",
        original_name=source.name,
        source_path=str(source),
        relative_source_path=source.name,
        extension=".mp4",
        size_bytes=source.stat().st_size,
    )
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path))
    normalized = builder._normalize_asset_record(
        asset,
        raw_record={
            "exiftool": {},
            "pillow": {},
            "ffprobe": {"format": {"tags": {"creation_time": "2024-07-16T10:00:00Z"}}},
            "filesystem": {"modified_at": "2024-07-16T10:01:00+00:00", "created_at": "2024-07-16T10:01:00+00:00"},
            "tool_sources": {"exiftool": False, "pillow": False, "ffprobe": True, "filesystem": True},
        },
        source_index=0,
        warnings=[],
    )

    assert normalized["normalized_capture_time"] == "2024-07-16T10:00:00+00:00"
    assert normalized["time_source"] == "ffprobe"


def test_whatsapp_filename_hint_is_low_confidence_and_timezone_unknown(tmp_path: Path):
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path))

    hint = builder._filename_hint("IMG-20240716-WA0001.jpg")

    assert hint is not None
    assert hint["normalized"] == "2024-07-16T00:00:00"
    assert hint["confidence"] == "low"


def test_conflicting_timestamps_produce_warning_without_guessing_timezone(tmp_path: Path):
    source = tmp_path / "photo.jpg"
    _make_photo(source)
    asset = AssetRecord(
        asset_id="asset3",
        media_type="photo",
        original_name=source.name,
        source_path=str(source),
        relative_source_path=source.name,
        extension=".jpg",
        size_bytes=source.stat().st_size,
    )
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path))
    warnings: list[dict] = []

    normalized = builder._normalize_asset_record(
        asset,
        raw_record={
            "exiftool": {
                "[EXIF]:DateTimeOriginal": "2024:07:16 14:22:11",
                "[EXIF]:CreateDate": "2024:07:16 16:30:00",
            },
            "pillow": {},
            "ffprobe": {},
            "filesystem": {"modified_at": "2024-07-16T10:01:00+00:00", "created_at": "2024-07-16T10:01:00+00:00"},
            "tool_sources": {"exiftool": True, "pillow": False, "ffprobe": False, "filesystem": True},
        },
        source_index=0,
        warnings=warnings,
    )

    assert normalized["normalized_capture_time"] == "2024-07-16T14:22:11"
    assert normalized["timezone_source"] is None
    assert any(item["code"] == "timestamp_conflict" for item in warnings)
    assert any(item["code"] == "timezone_unknown" for item in warnings)


def test_gps_export_modes_are_stable(tmp_path: Path):
    gps = {"latitude": 40.7128123, "longitude": -74.0059231, "altitude": 15.678}

    exact = AssetMetadataBuilder(
        BuilderConfig(project_name="X", output_dir=tmp_path, gps_export_mode="exact")
    )._apply_gps_mode(gps)
    rounded = AssetMetadataBuilder(
        BuilderConfig(project_name="X", output_dir=tmp_path, gps_export_mode="rounded")
    )._apply_gps_mode(gps)
    venue_only = AssetMetadataBuilder(
        BuilderConfig(project_name="X", output_dir=tmp_path, gps_export_mode="venue_label_only")
    )._apply_gps_mode(gps)
    excluded = AssetMetadataBuilder(
        BuilderConfig(project_name="X", output_dir=tmp_path, gps_export_mode="excluded")
    )._apply_gps_mode(gps)

    assert exact == gps
    assert rounded == {"latitude": 40.713, "longitude": -74.006, "altitude": 15.7}
    assert venue_only == {"venue_label": "cluster_40.71_-74.01"}
    assert excluded is None


def test_chronology_is_deterministic_on_repeat(tmp_path: Path):
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path))
    normalized_records = [
        {
            "asset_id": "b",
            "normalized_capture_time_epoch_ms": 2000,
            "normalized_capture_time": "2024-07-16T10:00:02+00:00",
            "time_source": "metadata",
            "device_id": "device-1",
            "source_order_index": 1,
        },
        {
            "asset_id": "a",
            "normalized_capture_time_epoch_ms": 1000,
            "normalized_capture_time": "2024-07-16T10:00:01+00:00",
            "time_source": "metadata",
            "device_id": "device-1",
            "source_order_index": 0,
        },
    ]

    first = builder._build_chronology([dict(item) for item in normalized_records])
    second = builder._build_chronology([dict(item) for item in normalized_records])

    assert first == second


def test_missing_exiftool_generates_explicit_warning_and_filesystem_fallback(tmp_path: Path):
    source = tmp_path / "plain.jpg"
    _make_photo(source)
    asset = AssetRecord(
        asset_id="asset4",
        media_type="photo",
        original_name=source.name,
        source_path=str(source),
        relative_source_path=source.name,
        extension=".jpg",
        size_bytes=source.stat().st_size,
    )
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path))
    builder._find_optional_executable = lambda name: None  # type: ignore[method-assign]

    result = builder.build([asset])

    assert any(item["code"] == "exiftool_unavailable" for item in result.warnings_payload["warnings"])
    assert result.normalized_records[0]["time_source"] in {"metadata", "filesystem"}
