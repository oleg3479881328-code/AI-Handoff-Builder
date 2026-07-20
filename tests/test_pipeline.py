from __future__ import annotations

import json
from pathlib import Path

from PIL import Image

from handoff_builder.ffmpeg_tools import FFmpegTools
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
