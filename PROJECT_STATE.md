# Current State

- Date: 2026-07-23
- Repository: `oleg3479881328-code/AI-Handoff-Builder`
- Active contract: `Yt-Dlp-Download-Manager` issue `#67`
- Current branch: `feat/metadata-after-voicebox-v1`
- Current phase: Metadata evidence expansion and final acceptance refresh in progress on the same branch

## What Exists Now

- Existing standalone desktop app remains the only app surface:
  - Tkinter GUI
  - v1 handoff ZIP builder
  - v2 local edit runner and Voice Studio layers
  - CLI
  - FFmpeg/ffprobe runtime
  - PyInstaller packaging
- Metadata handoff contract is now extended with:
  - portable manifests without absolute owner paths
  - local owner-only asset registry outside the ZIP
  - normalized capture-time source and confidence
  - location confidence and privacy-mode export behavior
  - video fps and audio-presence fields
  - metadata warnings artifact at `metadata/metadata_warnings.json`
- Stable asset IDs are now content-based instead of mtime-based, so reruns across re-extracted ZIP inputs stay deterministic.

## Current Focus

Finish the metadata-only acceptance refresh on `feat/metadata-after-voicebox-v1` by publishing exact real-run evidence, GUI/CLI proof, and the missing dangling-reference hard-failure regression without re-expanding Voicebox scope.

## Published Baseline

- Remote URL: `https://github.com/oleg3479881328-code/AI-Handoff-Builder`
- Accepted Voice Studio preservation commit on this branch history: `64f9975540942cf47b50b7af177ce8399f011f48`
- Accepted voice baseline source worktree commit kept intact before integration: `5f6a6e5b70251dd06d47824440b06a969c314579`

## Metadata Hardening Results

- Extended `AssetRecord` and handoff manifests with richer metadata fields:
  - `capture_time_source`
  - `capture_time_confidence`
  - `location_confidence`
  - `fps`
  - `audio_present`
- Added owner-only `local_asset_registry.json` outside the portable ZIP and removed absolute `source_path` from portable manifests.
- Expanded normalized metadata contract with:
  - capture time raw/utc/project/source/confidence
  - timezone source and raw offset
  - device and camera aliases
  - GPS source
  - privacy-aware `location` payload
  - chronology and cluster references
- Moved warnings artifact to `metadata/metadata_warnings.json` and wired it into GUI summaries, README, validation, and manifests.
- Hardened ExifTool extraction for Windows Unicode paths by:
  - grouping files by parent directory
  - invoking ExifTool from ASCII-safe `cwd`
  - passing filenames only
  - clearing locale env overrides
  - allowing partial-group fallback without killing the whole build
- Fixed Pillow EXIF GPS handling for real offset-backed `GPSInfo` payloads via `exif.get_ifd(34853)`.
- Normalized Pillow/ExifTool/ffprobe exports to JSON-safe primitives, including `IFDRational`.
- Updated build packaging so `dist\AI Handoff Builder\bin` now contains:
  - `ffmpeg.exe`
  - `ffprobe.exe`
  - `exiftool.exe`
  - full `exiftool_files\**`

## Fresh Validation From 2026-07-23

- Full test suite:
  - `python -m pytest -q` -> `84 passed in 43.58s`
- Targeted metadata regression:
  - `python -m pytest tests\\test_pipeline.py -q` -> `23 passed in 8.99s`
- Bytecode check:
  - `python -m compileall handoff_builder app.py` -> success
- Diff hygiene:
  - `git diff --check` -> line-ending warnings only
- Portable build:
  - `cmd /c "echo.| build_exe.bat"` -> success on 2026-07-23 after delayed-expansion fix
- Packaged runtime smoke:
  - `tmp_synthetic_privacy_packaged_smoke\\packaged_smoke_summary.json`
  - `coverage_ok=true`
  - `exiftool_status=available`
  - `extraction_error_count=0`
  - `assets_with_gps=2`
  - `assets_with_device_identity=2`
  - `sample_source=EXIF:GPSLatitude/GPSLongitude`

## Real Input Validation

- Real owner dataset ZIP remained unchanged on the owner machine:
  - `C:\Users\oleg3\OneDrive\Desktop\Раскладывание вещей\Раскладывание вещей.zip`
- Successful real analysis handoff run already exists locally and remains valid:
  - `tmp_metadata_real_current_run_c\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
  - repeat proof: `tmp_metadata_real_current_run_d\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
  - `coverage_ok=true`
  - `source_asset_count=50`
  - `processed_asset_count=50`
  - `scene_count=67`
  - `metadata_records_total=50`
  - `extraction_error_count=0`
- Deterministic-ID follow-up:
  - stable asset ID sequence matched across two independently extracted source roots after the content-hash fix
  - `validation_equal=true`
  - `asset_join_equal=true`
  - `scene_join_equal=true`
  - `normalized_order_equal=true`
  - `asset_ids_equal=true`
  - `scene_ids_equal=true`
- Exact evidence bundle for runs C/D and fresh CLI proof exists at:
  - `tmp_prepare_evidence_bundle\real_runs_evidence.json`
- This bundle records:
  - exact CLI command strings for run C, run D, and the fresh CLI proof run
  - archive creation/write timestamps
  - full ZIP tree for each run
  - JSON parse plus `schema_version` checks for all manifest/metadata JSON files
  - factual validation counts:
    - `ok=0`
    - `partial=50`
    - `missing=0`
    - `error=0`
    - `assets_with_capture_time=50`
    - `assets_with_gps=0`
    - `assets_with_device_identity=0`
    - `assets_using_filename_fallback=50`
    - `assets_using_filesystem_fallback=0`
    - `extraction_error_count=0`

## Prepare Handoff CLI / GUI Proof

- Fresh official CLI proof run exists at:
  - `tmp_prepare_cli_proof\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
  - command:
    `python -m handoff_builder.cli --project "WEDDING_PROJECTv2" --output "C:\Users\oleg3\Documents\AI Handoff Builder v1\tmp_prepare_cli_proof" --input "C:\Users\oleg3\OneDrive\Desktop\Раскладывание вещей\Раскладывание вещей.zip" --gps-export-mode exact`
- GUI summary proof based on that completed real package exists at:
  - `tmp_prepare_gui_summary_from_cli_proof\prepare_handoff_gui_proof.json`
  - `tmp_prepare_gui_summary_from_cli_proof\prepare_handoff_gui_main.png`
  - `tmp_prepare_gui_summary_from_cli_proof\prepare_handoff_gui_summary.png`
- GUI proof confirms:
  - `status_text=Готово: WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
  - `metadata_status_text=ExifTool: available`
  - summary window shows:
    - `34 videos found`
    - `34 videos represented`
    - `16 photos found`
    - `16 photos represented`
    - `50 metadata records`
    - `50 assets with capture time`
    - `0 assets with GPS`
    - `50 partial metadata records`
    - `0 lost files`
    - `ExifTool status: available | GPS mode: exact`
    - `Metadata warnings: 100 at metadata/metadata_warnings.json`

## Voicebox Scope Note

- Commit `8adb2a4e9619cae010c8fd8c74d53bd85ddba5d4` temporarily mixed metadata evidence work with a Voice Studio approval-gate hardening change.
- That Voicebox-specific change is not required for the metadata DoD on this page.
- The current local acceptance refresh removes those Voicebox-only file changes from the next metadata commit, keeping the final scope on:
  - metadata determinism
  - explicit dangling-reference hard failure
  - exact real-run / CLI / GUI evidence
  - report/log refresh

## Synthetic Privacy Validation

- Fresh Unicode-path privacy matrix rerun exists at:
  - `tmp_synthetic_privacy_final\synthetic_privacy_summary.json`
- Matrix characteristics:
  - path includes Cyrillic, spaces, `&`, and apostrophe
  - 4 assets total
  - 2 assets with real GPS/device metadata
  - all four export modes completed with `coverage_ok=true`
- Mode evidence:
  - `exact`: exact coordinates preserved
  - `rounded`: coordinates rounded in exported `location`, raw GPS removed
  - `venue_label_only`: coordinates removed, venue label retained
  - `excluded`: coordinates removed from exported payload
- Local-only registry still retains `source_path`, while portable manifest still excludes it.

## Constraints In Force

- Extend the existing standalone app only.
- Do not modify originals on the owner machine.
- Use safe FFmpeg argument arrays only.
- No `shell=True`.
- No merge yet.
- Keep GitHub and the active issue contract as the source of truth.

## Immediate Next Actions

1. Commit the metadata-only acceptance refresh on `feat/metadata-after-voicebox-v1`.
2. Update the existing Notion execution report page only.
3. Wait for coordinator/owner review. No merge.
