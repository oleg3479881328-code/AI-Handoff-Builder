from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path

import pytest
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from handoff_builder.ffmpeg_tools import FFmpegTools
from handoff_builder.metadata import AssetMetadataBuilder
from handoff_builder.models import AssetRecord, BuilderConfig, SceneRecord
from handoff_builder.pipeline import HandoffBuilder
from handoff_builder.utils import stable_asset_id


class FakeFFmpegTools:
    def probe(self, source: Path) -> dict:
        return {
            "duration": 20.0,
            "width": 1920,
            "height": 1080,
            "rotation": 0,
            "codec": "h264",
            "fps": 29.97,
            "audio_present": True,
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


def _make_source_zip(zip_path: Path, files: list[Path]) -> None:
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in files:
            archive.write(file_path, file_path.name)


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

    assert any(asset["relative_source_path"] == "невеста.jpg" for asset in manifest["assets"])
    assert "source_path" not in manifest["assets"][0]


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
        result.package_root / "metadata" / "metadata_warnings.json",
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
    assert normalized["location_source"] == "EXIF:GPSLatitude/GPSLongitude"
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
    assert normalized["capture_time_source"] == "ffprobe"


def test_whatsapp_filename_hint_is_low_confidence_and_timezone_unknown(tmp_path: Path):
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path))

    hint = builder._filename_hint("IMG-20240716-WA0001.jpg")

    assert hint is not None
    assert hint["normalized"] == "2024-07-16T00:00:00"
    assert hint["confidence"] == 0.35


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
    assert venue_only == {"latitude": None, "longitude": None, "altitude": None, "venue_label": "cluster_40.71_-74.01"}
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


def test_stable_asset_id_ignores_mtime_changes(tmp_path: Path):
    source = tmp_path / "source" / "clip.mp4"
    _make_video_placeholder(source)

    first = stable_asset_id(source, tmp_path / "source")
    current_atime = source.stat().st_atime
    source.touch()
    second = stable_asset_id(source, tmp_path / "source")

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
    assert result.normalized_records[0]["capture_time_source"] in {"metadata", "filesystem"}


def test_portable_package_excludes_absolute_source_paths_and_keeps_local_registry(tmp_path: Path):
    source = tmp_path / "источник & Oleg's"
    _make_photo(source / "IMG-20240716-WA0001.jpg")

    builder = HandoffBuilder(
        BuilderConfig(project_name="PORTABLE", output_dir=tmp_path / "out", include_video_proxies=False),
        project_root=tmp_path,
    )
    builder.ffmpeg = FakeFFmpegTools()

    result = builder.build([source])

    manifest = json.loads((result.package_root / "handoff_manifest.json").read_text(encoding="utf-8"))
    assert all("source_path" not in asset for asset in manifest["assets"])
    assert result.local_asset_registry_path is not None
    registry = json.loads(result.local_asset_registry_path.read_text(encoding="utf-8"))
    assert registry["assets"][0]["source_path"].endswith("IMG-20240716-WA0001.jpg")
    with zipfile.ZipFile(result.archive_path) as archive:
        names = set(archive.namelist())
        assert "local_asset_registry.json" not in names
        assert "metadata/metadata_warnings.json" in names


def test_owner_flow_single_source_zip_uses_project_root_workspace(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    source_dir = tmp_path / "source"
    photo = source_dir / "IMG-20240716-WA0001.jpg"
    _make_photo(photo)
    project_root = tmp_path / "WEDDING_PROJECT"
    source_zip = project_root / "WEDDING_PROJECT_source.zip"
    _make_source_zip(source_zip, [photo])

    builder = HandoffBuilder(
        BuilderConfig(
            project_name="WEDDING_PROJECT",
            output_dir=tmp_path / "out",
            workspace_root=project_root,
            source_zip_path=source_zip,
            include_video_proxies=False,
        ),
        project_root=tmp_path,
    )
    builder.ffmpeg = FakeFFmpegTools()

    result = builder.build([source_zip])

    assert result.project_root == project_root.resolve()
    assert result.archive_path.parent == (project_root / "handoffs").resolve()
    assert result.local_asset_registry_path == (project_root / "analysis" / "local_asset_registry.json").resolve()
    assert (project_root / "incoming_ai_packages").exists()
    manifest = json.loads((result.package_root / "handoff_manifest.json").read_text(encoding="utf-8"))
    assert manifest["project_id"] == "WEDDING_PROJECT"
    assert manifest["handoff_id"] == result.handoff_id
    handoff_index = json.loads((project_root / "analysis" / "handoff_index.json").read_text(encoding="utf-8"))
    assert handoff_index["handoffs"][0]["handoff_id"] == result.handoff_id
    assert handoff_index["handoffs"][0]["handoff_sha256"] == result.handoff_sha256


def test_single_source_zip_derives_owner_visible_names_and_shotcut_contract(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    source_dir = tmp_path / "source"
    photo = source_dir / "IMG-20240716-WA0001.jpg"
    _make_photo(photo)
    project_root = tmp_path / "Carolyn and Rob"
    source_zip = project_root / "Carolyn and Rob.zip"
    _make_source_zip(source_zip, [photo])

    builder = HandoffBuilder(
        BuilderConfig(
            project_name="Carolyn and Rob",
            project_id="carolyn_and_rob",
            output_dir=tmp_path / "out",
            workspace_root=project_root,
            source_zip_path=source_zip,
            include_video_proxies=False,
        ),
        project_root=tmp_path,
    )
    builder.ffmpeg = FakeFFmpegTools()

    result = builder.build([source_zip])

    assert result.archive_path.name == "Carolyn and Rob_ANALYSIS_HANDOFF.zip"
    manifest = json.loads((result.package_root / "handoff_manifest.json").read_text(encoding="utf-8"))
    assert manifest["project_name"] == "Carolyn and Rob"
    assert manifest["project_id"] == "carolyn_and_rob"
    assert manifest["expected_output_filename"] == "Carolyn and Rob.json"
    assert manifest["target_editor"] == "shotcut"
    assert manifest["content_hash"] == result.handoff_content_hash

    start_here = (result.package_root / "00_START_HERE.md").read_text(encoding="utf-8")
    brief = (result.package_root / "PROJECT_BRIEF.md").read_text(encoding="utf-8")
    contract = (result.package_root / "OUTPUT_CONTRACT.md").read_text(encoding="utf-8")
    combined = "\n".join([start_here, brief, contract])
    assert "Shotcut" in combined
    assert "standalone JSON" in combined
    assert "AI_EDIT_PACKAGE.zip" not in combined
    assert "DaVinci" not in combined


def test_exiftool_uses_parent_cwd_for_unicode_zip_roots(tmp_path: Path, monkeypatch):
    source = tmp_path / "Раскладывание вещей" / "IMG-20240716-WA0001.jpg"
    _make_photo(source)
    asset = AssetRecord(
        asset_id="asset-unicode",
        media_type="photo",
        original_name=source.name,
        source_path=str(source),
        relative_source_path=source.name,
        extension=".jpg",
        size_bytes=source.stat().st_size,
    )
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path), project_root=tmp_path)
    builder._find_optional_executable = lambda name: str(tmp_path / "bin" / "exiftool.exe") if name == "exiftool" else None  # type: ignore[method-assign]

    calls: list[dict[str, object]] = []

    def fake_run_command(args, **kwargs):
        calls.append({"args": args, "cwd": kwargs.get("cwd"), "env": kwargs.get("env")})
        return subprocess.CompletedProcess(
            args=args,
            returncode=0,
            stdout='[{"SourceFile":"IMG-20240716-WA0001.jpg","EXIF:DateTimeOriginal":"2024:07:16 12:34:56"}]',
            stderr="",
        )

    monkeypatch.setattr("handoff_builder.metadata.run_command", fake_run_command)

    result = builder.build([asset])

    assert result.tool_status["exiftool"]["status"] == "available"
    assert len(calls) == 1
    assert calls[0]["cwd"] == source.parent.resolve()
    assert calls[0]["args"][-1] == source.name
    env = calls[0]["env"]
    assert isinstance(env, dict)
    assert "LANG" not in env
    assert "LC_ALL" not in env
    assert "LC_CTYPE" not in env


def test_raw_metadata_export_serializes_pillow_rationals(tmp_path: Path):
    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path, gps_export_mode="exact"))
    raw_record = {
        "schema_version": "1.0",
        "asset_id": "asset-rational",
        "original_name": "camA_photo.jpg",
        "relative_source_path": "camA_photo.jpg",
        "media_type": "photo",
        "tool_sources": {"exiftool": False, "pillow": True, "ffprobe": False, "filesystem": True},
        "exiftool": {},
        "pillow": {"XResolution": IFDRational(72, 1), "GPSInfo": {"GPSAltitude": IFDRational(5, 1)}},
        "ffprobe": {},
        "filesystem": {"modified_at": "2026-07-23T00:00:00+00:00", "created_at": "2026-07-23T00:00:00+00:00"},
    }

    exported = builder._sanitize_raw_record_for_export(raw_record)

    assert exported["pillow"]["XResolution"] == 72.0
    assert exported["pillow"]["GPSInfo"]["GPSAltitude"] == 5.0
    json.dumps(exported, ensure_ascii=False)


def test_extract_pillow_metadata_reads_gps_ifd_offsets(tmp_path: Path, monkeypatch):
    path = tmp_path / "photo.jpg"
    _make_photo(path)

    class FakeExif(dict):
        def get_ifd(self, tag_id: int):
            if tag_id == 34853:
                return {
                    1: "N",
                    2: ((40, 1), (42, 1), (46, 1)),
                    3: "W",
                    4: ((74, 1), (0, 1), (216, 10)),
                    6: IFDRational(5, 1),
                }
            return None

    class FakeImage:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def getexif(self):
            return FakeExif({34853: 226, 271: "Canon", 272: "R6"})

    monkeypatch.setattr("handoff_builder.metadata.Image.open", lambda _: FakeImage())

    builder = AssetMetadataBuilder(BuilderConfig(project_name="X", output_dir=tmp_path))
    payload = builder._extract_pillow_metadata(path)

    assert payload["GPSInfo"]["GPSLatitudeRef"] == "N"
    assert payload["GPSInfo"]["GPSLongitudeRef"] == "W"
    assert payload["GPSInfo"]["GPSAltitude"] == 5.0
    assert payload["Make"] == "Canon"
    assert payload["Model"] == "R6"


def test_stable_scene_order_sorts_by_chronology_then_asset_then_index(tmp_path: Path):
    builder = HandoffBuilder(
        BuilderConfig(project_name="ORDER", output_dir=tmp_path / "out"),
        project_root=tmp_path,
    )
    unordered = [
        SceneRecord(
            scene_id="asset-b_s0001",
            asset_id="asset-b",
            scene_index=1,
            start_ms=0,
            end_ms=1000,
            duration_ms=1000,
            detection_mode="short_full_video",
            keyframe_time_ms=500,
            keyframe_path="scene_keyframes/asset-b_s0001.jpg",
            preview_path="scene_previews/asset-b_s0001.mp4",
            chronology_rank=2,
            capture_time_iso="2026-07-19T00:00:00",
        ),
        SceneRecord(
            scene_id="asset-a_s0002",
            asset_id="asset-a",
            scene_index=2,
            start_ms=1000,
            end_ms=2000,
            duration_ms=1000,
            detection_mode="short_full_video",
            keyframe_time_ms=1500,
            keyframe_path="scene_keyframes/asset-a_s0002.jpg",
            preview_path="scene_previews/asset-a_s0002.mp4",
            chronology_rank=1,
            capture_time_iso="2026-07-19T00:00:00",
        ),
        SceneRecord(
            scene_id="asset-a_s0001",
            asset_id="asset-a",
            scene_index=1,
            start_ms=0,
            end_ms=1000,
            duration_ms=1000,
            detection_mode="short_full_video",
            keyframe_time_ms=500,
            keyframe_path="scene_keyframes/asset-a_s0001.jpg",
            preview_path="scene_previews/asset-a_s0001.mp4",
            chronology_rank=1,
            capture_time_iso="2026-07-19T00:00:00",
        ),
    ]

    ordered = builder._stable_scene_order(unordered)

    assert [scene.scene_id for scene in ordered] == [
        "asset-a_s0001",
        "asset-a_s0002",
        "asset-b_s0001",
    ]


def test_metadata_contract_failure_marks_coverage_not_ok(tmp_path: Path):
    source = tmp_path / "source"
    _make_photo(source / "IMG-20240716-WA0001.jpg")

    builder = HandoffBuilder(
        BuilderConfig(project_name="BROKEN_META", output_dir=tmp_path / "out", include_video_proxies=False),
        project_root=tmp_path,
    )
    builder.ffmpeg = FakeFFmpegTools()

    original_build = builder.metadata.build

    def broken_build(assets):
        result = original_build(assets)
        result.normalized_records[0]["capture_time_source"] = None
        result.normalized_records[0]["time_confidence"] = None
        return result

    builder.metadata.build = broken_build  # type: ignore[method-assign]
    result = builder.build([source])

    assert result.validation["coverage_ok"] is False
    assert any("computed capture time missing source/confidence" in item for item in result.validation["metadata_hard_failures"])


def test_manifest_reference_without_metadata_record_is_hard_failure(tmp_path: Path):
    source = tmp_path / "source"
    _make_photo(source / "IMG-20240716-WA0001.jpg")

    builder = HandoffBuilder(
        BuilderConfig(project_name="BROKEN_REFERENCE", output_dir=tmp_path / "out", include_video_proxies=False),
        project_root=tmp_path,
    )
    builder.ffmpeg = FakeFFmpegTools()

    original_build = builder.metadata.build

    def broken_build(assets):
        result = original_build(assets)
        result.normalized_records = []
        return result

    builder.metadata.build = broken_build  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="manifest references assets without metadata records"):
        builder.build([source])


def test_prepare_handoff_succeeds_without_voicebox_runtime(tmp_path: Path):
    source = tmp_path / "source"
    _make_photo(source / "IMG-20240716-WA0001.jpg")

    builder = HandoffBuilder(
        BuilderConfig(project_name="NO_VOICEBOX", output_dir=tmp_path / "out", include_video_proxies=False),
        project_root=tmp_path,
    )
    builder.ffmpeg = FakeFFmpegTools()

    result = builder.build([source])

    assert result.validation["coverage_ok"] is True


def test_prepare_handoff_contract_is_stable_with_or_without_voicebox(tmp_path: Path):
    source = tmp_path / "source"
    _make_photo(source / "IMG-20240716-WA0001.jpg")

    def build_once(name: str):
        builder = HandoffBuilder(
            BuilderConfig(project_name=name, output_dir=tmp_path / name, include_video_proxies=False),
            project_root=tmp_path,
        )
        builder.ffmpeg = FakeFFmpegTools()
        result = builder.build([source])
        manifest = json.loads((result.package_root / "handoff_manifest.json").read_text(encoding="utf-8"))
        manifest.pop("created_at", None)
        return manifest

    without_voicebox = build_once("WITHOUT_VOICEBOX")
    with_voicebox = build_once("WITH_VOICEBOX")

    without_voicebox["project_name"] = "SAME"
    with_voicebox["project_name"] = "SAME"
    without_voicebox["summary"]["project_name"] = "SAME"
    with_voicebox["summary"]["project_name"] = "SAME"
    assert without_voicebox["assets"] == with_voicebox["assets"]
    assert without_voicebox["summary"]["metadata_report_paths"] == with_voicebox["summary"]["metadata_report_paths"]
