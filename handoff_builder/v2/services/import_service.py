from __future__ import annotations

import json
import shutil
from pathlib import Path

from ..assets import load_active_local_registry, resolve_plan_assets_against_registry
from ..common import stable_v2_id
from ..domain.enums import QueueItemStatus
from ..domain.records import ImportResult, RenderQueueItem
from ..errors import UnsafePackageError
from ..packages.guards import compute_sha256
from ..packages.importer import import_edit_package
from ..plans.schema import deterministic_plan_hash, validate_payload
from ..render.report_stub import build_render_report_stub, write_render_report_stub
from ..storage import apply_migrations, connect_workspace_db
from ..storage.repositories import SqliteRenderQueueRepository, WorkspaceRepository
from ..workspace import load_project_config


def import_package_into_workspace(package_zip: Path, workspace: Path) -> ImportResult:
    project_root = workspace.resolve()
    config = load_project_config(project_root)
    project_id = str(config["project_id"])
    database_path = project_root / "project.sqlite"
    package_sha256 = compute_sha256(package_zip)

    connection = connect_workspace_db(database_path)
    package_root: Path | None = None
    try:
        apply_migrations(connection)
        workspace_repo = WorkspaceRepository(connection)
        queue_repo = SqliteRenderQueueRepository(connection)
        workspace_repo.get_project(project_id)

        existing = workspace_repo.get_existing_import_result(project_id, package_sha256)
        if existing:
            return ImportResult(
                project_id=existing["project_id"],
                package_id=existing["package_id"],
                handoff_id=existing["handoff_id"],
                edit_plan_id=existing["edit_plan_id"],
                render_job_id=existing["render_job_id"],
                render_report_path=Path(existing["report_path"]),
                package_root=Path(existing["extracted_root"]),
                package_sha256=existing["package_sha256"],
                plan_hash=existing["plan_hash"],
                duplicate=True,
            )

        package_id = stable_v2_id(project_id, package_sha256, length=20)
        package_root = project_root / "ai_packages" / package_id
        imported = import_edit_package(
            package_zip,
            project_root / "ai_packages",
            expected_project_id=project_id,
            package_root=package_root,
        )
        manifest = json.loads((package_root / "ai_edit_package.json").read_text(encoding="utf-8"))
        if not manifest.get("plans"):
            raise UnsafePackageError("AI edit package does not declare any plans.")
        active_plan = manifest["plans"][0]
        plan_path = (package_root / str(active_plan["path"])).resolve()
        plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
        plan_version = str(plan_payload["schema_version"])
        validate_payload("edit_plan", plan_version, plan_payload)
        if str(plan_payload["project_id"]) != project_id:
            raise UnsafePackageError("Edit plan project_id does not match workspace project.")
        if str(plan_payload["handoff_id"]) != imported.handoff_id:
            raise UnsafePackageError("Edit plan handoff_id does not match package handoff.")
        if str(plan_payload["handoff_sha256"]) != imported.handoff_sha256:
            raise UnsafePackageError("Edit plan handoff_sha256 does not match package handoff.")
        resolution_report: dict | None = None
        if plan_version in {"2.0", "2.1"}:
            registry_payload = (
                load_active_local_registry(project_root, fallback_dir=package_zip.parent)
                if plan_version == "2.0"
                else load_active_local_registry(project_root)
            )
            resolution_report = resolve_plan_assets_against_registry(
                list(plan_payload["assets"]),
                registry_payload,
                require_declared_integrity=plan_version == "2.0",
            )
        if plan_payload.get("voiceover"):
            voiceover_path = (package_root / str(plan_payload["voiceover"]["spec_path"])).resolve()
            if package_root not in voiceover_path.parents:
                raise UnsafePackageError("voiceover_spec path escapes the imported package root.")
            if not voiceover_path.exists():
                raise UnsafePackageError(f"voiceover_spec is missing: {voiceover_path}")
            voiceover_payload = json.loads(voiceover_path.read_text(encoding="utf-8"))
            validate_payload("voiceover_spec", str(voiceover_payload["schema_version"]), voiceover_payload)

        edit_plan_id = str(plan_payload.get("plan_id") or active_plan["plan_id"])
        plan_hash = deterministic_plan_hash(plan_payload)
        render_job_id = stable_v2_id(project_id, imported.package_id, edit_plan_id, "job", length=20)
        report_path = project_root / "renders" / render_job_id / "render_report.json"
        report = build_render_report_stub(
            project_id=project_id,
            package_id=imported.package_id,
            handoff_id=imported.handoff_id,
            handoff_sha256=imported.handoff_sha256,
            edit_plan_id=edit_plan_id,
            render_job_id=render_job_id,
            plan_hash=plan_hash,
            output_directory=report_path.parent,
        )
        resolution_report_path = report_path.parent / "asset_resolution.json"

        connection.execute("BEGIN")
        try:
            workspace_repo.insert_package(
                package_id=imported.package_id,
                project_id=project_id,
                handoff_id=imported.handoff_id,
                handoff_sha256=imported.handoff_sha256,
                schema_version=imported.schema_version,
                package_sha256=imported.package_sha256,
                source_zip_name=package_zip.name,
                extracted_root=imported.extracted_root,
            )
            workspace_repo.insert_plan(
                edit_plan_id=edit_plan_id,
                project_id=project_id,
                package_id=imported.package_id,
                handoff_id=imported.handoff_id,
                schema_version=plan_version,
                plan_sha256=compute_sha256(plan_path),
                plan_hash=plan_hash,
                plan_path=plan_path,
                plan_version=int(plan_payload.get("plan_version") or 1),
                parent_plan_id=str(plan_payload["parent_plan_id"]) if plan_payload.get("parent_plan_id") else None,
                patch_id=str(plan_payload["patch_id"]) if plan_payload.get("patch_id") else None,
                base_plan_hash=str(plan_payload["base_plan_hash"]) if plan_payload.get("base_plan_hash") else None,
            )
            queue_repo.enqueue(
                RenderQueueItem(
                    render_job_id=render_job_id,
                    project_id=project_id,
                    package_id=imported.package_id,
                    edit_plan_id=edit_plan_id,
                    status=QueueItemStatus.PENDING,
                )
            )
            write_render_report_stub(report, report_path)
            if resolution_report is not None:
                resolution_report_path.parent.mkdir(parents=True, exist_ok=True)
                resolution_report_path.write_text(
                    json.dumps(resolution_report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            queue_repo.insert_render_output(
                output_id=stable_v2_id(render_job_id, "report", length=20),
                render_job_id=render_job_id,
                report_path=report_path,
                renderer_status="not_started",
            )
            workspace_repo.add_event(
                project_id=project_id,
                package_id=imported.package_id,
                render_job_id=render_job_id,
                event_type="package_imported",
                payload={
                    "package_id": imported.package_id,
                    "edit_plan_id": edit_plan_id,
                    "render_job_id": render_job_id,
                    "package_sha256": imported.package_sha256,
                    "plan_hash": plan_hash,
                    "resolved_asset_count": resolution_report["resolved_asset_count"] if resolution_report else 0,
                },
            )
            connection.commit()
        except Exception:
            connection.rollback()
            if report_path.exists():
                report_path.unlink()
            raise

        return ImportResult(
            project_id=project_id,
            package_id=imported.package_id,
            handoff_id=imported.handoff_id,
            edit_plan_id=edit_plan_id,
            render_job_id=render_job_id,
            render_report_path=report_path,
            package_root=imported.extracted_root,
            package_sha256=imported.package_sha256,
            plan_hash=plan_hash,
            duplicate=False,
        )
    except Exception:
        if package_root and package_root.exists():
            shutil.rmtree(package_root, ignore_errors=True)
        raise
    finally:
        connection.close()
