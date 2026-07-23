# Latest Log

Date: 2026-07-23
Step: Metadata hardening completion, Voice Studio acceptance proof, and final local verification

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
- Found and fixed a real Voice Studio approval defect:
  - delegated/manual approval could approve a take based on pre-tempo QC
  - after `atempo`, the corrected WAV could fail transcript QC and still remain approved
  - approval now re-checks corrected audio and downgrades the take to `voiceover_needs_rewrite` when corrected QC fails
- Added Voice Studio regression coverage for:
  - lazy runtime model loading
  - corrected-audio transcript failure after tempo correction
- Repaired the local Voicebox runtime on this Windows machine and confirmed successful Olga generation through the real local API.
- Generated three real Olga wedding takes in:
  - `tmp_cross_workflow_real\workspace\voice\jobs\ae7ed3ffd0b21861e825`
- Re-ran delegated technical approval after the fix and confirmed the job now correctly ends in:
  - `status=voiceover_needs_rewrite`
  - `primary_approval=null`
- Verified GUI Voice Studio directly through the Tk application and captured proof at:
  - `tmp_cross_workflow_real\gui_proof\voice_studio_gui_proof.json`
  - `tmp_cross_workflow_real\gui_proof\voice_studio_gui.png`
- GUI proof confirms:
  - runtime is healthy
  - Olga profile is loaded
  - exactly 3 real takes are listed
  - `Play Selected` is enabled
  - `Approve Selected Take` is enabled

## Verification

- `python -m pytest tests\\test_pipeline.py -q` -> `22 passed in 20.28s`
- `python -m pytest tests\\test_v2_voice_studio.py -q` -> `18 passed in 3.25s`
- `python -m pytest -q` -> `85 passed in 43.36s`
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
- The Voice Studio GUI is ready for owner use with real Olga takes, but the current wedding script still needs a better approved take because all three candidates miss the strict approval policy after the corrected QC gate.
- No merge was performed.

## Next

- Commit the integrated metadata + approval-hardening branch state.
- Push `feat/metadata-after-voicebox-v1`.
- Update the existing Notion execution report page only.
- Wait for review. No merge.
