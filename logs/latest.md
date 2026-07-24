# Latest Log

Date: 2026-07-24
Step: Official Acceptance Run on `Photos-1-001.zip` from `codex/real-package-hardening-v1`

## Completed

- Used the full local acceptance dataset:
  - ZIP path:
    - `C:\Users\oleg3\Downloads\Photos-1-001.zip`
  - ZIP SHA-256:
    - `C27C40C4AAC0E6E88F849A0173BFFB605498CDBC6DF4196C2D06D1F38C301A20`
  - ZIP contents:
    - `53 asset / 35 JPG / 18 MP4`
- Reproduced the active blocker on the accepted hardening branch:
  - photos normalized to local EXIF times like `17:xx-04:00`
  - videos normalized to naive QuickTime times like `21:xx`
  - chronology was split by media type instead of mixed by real time
  - warnings were:
    - `18 timestamp_conflict`
    - `18 timezone_unknown`
- Implemented the narrow blocker fix in `handoff_builder/metadata.py`:
  - do not route video QuickTime dates through the generic photo-style `CreateDate` path
  - when Samsung/QuickTime video metadata includes a companion local offset, treat the naive QuickTime create times as UTC and project them into the local offset
  - prefer project-offset hints from:
    - `ffprobe:com.samsung.android.utc_offset`
    - fallback: `exiftool:AndroidTimeZone`
- Added regression coverage in `tests/test_pipeline.py`:
  - `test_video_quicktime_utc_is_projected_into_local_offset_without_conflict`
  - `test_chronology_mixes_photo_and_video_by_real_time_with_local_projection`
- Updated local transfer-state docs:
  - `PROJECT_STATE.md`
  - `logs/latest.md`

## Verification

- Targeted timezone/chronology regressions:
  - `python -m pytest -q tests/test_pipeline.py -k "quicktime or chronology"` -> `6 passed`
- Full regression suite:
  - `python -m pytest -q` -> `95 passed in 28.14s`
- Official acceptance rebuild on the same `Photos-1-001.zip` dataset:
  - output ZIP:
    - `tmp_acceptance_photos_1_001_fixed\PHOTOS-1-001_ANALYSIS_HANDOFF.zip`
  - output ZIP SHA-256:
    - `4FF1349878ACF9DC6E2359D8F0D4A4550B9A930EAEE6B8E98ABE5AFE92F59293`
  - validation report:
    - `tmp_acceptance_photos_1_001_fixed\PHOTOS-1-001_20260724_042222\package\validation_report.json`
  - validation report SHA-256:
    - `838315287D87A2B1131007715557B046B54FA2EBE1C4C8869267454E2F4DAA0F`
- Acceptance package facts:
  - `source_asset_count=53`
  - `source_video_count=18`
  - `source_photo_count=35`
  - `scene_count=19`
  - `artifact_coverage_ok=true`
  - `metadata_completeness=pass`
  - `metadata_reliability=pass`
  - `chronology_reliability=pass`
  - `missing_artifact_paths=[]`
  - `failed_asset_count=0`
  - `duplicate_asset_count=0`
- Mixed chronology proof from the accepted package:
  - rank `1`: `20260723_170122.mp4` -> `2026-07-23T17:01:33-04:00`
  - rank `4`: `20260723_170158.jpg` -> `2026-07-23T17:01:58-04:00`
  - rank `13`: `20260723_170321.mp4` -> `2026-07-23T17:03:31-04:00`
  - rank `15`: `20260723_170345.jpg` -> `2026-07-23T17:03:45-04:00`
  - later ranks stay mixed as well:
    - `20260723_171002.mp4` -> rank `44`
    - `20260723_171107.jpg` -> rank `45`
    - `20260723_171215.mp4` -> rank `49`
    - `20260723_171307.jpg` -> rank `51`
- Warning cleanup after the fix:
  - `metadata_warning_count=0`
- Hardening fields verified in the package:
  - every asset entry includes `sha256` and `duplicate_of_asset_id`
  - summary contains:
    - `artifact_coverage_ok`
    - `metadata_completeness`
    - `metadata_reliability`
    - `chronology_reliability`
  - scene manifest contains `segment_origin`
- GPS/privacy/orientation/integrity checks:
  - `gps_export_mode=rounded`
  - `assets_with_gps=53`
  - sample photo analysis copies open upright at `960x1280`
  - all proxies, previews, keyframes, storyboards, and contact sheets exist physically

## Next

- Commit and push the timezone-normalization blocker fix in `codex/real-package-hardening-v1`.
- Update the current Notion Implementation Report with the official acceptance run evidence.
- Reply to the coordinator in the active Notion thread and stop. No merge, release, or tag.
