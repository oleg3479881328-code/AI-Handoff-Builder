# Project Log

## 2026-07-20

- Created the dedicated GitHub repository `oleg3479881328-code/AI-Handoff-Builder`.
- Bootstrapped `PROJECT.md`, `AGENTS.md`, `PROJECT_STATE.md`, and `logs/latest.md`.
- Prepared the locally verified v1 application baseline for first publication.
- Published the baseline to `main` at `dbaa4199d45137370166c716b40f33b2eafa7c7c`.
- Completed Milestone 2 architecture skeleton on branch `feat/v2-architecture-skeleton`.
- Added existing solution scan, v2 architecture doc, versioned schema skeletons, v2 package boundaries, and bounded architecture/security tests.
- Completed Milestone 3 first vertical slice on branch `feat/v2-import-persist-queue`.
- Added SQLite persistence, atomic import orchestration, queue operations, render report stub generation, v2 CLI commands, and bounded persistence/queue tests.
- Completed Milestone 4 real local preview worker on branch `feat/v2-preview-render-worker`.
- Added semantic plan validation, deterministic FFmpeg preview compilation, worker lifecycle, QC, render artifact persistence, and preview-worker tests.
- Finalized Milestone 4 validation with a real local FFmpeg smoke on a workspace path containing Cyrillic, spaces, `&`, and apostrophe characters.
- Tightened the queue claim lifecycle so `started_at` is persisted for jobs rendered via `v2 render-next`.
- Completed Milestone 5 desktop GUI workflow + immutable patch rerender loop on branch `feat/v2-gui-patch-loop`.
- Added exact-workspace initialization, immutable patch lineage, patch CLI commands, queue query/retry/cancel services, and a cancel-aware FFmpeg path.
- Extended the existing Tkinter app with owner-facing v2 workspace import/render/QC/patch sections and validated the full GUI loop on a real Windows path containing Cyrillic, spaces, `&`, and apostrophe characters.

## 2026-07-28

- Re-entered Issue `#25` through Project Execution OS and isolated the work on branch `experiment/shotcut-mcp-windows-proof` from the accepted base SHA `67b74e9d512012829efb9c990a1055d3f43eb59b`.
- Re-ran the clean Issue `#25` baseline and confirmed `python -m pytest -q` -> `124 passed`.
- Audited pinned donor `matrodrigs/shotcut-mcp` tag `v1.5.0` at full SHA `7e66c17b92c2058670ae5e4c21aa61e27c51d317`.
- Verified official Shotcut `26.6.25` plus `melt.exe 7.40.0` and bundled `ffmpeg/ffprobe n8.1.2` in an isolated local proof workspace.
- Repeated Gate 4 from scratch on one owner-selected real MP4 and completed the full 15-step proof with real project readback before and after mutation, preview, contact sheet, open-in-Shotcut, render, rendered-media probe, and final inspect.
- Posted the sanitized GitHub checkpoint `REAL_SHOTCUT_MCP_PROOF_PASSED` to Issue `#25`.
- Documented two real Windows donor integration issues discovered during the proof:
  - detached worker import visibility from a raw donor checkout
  - a short `render_status` finalization race before durable metadata settles
- Added a bounded Shotcut backend adapter in the repository under `handoff_builder/v2/render/shotcut_backend.py` and `handoff_builder/v2/render/backends.py`.
- Added focused regression coverage in `tests/test_v2_shotcut_backend.py`.
- Added `docs/shotcut-mcp-donor-audit.md` and `docs/shotcut-backend-adapter.md`.
