from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class VoiceRuntimeInfo:
    base_url: str
    api_version: str
    status: str
    model_loaded: bool
    model_downloaded: bool | None
    model_size: str | None
    gpu_available: bool
    gpu_type: str | None
    vram_used_mb: float | None
    backend_type: str | None
    backend_variant: str | None
    engines: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class VoiceProfile:
    profile_id: str
    name: str
    language: str
    voice_type: str
    default_engine: str | None
    sample_count: int
    generation_count: int
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class VoiceGenerationRequest:
    profile_key: str
    profile_id: str
    text: str
    language: str
    takes: int
    seeds: tuple[int, ...]
    engine: str
    model_size: str
    instruct: str | None
    target_duration_ms: int | None
    duration_tolerance_percent: float
    max_auto_tempo_percent: float
    normalize_voice: bool
    word_timestamps_required: bool
    mix: dict[str, Any]
    raw_spec: dict[str, Any]


@dataclass(frozen=True, slots=True)
class VoiceGenerationResult:
    generation_id: str
    status: str
    audio_path: str | None
    duration_seconds: float | None
    seed: int | None
    engine: str | None
    model_size: str | None
    created_at: str
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class AudioQCResult:
    codec: str | None
    container: str | None
    sample_rate: int | None
    channels: int | None
    duration_ms: int
    integrated_lufs: float | None
    sample_peak_dbfs: float | None
    clipping_detected: bool
    leading_silence_ms: int | None
    trailing_silence_ms: int | None
    transcript: str
    transcript_exact_match: bool
    missing_words: tuple[str, ...]
    extra_words: tuple[str, ...]
    punctuation_different: bool
    generation_latency_ms: int | None
    audio_sha256: str
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    status: str
    reason: str | None
    artifact_path: Path | None = None
    subtitle_path: Path | None = None
    karaoke_ass_path: Path | None = None
