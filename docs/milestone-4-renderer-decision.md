# Milestone 4 Renderer Decision

Date: 2026-07-20
Base SHA: `2521b5db4d6351464b2092687c52dccc6a47c690`

## Goal

Implement the first real local preview worker without broadening the renderer surface beyond a safe, deterministic MVP.

## Reuse Decisions

### v1 `ffmpeg_tools.py`

- Reused:
  - executable resolution pattern via `find_executable`
  - ffprobe JSON probing approach
  - subprocess argument-array execution style from `run_command`
- Adapted:
  - moved preview-worker-specific probing/execution into `handoff_builder.v2.render.ffmpeg_backend`
- Reason:
  - keeps the milestone aligned with the accepted local FFmpeg foundation while avoiding a rewrite of the v1 analysis pipeline

### v2 queue/storage/services

- Reused:
  - SQLite workspace, package, plan, render job, and event persistence from Milestone 3
  - retry semantics based on new job attempts
- Adapted:
  - render job lifecycle now stores started/finished timestamps and failure metadata
- Reason:
  - preserves the accepted import/persist backbone and extends it additively into a real worker lifecycle

## FFmpeg Strategy Chosen

Chosen approach:

- one FFmpeg invocation per job
- per-segment `-ss` / `-to` inputs
- deterministic `filter_complex`
- normalization per segment:
  - explicit rotation normalization
  - `fps=30`
  - `scale=720:1280:force_original_aspect_ratio=increase`
  - `crop=720:1280`
  - `setsar=1`
  - `format=yuv420p`
- audio handling:
  - preserve source audio when present
  - inject deterministic silent stereo audio when absent
- concatenation through the FFmpeg `concat` filter

Why this path:

- works with actual transcoding and normalization in one pass
- stays deterministic and compatible with subprocess argument arrays
- avoids shell quoting issues on Windows Unicode/special-character paths
- avoids exposing raw filter strings to AI packages

## Alternatives Considered

### Concat demuxer as the main path

- Rejected as the primary milestone-4 foundation
- Reason:
  - concat demuxer is good for already-compatible files, but this milestone needs trim + normalize + scale/crop + audio normalization before concatenation
  - the filter-based concat path better fits this preview worker

### Multiple staged intermediate files

- Rejected for this milestone
- Reason:
  - would add extra IO, cleanup complexity, and more failure surfaces
  - one-pass filtered preview is sufficient for the narrow MVP operation set

### Raw AI-provided FFmpeg filters/commands

- Rejected
- Reason:
  - violates the core project safety boundary
  - would break deterministic compilation and auditability

## Encoding Contract Chosen

- resolution: `720x1280`
- fps: `30`
- video codec: `libx264`
- preset: `veryfast`
- quality: `crf=27`
- pixel format: `yuv420p`
- audio codec: `aac` when audio stream exists or synthesized silence is required
- audio bitrate: `128k`
- container behavior: `+faststart`

Reason:

- CPU-friendly local preview target for Windows
- visually sufficient for preview validation
- fast enough for milestone-4 smoke rendering

## Safety Boundaries Preserved

- no `shell=True`
- no raw FFmpeg strings from AI packages
- asset resolution only from controlled workspace/package paths
- semantic validation before process launch
- deterministic compiled plan persisted before execution
- failed jobs produce explicit stage/error metadata and do not produce false completed outputs

## Result

Milestone 4 uses a narrow, deterministic, FFmpeg-first preview renderer that is production-shaped enough to validate the backbone, while still keeping the full renderer surface intentionally small.
