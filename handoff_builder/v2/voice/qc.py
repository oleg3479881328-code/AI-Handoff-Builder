from __future__ import annotations

import json
import re
import string
from pathlib import Path

from handoff_builder.ffmpeg_tools import run_command
from handoff_builder.v2.packages.guards import compute_sha256

from .client import VoiceboxClient, VoiceboxError
from .models import AudioQCResult


def inspect_generated_audio(
    *,
    ffmpeg_path: str,
    ffprobe_path: str,
    client: VoiceboxClient,
    audio_path: Path,
    expected_text: str,
    generation_latency_ms: int | None,
) -> AudioQCResult:
    metadata = _probe_audio(ffprobe_path, audio_path)
    loudness = _measure_loudness(ffmpeg_path, audio_path)
    silence = _measure_silence(ffmpeg_path, audio_path, metadata["duration_ms"])
    transcript = ""
    missing_words: list[str] = []
    extra_words: list[str] = []
    punctuation_different = False
    exact_match = False
    warnings: list[str] = []
    errors: list[str] = []
    try:
        transcript_payload = client.transcribe_audio(audio_path)
        transcript = str(transcript_payload.get("text") or "")
        missing_words, extra_words, punctuation_different = _compare_transcript(expected_text, transcript)
        exact_match = not missing_words and not extra_words
    except VoiceboxError as exc:
        warnings.append("transcription_unavailable")
        errors.append(str(exc))
    if silence["leading_silence_ms"] and silence["leading_silence_ms"] > 800:
        warnings.append("leading_silence_high")
    if silence["trailing_silence_ms"] and silence["trailing_silence_ms"] > 1000:
        warnings.append("trailing_silence_high")
    if missing_words:
        warnings.append("transcript_missing_words")
    if extra_words:
        warnings.append("transcript_extra_words")
    if loudness["clipping_detected"]:
        warnings.append("clipping_detected")
    return AudioQCResult(
        codec=metadata["codec"],
        container=metadata["container"],
        sample_rate=metadata["sample_rate"],
        channels=metadata["channels"],
        duration_ms=metadata["duration_ms"],
        integrated_lufs=loudness["integrated_lufs"],
        sample_peak_dbfs=loudness["sample_peak_dbfs"],
        clipping_detected=loudness["clipping_detected"],
        leading_silence_ms=silence["leading_silence_ms"],
        trailing_silence_ms=silence["trailing_silence_ms"],
        transcript=transcript,
        transcript_exact_match=exact_match,
        missing_words=tuple(missing_words),
        extra_words=tuple(extra_words),
        punctuation_different=punctuation_different,
        generation_latency_ms=generation_latency_ms,
        audio_sha256=compute_sha256(audio_path),
        warnings=tuple(warnings),
        errors=tuple(errors),
    )


def _probe_audio(ffprobe_path: str, audio_path: Path) -> dict[str, int | str | None]:
    completed = run_command(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(audio_path),
        ]
    )
    data = json.loads(completed.stdout or "{}")
    audio_stream = next(
        (stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"),
        {},
    )
    duration = float(audio_stream.get("duration") or data.get("format", {}).get("duration") or 0.0)
    return {
        "codec": audio_stream.get("codec_name"),
        "container": data.get("format", {}).get("format_name"),
        "sample_rate": int(audio_stream.get("sample_rate") or 0) or None,
        "channels": int(audio_stream.get("channels") or 0) or None,
        "duration_ms": int(round(duration * 1000)),
    }


def _measure_loudness(ffmpeg_path: str, audio_path: Path) -> dict[str, float | bool | None]:
    completed = run_command(
        [
            ffmpeg_path,
            "-hide_banner",
            "-i",
            str(audio_path),
            "-filter_complex",
            "ebur128=peak=true",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    text = (completed.stderr or "") + "\n" + (completed.stdout or "")
    integrated_match = re.findall(r"I:\s*(-?\d+(?:\.\d+)?) LUFS", text)
    peak_match = re.findall(r"Peak:\s*(-?\d+(?:\.\d+)?) dBFS", text)
    peak_value = float(peak_match[-1]) if peak_match else None
    return {
        "integrated_lufs": float(integrated_match[-1]) if integrated_match else None,
        "sample_peak_dbfs": peak_value,
        "clipping_detected": bool(peak_value is not None and peak_value >= -0.1),
    }


def _measure_silence(ffmpeg_path: str, audio_path: Path, duration_ms: int) -> dict[str, int | None]:
    completed = run_command(
        [
            ffmpeg_path,
            "-hide_banner",
            "-i",
            str(audio_path),
            "-af",
            "silencedetect=noise=-35dB:d=0.05",
            "-f",
            "null",
            "-",
        ],
        check=False,
    )
    text = (completed.stderr or "") + "\n" + (completed.stdout or "")
    starts = [float(value) for value in re.findall(r"silence_start: ([0-9]+(?:\.[0-9]+)?)", text)]
    ends = [float(value) for value in re.findall(r"silence_end: ([0-9]+(?:\.[0-9]+)?)", text)]
    leading = int(round(ends[0] * 1000)) if starts and starts[0] <= 0.01 and ends else 0
    trailing = None
    if starts and ends:
        for start in starts:
            if abs((duration_ms / 1000) - start) < 2.0:
                trailing = int(round((duration_ms / 1000 - start) * 1000))
                break
    return {"leading_silence_ms": leading, "trailing_silence_ms": trailing}


def _compare_transcript(expected_text: str, actual_text: str) -> tuple[list[str], list[str], bool]:
    expected_tokens = _normalize_words(expected_text)
    actual_tokens = _normalize_words(actual_text)
    missing = [word for word in expected_tokens if word not in actual_tokens]
    extra = [word for word in actual_tokens if word not in expected_tokens]
    punctuation_different = expected_text.translate(str.maketrans("", "", string.ascii_letters + string.digits)).strip() != actual_text.translate(str.maketrans("", "", string.ascii_letters + string.digits)).strip()
    return missing, extra, punctuation_different


def _normalize_words(text: str) -> list[str]:
    cleaned = re.sub(r"[^\w\s']", " ", text.lower())
    return [token for token in cleaned.split() if token]
