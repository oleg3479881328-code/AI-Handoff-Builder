# Existing Solution Scan

Date: 2026-07-20
Milestone: 2
Base SHA: `196886bd7eb26671b6999539220261fe753920a6`

## Decision Summary

This milestone keeps the accepted v1 handoff builder intact and adds a v2 architecture skeleton around it.

Reuse decisions:

- Reuse v1 safe ZIP extraction, stable IDs, UTF-8 JSON writing, and FFmpeg executable discovery patterns.
- Adapt SQLite as the local source of truth with explicit migration ownership and transaction boundaries.
- Adapt JSON Schema version dispatch for package, plan, patch, and render-report contracts.
- Adapt FFmpeg and ffprobe as local rendering primitives, but keep the compiler boundary deferred.
- Keep OpenTimelineIO only as a future interchange/export adapter, not as the MVP runtime foundation.
- Keep ASS/libass only as a future text-rendering boundary, not as the milestone 2 rendering core.

Rejected as MVP foundations:

- Remotion
- Shotcut / MLT
- Auto-Editor
- Arbitrary command templates from AI packages

## Internal Candidates

### Current AI Handoff Builder v1

- Checked: `handoff_builder/utils.py`, `handoff_builder/models.py`, `handoff_builder/pipeline.py`, `handoff_builder/ffmpeg_tools.py`, tests, manifests.
- Relevant capability: safe ZIP extraction, deterministic-ish media identity, local FFmpeg execution, manifest discipline, Windows-safe CLI/GUI paths.
- License: repository-local code
- Decision: Reuse / Adapt
- Reason: already validated locally; directly aligned with owner constraint to extend the existing app rather than create a second tool.
- Risk: v1 models are media-analysis oriented, so v2 must add isolated package/render/storage boundaries instead of overloading current classes.

### Current project memory files

- Checked: `PROJECT.md`, `AGENTS.md`, `PROJECT_STATE.md`, `logs/latest.md`
- Relevant capability: durable execution context and transfer readiness
- License: repository-local docs
- Decision: Reuse
- Reason: PEOS already requires these as the active front door and continuity layer.
- Risk: must stay updated after each milestone or re-entry cost rises quickly.

## External Candidates

### FFmpeg / ffprobe

- Checked: official project and legal pages
- Relevant capability: local transcoding, trimming, concat, scaling, overlays, waveform/audio transforms, metadata probing
- License: LGPL 2.1+ by default, with GPL impact for certain enabled components
- Decision: Reuse
- Reason: already the accepted local renderer foundation and well matched to safe compilation into argument arrays.
- Risk: build/license mix matters when bundling binaries, so v2 must keep an allowlisted operation layer above raw args.
- Sources:
  - https://www.ffmpeg.org/legal.html
  - https://www.ffmpeg.org/

### SQLite

- Checked: official transaction and WAL docs
- Relevant capability: local durable source of truth, migrations, crash recovery, queue state
- License: public domain (widely documented project stance; not re-verified here)
- Decision: Adapt
- Reason: perfect fit for a single-user Windows desktop app with bounded local concurrency and auditable state.
- Risk: WAL is single-host oriented and should be treated as local-machine storage, not a network-share multi-host foundation.
- Sources:
  - https://sqlite.org/lang_transaction.html
  - https://sqlite.org/wal.html

### Pydantic JSON Schema patterns

- Checked: official docs for JSON schema-related configuration concepts
- Relevant capability: strict versioned schema modeling and generation patterns
- License: MIT (not re-verified in this turn; inferred from the project’s common distribution metadata)
- Decision: Adapt concept, reject as milestone-2 runtime dependency
- Reason: the project needs versioned schemas immediately, but not a new runtime dependency just to ship static schema skeletons and dispatch tests.
- Risk: if runtime validation grows complex, adding Pydantic later may be justified.
- Sources:
  - https://docs.pydantic.dev/2.11/api/config/
  - https://docs.pydantic.dev/fastui/

### OpenTimelineIO

- Checked: official overview and file-bundle docs
- Relevant capability: editorial interchange and future export/import adapter patterns
- License: Apache 2.0 (not re-verified in this turn; recalled from project packaging and may be stale)
- Decision: Reject as MVP foundation, keep as future adapter
- Reason: OTIO models editorial timelines, but this milestone needs a controlled local package/render workflow first, not cross-NLE interchange.
- Risk: adopting OTIO too early would pull the design toward external-edit interoperability before the local safe compiler exists.
- Sources:
  - https://opentimelineio.readthedocs.io/en/latest/
  - https://opentimelineio.readthedocs.io/en/latest/tutorials/otio-filebundles.html

### ASS / libass

- Checked: official libass repository
- Relevant capability: subtitle/text rendering boundary for future overlays
- License: ISC
- Decision: Reject as milestone-2 foundation, keep as future extension point
- Reason: useful later for high-fidelity text overlays, but not necessary to define the package/import/storage skeleton.
- Risk: text rendering requirements could later require platform-specific font and shaping behavior work.
- Sources:
  - https://github.com/libass/libass

### Remotion

- Checked: official license/pricing docs
- Relevant capability: browser/React-based programmatic video rendering
- License: source-available with commercial licensing conditions
- Decision: Reject
- Reason: directly conflicts with owner constraints against browser renderer / Remotion and would introduce a second rendering stack.
- Risk: license/compliance and Node/browser runtime complexity are misaligned with the local FFmpeg-first MVP.
- Sources:
  - https://www.remotion.dev/docs/license
  - https://www.remotion.dev/docs/license/faq

### Shotcut / MLT

- Checked: official Shotcut site
- Relevant capability: full NLE and timeline framework
- License: open source; Shotcut is presented as a cross-platform editor built on MLT
- Decision: Reject
- Reason: too heavy for an additive local runner skeleton and would drag the app toward editor integration instead of controlled plan compilation.
- Risk: deep dependency and timeline-model complexity far beyond milestone 2 scope.
- Sources:
  - https://www.shotcut.org/

### Auto-Editor

- Checked: official app/download/docs pages
- Relevant capability: automatic silence/stillness-based editing
- License: commercial app licensing for exports/features
- Decision: Reject
- Reason: its product model is specialized around automatic edits rather than deterministic execution of owner-controlled AI packages.
- Risk: importing its assumptions would skew the architecture toward heuristic editing instead of auditable plan execution.
- Sources:
  - https://app.auto-editor.com/download
  - https://auto-editor.com/ref/options

### Arbitrary command templates from AI

- Checked: owner constraints from issue `#67` and the milestone handoff page
- Relevant capability: raw flexibility
- License: n/a
- Decision: Reject
- Reason: violates the project’s core safety boundary. The AI package must describe intent through allowlisted operations, not raw shell or FFmpeg text.
- Risk: command injection, drift, non-portable plans, and unreviewable render behavior.

## Resulting Milestone-2 Architecture Direction

- Preserve v1 as a stable analysis/handoff baseline.
- Add a v2 package-import, schema, storage, and render-boundary layer in parallel.
- Keep runtime dependencies minimal.
- Leave renderer compilation, effect coverage, and NLE/export adapters for later milestones.
