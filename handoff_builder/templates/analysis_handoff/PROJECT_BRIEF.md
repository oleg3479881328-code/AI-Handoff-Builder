# Project Brief

## Project

- Project ID: `{{PROJECT_ID}}`
- Project Name: `{{PROJECT_NAME}}`
- Handoff ID: `{{HANDOFF_ID}}`
- Created: `{{CREATED_AT}}`

## Proven Workflow

The repository-owned workflow for this package is:

`MLT + MP3 + timeline map -> Gemini transcript import -> validated ANALYSIS_HANDOFF.zip`

This means:

- the package keeps the Shotcut-oriented local contract;
- the master timeline already exists;
- the master MP3 already exists;
- the transcript already passed local validation before this ZIP was created.

## Included Source Material

- Photos: `{{PHOTO_COUNT}}`
- Videos: `{{VIDEO_COUNT}}`
- Audio-only sources: `{{AUDIO_COUNT}}`

## Constraints

1. Preserve the owner-visible timeline ordering from `MASTER_TIMELINE_MAP.json`.
2. Preserve overlapping transcript events when they exist.
3. Preserve transcript text and event metadata instead of auto-correcting it.
4. Treat pending AI-analysis maps as intentionally empty placeholders, not as missing local implementation.
5. Do not require a master MP4 unless the owner explicitly requested it separately.
6. This final package is not the old standalone JSON-first handoff; the standalone JSON path belongs to the earlier Issue #27 workflow.
