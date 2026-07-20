from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..plans.schema import deterministic_plan_hash
from ..plans.semantic import ValidatedPreviewPlan


PREVIEW_WIDTH = 720
PREVIEW_HEIGHT = 1280
PREVIEW_FPS = 30
VIDEO_PRESET = "veryfast"
VIDEO_CRF = 27
AUDIO_BITRATE = "128k"


@dataclass(frozen=True, slots=True)
class CompiledRenderPlan:
    render_plan: dict
    ffmpeg_args: list[str]
    command_metadata: dict
    compiled_plan_hash: str


def compile_preview_render_plan(
    validated: ValidatedPreviewPlan,
    *,
    ffmpeg_path: str,
    output_path: Path,
) -> CompiledRenderPlan:
    filter_parts: list[str] = []
    ffmpeg_args: list[str] = [ffmpeg_path, "-y"]
    concat_labels: list[str] = []
    source_fingerprints: list[dict] = []

    for index, operation in enumerate(validated.operations):
        asset = validated.assets[operation.asset_id]
        ffmpeg_args.extend(
            [
                "-ss",
                f"{operation.source_in_ms / 1000:.3f}",
                "-to",
                f"{operation.source_out_ms / 1000:.3f}",
                "-noautorotate",
                "-i",
                str(asset.path),
            ]
        )
        video_label = f"v{index}"
        audio_label = f"a{index}"
        filter_parts.append(
            f"[{index}:v]{_rotation_filter(asset.rotation)}fps={PREVIEW_FPS},"
            f"scale={PREVIEW_WIDTH}:{PREVIEW_HEIGHT}:force_original_aspect_ratio=increase,"
            f"crop={PREVIEW_WIDTH}:{PREVIEW_HEIGHT},setsar=1,format=yuv420p[{video_label}]"
        )
        if asset.has_audio:
            filter_parts.append(
                f"[{index}:a]aresample=async=1:first_pts=0,asetpts=PTS-STARTPTS[{audio_label}]"
            )
        else:
            duration_seconds = operation.duration_ms / 1000
            filter_parts.append(
                f"anullsrc=channel_layout=stereo:sample_rate=48000,"
                f"atrim=duration={duration_seconds:.3f},asetpts=PTS-STARTPTS[{audio_label}]"
            )
        concat_labels.extend([f"[{video_label}]", f"[{audio_label}]"])
        source_fingerprints.append(
            {
                "asset_id": asset.asset_id,
                "path": str(asset.path),
                "source_in_ms": operation.source_in_ms,
                "source_out_ms": operation.source_out_ms,
                "rotation": asset.rotation,
                "has_audio": asset.has_audio,
            }
        )

    filter_parts.append(
        "".join(concat_labels) + f"concat=n={len(validated.operations)}:v=1:a=1[vout][aout]"
    )
    filter_complex = ";".join(filter_parts)
    ffmpeg_args.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-r",
            str(PREVIEW_FPS),
            "-c:v",
            "libx264",
            "-preset",
            VIDEO_PRESET,
            "-crf",
            str(VIDEO_CRF),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            AUDIO_BITRATE,
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )

    render_plan = {
        "schema_version": "1.0",
        "mode": "preview",
        "output": {
            "width": PREVIEW_WIDTH,
            "height": PREVIEW_HEIGHT,
            "fps": PREVIEW_FPS,
            "video_codec": "h264",
            "audio_codec": "aac",
            "preset": VIDEO_PRESET,
            "crf": VIDEO_CRF,
        },
        "segments": source_fingerprints,
        "planned_duration_ms": validated.planned_duration_ms,
    }
    compiled_plan_hash = deterministic_plan_hash(render_plan)
    command_metadata = {
        "args": ffmpeg_args,
        "mode": "preview",
        "compiled_plan_hash": compiled_plan_hash,
        "segment_count": len(validated.operations),
    }
    return CompiledRenderPlan(
        render_plan=render_plan,
        ffmpeg_args=ffmpeg_args,
        command_metadata=command_metadata,
        compiled_plan_hash=compiled_plan_hash,
    )


def _rotation_filter(rotation: int) -> str:
    normalized = rotation % 360
    if normalized == 90:
        return "transpose=clock,"
    if normalized == 180:
        return "hflip,vflip,"
    if normalized == 270:
        return "transpose=cclock,"
    return ""
