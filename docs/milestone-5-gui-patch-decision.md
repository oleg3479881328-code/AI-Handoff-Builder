# Milestone 5 GUI + Patch Decision

Date: 2026-07-20
Branch: `feat/v2-gui-patch-loop`
Base: `feat/v2-preview-render-worker` at `e8cc5113657c45ce7b10db261af549d0e978972a`

## Existing Solutions Checked

### Current Tkinter patterns in this repository

- `app.py` already used a responsive background-worker pattern:
  - long-running work on `threading.Thread`
  - thread-safe `queue.Queue`
  - Tkinter `after()` polling on the UI thread
- This pattern was reused directly for v2 instead of introducing asyncio, multiprocessing, or a second UI framework.

### Existing v2 import / queue / render services

- Reused:
  - `init_project_workspace(...)`
  - `import_package_into_workspace(...)`
  - `render_job(...)`
  - `render_next_pending_job(...)`
  - SQLite repositories, migrations, and report stub generation
- Extended additively:
  - immutable plan lineage
  - patch persistence
  - exact-workspace contract
  - queue query / retry / cancel helpers

### Python Tkinter background worker / `after()` queue patterns

- The existing v1 pattern was already the right fit for owner-facing FFmpeg work.
- The v2 controller keeps service logic out of widget callbacks and reports results back through the same queue + `after()` polling style.

### Current SQLite transaction and idempotency design

- Reused Milestone 3-4 transaction boundaries:
  - write rows only inside explicit transactions
  - rollback on validation / persistence failure
  - render job and report stub creation remain additive
- Extended idempotency by keying patch reuse on:
  - `project_id`
  - `patch_sha256`
  - `base_plan_id`

### JSON Patch / JSON Merge Patch concepts

- Reviewed only as references.
- Rejected as the primary contract because they would allow writes outside the explicit allowlist and would make owner-facing safety review harder.
- Instead, Milestone 5 uses a narrow semantic patch model with explicit operations:
  - `update_segment`
  - `remove_segment`
  - `duplicate_segment`
  - `reorder_segments`

## Reuse / Adapt / Reject

### Reuse

- Existing Tkinter worker queue pattern
- Existing v2 import / render / QC service boundaries
- Existing SQLite repositories and additive migrations
- Existing package extraction / checksum / path safety

### Adapt

- Exact-workspace initialization replaced the old accidental double-nesting behavior.
- Imported base plans are normalized with stable synthetic `operation_id` values when the original package did not provide them.
- Render cancellation now reaches FFmpeg through a cancel event and preserves queue semantics.

### Reject

- Generic JSON Patch / JSON Merge Patch as a live mutation layer
- A second standalone app
- Arbitrary FFmpeg strings in patches
- ORM migration or database rewrite

## Why Custom Implementation Was Necessary

- The repository already had the right architectural seams, but not the immutable patch lineage, GUI workflow, or patch-safe allowlist required by the milestone.
- The new implementation stays thin:
  - patch schema + semantic application
  - additive SQLite lineage
  - controller layer for Tkinter
  - small CLI surface for recovery and tests

## Chosen Contract

### Workspace path contract

- Chosen mode: exact-workspace mode
- `v2 init-project <workspace> --project-id <id>` now creates or reopens the workspace exactly at `<workspace>`.
- It does not append an extra `project_id` directory.

### Patch identity contract

- Each accepted patch produces:
  - `patch_id`
  - `patch_sha256`
  - `base_plan_id`
  - `base_plan_hash`
  - `new_plan_id`
  - `new_plan_hash`
  - `created_at`

### Immutable lineage contract

- Imported base plan remains untouched.
- Patch application writes a derived plan under workspace-owned patch storage.
- Previous render outputs and reports remain available side by side with new outputs.
