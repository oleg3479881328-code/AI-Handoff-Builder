# Shotcut MCP Backend Adapter

Date: 2026-07-28
Issue: `#25`

## Goal

Add the smallest AI-Handoff-Builder integration boundary for a real, local Shotcut MCP backend without changing the existing FFmpeg production path.

## Adapter Boundary

Code:

- `handoff_builder/v2/render/shotcut_backend.py`
- `handoff_builder/v2/render/backends.py`

The adapter is intentionally narrow:

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

This is a code-level backend boundary, not a new GUI workflow and not a replacement for the current FFmpeg queue.

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
- no GUI/operator surface in this issue
- no bundling of donor source or Shotcut binaries into the repository
- no arbitrary low-level MLT exposure to AI package payloads

## Rollback / Uninstall

Rollback is local and source-only:

1. remove the adapter files:
   - `handoff_builder/v2/render/shotcut_backend.py`
   - `handoff_builder/v2/render/backends.py`
   - related tests/docs
2. keep the external donor checkout and official Shotcut portable runtime out of git
3. existing FFmpeg workflow continues unchanged because the current render service still instantiates `FFmpegBackend`

No database migration, schema mutation, or user-global tool registration is required for rollback.
