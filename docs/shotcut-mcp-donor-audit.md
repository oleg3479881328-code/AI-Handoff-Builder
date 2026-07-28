# Shotcut MCP Donor Audit

Date: 2026-07-28
Issue: `#25`
Decision: `ACCEPT_FOR_ISOLATED_PROOF`

## Pin

- Donor repository: `matrodrigs/shotcut-mcp`
- Pinned tag: `v1.5.0`
- Full commit SHA behind the tag: `7e66c17b92c2058670ae5e4c21aa61e27c51d317`
- Runtime entry script: `scripts/shotcut_mcp_server.py`

## License And Attribution

- Shotcut MCP license: MIT
- Shotcut license: GNU General Public License v3.0
- Proof runtime target: official Shotcut `26.6.25`
- MLT detected during proof: `7.40.0`
- FFmpeg / FFprobe detected during proof: bundled `n8.1.2`

## Runtime Dependencies

Confirmed from code and README:

- Python `3.10+`
- official Shotcut installation providing:
  - `shotcut.exe`
  - `melt.exe`
  - `ffmpeg.exe`
  - `ffprobe.exe`
- standard-library-only Python runtime for the MCP server itself

The donor README states that a source checkout does not require `pip install`. Code inspection confirmed no mandatory third-party runtime import in the MCP server path.

## Executable Boundaries

Reviewed files:

- `README.md`
- `LICENSE`
- `SECURITY.md`
- `CHANGELOG.md`
- `pyproject.toml`
- `scripts/shotcut_mcp_server.py`
- `shotcut_mcp/server.py`
- `shotcut_mcp/tools.py`
- `shotcut_mcp/path_policy.py`
- `shotcut_mcp/platform.py`
- `shotcut_mcp/project.py`
- `shotcut_mcp/render.py`
- `shotcut_mcp/render_worker.py`
- `shotcut_mcp/render_jobs.py`
- `tests/test_integration.py`

Observed execution boundaries:

- `scripts/shotcut_mcp_server.py` inserts the donor root into `sys.path` and dispatches into `shotcut_mcp.server:main`
- MCP transport is newline-delimited JSON-RPC over stdio
- external process execution uses argument arrays only
- no `shell=True` found in the audited runtime path
- render jobs launch a detached worker process:
  - `python -m shotcut_mcp.render_worker <job_id>`
- actual render work delegates to `melt.exe`
- media probing / QC delegates to `ffmpeg.exe` / `ffprobe.exe`

## Filesystem Write Scope

Confirmed write areas from code:

- explicit target project path supplied by the caller
- per-project backup directories under a hidden donor-managed folder
- donor render job metadata and logs under user temp storage
- preview / contact-sheet / render output paths supplied by the caller
- temporary validation / output transaction files near the target project or render output

No evidence was found of arbitrary repository-wide writes beyond:

- caller-authorized project/output paths
- donor-owned temp/job state

## Network Behavior

Confirmed in code:

- stdio server only; no HTTP listener path in the audited runtime
- network resources are denied by default through path policy
- no telemetry or outbound reporting logic found in the audited runtime files

Not confirmed:

- upstream build/release pipelines outside the local audited source tree

## Safety Controls Confirmed In Code

- allowed-root path policy
- optional absolute-path requirement, enabled for the proof
- network-resource denial by default
- unsafe-consumer-property denial by default
- SHA-256 revision checks before project mutation
- lock / backup / restore flow for project edits
- temporary-write + validation + atomic replace workflow
- bounded message/project size enforcement in current release notes and schemas
- render supervisor separation with durable job metadata
- explicit JSON-RPC argument validation and structured `isError` responses
- subprocess invocation via argument arrays only

## Claims Not Fully Confirmed In Code

- broad client-marketplace behaviors outside the local stdio server
- release CI provenance beyond the checked-in repository metadata
- all cross-platform claims outside Windows-focused proof coverage

## Windows Evidence

Verified locally during the owner-machine proof:

- official Shotcut `26.6.25` portable runtime launched on Windows 11
- `shotcut_status` reported:
  - Shotcut found
  - Melt found
  - FFmpeg found
  - FFprobe found
  - repository ready
- `shotcut_doctor` reported:
  - `compatible=true`
  - validated stack `Shotcut 26.6.25` + `MLT 7.40.x`
- all required Gate 4 operations completed against one real owner-selected MP4:
  - status
  - doctor
  - probe
  - create
  - inspect
  - plan
  - edit
  - validate
  - preview
  - contact sheet
  - open in Shotcut
  - render
  - render status
  - rendered-media probe
  - final inspect

## Known Limitations

- Source-checkout runtime on Windows needs explicit donor import visibility for detached render workers.
  - The entry script fixes `sys.path` for the foreground server.
  - The detached worker path `python -m shotcut_mcp.render_worker` does not inherit that fix by itself when the donor is only a raw clone and not installed into an environment.
  - In the isolated proof this was resolved by injecting donor-root `PYTHONPATH` from the adapter boundary.
- A short Windows race was observed around `render_status`.
  - Immediately after render completion, one early status poll can transiently report:
    - `status=failed`
    - `status_note="The render supervisor exited before finalizing the job."`
  - The durable job metadata then settles to `completed`, and the final MP4 is present.
  - The AI-Handoff-Builder adapter compensates for this by re-reading durable job metadata before surfacing a terminal failure.
- The donor is intentionally low-level.
  - It exposes many editing operations.
  - AI-Handoff-Builder must keep a narrow validated adapter surface instead of forwarding arbitrary low-level operations.

## Risks

- Without a wrapper, a raw clone on Windows can fail background renders even though `shotcut_status` and `shotcut_doctor` pass.
- Without defensive status readback, callers can misclassify a successful render as failed.
- The donor operates on real editable `.mlt` files, so caller-side path policy and revision discipline remain mandatory.
- The donor is powerful enough to edit timelines directly; exposing it as a free-form AI tool would exceed the trusted local-runner boundary.

## Accept / Reject Decision

Decision: `ACCEPT_FOR_ISOLATED_PROOF`

Reason:

- the donor enforces meaningful project-safety controls in code;
- the Windows proof succeeded end-to-end on official Shotcut `26.6.25`;
- the two observed Windows issues were boundary/integration issues, not evidence of unsafe arbitrary execution;
- AI-Handoff-Builder can contain those issues behind a narrow adapter without copying the donor into the main runtime tree.
