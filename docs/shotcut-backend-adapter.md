# Shotcut MCP Backend Adapter

Date: 2026-08-02
Issues: `#25`, `#27`, `#28`

## Issue #28 Extension - MASTER_AUDIO transcript workflow

The same repository-owned Shotcut boundary is now reused for the new owner workflow in Issue `#28`:

`Prepare Master Package -> MASTER_AUDIO.mp3 -> Gemini transcript import -> validated final ANALYSIS_HANDOFF.zip`

New owner-facing expectations:

- no final `ANALYSIS_HANDOFF.zip` before transcript import succeeds
- no mandatory master MP4 by default
- the canonical transcript source is the generated master MP3, not uploaded video
- the editable master `.mlt` remains a local project artifact the owner can open in Shotcut

Repository additions for this workflow include:

- `handoff_builder/v2/services/master_package_service.py`
- `handoff_builder/v2/services/transcript_service.py`
- `schemas/master_audio_transcript/1.0.json`

Date: 2026-07-29
Issues: `#25`, `#27`

## Goal

Add the smallest AI-Handoff-Builder integration boundary for a real, local Shotcut MCP backend without changing the existing FFmpeg production path, then expose that boundary as an owner-facing MVP inside the existing desktop app.

## Adapter Boundary

Code:

- `handoff_builder/v2/render/shotcut_backend.py`
- `handoff_builder/v2/render/backends.py`

The adapter remains intentionally narrow:

- `status`
- `doctor`
- `capabilities`
- `probe_media`
- `create_disposable_project`
- `inspect_project`
- `append_linked_clip`
- `trim_linked_clip`
- `plan_operations`
- `edit_operations`
- `validate_project`
- `render_preview`
- `render_contact_sheet`
- `open_in_shotcut`
- `start_render`
- `render_status`
- `await_render`
- `verify_rendered_media`

Issue `#25` established the code-level backend boundary.

Issue `#27` reuses that boundary inside the current Tkinter application. It does not replace the current FFmpeg queue and does not introduce a second app.

## Owner-Facing MVP Surface

The current owner-facing controls now live inside `Local Edit Runner (v2)` in `app.py`.

Exposed controls:

- backend selector:
  - `ffmpeg`
  - `shotcut`
- Shotcut runtime folder path
- donor `shotcut_mcp_server.py` path
- `Check Status`
- `Reset Paths`
- `Build Editable Project`
- `Open Editable Project`
- `Open in Shotcut`

Supporting code:

- `handoff_builder/v2/shotcut_settings.py`
- `handoff_builder/v2/services/shotcut_service.py`

Persisted local-only settings:

- `%LOCALAPPDATA%\\AI Handoff Builder\\shotcut_settings.json`

## Trust Boundary

AI-Handoff-Builder keeps Shotcut behind an adapter for these reasons:

- the donor server remains external and pinned
- path policy is enforced before every tool call
- absolute paths remain mandatory
- network resources remain disabled
- unsafe consumer properties remain disabled
- the adapter rejects malformed JSON-RPC replies and `isError=true` tool results
- durable render status is re-read before surfacing a terminal failure on the known Windows race

## Normalized Timeline Mapping

The adapter currently maps only a minimal local boundary:

- `ShotcutProfile`
  - validated width / height / fps
- `ShotcutClipIntent`
  - validated local media path
  - track
  - optional position
  - optional source in/out frames
  - optional caption

This keeps the AI-Handoff-Builder side bounded to:

- one linked clip create/append path
- one linked clip trim path
- caller-controlled inspect/plan/edit/validate/readback loop

The adapter does **not** expose the full donor operation catalog as an AI-facing schema.

## Donor Pin And Update Policy

- pinned donor tag: `v1.5.0`
- pinned donor SHA: `7e66c17b92c2058670ae5e4c21aa61e27c51d317`
- official Shotcut target for the proven path: `26.6.25`

Any donor upgrade should repeat:

1. donor audit
2. Windows proof
3. adapter regression tests
4. full repository tests

## Local Path Handling

The adapter requires caller-supplied allowed roots and resolves every path against them.

Authorized categories:

- donor server script
- local project path
- local source media path
- local preview/contact-sheet/render output paths

Redaction support is included for sanitized reporting:

- absolute private paths inside allowed roots become `<allowed-root-N>/...`

## Editable Project Workflow

The owner-facing MVP now supports a bounded editable-project loop for imported preview jobs:

1. select or auto-detect the local Shotcut runtime folder
2. select or auto-detect the donor `shotcut_mcp_server.py`
3. choose backend `shotcut`
4. build an editable `.mlt` from the selected imported job
5. optionally open the generated project in the local Shotcut desktop app
6. render the same job back into the existing workspace render location

Generated artifacts stay inside the current workspace:

- `renders/<job_id>/shotcut/editable_project.mlt`
- `renders/<job_id>/shotcut/preview.png`
- `renders/<job_id>/shotcut/contact_sheet.png`
- `renders/<job_id>/shotcut/runtime_status.json`
- `renders/<job_id>/shotcut/build_summary.json`
- `renders/<job_id>/shotcut/render_summary.json`
- `renders/<job_id>/reel.mp4`
- `renders/<job_id>/first_frame.jpg`

The service layer keeps the queue safe when the source job is already terminal by allowing a bounded rerender path instead of forcing invalid `pending -> running` transitions.

## Revision / Locking Model

AI-Handoff-Builder relies on donor semantics instead of re-implementing timeline locking:

- inspect project
- capture donor revision
- plan edits read-only
- apply edits only with `expected_revision`
- validate
- inspect saved state again

This preserves donor backups and atomic replace behavior.

## Readback Verification

The accepted proof path remains:

`intent -> inspect -> plan -> edit(expected_revision) -> validate -> inspect -> preview/contact-sheet -> render -> rendered-media probe`

The adapter treats any one of these as insufficient on its own:

- a process exit code
- raw `structuredContent` without checking `isError`
- a render request without durable final status

## Current Non-Goals

- no new planner
- no replacement of the FFmpeg backend
- no bundling of donor source or Shotcut binaries into the repository
- no arbitrary low-level MLT exposure to AI package payloads

## Validation Status

Repository validation on Wednesday, July 29, 2026:

- `python -m pytest -q tests/test_v2_shotcut_backend.py tests/test_v2_shotcut_service.py tests/test_app_v2_ui.py`
  - `20 passed in 3.09s`
- `python -m pytest -q`
  - `142 passed in 49.64s`

Live service-path validation on the existing local acceptance workspace:

- selected job:
  - `f35260850bb76dead667`
- build result:
  - `renderer_status=shotcut_editable_ready`
- render result:
  - `renderer_status=completed`
  - `540x960`
  - `30.0 fps`
  - `1.834 s`
  - `audio_present=1`
  - SHA-256:
    - `f0f94ee7b46e85ea1a3a9b95d6c899ea0c3f24676899c0a764f414fccdfcc234`

## Rollback / Uninstall

Rollback is local and source-only:

1. remove the adapter files:
   - `handoff_builder/v2/render/shotcut_backend.py`
   - `handoff_builder/v2/render/backends.py`
   - related tests/docs
2. keep the external donor checkout and official Shotcut portable runtime out of git
3. existing FFmpeg workflow continues unchanged because the current render service still instantiates `FFmpegBackend`

No database migration, schema mutation, or user-global tool registration is required for rollback.
