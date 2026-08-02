# Latest Log

Date: 2026-08-02
Step: Issue #28 master package + transcript workflow groundwork

## Completed

- Added the initial repository service layer for the Issue `#28` owner workflow:
  - `handoff_builder/v2/services/master_package_service.py`
  - `handoff_builder/v2/services/transcript_service.py`
- Added workflow-state persistence hooks to the existing local project metadata path:
  - `handoff_builder/v2/workspace.py`
- Added the transcript schema scaffold:
  - `schemas/master_audio_transcript/1.0.json`
- Updated repository-owned handoff templates so they now describe:
  - `MLT + MP3 + timeline map -> Gemini transcript import -> validated final ANALYSIS_HANDOFF`
  instead of claiming the older standalone edit-plan JSON path as the current final owner contract.

## Validation

- `python -m py_compile app.py handoff_builder\pipeline.py handoff_builder\models.py handoff_builder\v2\workspace.py handoff_builder\v2\project_registry.py handoff_builder\v2\services\master_package_service.py handoff_builder\v2\services\transcript_service.py handoff_builder\v2\services\__init__.py` -> success
- `python -m pytest -q tests\test_app_v2_ui.py tests\test_pipeline.py tests\test_v2_shotcut_service.py` -> `40 passed, 1 skipped in 25.28s`

Date: 2026-08-01
Step: Issue #27 owner-visible application version

## Completed

- Added the single version source:
  - `handoff_builder/version.py`
  - `APP_VERSION = V0.1.0`
- Connected the same source to:
  - PyInstaller bundle and EXE name: `V0.1.0_AI_Handoff_Builder.exe`
  - application window title: `AI Handoff Builder - V0.1.0`
  - stable visible header label: `Version: V0.1.0`
- Preserved the existing workspace-resolution correction and included it in the pending PR update.
- Captured packaged UI evidence in local-only `tmp_version_ui.png`.

## Validation

- `python -m pytest -q tests\\test_app_v2_ui.py tests\\test_packaged_resources.py` -> `8 passed, 1 skipped in 2.85s`
- `python -m py_compile app.py handoff_builder\\version.py handoff_builder\\__init__.py` -> success
- `cmd /c "echo.| build_exe.bat"` -> success; PyInstaller reported `Build complete!`
- launched packaged EXE and verified title: `AI Handoff Builder - V0.1.0`
- verified visible UI label: `Version: V0.1.0`
- packaged EXE SHA-256: `057A32663C38FB6D17CDDFAFDAAD84045D498F911BD3D631B4D4630FB064D19C`

## Status

- Draft PR #26: remains Draft and unmerged
- owner-visible version requirement: complete

Date: 2026-07-31
Step: Issue #27 direct JSON workspace recovers beside selected deep plan

## Completed

- Tightened direct `Edit Plan JSON` workspace resolution in:
  - `handoff_builder/v2/project_registry.py`
  - `handoff_builder/v2/services/import_service.py`
- Direct JSON import no longer accepts the loose `project_id`-only registry fallback.
- The import path now prefers:
  - exact saved handoff identity from the registry
  - then the folder containing the selected JSON itself
- If the selected JSON sits inside the real local handoff folder and that folder already has:
  - `analysis/handoff_index.json`
  but does not yet have a v2 workspace bootstrap,
  the app now initializes the workspace there automatically before importing.
- Added focused regression coverage in:
  - `tests/test_v2_one_json_workflow.py`
  proving:
  - stale same-`project_id` registry entries no longer steal the import
  - exact handoff registry matches still win when they exist

## Validation

- Focused regression:
  - `python -m pytest -q tests\test_v2_one_json_workflow.py tests\test_v2_gui_controller.py`
  - result: `13 passed in 8.22s`
- Compile validation:
  - `python -m py_compile handoff_builder\v2\project_registry.py handoff_builder\v2\services\import_service.py app.py`
  - result: success

Date: 2026-07-31
Step: Issue #27 self-describing handoff for first-try MLT

## Completed

- Added mandatory `ASSISTANT_CONTEXT.json` to every new analysis handoff package.
- `ASSISTANT_CONTEXT.json` now carries the owner-facing direct-MLT contract when local path context is enabled:
  - project identity
  - actual `project_root`
  - actual `originals_root`
  - actual `proxies_root`
  - `preferred_edit_source = originals`
  - complete `asset_id -> original filename -> original path` mapping
  - proxy mapping when available
  - direct-MLT path rules:
    - absolute original-media paths required
    - downloaded `.mlt` may be opened from any folder
    - no user file movement required
- Added persisted owner control in:
  - `handoff_builder/v2/shotcut_settings.py`
  - owner default remains enabled for this build
  - when disabled, direct MLT support is explicitly marked unavailable in `ASSISTANT_CONTEXT.json`
- Updated analysis handoff templates:
  - `handoff_builder/templates/analysis_handoff/00_START_HERE.md`
  - `handoff_builder/templates/analysis_handoff/PROJECT_BRIEF.md`
  - `handoff_builder/templates/analysis_handoff/OUTPUT_CONTRACT.md`
  - all now include:
    - `DIRECT SHOTCUT MLT MODE - NO USER FILE MOVEMENT`
- Added a new direct-MLT helper:
  - `handoff_builder/v2/direct_mlt.py`
  - builds a first-try Shotcut `.mlt` from `ASSISTANT_CONTEXT.json`
  - validates that:
    - every selected asset has a mapped original path
    - only original-media resources are used in direct mode
    - no physical filename contains literal `%20`
- Expanded regression coverage:
  - `tests/test_pipeline.py`
  - `tests/test_v2_shotcut_service.py`
  - `tests/test_v2_direct_mlt.py`
  - `tests/test_app_v2_ui.py`
- Updated packaged acceptance harness:
  - `scripts/run_issue27_packaged_acceptance.py`
  - it now proves:
    - packaged EXE creates the handoff
    - `ASSISTANT_CONTEXT.json` exists with full mapping
    - a direct `.mlt` can be created in an unrelated folder
    - Shotcut opens that `.mlt` without `Missing Files`

## Validation

- Focused source regression:
  - `python -m pytest -q tests\test_pipeline.py tests\test_v2_shotcut_service.py tests\test_v2_direct_mlt.py tests\test_app_v2_ui.py`
  - result: `42 passed, 1 skipped in 22.77s`
- Full suite:
  - `python -m pytest -q`
  - result: `166 passed in 85.24s`
- Compile validation:
  - `python -m py_compile app.py handoff_builder\pipeline.py handoff_builder\v2\shotcut_settings.py handoff_builder\v2\direct_mlt.py`
  - result: success
- Fresh packaged build from the active Issue `#27` worktree:
  - `cmd /c "echo.| build_exe.bat"`
  - result: success
  - EXE SHA-256:
    - `6365c90fef83ac7895fcfa5089766f1e14c5b1507e20bd468a04282ef94d7976`
- Packaged acceptance:
  - `python scripts\run_issue27_packaged_acceptance.py`
  - result:
    - handoff manifest includes `ASSISTANT_CONTEXT.json`
    - direct MLT path:
      - `C:\Users\oleg3\Documents\AIHB_issue27_packaged_acceptance_final\Unrelated Downloads\Каролина And RÖB direct owner test.mlt`
    - `opened_from_unrelated_folder = true`
    - `missing_files_dialog_absent = true`
    - `physical_filename_contains_percent20 = false`
    - direct MLT resource validation:
      - `uses_only_originals = true`
      - `missing_resources = []`

Date: 2026-07-30
Step: Issue #27 automatic complete local project hardening + packaged acceptance

## Completed

- Kept the single-source-ZIP owner workflow on the active `issue25` / PR `#26` branch and hardened the local project workspace contract so the selected ZIP now materializes project-owned:
  - `originals/`
  - `proxies/`
  - `analysis/`
  - `handoffs/`
  - `imports/`
  - root `<project_name>.mlt`
- Preserved stable local asset identity after extraction by extending the local registry with:
  - `original_project_path`
  - `proxy_project_path`
- Stopped workspace re-entry from wiping `source_snapshot.json`, so a reopened project no longer silently loses the original source ZIP identity used for collision protection.
- Fixed direct standalone JSON import to keep a project-root copy under:
  - `imports/<project_name>.json`
  and to resolve originals through project-relative registry paths even after moving the whole workspace folder.
- Fixed the packaged Shotcut path for frozen `.exe` runs:
  - the donor MCP server now launches with a real Python interpreter instead of recursively spawning `AI Handoff Builder.exe`
  - photo-only Shotcut clips now use still-image-safe duration/keyframe behavior for the editable `.mlt` build path
- Updated the packaged acceptance harness:
  - Unicode-safe report output
  - timeline-duration proof derived from the actual inspected Shotcut project
- Added/updated focused regression coverage:
  - `tests/test_pipeline.py`
  - `tests/test_utils.py`
  - `tests/test_v2_one_json_workflow.py`
  - `tests/test_v2_shotcut_backend.py`
  - `tests/test_v2_shotcut_service.py`
  - `tests/test_app_v2_ui.py`

## Validation

- Focused workflow regression:
  - `python -m pytest -q tests\test_utils.py tests\test_pipeline.py tests\test_v2_one_json_workflow.py tests\test_v2_shotcut_service.py tests\test_app_v2_ui.py`
  - result: `49 passed, 1 skipped in 13.26s`
- Full suite after the ZIP/workspace hardening:
  - `python -m pytest -q`
  - result: `160 passed in 46.00s`
- Focused packaged Shotcut follow-up after the frozen-recursion + still-image fixes:
  - `python -m pytest -q tests\test_v2_shotcut_backend.py tests\test_v2_shotcut_service.py tests\test_app_v2_ui.py tests\test_v2_one_json_workflow.py`
  - result: `34 passed, 1 skipped in 4.08s`
- Compile validation:
  - `python -m py_compile handoff_builder\v2\render\shotcut_backend.py handoff_builder\v2\services\shotcut_service.py app.py`
  - result: success
- Fresh packaged build from the active worktree:
  - `cmd /c "echo.| build_exe.bat"`
  - result: success
- Real packaged acceptance evidence:
  - harness:
    - `python scripts\run_issue27_packaged_acceptance.py`
  - evidence root:
    - `C:\Users\oleg3\Documents\AIHB_issue27_packaged_acceptance_final\evidence\`
  - final packaged status:
    - `shotcut_opened`
  - real opened project:
    - `C:\Users\oleg3\Documents\AIHB_issue27_packaged_acceptance_final\Каролина And RÖB\Каролина And RÖB.mlt`
  - opened Shotcut window title showed:
    - `Каролина And RÖB.mlt - 1080x1920 30.00fps 2ch - Shotcut`

Date: 2026-07-30
Step: Issue #27 packaged UI parity correction

## Completed

- Matched the current `issue25` packaged UI to the owner-expected v1 behavior by collapsing the `Настройки` block behind:
  - `Показать настройки`
- Added the same toggle flow directly in the active branch app instead of launching the older `v1` build as a substitute.
- Added focused UI regression coverage:
  - `tests/test_app_v2_ui.py`
  - verifies:
    - collapsed initial state
    - button text swap
    - expand/collapse manager transition
- Validation on Thursday, July 30, 2026:
  - `python -m py_compile app.py` -> success
  - `python -m pytest -q tests\test_app_v2_ui.py` -> `3 passed`
  - `cmd /c build_exe.bat` -> success
- Fresh packaged executable rebuilt from the active Issue `#27` worktree:
  - `dist\AI Handoff Builder\AI Handoff Builder.exe`

Date: 2026-07-30
Step: Issue #27 one-JSON Shotcut workflow correction

## Completed

- Replaced the active owner path with:
  - `<project_name>.zip -> <project_name>_ANALYSIS_HANDOFF.zip -> <project_name>.json -> <project_name>.mlt`
- Added repository-owned analysis handoff templates for the standalone Shotcut JSON contract:
  - `handoff_builder/templates/analysis_handoff/00_START_HERE.md`
  - `handoff_builder/templates/analysis_handoff/PROJECT_BRIEF.md`
  - `handoff_builder/templates/analysis_handoff/OUTPUT_CONTRACT.md`
- Added new schemas:
  - `schemas/analysis_handoff/1.0.json`
  - `schemas/edit_plan/3.0.json`
  - `schemas/normalized_timeline/1.0.json`
- Extended Prepare Handoff so the manifest now records:
  - `project_name`
  - `expected_output_filename`
  - `target_editor=shotcut`
  - semantic `content_hash`
- Added direct standalone JSON import and local identity verification through:
  - `handoff_builder/v2/services/import_service.py`
  - `handoff_builder/v2/project_registry.py`
  - `handoff_builder/v2/timeline/compiler.py`
- Extended Shotcut build path so `edit_plan 3.0` now compiles:
  - `direct JSON -> Normalized Timeline -> editable <project_name>.mlt`
- Updated the existing `Local Edit Runner (v2)` UI so the primary import action is:
  - `Import Edit Plan JSON`
- Added focused one-JSON regression coverage:
  - `tests/test_v2_one_json_workflow.py`
  - `tests/test_pipeline.py` owner naming/contract assertions
- Validation on Thursday, July 30, 2026:
  - `python -m pytest -q` -> `144 passed, 1 skipped in 48.56s`
  - `python -m py_compile app.py handoff_builder\pipeline.py handoff_builder\v2\services\import_service.py handoff_builder\v2\services\shotcut_service.py handoff_builder\v2\plans\semantic.py handoff_builder\v2\timeline\compiler.py` -> success
  - `cmd /c build_exe.bat` -> success
- Packaged build verification:
  - `dist\AI Handoff Builder\AI Handoff Builder.exe`
  - SHA-256: `01e930e8dad8f383295ee082b252a7141a27df2a151f8a28814cea00a2e51c36`
  - packaged templates and new schemas confirmed under `_internal`

Date: 2026-07-29
Step: Issue #27 owner-facing Shotcut MVP inside Local Edit Runner (v2)

## Completed

- Continued on the existing Issue `#25` worktree and branch instead of starting a parallel app or a fresh renderer path:
  - branch:
    - `experiment/shotcut-mcp-windows-proof`
  - base branch:
    - `feat/issue-16-preview-scroll-fix`
- Kept FFmpeg as the default backend and added a bounded owner-facing Shotcut choice inside the existing `Local Edit Runner (v2)` UI.
- Added a local persisted Shotcut settings layer:
  - `handoff_builder/v2/shotcut_settings.py`
  - stores:
    - runtime folder
    - donor `shotcut_mcp_server.py` path
  - persistence path:
    - `%LOCALAPPDATA%\\AI Handoff Builder\\shotcut_settings.json`
  - auto-detects the already-proven local proof runtime when present
- Added a new owner-facing orchestration layer:
  - `handoff_builder/v2/services/shotcut_service.py`
  - responsibilities:
    - describe local Shotcut runtime readiness
    - build editable `.mlt` projects from imported preview-plan `1.0` jobs
    - write reusable local artifacts under:
      - `workspace/renders/<job_id>/shotcut/`
    - open the generated project in the local Shotcut app
    - render the same job through the Shotcut MCP backend into:
      - `workspace/renders/<job_id>/reel.mp4`
- Extended the existing Tkinter app in `app.py` with a dedicated `Shotcut MCP` block inside `Local Edit Runner (v2)`:
  - backend selector:
    - `ffmpeg`
    - `shotcut`
  - runtime folder picker
  - MCP script picker
  - `Check Status`
  - `Reset Paths`
  - `Build Editable Project`
  - `Open Editable Project`
  - `Open in Shotcut`
- Integrated the Shotcut path into the existing render controls without replacing the queue model:
  - `Run Next Pending`
  - `Run Selected Job`
  - `Request Cancel`
  - `Retry Job`
- Preserved safe terminal-job behavior by allowing a completed FFmpeg source job to be re-built and re-rendered through Shotcut without forcing invalid queue transitions.
- Added focused coverage:
  - `tests/test_v2_shotcut_service.py`
  - `tests/test_app_v2_ui.py`
- Validation on Wednesday, July 29, 2026:
  - syntax:
    - `python -m py_compile app.py handoff_builder\\v2\\shotcut_settings.py handoff_builder\\v2\\services\\shotcut_service.py handoff_builder\\v2\\render\\shotcut_backend.py`
    - result: success
  - targeted regression:
    - `python -m pytest -q tests\\test_v2_shotcut_backend.py tests\\test_v2_shotcut_service.py tests\\test_app_v2_ui.py`
    - result: `20 passed in 3.09s`
  - full suite:
    - `python -m pytest -q`
    - result: `142 passed in 49.64s`
- Completed live service-path acceptance on the existing local acceptance set:
  - workspace:
    - `tmp_rc_real_e2e/workspace`
  - package:
    - `AI_EDIT_PACKAGE_REAL.zip`
  - selected job:
    - `f35260850bb76dead667`
  - Shotcut editable build:
    - `renderer_status=shotcut_editable_ready`
  - Shotcut render:
    - `renderer_status=completed`
    - output:
      - `540x960`
      - `30.0 fps`
      - `1.834 s`
      - `audio_present=1`
      - SHA-256:
        - `f0f94ee7b46e85ea1a3a9b95d6c899ea0c3f24676899c0a764f414fccdfcc234`
- Captured a local GUI proof image that shows the new `Shotcut MCP` section inside the live application window.

## Completed

- Re-entered through PEOS and re-read the active repository instructions plus Issue `#25` and the DeepSeek handoff.
- Preserved Issue `#20`, PR `#21`, Issue `#23`, and PR `#24` by working in an isolated Issue `#25` worktree:
  - branch:
    - `experiment/shotcut-mcp-windows-proof`
  - base SHA:
    - `67b74e9d512012829efb9c990a1055d3f43eb59b`
- Re-ran the clean worktree baseline:
  - `python -m pytest -q`
  - result:
    - `124 passed`
- Audited pinned donor `matrodrigs/shotcut-mcp`:
  - tag:
    - `v1.5.0`
  - full SHA:
    - `7e66c17b92c2058670ae5e4c21aa61e27c51d317`
  - decision:
    - `ACCEPT_FOR_ISOLATED_PROOF`
  - document:
    - `docs/shotcut-mcp-donor-audit.md`
- Verified the isolated official Shotcut Windows stack in the proof workspace:
  - Shotcut:
    - `26.6.25`
  - Melt:
    - `7.40.0`
  - bundled FFmpeg / FFprobe:
    - `n8.1.2`
- Completed the full Gate 4 cycle on one owner-selected real MP4 using all 15 required steps:
  - `shotcut_status`
  - `shotcut_doctor`
  - `probe_media`
  - `create_project`
  - `inspect_project`
  - `plan_project_edit`
  - `edit_project`
  - `validate_project`
  - `render_preview`
  - `render_contact_sheet`
  - `open_in_shotcut`
  - `start_render`
  - `render_status`
  - `probe_media` on the rendered MP4
  - final `inspect_project`
- Verified readback evidence from the real proof:
  - pre-edit project revision:
    - `0b9dbe445a750eea37c125dcadac627932a5d9cc3a03029219ea96650301e259`
  - post-edit project revision:
    - `012c5dc02e3d3164dd996e2f1d369b7d1335b883be729292c59d48bdc6001625`
  - rendered MP4:
    - non-zero
    - `h264` video stream present
    - `aac stereo` audio stream present
    - duration:
      - `2.986 s`
- Posted the sanitized GitHub checkpoint:
  - `LIVE PROOF CHECKPOINT`
  - status:
    - `REAL_SHOTCUT_MCP_PROOF_PASSED`
- Added a narrow code-level Shotcut backend boundary inside the repository:
  - `handoff_builder/v2/render/shotcut_backend.py`
  - `handoff_builder/v2/render/backends.py`
  - `handoff_builder/v2/render/__init__.py`
- Added focused adapter regression coverage:
  - `tests/test_v2_shotcut_backend.py`
  - `python -m pytest -q tests/test_v2_shotcut_backend.py`
  - result:
    - `14 passed in 2.16s`
- Added architecture/setup docs:
  - `docs/shotcut-mcp-donor-audit.md`
  - `docs/shotcut-backend-adapter.md`
- Tightened the adapter and final proof to materialize a separate `A1` audio track in the disposable Shotcut project:
  - `ShotcutTrackIntent`
  - explicit `tracks=[{kind=audio,name=A1}]`
  - linked real-media audio clips on `A1`
- Re-ran the full suite after the `A1` update:
  - `python -m pytest -q`
  - result:
    - `138 passed in 43.78s`
- Re-ran the real final-HEAD proof through `handoff_builder.v2.render.shotcut_backend` after the `A1` update:
  - repository HEAD during proof:
    - `5ba01f6241b921a43fc9116cac300e7754d7e7f1`
  - final proof project readback now shows:
    - `V1`
    - `A1`
    - `Titles`
  - rendered MP4 remained valid with:
    - `h264` video
    - `aac stereo` audio
  - local SHA-256 recorded outside GitHub for the final render:
    - `e7d77ac0edf70c2fcd1b02c483ec030b2642cc3f630fc5e6635b2769b32def9d`

## Errors And Resolutions

- `2026-07-28T20:06Z`
  - stage:
    - Gate 4 runner bootstrap
  - command/tool:
    - local proof runner using `probe_media`
  - sanitized error:
    - source frame rate came back as a numeric value instead of a fraction string
  - hypothesis:
    - the runner incorrectly assumed `avg_frame_rate` always contains `/`
  - attempted solution:
    - accept both numeric and fraction formats
  - result:
    - resolved

- `2026-07-28T20:07Z`
  - stage:
    - Gate 4 edit
  - command/tool:
    - `edit_project`
  - sanitized error:
    - JSON-RPC argument validation rejected `$.validate`
  - hypothesis:
    - the local runner copied an unsupported field from older assumptions instead of the published v1.5.0 schema
  - attempted solution:
    - remove `validate` and treat schema contracts as authoritative
  - result:
    - resolved

- `2026-07-28T20:08Z`
  - stage:
    - Gate 4 render bootstrap
  - command/tool:
    - detached donor render worker
  - sanitized error:
    - `ModuleNotFoundError: No module named 'shotcut_mcp'`
  - hypothesis:
    - the donor checkout script fixes `sys.path` only for the foreground server, not for the detached `python -m shotcut_mcp.render_worker` process
  - attempted solution:
    - inject donor-root `PYTHONPATH` from the caller boundary
  - result:
    - resolved and captured as a documented Windows limitation

- `2026-07-28T20:08Z`
  - stage:
    - Gate 4 render completion
  - command/tool:
    - `render_status`
  - sanitized error:
    - transient `failed` with status note `The render supervisor exited before finalizing the job.`
  - hypothesis:
    - Windows race between early status polling and durable job finalization
  - attempted solution:
    - re-read the durable job JSON/log metadata before accepting the terminal failure
  - result:
    - resolved for proof acceptance and codified into the adapter

- `2026-07-28T21:20Z`
  - stage:
    - Gate 6 donor tests
  - command/tool:
    - `python -m unittest -q tests.test_integration`
  - sanitized error:
    - direct donor integration tests failed with `melt was not found` in the raw-clone module-import path
  - hypothesis:
    - the donor integration suite exercises module-level executable discovery differently from the stdio proof path and does not inherit the same detached-worker/runtime wrapper guarantees
  - attempted solution:
    - re-run repository acceptance through the actual stdio server and then through the new AI Handoff Builder adapter boundary
  - result:
    - unresolved inside the raw donor test path; documented as a remaining donor limitation, while the real stdio proof and final repository adapter proof both passed

## Remaining Work In This Run

- publish the final GitHub execution report
- create the final incremental commit for the explicit `A1` track update
- push the updated branch head into the existing Draft PR

## Completed

- Confirmed the official current local runtime:
  - `node --version` -> `v24.13.0`
  - `npm --version` -> `11.6.2`
  - `hyperframes --version` -> `0.7.71`
- Installed the official HyperFrames CLI globally and completed browser provisioning with:
  - `npm install -g hyperframes`
  - `hyperframes browser ensure`
- Ran `hyperframes doctor --json` and confirmed the required local render path works after browser provisioning:
  - Version OK
  - Node.js OK
  - FFmpeg OK
  - FFprobe OK
  - Chrome OK
- Located the six private owner JPEGs on this Windows machine and copied them into:
  - `prototypes/hyperframes/assets/`
  - originals were not modified or moved
- Detected and fixed real compatibility drift between the issue assumptions and current HyperFrames `0.7.71`:
  - current CLI expects a project directory, not direct `comp.html` entry
  - current project shape uses:
    - `index.html`
    - `meta.json`
    - `hyperframes.json`
    - `package.json`
  - `inspect` is deprecated but still usable; current CLI points toward `check`
- Converted the trusted prototype into the current CLI-compatible project format while preserving the same 9:16 visual intent.
- Fixed all live lint/runtime issues reported by the current CLI:
  - added `class="clip"` to timed elements
  - assigned overlapping cross-fade shots to separate tracks
  - removed duplicate live root-composition discovery from legacy `comp.html`
  - marked the intended text overlap explicitly
- Validated the trusted prototype on real local owner media:
  - `hyperframes lint . --json` -> clean
  - `hyperframes inspect .` -> clean
  - `hyperframes render . -o out/hyperframes_photo_demo.mp4`
  - `hyperframes render . -o out/hyperframes_photo_demo_second.mp4`
- Confirmed deterministic output:
  - first SHA-256: `C4CF14908710486616C28B3674E1EB0465FBFD92F5DA9CE3D19718DC3A5EE45D`
  - second SHA-256: `C4CF14908710486616C28B3674E1EB0465FBFD92F5DA9CE3D19718DC3A5EE45D`
- Probed the produced MP4:
  - `1080x1920`
  - `30 FPS`
  - `12.000000 s`
  - `22269151` bytes
  - video-only, no audio stream
- Started local preview successfully:
  - `hyperframes preview . --background --no-open --force-new`
  - active server on `http://localhost:3002`
  - endpoint returned `200`
- Captured preview evidence artifacts:
  - `prototypes/hyperframes/out/preview-studio.png`
  - `prototypes/hyperframes/out/preview-studio-loaded.png`
- Confirmed the loaded Studio project route in a real browser session:
  - `http://127.0.0.1:3002/#project/hyperframes?v=1&t=0&tab=renders&rc=1`
- Implemented the bounded Python adapter:
  - `handoff_builder/v2/hyperframes_lab.py`
  - safety boundary:
    - only trusted prototype root or active workspace paths
    - explicit argument arrays only
    - no `shell=True`
    - no remote scripts/iframes/fetch/network patterns in trusted HTML
    - structured success/failure metadata
- Added the minimal themed in-app `HyperFrames Lab` surface inside `app.py`:
  - choose trusted project dir
  - refresh doctor
  - open local preview
  - render MP4
  - cancel request
  - open output folder
- Fixed the real UI-thread bug discovered during owner-facing validation:
  - background HyperFrames worker no longer reads `tk.StringVar` values off the Tk main thread
- Validated the owner-facing Tkinter flow directly from the real `App()` object:
  - `Refresh Doctor` succeeded
  - `Render MP4` succeeded
  - output artifact:
    - `prototypes/hyperframes/out/hyperframes_lab_render.mp4`
  - output SHA-256:
    - `D18B2EBF2F1CDAA46C0B700D351EC69670E06005E1D4B39A0CCB98554018E1C7`
- Added focused tests:
  - `tests/test_v2_hyperframes_lab.py`
- Revalidated the repository:
  - `python -m pytest -q tests/test_v2_hyperframes_lab.py` -> `8 passed in 0.15s`
  - `python -m pytest -q` -> `95 passed in 28.69s`
  - `python -m compileall handoff_builder app.py` -> success
- Completed the coordinator-requested live Windows acceptance pass on `feat/hyperframes-lab`:
  - launched the app again through `run_windows.bat`
  - opened `Local Edit Runner (v2)` and confirmed `HyperFrames Lab` controls remain fully visible in both Light and Dark themes
  - reproduced a real preview acceptance gap:
    - UI `Open Preview` surfaced only the bare Studio root URL
    - a fresh browser window at the root URL did not auto-load the trusted local project
  - fixed the preview routing gap in `handoff_builder/v2/hyperframes_lab.py`:
    - adapter now returns a project-aware Studio deep-link:
      - `http://localhost:3003/#project/hyperframes?v=1&t=0&tab=renders&rc=1`
    - preserved the original root Studio URL separately as structured metadata
  - added/updated focused proof:
    - `tests/test_v2_hyperframes_lab.py`
    - `python -m pytest -q tests/test_v2_hyperframes_lab.py` -> `8 passed in 0.20s`
    - `python -m pytest -q` -> `95 passed in 39.73s`
  - reran the real UI flow after the fix:
    - `Refresh Doctor` succeeded
    - `Open Preview` exposed the project-aware deep-link in the app status line
    - dedicated browser capture showed the loaded `hyperframes` project with six owner-photo thumbnails visible on the timeline
    - browser scrub capture showed the playhead advanced to `00:04 / 00:12` with the preview frame updated
    - `Render MP4` completed from the real Tkinter app
    - `Open Output Folder` opened `out - File Explorer`
  - captured real UI render result:
    - output: `prototypes/hyperframes/out/hyperframes_lab_render.mp4`
    - `ffprobe`: `1080x1920`, `30 FPS`, `12.000000 s`, `22252596` bytes, video-only
    - SHA-256: `D18B2EBF2F1CDAA46C0B700D351EC69670E06005E1D4B39A0CCB98554018E1C7`
- Addressed the final coordinator code-review blockers on Saturday, July 25, 2026:
  - removed the owner-machine absolute test path from `tests/test_v2_hyperframes_lab.py`
  - switched the `.gitignore` assertion to a repository-relative path derived from the test file
  - hardened the trusted HyperFrames HTML/CSS boundary in `handoff_builder/v2/hyperframes_lab.py`
  - the validator now rejects any remote `http://` / `https://` reference inside trusted composition HTML/CSS, including remote:
    - images
    - video/audio media
    - `<source>` tags
    - CSS `url(...)` references
  - expanded the focused test matrix for remote script, iframe, fetch, image, video, audio, source, and CSS URL cases
  - validation after the hardening pass:
    - `python -m pytest -q tests/test_v2_hyperframes_lab.py` -> `13 passed in 0.76s`
    - `python -m pytest -q` -> `100 passed in 32.73s`
    - `python -m compileall handoff_builder app.py` -> success
    - `git diff --check` -> warnings only for LF/CRLF conversion, no content errors

## Acceptance Status

- Local HyperFrames runtime: satisfied
- `doctor` evidence: satisfied
- browser preview opened locally: satisfied
- preview screenshot captured: satisfied
- project-aware preview deep-link from the real UI: satisfied
- loaded Studio composition with six owner-photo timeline thumbnails: satisfied
- timeline scrubbing in the real browser window: satisfied
- `Open Output Folder` local-only path behavior: satisfied
- real 1080x1920 MP4 from the six owner photos: satisfied
- repeat render comparison: satisfied
- bounded Python adapter: satisfied
- minimal themed Tkinter surface: satisfied
- `shell=True` avoided: satisfied
- FFmpeg default preserved: satisfied
- full Python regression suite: satisfied
- remote media/CSS URL rejection in trusted compositions: satisfied
- state files updated: satisfied
- draft PR `#4` into `codex/release-candidate-light-dark-ui`: open and documented
- GitHub CI/status checks on current PR head: none configured; local regression evidence remains the validation source

## Security Boundary Still In Force

- FFmpeg remains the production default renderer.
- HyperFrames stays optional and local.
- No cloud rendering.
- No raw command strings.
- No `shell=True`.
- No raw AI-authored HTML/JavaScript execution.
- No remote scripts, fonts, media, iframes, or arbitrary URLs in trusted compositions.
- No modification of owner originals.
- No tracked personal media or generated MP4 files.
- No merge to `main`.

## Next

- Final coordinator verification on draft PR `#4`.
- Wait for an explicit owner decision before marking ready or merging.
- Do not merge to `main` or `codex/release-candidate-light-dark-ui`.

## Update: Coordinator Bridge + Tabbed Voice Studio

- Reworked the desktop UI so `Voice Studio` now opens inside the main application notebook as its own tab instead of spawning a second top-level window.
- Preserved the existing `Open Voice Studio` button in `Local Edit Runner (v2)`, but redirected it to:
  - switch to the embedded `Voice Studio` tab
  - trigger a fresh runtime/job refresh in the tabbed surface
- Added a new in-app `Coordinator Bridge` block inside `Local Edit Runner (v2)` for the missing coordinator workflow handoff step:
  - paste a coordinator brief / scenario outline
  - build a trusted local draft summary
  - send the extracted voice script into `Voice Studio`
  - save the draft package into the active local workspace
  - open the saved draft folder directly from the UI
- Added `handoff_builder/v2/coordinator_bridge.py` to normalize:
  - JSON coordinator briefs
  - simple plain-text briefs with `Title`, `Voice`, `Visual`, `Shots`, and `Overlay` sections
- The exported coordinator payload now stays explicitly local/trusted:
  - `raw_html_allowed=false`
  - `remote_urls_allowed=false`
  - `render_target=local_windows_machine`
- Added focused regression coverage:
  - `tests/test_v2_coordinator_bridge.py`
- Validation for this UI/workflow step:
  - `python -m pytest -q tests/test_v2_coordinator_bridge.py` -> `3 passed in 0.13s`
  - `python -m py_compile app.py handoff_builder/v2/coordinator_bridge.py` -> success

## Update: Issue #6 AI Edit Package 2.0 bridge

- Created and switched to the dedicated issue branch:
  - `feat/issue-6-ai-edit-package-2`
  - base SHA: `de459744d4682a14290bb6d4ca7838cfc6475423`
- Extended Prepare Handoff local registry output with:
  - `media_type`
  - `size_bytes`
  - `sha256`
  - `capture_time`
  - `analysis_preview_paths`
- Added schemas:
  - `schemas/ai_edit_package/2.0.json`
  - `schemas/edit_plan/2.0.json`
- Added workspace asset-bridge helpers:
  - `handoff_builder/v2/assets/local_registry.py`
- Added import-time active registry bootstrap and validation:
  - `workspace/analysis/local_asset_registry.json`
  - sibling `local_asset_registry.json` fallback next to `AI_EDIT_PACKAGE.zip`
  - hard failure on:
    - missing asset
    - ambiguous asset
    - checksum mismatch
    - unreadable source
- Added plan-only package protection for `AI_EDIT_PACKAGE 2.0`:
  - no media payloads allowed in the ZIP
- Added a safe local photo compiler path for the first vertical slice:
  - `image_hold`
  - `text_overlay`
  - local staged frames
  - FFmpeg render with no audio
- Added parameterized QC so the runner can validate:
  - legacy `720x1280` preview outputs
  - new `1080x1920` photo-plan outputs
- Added focused regression coverage:
  - `tests/test_v2_ai_edit_package_2.py`
- Validation:
  - `python -m pytest -q tests/test_v2_ai_edit_package_2.py` -> `6 passed`
  - `python -m pytest -q tests/test_pipeline.py tests/test_v2_vertical_slice.py tests/test_v2_preview_worker.py tests/test_v2_ai_edit_package_2.py` -> passed
  - `python -m pytest -q` -> `109 passed in 29.30s`
  - `python -m compileall handoff_builder app.py` -> success
  - `git diff --check` -> line-ending warnings only, no content errors
- Real acceptance run completed on Saturday, July 25, 2026:
  - local source registry:
    - `C:\\Users\\oleg3\\Desktop\\WEDDING_PROJECT_20260724_093205\\local_asset_registry.json`
  - selected real photo asset count:
    - `10`
  - lightweight package:
    - `tmp_issue6_acceptance/AI_EDIT_PACKAGE.zip`
    - entries:
      - `ai_edit_package.json`
      - `plans/plan-photos-issue6-10.json`
  - local render output:
    - `tmp_issue6_acceptance/workspace/renders/78d6ca7e6b67f69b1818/reel.mp4`
    - `1080x1920`
    - `10.0s`
    - `30fps`
    - `audio_present=0`
    - SHA-256: `0515025A8C677B72A99830DEC555CF38C74C6EFEC2D8B727EBCFD9911079205B`
  - asset resolution evidence:
    - `tmp_issue6_acceptance/workspace/renders/78d6ca7e6b67f69b1818/asset_resolution.json`
    - `resolved_asset_count=10`

## Update: Issue #8 packaged release-candidate acceptance

- Synced to the accepted release-candidate baseline:
  - branch: `codex/release-candidate-light-dark-ui`
  - exact HEAD: `bd3867280c19b252489011c3c3b589c05c87c061`
- Verified source health before packaging work:
  - `python -m pytest -q` -> `109 passed` on the accepted baseline
  - `python -m compileall handoff_builder app.py` -> success
  - `git diff --check` -> clean
- Confirmed the real packaged defect that blocks Issue #8 acceptance:
  - current frozen app shipped `prototypes/hyperframes/`
  - current frozen app missed `_internal/schemas/`
  - packaged `AI_EDIT_PACKAGE 2.0` import could not rely on the repository schema loader path without this fix
- Implemented the dedicated packaging-only fix on branch:
  - `feat/issue-8-packaged-schema-fix`
  - changes:
    - `AI Handoff Builder.spec`
    - `build_exe.bat`
    - `tests/test_packaged_resources.py`
- Post-fix validation:
  - `python -m pytest -q tests/test_packaged_resources.py tests/test_v2_ai_edit_package_2.py -q` -> passed
  - `python -m pytest -q` -> `111 passed in 30.35s`
  - `python -m compileall handoff_builder app.py` -> success
  - `git diff --check` -> line-ending warning only for `build_exe.bat`
- Rebuilt the portable packaged app:
  - command:
    - `cmd /c build_exe.bat`
  - artifact:
    - `dist/AI Handoff Builder/AI Handoff Builder.exe`
  - last write UTC:
    - `2026-07-25T19:47:29Z`
  - size:
    - `6233403` bytes
  - SHA-256:
    - `3737F885698D1F71AA9196474676B307E02AF66666D9CC6DA9B2BCCB298E2F97`
- Confirmed packaged resources after rebuild:
  - `_internal/prototypes/hyperframes/`
  - `_internal/schemas/ai_edit_package/1.0.json`
  - `_internal/schemas/ai_edit_package/2.0.json`
  - `_internal/schemas/edit_plan/1.0.json`
  - `_internal/schemas/edit_plan/2.0.json`
  - `_internal/schemas/edit_patch/1.0.json`
  - `_internal/schemas/render_report/1.0.json`
  - `_internal/schemas/voiceover_spec/1.0.json`
- Packaged GUI evidence gathered:
  - startup screenshot:
    - `tmp_issue8_startup.png`
  - `Local Edit Runner (v2)` packaged tab screenshot:
    - `tmp_issue8_v2tab.png`
  - packaged workspace-open proof:
    - `tmp_issue8_open_workspace_probe/after-open.png`
  - UI status in the packaged app:
    - `Workspace готов.`
- Remaining blocker:
  - the standard Windows `Выберите AI_EDIT_PACKAGE.zip` picker still needs one final working unattended confirmation path
  - automation now reliably:
    - opens the packaged dialog
    - populates the `File name` field with the real `AI_EDIT_PACKAGE.zip` path
  - but the automated confirm step has not yet produced imported workspace markers
  - therefore the packaging/resource defect is fixed and proven, while the last packaged import/render acceptance step remains open

## Update: Issue #10 handoff-derived package bridge

- Created and switched to the dedicated branch:
  - `feat/issue-10-handoff-derived-package`
- Preserved `2.0` unchanged and added:
  - `schemas/ai_edit_package/2.1.json`
  - `schemas/edit_plan/2.1.json`
- Updated the runtime so `2.1` photo packages:
  - accept only handoff-available asset fields from ChatGPT
  - resolve originals strictly from the active workspace registry
  - hard-fail on missing, ambiguous, unreadable, size-mismatched, or checksum-mismatched originals
  - never fall back to a sidecar registry for `2.1`
- Updated:
  - `handoff_builder/v2/assets/local_registry.py`
  - `handoff_builder/v2/packages/importer.py`
  - `handoff_builder/v2/plans/schema.py`
  - `handoff_builder/v2/plans/semantic.py`
  - `handoff_builder/v2/render/compiler.py`
  - `handoff_builder/v2/services/import_service.py`
  - `handoff_builder/v2/services/render_service.py`
  - `tests/test_v2_ai_edit_package_2.py`
  - `tests/test_v2_architecture.py`
- Validation after the code changes:
  - `python -m pytest -q tests/test_v2_architecture.py tests/test_v2_ai_edit_package_2.py` -> `21 passed in 6.79s`
  - `python -m pytest -q` -> `116 passed in 40.82s`
  - `python -m compileall handoff_builder app.py` -> success
- Confirmed the uploaded handoff input:
  - `C:\Users\oleg3\Desktop\WEDDING_PROJECT_ANALYSIS_HANDOFF.zip`
- Generated a valid handoff-derived plan-only package from handoff contents only:
  - `tmp_issue10_acceptance_tuned/AI_EDIT_PACKAGE.zip`
  - entries:
    - `ai_edit_package.json`
    - `plans/plan-wedding-8.json`
  - package checks:
    - no media payloads
    - no local `source_path`
    - no local registry file
    - no registry-reference words
- Source acceptance on the matching `WEDDING_PROJECT` workspace:
  - workspace:
    - `tmp_issue10_acceptance_tuned/workspace`
  - completed render:
    - `tmp_issue10_acceptance_tuned/workspace/renders/4b29d9e5e82e7d559313/reel.mp4`
    - SHA-256: `60c1e8c84dd905a04f74de66a6eb1f3320e784ce57a6ef8554d579fa90e99592`
    - `1080x1920`
    - `30.0 fps`
    - `7.766667 s`
    - `audio_present=0`
  - asset resolution:
    - `tmp_issue10_acceptance_tuned/workspace/renders/4b29d9e5e82e7d559313/asset_resolution.json`
    - `resolved_asset_count=8`
- Rebuilt the packaged app after the `2.1` changes:
  - command:
    - `cmd /c build_exe.bat`
  - artifact:
    - `dist/AI Handoff Builder/AI Handoff Builder.exe`
  - last write UTC:
    - `2026-07-26T00:17:02Z`
  - size:
    - `6233896` bytes
  - SHA-256:
    - `DFC1E0647A33C3740B4F1F59D3BB7C0CAE41E766C9AAFB838C7C09C39CCBCCBB`
  - packaged schema resources confirmed present:
    - `_internal/schemas/ai_edit_package/2.1.json`
    - `_internal/schemas/edit_plan/2.1.json`
- Packaged GUI acceptance sequence:
  - packaged UI first proved a correct safety failure on the wrong workspace:
    - screenshot:
      - `tmp_issue10_packaged_evidence/11-after-import-third-pass.png`
    - error:
      - `Package project mismatch: WEDDING_PROJECT != proj-photos-issue6`
  - created a second handoff-derived acceptance ZIP with the same 8-photo contract and a distinct `plan_id`:
    - `tmp_issue10_acceptance_tuned/AI_EDIT_PACKAGE_packaged.zip`
    - `plan_id=plan-wedding-8-packaged`
  - opened the matching existing `WEDDING_PROJECT` workspace in the packaged app:
    - screenshot:
      - `tmp_issue10_packaged_evidence/13-matching-workspace-opened.png`
  - imported the new `2.1` package in the packaged app:
    - screenshot:
      - `tmp_issue10_packaged_evidence/14-after-successful-import.png`
    - workspace rows now include:
      - `package_id=59f161063888f781`
      - `edit_plan_id=plan-wedding-8-packaged`
      - `render_job_id=8bc66f8c13d8c14ae583`
  - completed the packaged render:
    - screenshot:
      - `tmp_issue10_packaged_evidence/16-final-packaged-ui.png`
    - render row:
      - `status=completed`
      - `started_at=2026-07-26T00:29:07Z`
      - `finished_at=2026-07-26T00:29:13Z`
    - output:
      - `tmp_issue10_acceptance_tuned/workspace/renders/8bc66f8c13d8c14ae583/reel.mp4`
      - SHA-256: `60c1e8c84dd905a04f74de66a6eb1f3320e784ce57a6ef8554d579fa90e99592`
      - `1080x1920`
      - `30.0 fps`
      - `7.766667 s`
      - `audio_present=0`
    - asset resolution:
      - `tmp_issue10_acceptance_tuned/workspace/renders/8bc66f8c13d8c14ae583/asset_resolution.json`
      - `resolved_asset_count=8`

## Update: Issue #16 Local Edit Runner scroll + current Preview target

- Created and switched to the dedicated branch:
  - `feat/issue-16-preview-scroll-fix`
- Reproduced the two blocking owner-reported defects from Issue `#16`:
  - the lower `Local Edit Runner (v2)` surface could be pushed below the window by large inline JSON with no vertical scroll path
  - `Open Preview` still used stale global HyperFrames project state instead of the current imported plan identity
- Fixed the v2 tab layout in `app.py`:
  - wrapped the full content area in a vertically scrollable canvas with a real scrollbar
  - bound mouse wheel / touchpad scrolling onto the active v2 shell
  - preserved themed sizing while keeping Jobs, Results, and HyperFrames controls reachable at smaller window heights
  - auto-focused the latest render job/results into view after snapshot updates so `Run Next Pending` no longer leaves the operator searching below hidden content
  - moved verbose JSON out of the main path into a collapsible diagnostics block hidden by default
- Fixed preview identity routing:
  - added active preview-plan tracking inside the app state
  - latest imported plan becomes the preview target by default unless the operator explicitly selects another plan
  - blocked silent fallback to a previous global project when the current plan is not previewable
- Added a new trusted local preview builder:
  - `handoff_builder/v2/hyperframes_preview.py`
  - emits workspace-local HyperFrames preview projects keyed by current plan identity
  - copies only resolved local assets for the active plan into the generated preview project
  - writes trusted preview metadata files:
    - `preview_identity.json`
    - `preview_segments.json`
- Added focused regression tests:
  - `tests/test_v2_hyperframes_preview.py`
    - `Marusia -> Samarkand -> restart -> explicit switch`
    - no old overlay/state leakage into the rebuilt preview
  - `tests/test_app_v2_ui.py`
    - scroll shell presence
    - diagnostics collapse behavior
    - auto-focus to latest job/results
- Validation:
  - `python -m py_compile app.py handoff_builder\\v2\\hyperframes_preview.py` -> success
  - `python -m pytest -q tests/test_v2_hyperframes_preview.py` -> `3 passed in 1.22s`
  - `python -m pytest -q tests/test_v2_hyperframes_preview.py tests/test_app_v2_ui.py` -> `5 passed in 1.82s`
  - `python -m pytest -q tests/test_v2_ai_edit_package_2.py tests/test_v2_gui_controller.py tests/test_v2_hyperframes_lab.py tests/test_v2_hyperframes_preview.py tests/test_app_v2_ui.py` -> `31 passed, 1 skipped in 10.49s`
  - `python -m pytest -q` -> `124 passed in 42.33s`
  - `python -m compileall handoff_builder app.py` -> success

## Acceptance Status

- v2 full-height scrolling path: satisfied in source
- Jobs accessibility at smaller window heights: satisfied in source
- visible post-run job/result focus: satisfied in source
- current-plan Preview identity binding: satisfied in source
- stale Marusia fallback after Samarkand import: prevented in source
- restart-like current Preview selection behavior: satisfied in source
- focused regression tests for both defects: satisfied
- full Python regression suite: satisfied
- packaged `.exe` rebuild and GitHub publication: pending in this run

## Update: Issue #14 auto project-root workflow

- Created and switched to the dedicated branch:
  - `feat/issue-14-auto-project-root`
- Reworked the normal owner flow so a single selected source ZIP now defines:
  - `project_root = parent(selected_source_zip)`
  - `project_id = basename(project_root)`
- Moved the project-local handoff/runtime surface into compact subfolders under that project root:
  - `handoffs/`
  - `incoming_ai_packages/`
  - `ai_packages/`
  - `analysis/`
  - `renders/`
  - `logs/`
  - existing `cache/`, `patches/`, `voice/`, and related runtime folders remain intact
- Changed Prepare Handoff owner flow behavior:
  - initializes/reopens the project-root workspace automatically
  - writes `ANALYSIS_HANDOFF.zip` into `project_root/handoffs/`
  - writes the active local asset registry into `project_root/analysis/local_asset_registry.json`
  - records local handoff identity into `project_root/analysis/handoff_index.json`
  - records durable app-level identity mapping into:
    - `%LOCALAPPDATA%\\AI Handoff Builder\\project_registry.json`
  - avoids silent overwrite of an existing outgoing handoff ZIP by allocating a new unique filename instead
- Changed Local Edit Runner import behavior:
  - `AI_EDIT_PACKAGE.zip` no longer requires a manually opened workspace on the normal path
  - import now reads package identity first:
    - `project_id`
    - `handoff_id`
    - `handoff_sha256`
  - if a saved mapping exists, import auto-opens the correct project root and continues
  - if the saved mapping is missing, the UI now asks once for:
    - original project folder
    - or original source ZIP
  - fallback is verified against the local handoff identity before the new mapping is saved
- Kept portable-package safety/compatibility intact:
  - schema `2.0` unchanged
  - Issue `#10` schema `2.1` workflow unchanged
  - no original-file local paths added into portable AI-facing ZIP payloads
  - no original media modified, moved, or deleted
- Added regression coverage:
  - `tests/test_pipeline.py`
    - `test_owner_flow_single_source_zip_uses_project_root_workspace`
  - `tests/test_v2_gui_controller.py`
    - `test_gui_controller_import_resolves_saved_project_mapping_without_manual_open`
    - `test_gui_controller_import_can_restore_link_from_project_folder_fallback`
- Validation on Sunday, July 26, 2026:
  - targeted new tests:
    - `python -m pytest -q tests/test_pipeline.py::test_owner_flow_single_source_zip_uses_project_root_workspace tests/test_v2_gui_controller.py::test_gui_controller_import_resolves_saved_project_mapping_without_manual_open tests/test_v2_gui_controller.py::test_gui_controller_import_can_restore_link_from_project_folder_fallback`
    - result: `3 passed in 4.39s`
  - affected-surface regression:
    - `python -m pytest -q tests/test_pipeline.py tests/test_v2_ai_edit_package_2.py tests/test_v2_gui_controller.py`
    - result: `38 passed in 16.69s`
  - full suite:
    - `python -m pytest -q`
    - result: `119 passed in 39.32s`
  - compile validation:
    - `python -m py_compile app.py handoff_builder\\pipeline.py handoff_builder\\v2\\gui_controller.py handoff_builder\\v2\\services\\import_service.py handoff_builder\\v2\\project_registry.py` -> success
    - `python -m compileall handoff_builder app.py` -> success
