# Latest Log

Date: 2026-07-22
Step: Coordinator review rerun for Local Voice Studio duration approval defect

## Completed

- Read the updated Notion handoff page and executed only the `COORDINATOR REVIEW` priority.
- Continued work on branch `feat/local-voice-studio-v1` in the dedicated voice worktree.
- Hardened delegated technical approval so approval now requires:
  - exact transcript match
  - duration inside the effective policy
  - no technical errors
- Clamped effective duration policy to:
  - `duration_tolerance_percent <= 3.0`
  - `max_auto_tempo_percent <= 8.0`
- Changed delegated approval fallback so no candidate meeting the policy now returns `voiceover_needs_rewrite` instead of approving the least-bad take.
- Persisted richer approval evidence:
  - `original_audio_sha256`
  - `approved_audio_sha256`
  - corrected SHA/QC metadata when tempo correction is used
- Fixed voice mix preview to hash the actual approved audio path rather than trusting stale take metadata.
- Added/updated regression coverage for:
  - exact `8%` correction boundary
  - rejection above `8%` without correction
  - rewrite path when no exact-text duration-safe take exists
- Re-ran the full real local workflow on a fresh imported package:
  - workspace: `C:\Users\oleg3\Documents\AI Handoff Builder voice\tmp_voice_e2e_6\Свадебный final proof & Oleg's\voice-workspace`
  - package: `AI_EDIT_PACKAGE_voice_e2e_6.zip`
  - plan: `plan-voice-e2e-6`
  - voice job: `8c8c41b1e0886bf351ff`
- Produced 3 real Olga takes with the deterministic seed set `[12011, 12022, 12033]`:
  - take 1 `a40b480b13d3822481d3`: `10800 ms`, exact text, `8.474576%` delta, correctly ineligible
  - take 2 `de5c108ff029994ff5d0`: `11360 ms`, transcript mismatch, correctly ineligible
  - take 3 `378d691e77a2ba1bdd50`: `12000 ms`, exact text, `1.694915%` delta, correctly approved
- Generated downstream artifacts from the approved take:
  - `voice_words.json`
  - `transcript.srt`
  - `voice_karaoke.ass`
  - preview `mix_v001`
  - music-only patch rerenders through `mix_v004`
  - separated stems for original/music/voice
- Captured GUI proof that Voice Studio opens on the final workspace with:
  - healthy runtime
  - 3 real Olga takes visible
  - approved take selected
  - `Approve Selected Take` present
- Captured bounded runtime recovery proof:
  - failed refresh against `http://127.0.0.1:17494`
  - successful recovery against `http://127.0.0.1:17493`
  - same approved job/takes restored after refresh

## Verification

- `python -m pytest -q` -> `66 passed`
- `python -m compileall handoff_builder app.py` -> success
- `git diff --check` -> clean aside from line-ending warnings
- real GUI proof artifacts:
  - `tmp_voice_e2e_6\voice_studio_gui_proof.png`
  - `tmp_voice_e2e_6\voice_studio_gui_proof.txt`
- runtime recovery proof:
  - `tmp_voice_e2e_6\voice_runtime_recovery.txt`
- final chain/report artifacts:
  - `tmp_voice_e2e_6\final_mix_chain.json`
  - `voice\reports\8c8c41b1e0886bf351ff.json`

## Notes

- Voicebox runtime was restarted locally on `17493` with the existing installed server and the loaded `0.6B` model before the final rerun.
- Package import required keeping only the video asset inside `edit_plan.assets`; music remained an external input for preview mix commands.
- The final approved take did not need tempo correction, so `approved_audio_sha256 == original_audio_sha256 == c2f052152cd1dc6301ba750e22d53794cee43b7f357b15ff7a98ed4731a4fc05`.

## Next

- Commit the coordinator review fix set.
- Update the existing Notion execution report page only.
- Wait for coordinator review. No merge.
