from __future__ import annotations

import json
import math
import os
import re
import subprocess
import threading
from pathlib import Path

from .utils import find_executable


CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class FFmpegError(RuntimeError):
    pass


def run_command(
    args: list[str],
    *,
    capture: bool = True,
    check: bool = True,
    cancel_event: threading.Event | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        args,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        creationflags=CREATE_NO_WINDOW,
        errors="replace",
        cwd=os.fspath(cwd) if cwd is not None else None,
        env=env,
    )
    try:
        while True:
            if cancel_event and cancel_event.is_set():
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                raise FFmpegError("Processing was canceled by the user.")
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                continue
    finally:
        if process.stdout:
            process.stdout.close()
        if process.stderr:
            process.stderr.close()
    completed = subprocess.CompletedProcess(args, process.returncode, stdout, stderr)
    if check and completed.returncode != 0:
        tail = (completed.stderr or completed.stdout or "")[-5000:]
        raise FFmpegError(f"Command failed ({completed.returncode}):\n{tail}")
    return completed


class FFmpegTools:
    def __init__(
        self,
        project_root: Path | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.ffmpeg = find_executable("ffmpeg", project_root)
        self.ffprobe = find_executable("ffprobe", project_root)
        self.cancel_event = cancel_event

    def probe(self, source: Path) -> dict:
        proc = run_command([
            self.ffprobe,
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            str(source),
        ], cancel_event=self.cancel_event)
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
        duration = (
            video_stream.get("duration")
            or data.get("format", {}).get("duration")
            or 0
        )
        frame_rate = video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or "0/0"
        return {
            "duration": float(duration or 0),
            "width": int(video_stream.get("width") or 0),
            "height": int(video_stream.get("height") or 0),
            "rotation": int(float(rotation or 0)),
            "codec": video_stream.get("codec_name"),
            "fps": self._parse_frame_rate(frame_rate),
            "audio_present": audio_stream is not None,
        }

    def _parse_frame_rate(self, value: str | int | float | None) -> float | None:
        if value in (None, "", "0/0"):
            return None
        text = str(value)
        if "/" in text:
            numerator, denominator = text.split("/", 1)
            try:
                num = float(numerator)
                den = float(denominator)
            except ValueError:
                return None
            if den == 0:
                return None
            return round(num / den, 6)
        try:
            return round(float(text), 6)
        except ValueError:
            return None

    def make_proxy(self, source: Path, destination: Path, target_height: int = 720) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        vf = (
            f"scale='if(gt(iw,ih),-2,{target_height})':"
            f"'if(gt(iw,ih),{target_height},-2)',"
            "setsar=1"
        )
        run_command([
            self.ffmpeg, "-y",
            "-i", str(source),
            "-map_metadata", "-1",
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "30",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "64k",
            "-movflags", "+faststart",
            str(destination),
        ], cancel_event=self.cancel_event)

    def detect_scene_cuts(
        self,
        source: Path,
        threshold: float,
        duration: float,
    ) -> list[float]:
        if duration <= 0:
            return []
        proc = run_command([
            self.ffmpeg,
            "-hide_banner",
            "-i", str(source),
            "-an",
            "-vf", f"select='gt(scene,{threshold})',showinfo",
            "-f", "null",
            "-",
        ], check=False, cancel_event=self.cancel_event)
        text = (proc.stderr or "") + "\n" + (proc.stdout or "")
        values = [
            float(value)
            for value in re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", text)
        ]
        result: list[float] = []
        for value in values:
            if value < 0.4 or value > duration - 0.4:
                continue
            if result and value - result[-1] < 0.75:
                continue
            result.append(value)
        return result

    def extract_frame(
        self,
        source: Path,
        at_seconds: float,
        destination: Path,
        max_width: int = 720,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        vf = f"scale='min({max_width},iw)':-2"
        run_command([
            self.ffmpeg, "-y",
            "-ss", f"{max(0.0, at_seconds):.3f}",
            "-i", str(source),
            "-frames:v", "1",
            "-vf", vf,
            "-q:v", "3",
            str(destination),
        ], cancel_event=self.cancel_event)

    def make_preview(
        self,
        source: Path,
        start_seconds: float,
        duration_seconds: float,
        destination: Path,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        vf = "scale='if(gt(iw,ih),960,540)':-2,setsar=1"
        run_command([
            self.ffmpeg, "-y",
            "-ss", f"{max(0.0, start_seconds):.3f}",
            "-i", str(source),
            "-t", f"{max(0.35, duration_seconds):.3f}",
            "-an",
            "-vf", vf,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "31",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(destination),
        ], cancel_event=self.cancel_event)

    def scene_segments(
        self,
        source: Path,
        duration: float,
        *,
        threshold: float,
        short_seconds: float,
        fallback_segment_seconds: float,
        max_segments: int,
    ) -> tuple[list[tuple[float, float]], str]:
        if duration <= 0:
            return [(0.0, 1.0)], "unknown_duration"
        if duration <= short_seconds:
            return [(0.0, duration)], "short_full_video"

        cuts = self.detect_scene_cuts(source, threshold, duration)
        boundaries = [0.0] + cuts + [duration]
        segments = [
            (start, end)
            for start, end in zip(boundaries, boundaries[1:])
            if end - start >= 0.35
        ]

        if len(segments) >= 2:
            if len(segments) > max_segments:
                stride = len(segments) / max_segments
                selected = []
                for index in range(max_segments):
                    selected.append(segments[min(int(index * stride), len(segments) - 1)])
                segments = selected
            return segments, "scene_detection"

        count = min(
            max_segments,
            max(2, math.ceil(duration / max(1.0, fallback_segment_seconds))),
        )
        step = duration / count
        fallback = [
            (index * step, duration if index == count - 1 else (index + 1) * step)
            for index in range(count)
        ]
        return fallback, "uniform_coverage"
