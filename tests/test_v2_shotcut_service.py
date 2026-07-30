from __future__ import annotations

from pathlib import Path

import pytest

from handoff_builder.v2.plans.semantic import ValidatedAsset, ValidatedOperation, ValidatedPreviewPlan
from handoff_builder.v2.render.shotcut_backend import ShotcutRenderJob
from handoff_builder.v2.services.shotcut_service import (
    ShotcutServicePaths,
    build_shotcut_project_from_timeline,
    build_shotcut_project_from_validated_plan,
    render_built_shotcut_project,
)
from handoff_builder.v2.shotcut_settings import ShotcutAppSettings, ShotcutSettingsStore


def test_shotcut_settings_store_round_trips(tmp_path: Path) -> None:
    runtime_dir = tmp_path / "Shotcut"
    runtime_dir.mkdir()
    (runtime_dir / "shotcut.exe").write_text("", encoding="utf-8")
    (runtime_dir / "melt.exe").write_text("", encoding="utf-8")
    server_script = tmp_path / "shotcut-mcp" / "scripts" / "shotcut_mcp_server.py"
    server_script.parent.mkdir(parents=True, exist_ok=True)
    server_script.write_text("print('ok')\n", encoding="utf-8")
    store = ShotcutSettingsStore(tmp_path / "shotcut_settings.json")

    saved = store.save(ShotcutAppSettings(runtime_dir=str(runtime_dir), server_script=str(server_script)))
    loaded = store.load()

    assert loaded == saved
    assert Path(loaded.runtime_dir) == runtime_dir.resolve()
    assert Path(loaded.server_script) == server_script.resolve()


def test_build_editable_project_from_preview_plan_creates_video_and_audio_tracks(tmp_path: Path) -> None:
    source_a = tmp_path / "source_a.mp4"
    source_b = tmp_path / "source_b.mp4"
    source_a.write_bytes(b"a")
    source_b.write_bytes(b"b")
    artifacts = _artifacts(tmp_path)
    validated = ValidatedPreviewPlan(
        payload={"schema_version": "1.0"},
        assets={
            "asset-a": ValidatedAsset("asset-a", source_a, 4000, 478, 850, 0, True),
            "asset-b": ValidatedAsset("asset-b", source_b, 4000, 478, 850, 0, False),
        },
        operations=(
            ValidatedOperation("asset-a", 0, 1000, 1000),
            ValidatedOperation("asset-b", 1000, 2000, 1000),
        ),
        planned_duration_ms=2000,
    )
    backend = _FakeBuildBackend()

    summary = build_shotcut_project_from_validated_plan(validated, backend=backend, artifacts=artifacts)

    assert summary["fps"] == 30
    assert backend.created["profile"] == {"width": 478, "height": 850, "fps_num": 30, "fps_den": 1}
    assert backend.created["tracks"] == [{"kind": "audio", "name": "A1"}]
    assert len(backend.created["clips"]) == 3
    assert backend.created["clips"][0]["track"] == "V1"
    assert backend.created["clips"][0]["position_frame"] == 0
    assert backend.created["clips"][1]["track"] == "A1"
    assert backend.created["clips"][2]["position_frame"] == 30


def test_render_built_shotcut_project_reports_progress_and_verifies_output(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    artifacts.shotcut_dir.mkdir(parents=True, exist_ok=True)
    artifacts.project_path.write_text("<mlt/>", encoding="utf-8")
    backend = _FakeRenderBackend(artifacts)
    ffmpeg_backend = _FakeFfmpegBackend()
    statuses: list[dict] = []

    summary = render_built_shotcut_project(
        backend=backend,
        ffmpeg_backend=ffmpeg_backend,
        artifacts=artifacts,
        progress_callback=statuses.append,
    )

    assert artifacts.preview_path.exists()
    assert artifacts.contact_sheet_path.exists()
    assert artifacts.reel_path.exists()
    assert artifacts.first_frame_path.exists()
    assert summary["render_status"]["status"] == "completed"
    assert len(statuses) == 2
    assert statuses[-1]["progress_percent"] == 100


def test_render_built_shotcut_project_fails_closed_when_video_stream_is_missing(tmp_path: Path) -> None:
    artifacts = _artifacts(tmp_path)
    artifacts.shotcut_dir.mkdir(parents=True, exist_ok=True)
    artifacts.project_path.write_text("<mlt/>", encoding="utf-8")
    backend = _FakeRenderBackend(artifacts, omit_video_stream=True)
    ffmpeg_backend = _FakeFfmpegBackend()

    with pytest.raises(Exception, match="missing a decodable video stream"):
        render_built_shotcut_project(
            backend=backend,
            ffmpeg_backend=ffmpeg_backend,
            artifacts=artifacts,
        )


def test_build_shotcut_project_from_timeline_preserves_photo_duration_and_applies_edit_intents(tmp_path: Path) -> None:
    photo = tmp_path / "cover.jpg"
    photo.write_bytes(b"photo")
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    artifacts = _artifacts(tmp_path)
    backend = _FakeTimelineBackend()
    timeline = {
        "canvas": {"width": 1080, "height": 1920},
        "timebase": {"fps_num": 30, "fps_den": 1},
        "normalized_timeline_hash": "a" * 64,
        "tracks": [{"track_id": "V1", "track_type": "video"}],
        "visual_items": [
            {
                "item_id": "photo-1",
                "asset_id": "asset-photo-1",
                "media_type": "photo",
                "track_id": "V1",
                "timeline_start_frame": 0,
                "duration_frames": 90,
                "source_in_us": 0,
                "source_out_us": 0,
                "source_audio_policy": "discard",
                "resolved_source_path": str(photo),
                "transform": {"scale_x": 1.1, "scale_y": 1.1, "position_x": 0.5, "position_y": 0.5},
                "crop": {"left": 10, "top": 20, "right": 30, "bottom": 40},
            },
            {
                "item_id": "video-1",
                "asset_id": "asset-video-1",
                "media_type": "video",
                "track_id": "V1",
                "timeline_start_frame": 90,
                "duration_frames": 30,
                "source_in_us": 0,
                "source_out_us": 1_000_000,
                "source_audio_policy": "discard",
                "resolved_source_path": str(video),
            },
        ],
        "audio_items": [],
        "text_items": [{"item_id": "title-1", "text": "Opening", "timeline_start_frame": 0, "duration_frames": 90}],
    }

    summary = build_shotcut_project_from_timeline(
        timeline,
        backend=backend,
        artifacts=artifacts,
        project_name="Carolyn and Rob",
    )

    assert summary["target_mlt_filename"] == "Carolyn and Rob.mlt"
    assert backend.created["clips"][0]["image_duration_seconds"] == 3.0
    assert backend.created["clips"][0]["in_frame"] == 0
    assert backend.created["clips"][0]["out_frame"] == 0
    assert backend.created["clips"][1]["position_frame"] == 90
    assert summary["clip_summary"][0]["track_item_index"] == 0
    assert summary["clip_summary"][1]["track_item_index"] == 1
    assert backend.edits[0]["op"] == "animate_clip"
    assert len(backend.edits[0]["keyframes"]) == 1
    assert backend.edits[1]["op"] == "add_filter"
    assert backend.edits[2] == {"op": "add_track", "kind": "video", "name": "Titles"}
    assert backend.edits[3]["op"] == "add_generator"
    assert backend.edits[3]["text"] == "Opening"


def test_build_shotcut_project_from_timeline_rejects_mismatched_video_duration(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"video")
    artifacts = _artifacts(tmp_path)
    backend = _FakeTimelineBackend()
    timeline = {
        "canvas": {"width": 1080, "height": 1920},
        "timebase": {"fps_num": 30, "fps_den": 1},
        "normalized_timeline_hash": "b" * 64,
        "tracks": [{"track_id": "V1", "track_type": "video"}],
        "visual_items": [
            {
                "item_id": "video-1",
                "asset_id": "asset-video-1",
                "media_type": "video",
                "track_id": "V1",
                "timeline_start_frame": 0,
                "duration_frames": 60,
                "source_in_us": 0,
                "source_out_us": 1_000_000,
                "source_audio_policy": "discard",
                "resolved_source_path": str(video),
            }
        ],
        "audio_items": [],
        "text_items": [],
    }

    with pytest.raises(Exception, match="Unsupported retiming"):
        build_shotcut_project_from_timeline(
            timeline,
            backend=backend,
            artifacts=artifacts,
            project_name="Carolyn and Rob",
        )


def _artifacts(tmp_path: Path) -> ShotcutServicePaths:
    output_dir = tmp_path / "renders" / "job-1"
    shotcut_dir = output_dir / "shotcut"
    return ShotcutServicePaths(
        output_dir=output_dir,
        shotcut_dir=shotcut_dir,
        project_path=shotcut_dir / "editable_project.mlt",
        preview_path=shotcut_dir / "preview.png",
        contact_sheet_path=shotcut_dir / "contact_sheet.png",
        runtime_status_path=shotcut_dir / "runtime_status.json",
        build_summary_path=shotcut_dir / "build_summary.json",
        render_summary_path=shotcut_dir / "render_summary.json",
        first_frame_path=output_dir / "first_frame.jpg",
        reel_path=output_dir / "reel.mp4",
    )


class _FakeBuildBackend:
    def __init__(self) -> None:
        self.created: dict[str, object] = {}

    def probe_media(self, path: Path) -> dict:
        return {
            "streams": [{"type": "video", "frame_rate": 29.97, "width": 478, "height": 850}],
        }

    def create_disposable_project(self, project_path: Path, *, profile, clips, tracks, overwrite: bool) -> dict:
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_path.write_text("<mlt/>", encoding="utf-8")
        self.created = {
            "profile": profile.to_create_project_args(),
            "clips": [clip.to_clip_args() for clip in clips],
            "tracks": [track.to_track_args() for track in tracks],
            "overwrite": overwrite,
        }
        return {"path": str(project_path), "revision": "a" * 64}

    def inspect_project(self, project_path: Path) -> dict:
        return {"path": str(project_path), "revision": "a" * 64}

    def validate_project(self, project_path: Path) -> dict:
        return {"valid": True, "ready": True}


class _FakeTimelineBackend(_FakeBuildBackend):
    def __init__(self) -> None:
        super().__init__()
        self.edits: list[dict] = []

    def edit_operations(self, project_path: Path, *, expected_revision: str, operations: list[dict]) -> dict:
        self.edits = operations
        return {"edited": True, "expected_revision": expected_revision, "operation_results": operations}


class _FakeRenderBackend:
    def __init__(self, artifacts: ShotcutServicePaths, *, omit_video_stream: bool = False) -> None:
        self.artifacts = artifacts
        self.omit_video_stream = omit_video_stream
        self.status_calls = 0

    def render_preview(self, project_path: Path, output_path: Path, *, frame: int, overwrite: bool) -> dict:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"preview")
        return {"output_path": str(output_path), "frame": frame}

    def render_contact_sheet(
        self,
        project_path: Path,
        output_path: Path,
        *,
        sample_count: int,
        columns: int,
        cell_width: int,
        overwrite: bool,
    ) -> dict:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"sheet")
        return {"output_path": str(output_path), "sample_count": sample_count}

    def start_render(self, project_path: Path, output_path: Path, *, preset: str, overwrite: bool) -> ShotcutRenderJob:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"render")
        return ShotcutRenderJob(job_id="job-shotcut", output_path=output_path, raw={"preset": preset})

    def cancel_render(self, job_id: str) -> dict:
        return {"job_id": job_id, "status": "cancel_requested"}

    def render_status(self, job_id: str) -> dict:
        self.status_calls += 1
        if self.status_calls == 1:
            return {"job_id": job_id, "status": "running", "progress_percent": 32}
        return {
            "job_id": job_id,
            "status": "completed",
            "progress_percent": 100,
            "output_path": str(self.artifacts.reel_path),
        }

    def verify_rendered_media(self, media_path: Path) -> dict:
        streams = [{"type": "audio", "codec": "aac"}]
        if not self.omit_video_stream:
            streams.insert(0, {"type": "video", "width": 478, "height": 850, "frame_rate": 30.0})
        return {
            "sha256": "a" * 64,
            "duration_seconds": 2.5,
            "streams": streams,
        }


class _FakeFfmpegBackend:
    def extract_first_frame(self, source: Path, output: Path) -> None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"frame")
