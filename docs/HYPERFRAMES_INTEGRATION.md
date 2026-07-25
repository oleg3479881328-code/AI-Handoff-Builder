# HyperFrames integration decision

Date: 2026-07-24
Status: approved discovery and local prototype
Owner decision: integrate HyperFrames inside the existing `AI-Handoff-Builder`; do not create a second application.

## Purpose

Add an optional local HyperFrames authoring and rendering path for richer photo/video motion design while preserving the existing safe FFmpeg renderer as the production default.

The first target is a local 9:16 demonstration built from owner-provided photographs, with browser preview and MP4 output.

## Existing solution selected

Primary donor:

- HyperFrames official repository: `https://github.com/heygen-com/hyperframes`
- Official documentation: `https://hyperframes.video/docs`
- License: Apache-2.0

Confirmed donor capabilities:

- plain HTML compositions;
- local browser preview with play, scrub, and frame-step;
- deterministic MP4 rendering;
- Windows CLI support;
- bundled Chromium management;
- FFmpeg-based final encoding;
- machine-readable CLI commands suitable for an agent loop.

## Architecture decision

```text
AI Handoff Builder desktop app
        |
        +-- Prepare Handoff (existing)
        |
        +-- Local Edit Runner (existing)
        |       +-- FFmpeg renderer [default / production]
        |
        +-- HyperFrames Lab [optional / experimental]
                +-- trusted composition compiler
                +-- local preview server
                +-- local HyperFrames render
                +-- existing render workspace and QC report
```

HyperFrames is an internal optional renderer/authoring adapter. It is not a second application, a cloud service, or a replacement for the current FFmpeg path.

## Security boundary

The desktop app must not execute arbitrary HTML or JavaScript supplied by an AI package.

Allowed model:

```text
validated allowlisted scene plan
        -> trusted local compiler/template
        -> generated composition HTML
        -> HyperFrames preview/render
```

Forbidden:

- raw HTML/JavaScript imported from ChatGPT or another untrusted package;
- `eval`, dynamically downloaded scripts, remote fonts, remote media, `fetch`, iframes, or arbitrary network access;
- arbitrary command strings;
- `shell=True`;
- modification of source media;
- cloud rendering for this integration;
- automatic replacement of the existing FFmpeg renderer.

All subprocesses must use explicit argument arrays and local allowlisted paths.

## Initial prototype scope

The discovery prototype is intentionally bounded:

- local Windows execution;
- 1080x1920 output;
- approximately 10-15 seconds;
- six local photographs;
- four-shot sequence: wide -> medium push-in -> portrait -> close-up;
- deterministic pan/zoom and cross-fade motion;
- optional local audio only after the silent visual render succeeds;
- output MP4 and a small machine-readable validation report.

## Integration path

### Phase 0 - repository prototype

- keep the sample composition under `prototypes/hyperframes/`;
- use placeholder asset names only; do not commit personal photographs;
- verify official CLI installation and `hyperframes doctor` on the owner Windows machine;
- preview and render the sample locally.

### Phase 1 - local adapter

Add a bounded Python adapter that:

- discovers the HyperFrames executable;
- runs `doctor`, `preview`, `lint`, `inspect`, and `render` through explicit argument arrays;
- writes generated compositions inside the current workspace;
- captures stdout, stderr, exit code, versions, and output hash;
- supports cancellation and reports failures through the existing job/report model.

### Phase 2 - trusted plan compiler

Extend the edit-plan contract without breaking schema `1.0`:

- create a new schema version rather than changing `1.0` in place;
- support image assets and a minimal allowlist of visual operations;
- compile those operations into trusted local HTML/CSS/seek code;
- reject unknown operations and unsafe paths before HyperFrames starts.

Candidate first operations:

- `image_hold`;
- `ken_burns`;
- `crossfade`;
- `text_overlay`;
- `audio_track`.

### Phase 3 - owner-facing UI

Add a `HyperFrames Lab` surface inside the existing Tkinter application:

- choose local assets;
- select a trusted template;
- open local preview;
- render MP4;
- open output folder;
- show status, diagnostics, and QC results.

The UI must use the existing Light/Dark theme layer.

## Compatibility rules

- The FFmpeg renderer remains the default and must continue passing existing tests.
- HyperFrames failure must not break Prepare Handoff, Voice Studio, or the current Local Edit Runner.
- Personal photos, videos, voice samples, and generated MP4 files remain local and must not be committed to the public repository.
- The feature remains experimental until a real owner-media render, repeat render, QC report, and portable-app behavior are verified.

## Acceptance evidence required before review

- exact Node, npm, HyperFrames, Chromium, and FFmpeg versions;
- `hyperframes doctor` output;
- successful local preview screenshot;
- successful 1080x1920 MP4;
- output duration, dimensions, FPS, audio presence, SHA-256, and file size;
- repeat-render comparison;
- regression test results for the existing Python application;
- explicit list of what remains unbundled in the portable EXE.

## Sources

- `https://github.com/heygen-com/hyperframes`
- `https://hyperframes.video/docs/getting-started/install`
- `https://hyperframes.video/docs/getting-started/quickstart`
- `https://hyperframes.video/docs/workflow/preview`
- `https://hyperframes.video/docs/workflow/cli-reference`
