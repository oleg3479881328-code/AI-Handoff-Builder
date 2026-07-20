# Latest Log

Date: 2026-07-20
Step: Milestone 5 desktop GUI workflow + immutable patch rerender loop

## Completed

- Read the Milestone 5 handoff page in Notion and used it as the active execution contract.
- Re-verified accepted Milestone 4 branch `feat/v2-preview-render-worker` at SHA `e8cc5113657c45ce7b10db261af549d0e978972a`.
- Created feature branch `feat/v2-gui-patch-loop`.
- Added `docs/milestone-5-gui-patch-decision.md` with explicit reuse / adapt / reject notes for Tkinter, v2 services, SQLite lineage, and patch safety.
- Switched `v2 init-project` to an exact-workspace contract to remove accidental double nesting.
- Added immutable patch application with additive SQLite lineage and idempotent patch reuse.
- Added CLI commands `v2 apply-patch`, `v2 plan-list`, and `v2 plan-show`.
- Added queue query / retry / cancel services and cancel-aware FFmpeg rendering.
- Extended the existing Tkinter desktop app with v2 owner-facing sections for:
  - workspace create/open
  - package import
  - render queue operations
  - results / QC inspection
  - patch import and rerender
- Added a headless-testable `V2RunnerController` to keep service logic outside widget callbacks.
- Added bounded tests for patch lineage, rollback, exact-workspace behavior, and GUI controller state transitions.

## Verification

- `python -m pytest -q` -> `50 passed`
- `python -m handoff_builder.cli --help` -> success
- `python -m handoff_builder.cli v2 --help` -> success
- `python -m handoff_builder.cli v2 apply-patch --help` -> success
- `python -m handoff_builder.cli v2 plan-list --help` -> success
- `python -m handoff_builder.cli v2 plan-show --help` -> success
- `python -c "import handoff_builder.v2"` -> success
- `git diff --check` -> pending final branch sweep
- real Windows Tkinter GUI smoke -> completed on July 20, 2026
  - workspace path: `C:\Users\oleg3\Documents\AI Handoff Builder v1\tmp_gui_smoke_m5\Рабочая папка & Oleg's\gui-workspace`
  - imported package through the desktop app
  - base plan: `plan-gui-1`
  - base plan hash: `0ea3280b5450003aec615f0a1898e495651aa249d88a8f7876381e868fb73e3c`
  - base render job: `ab80c272926cb2713356`
  - derived plan: `a33c4e273f630ec12212`
  - derived plan version: `2`
  - derived plan hash: `fb4378b5d91881248b5846397b3c7c3f3dba5044b6e5a043d63b43f25a83ae71`
  - derived render job: `185805b03f892b22b8d2`
  - both outputs remained available
  - `first_frame.jpg` displayed and existed for the rerendered output
  - rerender QC stayed green: `720x1280`, ~`30 fps`, duration within tolerance, audio present, first-frame extracted

## Reuse / Adapt

- Reuse: existing Tkinter `threading + Queue + after()` pattern, v2 import/render/QC services, SQLite transaction boundaries, ZIP safety, hashing, and CLI compatibility.
- Adapt: exact-workspace initialization, synthetic stable `operation_id` normalization for imported base plans, additive patch lineage, and owner-facing render cancellation.

## Notes

- Generic JSON Patch / JSON Merge Patch was reviewed only as reference and rejected as the primary contract because it would allow writes outside the narrow patch allowlist.
- Patch idempotency is keyed by `project_id + patch_sha256 + base_plan_id`.
- Previous plans, render jobs, reports, and outputs remain immutable and available after rerender.

## Next

- Run the final branch-wide validation sweep and verify local/remote SHA match after push.
- Create the dedicated Milestone 5 execution report page in Notion.
- Wait for owner review before widening supported renderer operations beyond the current patch allowlist.
