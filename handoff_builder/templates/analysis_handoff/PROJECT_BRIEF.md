# Project Brief

> This file is rendered from project-specific values. The structure is owned by the repository.

## Project

- **Project ID**: `{{PROJECT_ID}}`
- **Project Name**: `{{PROJECT_NAME}}`
- **Handoff ID**: `{{HANDOFF_ID}}`
- **Created**: `{{CREATED_AT}}`
- **Target Editor**: `Shotcut`

## Source Material

This handoff contains analysis representations of the following media types:

- **Photos**: {{PHOTO_COUNT}} files
- **Videos**: {{VIDEO_COUNT}} files
- **Audio**: {{AUDIO_COUNT}} files

## Goal

Create a precise edit plan that AI Handoff Builder can compile into an editable Shotcut project.

## Constraints

1. Use only declared `asset_id` values from the manifest.
2. Produce exactly one standalone JSON file and nothing else.
3. Do not include local paths, original SHA-256, original size, or registry data.
4. Unknown schema versions must hard-fail.
5. Use rational timebase (`fps_num`/`fps_den`) and explicit integer frame positions.
6. All timeline placement must be explicit; do not infer ordering from asset lists.
7. Use `source_audio_policy` enum instead of raw mute/command fields.
8. No executable payloads, FFmpeg filters, scripts, Python, JavaScript, shell, remote URLs, or MLT/XML.
