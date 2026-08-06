from __future__ import annotations

import json
import threading
from pathlib import Path

from handoff_builder.ffmpeg_tools import FFmpegError, run_command
from handoff_builder.utils import find_executable


class FFmpegBackend:
    def __init__(
        self,
        *,
        project_root: Path | None = None,
        ffmpeg_path: str | None = None,
        ffprobe_path: str | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.ffmpeg = ffmpeg_path or find_executable("ffmpeg", project_root)
        self.ffprobe = ffprobe_path or find_executable("ffprobe", project_root)
        self.cancel_event = cancel_event

    def probe(self, source: Path) -> dict:
        proc = run_command(
            [
                self.ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(source),
            ],
            cancel_event=self.cancel_event,
        )
        data = json.loads(proc.stdout or "{}")
        video_stream = next(
            (stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"),
            {},
        )
        audio_stream = next(
            (stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"),
            None,
        )
        tags = video_stream.get("tags", {})
        side_data = video_stream.get("side_data_list", [])
        rotation = tags.get("rotate")
        if rotation is None:
            for item in side_data:
                if "rotation" in item:
                    rotation = item["rotation"]
                    break
        duration = video_stream.get("duration") or data.get("format", {}).get("duration") or 0
        frame_rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/1"
        fps = _fraction_to_float(frame_rate)
        return {
            "duration": float(duration or 0),
            "width": int(video_stream.get("width") or 0),
            "height": int(video_stream.get("height") or 0),
            "rotation": int(float(rotation or 0)),
            "codec": video_stream.get("codec_name"),
            "fps": fps,
            "has_audio": audio_stream is not None,
        }

    def run_ffmpeg(self, args: list[str]) -> tuple[int, str, str]:
        proc = run_command(args, check=False, cancel_event=self.cancel_event)
        return proc.returncode, proc.stdout or "", proc.stderr or ""

    def extract_first_frame(self, source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        proc = run_command(
            [
                self.ffmpeg,
                "-y",
                "-ss",
                "0.000",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(destination),
            ],
            cancel_event=self.cancel_event,
        )
        if proc.returncode != 0:
            raise FFmpegError("Failed to extract first frame.")


def _fraction_to_float(value: str) -> float:
    if "/" not in value:
        try:
            return float(value)
        except ValueError:
            return 0.0
    numerator, denominator = value.split("/", 1)
    try:
        num = float(numerator)
        den = float(denominator)
    except ValueError:
        return 0.0
    if den == 0:
        return 0.0
    return num / den
