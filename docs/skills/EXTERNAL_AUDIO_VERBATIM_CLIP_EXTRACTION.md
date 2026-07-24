# External Audio Verbatim Clip Extraction

## Status

Registered project capability.

## Purpose

Use an external multimodal transcription system, such as Gemini, to convert an audio recording into a trustworthy, reusable editing package when the receiving agent cannot reliably transcribe the original audio itself.

## Core Outcome

The workflow must preserve the original audio and produce exact, speaker-specific, time-coded excerpts that can be inserted into a song, reel, short video, documentary, podcast, or other edited media.

## Inputs

- original audio file;
- target speaker name or role;
- extraction purpose, such as poems, lyrics, quotes, hooks, emotional phrases, or montage-ready clips;
- optional context about the final media output.

## Required Process

1. Send the original audio to an external transcription system capable of processing the full recording.
2. Request a complete transcript with speaker separation.
3. Require millisecond timestamps in `HH:MM:SS.mmm` or `MM:SS.mmm` format.
4. Extract every relevant verbatim fragment spoken by the target speaker.
5. Do not rewrite grammar, pronunciation, wording, child speech, code-switching, or mistakes.
6. Mark unclear words explicitly instead of inventing them.
7. Record whether another speaker overlaps the target voice.
8. Produce a ranked list of the strongest clips.
9. Produce a clean montage sheet and machine-readable JSON.
10. Return the transcript package together with the untouched original audio.
11. Verify the reported audio duration against the source file before editing.

## Required Outputs

- full transcript with speaker labels and timestamps;
- target-speaker excerpt list;
- ranked best-fragment table;
- clean montage sheet with START, END, and TEXT;
- JSON clip manifest;
- quality-control checklist;
- original audio file.

## Accuracy Rules

- quotations must remain verbatim;
- adult speech must never be attributed to a child or other target speaker;
- repeated versions must be preserved as separate clips;
- timestamps must match across transcript, table, montage sheet, and JSON;
- a duration mismatch must be flagged before final cutting;
- low-confidence fragments must be labeled, not silently normalized.

## Failure Rule

If transcription fails, the handoff must still contain the original audio and a visible failure report. Missing derived text must never cause the source audio to disappear.

## Demonstrated Use Case

A conversation with Marusya was transcribed externally. The resulting package identified exact English song lines, spoken hooks, emotional Russian phrases, repeated takes, speaker separation, and montage-ready timestamps. This allowed the receiving agent to design a reel around Marusya's real voice and original words rather than recreating them with another voice.

## Handoff Builder Integration Requirement

AI Handoff Builder should support this capability as an audio-processing route:

`source audio -> external transcription prompt -> transcript package -> integrity validation -> final handoff`

The package manifest should record:

- source filename;
- source duration;
- source checksum;
- transcription provider;
- transcript status;
- transcript filename;
- clip count;
- timestamp format;
- speaker of interest;
- validation result.
