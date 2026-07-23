from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

from handoff_builder.ffmpeg_tools import run_command
from handoff_builder.utils import find_executable

from ..audio import render_voice_mix_preview
from ..common import stable_v2_id, utc_now_iso
from ..packages.guards import compute_sha256
from ..plans.schema import validate_payload
from ..storage import apply_migrations, connect_workspace_db
from ..workspace import load_project_config
from ..voice import VoiceStudioRepository, VoiceboxClient
from ..voice.alignment import align_words_for_take
from ..voice.qc import inspect_generated_audio


DEFAULT_VOICEBOX_URL = "http://127.0.0.1:17493"
DEFAULT_DURATION_TOLERANCE_PERCENT = 3.0
MAX_AUTO_TEMPO_PERCENT = 8.0


def voice_health(*, base_url: str = DEFAULT_VOICEBOX_URL) -> dict[str, Any]:
    client = VoiceboxClient(base_url)
    info = client.health_check()
    return asdict(info)


def voice_profiles(*, base_url: str = DEFAULT_VOICEBOX_URL) -> list[dict[str, Any]]:
    client = VoiceboxClient(base_url)
    return [asdict(item) for item in client.list_profiles()]


def voice_profile_map(workspace: Path, *, profile_key: str, profile_id: str, base_url: str = DEFAULT_VOICEBOX_URL) -> dict[str, Any]:
    client = VoiceboxClient(base_url)
    profile = next((item for item in client.list_profiles() if item.profile_id == profile_id), None)
    if profile is None:
        raise ValueError(f"Profile not found in runtime: {profile_id}")
    project_root = workspace.resolve()
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        repo.upsert_profile_mapping(
            profile_key=profile_key,
            profile_id=profile.profile_id,
            profile_name=profile.name,
            language=profile.language,
            default_engine=profile.default_engine,
        )
        connection.commit()
    finally:
        connection.close()
    return {
        "profile_key": profile_key,
        "profile_id": profile.profile_id,
        "name": profile.name,
        "language": profile.language,
        "default_engine": profile.default_engine,
    }


def voice_profile_samples(
    workspace: Path | None = None,
    *,
    profile_key: str | None = None,
    profile_id: str | None = None,
    base_url: str = DEFAULT_VOICEBOX_URL,
) -> dict[str, Any]:
    client = VoiceboxClient(base_url)
    resolved_profile_id = profile_id
    if profile_key:
        if workspace is None:
            raise ValueError("--workspace is required when using --profile-key")
        resolved_profile_id = _resolve_profile_mapping(workspace.resolve(), profile_key, client)["profile_id"]
    if not resolved_profile_id:
        raise ValueError("Either profile_key or profile_id is required.")
    return {
        "profile_id": resolved_profile_id,
        "samples": client.get_profile_samples(resolved_profile_id),
    }


def voice_generate(
    workspace: Path,
    *,
    profile_key: str,
    text: str,
    language: str = "en-US",
    takes: int = 3,
    seeds: list[int] | None = None,
    engine: str = "qwen",
    model_size: str = "0.6B",
    instruct: str | None = None,
    target_duration_ms: int | None = None,
    duration_tolerance_percent: float = 3.0,
    max_auto_tempo_percent: float = 8.0,
    normalize_voice: bool = True,
    word_timestamps_required: bool = True,
    mix: dict[str, Any] | None = None,
    base_url: str = DEFAULT_VOICEBOX_URL,
) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    duration_tolerance_percent, max_auto_tempo_percent = _effective_duration_policy(
        duration_tolerance_percent,
        max_auto_tempo_percent,
    )
    runtime_client = VoiceboxClient(base_url)
    runtime_info = runtime_client.health_check()
    if runtime_info.status != "healthy":
        raise RuntimeError(f"Voicebox runtime is not healthy: {runtime_info.status}")
    if takes < 1 or takes > 5:
        raise ValueError("takes must be between 1 and 5")
    if not text.strip():
        raise ValueError("text must not be empty")
    if seeds is None or not seeds:
        seeds = [3471 + index for index in range(takes)]
    if len(seeds) < takes:
        raise ValueError("Not enough seeds were provided for the requested take count.")

    resolved = _resolve_profile_mapping(workspace_root, profile_key, runtime_client)
    mix_payload = _normalize_mix_payload(
        mix
        or {
            "profile": "voice-100_music-12",
            "voice_gain_percent": 100,
            "music_gain_percent": 12,
            "original_audio_gain_percent": 0,
            "ducking": False,
            "music_fade_out_ms": 350,
        }
    )
    spec = {
        "schema_version": "1.0",
        "voiceover": {
            "provider": "local_voicebox",
            "profile_key": profile_key,
            "profile_id": resolved["profile_id"],
            "language": language,
            "text": text,
            "text_hash": f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}",
            "engine": engine,
            "model_size": model_size,
            "delivery": {
                "preset": "custom",
                "instruct": instruct,
                "pronunciation_notes": [],
                "pause_policy": "natural",
            },
            "takes": takes,
            "seeds": seeds[:takes],
            "target_duration_ms": target_duration_ms,
            "duration_tolerance_percent": duration_tolerance_percent,
            "max_auto_tempo_percent": max_auto_tempo_percent,
            "normalize_voice": normalize_voice,
            "word_timestamps_required": word_timestamps_required,
            "mix": mix_payload,
        },
    }
    return _run_voice_job(workspace_root, spec=spec, profile_key=profile_key, base_url=base_url)


def voice_generate_from_plan(
    workspace: Path,
    *,
    plan_id: str,
    base_url: str = DEFAULT_VOICEBOX_URL,
) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    plan_payload, voiceover_payload = _load_imported_voiceover_spec(workspace_root, plan_id)
    voiceover = dict(voiceover_payload["voiceover"])
    return voice_generate(
        workspace_root,
        profile_key=str(voiceover["profile_key"]),
        text=str(voiceover["text"]),
        language=str(voiceover.get("language") or "en-US"),
        takes=int(voiceover.get("takes") or 3),
        seeds=[int(item) for item in voiceover.get("seeds") or []],
        engine=str(voiceover.get("engine") or "qwen"),
        model_size=str(voiceover.get("model_size") or "0.6B"),
        instruct=(voiceover.get("delivery") or {}).get("instruct"),
        target_duration_ms=voiceover.get("target_duration_ms"),
        duration_tolerance_percent=float(voiceover.get("duration_tolerance_percent") or 3.0),
        max_auto_tempo_percent=float(voiceover.get("max_auto_tempo_percent") or 8.0),
        normalize_voice=bool(voiceover.get("normalize_voice", True)),
        word_timestamps_required=bool(voiceover.get("word_timestamps_required", True)),
        mix=dict(voiceover.get("mix") or {}),
        base_url=base_url,
    )


def voice_job_status(workspace: Path, voice_job_id: str) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        job = dict(repo.get_voice_job(voice_job_id))
        spec = json.loads(Path(job["spec_path"]).read_text(encoding="utf-8"))
        takes = []
        for row in repo.list_takes(voice_job_id):
            take = dict(row)
            qc = repo.get_take_qc(take["voice_take_id"])
            alignment = repo.get_alignment(take["voice_take_id"])
            take["qc"] = json.loads(qc["payload_json"]) if qc else None
            take["alignment"] = json.loads(alignment["payload_json"]) if alignment else None
            takes.append(take)
        approval = repo.get_primary_approval(voice_job_id)
        mix_profile = repo.get_mix_profile(voice_job_id)
        mix_patches = [dict(row) | {"payload": json.loads(row["payload_json"])} for row in repo.list_mix_patches(voice_job_id)]
        return {
            "job": job,
            "spec": spec,
            "takes": takes,
            "primary_approval": _deserialize_approval(approval),
            "mix_profile": json.loads(mix_profile["payload_json"]) if mix_profile else None,
            "mix_patches": mix_patches,
        }
    finally:
        connection.close()


def list_voice_jobs(workspace: Path) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    config = load_project_config(workspace_root)
    project_id = str(config["project_id"])
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        jobs: list[dict[str, Any]] = []
        for row in repo.list_voice_jobs(project_id):
            job = dict(row)
            takes = repo.list_takes(str(job["voice_job_id"]))
            approval = repo.get_primary_approval(str(job["voice_job_id"]))
            mix_patches = repo.list_mix_patches(str(job["voice_job_id"]))
            job["take_count"] = len(takes)
            job["has_primary_approval"] = approval is not None
            job["mix_patch_count"] = len(mix_patches)
            jobs.append(job)
        return {
            "workspace": str(workspace_root),
            "project_id": project_id,
            "jobs": jobs,
        }
    finally:
        connection.close()


def voice_take_qc(workspace: Path, take_id: str) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        repo = VoiceStudioRepository(connection)
        take = dict(repo.get_take(take_id))
        qc = repo.get_take_qc(take_id)
        return {"take": take, "qc": json.loads(qc["payload_json"]) if qc else None}
    finally:
        connection.close()


def voice_approve(
    workspace: Path,
    *,
    take_id: str,
    similarity: int,
    naturalness: int,
    pronunciation: int,
    pacing: int,
    emotion_style_fit: int,
    artifacts: str,
    approve: bool,
    notes: str = "",
) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    ffmpeg_path = find_executable("ffmpeg", workspace_root.parents[0] if workspace_root.parents else None)
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        take = dict(repo.get_take(take_id))
        job = dict(repo.get_voice_job(str(take["voice_job_id"])))
        spec = json.loads(Path(job["spec_path"]).read_text(encoding="utf-8"))
        review_payload = {
            "approval_mode": "human_review",
            "similarity_to_olga": similarity,
            "naturalness": naturalness,
            "pronunciation": pronunciation,
            "pacing": pacing,
            "emotion_style_fit": emotion_style_fit,
            "artifacts": artifacts,
            "approve": approve,
            "notes": notes,
        }
        connection.execute("BEGIN")
        repo.add_review(take_id=take_id, review_payload=review_payload)
        connection.commit()
        if not approve:
            return {"take_id": take_id, "status": "rejected", "review": review_payload}
        return _apply_take_approval(
            repo=repo,
            take=take,
            spec=spec,
            ffmpeg_path=ffmpeg_path,
            review_payload=review_payload,
            approval_mode="human_review",
        )
    finally:
        connection.close()


def voice_delegated_technical_approval(
    workspace: Path,
    *,
    voice_job_id: str,
    notes: str = "",
) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    ffmpeg_path = find_executable("ffmpeg", workspace_root.parents[0] if workspace_root.parents else None)
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        job = dict(repo.get_voice_job(voice_job_id))
        spec = json.loads(Path(job["spec_path"]).read_text(encoding="utf-8"))
        takes = [dict(row) for row in repo.list_takes(voice_job_id)]
        if not takes:
            raise ValueError(f"No takes found for voice job {voice_job_id}")
        evaluated = [
            _evaluate_take_for_delegated_approval(
                take=take,
                qc_row=repo.get_take_qc(str(take["voice_take_id"])),
                job_root=Path(job["spec_path"]).parent,
                spec=spec,
            )
            for take in takes
        ]
        ranked = sorted(
            evaluated,
            key=lambda item: (
                1 if not item["eligible_for_approval"] else 0,
                1 if item["technical_error"] else 0,
                item["wer"],
                item["duration_delta_percent"],
                item["trailing_silence_ms"],
                1 if item["clipping_detected"] else 0,
                item["warning_count"],
                item["take_index"],
            ),
        )
        eligible = [item for item in ranked if item["eligible_for_approval"]]
        chosen = eligible[0] if eligible else ranked[0]
        review_payload = {
            "approval_mode": "delegated_technical_approval",
            "approve": bool(eligible),
            "notes": notes or "Delegated technical approval based on local transcription, duration, silence, clipping, and render safety metrics.",
            "comparative_metrics": ranked,
            "tie_breaker_order": [
                "eligible_for_approval",
                "technical_error",
                "wer",
                "duration_delta_percent",
                "trailing_silence_ms",
                "clipping_detected",
                "warning_count",
                "take_index",
            ],
        }
        if not eligible:
            review_payload["rejection_reason"] = "no_take_met_exact_text_and_duration_policy"
            connection.execute("BEGIN")
            repo.add_review(take_id=str(chosen["take_id"]), review_payload=review_payload)
            repo.set_approval(
                voice_job_id=voice_job_id,
                take_id=str(chosen["take_id"]),
                approved=False,
                approval_payload={
                    "approval_mode": "delegated_technical_approval",
                    "review": review_payload,
                    "duration_result": {
                        "target_duration_ms": spec["voiceover"].get("target_duration_ms"),
                        "actual_duration_ms": chosen["duration_ms"],
                        "tempo_applied": False,
                        "delta_percent": round(chosen["duration_delta_percent"], 3),
                    },
                    "approved_at": utc_now_iso(),
                },
            )
            repo.update_voice_job_status(voice_job_id, "voiceover_needs_rewrite")
            repo.add_event(
                voice_job_id=voice_job_id,
                event_type="voiceover_needs_rewrite",
                payload={
                    "take_id": str(chosen["take_id"]),
                    "approval_mode": "delegated_technical_approval",
                    "reason": "no_take_met_exact_text_and_duration_policy",
                },
            )
            connection.commit()
            return {
                "take_id": str(chosen["take_id"]),
                "status": "voiceover_needs_rewrite",
                "comparative_metrics": ranked,
                "reason": "no_take_met_exact_text_and_duration_policy",
            }
        connection.execute("BEGIN")
        repo.add_review(take_id=str(chosen["take_id"]), review_payload=review_payload)
        connection.commit()
        result = _apply_take_approval(
            repo=repo,
            take=dict(repo.get_take(str(chosen["take_id"]))),
            spec=spec,
            ffmpeg_path=ffmpeg_path,
            review_payload=review_payload,
            approval_mode="delegated_technical_approval",
        )
        if result["status"] == "approved":
            alignment = voice_align(workspace_root, take_id=str(chosen["take_id"]))
            result["alignment"] = alignment
        result["comparative_metrics"] = ranked
        return result
    finally:
        connection.close()


def voice_align(workspace: Path, *, take_id: str) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        take = dict(repo.get_take(take_id))
        job = dict(repo.get_voice_job(str(take["voice_job_id"])))
        spec = json.loads(Path(job["spec_path"]).read_text(encoding="utf-8"))
        audio_path = Path(take["normalized_audio_path"] or take["raw_audio_path"])
        result = align_words_for_take(
            audio_path=audio_path,
            expected_text=str(spec["voiceover"]["text"]),
            output_dir=Path(job["spec_path"]).parent / "alignment",
            take_id=take_id,
            language=str(spec["voiceover"].get("language") or "en"),
        )
        payload = {
            "status": result.status,
            "reason": result.reason,
            "artifact_path": str(result.artifact_path) if result.artifact_path else None,
            "subtitle_path": str(result.subtitle_path) if result.subtitle_path else None,
            "karaoke_ass_path": str(result.karaoke_ass_path) if result.karaoke_ass_path else None,
            "audio_sha256": compute_sha256(audio_path) if audio_path.exists() else None,
        }
        connection.execute("BEGIN")
        repo.set_alignment(
            take_id=take_id,
            status=result.status,
            artifact_path=result.artifact_path,
            payload=payload,
        )
        repo.add_event(
            voice_job_id=str(take["voice_job_id"]),
            event_type="alignment_attempted",
            payload={"take_id": take_id, **payload},
        )
        connection.commit()
        return payload
    finally:
        connection.close()


def voice_mix_preview(
    workspace: Path,
    *,
    take_id: str,
    video_path: Path,
    music_path: Path | None = None,
    voice_gain_percent: float = 100,
    music_gain_percent: float = 12,
    original_audio_gain_percent: float = 0,
    ducking: bool = False,
    music_fade_out_ms: int = 350,
) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    ffmpeg_path = find_executable("ffmpeg", workspace_root.parents[0] if workspace_root.parents else None)
    ffprobe_path = find_executable("ffprobe", workspace_root.parents[0] if workspace_root.parents else None)
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        take = dict(repo.get_take(take_id))
        job = dict(repo.get_voice_job(str(take["voice_job_id"])))
        approval = repo.get_primary_approval(str(take["voice_job_id"]))
        if approval is None or str(approval["voice_take_id"]) != take_id:
            raise ValueError("Preview voice mix requires the approved primary take.")
        audio_path = Path(take["normalized_audio_path"] or take["raw_audio_path"])
        approved_voice_sha256 = compute_sha256(audio_path) if audio_path.exists() else ""
        version = len(repo.list_mix_patches(str(take["voice_job_id"]))) + 1
        output_dir = Path(job["spec_path"]).parent / "renders"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"mix_v{version:03d}_{take_id}.mp4"
        result = render_voice_mix_preview(
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            video_path=video_path,
            voice_path=audio_path,
            music_path=music_path,
            output_path=output_path,
            voice_gain_percent=voice_gain_percent,
            music_gain_percent=music_gain_percent,
            original_audio_gain_percent=original_audio_gain_percent,
            ducking=ducking,
            music_fade_out_ms=music_fade_out_ms,
        )
        patch_payload = {
            "patch_type": "mix_render",
            "version_number": version,
            "video_path": str(video_path),
            "music_path": str(music_path) if music_path else None,
            "voice_take_id": take_id,
            "approved_voice_sha256": approved_voice_sha256,
            "voice_gain_percent": float(voice_gain_percent),
            "music_gain_percent": float(music_gain_percent),
            "original_audio_gain_percent": float(original_audio_gain_percent),
            "ducking": ducking,
            "music_fade_out_ms": music_fade_out_ms,
            "output_path": str(result.output_path),
            "ffmpeg_command_path": str(result.ffmpeg_command_path),
            "render_plan_path": str(result.render_plan_path),
            "stem_paths": {name: str(path) for name, path in result.stem_paths.items()},
            "metrics": result.metrics,
        }
        connection.execute("BEGIN")
        patch_id = repo.add_mix_patch(voice_job_id=str(take["voice_job_id"]), patch_payload=patch_payload)
        repo.add_event(
            voice_job_id=str(take["voice_job_id"]),
            event_type="mix_preview_rendered",
            payload={"take_id": take_id, "patch_id": patch_id, **patch_payload},
        )
        connection.commit()
        return {
            "take_id": take_id,
            "patch_id": patch_id,
            "version_number": version,
            "output_path": str(result.output_path),
            "ffmpeg_command_path": str(result.ffmpeg_command_path),
            "render_plan_path": str(result.render_plan_path),
            "stem_paths": {name: str(path) for name, path in result.stem_paths.items()},
            "metrics": result.metrics,
            "approved_voice_sha256": approved_voice_sha256,
        }
    finally:
        connection.close()


def voice_music_patch(
    workspace: Path,
    *,
    voice_job_id: str,
    video_path: Path,
    music_path: Path | None,
    reduce_music_percent: float | None = None,
    music_gain_percent: float | None = None,
    voice_gain_percent: float | None = None,
    original_audio_gain_percent: float | None = None,
    ducking: bool | None = None,
    music_fade_out_ms: int | None = None,
) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        approval = repo.get_primary_approval(voice_job_id)
        if approval is None:
            raise ValueError("Immutable music-only patch requires an approved take.")
        take_id = str(approval["voice_take_id"])
        mix_profile_row = repo.get_mix_profile(voice_job_id)
        if mix_profile_row is None:
            raise ValueError("No audio mix profile exists for this voice job.")
        base_mix = json.loads(mix_profile_row["payload_json"])
        latest_patch_rows = repo.list_mix_patches(voice_job_id)
        if latest_patch_rows:
            base_render = max(
                (json.loads(row["payload_json"]) for row in latest_patch_rows),
                key=lambda payload: int(payload.get("version_number") or 0),
            )
            current_music_gain = float(base_render["music_gain_percent"])
            current_voice_gain = float(base_render["voice_gain_percent"])
            current_original_gain = float(base_render["original_audio_gain_percent"])
            current_ducking = bool(base_render["ducking"])
            current_fade = int(base_render["music_fade_out_ms"])
        else:
            current_music_gain = float(base_mix["music_gain_percent"])
            current_voice_gain = float(base_mix["voice_gain_percent"])
            current_original_gain = float(base_mix["original_audio_gain_percent"])
            current_ducking = bool(base_mix["ducking"])
            current_fade = int(base_mix.get("music_fade_out_ms") or 350)
        new_music_gain = float(music_gain_percent) if music_gain_percent is not None else current_music_gain
        if reduce_music_percent is not None:
            new_music_gain = round(current_music_gain * (1 - (float(reduce_music_percent) / 100.0)), 4)
        if new_music_gain < 0:
            raise ValueError("music_gain_percent cannot be negative.")
        next_voice_gain = current_voice_gain if voice_gain_percent is None else float(voice_gain_percent)
        next_original_gain = current_original_gain if original_audio_gain_percent is None else float(original_audio_gain_percent)
        next_ducking = current_ducking if ducking is None else bool(ducking)
        next_fade = current_fade if music_fade_out_ms is None else int(music_fade_out_ms)
        if next_voice_gain != current_voice_gain or next_original_gain != current_original_gain or next_ducking != current_ducking or next_fade != current_fade:
            raise ValueError("Immutable music-only patch may change only music gain.")
        result = voice_mix_preview(
            workspace_root,
            take_id=take_id,
            video_path=video_path,
            music_path=music_path,
            voice_gain_percent=current_voice_gain,
            music_gain_percent=new_music_gain,
            original_audio_gain_percent=current_original_gain,
            ducking=current_ducking,
            music_fade_out_ms=current_fade,
        )
        result["music_patch"] = {
            "base_music_gain_percent": current_music_gain,
            "new_music_gain_percent": new_music_gain,
            "reduce_music_percent": reduce_music_percent,
            "voice_gain_unchanged": True,
            "approved_voice_sha256_unchanged": True,
        }
        return result
    finally:
        connection.close()


def voice_report(workspace: Path, *, voice_job_id: str) -> dict[str, Any]:
    workspace_root = workspace.resolve()
    status = voice_job_status(workspace_root, voice_job_id)
    report_path = workspace_root / "voice" / "reports" / f"{voice_job_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": utc_now_iso(),
        **status,
    }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"report_path": str(report_path), "report": payload}


def _run_voice_job(workspace_root: Path, *, spec: dict[str, Any], profile_key: str, base_url: str) -> dict[str, Any]:
    config = load_project_config(workspace_root)
    project_id = str(config["project_id"])
    runtime_client = VoiceboxClient(base_url)
    runtime_info = runtime_client.health_check()
    resolved = _resolve_profile_mapping(workspace_root, profile_key, runtime_client)
    spec = json.loads(json.dumps(spec))
    spec["voiceover"]["profile_id"] = resolved["profile_id"]
    spec["voiceover"]["mix"] = _normalize_mix_payload(spec["voiceover"].get("mix"))

    takes = int(spec["voiceover"].get("takes") or 3)
    seeds = [int(item) for item in spec["voiceover"].get("seeds") or []]
    if not seeds:
        seeds = [3471 + index for index in range(takes)]
        spec["voiceover"]["seeds"] = seeds

    job_id = stable_v2_id(project_id, profile_key, utc_now_iso(), "voice-job", length=20)
    job_root = workspace_root / "voice" / "jobs" / job_id
    requests_dir = job_root / "requests"
    responses_dir = job_root / "responses"
    raw_dir = job_root / "takes" / "raw"
    qc_dir = job_root / "qc"
    for directory in (
        requests_dir,
        responses_dir,
        raw_dir,
        qc_dir,
        job_root / "alignment",
        job_root / "approval",
        job_root / "takes" / "normalized",
        job_root / "renders",
    ):
        directory.mkdir(parents=True, exist_ok=True)
    spec_path = job_root / "spec.json"
    spec_path.write_text(json.dumps(spec, ensure_ascii=False, indent=2), encoding="utf-8")
    spec_hash = compute_sha256(spec_path)

    ffmpeg_path = find_executable("ffmpeg", workspace_root.parents[0] if workspace_root.parents else None)
    ffprobe_path = find_executable("ffprobe", workspace_root.parents[0] if workspace_root.parents else None)

    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        repo.add_runtime_snapshot(base_url=base_url, payload=asdict(runtime_info))
        repo.create_voice_job(
            job_id=job_id,
            project_id=project_id,
            profile_key=profile_key,
            spec_path=spec_path,
            spec_hash=spec_hash,
            target_duration_ms=spec["voiceover"].get("target_duration_ms"),
            status="generation_running",
        )
        repo.add_voice_job_version(
            version_id=stable_v2_id(job_id, "v1", length=20),
            voice_job_id=job_id,
            version_number=1,
            payload_path=spec_path,
            payload_hash=spec_hash,
        )
        repo.set_mix_profile(
            voice_job_id=job_id,
            profile_key=str(spec["voiceover"]["mix"].get("profile") or "custom"),
            payload=spec["voiceover"]["mix"],
        )
        connection.commit()

        for index, seed in enumerate(seeds[:takes], start=1):
            request_started = time.time()
            request_payload = {
                "profile_id": spec["voiceover"]["profile_id"],
                "text": spec["voiceover"]["text"],
                "language": spec["voiceover"]["language"],
                "seed": seed,
                "engine": spec["voiceover"]["engine"],
                "model_size": spec["voiceover"]["model_size"],
                "instruct": (spec["voiceover"].get("delivery") or {}).get("instruct"),
                "normalize": bool(spec["voiceover"].get("normalize_voice", True)),
            }
            (requests_dir / f"generation_{index:02d}.json").write_text(
                json.dumps(request_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            generation = runtime_client.generate_take(_build_generation_request(spec["voiceover"]), seed=seed)
            take_id = stable_v2_id(job_id, generation.generation_id, length=20)
            connection.execute("BEGIN")
            repo.create_take(
                take_id=take_id,
                voice_job_id=job_id,
                generation_id=generation.generation_id,
                take_index=index,
                seed=seed,
                raw_response_json=generation.raw,
                status=generation.status,
            )
            repo.add_event(
                voice_job_id=job_id,
                event_type="generation_started",
                payload={"take_id": take_id, "generation_id": generation.generation_id, "seed": seed},
            )
            connection.commit()

            resolved_generation = runtime_client.wait_for_generation(generation.generation_id)
            response_path = responses_dir / f"generation_{index:02d}.json"
            response_path.write_text(json.dumps(resolved_generation.raw, ensure_ascii=False, indent=2), encoding="utf-8")
            if resolved_generation.status != "completed":
                connection.execute("BEGIN")
                repo.update_take_artifact(take_id=take_id, status=resolved_generation.status)
                repo.add_event(
                    voice_job_id=job_id,
                    event_type="generation_failed",
                    payload={"take_id": take_id, "generation_id": generation.generation_id, "status": resolved_generation.status},
                )
                connection.commit()
                continue

            audio_path = raw_dir / f"take_{index:02d}_{generation.generation_id}.wav"
            runtime_client.download_audio(generation.generation_id, audio_path)
            try:
                qc = inspect_generated_audio(
                    ffmpeg_path=ffmpeg_path,
                    ffprobe_path=ffprobe_path,
                    client=runtime_client,
                    audio_path=audio_path,
                    expected_text=str(spec["voiceover"]["text"]),
                    generation_latency_ms=int(round((time.time() - request_started) * 1000)),
                )
                qc_payload = asdict(qc)
                take_status = "awaiting_human_approval"
                event_audio_sha = qc.audio_sha256
            except Exception as exc:
                event_audio_sha = compute_sha256(audio_path)
                qc_payload = {
                    "codec": None,
                    "container": None,
                    "sample_rate": None,
                    "channels": None,
                    "duration_ms": 0,
                    "integrated_lufs": None,
                    "sample_peak_dbfs": None,
                    "clipping_detected": False,
                    "leading_silence_ms": None,
                    "trailing_silence_ms": None,
                    "transcript": "",
                    "transcript_exact_match": False,
                    "missing_words": [],
                    "extra_words": [],
                    "punctuation_different": False,
                    "generation_latency_ms": int(round((time.time() - request_started) * 1000)),
                    "audio_sha256": event_audio_sha,
                    "warnings": ["qc_failed"],
                    "errors": [str(exc)],
                }
                take_status = "qc_failed"
            (qc_dir / f"{take_id}.json").write_text(json.dumps(qc_payload, ensure_ascii=False, indent=2), encoding="utf-8")
            connection.execute("BEGIN")
            repo.update_take_artifact(
                take_id=take_id,
                status=take_status,
                raw_audio_path=audio_path,
                audio_sha256=str(qc_payload["audio_sha256"]),
                duration_ms=int(qc_payload["duration_ms"]),
            )
            repo.set_take_qc(take_id=take_id, payload=qc_payload)
            repo.add_event(
                voice_job_id=job_id,
                event_type="generation_completed",
                payload={"take_id": take_id, "generation_id": generation.generation_id, "audio_sha256": event_audio_sha},
            )
            connection.commit()

        connection.execute("BEGIN")
        repo.update_voice_job_status(job_id, "awaiting_human_approval")
        connection.commit()
    finally:
        connection.close()
    return voice_job_status(workspace_root, job_id)


def _resolve_profile_mapping(workspace_root: Path, profile_key: str, client: VoiceboxClient) -> dict[str, Any]:
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        apply_migrations(connection)
        repo = VoiceStudioRepository(connection)
        mapping = repo.get_profile_mapping(profile_key)
        if mapping is not None:
            return dict(mapping)
        profiles = client.list_profiles()
        auto = None
        if profile_key == "olga-polo-en-v1":
            matches = [profile for profile in profiles if profile.name.lower() == "olga" and profile.language.lower().startswith("en")]
            if len(matches) == 1:
                auto = matches[0]
        if auto is None:
            raise ValueError(f"Profile key is not mapped: {profile_key}")
        repo.upsert_profile_mapping(
            profile_key=profile_key,
            profile_id=auto.profile_id,
            profile_name=auto.name,
            language=auto.language,
            default_engine=auto.default_engine,
        )
        connection.commit()
        return {
            "profile_key": profile_key,
            "profile_id": auto.profile_id,
            "profile_name": auto.name,
            "language": auto.language,
            "default_engine": auto.default_engine,
        }
    finally:
        connection.close()


def _load_imported_voiceover_spec(workspace_root: Path, plan_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    connection = connect_workspace_db(workspace_root / "project.sqlite")
    try:
        plan_row = connection.execute(
            "SELECT plan_path, package_id FROM edit_plans WHERE edit_plan_id = ?",
            (plan_id,),
        ).fetchone()
        if plan_row is None:
            raise KeyError(f"Unknown plan: {plan_id}")
        package_row = connection.execute(
            "SELECT extracted_root FROM ai_packages WHERE package_id = ?",
            (plan_row["package_id"],),
        ).fetchone()
        if package_row is None:
            raise KeyError(f"Missing package for plan: {plan_id}")
        plan_payload = json.loads(Path(plan_row["plan_path"]).read_text(encoding="utf-8"))
        voiceover_section = plan_payload.get("voiceover")
        if not voiceover_section:
            raise ValueError(f"Plan {plan_id} does not declare voiceover.spec_path.")
        package_root = Path(package_row["extracted_root"]).resolve()
        spec_path = (package_root / str(voiceover_section["spec_path"])).resolve()
        if package_root not in spec_path.parents:
            raise ValueError("voiceover_spec path escapes the imported package root.")
        voiceover_payload = json.loads(spec_path.read_text(encoding="utf-8"))
        validate_payload("voiceover_spec", str(voiceover_payload["schema_version"]), voiceover_payload)
        return plan_payload, voiceover_payload
    finally:
        connection.close()


def _build_generation_request(voiceover: dict[str, Any]):
    from ..voice.models import VoiceGenerationRequest

    return VoiceGenerationRequest(
        profile_key=str(voiceover["profile_key"]),
        profile_id=str(voiceover["profile_id"]),
        text=str(voiceover["text"]),
        language=str(voiceover["language"]),
        takes=int(voiceover["takes"]),
        seeds=tuple(int(item) for item in voiceover["seeds"]),
        engine=str(voiceover["engine"]),
        model_size=str(voiceover["model_size"]),
        instruct=(voiceover.get("delivery") or {}).get("instruct"),
        target_duration_ms=voiceover.get("target_duration_ms"),
        duration_tolerance_percent=float(voiceover.get("duration_tolerance_percent") or 3.0),
        max_auto_tempo_percent=float(voiceover.get("max_auto_tempo_percent") or 8.0),
        normalize_voice=bool(voiceover.get("normalize_voice", True)),
        word_timestamps_required=bool(voiceover.get("word_timestamps_required", True)),
        mix=dict(voiceover.get("mix") or {}),
        raw_spec={"voiceover": voiceover},
    )


def _apply_take_approval(
    *,
    repo: VoiceStudioRepository,
    take: dict[str, Any],
    spec: dict[str, Any],
    ffmpeg_path: str,
    review_payload: dict[str, Any],
    approval_mode: str,
) -> dict[str, Any]:
    normalized_path = None
    target_duration_ms = spec["voiceover"].get("target_duration_ms")
    tolerance, max_auto = _effective_duration_policy(
        spec["voiceover"].get("duration_tolerance_percent"),
        spec["voiceover"].get("max_auto_tempo_percent"),
    )
    duration_ms = int(take.get("duration_ms") or 0)
    source_audio_path = Path(take["raw_audio_path"])
    status = "approved"
    duration_result: dict[str, Any] = {
        "target_duration_ms": target_duration_ms,
        "actual_duration_ms": duration_ms,
        "tempo_applied": False,
        "duration_tolerance_percent": tolerance,
        "max_auto_tempo_percent": max_auto,
        "original_audio_sha256": compute_sha256(source_audio_path) if source_audio_path.exists() else None,
    }
    corrected_qc: dict[str, Any] | None = None
    if target_duration_ms and duration_ms > 0:
        delta_percent = abs((duration_ms - target_duration_ms) / target_duration_ms * 100)
        duration_result["delta_percent"] = round(delta_percent, 3)
        if delta_percent > tolerance and delta_percent <= max_auto:
            normalized_dir = Path(repo.get_voice_job(str(take["voice_job_id"]))["spec_path"]).parent / "takes" / "normalized"
            normalized_dir.mkdir(parents=True, exist_ok=True)
            normalized_path = normalized_dir / f"{take['voice_take_id']}_approved.wav"
            factor = duration_ms / target_duration_ms
            _apply_atempo(ffmpeg_path, source_audio_path, normalized_path, factor)
            duration_result["tempo_applied"] = True
            duration_result["atempo_factor"] = round(factor, 6)
            corrected_qc = _inspect_approved_audio(
                repo=repo,
                take=take,
                spec=spec,
                audio_path=normalized_path,
            )
            duration_result["corrected_audio_sha256"] = corrected_qc["audio_sha256"]
            duration_result["corrected_duration_ms"] = corrected_qc["duration_ms"]
            duration_result["corrected_qc"] = corrected_qc
        elif delta_percent > max_auto:
            status = "voiceover_needs_rewrite"
    if status == "approved" and corrected_qc is not None:
        corrected_errors = list(corrected_qc.get("errors") or [])
        corrected_exact_match = bool(corrected_qc.get("transcript_exact_match"))
        if corrected_errors or not corrected_exact_match:
            status = "voiceover_needs_rewrite"
            duration_result["approval_blocker"] = {
                "reason": "corrected_audio_failed_qc",
                "transcript_exact_match": corrected_exact_match,
                "error_count": len(corrected_errors),
                "warnings": list(corrected_qc.get("warnings") or []),
            }
    approved_audio_path = normalized_path or source_audio_path
    duration_result["approved_audio_sha256"] = (
        duration_result.get("corrected_audio_sha256")
        or (compute_sha256(approved_audio_path) if approved_audio_path.exists() else None)
    )

    approval_payload = {
        "approval_mode": approval_mode,
        "review": review_payload,
        "duration_result": duration_result,
        "approved_at": utc_now_iso(),
    }
    repo.connection.execute("BEGIN")
    repo.set_approval(
        voice_job_id=str(take["voice_job_id"]),
        take_id=str(take["voice_take_id"]),
        approved=(status == "approved"),
        approval_payload=approval_payload,
    )
    repo.update_take_artifact(
        take_id=str(take["voice_take_id"]),
        status=status,
        normalized_audio_path=normalized_path,
    )
    repo.update_voice_job_status(str(take["voice_job_id"]), status if status != "approved" else "approved")
    repo.add_event(
        voice_job_id=str(take["voice_job_id"]),
        event_type="take_approved" if status == "approved" else "voiceover_needs_rewrite",
        payload={
            "take_id": str(take["voice_take_id"]),
            "status": status,
            "duration_result": duration_result,
            "approval_mode": approval_mode,
        },
    )
    repo.connection.commit()
    return {
        "take_id": str(take["voice_take_id"]),
        "status": status,
        "normalized_audio_path": str(normalized_path) if normalized_path else None,
        "duration_result": duration_result,
    }


def _evaluate_take_for_delegated_approval(
    *,
    take: dict[str, Any],
    qc_row: Any,
    job_root: Path,
    spec: dict[str, Any],
) -> dict[str, Any]:
    qc = json.loads(qc_row["payload_json"]) if qc_row else {}
    transcript_source = "voicebox_transcribe"
    transcript_text = str(qc.get("transcript") or "")
    local_alignment_dir = job_root / "alignment" / f"delegated_{take['voice_take_id']}"
    local_alignment = align_words_for_take(
        audio_path=Path(take["normalized_audio_path"] or take["raw_audio_path"]),
        expected_text=str(spec["voiceover"]["text"]),
        output_dir=local_alignment_dir,
        take_id=str(take["voice_take_id"]),
        language=str(spec["voiceover"].get("language") or "en"),
    )
    if local_alignment.status == "aligned" and local_alignment.artifact_path and local_alignment.artifact_path.exists():
        payload = json.loads(local_alignment.artifact_path.read_text(encoding="utf-8"))
        transcript_text = " ".join(word["word"] for word in payload.get("words", []))
        transcript_source = "local_whisper_alignment"
    expected_tokens = _normalize_words(str(spec["voiceover"]["text"]))
    actual_tokens = _normalize_words(transcript_text)
    wer = _word_error_rate(expected_tokens, actual_tokens)
    transcript_exact_match = expected_tokens == actual_tokens
    target_duration_ms = spec["voiceover"].get("target_duration_ms")
    actual_duration_ms = int(take.get("duration_ms") or qc.get("duration_ms") or 0)
    tolerance, max_auto = _effective_duration_policy(
        spec["voiceover"].get("duration_tolerance_percent"),
        spec["voiceover"].get("max_auto_tempo_percent"),
    )
    if target_duration_ms and actual_duration_ms:
        duration_delta_percent = round(abs((actual_duration_ms - int(target_duration_ms)) / int(target_duration_ms) * 100), 6)
    else:
        duration_delta_percent = 0.0
    errors = list(qc.get("errors") or [])
    warnings = list(qc.get("warnings") or [])
    duration_within_tolerance = bool(not target_duration_ms or duration_delta_percent <= tolerance)
    duration_within_auto_tempo_limit = bool(not target_duration_ms or duration_delta_percent <= max_auto)
    requires_tempo_correction = bool(target_duration_ms and duration_delta_percent > tolerance and duration_delta_percent <= max_auto)
    eligible_for_approval = bool(
        not errors
        and (take.get("raw_audio_path") or take.get("normalized_audio_path"))
        and transcript_exact_match
        and duration_within_auto_tempo_limit
    )
    return {
        "take_id": str(take["voice_take_id"]),
        "take_index": int(take.get("take_index") or 0),
        "status": str(take.get("status") or ""),
        "audio_sha256": str(take.get("audio_sha256") or qc.get("audio_sha256") or ""),
        "transcript_source": transcript_source,
        "transcript": transcript_text,
        "transcript_exact_match": transcript_exact_match,
        "wer": round(wer, 6),
        "duration_ms": actual_duration_ms,
        "duration_delta_percent": duration_delta_percent,
        "duration_tolerance_percent": tolerance,
        "max_auto_tempo_percent": max_auto,
        "duration_within_tolerance": duration_within_tolerance,
        "duration_within_auto_tempo_limit": duration_within_auto_tempo_limit,
        "requires_tempo_correction": requires_tempo_correction,
        "leading_silence_ms": int(qc.get("leading_silence_ms") or 0),
        "trailing_silence_ms": int(qc.get("trailing_silence_ms") or 0),
        "integrated_lufs": qc.get("integrated_lufs"),
        "sample_peak_dbfs": qc.get("sample_peak_dbfs"),
        "clipping_detected": bool(qc.get("clipping_detected")),
        "missing_word_count": max(0, len(expected_tokens) - len(actual_tokens)),
        "extra_word_count": max(0, len(actual_tokens) - len(expected_tokens)),
        "warning_count": len(warnings),
        "warnings": warnings,
        "error_count": len(errors),
        "errors": errors,
        "technical_error": bool(errors) or not (take.get("raw_audio_path") or take.get("normalized_audio_path")),
        "eligible_for_approval": eligible_for_approval,
    }


def _normalize_mix_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    source = dict(payload or {})
    return {
        "profile": str(source.get("profile") or "custom"),
        "voice_gain_percent": float(source.get("voice_gain_percent") if source.get("voice_gain_percent") is not None else 100),
        "music_gain_percent": float(source.get("music_gain_percent") if source.get("music_gain_percent") is not None else 12),
        "original_audio_gain_percent": float(source.get("original_audio_gain_percent") if source.get("original_audio_gain_percent") is not None else 0),
        "ducking": bool(source.get("ducking", False)),
        "music_fade_out_ms": int(source.get("music_fade_out_ms") or 350),
    }


def _effective_duration_policy(
    duration_tolerance_percent: float | int | None,
    max_auto_tempo_percent: float | int | None,
) -> tuple[float, float]:
    tolerance = float(duration_tolerance_percent or DEFAULT_DURATION_TOLERANCE_PERCENT)
    max_auto = float(max_auto_tempo_percent or MAX_AUTO_TEMPO_PERCENT)
    tolerance = min(tolerance, DEFAULT_DURATION_TOLERANCE_PERCENT)
    max_auto = min(max_auto, MAX_AUTO_TEMPO_PERCENT)
    max_auto = max(max_auto, tolerance)
    return round(tolerance, 3), round(max_auto, 3)


def _inspect_approved_audio(
    *,
    repo: VoiceStudioRepository,
    take: dict[str, Any],
    spec: dict[str, Any],
    audio_path: Path,
) -> dict[str, Any]:
    job_root = Path(repo.get_voice_job(str(take["voice_job_id"]))["spec_path"]).parent
    workspace_root = job_root.parents[2]
    ffmpeg_path = find_executable("ffmpeg", workspace_root.parents[0] if workspace_root.parents else None)
    ffprobe_path = find_executable("ffprobe", workspace_root.parents[0] if workspace_root.parents else None)
    client = VoiceboxClient(DEFAULT_VOICEBOX_URL)
    return asdict(
        inspect_generated_audio(
            ffmpeg_path=ffmpeg_path,
            ffprobe_path=ffprobe_path,
            client=client,
            audio_path=audio_path,
            expected_text=str(spec["voiceover"]["text"]),
            generation_latency_ms=None,
        )
    )


def _normalize_words(text: str) -> list[str]:
    lowered = text.lower()
    cleaned = "".join(character if character.isalnum() or character in {"'", " "} else " " for character in lowered)
    return [token for token in cleaned.split() if token]


def _word_error_rate(expected: list[str], actual: list[str]) -> float:
    if not expected:
        return 0.0 if not actual else 1.0
    rows = len(expected) + 1
    cols = len(actual) + 1
    matrix = [[0] * cols for _ in range(rows)]
    for row in range(rows):
        matrix[row][0] = row
    for col in range(cols):
        matrix[0][col] = col
    for row in range(1, rows):
        for col in range(1, cols):
            cost = 0 if expected[row - 1] == actual[col - 1] else 1
            matrix[row][col] = min(
                matrix[row - 1][col] + 1,
                matrix[row][col - 1] + 1,
                matrix[row - 1][col - 1] + cost,
            )
    return matrix[-1][-1] / max(1, len(expected))


def _deserialize_approval(row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    payload = json.loads(row["payload_json"])
    data = dict(row)
    data["payload"] = payload
    return data


def _apply_atempo(ffmpeg_path: str, source_path: Path, destination_path: Path, factor: float) -> None:
    destination_path.parent.mkdir(parents=True, exist_ok=True)
    if factor <= 0:
        raise ValueError("Invalid atempo factor.")
    run_command(
        [
            ffmpeg_path,
            "-y",
            "-i",
            str(source_path),
            "-filter:a",
            f"atempo={factor:.6f}",
            str(destination_path),
        ]
    )
