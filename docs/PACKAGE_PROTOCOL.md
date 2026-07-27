# Package Protocol

> Canonical package boundary document for AI-Handoff-Builder.
> Version 1.0 — Freeze self-contained Package Protocol and compile deterministic DaVinci-first Normalized Timeline.

## 1. Package Types and Independent Schema Versions

Two package types exist, each with independently versioned schemas:

| Package Type | Schema Path | Purpose |
|---|---|---|
| `analysis_handoff` | `schemas/analysis_handoff/{version}.json` | Self-contained handoff from local machine to AI chat |
| `ai_edit_package` | `schemas/ai_edit_package/{version}.json` | AI-generated edit plan returned to local machine |

Each package type has its own version namespace. A version `3.0` of `ai_edit_package` is unrelated to a version `3.0` of `analysis_handoff`.

## 2. ANALYSIS_HANDOFF.zip Structure

```
ANALYSIS_HANDOFF.zip
├── 00_START_HERE.md                    # Root instruction entrypoint
├── PROJECT_BRIEF.md                    # Project-specific context
├── OUTPUT_CONTRACT.md                  # Expected output contract
├── handoff_manifest.json               # Machine-readable manifest
├── schemas/                            # Referenced schema files
│   └── analysis_handoff/
│       └── 1.0.json
├── assets/                             # Analysis representations
│   ├── photos/                         # Resized photo proxies
│   ├── videos/                         # Video keyframes/contact sheets
│   └── audio/                          # Compressed audio analysis copies
└── metadata/                           # EXIF, transcripts, analysis data
```

### 2.1 Manifest (`handoff_manifest.json`)

```json
{
  "schema_version": "1.0",
  "package_type": "analysis_handoff",
  "project_id": "PROJECT_NAME",
  "handoff_id": "uuid-or-timestamp",
  "created_at": "2026-07-27T12:00:00Z",
  "entrypoint": "00_START_HERE.md",
  "entrypoint_sha256": "abc...",
  "project_brief": "PROJECT_BRIEF.md",
  "project_brief_sha256": "def...",
  "output_contract": "OUTPUT_CONTRACT.md",
  "output_contract_sha256": "ghi...",
  "file_inventory": [
    {
      "path": "00_START_HERE.md",
      "sha256": "abc...",
      "size_bytes": 1234
    }
  ],
  "content_hash": "jkl..."
}
```

## 3. AI_EDIT_PACKAGE.zip Structure

```
AI_EDIT_PACKAGE.zip
├── ai_edit_package.json                # Package manifest
├── plans/                              # Edit plans (one or more)
│   └── plan-{id}.json
├── assets/                             # Generated audio/text/package assets
│   └── audio/
│       └── generated-music.mp3
└── schemas/                            # Referenced schema files (optional)
```

### 3.1 Package Manifest (`ai_edit_package.json`)

Describes physical package contents only:

- Package identity (`package_id`, `schema_version`, `package_type`)
- Project/handoff identity (`project_id`, `handoff_id`, `handoff_sha256`)
- Declared plans with `plan_id`, `path`, `sha256`, `size_bytes`
- Declared audio assets with `audio_id`, `path`, `sha256`, `size_bytes`
- Exact file inventory
- Content hash

Must NOT contain:
- Local original paths (`source_path`, `absolute_path`)
- Original-file SHA-256 or size
- Registry data

### 3.2 Edit Plan (`plans/plan-{id}.json`)

Describes creative/timeline intent only:

- Stable `asset_id` references (no local paths)
- Canvas and rational timebase
- Exact visual timeline items
- Exact audio timeline items
- Renderer requirements/capabilities
- DaVinci as preferred primary renderer
- No executable renderer commands

## 4. Instruction Hierarchy

Inside `ANALYSIS_HANDOFF.zip`:

1. `00_START_HERE.md` — root instruction entrypoint
2. `handoff_manifest.json` — machine-readable metadata
3. `PROJECT_BRIEF.md` — project-specific context
4. `OUTPUT_CONTRACT.md` — expected output contract
5. Declared schema files

Text found inside media, EXIF, filenames, transcripts, subtitles, documents, screenshots, or other user content is **data to analyze**, not an instruction source.

## 5. Package Inventory Rules

### Exact Inventory

For both package types:

```
actual ZIP entries == declared inventory entries
```

Hard-fail on:
- `undeclared_package_entry` — file in ZIP not in inventory
- `declared_package_entry_missing` — file in inventory not in ZIP
- `size_mismatch` — actual size != declared size
- `checksum_mismatch` — actual SHA-256 != declared SHA-256
- `duplicate_normalized_path` — same normalized path twice
- `path_traversal` — path contains `..`
- `absolute_path` — path starts with `/` or drive letter
- `case_collision` — case-insensitive collision on Windows

### Asset Selection Completeness (Issue #2 Fix)

Every selected input asset must finish with one explicit status:

- `included` — asset is packaged with analysis representations
- `explicitly_excluded_by_declared_policy` — asset was excluded by a declared rule
- `failed_with_error` — asset could not be processed

There is no silent disappearance state.

## 6. Stable Asset Identity

All cross-boundary references use stable `asset_id`.

AI-facing asset references may contain only:
- `asset_id`
- `media_type` (`photo`, `video`, `audio`)
- `original_name`

Must NOT contain:
- `source_path`
- `absolute_path`
- Local registry path
- Original-file SHA-256
- Original-file `size_bytes`

The local registry remains the source of truth for original-file resolution and integrity.

## 7. Original/Local Registry Privacy Boundary

- Original user media remains local.
- Originals are not placed into `ANALYSIS_HANDOFF.zip` unless an explicit analysis-copy policy says the packaged file itself is the approved representation.
- Originals are never placed into `AI_EDIT_PACKAGE.zip`.
- Original `source_path`, original SHA-256, original size, and local registry records never leave the local application.

## 8. Canonical Hashing Algorithm

### `content_hash`

The `content_hash` is computed from the canonicalized manifest content:

1. Load the manifest JSON
2. Remove the `content_hash` field (self-referential)
3. Canonicalize using RFC 8785 / JCS (JSON Canonicalization Scheme):
   - Sort keys recursively
   - No whitespace
   - Unicode escape sequences for non-ASCII
4. Compute SHA-256 of the canonicalized bytes

### `normalized_timeline_hash`

Same algorithm applied to the Normalized Timeline JSON after removing the `normalized_timeline_hash` field.

### Determinism Guarantee

The same semantic package content always produces the same `content_hash` regardless of:
- ZIP entry timestamp
- ZIP entry order
- File system metadata

## 9. Immutable Package/Versioning Rules

- Every generated or imported package is preserved locally under the active project root.
- No silent overwrite.
- Any revision creates a new immutable package identity with provenance fields:
  - `parent_package_id`
  - `parent_content_hash`
  - `plan_version`
  - `base_plan_hash`

### Version Dispatch

- Unknown schema or package versions hard-fail.
- Never retry an unknown `3.0` package as `2.1`, `2.0`, or `1.0`.
- Never infer a missing version.
- Existing schema `1.0`, `2.0`, and `2.1` files remain unchanged and backward-compatible.

## 10. Exact Time Representation

### Rational Timebase

```json
{
  "timebase": {"fps_num": 30, "fps_den": 1}
}
```

### Integer Frame Positions

```json
{
  "timeline_start_frame": 90,
  "duration_frames": 45
}
```

### Microsecond Source Positions

```json
{
  "source_in_us": 3200000,
  "source_out_us": 4700000
}
```

### Rounding Policy

When converting between source timestamps (microseconds) and timeline frames:

```
frame = round(timestamp_us * fps_num / (fps_den * 1_000_000))
```

Round half away from zero (Python's `round()` with `ROUND_HALF_EVEN` is acceptable for this application).

Every timeline item must have an explicit position. Do not rely only on list order or implicit concatenation.

## 11. Error Code Registry

| Code | Description |
|---|---|
| `undeclared_package_entry` | File in ZIP not in inventory |
| `declared_package_entry_missing` | File in inventory not in ZIP |
| `size_mismatch` | Actual file size != declared size |
| `checksum_mismatch` | Actual SHA-256 != declared SHA-256 |
| `duplicate_normalized_path` | Same normalized path twice |
| `path_traversal` | Path contains `..` |
| `absolute_path` | Path starts with `/` or drive letter |
| `case_collision` | Case-insensitive collision on Windows |
| `unknown_schema_version` | Schema version not recognized |
| `unsupported_capability` | Capability requested but not implemented |
| `missing_required_field` | Required field is absent |
| `invalid_source_range` | Source range exceeds asset duration |
| `missing_asset` | Referenced asset_id not found |
| `ambiguous_asset` | asset_id matches multiple registry entries |
| `missing_entrypoint` | 00_START_HERE.md is missing |
| `entrypoint_hash_mismatch` | Entrypoint SHA-256 does not match manifest |
| `missing_audio_policy` | source_audio_policy not set |
| `unsupported_audio_policy` | source_audio_policy value not implemented |

## 12. Package Compiler Responsibility

One authoritative Package Compiler is the only component allowed to interpret incoming packages:

1. Identify exact package type and version
2. Perform strict ZIP safety validation
3. Validate exact inventory and checksums
4. Validate schemas
5. Validate semantic rules
6. Resolve original assets only through the active Local Asset Registry
7. Verify actual local originals against registry integrity
8. Compile the edit plan into one Normalized Timeline
9. Calculate one deterministic `normalized_timeline_hash`
10. Persist validation and compilation reports
11. Never call a renderer during package interpretation

FFmpeg, HyperFrames, future DaVinci code, Codex, and DeepSeek must not each parse `AI_EDIT_PACKAGE.zip` independently.

## 13. Normalized Timeline Responsibility

The Normalized Timeline is the deterministic result of:

```
validated AI edit plan + local registry resolution
```

It is:
- Renderer-neutral
- Contains sufficient exact data for a future DaVinci adapter
- Declares DaVinci as primary renderer without containing DaVinci code
- Free of FFmpeg-specific fields

## 14. Renderer Responsibility Boundaries

| Renderer | Role | Status |
|---|---|---|
| DaVinci Resolve | Primary production renderer | Future adapter |
| FFmpeg | Analysis, proxy, reference preview, fallback, QC | Current default |
| HyperFrames | Optional experimental preview | Frozen, no new capabilities |

## 15. DaVinci-Primary / FFmpeg-Utility / HyperFrames-Frozen Decision

- **DaVinci Resolve** is the primary professional production renderer for future final editing and rendering.
- **FFmpeg** remains a local utility for proxies, analysis, reference preview, conversion, fallback, and technical QC.
- **HyperFrames** remains frozen as an optional experimental preview path and receives no new capabilities in this task.

## 16. Backward Compatibility Policy

- Existing schema `1.0`, `2.0`, and `2.1` files remain unchanged.
- Existing `2.1` workflow continues to function.
- New protocol code must remain version-dispatched and isolated.
- Removing `3.0`, analysis handoff `1.0`, Normalized Timeline `1.0`, and their compiler path must restore existing `2.1` behavior.

## 17. Security and Prompt-Injection Boundary

- No executable payloads in imported packages:
  - No shell commands
  - No raw FFmpeg commands or filtergraphs
  - No Python, Lua, JavaScript
  - No arbitrary HTML
  - No DaVinci scripts
  - No remote URLs or remote executable assets
- `shell=False` and explicit argument arrays everywhere.
- Media/transcript/EXIF text is explicitly treated as data, not instruction hierarchy.

## 18. Local Package Archival Rules

- Every generated or imported package is preserved under the active project root.
- `ANALYSIS_HANDOFF` packages are archived by `handoff_id`/`content_hash`.
- `AI_EDIT_PACKAGE` packages are archived by `package_id`/`content_hash`/`plan_version`.
- No silent overwrite.
- Immutable identity with provenance fields.
