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
- Phase: repository bootstrap completed; v2 architecture and implementation not yet started
- Health: good baseline for v1 packaging flow; v2 local edit runner still unimplemented

## Done So Far

- Built and verified the standalone v1 Windows app locally from the owner's source folder.
- Added Windows hardening for v1: coverage-aware summary, cancel/retry-failed, bounded workers, Unicode-safe CLI, portable PyInstaller build with bundled `ffmpeg` and `ffprobe`.
- Created the dedicated GitHub repository `AI-Handoff-Builder` on July 20, 2026.

## Current Focus

Publish the current v1 baseline into the dedicated repository and initialize transfer-ready project files before starting the v2 local edit runner from issue `#67`.

## Next Practical Step

Push the current v1 baseline plus PEOS project-state files to `AI-Handoff-Builder`, then begin the existing-solution scan and architecture scaffolding required by issue `#67`.

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
