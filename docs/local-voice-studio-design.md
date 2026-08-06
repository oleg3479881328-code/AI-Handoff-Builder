# Local Voice Studio Design

## Goal

Add a local Voicebox-backed voice workflow to AI Handoff Builder without breaking:

- v1 Prepare Handoff
- v2 import -> render -> QC -> patch -> rerender

## Implemented layers

```text
CLI / future GUI
-> v2.services.voice_service
-> v2.voice.client / repository / qc / alignment
-> v2.audio.mix
-> local Voicebox runtime + FFmpeg/ffprobe
```

## Current implementation choices

- Voicebox remains a sidecar runtime on `127.0.0.1`
- generated audio is stored in workspace files, not SQLite blobs
- runtime snapshots, profile mappings, jobs, takes, reviews, approvals, alignments and mix patches are persisted additively in SQLite
- QC uses ffprobe + ffmpeg filters for audio inspection
- transcript fallback uses local Voicebox `/transcribe`
- if transcript or word alignment is unavailable, the job keeps its audio artifacts and records a warning instead of crashing

## Workspace structure

```text
workspace/
└── voice/
    ├── runtime/
    ├── profiles/
    ├── jobs/<voice_job_id>/
    │   ├── spec.json
    │   ├── requests/
    │   ├── responses/
    │   ├── takes/raw/
    │   ├── takes/normalized/
    │   ├── qc/
    │   ├── alignment/
    │   ├── approval/
    │   └── renders/
    └── reports/
```

## Honest gaps

- full GUI tab is not implemented yet
- AI_EDIT_PACKAGE `voiceover_spec` import wiring is not implemented yet
- word-level alignment is still `word_alignment_unavailable` unless a real local aligner is added to the Builder runtime
- owner listening approval is not something the agent can fabricate; only the storage and CLI path are implemented
