from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from ..plans.schema import deterministic_plan_hash
from ..plans.semantic import ValidatedLocalPhotoPlan, ValidatedPreviewPlan


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


def compile_local_photo_render_plan(
    validated: ValidatedLocalPhotoPlan,
    *,
    ffmpeg_path: str,
    output_path: Path,
) -> CompiledRenderPlan:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    staging_dir = Path(tempfile.mkdtemp(prefix="photo_plan_", dir=str(output_path.parent)))
    frame_paths: list[Path] = []
    segments: list[dict] = []
    ffmpeg_args: list[str] = [ffmpeg_path, "-y"]
    filter_parts: list[str] = []
    concat_labels: list[str] = []

    for index, segment in enumerate(validated.segments, start=1):
        asset = validated.assets[segment.asset_id]
        frame_path = staging_dir / f"frame_{index:03d}.png"
        _render_segment_frame(
            asset.path,
            frame_path,
            width=validated.output_width,
            height=validated.output_height,
            overlay_text=segment.overlay_text,
        )
        frame_paths.append(frame_path)
        ffmpeg_args.extend(
            [
                "-loop",
                "1",
                "-t",
                f"{segment.duration_ms / 1000:.3f}",
                "-i",
                str(frame_path),
            ]
        )
        video_label = f"v{index - 1}"
        filter_parts.append(
            f"[{index - 1}:v]fps={validated.output_fps},scale={validated.output_width}:{validated.output_height},"
            f"setsar=1,format=yuv420p[{video_label}]"
        )
        concat_labels.append(f"[{video_label}]")
        segments.append(
            {
                "asset_id": segment.asset_id,
                "path": str(asset.path),
                "duration_ms": segment.duration_ms,
                "overlay_text": segment.overlay_text,
                "sha256": asset.sha256,
            }
        )
    filter_parts.append("".join(concat_labels) + f"concat=n={len(validated.segments)}:v=1:a=0[vout]")
    ffmpeg_args.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            "[vout]",
            "-r",
            str(validated.output_fps),
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            VIDEO_PRESET,
            "-crf",
            str(VIDEO_CRF),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    render_plan = {
        "schema_version": str(validated.payload.get("schema_version") or "2.0"),
        "mode": "preview",
        "output": {
            "width": validated.output_width,
            "height": validated.output_height,
            "fps": validated.output_fps,
            "video_codec": "h264",
            "audio_codec": None,
            "preset": VIDEO_PRESET,
            "crf": VIDEO_CRF,
        },
        "segments": segments,
        "planned_duration_ms": validated.planned_duration_ms,
    }
    compiled_plan_hash = deterministic_plan_hash(render_plan)
    command_metadata = {
        "args": ffmpeg_args,
        "mode": "preview",
        "compiled_plan_hash": compiled_plan_hash,
        "segment_count": len(validated.segments),
        "staging_dir": str(staging_dir),
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


def _render_segment_frame(
    source_path: Path,
    output_path: Path,
    *,
    width: int,
    height: int,
    overlay_text: str | None,
) -> None:
    with Image.open(source_path) as image:
        image = image.convert("RGB")
        scale = max(width / image.width, height / image.height)
        resized = image.resize(
            (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
            Image.Resampling.LANCZOS,
        )
        left = max(0, (resized.width - width) // 2)
        top = max(0, (resized.height - height) // 2)
        canvas = resized.crop((left, top, left + width, top + height))

    if overlay_text:
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default()
        text_bbox = draw.textbbox((0, 0), overlay_text, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        text_height = text_bbox[3] - text_bbox[1]
        padding_x = 32
        padding_y = 16
        box_width = text_width + padding_x * 2
        box_height = text_height + padding_y * 2
        box_left = max(24, (width - box_width) // 2)
        box_top = max(24, height - box_height - 48)
        box_right = min(width - 24, box_left + box_width)
        box_bottom = min(height - 24, box_top + box_height)
        draw.rounded_rectangle((box_left, box_top, box_right, box_bottom), radius=24, fill=(0, 0, 0))
        draw.text(
            (box_left + padding_x, box_top + padding_y),
            overlay_text,
            fill=(255, 255, 255),
            font=font,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, "PNG")
