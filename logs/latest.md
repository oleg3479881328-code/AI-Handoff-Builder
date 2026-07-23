# Latest Log

Date: 2026-07-23
Step: Real Package Hardening v1 from the accepted RC baseline

## Completed

- Started from accepted RC commit:
  - branch: `codex/release-candidate-light-dark-ui`
  - commit: `56d927a3e93f1ee4b161cbcfe55f729fc2207091`
- Created the new working branch:
  - `codex/real-package-hardening-v1`
- Implemented narrow hardening changes in the existing v1 handoff pipeline:
  - WhatsApp `AM/PM` filename parsing now preserves real clock time instead of collapsing to `00:00:00`
  - exact SHA-256 duplicate wiring was added through `sha256` and `duplicate_of_asset_id`
  - quality output was split into:
    - `artifact_coverage_ok`
    - `metadata_completeness`
    - `metadata_reliability`
    - `chronology_reliability`
  - `gps_missing` was downgraded from `warning` to `info`
  - scene provenance export now uses a stable origin label derived from the detection mode
- Updated local transfer-state docs:
  - `PROJECT_STATE.md`
  - `logs/latest.md`

## Verification

- Targeted hardening regressions:
  - `python -m pytest -q tests/test_pipeline.py -k "whatsapp or chronology or duplicate or quality or gps_missing or metadata_contract_failure"` -> `10 passed`
- Full regression suite:
  - `python -m pytest -q` -> `93 passed in 44.63s`
- Real rebuild on the locally available wedding source set:
  - source folder:
    - `tmp_metadata_real\WEDDING_PROJECTv2_20260722_192513\source\zip_001_Раскладывание_вещей`
  - output ZIP:
    - `tmp_real_package_hardening_v1\WEDDING_PROJECTv2_ANALYSIS_HANDOFF.zip`
- New rebuilt package facts:
  - `source_asset_count=50`
  - `source_video_count=34`
  - `source_photo_count=16`
  - `scene_count=67`
  - `artifact_coverage_ok=true`
  - `metadata_completeness=partial`
  - `metadata_reliability=partial`
  - `chronology_reliability=pass`
  - `missing_artifact_paths=[]`
  - `failed_asset_count=0`
  - `duplicate_asset_count=0`
- Real chronology proof from the rebuilt package:
  - first normalized timestamps now include real clock values such as:
    - `2026-07-19T20:33:32`
    - `2026-07-19T20:33:33`
    - `2026-07-19T20:33:44`
    - `2026-07-19T20:34:28`
    - `2026-07-19T20:36:05`
  - chronology no longer collapses all assets to midnight
- Warning severity split from the rebuilt package:
  - `gps_missing` -> `info` (`50`)
  - `filename_fallback` -> `warning` (`50`)

## Additional proof completed after the first hardening push

- Tightened chronology quality semantics:
  - filename-only timelines no longer receive unconditional `chronology_reliability=pass`
  - if chronology relies only on filename timestamps, the result is now at least `partial`
  - if identical filename times collapse chronology order, the result is `fail`
- Added and verified a real-file duplicate proof because the original `1WhatsApp ...` source file was not found in the available local source copies:
  - original file found locally:
    - `tmp_metadata_real\WEDDING_PROJECTv2_20260722_192513\source\zip_001_Раскладывание_вещей\WhatsApp Image 2026-07-19 at 9.08.02 PM.jpeg`
  - byte-identical copy created for integration proof:
    - `1WhatsApp Image 2026-07-19 at 9.08.02 PM.jpeg`
  - proof output ZIP:
    - `tmp_duplicate_realfile_proof\out\DUPLICATE_REALFILE_PROOF_ANALYSIS_HANDOFF.zip`
  - proof validation facts:
    - `source_asset_count=2`
    - `source_photo_count=2`
    - `artifact_coverage_ok=true`
    - `duplicate_asset_count=1`
    - `chronology_reliability=fail`
    - `chronology_reliability_reasons=[filename_times_collapsed, filename_only_timeline, all_timestamps_identical]`
  - duplicate mapping proof from the manifest:
    - canonical asset: `afb107b5e8a3` (`1WhatsApp Image 2026-07-19 at 9.08.02 PM.jpeg`)
    - duplicate asset: `9824a4d37d40` (`WhatsApp Image 2026-07-19 at 9.08.02 PM.jpeg`)
    - shared SHA-256:
      - `ef8c01e22bef2529c0524ae78b897191aee8b184b09e5869a57551739231965a`

## Blocker

- The coordinator's expected proof target was:
  - `51 asset / 34 video / 17 photo`
  - one exact duplicate detected
- The locally available real source set on this machine is:
  - `50 asset / 34 video / 16 photo`
  - exact duplicate groups detected: `0`
- This mismatch was confirmed from:
  - the source directory file count
  - previous local `validation_report.json` files
  - the new rebuilt package
- Result:
  - code changes are implemented and verified locally
  - acceptance proof for `51/34/17` is still blocked by source availability, not by an unimplemented duplicate or chronology code path

## Next

- Commit and push the chronology/duplicate-proof follow-up in `codex/real-package-hardening-v1`.
- Update the current Notion Implementation Report with the new duplicate proof and chronology-reliability correction.
- Wait for coordinator decision. No merge, release, or tag.
