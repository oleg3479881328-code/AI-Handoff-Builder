# Current State

- Date: 2026-07-20
- Repository: `oleg3479881328-code/AI-Handoff-Builder`
- Active contract: `Yt-Dlp-Download-Manager` issue `#67`
- Current branch: `feat/v2-gui-patch-loop`
- Current phase: milestone 5 desktop GUI workflow and immutable patch rerender loop implemented locally; pending review push/report

## What Exists Now

- Windows-ready v1 application for handoff ZIP preparation
- Tkinter GUI, CLI, FFmpeg-based analysis pipeline, tests, and PyInstaller packaging
- Local verification evidence from July 19-20, 2026:
  - `pytest` passed
  - smoke handoff ZIP built successfully
  - `coverage_ok=true` on the smoke validation report
  - portable EXE built with bundled `ffmpeg.exe` and `ffprobe.exe`

## Current Focus

Land the first owner-facing v2 desktop workflow without changing accepted v1 behavior.

## Immediate Next Actions

1. Push and report the milestone 5 branch.
2. Review the desktop patch loop and exact-workspace contract before widening supported operations.
3. Keep broader effects, music/text/TTS families, and final/full-quality rendering deferred until this slice is accepted.

## Published Baseline

- Remote URL: `https://github.com/oleg3479881328-code/AI-Handoff-Builder`
- Remote branch: `main`
- Verified remote SHA: `196886bd7eb26671b6999539220261fe753920a6`

## Milestone 2 Results

- Added `docs/existing-solution-scan.md` with explicit reuse / adapt / reject decisions.
- Added `docs/v2-local-edit-runner-architecture.md` covering required boundaries.
- Added `schemas/**` versioned skeletons for `ai_edit_package`, `edit_plan`, `edit_patch`, and `render_report`.
- Added importable `handoff_builder/v2/**` skeleton:
  - `domain`
  - `packages`
  - `plans`
  - `storage`
  - `render`
  - `qc`
  - `errors`
- Added bounded safety and architecture tests in `tests/test_v2_architecture.py`.
- Validation on branch:
  - `python -m pytest -q` -> `17 passed`
  - `python -c "import handoff_builder.v2"` -> success
  - `git diff --check` -> clean

## Milestone 3 Results

- Added SQLite-backed project workspace initialization with additive migrations.
- Added persistence for:
  - `projects`
  - `ai_packages`
  - `edit_plans`
  - `render_jobs`
  - `render_outputs`
  - `events`
- Added atomic import orchestration:
  - safe package import
  - schema validation
  - checksum and project binding validation
  - persisted package + plan
  - one pending render job
  - initial `render_report.json` stub
- Added v2 CLI commands:
  - `v2 init-project`
  - `v2 import-package`
  - `v2 queue-list`
  - `v2 queue-show`
- Added queue transitions and retry path on top of SQLite persistence.
- Validation on branch:
  - `python -m pytest -q` -> `31 passed`
  - legacy `python -m handoff_builder.cli --help` -> success
  - `python -m handoff_builder.cli v2 --help` -> success
  - `python -m handoff_builder.cli v2 init-project --help` -> success
  - `python -m handoff_builder.cli v2 import-package --help` -> success
  - `python -m handoff_builder.cli v2 queue-list --help` -> success
  - `python -c "import handoff_builder.v2"` -> success

## Milestone 4 Results

- Added focused renderer decision note at `docs/milestone-4-renderer-decision.md`.
- Added strict semantic preview-plan validation with controlled asset-path resolution.
- Added deterministic FFmpeg compiler for allowlisted preview operations.
- Added real local preview worker lifecycle:
  - claim/mark running
  - compile
  - execute
  - QC
  - mark completed/failed
- Added render artifacts:
  - `reel.mp4`
  - `render_plan.json`
  - `render_report.json`
  - `ffmpeg_command.json`
  - `first_frame.jpg`
- Added basic QC for resolution, fps, duration tolerance, first frame extraction, audio presence, and output SHA-256.
- Added CLI commands:
  - `v2 render-next`
  - `v2 render-job`
- Added additive render-job lifecycle DB fields and tests.
- Validation on branch:
  - `python -m pytest -q` -> `41 passed`
  - legacy and v2 CLI help commands -> success
  - real local FFmpeg preview smoke -> completed on July 20, 2026 (`5d98c33ca4eac8dfb0a4`)
    - workspace path included Cyrillic, spaces, `&`, and apostrophe characters
    - `render_report.json` confirmed `720x1280`, `30.0 fps`, `1.4s`, `audio_present=1`
    - `first_frame.jpg` extracted and `ffprobe` matched expected output shape

## Constraints In Force

- No arbitrary FFmpeg strings from AI packages.
- No `shell=True`.
- No new second application.
- No cloud rendering.
- Keep scope inside the issue `#67` contract unless the owner changes it.

## Milestone 5 Results

- Added `docs/milestone-5-gui-patch-decision.md` documenting reuse from Tkinter worker queues, v2 services, SQLite transactions, and the rejection of generic JSON Patch as the live mutation layer.
- Switched `v2 init-project` to an exact-workspace contract so the selected path is the real workspace root and no extra `project_id` folder is appended.
- Added immutable patch support for:
  - `AI_EDIT_PATCH.json`
  - `AI_EDIT_PATCH.zip`
- Added additive persistence for:
  - `edit_patches`
  - plan lineage on `edit_plans`
  - base plan hash / parent plan / patch ID / plan version
- Added patch allowlist operations:
  - `update_segment`
  - `remove_segment`
  - `duplicate_segment`
  - `reorder_segments`
- Added v2 services for:
  - apply patch in workspace
  - list/show plans
  - list/show render jobs
  - retry render job
  - request cancel render job
- Added cancel-aware FFmpeg rendering through a propagated cancel event.
- Added Tkinter v2 owner-facing workflow inside the same app:
  - create/open workspace
  - import package
  - inspect plan summary
  - run selected job / next pending job
  - refresh queue
  - retry / cancel
  - open output directory / reel / report / FFmpeg command
  - preview `first_frame.jpg`
  - inspect QC and error details
  - import patch and rerender
- Added a headless-testable `V2RunnerController` for state transitions outside widget callbacks.
- Added CLI commands:
  - `v2 apply-patch`
  - `v2 plan-list`
  - `v2 plan-show`
- Validation on branch:
  - `python -m pytest -q` -> `50 passed`
  - legacy and v2 CLI help commands -> success
  - `python -c "import handoff_builder.v2"` -> success
  - real Windows Tkinter GUI smoke -> completed on July 20, 2026
    - workspace path included Cyrillic, spaces, `&`, and apostrophe characters
    - package import completed through the desktop app
    - base preview render completed with QC artifacts preserved
    - patch import created immutable plan v2 and a new render job
    - rerender completed with a different plan hash and different render job ID
    - both old and new outputs remained available
