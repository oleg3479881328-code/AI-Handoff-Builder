# Output Contract

This final handoff is no longer the old “return one standalone JSON edit-plan first” contract.

The authoritative local workflow is already completed up to:

`MASTER package -> transcript import -> transcript validation -> final ZIP validation`

## What Downstream Analysis May Trust

- `MASTER/*_MASTER_ALL_MEDIA.mlt`
- `MASTER/*_MASTER_AUDIO.mp3`
- `MASTER/*_MASTER_TIMELINE_MAP.json`
- `MASTER/*_MASTER_EDIT_PLAN.json`
- `MASTER/*_MASTER_EDIT_PLAN.csv`
- `MASTER/*_MASTER_AUDIO_TRANSCRIPT_ORIGINAL.json`
- `MASTER/*_MASTER_AUDIO_TRANSCRIPT.json`
- `REPORTS/BUILD_VALIDATION_REPORT.json`

## Shotcut Context

- the master editable project is a Shotcut `.mlt`
- the validated timeline map remains the canonical local ordering source
- the older standalone JSON path belongs to the previous Issue `#27` workflow, not this final package

## What Downstream Analysis Must Not Invent

- local-only people identities
- scene boundaries not supported by the validated timeline map
- hook labels when the placeholder map says `pending_ai_analysis`
- creative decisions that were not derived from the validated transcript/timeline package

## Transcript Rules

1. Preserve event ordering.
2. Preserve overlapping events.
3. Preserve low-confidence events.
4. Preserve Gemini text fields without automatic correction.
5. Use `source_mappings[]` when an event crosses more than one source item.

## Non-Goals

- no required master MP4 by default
- no required WAV by default
- no assumption that Gemini processed source video instead of the canonical master MP3
