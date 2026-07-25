# Current State

- Date: 2026-07-25
- Repository: `oleg3479881328-code/AI-Handoff-Builder`
- Broad v2 contract: `Yt-Dlp-Download-Manager` issue `#67`
- HyperFrames contract: repository issue `#3`
- Handoff completeness defect: repository issue `#2`
- Current branch: `feat/hyperframes-lab`
- Base branch: `codex/release-candidate-light-dark-ui`
- Draft PR: `#4` -> `codex/release-candidate-light-dark-ui`
- Current phase: HyperFrames trusted prototype validated locally on Windows, bounded Python adapter implemented, minimal in-app HyperFrames Lab surface validated, coordinator bridge and tabbed Voice Studio added, and draft PR `#4` open for final coordinator verification

## Accepted Baseline Preserved

- Existing standalone desktop app remains the only app surface:
  - Tkinter GUI
  - v1 Prepare Handoff ZIP builder
  - v2 Local Edit Runner
  - Voice Studio / Voicebox workflow
  - CLI
  - FFmpeg / ffprobe / ExifTool runtime
  - PyInstaller packaging
- Release-candidate baseline commit:
  - `56d927a3e93f1ee4b161cbcfe55f729fc2207091`
- Existing regression evidence:
  - `python -m pytest -q` -> `87 passed in 48.49s`
  - `python -m compileall handoff_builder app.py` -> success
  - portable build -> success on 2026-07-23
- Existing real end-to-end FFmpeg rerender proof remains intact.

## Owner Decision Added

HyperFrames will be evaluated **inside the existing AI Handoff Builder**, not as a second application.

The integration is bounded as follows:

- FFmpeg remains the default production renderer;
- HyperFrames is optional, local, and experimental;
- no cloud rendering;
- no arbitrary AI-authored HTML or JavaScript execution;
- only trusted repository-owned composition templates or allowlisted plan compilation;
- no personal assets or rendered outputs in GitHub;
- no merge to `main` without owner authorization.

## Work Completed In This Step

- Re-entered through Project Execution OS `START_HERE.md` and `docs/ROUTER.md`.
- Read the active project entrypoint, state, latest log, current release-candidate branch, renderer service, semantic validation, schema dispatch, and edit-plan schema.
- Confirmed the current edit-plan schema `1.0` supports only video assets and `video_segment` operations.
- Confirmed the current render service directly uses the safe FFmpeg compiler/backend and remains the production default.
- Checked the official HyperFrames repository and current official CLI/documentation as the selected existing donor.
- Validated the local Windows runtime with:
  - `node --version` -> `v24.13.0`
  - `npm --version` -> `11.6.2`
  - `hyperframes --version` -> `0.7.71`
  - `hyperframes doctor --json`
- Confirmed and copied the six private owner photographs into the ignored local prototype asset folder without modifying originals.
- Upgraded the checked-in prototype from legacy single-file `comp.html` assumptions to the current HyperFrames `0.7.x` project shape:
  - `prototypes/hyperframes/index.html`
  - `prototypes/hyperframes/meta.json`
  - `prototypes/hyperframes/hyperframes.json`
  - `prototypes/hyperframes/package.json`
- Kept `prototypes/hyperframes/comp.html` only as the original discovery draft, no longer a live root composition.
- Implemented a bounded HyperFrames adapter under:
  - `handoff_builder/v2/hyperframes_lab.py`
- Added focused safety/regression coverage:
  - `tests/test_v2_hyperframes_lab.py`
- Added a minimal themed `HyperFrames Lab` control surface inside the existing Tkinter application:
  - project-dir picker
  - doctor refresh
  - local preview launch
  - local MP4 render
  - cancel request
  - open output folder
- Updated:
  - `prototypes/hyperframes/README.md`
  - `app.py`

## Fresh Coordinator Bridge And Voice Studio Update From 2026-07-25

- Moved `Voice Studio` into the main application notebook as a first-class tab instead of a separate `Toplevel` window.
- Kept the `Open Voice Studio` action in `Local Edit Runner (v2)` but changed it to switch the operator into the embedded `Voice Studio` tab and trigger a fresh runtime/job refresh there.
- Added a bounded `Coordinator Bridge` block to `Local Edit Runner (v2)`:
  - paste coordinator brief / scenario layout
  - build a trusted local draft summary
  - push the extracted voice script directly into `Voice Studio`
  - save a local coordinator draft package into the active workspace
  - reopen the saved draft folder from the UI
- Added a new helper module:
  - `handoff_builder/v2/coordinator_bridge.py`
- The coordinator bridge currently supports:
  - structured JSON briefs
  - simple plain-text section briefs (`Title`, `Voice`, `Visual`, `Shots`, `Overlay`)
  - trusted payload export with:
    - `raw_html_allowed=false`
    - `remote_urls_allowed=false`
    - `render_target=local_windows_machine`
- Added focused regression coverage:
  - `tests/test_v2_coordinator_bridge.py`
- Validation for this step:
  - `python -m pytest -q tests/test_v2_coordinator_bridge.py` -> `3 passed in 0.13s`
  - `python -m py_compile app.py handoff_builder/v2/coordinator_bridge.py` -> success

## Trusted Prototype

The checked-in prototype is designed for:

- six private local photographs;
- 1080x1920;
- 30 FPS;
- 12 seconds;
- wide -> medium -> portrait -> close-up flow;
- deterministic seek-driven pan/zoom and cross-fades;
- no external scripts, fonts, media, or network dependencies.

The actual photographs are intentionally not committed.

Expected private source filenames:

- `20260722_172637.jpg`
- `20260722_172633.jpg`
- `20260722_172635.jpg`
- `20260722_172119.jpg`
- `20260722_172122.jpg`
- `20260722_172124.jpg`

## Current Health

- Existing application baseline: preserved
- HyperFrames architecture decision: implemented
- Repository prototype: validated against current HyperFrames CLI
- Local Windows HyperFrames runtime: checked and working
- Real owner-media HyperFrames MP4: rendered twice with identical SHA-256
- Python adapter: implemented with allowlisted path and HTML safety checks
- Tkinter HyperFrames Lab controls: implemented minimally inside the existing app
- FFmpeg renderer default: preserved
- Preview screenshot: satisfied with a loaded Studio capture showing the active project composition and timeline
- Draft PR state: open as draft into `codex/release-candidate-light-dark-ui`
- Voice Studio surface: now embedded as a notebook tab in the main desktop app
- Coordinator workflow gap: reduced by local brief -> draft -> voice-script bridge inside `Local Edit Runner (v2)`
- GitHub status checks: none configured for PR head `37dbaf1ae1a015e35fcfcd4b5eb9e9b956250424`; local regression evidence remains the validation source
- Private assets / generated outputs: still ignored and untracked

## Fresh HyperFrames Validation From 2026-07-25

- Official CLI/runtime:
  - `hyperframes --version` -> `0.7.71`
  - `hyperframes doctor --json`
    - required runtime checks passed for:
      - Version
      - Node.js
      - FFmpeg
      - FFprobe
      - Chrome after `hyperframes browser ensure`
    - optional checks still absent:
      - `whisper-cpp`
      - `TTS (Kokoro)`
      - `BGM (MusicGen)`
      - Docker running
- Trusted prototype validation:
  - `hyperframes lint . --json` -> `ok=true`, `0 error`, `0 warning`
  - `hyperframes inspect .` -> `0 layout issues across 9 sample(s)`
  - first render:
    - `prototypes/hyperframes/out/hyperframes_photo_demo.mp4`
    - size: `22269151` bytes
    - duration: `12.000000`
    - dimensions: `1080x1920`
    - frame rate: `30/1`
    - audio streams: `0`
    - SHA-256: `C4CF14908710486616C28B3674E1EB0465FBFD92F5DA9CE3D19718DC3A5EE45D`
  - second render:
    - `prototypes/hyperframes/out/hyperframes_photo_demo_second.mp4`
    - SHA-256: `C4CF14908710486616C28B3674E1EB0465FBFD92F5DA9CE3D19718DC3A5EE45D`
  - determinism result:
    - byte-identical output confirmed
- Preview runtime evidence:
  - `hyperframes preview . --background --no-open --force-new`
  - local server responded `200` at `http://localhost:3002`
  - active preview server listed on port `3002`
  - loaded Studio route confirmed in a real browser session:
    - `http://127.0.0.1:3002/#project/hyperframes?v=1&t=0&tab=renders&rc=1`
  - screenshot artifacts:
    - `prototypes/hyperframes/out/preview-studio.png`
    - `prototypes/hyperframes/out/preview-studio-loaded.png`
- In-app Tkinter validation:
  - instantiated the existing `App()` locally
  - confirmed the `Local Edit Runner (v2)` tab remains present
  - executed the new `HyperFrames Lab` actions through the real UI methods:
    - `Refresh Doctor`
    - `Render MP4`
  - UI returned:
    - `HyperFrames render completed: 1080x1920 | 12.0s | fps=30.0 | sha256=D18B2EBF2F1CDAA46C0B700D351EC69670E06005E1D4B39A0CCB98554018E1C7`
  - in-app render artifact:
    - `prototypes/hyperframes/out/hyperframes_lab_render.mp4`
- Final regression after the UI thread-safety fix:
  - `python -m pytest -q tests/test_v2_hyperframes_lab.py` -> `8 passed in 0.15s`
  - `python -m pytest -q` -> `95 passed in 28.69s`
  - `python -m compileall app.py` -> success
- Python regression and compile validation:
  - `python -m pytest -q tests/test_v2_hyperframes_lab.py` -> `8 passed`
  - `python -m pytest -q` -> `95 passed in 33.47s`
  - `python -m compileall handoff_builder app.py` -> success
- Live owner-facing Windows acceptance rerun on Saturday, July 25, 2026:
  - relaunched the existing app through `run_windows.bat`
  - confirmed the `Local Edit Runner (v2)` tab and `HyperFrames Lab` controls remain fully visible in both Light and Dark themes
  - confirmed `Refresh Doctor` succeeds from the real Tkinter window
  - identified and fixed a preview acceptance defect:
    - the adapter originally exposed only the bare Studio root URL
    - updated `handoff_builder/v2/hyperframes_lab.py` to return a project-aware deep-link while keeping the root URL as structured metadata
    - new expected route shape:
      - `http://localhost:3003/#project/hyperframes?v=1&t=0&tab=renders&rc=1`
  - expanded the focused preview test:
    - `tests/test_v2_hyperframes_lab.py`
  - reran validation after the preview routing fix:
    - `python -m pytest -q tests/test_v2_hyperframes_lab.py` -> `8 passed in 0.20s`
    - `python -m pytest -q` -> `95 passed in 39.73s`
  - browser proof from the live UI flow now shows:
    - loaded `hyperframes` project in `HyperFrames Studio`
    - six owner-photo thumbnails visible on the timeline
    - scrubbed playhead at `00:04 / 00:12` with updated preview frame
  - real UI render proof now shows:
    - `HyperFrames render completed: 1080x1920 | 12.0s | fps=30.0 | sha256=D18B2EBF2F1CDAA46C0B700D351EC69670E06005E1D4B39A0CCB98554018E1C7`
    - output file explorer window opened as `out - File Explorer`
    - `ffprobe` for `prototypes/hyperframes/out/hyperframes_lab_render.mp4`:
      - size: `22252596` bytes
      - duration: `12.000000`
      - dimensions: `1080x1920`
      - frame rate: `30/1`
      - audio streams: `0`
- Final coordinator code-review hardening on Saturday, July 25, 2026:
  - removed the owner-machine absolute path from `tests/test_v2_hyperframes_lab.py`
  - switched the `.gitignore` assertion to a repository-relative path derived from the test file location
  - tightened the trusted HyperFrames HTML/CSS safety boundary in `handoff_builder/v2/hyperframes_lab.py`
  - trusted compositions now reject any remote `http://` / `https://` reference, including:
    - remote image assets
    - remote video/audio assets
    - remote `<source>` media references
    - remote CSS `url(...)` references
  - expanded focused boundary tests accordingly
  - validation after the hardening pass:
    - `python -m pytest -q tests/test_v2_hyperframes_lab.py` -> `13 passed in 0.76s`
    - `python -m pytest -q` -> `100 passed in 32.73s`
    - `python -m compileall handoff_builder app.py` -> success

## Immediate Next Actions

1. Complete final coordinator verification on draft PR `#4`.
2. Wait for an explicit owner decision before marking the PR ready or merging.
3. Keep FFmpeg as default and expand HyperFrames only behind the same trusted-template boundary if a later phase is authorized.

## Constraints Still In Force

- Extend the existing standalone app only.
- Do not modify originals on the owner machine.
- Keep the safe FFmpeg renderer as default.
- Use explicit subprocess argument arrays only.
- No `shell=True`.
- No raw untrusted HTML/JavaScript execution.
- No cloud rendering for HyperFrames.
- No tracked private media or generated output.
- No merge to `main` or `codex/release-candidate-light-dark-ui`.
