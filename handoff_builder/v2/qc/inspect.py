from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import UnsafePackageError
from ..packages.guards import compute_sha256
from ..render.ffmpeg_backend import FFmpegBackend


FPS_TOLERANCE = 0.6
DURATION_TOLERANCE_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class QCResult:
    output_sha256: str
    duration_seconds: float
    width: int
    height: int
    fps: float
    audio_present: bool
    checks: tuple[str, ...]
    warnings: tuple[str, ...]


def inspect_preview_output(
    backend: FFmpegBackend,
    output_path: Path,
    *,
    expected_duration_ms: int,
    expected_width: int = 720,
    expected_height: int = 1280,
    expected_fps: float = 30.0,
    first_frame_path: Path,
) -> QCResult:
    if not output_path.exists() or output_path.stat().st_size <= 0:
        raise UnsafePackageError("Rendered output is missing or empty.")
    metadata = backend.probe(output_path)
    if metadata["width"] != expected_width or metadata["height"] != expected_height:
        raise UnsafePackageError(
            f"Rendered preview does not have required {expected_width}x{expected_height} resolution."
        )
    if abs(float(metadata["fps"]) - expected_fps) > FPS_TOLERANCE:
        raise UnsafePackageError(f"Rendered preview is not approximately {expected_fps:g} fps.")
    expected_seconds = expected_duration_ms / 1000
    if abs(float(metadata["duration"]) - expected_seconds) > DURATION_TOLERANCE_SECONDS:
        raise UnsafePackageError("Rendered preview duration is outside the allowed tolerance.")
    backend.extract_first_frame(output_path, first_frame_path)
    checks = [
        "output_exists",
        "output_decodable",
        f"resolution_{expected_width}x{expected_height}",
        f"fps_approx_{int(expected_fps)}",
        "duration_within_tolerance",
        "first_frame_extracted",
    ]
    warnings: list[str] = []
    if metadata["has_audio"]:
        checks.append("audio_present")
    else:
        warnings.append("audio_not_present")
    return QCResult(
        output_sha256=compute_sha256(output_path),
        duration_seconds=float(metadata["duration"]),
        width=int(metadata["width"]),
        height=int(metadata["height"]),
        fps=float(metadata["fps"]),
        audio_present=bool(metadata["has_audio"]),
        checks=tuple(checks),
        warnings=tuple(warnings),
    )
