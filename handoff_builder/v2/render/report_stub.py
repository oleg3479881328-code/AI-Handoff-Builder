from __future__ import annotations

import json
from pathlib import Path

from ..common import utc_now_iso
from ..plans.schema import validate_payload


def build_render_report_stub(
    *,
    project_id: str,
    package_id: str,
    handoff_id: str,
    handoff_sha256: str,
    edit_plan_id: str,
    render_job_id: str,
    plan_hash: str,
    output_directory: Path,
    warnings: list[str] | None = None,
) -> dict:
    report = {
        "schema_version": "1.0",
        "project_id": project_id,
        "package_id": package_id,
        "handoff_id": handoff_id,
        "handoff_sha256": handoff_sha256,
        "edit_plan_id": edit_plan_id,
        "plan_id": edit_plan_id,
        "render_job_id": render_job_id,
        "render_id": render_job_id,
        "plan_hash": plan_hash,
        "mode": "preview",
        "status": "pending",
        "created_at": utc_now_iso(),
        "output_directory": str(output_directory),
        "validation_summary": {
            "package_validated": 1,
            "queue_enqueued": 1,
            "renderer_status": "not_started",
        },
        "warnings": warnings or [],
        "outputs": [],
        "renderer_status": "not_started",
    }
    validate_payload("render_report", "1.0", report)
    return report


def write_render_report_stub(report: dict, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
