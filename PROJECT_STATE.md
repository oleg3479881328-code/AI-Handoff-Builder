# Current State

- Date: 2026-07-20
- Repository: `oleg3479881328-code/AI-Handoff-Builder`
- Active contract: `Yt-Dlp-Download-Manager` issue `#67`
- Current branch: `feat/v2-import-persist-queue`
- Current phase: milestone 3 vertical slice implemented locally; pending review push/report

## What Exists Now

- Windows-ready v1 application for handoff ZIP preparation
- Tkinter GUI, CLI, FFmpeg-based analysis pipeline, tests, and PyInstaller packaging
- Local verification evidence from July 19-20, 2026:
  - `pytest` passed
  - smoke handoff ZIP built successfully
  - `coverage_ok=true` on the smoke validation report
  - portable EXE built with bundled `ffmpeg.exe` and `ffprobe.exe`

## Current Focus

Land the first working v2 execution backbone without changing accepted v1 behavior.

## Immediate Next Actions

1. Push and report the milestone 3 branch.
2. Review the persistence and queue contracts before adding real renderer execution.
3. Keep full FFmpeg render compilation, GUI wiring, and effect families deferred until this backbone is accepted.

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

## Constraints In Force

- No arbitrary FFmpeg strings from AI packages.
- No `shell=True`.
- No new second application.
- No cloud rendering.
- Keep scope inside the issue `#67` contract unless the owner changes it.
