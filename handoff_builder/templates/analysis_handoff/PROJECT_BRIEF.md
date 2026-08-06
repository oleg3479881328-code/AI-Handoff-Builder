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

## DIRECT SHOTCUT MLT MODE - NO USER FILE MOVEMENT

- Status: `{{DIRECT_MLT_MODE_STATUS}}`
- `{{DIRECT_MLT_MODE_NOTE}}`
- When direct mode is available, `ASSISTANT_CONTEXT.json` is the source of truth for:
  - actual local project root
  - actual originals root
  - actual proxies root
  - complete `asset_id -> original filename -> original path` mapping
- Preferred edit source is `originals`.
- The downloaded `.mlt` may be opened from any folder.
- No user file movement is required.

## Constraints

1. Use only declared `asset_id` values from the manifest.
2. Produce exactly one standalone JSON file and nothing else.
3. For the normal JSON workflow, do not include local paths, original SHA-256, original size, or registry data.
4. Unknown schema versions must hard-fail.
5. Use rational timebase (`fps_num`/`fps_den`) and explicit integer frame positions.
6. All timeline placement must be explicit; do not infer ordering from asset lists.
7. Use `source_audio_policy` enum instead of raw mute/command fields.
8. No executable payloads, FFmpeg filters, scripts, Python, JavaScript, shell, remote URLs, or MLT/XML.
9. Never substitute proxies when direct mode says `preferred_edit_source=originals`.
10. Never infer local paths from screenshots when `ASSISTANT_CONTEXT.json` exists.
