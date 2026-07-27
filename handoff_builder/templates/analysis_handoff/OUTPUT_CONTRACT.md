# Output Contract

> The AI must produce exactly one valid `AI_EDIT_PACKAGE.zip` matching the specifications below.

## Required Schema Versions

- `ai_edit_package`: **3.0**
- `edit_plan`: **3.0**

## Package Structure

```
AI_EDIT_PACKAGE.zip
├── ai_edit_package.json
├── plans/
│   └── plan-{plan_id}.json
└── assets/
    └── audio/          (optional generated audio)
```

## Package Manifest (`ai_edit_package.json`)

Required fields:
- `schema_version` — must be `"3.0"`
- `package_type` — must be `"ai_edit_package"`
- `project_id` — from the handoff manifest
- `handoff_id` — from the handoff manifest
- `handoff_sha256` — from the handoff manifest
- `plans` — array of plan references with `plan_id`, `path`, `sha256`, `size_bytes`
- `audio_assets` — array of audio asset references (if any) with `audio_id`, `path`, `sha256`, `size_bytes`
- `file_inventory` — exact list of all files in the ZIP
- `content_hash` — canonical hash of the manifest

## Edit Plan (`plans/plan-{plan_id}.json`)

Required fields:
- `schema_version` — must be `"3.0"`
- `plan_id` — unique plan identifier
- `project_id` — from the handoff manifest
- `handoff_id` — from the handoff manifest
- `handoff_sha256` — from the handoff manifest
- `canvas` — output dimensions: `width`, `height`
- `timebase` — rational timebase: `fps_num`, `fps_den`
- `assets` — array of asset references with only:
  - `asset_id`
  - `media_type` (`photo`, `video`, `audio`)
  - `original_name` (optional)
- `visual_items` — array of visual timeline items, each with:
  - `item_id`
  - `asset_id`
  - `media_type`
  - `timeline_start_frame` (integer)
  - `duration_frames` (integer)
  - `source_in_us` (integer, microseconds)
  - `source_out_us` (integer, microseconds)
  - `source_audio_policy` — one of: `discard`, `keep`, `duck_under_music`, `replace`
- `audio_items` — array of audio timeline items (if any), each with:
  - `item_id`
  - `audio_id`
  - `role` — `music` or `voiceover`
  - `timeline_start_frame` (integer)
  - `duration_frames` (integer)
  - `source_in_us` (integer, optional)
  - `source_out_us` (integer, optional)
  - `gain` (number, dB)
- `renderer` — renderer requirements:
  - `primary_renderer` — must be `"davinci"`
  - `capabilities` — array of required capabilities

## Forbidden Fields

Do not include:
- `source_path`, `absolute_path`, or any local path
- Original-file `sha256` or `size_bytes`
- Registry data
- `ffmpeg`, `ffmpeg_args`, `ffmpeg_filter`, `filter_complex`, `command`, `shell`
- `mute_original_audio` (use `source_audio_policy` instead)

## Validation Rules

1. Every file in the ZIP must be declared in `file_inventory`.
2. Every declared file must be present in the ZIP.
3. SHA-256 and size must match for every declared file.
4. Unknown schema versions must hard-fail.
5. Every selected asset must have an explicit status.
6. `source_audio_policy` must be one of the allowed enum values.
7. `discard` is the only required implementation; other values return unsupported error.
