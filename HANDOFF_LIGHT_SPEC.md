# Handoff Light — Standalone MVP Specification

## Product boundary

Create a new standalone Windows executable:

```text
Handoff Light.exe
```

This is not a mode inside the existing AI Handoff Builder. Do not modify, merge into, or depend on the current Shotcut/Gemini/audio workflow.

The product has one job:

```text
arbitrary local material -> persistent project -> versioned Handoff ZIP for ChatGPT
```

## Minimal GUI

The main window must contain only these owner actions:

```text
New Project
Open Project
Add Material
Build Handoff ZIP
Open Package Folder
```

One compact status area must show:

```text
Project
Registered assets
New assets since previous handoff
Duplicates skipped
Missing files
Last handoff version
Next handoff version
```

No Shotcut controls, timeline controls, render controls, Gemini controls, transcript controls, audio workflow, tabs, advanced sections, or second-stage editor workflow.

## Project model

A project is persistent local state. A Handoff ZIP is only a versioned export of that project.

Suggested structure:

```text
Handoff Light Projects/
└── <Project_Name>/
    ├── project.json
    ├── asset_registry.json
    ├── ingestion_history.json
    ├── cache/
    ├── proxies/
    ├── photos/
    ├── metadata/
    ├── reports/
    └── handoffs/
```

Original media should remain in place by default. Store absolute local source paths only in local project state. Never include absolute paths in the Handoff ZIP.

The user must be able to reopen a project later and add more material.

## Accepted input

The user may add any mixture of:

- individual files;
- multiple files;
- folders;
- multiple folders;
- ZIP archives;
- ZIP archives inside folders;
- ZIP archives inside ZIP archives;
- arbitrary nested folder hierarchy;
- mixed video, photo, audio, and supported sidecar files.

The ingestion engine must recursively traverse folders and recursively unpack supported ZIP files until ordinary files are reached or a safety limit blocks further expansion.

## Nested archive provenance

For every discovered file, preserve a source chain such as:

```json
{
  "source_chain": [
    "Wedding.zip",
    "Guest Uploads",
    "Weekend.zip",
    "Phones",
    "IMG_4821.MOV"
  ],
  "archive_depth": 2
}
```

Files with the same filename but different content are separate assets.

## Deduplication

Exact duplicates must be detected by content, not filename.

Required identity inputs:

```text
file size + SHA-256
```

Behavior:

- exact duplicate already registered -> skip and report;
- same filename but different SHA-256 -> register as a new asset;
- already registered source missing from disk -> preserve asset and mark missing;
- damaged/unreadable file -> preserve record and report failure.

## Media inspection

Use:

- `ffprobe` for technical inspection;
- `ffmpeg` only for proxy generation or required media transformation;
- do not depend on `ffplay`.

Store useful technical metadata where available:

```text
duration
container
video codec
audio codec
width
height
fps
bitrate
audio sample rate
audio channels
creation/capture metadata
```

Unsupported non-media files must not crash ingestion. Record them as ignored or unsupported.

## Safety limits

Recursive ingestion must be safe.

Required protections:

- ZIP path traversal prevention;
- extraction only inside a controlled temporary root;
- maximum nested archive depth: configurable, default 20;
- maximum discovered file count: configurable, default 100000;
- maximum total expanded bytes: configurable;
- compression-ratio / ZIP-bomb protection;
- reject encrypted archives with a clear report unless explicitly supported later;
- reject executable payloads from the Handoff ZIP;
- clean temporary extraction after completion or failure;
- no `shell=True`;
- long operations run in the existing background-task pattern so the GUI remains responsive.

## Versioned Handoff ZIP

Every export receives the next three-digit version and never overwrites a previous package:

```text
V001_<Project_Name>_HANDOFF.zip
V002_<Project_Name>_HANDOFF.zip
V003_<Project_Name>_HANDOFF.zip
```

The next version is determined from durable project history, not merely by scanning one output folder.

`handoff_manifest.json` must include at least:

```json
{
  "schema_version": "1.0",
  "project_id": "stable-id",
  "project_name": "Human-readable name",
  "handoff_version": 3,
  "handoff_filename": "V003_Project_HANDOFF.zip",
  "created_at": "ISO-8601 timestamp",
  "previous_handoff": "V002_Project_HANDOFF.zip",
  "asset_count": 0,
  "new_asset_count": 0,
  "duplicate_count": 0,
  "missing_asset_count": 0
}
```

## Handoff ZIP inventory

Minimum required inventory:

```text
00_START_HERE.md
PROJECT_BRIEF.md
handoff_manifest.json
asset_registry.json

PROXIES/
PHOTOS/
AUDIO/
METADATA/

REPORTS/
├── NEW_MATERIAL.json
├── DUPLICATES.json
├── MISSING_FILES.json
├── DAMAGED_FILES.json
├── UNSUPPORTED_FILES.json
└── BUILD_VALIDATION_REPORT.json
```

Do not include:

- absolute local paths;
- original full-size videos by default;
- executable files;
- temp/cache files;
- archive passwords;
- unrelated project state.

`asset_registry.json` inside the ZIP must use portable `asset_id` references and package-relative paths only.

## Incremental updates

When material is added later:

1. reopen the same project;
2. ingest the new selection recursively;
3. compare against the durable registry;
4. add only new assets;
5. update missing/damaged status;
6. generate proxies only for new or changed media;
7. record ingestion history;
8. build the next Handoff ZIP version.

`REPORTS/NEW_MATERIAL.json` must describe what changed since the immediately preceding successful handoff.

## Build validation

Before showing success:

1. open the generated ZIP;
2. verify ZIP CRC;
3. verify exact required inventory;
4. reject undeclared unsafe entries;
5. validate all JSON as UTF-8;
6. verify every declared package-relative file exists;
7. verify no absolute paths leaked;
8. write `BUILD_VALIDATION_REPORT.json`;
9. only then mark the handoff ready.

## Application version

Use one source of truth for the application version.

Show it in:

- EXE filename;
- window title;
- visible main window label;
- build report.

Initial build naming:

```text
V0.1.0_Handoff_Light.exe
```

Git commit SHA must not appear in the EXE filename. It may appear separately in About/build evidence.

## Acceptance tests

Required tests must cover:

1. individual files;
2. one folder with deep hierarchy;
3. ZIP containing folders;
4. ZIP inside ZIP to multiple levels;
5. same filename with different content;
6. duplicate content with different filename;
7. adding new material to an existing project;
8. missing previously registered source;
9. damaged media;
10. unsupported file;
11. blocked path traversal ZIP;
12. blocked ZIP bomb / expansion limit;
13. version increments V001 -> V002 without overwrite;
14. no absolute paths inside final ZIP;
15. packaged Windows EXE manual GUI acceptance.

## Git boundary

Work only on:

```text
feat/handoff-light-standalone
```

Do not modify PR #26, Issue #27, or the existing combined Builder workflow. Create a separate Draft PR for Handoff Light. Do not merge or mark Ready for Review without owner approval.
