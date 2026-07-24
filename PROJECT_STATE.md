# Current State

- Date: 2026-07-23
- Repository: `oleg3479881328-code/AI-Handoff-Builder`
- Active contract: `Yt-Dlp-Download-Manager` issue `#67`
- Current branch: `codex/real-package-hardening-v1`
- Current phase: Real Package Hardening v1 implemented locally from the accepted RC baseline; duplicate behavior and chronology reliability proof added, while the full `51 asset / 17 photo` rebuild remains blocked by source availability

## What Exists Now

- The existing standalone desktop app remains the only app surface:
  - Tkinter GUI
  - v1 Prepare Handoff ZIP builder
  - v2 Local Edit Runner
  - Voice Studio / Voicebox workflow
  - CLI
  - FFmpeg / ffprobe / ExifTool runtime
  - PyInstaller packaging
- The release-candidate branch now adds a centralized Light/Dark theme layer with:
  - semantic design tokens in `handoff_builder/theme.py`
  - persistent theme selection storage between launches
  - live theme switching without restart
  - themed dialogs, summary window, Local Edit Runner, and Voice Studio
  - themed text/list widgets and focus styling
- The new hardening branch additionally changes the v1 handoff pipeline so that:
  - WhatsApp filenames with `AM/PM` now parse to real clock times instead of collapsing to midnight
  - exact SHA-256 duplicate groups are detected and exposed through `duplicate_of_asset_id`
  - artifact coverage is separated from metadata and chronology quality statuses
  - `gps_missing` is downgraded to `info`
  - scene provenance is exported explicitly as `detected_scene`, `uniform_coverage`, or `short_full_video`

## Accepted Baseline Verified

- Accepted metadata HEAD: `7d06faac3bdc7ab9ba423a5876a3e5607e5444e8`
- Accepted voice baseline kept intact in branch history: `5f6a6e5b70251dd06d47824440b06a969c314579`
- Ancestry proof was verified locally:
  - `git merge-base --is-ancestor 5f6a6e5b70251dd06d47824440b06a969c314579 7d06faac3bdc7ab9ba423a5876a3e5607e5444e8`
  - result: baseline ancestry OK

## Release-Candidate Results

- Added the centralized theme layer in:
  - `handoff_builder/theme.py`
- Updated the main application in:
  - `app.py`
- Added theme regression coverage in:
  - `tests/test_theme.py`
- The release-candidate UI now has:
  - visible Light / Dark switch in the persistent header
  - saved theme choice across launches
  - themed message dialogs for info / warning / error
  - themed Prepare Handoff summary dialog
  - themed Voice Studio top-level window
  - themed Local Edit Runner panels, buttons, tables, and text surfaces

## Fresh Validation From 2026-07-23

- Full regression suite:
  - `python -m pytest -q` -> `87 passed in 48.49s`
- Bytecode check:
  - `python -m compileall handoff_builder app.py` -> success
- Diff hygiene:
  - `git diff --check` -> only LF/CRLF warning in `app.py`
- Portable build:
  - `cmd /c "echo.| build_exe.bat"` -> success on 2026-07-23
- Full regression suite on the hardening branch:
  - `python -m pytest -q` -> `93 passed in 44.63s`
- Targeted hardening regressions:
  - `python -m pytest -q tests/test_pipeline.py -k "whatsapp or chronology or duplicate or quality or gps_missing or metadata_contract_failure"` -> `10 passed`
- Existing packaged runtime still includes:
  - `dist\AI Handoff Builder\AI Handoff Builder.exe`
  - `dist\AI Handoff Builder\bin\ffmpeg.exe`
  - `dist\AI Handoff Builder\bin\ffprobe.exe`
  - `dist\AI Handoff Builder\bin\exiftool.exe`
  - `dist\AI Handoff Builder\bin\exiftool_files\**`

## Real Package Hardening v1 Result

- New working branch was cut from the accepted RC commit:
  - base branch: `codex/release-candidate-light-dark-ui`
  - base commit: `56d927a3e93f1ee4b161cbcfe55f729fc2207091`
  - working branch: `codex/real-package-hardening-v1`
- Real rebuild completed on the locally available `WEDDING_PROJECTv2` source set:
  - source path used: `tmp_metadata_real\WEDDING_PROJECTv2_20260722_192513\source\zip_001_Раскладывание_вещей`
  - new output ZIP: `tmp_real_package_hardening_v1\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
- The rebuilt package now proves:
  - filename-derived timestamps are no longer all `00:00:00`
  - chronology is ordered by the parsed file times
  - `artifact_coverage_ok=true`
  - `metadata_completeness=partial`
  - `metadata_reliability=partial`
  - `chronology_reliability=pass`
  - `gps_missing` warnings were downgraded to `info`
  - `scene_count=67`
  - `missing_artifact_paths=[]`
  - `failed_asset_count=0`
- The locally available source set did **not** satisfy the coordinator's expected proof shape:
  - actual local counts: `50 asset / 34 video / 16 photo`
  - actual exact duplicate count: `0`
- therefore the acceptance proof `51 asset / exact duplicate detected` is still blocked by source mismatch, not by the implemented code path
- A follow-up duplicate proof was completed with a byte-identical real-file copy:
  - source original found locally:
    - `tmp_metadata_real\WEDDING_PROJECTv2_20260722_192513\source\zip_001_Раскладывание_вещей\WhatsApp Image 2026-07-19 at 9.08.02 PM.jpeg`
  - second original with the `1` prefix was not found in the available source-set copies or searched ZIP/material directories on this machine
  - minimal real-file proof output:
    - `tmp_duplicate_realfile_proof\out\DUPLICATE_REALFILE_PROOF_ANALYSIS_HANDOFF.zip`
  - proof package confirms:
    - `duplicate_asset_count=1`
    - canonical asset: `afb107b5e8a3`
    - duplicate asset: `9824a4d37d40`
    - shared `sha256=ef8c01e22bef2529c0524ae78b897191aee8b184b09e5869a57551739231965a`
    - `duplicate_of_asset_id` is populated in the duplicate manifest entry
    - `chronology_reliability=fail` for the two-file duplicate proof because the filename-only timestamps are identical and should not be treated as trustworthy chronology

## UI Evidence

- Paired Light/Dark screenshots now exist at:
  - `tmp_rc_theme_screenshots\dark_prepare_main.png`
  - `tmp_rc_theme_screenshots\light_prepare_main.png`
  - `tmp_rc_theme_screenshots\dark_summary.png`
  - `tmp_rc_theme_screenshots\light_summary.png`
  - `tmp_rc_theme_screenshots\dark_local_edit_runner.png`
  - `tmp_rc_theme_screenshots\light_local_edit_runner.png`
  - `tmp_rc_theme_screenshots\dark_local_edit_runner_busy.png`
  - `tmp_rc_theme_screenshots\light_local_edit_runner_busy.png`
  - `tmp_rc_theme_screenshots\dark_voice_studio.png`
  - `tmp_rc_theme_screenshots\light_voice_studio.png`
  - `tmp_rc_theme_screenshots\dark_dialog_info.png`
  - `tmp_rc_theme_screenshots\light_dialog_info.png`
  - `tmp_rc_theme_screenshots\dark_dialog_warning.png`
  - `tmp_rc_theme_screenshots\light_dialog_warning.png`
  - `tmp_rc_theme_screenshots\dark_dialog_error.png`
  - `tmp_rc_theme_screenshots\light_dialog_error.png`
- Scaling and keyboard-focus evidence now exists at:
  - `tmp_rc_theme_screenshots\theme_ui_validation.json`
  - `tmp_rc_theme_screenshots\voice_studio_theme_validation.json`
- The scaling validation confirms visible key controls fit at:
  - `100%`
  - `125%`
  - `150%`
- The focus validation records keyboard traversal across header theme controls, notebook, source actions, listbox, and entries for both themes.

## Real End-To-End Evidence Kept Intact

- Real handoff CLI proof package:
  - `tmp_prepare_cli_proof\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
- Real RC workspace and rerender proof:
  - `tmp_rc_real_e2e\workspace`
  - first preview render job: `f35260850bb76dead667`
  - rerender job: `46cf0e82d55d5a4d49ac`
  - rerender MP4: `tmp_rc_real_e2e\workspace\renders\46cf0e82d55d5a4d49ac\reel.mp4`
- Real Voice Studio evidence kept in the same workspace:
  - voice job: `b15f0c360c9f8daf9ccd`
  - approved take: `b558be4c77dbac793612`
  - alignment artifacts under `tmp_rc_real_e2e\workspace\voice\jobs\b15f0c360c9f8daf9ccd\alignment\`

## Constraints Still In Force

- Extend the existing standalone app only.
- Do not modify originals on the owner machine.
- Use safe FFmpeg argument arrays only.
- No `shell=True`.
- No merge to `main`.
- Keep GitHub and the active issue contract as the source of truth.

## Official Acceptance Run From 2026-07-24

- Acceptance dataset used locally:
  - ZIP path: `C:\Users\oleg3\Downloads\Photos-1-001.zip`
  - ZIP SHA-256: `C27C40C4AAC0E6E88F849A0173BFFB605498CDBC6DF4196C2D06D1F38C301A20`
  - ZIP size: `338759229` bytes
  - ZIP contents: `53 asset / 35 photo / 18 video`
- The first current-branch reproduction on this dataset exposed the live blocker:
  - photos normalized to local EXIF time such as `2026-07-23T17:01:58-04:00`
  - videos normalized to naive QuickTime clock values such as `2026-07-23T21:01:33`
  - chronology was split into photo-first/video-last blocks instead of one mixed timeline
  - metadata warnings were `18 timestamp_conflict + 18 timezone_unknown`
  - hardening fields were present, so the remaining failure was specifically timezone normalization
- The blocker was fixed in `handoff_builder/metadata.py` by:
  - separating photo EXIF timestamp lookup from video QuickTime timestamp lookup
  - treating Samsung/QuickTime video create times as UTC when a companion offset is available
  - projecting video capture time into the local project offset using:
    - `ffprobe:com.samsung.android.utc_offset`
    - fallback: `exiftool:AndroidTimeZone`
- Added regression coverage in `tests/test_pipeline.py` for:
  - Samsung QuickTime UTC -> local project time projection without `timestamp_conflict`
  - mixed photo/video chronology ordering under `America/New_York`
- Full validation after the fix on the same dataset:
  - output ZIP: `tmp_acceptance_photos_1_001_fixed\PHOTOS-1-001_ANALYSIS_HANDOFF.zip`
  - output ZIP SHA-256: `4FF1349878ACF9DC6E2359D8F0D4A4550B9A930EAEE6B8E98ABE5AFE92F59293`
  - machine-readable validation report:
    - `tmp_acceptance_photos_1_001_fixed\PHOTOS-1-001_20260724_042222\package\validation_report.json`
    - SHA-256: `838315287D87A2B1131007715557B046B54FA2EBE1C4C8869267454E2F4DAA0F`
  - counts:
    - `source_asset_count=53`
    - `source_photo_count=35`
    - `source_video_count=18`
    - `failed_asset_count=0`
    - `missing_artifact_paths=[]`
    - `duplicate_asset_count=0`
  - quality statuses:
    - `artifact_coverage_ok=true`
    - `metadata_completeness=pass`
    - `metadata_reliability=pass`
    - `chronology_reliability=pass`
    - `chronology_reliability_reasons=[]`
  - chronology proof now mixes media by real time:
    - rank 1: `20260723_170122.mp4` -> `2026-07-23T17:01:33-04:00`
    - rank 4: `20260723_170158.jpg` -> `2026-07-23T17:01:58-04:00`
    - rank 13: `20260723_170321.mp4` -> `2026-07-23T17:03:31-04:00`
    - rank 15: `20260723_170345.jpg` -> `2026-07-23T17:03:45-04:00`
  - warnings after the fix:
    - `metadata_warning_count=0`
  - hardening fields verified in the package:
    - asset manifest entries include `sha256` and `duplicate_of_asset_id`
    - summary contains `artifact_coverage_ok`, `metadata_completeness`, `metadata_reliability`, `chronology_reliability`
    - scene entries include `segment_origin`
  - GPS/privacy/orientation/integrity:
    - `gps_export_mode=rounded`
    - `assets_with_gps=53`
    - photo analysis copies open upright at portrait dimensions such as `960x1280`
    - all proxies, previews, keyframes, storyboards, and contact sheets exist physically

## Immediate Next Actions

1. Commit and push the timezone-normalization fix in `codex/real-package-hardening-v1`.
2. Update the current Notion Implementation Report with the official acceptance run evidence.
3. Reply to the coordinator in the active Notion thread, then stop. No merge, release, or tag.
