# Latest Log

Date: 2026-07-23
Step: Metadata hardening completion, packaged runtime fix, and final local verification

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

## Verification

- `python -m pytest tests\\test_pipeline.py -q` -> `21 passed in 16.90s`
- `python -m pytest -q` -> `82 passed in 117.11s`
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
- The real owner dataset remains unchanged and the previously successful deterministic real run remains available at `tmp_metadata_real_exif_deterministic`.
- No merge was performed.

## Next

- Commit the metadata hardening branch state.
- Update the existing Notion execution report page only.
- Wait for review. No merge.
