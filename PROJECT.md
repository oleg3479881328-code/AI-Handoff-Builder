# Project

- Name: `AI-Handoff-Builder`
- Description: Standalone Windows application for preparing ChatGPT handoff packages from local photo/video media and, in the next phase, importing AI edit plans for safe local rendering.
- Type: Desktop application / local media-processing tool

## Purpose

This project exists to keep original media and final rendering on Oleg's Windows machine while letting ChatGPT work with small machine-readable packages instead of raw footage.

Current success for this stage means:

- the project is durably published in its own GitHub repository;
- the existing Windows-ready v1 baseline is preserved;
- issue `#67` becomes executable from a transfer-ready repo state.

## Source Of Truth

- Code and execution source of truth: GitHub repository `oleg3479881328-code/AI-Handoff-Builder`
- Active implementation contract: issue `#67` in `Yt-Dlp-Download-Manager`
- Readable project-management layer: existing Notion page referenced by the owner

## Current Status

- Mode: active execution
- Phase: first v2 vertical slice implemented on feature branch; full renderer still deferred
- Health: v1 remains stable and v2 now has a working import -> SQLite -> queue -> render-report backbone

## Done So Far

- Built and verified the standalone v1 Windows app locally from the owner's source folder.
- Added Windows hardening for v1: coverage-aware summary, cancel/retry-failed, bounded workers, Unicode-safe CLI, portable PyInstaller build with bundled `ffmpeg` and `ffprobe`.
- Created the dedicated GitHub repository `AI-Handoff-Builder` on July 20, 2026.
- Published the initial baseline to `main` with remote commit `dbaa4199d45137370166c716b40f33b2eafa7c7c`.
- Completed the milestone 2 existing-solution scan and v2 architecture skeleton on feature branch `feat/v2-architecture-skeleton`.
- Completed the milestone 3 first vertical slice on feature branch `feat/v2-import-persist-queue`: safe package import, SQLite persistence, queue operations, render report stub, and CLI commands.

## Current Focus

Keep the milestone 3 branch review-ready and use it as the base for the first non-stub render execution slice after owner approval.

## Next Practical Step

Review and accept the milestone 3 backbone, then implement the next slice: queued job execution and stub-to-real render progression without breaking current persistence contracts.

## Key Decisions And Constraints

- Do not create a second application; extend the current standalone AI Handoff Builder.
- Use bundled `ffmpeg` / `ffprobe` as the production renderer.
- Do not introduce Remotion, browser rendering, PostgreSQL, microservices, or cloud rendering in this MVP.
- The renderer must compile only allowlisted operations into safe FFmpeg argument arrays and must not use `shell=True`.
- GitHub is the execution source of truth for this project.
- Existing Solution First applies before inventing new renderer/schema patterns.

## Read Next

- `PROJECT_STATE.md`
- `logs/latest.md`
- `docs/EXECUTOR_TASK.md`
- Issue `#67`: `https://github.com/oleg3479881328-code/Yt-Dlp-Download-Manager/issues/67`
