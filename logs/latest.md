# Latest Log

Date: 2026-07-23
Step: Metadata acceptance refresh, exact real-run evidence bundle, and scoped final verification

## Completed

- Continued work on branch `feat/metadata-after-voicebox-v1` using the accepted voice baseline plus preserved metadata work.
- Extended the v1 handoff metadata contract with:
  - capture-time source/confidence
  - location confidence and privacy-aware export
  - fps/audio-presence for video assets
  - owner-only local asset registry outside the ZIP
- Removed absolute `source_path` from portable manifests while preserving local traceability in `local_asset_registry.json`.
- Moved warnings artifact references to `metadata/metadata_warnings.json` across pipeline, GUI, README, manifests, and validation.
- Hardened ExifTool Windows Unicode handling by executing from each parent directory with filename-only arguments and locale-safe subprocess env.
- Added JSON-safe export normalization for Pillow/ExifTool/ffprobe payloads, including `IFDRational`.
- Changed stable asset IDs from mtime-sensitive derivation to content-hash derivation so re-extracted ZIP reruns stay deterministic.
- Found and fixed a real Pillow GPS regression from the final synthetic privacy rerun:
  - `GPSInfo` tag in main EXIF can be only an offset integer
  - real GPS payload must be loaded through `exif.get_ifd(34853)`
- Added regression coverage for:
  - Pillow GPS offset-backed EXIF payloads
  - Unicode ExifTool cwd usage
  - JSON-safe Pillow rational export
  - mtime-independent stable asset IDs
- Ran a fresh Unicode-path synthetic privacy matrix at:
  - `tmp_synthetic_privacy_final\synthetic_privacy_summary.json`
- Confirmed privacy behavior across all four export modes with `coverage_ok=true` in each mode.
- Investigated packaged runtime failure in `dist` and fixed two build issues:
  - replaced fragile `xcopy` with `robocopy`
  - enabled delayed expansion so `EXIFTOOL_ROOT` is evaluated correctly inside the batch block
- Rebuilt portable `dist` successfully on 2026-07-23 with full ExifTool runtime copied into:
  - `dist\AI Handoff Builder\bin\exiftool_files\**`
- Ran packaged metadata smoke at:
  - `tmp_synthetic_privacy_packaged_smoke\packaged_smoke_summary.json`
- Confirmed the packaged runtime now uses ExifTool successfully:
  - `coverage_ok=true`
  - `exiftool_status=available`
  - `extraction_error_count=0`
  - `assets_with_gps=2`
  - `assets_with_device_identity=2`
  - `sample_source=EXIF:GPSLatitude/GPSLongitude`
- Re-ran the real owner dataset handoff twice with the integrated app and confirmed deterministic joins/order on:
  - `tmp_metadata_real_current_run_c\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
  - `tmp_metadata_real_current_run_d\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
- Verified the real reruns still produce:
  - `50 assets`
  - `34 videos`
  - `16 photos`
  - `50 metadata records`
  - `0 lost assets`
  - `0 dangling references`
  - `gps_export_mode=exact`
  - all six metadata JSON files present
- Added stable-order hardening in the metadata pipeline so repeated chronology export preserves deterministic scene ordering across reruns.
- Added one missing metadata regression that the coordinator explicitly asked for:
  - `test_manifest_reference_without_metadata_record_is_hard_failure`
- Hardened the pipeline so a missing metadata record referenced by the manifest now fails explicitly with a controlled `ValueError` instead of a late `KeyError`.
- Created an exact evidence bundle for the fresh real runs plus a fresh official CLI proof run at:
  - `tmp_prepare_evidence_bundle\real_runs_evidence.json`
- The evidence bundle records:
  - exact CLI commands for run C, run D, and the fresh CLI proof run
  - archive create/write timestamps
  - full ZIP tree
  - factual validation counts
  - JSON parse plus `schema_version` checks for all manifest/metadata JSON files
- Created a fresh official CLI proof run on the real owner ZIP:
  - `tmp_prepare_cli_proof\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
  - `coverage_ok=true`
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
- Created GUI Prepare Handoff proof from the completed real package at:
  - `tmp_prepare_gui_summary_from_cli_proof\prepare_handoff_gui_proof.json`
  - `tmp_prepare_gui_summary_from_cli_proof\prepare_handoff_gui_main.png`
  - `tmp_prepare_gui_summary_from_cli_proof\prepare_handoff_gui_summary.png`
- GUI summary proof confirms:
  - `ExifTool: available`
  - `GPS mode: exact`
  - `34 videos found`
  - `34 videos represented`
  - `16 photos found`
  - `16 photos represented`
  - `50 metadata records`
  - `50 assets with capture time`
  - `0 assets with GPS`
  - `50 partial metadata records`
  - `0 lost files`
- Removed the temporary Voicebox-only approval-gate changes from the next metadata commit scope so the final metadata refresh does not repeat Voicebox development after the accepted baseline.

## Verification

- `python -m pytest tests\\test_pipeline.py -q` -> `23 passed in 8.99s`
- `python -m pytest -q` -> `84 passed in 43.58s`
- `python -m compileall handoff_builder app.py` -> success
- `git diff --check` -> clean aside from LF/CRLF warnings
- portable build on 2026-07-23:
  - `cmd /c "echo.| build_exe.bat"` -> success
- packaged runtime contents now include:
  - `dist\AI Handoff Builder\bin\exiftool.exe`
  - `dist\AI Handoff Builder\bin\exiftool_files\perl.exe`
  - `dist\AI Handoff Builder\bin\ffmpeg.exe`
  - `dist\AI Handoff Builder\bin\ffprobe.exe`

## Notes

- The fresh synthetic privacy matrix still showed `exiftool_status=error` when run against the older incomplete `dist` from before the delayed-expansion fix; that result is now superseded by the successful packaged smoke from 2026-07-23.
- The real owner dataset remains unchanged at `C:\Users\oleg3\OneDrive\Desktop\Раскладывание вещей\Раскладывание вещей.zip`.
- Commit `8adb2a4...` mixed metadata evidence with a Voicebox-only approval hardening change; the current refresh removes those voice-only file changes from the next metadata commit instead of rewriting published history.
- No merge was performed.

## Next

- Commit the metadata-only acceptance refresh branch state.
- Push `feat/metadata-after-voicebox-v1`.
- Update the existing Notion execution report page only.
- Wait for review. No merge.
