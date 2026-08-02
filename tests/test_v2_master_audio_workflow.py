from __future__ import annotations

import json
from pathlib import Path

from handoff_builder.models import AssetRecord
from handoff_builder.v2.services.master_package_service import PHOTO_DURATION_MS, prepare_master_package
from handoff_builder.v2.services.transcript_service import create_final_analysis_handoff, import_gemini_transcript
from handoff_builder.v2.shotcut_settings import ShotcutAppSettings
from handoff_builder.v2.workspace import init_project_workspace


class _FakeFFmpeg:
    ffmpeg = "ffmpeg"
    ffprobe = "ffprobe"
    cancel_event = None


class _FakeBackend:
    def __init__(self) -> None:
        self.created: dict[str, object] = {}

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

    def validate_project(self, project_path: Path) -> dict:
        return {"valid": project_path.exists()}


def _asset(path: Path, *, asset_id: str, media_type: str, duration_ms: int | None, audio: bool) -> AssetRecord:
    return AssetRecord(
        asset_id=asset_id,
        media_type=media_type,
        original_name=path.name,
        source_path=str(path.resolve()),
        relative_source_path=path.name,
        extension=path.suffix.lower(),
        size_bytes=path.stat().st_size,
        original_project_path=f"originals/{path.name}",
        duration_ms=duration_ms,
        width=1080,
        height=1920,
        fps=30.0,
        audio_present=audio,
        chronology_rank=0 if asset_id.endswith("1") else 1,
    )


def _write_registry(project_root: Path, assets: list[AssetRecord]) -> None:
    payload = {
        "schema_version": "1.0",
        "assets": [
            {
                "asset_id": asset.asset_id,
                "source_path": asset.source_path,
                "original_project_path": asset.original_project_path,
                "relative_source_path": asset.relative_source_path,
                "original_name": asset.original_name,
                "media_type": asset.media_type,
                "size_bytes": asset.size_bytes,
                "sha256": f"{asset.asset_id:0<64}"[:64],
                "capture_time": "2026-08-02T12:00:00+00:00",
                "proxy_project_path": None,
                "analysis_preview_paths": {"analysis_copy": None, "proxy": None, "storyboard": None},
            }
            for asset in assets
        ],
    }
    (project_root / "analysis" / "local_asset_registry.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def test_prepare_master_package_creates_master_files_and_preserves_photo_duration(tmp_path: Path, monkeypatch) -> None:
    project_root = init_project_workspace(tmp_path / "Carolyn and Rob", "carolyn_and_rob")
    photo = project_root / "originals" / "cover.jpg"
    video = project_root / "originals" / "clip.mp4"
    photo.write_bytes(b"photo")
    video.write_bytes(b"video")
    assets = [
        _asset(photo, asset_id="asset-1", media_type="photo", duration_ms=None, audio=False),
        _asset(video, asset_id="asset-2", media_type="video", duration_ms=2_000, audio=True),
    ]
    metadata = [
        {"asset_id": "asset-1", "normalized_capture_time": "2026-08-02T12:00:00+00:00"},
        {"asset_id": "asset-2", "normalized_capture_time": "2026-08-02T12:00:01+00:00"},
    ]
    _write_registry(project_root, assets)
    monkeypatch.setattr(
        "handoff_builder.v2.services.master_package_service._write_master_audio",
        lambda _ffmpeg, _items, output: output.write_bytes(b"mp3"),
    )
    monkeypatch.setattr(
        "handoff_builder.v2.services.master_package_service._probe_audio",
        lambda _ffmpeg, _path: {"duration_seconds": 2.5, "sample_rate": 48000, "channels": 2},
    )

    result = prepare_master_package(
        project_root=project_root,
        project_id="carolyn_and_rob",
        project_name="Carolyn and Rob",
        assets=assets,
        metadata_records=metadata,
        ffmpeg_tools=_FakeFFmpeg(),
        shotcut_settings=ShotcutAppSettings(),
        shotcut_backend=_FakeBackend(),
    )

    assert result.state == "WAITING_FOR_TRANSCRIPT"
    assert result.timeline_item_count == 2
    payload = json.loads(result.timeline_map_path.read_text(encoding="utf-8"))
    assert payload["items"][0]["duration_ms"] == PHOTO_DURATION_MS
    assert payload["items"][1]["has_audio"] is True
    assert result.master_mlt_path.exists()
    assert result.prompt_path.exists()


def test_import_transcript_preserves_overlaps_and_source_mappings(tmp_path: Path, monkeypatch) -> None:
    project_root = init_project_workspace(tmp_path / "Carolyn and Rob", "carolyn_and_rob")
    master_dir = project_root / "handoffs" / "Carolyn and Rob_MASTER_PACKAGE"
    master_dir.mkdir(parents=True, exist_ok=True)
    (master_dir / "Carolyn and Rob_MASTER_AUDIO.mp3").write_bytes(b"mp3")
    timeline_map = {
        "items": [
            {"timeline_index": 0, "asset_id": "asset-1", "source_file_name": "cover.jpg", "master_start": "00:00:00.000", "master_end": "00:00:00.500"},
            {"timeline_index": 1, "asset_id": "asset-2", "source_file_name": "clip.mp4", "master_start": "00:00:00.500", "master_end": "00:00:02.500"},
        ]
    }
    (master_dir / "Carolyn and Rob_MASTER_TIMELINE_MAP.json").write_text(json.dumps(timeline_map, ensure_ascii=False, indent=2), encoding="utf-8")
    transcript = {
        "project_name": "Carolyn and Rob",
        "events": [
            {"start_time": "00:00:00.250", "end_time": "00:00:00.750", "event_type": "speech", "speaker": "A"},
        ],
    }
    transcript_path = tmp_path / "transcript.json"
    transcript_path.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        "handoff_builder.v2.services.transcript_service._probe_audio",
        lambda _ffmpeg, _path: {"duration_seconds": 2.5},
    )

    result = import_gemini_transcript(
        project_root=project_root,
        project_id="carolyn_and_rob",
        project_name="Carolyn and Rob",
        transcript_json_path=transcript_path,
    )

    assert result.state == "TRANSCRIPT_READY"
    normalized = json.loads(result.transcript_normalized_path.read_text(encoding="utf-8"))
    mappings = normalized["events"][0]["source_mappings"]
    assert len(mappings) == 2
    assert mappings[0]["asset_id"] == "asset-1"
    assert mappings[1]["asset_id"] == "asset-2"


def test_final_handoff_is_blocked_before_transcript_and_succeeds_after_valid_transcript(tmp_path: Path, monkeypatch) -> None:
    project_root = init_project_workspace(tmp_path / "Carolyn and Rob", "carolyn_and_rob")
    master_dir = project_root / "handoffs" / "Carolyn and Rob_MASTER_PACKAGE"
    master_dir.mkdir(parents=True, exist_ok=True)
    (master_dir / "00_START_HERE.md").write_text("start", encoding="utf-8")
    (master_dir / "PROJECT_BRIEF.md").write_text("brief", encoding="utf-8")
    (master_dir / "OUTPUT_CONTRACT.md").write_text("contract", encoding="utf-8")
    (master_dir / "V1_Carolyn and Rob_MASTER_ALL_MEDIA.mlt").write_text("<mlt/>", encoding="utf-8")
    (master_dir / "Carolyn and Rob_MASTER_AUDIO.mp3").write_bytes(b"mp3")
    (master_dir / "Carolyn and Rob_MASTER_TIMELINE_MAP.json").write_text(
        json.dumps({"items": [{"timeline_index": 0, "asset_id": "asset-1", "source_file_name": "cover.jpg", "master_start": "00:00:00.000", "master_end": "00:00:00.500"}]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (master_dir / "Carolyn and Rob_MASTER_EDIT_PLAN.json").write_text("{}", encoding="utf-8")
    (master_dir / "Carolyn and Rob_MASTER_EDIT_PLAN.csv").write_text("timeline_index\n0\n", encoding="utf-8")
    (master_dir / "Carolyn and Rob_GEMINI_AUDIO_TRANSCRIPTION_PROMPT.md").write_text("prompt", encoding="utf-8")
    (project_root / "analysis" / "handoff_manifest.json").write_text("{}", encoding="utf-8")
    (project_root / "analysis" / "local_asset_registry.json").write_text(json.dumps({"assets": []}), encoding="utf-8")
    (project_root / "analysis" / "photo_analysis_copies").mkdir(parents=True, exist_ok=True)
    (project_root / "analysis" / "video_storyboards").mkdir(parents=True, exist_ok=True)
    (project_root / "proxies").mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(
        "handoff_builder.v2.services.transcript_service._probe_audio",
        lambda _ffmpeg, _path: {"duration_seconds": 0.5, "sample_rate": 48000, "channels": 2},
    )
    try:
        create_final_analysis_handoff(
            project_root=project_root,
            project_id="carolyn_and_rob",
            project_name="Carolyn and Rob",
            ffmpeg_tools=_FakeFFmpeg(),
        )
        assert False, "expected transcript gate failure"
    except Exception as exc:
        assert "Transcript is not ready" in str(exc)

    (master_dir / "Carolyn and Rob_MASTER_AUDIO_TRANSCRIPT_ORIGINAL.json").write_text("{}", encoding="utf-8")
    (master_dir / "Carolyn and Rob_MASTER_AUDIO_TRANSCRIPT.json").write_text(
        json.dumps({"event_count": 1, "events": [{"end_time": "00:00:00.500"}]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    result = create_final_analysis_handoff(
        project_root=project_root,
        project_id="carolyn_and_rob",
        project_name="Carolyn and Rob",
        ffmpeg_tools=_FakeFFmpeg(),
    )

    assert result.state == "HANDOFF_READY"
    assert result.archive_path.exists()
