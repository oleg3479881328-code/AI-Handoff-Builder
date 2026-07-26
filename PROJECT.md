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
- Phase: release-candidate baseline preserved; `AI_EDIT_PACKAGE` / `edit_plan` schema `2.1` handoff-derived workflow implemented and validated locally, including packaged `.exe` acceptance
- Active branch: `feat/issue-16-preview-scroll-fix`
- Draft PR: pending publication from `feat/issue-16-preview-scroll-fix` into `feat/issue-14-auto-project-root`
- Health: current FFmpeg, Voice Studio, metadata, Light/Dark release-candidate baseline, packaged schema resources, HyperFrames follow-up, schema `2.1` handoff-derived workflow, and Issue `#14` owner-flow remain intact; the new Issue `#16` fixes keep `Local Edit Runner (v2)` vertically scrollable, collapse diagnostic JSON out of the main operator path, and bind `Open Preview` to the current active imported plan instead of stale global prototype state; no private media or generated outputs are tracked

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
- Completed the bounded HyperFrames Lab implementation on `feat/hyperframes-lab`.
- Completed live local Windows acceptance for HyperFrames Lab through the real Tkinter UI and browser preview flow.
- Completed coordinator code/safety review follow-ups, including project-aware preview routing, repository-relative tests, and remote asset rejection inside trusted compositions.
- Opened draft PR `#4` from `feat/hyperframes-lab` into `codex/release-candidate-light-dark-ui`.
- Added schema `2.1` for:
  - `schemas/ai_edit_package/2.1.json`
  - `schemas/edit_plan/2.1.json`
- Preserved `2.0` unchanged while allowing ChatGPT-facing photo plans to contain only handoff-available asset fields.
- Moved original-file integrity back to the active local workspace registry during `2.1` import:
  - resolve by `asset_id`
  - read registry `sha256`, `size_bytes`, and `source_path`
  - hard-fail on missing, ambiguous, unreadable, size-mismatched, or checksum-mismatched originals
- Extended the local-photo import/render path, schema dispatch, and packaged schema loading so the same `2.1` workflow works in source and in the rebuilt Windows `.exe`.
- Completed real acceptance on the uploaded `WEDDING_PROJECT_ANALYSIS_HANDOFF.zip`:
  - generated handoff-derived plan-only ZIP with no media and no local path access
  - resolved 8 local originals from the active registry
  - rendered `1080x1920`, `30 fps`, `7.766667 s`, `audio=0`
  - confirmed the rebuilt packaged `.exe` contains schema resources through `2.1` and completed the same `2.1` import/render flow against a matching `WEDDING_PROJECT` workspace

## Current Focus

Publish the completed Issue `#16` scroll + current-preview-target implementation on a dedicated draft PR with exact local and packaged acceptance evidence.

## Next Practical Step

Push `feat/issue-16-preview-scroll-fix`, open one draft PR into `feat/issue-14-auto-project-root`, and post the execution report to Issue `#16`. No merge to `main`, `feat/issue-14-auto-project-root`, or `codex/release-candidate-light-dark-ui` is authorized.

## Key Decisions And Constraints

- Do not create a second application; extend the current standalone AI Handoff Builder.
- The bundled FFmpeg / ffprobe renderer remains the default production renderer.
- HyperFrames is approved only as an optional local experimental module until real owner-media validation succeeds.
- HyperFrames must not use cloud rendering in this integration.
- Do not execute arbitrary HTML or JavaScript supplied by an AI package; compile only allowlisted plans into trusted repository-owned templates.
- No remote scripts, fonts, media, iframes, arbitrary URLs, raw command strings, or `shell=True`.
- Do not modify originals on the owner machine.
- Personal media and generated outputs must not be committed to the public repository.
- GitHub currently has no configured CI/status checks for the draft PR head; recorded local regression evidence remains the validation source for this step.
- Schema `1.0` must not be changed in place; future capability widening requires a new version.
- GitHub is the execution source of truth for this project.
- Existing Solution First applies before inventing renderer, preview, or authoring patterns.
- No merge to `main` or `codex/release-candidate-light-dark-ui` without owner authorization.

## Read Next

- `PROJECT_STATE.md`
- `logs/latest.md`
- Issue `#10`: `https://github.com/oleg3479881328-code/AI-Handoff-Builder/issues/10`
- Issue `#8`: `https://github.com/oleg3479881328-code/AI-Handoff-Builder/issues/8`
- Issue `#2`: `https://github.com/oleg3479881328-code/AI-Handoff-Builder/issues/2`
