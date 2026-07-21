from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from handoff_builder import cli
from handoff_builder.v2.packages.guards import compute_sha256
from handoff_builder.v2.services.import_service import import_package_into_workspace
from handoff_builder.v2.services.voice_service import voice_delegated_technical_approval
from handoff_builder.v2.storage import apply_migrations, connect_workspace_db
from handoff_builder.v2.voice import alignment
from handoff_builder.v2.voice.alignment import align_words_for_take
from handoff_builder.v2.voice.qc import _compare_transcript
from handoff_builder.v2.workspace import init_project_workspace


def test_voice_migration_tables_exist(tmp_path: Path):
    connection = connect_workspace_db(tmp_path / "project.sqlite")
    try:
        apply_migrations(connection)
        tables = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    finally:
        connection.close()
    assert {
        "voice_runtime_snapshots",
        "voice_profile_mappings",
        "voice_jobs",
        "voice_job_versions",
        "voice_takes",
        "voice_take_qc",
        "voice_human_reviews",
        "voice_approvals",
        "voice_alignments",
        "audio_mix_profiles",
        "audio_mix_patches",
        "voice_events",
    } <= tables


def test_voice_workspace_dirs_created(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-voice")
    assert (workspace / "voice").exists()
    assert (workspace / "voice" / "runtime").exists()
    assert (workspace / "voice" / "profiles").exists()
    assert (workspace / "voice" / "reports").exists()


def test_compare_transcript_detects_missing_and_extra_words():
    missing, extra, punctuation = _compare_transcript("Warm and alive forever", "Warm and bright forever")
    assert "alive" in missing
    assert "bright" in extra
    assert punctuation is False


def test_alignment_returns_unavailable_without_local_aligner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"fake")
    monkeypatch.setattr(alignment, "_discover_whisper_cpp_runtime", lambda: None)
    result = align_words_for_take(audio_path=audio, expected_text="hello world", output_dir=tmp_path / "align")
    assert result.status == "word_alignment_unavailable"
    assert result.reason


def test_alignment_writes_voice_words_and_karaoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    audio = tmp_path / "clip.wav"
    audio.write_bytes(b"RIFFfakewav")
    runtime = {"exe_path": tmp_path / "whisper-cli.exe", "model_path": tmp_path / "ggml-small.bin"}
    runtime["exe_path"].write_bytes(b"")
    runtime["model_path"].write_bytes(b"")

    def fake_run_command(args: list[str], **_: object):
        prefix = Path(args[args.index("-of") + 1])
        prefix.with_suffix(".json").write_text(
            json.dumps(
                {
                    "transcription": [
                        {
                            "tokens": [
                                {"text": "[_BEG_]", "offsets": {"from": 0, "to": 0}, "p": 1.0},
                                {"text": " Your", "offsets": {"from": 120, "to": 310}, "p": 0.98},
                                {"text": " wedding", "offsets": {"from": 320, "to": 700}, "p": 0.95},
                                {"text": ".", "offsets": {"from": 700, "to": 700}, "p": 0.4},
                            ]
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        prefix.with_suffix(".srt").write_text("1\n00:00:00,120 --> 00:00:00,700\nYour wedding\n", encoding="utf-8")
        prefix.with_suffix(".txt").write_text("Your wedding", encoding="utf-8")
        prefix.with_suffix(".vtt").write_text("WEBVTT\n", encoding="utf-8")
        return None

    monkeypatch.setattr(alignment, "_discover_whisper_cpp_runtime", lambda: runtime)
    monkeypatch.setattr(alignment, "run_command", fake_run_command)
    result = align_words_for_take(
        audio_path=audio,
        expected_text="Your wedding",
        output_dir=tmp_path / "align",
        take_id="take-123",
        language="en-US",
    )
    assert result.status == "aligned"
    assert result.artifact_path is not None and result.artifact_path.exists()
    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["voice_take_id"] == "take-123"
    assert payload["language"] == "en"
    assert [item["word"] for item in payload["words"]] == ["Your", "wedding"]
    assert result.subtitle_path is not None and result.subtitle_path.exists()
    assert result.karaoke_ass_path is not None and result.karaoke_ass_path.exists()


def test_cli_v2_voice_help_commands_available(capsys):
    with_json = [
        ["v2", "voice-health", "--help"],
        ["v2", "voice-profiles", "--help"],
        ["v2", "voice-generate", "--help"],
        ["v2", "voice-auto-approve", "--help"],
        ["v2", "voice-qc", "--help"],
        ["v2", "voice-approve", "--help"],
        ["v2", "voice-align", "--help"],
        ["v2", "voice-mix-preview", "--help"],
        ["v2", "voice-report", "--help"],
    ]
    for argv in with_json:
        try:
            cli.main(argv)
        except SystemExit as exc:
            assert exc.code == 0
    out = capsys.readouterr().out
    assert "voice-health" in out


def test_import_package_accepts_voiceover_spec(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-voice")
    plan = {
        "schema_version": "1.0",
        "project_id": "proj-voice",
        "handoff_id": "handoff-voice",
        "handoff_sha256": "a" * 64,
        "plan_id": "plan-voice-1",
        "created_at": "2026-07-21T12:00:00Z",
        "mode": "preview",
        "assets": [{"asset_id": "asset-1", "path": "assets/source.mp4", "media_type": "video"}],
        "operations": [{"op": "video_segment", "asset_id": "asset-1", "source_in_ms": 0, "source_out_ms": 500}],
        "voiceover": {"spec_path": "voice/voiceover_spec.json"},
    }
    voiceover_spec = {
        "schema_version": "1.0",
        "voiceover": {
            "provider": "local_voicebox",
            "profile_key": "olga-polo-en-v1",
            "language": "en-US",
            "text": "Warm and alive forever.",
            "text_hash": "sha256:" + ("b" * 64),
            "engine": "qwen",
            "model_size": "0.6B",
            "takes": 3,
            "seeds": [11, 22, 33],
            "normalize_voice": True,
            "word_timestamps_required": True,
            "mix": {
                "voice_gain_percent": 100,
                "music_gain_percent": 12,
                "original_audio_gain_percent": 0,
                "ducking": False,
                "music_fade_out_ms": 350,
            },
        },
    }
    plan_bytes = json.dumps(plan, ensure_ascii=False).encode("utf-8")
    voice_bytes = json.dumps(voiceover_spec, ensure_ascii=False).encode("utf-8")
    asset_bytes = b"fake-video-placeholder"
    plan_tmp = tmp_path / "plan.tmp"
    voice_tmp = tmp_path / "voice.tmp"
    asset_tmp = tmp_path / "asset.tmp"
    plan_tmp.write_bytes(plan_bytes)
    voice_tmp.write_bytes(voice_bytes)
    asset_tmp.write_bytes(asset_bytes)
    manifest = {
        "schema_version": "1.0",
        "project_id": "proj-voice",
        "handoff_id": "handoff-voice",
        "handoff_sha256": "a" * 64,
        "created_at": "2026-07-21T12:00:00Z",
        "package_files": [
            {"path": "plans/plan-voice-1.json", "sha256": compute_sha256(plan_tmp), "size_bytes": len(plan_bytes)},
            {"path": "voice/voiceover_spec.json", "sha256": compute_sha256(voice_tmp), "size_bytes": len(voice_bytes)},
            {"path": "assets/source.mp4", "sha256": compute_sha256(asset_tmp), "size_bytes": len(asset_bytes)},
        ],
        "plans": [{"plan_id": "plan-voice-1", "path": "plans/plan-voice-1.json", "sha256": compute_sha256(plan_tmp)}],
    }
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    with zipfile.ZipFile(package_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ai_edit_package.json", json.dumps(manifest))
        archive.writestr("plans/plan-voice-1.json", plan_bytes)
        archive.writestr("voice/voiceover_spec.json", voice_bytes)
        archive.writestr("assets/source.mp4", asset_bytes)
    result = import_package_into_workspace(package_zip, workspace)
    assert result.edit_plan_id == "plan-voice-1"
    assert result.render_report_path.exists()


def test_delegated_technical_approval_prefers_lower_wer_then_duration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = init_project_workspace(tmp_path / "work", "proj-voice")
    job_root = workspace / "voice" / "jobs" / "job-1"
    (job_root / "takes" / "raw").mkdir(parents=True, exist_ok=True)
    spec = {
        "schema_version": "1.0",
        "voiceover": {
            "profile_key": "olga-polo-en-v1",
            "profile_id": "local-profile",
            "language": "en-US",
            "text": "warm and alive forever",
            "engine": "qwen",
            "model_size": "0.6B",
            "takes": 3,
            "seeds": [1, 2, 3],
            "target_duration_ms": 6000,
            "duration_tolerance_percent": 20,
            "max_auto_tempo_percent": 25,
            "normalize_voice": True,
            "word_timestamps_required": True,
            "mix": {
                "profile": "voice-100_music-12",
                "voice_gain_percent": 100,
                "music_gain_percent": 12,
                "original_audio_gain_percent": 0,
                "ducking": False,
                "music_fade_out_ms": 350,
            },
        },
    }
    spec_path = job_root / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    raw_one = job_root / "takes" / "raw" / "take1.wav"
    raw_two = job_root / "takes" / "raw" / "take2.wav"
    raw_three = job_root / "takes" / "raw" / "take3.wav"
    for path in (raw_one, raw_two, raw_three):
        path.write_bytes(b"RIFFfakewav")

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO voice_jobs (voice_job_id, project_id, profile_key, spec_path, spec_hash, target_duration_ms, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("job-1", "proj-voice", "olga-polo-en-v1", str(spec_path), "hash", 6000, "awaiting_human_approval", "2026-07-21T12:00:00Z", "2026-07-21T12:00:00Z"),
        )
        rows = [
            ("take-1", raw_one, 6100, {"warnings": [], "errors": [], "trailing_silence_ms": 300, "leading_silence_ms": 0, "clipping_detected": False, "audio_sha256": "a" * 64}),
            ("take-2", raw_two, 6005, {"warnings": [], "errors": [], "trailing_silence_ms": 450, "leading_silence_ms": 0, "clipping_detected": False, "audio_sha256": "b" * 64}),
            ("take-3", raw_three, 6500, {"warnings": ["transcript_missing_words"], "errors": [], "trailing_silence_ms": 200, "leading_silence_ms": 0, "clipping_detected": False, "audio_sha256": "c" * 64}),
        ]
        for index, (take_id, audio_path, duration_ms, qc) in enumerate(rows, start=1):
            connection.execute(
                "INSERT INTO voice_takes (voice_take_id, voice_job_id, generation_id, take_index, seed, status, response_json, raw_audio_path, audio_sha256, duration_ms, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (take_id, "job-1", f"gen-{index}", index, index, "awaiting_human_approval", "{}", str(audio_path), qc["audio_sha256"], duration_ms, "2026-07-21T12:00:00Z", "2026-07-21T12:00:00Z"),
            )
            connection.execute(
                "INSERT INTO voice_take_qc (voice_take_qc_id, voice_take_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (f"qc-{index}", take_id, json.dumps(qc), "2026-07-21T12:00:00Z"),
            )
        connection.commit()
    finally:
        connection.close()

    def fake_align_words_for_take(*, audio_path: Path, **_: object):
        output_dir = tmp_path / "align" / audio_path.stem
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact = output_dir / "voice_words.json"
        mapping = {
            "take1": ["warm", "and", "alive", "forever"],
            "take2": ["warm", "and", "alive", "forever"],
            "take3": ["warm", "alive"],
        }
        words = []
        for index, word in enumerate(mapping[audio_path.stem]):
            words.append({"index": index, "word": word, "start_ms": index * 100, "end_ms": index * 100 + 80, "confidence": 0.99})
        artifact.write_text(json.dumps({"words": words}), encoding="utf-8")
        return type(
            "AlignmentResult",
            (),
            {
                "status": "aligned",
                "reason": None,
                "artifact_path": artifact,
                "subtitle_path": None,
                "karaoke_ass_path": None,
            },
        )()

    monkeypatch.setattr("handoff_builder.v2.services.voice_service.align_words_for_take", fake_align_words_for_take)
    monkeypatch.setattr("handoff_builder.v2.services.voice_service._apply_atempo", lambda *args, **kwargs: None)
    result = voice_delegated_technical_approval(workspace, voice_job_id="job-1")
    assert result["take_id"] == "take-2"
    assert result["status"] == "approved"
    assert result["comparative_metrics"][0]["take_id"] == "take-2"
