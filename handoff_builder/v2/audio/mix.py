from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from handoff_builder.ffmpeg_tools import run_command


@dataclass(frozen=True, slots=True)
class MixPreviewResult:
    output_path: Path
    ffmpeg_command_path: Path
    render_plan_path: Path
    stem_paths: dict[str, Path]
    metrics: dict[str, Any]


def render_voice_mix_preview(
    *,
    ffmpeg_path: str,
    ffprobe_path: str,
    video_path: Path,
    voice_path: Path,
    output_path: Path,
    music_path: Path | None = None,
    voice_gain_percent: float = 100,
    music_gain_percent: float = 12,
    original_audio_gain_percent: float = 0,
    ducking: bool = False,
    music_fade_out_ms: int = 350,
) -> MixPreviewResult:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    duration_seconds, video_has_audio = _probe_video(ffprobe_path, video_path)
    args = [ffmpeg_path, "-y", "-i", str(video_path), "-i", str(voice_path)]
    if music_path:
        args.extend(["-i", str(music_path)])

    filters = []
    original_label = "aorig"
    voice_label = "avoice"
    mixed_original_label = "aorig_mix"
    mixed_voice_label = "avoice_mix"
    mixed_music_label = "amusic_mix"
    mix_inputs: list[str] = []
    stem_paths: dict[str, Path] = {}

    if video_has_audio:
        filters.append(
            f"[0:a]volume={original_audio_gain_percent / 100:.4f},aresample=async=1:first_pts=0,"
            f"atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS[{original_label}]"
        )
        mix_inputs.append(f"[{original_label}]")
        stem_paths["original"] = output_path.parent / f"{output_path.stem}_original.wav"
        _render_audio_stem(
            ffmpeg_path=ffmpeg_path,
            source_path=video_path,
            output_path=stem_paths["original"],
            filter_expression=(
                f"[0:a]volume={original_audio_gain_percent / 100:.4f},aresample=async=1:first_pts=0,"
                f"atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS[{mixed_original_label}]"
            ),
            output_label=mixed_original_label,
        )

    filters.append(
        f"[1:a]volume={voice_gain_percent / 100:.4f},aresample=async=1:first_pts=0,"
        f"atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS[{voice_label}]"
    )
    mix_inputs.append(f"[{voice_label}]")
    stem_paths["voice"] = output_path.parent / f"{output_path.stem}_voice.wav"
    _render_audio_stem(
        ffmpeg_path=ffmpeg_path,
        source_path=voice_path,
        output_path=stem_paths["voice"],
        filter_expression=(
            f"[0:a]volume={voice_gain_percent / 100:.4f},aresample=async=1:first_pts=0,"
            f"atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS[{mixed_voice_label}]"
        ),
        output_label=mixed_voice_label,
    )

    music_filter_label = None
    if music_path:
        music_filter_label = "amusic"
        music_gain = music_gain_percent / 100
        music_filter_expression = (
            f"[2:a]volume={music_gain:.4f},aresample=async=1:first_pts=0,"
            f"atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS[{music_filter_label}]"
        )
        if music_fade_out_ms > 0:
            fade_start = max(0.0, duration_seconds - music_fade_out_ms / 1000)
            music_filter_expression = (
                f"[2:a]volume={music_gain:.4f},aresample=async=1:first_pts=0,"
                f"atrim=duration={duration_seconds:.3f},afade=t=out:st={fade_start:.3f}:d={music_fade_out_ms / 1000:.3f},"
                f"asetpts=PTS-STARTPTS[{music_filter_label}]"
            )
        filters.append(music_filter_expression)
        mix_inputs.append(f"[{music_filter_label}]")
        stem_paths["music"] = output_path.parent / f"{output_path.stem}_music.wav"
        _render_audio_stem(
            ffmpeg_path=ffmpeg_path,
            source_path=music_path,
            output_path=stem_paths["music"],
            filter_expression=music_filter_expression.replace(f"[2:a]", "[0:a]").replace(f"[{music_filter_label}]", f"[{mixed_music_label}]"),
            output_label=mixed_music_label,
        )

    if ducking and music_filter_label:
        raise ValueError("ducking=true is not implemented yet; default ducking=false is enforced.")

    filters.append("".join(mix_inputs) + f"amix=inputs={len(mix_inputs)}:normalize=0:duration=longest[aout]")
    args.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "0:v:0",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    run_command(args)
    command_path = output_path.parent / f"{output_path.stem}_ffmpeg_command.json"
    render_plan_path = output_path.parent / f"{output_path.stem}_render_plan.json"
    command_path.write_text(json.dumps({"args": args}, ensure_ascii=False, indent=2), encoding="utf-8")
    render_plan_path.write_text(
        json.dumps(
            {
                "video_path": str(video_path),
                "voice_path": str(voice_path),
                "music_path": str(music_path) if music_path else None,
                "voice_gain_percent": voice_gain_percent,
                "music_gain_percent": music_gain_percent,
                "original_audio_gain_percent": original_audio_gain_percent,
                "ducking": ducking,
                "music_fade_out_ms": music_fade_out_ms,
                "duration_seconds": duration_seconds,
                "stem_paths": {name: str(path) for name, path in stem_paths.items()},
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    output_probe = _probe_media(ffprobe_path, output_path)
    voice_probe = _probe_media(ffprobe_path, voice_path)
    music_probe = _probe_media(ffprobe_path, music_path) if music_path else None
    return MixPreviewResult(
        output_path=output_path,
        ffmpeg_command_path=command_path,
        render_plan_path=render_plan_path,
        stem_paths=stem_paths,
        metrics={
            "duration_seconds": duration_seconds,
            "output_duration_seconds": output_probe["duration_seconds"],
            "output_audio_present": output_probe["has_audio"],
            "voice_duration_seconds": voice_probe["duration_seconds"],
            "voice_audio_present": voice_probe["has_audio"],
            "music_duration_seconds": music_probe["duration_seconds"] if music_probe else None,
            "music_audio_present": music_probe["has_audio"] if music_probe else False,
            "voice_gain_linear": round(voice_gain_percent / 100, 4),
            "music_gain_linear": round(music_gain_percent / 100, 4),
            "original_audio_gain_linear": round(original_audio_gain_percent / 100, 4),
            "ducking": ducking,
            "no_shortest": True,
        },
    )


def _probe_video(ffprobe_path: str, video_path: Path) -> tuple[float, bool]:
    probe = _probe_media(ffprobe_path, video_path)
    return probe["duration_seconds"], probe["has_audio"]


def _probe_media(ffprobe_path: str, media_path: Path) -> dict[str, Any]:
    completed = run_command(
        [
            ffprobe_path,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(media_path),
        ]
    )
    data = json.loads(completed.stdout or "{}")
    return {
        "duration_seconds": float(data.get("format", {}).get("duration") or 0.0),
        "has_audio": any(stream.get("codec_type") == "audio" for stream in data.get("streams", [])),
    }


def _render_audio_stem(
    *,
    ffmpeg_path: str,
    source_path: Path,
    output_path: Path,
    filter_expression: str,
    output_label: str,
) -> None:
    run_command(
        [
            ffmpeg_path,
            "-y",
            "-i",
            str(source_path),
            "-filter_complex",
            filter_expression,
            "-map",
            f"[{output_label}]",
            "-c:a",
            "pcm_s16le",
            str(output_path),
        ]
    )
