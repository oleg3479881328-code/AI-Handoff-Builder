# Project

- Name: `AI-Handoff-Builder`
- Description: Standalone Windows application for preparing ChatGPT handoff packages from local photo/video media and importing AI edit plans for safe local rendering.
- Type: Desktop application / local media-processing tool

## Purpose

This project exists to keep original media and final rendering on Oleg's Windows machine while letting ChatGPT work with small machine-readable packages instead of raw footage.

Current success for this stage means:

- preserve the accepted Windows-ready release-candidate baseline;
- fix the no-silent-asset-loss defect tracked in issue `#2`;
- validate an optional local HyperFrames authoring/rendering path inside the same application without replacing the existing FFmpeg renderer;
- keep all personal media and generated outputs local.

## Source Of Truth

- Code and execution source of truth: GitHub repository `oleg3479881328-code/AI-Handoff-Builder`
- Broad v2 implementation contract: issue `#67` in `Yt-Dlp-Download-Manager`
- HyperFrames Lab implementation contract: issue `#3` in this repository
- Handoff completeness defect: issue `#2` in this repository
- Readable project-management layer: existing Notion page referenced by the owner

## Current Status

- Mode: active execution
- Phase: release candidate preserved; HyperFrames discovery branch initialized
- Active branch: `feat/hyperframes-lab`
- Health: current FFmpeg, Voice Studio, metadata, and Light/Dark release-candidate baseline remains intact; HyperFrames is not yet locally validated

## Done So Far

- Built and verified the standalone v1 Windows app locally from the owner's source folder.
- Added Windows hardening for v1: coverage-aware summary, cancel/retry-failed, bounded workers, Unicode-safe CLI, portable PyInstaller build with bundled FFmpeg, ffprobe, and ExifTool.
- Implemented the v2 local workspace, package import, safe preview render, QC, immutable patch/rerender loop, and Voice Studio inside the existing Tkinter app.
- Completed the release-candidate Light/Dark theme layer on `codex/release-candidate-light-dark-ui` with `87 passed` and a successful portable build.
- Recorded the missing-audio / incomplete-handoff defect in issue `#2`.
- Approved HyperFrames as an existing open-source donor for an optional local experimental renderer.
- Created branch `feat/hyperframes-lab` from the release candidate.
- Added the integration decision and a trusted 1080x1920 photo-composition prototype under `prototypes/hyperframes/`.
- Created executable implementation handoff issue `#3`.

## Current Focus

Validate the official HyperFrames CLI locally on Windows with the six owner café photographs, then add the smallest safe adapter and themed in-app `HyperFrames Lab` surface without weakening the current FFmpeg boundary.

## Next Practical Step

Executor runs issue `#3` on the owner Windows workspace: verify the official HyperFrames runtime, preview and render the checked-in trusted composition using the six private local photographs, then implement and test the bounded adapter inside the existing app.

## Key Decisions And Constraints

- Do not create a second application; extend the current standalone AI Handoff Builder.
- The bundled FFmpeg / ffprobe renderer remains the default production renderer.
- HyperFrames is approved only as an optional local experimental module until real owner-media validation succeeds.
- HyperFrames must not use cloud rendering in this integration.
- Do not execute arbitrary HTML or JavaScript supplied by an AI package; compile only allowlisted plans into trusted repository-owned templates.
- No remote scripts, fonts, media, iframes, arbitrary URLs, raw command strings, or `shell=True`.
- Do not modify originals on the owner machine.
- Personal media and generated outputs must not be committed to the public repository.
- Schema `1.0` must not be changed in place; future capability widening requires a new version.
- GitHub is the execution source of truth for this project.
- Existing Solution First applies before inventing renderer, preview, or authoring patterns.
- No merge to `main` without owner authorization.

## Read Next

- `PROJECT_STATE.md`
- `logs/latest.md`
- `docs/HYPERFRAMES_INTEGRATION.md`
- `prototypes/hyperframes/README.md`
- Issue `#3`: `https://github.com/oleg3479881328-code/AI-Handoff-Builder/issues/3`
- Issue `#2`: `https://github.com/oleg3479881328-code/AI-Handoff-Builder/issues/2`
