# Output Contract

> The AI must produce exactly one valid standalone JSON edit plan for Shotcut.

## Required Schema Version

- `edit_plan`: **3.0**

## Required Output Filename

- exact filename: `{{EXPECTED_OUTPUT_FILENAME}}`
- exactly one returned file
- no ZIP wrapper
- no copied input media

## Edit Plan JSON

Required top-level fields:

- `schema_version` = `"3.0"`
- `document_type` = `"edit_plan"`
- `project_id` = from `handoff_manifest.json`
- `project_name` = from `handoff_manifest.json`
- `handoff_id` = from `handoff_manifest.json`
- `handoff_content_hash` = `handoff_manifest.json.content_hash`
- `plan_id` = stable non-empty plan id
- `plan_version` = integer >= 1
- `canvas`
- `timebase`
- `assets`
- `visual_items`
- `audio_items`
- `text_items`
- `renderer.primary_renderer` = `"shotcut"`

## Asset Rules

- `assets` may contain only `asset_id`, `media_type`, and optional `original_name`.
- `visual_items` must use explicit `track_id`, `timeline_start_frame`, `duration_frames`, `source_in_us`, `source_out_us`, and `source_audio_policy`.
- Photo items use `source_in_us=0` and `source_out_us=0`.
- Audio items may reference only already-registered local assets by `audio_id`.

## Forbidden Content

Do not include:

- local paths or absolute paths
- original file SHA-256 or size
- registry records
- commands, scripts, Python, JavaScript, shell
- FFmpeg fields or filters
- MLT/XML
- remote URLs
- manifest wrappers
- ZIP structure instructions
- returned proxies, previews, photos, video, audio, metadata copies, or any other media files

## Validation Rules

1. Unknown schema versions must hard-fail.
2. `renderer.primary_renderer` must be exactly `shotcut`.
3. Only implemented `source_audio_policy` values may pass validation.
4. Every `asset_id` used in timeline items must appear in `assets`.
5. The local app will verify `project_id`, `handoff_id`, and `handoff_content_hash` against the saved handoff manifest and local asset registry before creating the `.mlt`.
