# Project

- Name: `AI-Handoff-Builder`
- Description: Standalone Windows application for preparing ChatGPT handoff packages from local photo/video media and importing AI edit plans for safe local rendering.
- Type: Desktop application / local media-processing tool

## Purpose

This project exists to keep original media and final rendering on Oleg's Windows machine while letting ChatGPT work with small machine-readable packages instead of raw footage.

Current success for this stage means:

- implement the standalone `Handoff Light` Windows executable tracked in issue `#29`;
- preserve the existing AI Handoff Builder / PR `#26` boundary untouched;
- support persistent projects, recursive ZIP ingestion, deduplicated asset registry, and versioned immutable Handoff ZIP export;
- keep all personal media and generated outputs local.

## Source Of Truth

- Code and execution source of truth: GitHub repository `oleg3479881328-code/AI-Handoff-Builder`
- Standalone Handoff Light implementation contract: issue `#29` in this repository
- Readable project-management layer: existing Notion page referenced by the owner

## Current Status

- Mode: active execution
- Phase: standalone `Handoff Light` MVP implemented and validated locally, including persistent projects, recursive safe archive ingestion, immutable `V001/V002/...` exports, packaged `.exe` launch, and minimal owner-facing GUI
- Active branch: `feat/handoff-light-standalone`
- Draft PR: pending publication from `feat/handoff-light-standalone`
- Health: the new standalone `Handoff Light` surface is isolated from the existing Builder; recursive ZIP traversal, ZIP safety limits, deduplication, portable package export, packaged GUI title/version, and local build acceptance are in place; no private media or generated outputs are tracked

## Done So Far

- Built and verified the standalone v1 Windows app locally from the owner's source folder.
- Added a separate standalone entrypoint:
  - `handoff_light_app.py`
- Added a dedicated package surface:
  - `handoff_builder/handoff_light/`
- Implemented persistent local project storage:
  - `project.json`
  - `asset_registry.json`
  - `ingestion_history.json`
- Implemented recursive safe discovery for:
  - individual files
  - folders
  - ZIP archives
  - ZIP inside ZIP
  - same-name / different-content assets
  - duplicate-content skip by `size + SHA-256`
- Implemented portable immutable Handoff ZIP exports:
  - `V001_<project>_HANDOFF.zip`
  - `V002_<project>_HANDOFF.zip`
- Added build validation and no-absolute-path checks for the exported package.
- Added a separate packaged build flow:
  - `Handoff Light.spec`
  - `build_handoff_light_exe.bat`
- Completed packaged launch proof with visible window title:
  - `V0.1.0_Handoff_Light - Handoff Light`

## Current Focus

Publish the completed Issue `#29` standalone `Handoff Light` implementation on a dedicated Draft PR with exact local and packaged acceptance evidence.

## Next Practical Step

Push `feat/handoff-light-standalone`, open one separate Draft PR for Issue `#29`, and post the execution report to Issue `#29`. No merge is authorized.

## Key Decisions And Constraints

- For Issue `#29`, create a separate standalone `Handoff Light` executable and do not integrate it into the existing AI Handoff Builder GUI.
- The bundled FFmpeg / ffprobe renderer remains the default production renderer.
- Do not modify PR `#26`, Issue `#27`, or the existing Builder workflow while implementing `Handoff Light`.
- No remote scripts, fonts, media, iframes, arbitrary URLs, raw command strings, or `shell=True`.
- Do not modify originals on the owner machine.
- Personal media and generated outputs must not be committed to the public repository.
- GitHub is the execution source of truth for this project.
- No merge or Ready-for-Review transition without owner authorization.

## Read Next

- `PROJECT_STATE.md`
- `logs/latest.md`
- Issue `#29`: `https://github.com/oleg3479881328-code/AI-Handoff-Builder/issues/29`
- `HANDOFF_LIGHT_SPEC.md`
