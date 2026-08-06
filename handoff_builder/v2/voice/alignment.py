from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from handoff_builder.ffmpeg_tools import FFmpegError, run_command
from handoff_builder.utils import json_dump
from handoff_builder.v2.packages.guards import compute_sha256

from .models import AlignmentResult


DEFAULT_WHISPER_CPP_EXE = Path(
    r"C:\Users\oleg3\OneDrive\Documents\Project-Execution-OS\projects\whisper-transcription-core\bin\whisper.cpp\build\bin\Release\whisper-cli.exe"
)
DEFAULT_WHISPER_CPP_MODEL = Path(
    r"C:\Users\oleg3\OneDrive\Documents\Project-Execution-OS\projects\whisper-transcription-core\models\ggml-small.bin"
)


def align_words_for_take(
    *,
    audio_path: Path,
    expected_text: str,
    output_dir: Path,
    take_id: str = "unknown-take",
    language: str = "en",
) -> AlignmentResult:
    output_dir.mkdir(parents=True, exist_ok=True)
    runtime = _discover_whisper_cpp_runtime()
    if runtime is None:
        return AlignmentResult(
            status="word_alignment_unavailable",
            reason="No local whisper.cpp runtime with a usable model was found.",
        )

    transcript_prefix = output_dir / "transcript"
    normalized_language = _normalize_whisper_language(language)
    dtw_preset = _infer_whisper_dtw_preset(runtime["model_path"])
    for suffix in (".json", ".srt", ".txt", ".vtt", ".csv", ".lrc", ".ass"):
        candidate = transcript_prefix.with_suffix(suffix)
        if candidate.exists():
            candidate.unlink()
    with tempfile.TemporaryDirectory(prefix="aihb-whisper-align-") as staging_dir_raw:
        staging_dir = Path(staging_dir_raw)
        staged_audio_path = staging_dir / f"{take_id}.wav"
        staged_transcript_prefix = staging_dir / "transcript"
        shutil.copy2(audio_path, staged_audio_path)
        command = [
            str(runtime["exe_path"]),
            "-m",
            str(runtime["model_path"]),
            "-f",
            str(staged_audio_path),
            "-l",
            normalized_language,
            "-t",
            "4",
            "-of",
            str(staged_transcript_prefix),
            "-otxt",
            "-osrt",
            "-ovtt",
            "-oj",
            "-ojf",
            "-sow",
        ]
        if dtw_preset:
            command.extend(["-dtw", dtw_preset])
        try:
            run_command(command)
        except FFmpegError as exc:
            return AlignmentResult(
                status="word_alignment_unavailable",
                reason=f"Local whisper.cpp alignment failed: {exc}",
            )

        transcript_json_path = staged_transcript_prefix.with_suffix(".json")
        if not transcript_json_path.exists():
            return AlignmentResult(
                status="word_alignment_unavailable",
                reason="Local whisper.cpp finished without transcript.json output.",
            )

        transcript_payload = json.loads(transcript_json_path.read_text(encoding="utf-8"))
        words = _extract_words(transcript_payload)
        if not words:
            return AlignmentResult(
                status="word_alignment_unavailable",
                reason="Local whisper.cpp did not return word-level timing tokens.",
            )

        transcript_srt_path = transcript_prefix.with_suffix(".srt")
        staged_srt_path = staged_transcript_prefix.with_suffix(".srt")
        if staged_srt_path.exists():
            shutil.copy2(staged_srt_path, transcript_srt_path)

        voice_words_path = output_dir / "voice_words.json"
        karaoke_ass_path = output_dir / "voice_karaoke.ass"
        json_dump(
            voice_words_path,
            {
                "schema_version": "1.0",
                "voice_take_id": take_id,
                "audio_sha256": compute_sha256(audio_path),
                "language": normalized_language,
                "expected_text": expected_text,
                "duration_ms": max(word["end_ms"] for word in words),
                "words": words,
            },
        )
        karaoke_ass_path.write_text(_build_karaoke_ass(words), encoding="utf-8")
        return AlignmentResult(
            status="aligned",
            reason=None,
            artifact_path=voice_words_path,
            subtitle_path=transcript_srt_path if transcript_srt_path.exists() else None,
            karaoke_ass_path=karaoke_ass_path,
        )


def _discover_whisper_cpp_runtime() -> dict[str, Path] | None:
    exe_candidates = [
        Path(os.environ["AIHB_WHISPER_CPP_EXE"]) if os.environ.get("AIHB_WHISPER_CPP_EXE") else None,
        DEFAULT_WHISPER_CPP_EXE,
        Path(shutil.which("whisper-cli") or "") if shutil.which("whisper-cli") else None,
        Path(shutil.which("whisper-cli.exe") or "") if shutil.which("whisper-cli.exe") else None,
    ]
    model_candidates = [
        Path(os.environ["AIHB_WHISPER_CPP_MODEL"]) if os.environ.get("AIHB_WHISPER_CPP_MODEL") else None,
        DEFAULT_WHISPER_CPP_MODEL,
    ]
    exe_path = next((path for path in exe_candidates if path and path.exists()), None)
    model_path = next((path for path in model_candidates if path and path.exists()), None)
    if exe_path is None or model_path is None:
        return None
    return {"exe_path": exe_path, "model_path": model_path}


def _extract_words(transcript_payload: dict[str, Any]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    index = 0
    for segment in transcript_payload.get("transcription", []):
        for token in segment.get("tokens", []):
            text = str(token.get("text") or "")
            cleaned = text.strip()
            if not cleaned or cleaned.startswith("[_"):
                continue
            if not any(char.isalnum() for char in cleaned):
                continue
            offsets = token.get("offsets") or {}
            start_ms = int(offsets.get("from") or 0)
            end_ms = int(offsets.get("to") or start_ms)
            words.append(
                {
                    "index": index,
                    "word": cleaned,
                    "start_ms": start_ms,
                    "end_ms": max(end_ms, start_ms),
                    "confidence": round(float(token.get("p") or 0.0), 6),
                }
            )
            index += 1
    return words


def _normalize_whisper_language(language: str) -> str:
    value = (language or "en").strip().lower().replace("_", "-")
    return value.split("-", 1)[0] or "en"


def _infer_whisper_dtw_preset(model_path: Path) -> str | None:
    name = model_path.name.lower()
    known_presets = (
        "large-v3-turbo",
        "large-v3",
        "large-v2",
        "large-v1",
        "medium.en",
        "medium",
        "small.en",
        "small",
        "base.en",
        "base",
        "tiny.en",
        "tiny",
    )
    for preset in known_presets:
        if f"ggml-{preset}.bin" in name:
            return preset
    return None


def _build_karaoke_ass(words: list[dict[str, Any]]) -> str:
    header = """[Script Info]
Title: Voice Karaoke
ScriptType: v4.00+
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,28,&H00FFFFFF,&H0000FFFF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2,0,2,40,40,40,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    if not words:
        return header
    start_ms = int(words[0]["start_ms"])
    end_ms = int(words[-1]["end_ms"])
    chunks: list[str] = []
    for word in words:
        duration_cs = max(1, int(round((int(word["end_ms"]) - int(word["start_ms"])) / 10)))
        chunks.append(f"{{\\k{duration_cs}}}{word['word']}")
    line = (
        f"Dialogue: 0,{_ass_timestamp(start_ms)},{_ass_timestamp(end_ms)},Default,,0,0,0,,"
        + " ".join(chunks)
    )
    return header + line + "\n"


def _ass_timestamp(value_ms: int) -> str:
    total_cs = max(0, int(round(value_ms / 10)))
    hours, rem = divmod(total_cs, 360000)
    minutes, rem = divmod(rem, 6000)
    seconds, centiseconds = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{seconds:02d}.{centiseconds:02d}"
