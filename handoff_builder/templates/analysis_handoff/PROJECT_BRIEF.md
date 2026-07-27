# Project Brief

> This file is rendered from project-specific values. The structure is owned by the repository.

## Project

- **Project ID**: `{{PROJECT_ID}}`
- **Handoff ID**: `{{HANDOFF_ID}}`
- **Created**: `{{CREATED_AT}}`

## Source Material

This handoff contains analysis representations of the following media types:

- **Photos**: {{PHOTO_COUNT}} files
- **Videos**: {{VIDEO_COUNT}} files
- **Audio**: {{AUDIO_COUNT}} files

## Goal

Create a precise edit plan that can be compiled into a DaVinci Resolve timeline.

## Constraints

1. Use only declared `asset_id` values from the manifest.
2. Do not include local paths, original SHA-256, original size, or registry data.
3. Every selected asset must have an explicit status in the output.
4. Unknown schema versions must hard-fail.
5. Use rational timebase (`fps_num`/`fps_den`) and integer frame positions.
6. Use `source_audio_policy` enum instead of `mute_original_audio`.
7. No executable payloads (shell commands, FFmpeg filters, scripts).
