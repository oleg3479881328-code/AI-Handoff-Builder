# v2 Local Edit Runner Architecture

Date: 2026-07-20
Milestone: 2
Base SHA: `196886bd7eb26671b6999539220261fe753920a6`

## Goal

Add the first additive architecture skeleton for a local edit runner without breaking the accepted v1 handoff flow.

## Module Boundaries

```text
handoff_builder/v2/
├── domain/    immutable IDs, records, enums
├── packages/  safe package import, path guards, checksum verification
├── plans/     schema dispatch, canonical hashing, future plan validation
├── storage/   SQLite connection and migration ownership
├── render/    render queue contracts and compiler boundary
├── qc/        render report contract
└── errors/    typed user-facing and internal errors
```

## Dependency Direction

```text
domain <- errors
packages -> domain, errors, plans
plans -> errors
storage -> domain
render -> domain
qc -> domain
```

Rules:

- `domain` must not import from other v2 layers.
- `packages` may validate and stage inputs but must not compile render commands.
- `render` defines interfaces only in this milestone.
- `storage` owns persistence boundaries; other layers should not issue ad-hoc SQL.

## Package Import Flow

```text
ZIP
-> safe_extract_package_zip()
-> reject traversal / symlink / oversize
-> load ai_edit_package manifest
-> schema version dispatch
-> expected project binding check
-> allowlisted path verification
-> checksum verification
-> ImportedPackage record
```

## Package Validation Flow

```text
manifest presence
-> schema version known?
-> top-level required binding fields present?
-> declared files allowlisted?
-> extracted files stay under root?
-> sha256 matches?
-> project_id matches target project?
```

This milestone intentionally stops before full semantic edit-operation validation.

## Project Workspace Layout

Proposed local v2 workspace shape:

```text
project_workspace/
├── db/
│   └── workspace.sqlite3
├── imports/
│   └── <handoff_id>/
├── plans/
├── patches/
├── renders/
├── reports/
└── temp/
```

Notes:

- imported packages are staged under `imports/`;
- SQLite tracks handoffs, queue items, and migration state;
- render outputs and QC reports remain outside the database as files with hashes in DB-backed records.

## SQLite Ownership And Transaction Boundary

- SQLite is the local source of truth for imported handoffs and render queue state.
- `storage/db.py` owns connection setup.
- `storage/migrations.py` owns schema evolution through explicit migration IDs.
- migrations run inside an explicit transaction and roll back on failure.
- WAL is a future optimization toggle, not a hidden default in milestone 2.

## Edit-Plan Versioning

- schemas are versioned by type and version path, for example `schemas/edit_plan/1.0.json`.
- version dispatch is explicit through `schema_dispatch(schema_type, version)`.
- unsupported versions raise a typed `UnsupportedSchemaVersionError`.

## Immutable Patch Versioning

- patches are modeled as append-only immutable intent deltas.
- each patch binds to `project_id`, `handoff_id`, `handoff_sha256`, and `plan_id`.
- later milestones should persist patch lineage and effective-plan snapshots rather than mutate prior patch records in place.

## Render Queue State Machine

```text
pending
-> validating
-> ready
-> rendering
-> qc_pending
-> completed

pending|validating|ready|rendering|qc_pending
-> failed

pending|validating|ready
-> canceled
```

This state machine is modeled in `domain.enums.QueueItemStatus`. Milestone 2 defines the contract only, not the executor.

## Renderer Compiler Boundary

- The renderer boundary is a protocol: `RenderCompiler.compile_plan(plan_path) -> list[list[str]]`.
- Output must be allowlisted FFmpeg argument arrays only.
- No raw command strings.
- No `shell=True`.
- No direct package content is allowed to bypass plan validation into compiler execution.

## QC Boundary

- QC is represented as a contract object (`QCReport`) and future schema (`render_report/1.0.json`).
- QC should verify expected outputs, hashes, warnings, and missing artifacts before a job is considered successful.

## Error Taxonomy

User-facing boundary errors:

- `UnsafePackageError`
- `UnsupportedSchemaVersionError`
- `ProjectMismatchError`
- `ChecksumMismatchError`

Internal boundary error:

- `InternalRenderBoundaryError`

Principle:

- unsafe input and unsupported versions fail early with typed exceptions;
- internal compiler/executor misuse is separated from package/user problems.

## Provenance And Hashes

- every schema binds to `project_id`, `handoff_id`, `handoff_sha256`, and an item ID (`plan_id`, `patch_id`, or `render_id`);
- package file entries carry per-file `sha256`;
- deterministic plan hash is computed from canonical JSON serialization with sorted keys and compact separators.

## Crash Recovery

Milestone 2 only defines the persistence seams required for later crash recovery:

- imported handoffs stored durably in SQLite;
- queue items persisted with explicit status;
- migrations recorded in `schema_migrations`;
- file outputs live in stable directories outside transient memory.

Later milestones should add:

- resume-safe queue picking;
- stale-job recovery;
- interrupted-render cleanup and requeue policy.

## Security Boundaries

- reject ZIP traversal;
- reject ZIP symlink members;
- enforce package path allowlist;
- enforce package size boundary hook;
- enforce checksum validation;
- enforce project binding;
- reject unsupported schema versions.

These boundaries are deliberately implemented before any full renderer logic.

## Backward Compatibility With v1

- v1 GUI, CLI, manifests, and current `PROJECT_ANALYSIS_HANDOFF.zip` remain unchanged.
- milestone 2 adds new files and modules without changing accepted v1 behavior.
- additive wiring into current UI or CLI is intentionally deferred.

## Extension Points

Deferred modules should plug in through stable boundaries instead of leaking into core import logic:

- Client Wishes & Reference Intake -> package adapters / future intake modules
- Metadata Chronology & Camera Sync -> future plan enrichment
- Music Atmosphere & Event Audio -> future analysis and scoring layer
- Effects Engine -> future compiler operation family
- Invisible Watermark & Rights Evidence -> future post-render/QC stage
- Local Voice Studio -> future media-generation module after first application slice is validated

## Why This Skeleton Is Enough For Milestone 2

- It creates importable module boundaries.
- It establishes versioned contracts.
- It preserves v1.
- It implements the highest-risk safety guards first.
- It leaves room for later renderer implementation without prematurely locking the project into a second runtime stack.
