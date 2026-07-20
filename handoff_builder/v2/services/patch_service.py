from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from ..common import stable_v2_id, utc_now_iso
from ..domain.enums import QueueItemStatus
from ..domain.records import PatchApplyResult, RenderQueueItem
from ..errors import UnsafePackageError
from ..packages.guards import compute_sha256, safe_extract_package_zip
from ..plans.schema import deterministic_plan_hash, validate_payload
from ..plans.semantic import load_and_validate_preview_plan
from ..render.ffmpeg_backend import FFmpegBackend
from ..render.report_stub import build_render_report_stub, write_render_report_stub
from ..storage import apply_migrations, connect_workspace_db
from ..storage.repositories import SqliteRenderQueueRepository, WorkspaceRepository
from ..workspace import load_project_config


def apply_patch_in_workspace(patch_source: Path, workspace: Path) -> PatchApplyResult:
    project_root = workspace.resolve()
    config = load_project_config(project_root)
    project_id = str(config["project_id"])
    patch_sha256 = compute_sha256(patch_source)
    connection = connect_workspace_db(project_root / "project.sqlite")
    patch_root: Path | None = None
    report_path: Path | None = None
    extracted_temp_root: Path | None = None
    try:
        apply_migrations(connection)
        workspace_repo = WorkspaceRepository(connection)
        queue_repo = SqliteRenderQueueRepository(connection)
        workspace_repo.get_project(project_id)

        patch_payload, patch_file_name, extracted_temp_root = _load_patch_payload(patch_source, project_root, patch_sha256)
        base_plan_id = str(patch_payload["base_plan_id"])
        existing = workspace_repo.get_existing_patch_result(project_id, patch_sha256, base_plan_id)
        if existing:
            return PatchApplyResult(
                project_id=existing["project_id"],
                package_id=existing["package_id"],
                handoff_id=existing["handoff_id"],
                patch_id=existing["patch_id"],
                patch_sha256=existing["patch_sha256"],
                base_plan_id=existing["base_plan_id"],
                base_plan_hash=existing["base_plan_hash"],
                new_plan_id=existing["new_plan_id"],
                new_plan_hash=existing["new_plan_hash"],
                render_job_id=existing["render_job_id"],
                render_report_path=Path(existing["report_path"]),
                patch_root=Path(existing["patch_source_path"]).parent,
                duplicate=True,
            )

        base_plan_row = workspace_repo.get_plan(base_plan_id)
        package_row = workspace_repo.get_package(base_plan_row["package_id"])
        _validate_patch_binding(
            patch_payload=patch_payload,
            project_id=project_id,
            base_plan_row=base_plan_row,
            package_row=package_row,
        )

        base_plan_payload = json.loads(Path(base_plan_row["plan_path"]).read_text(encoding="utf-8"))
        normalized_base = _normalize_plan_payload(base_plan_payload, plan_version=int(base_plan_row["plan_version"] or 1))
        new_plan_id = stable_v2_id(project_id, patch_sha256, base_plan_id, "plan", length=20)
        derived_payload = _apply_patch_operations(
            base_plan=normalized_base,
            patch_payload=patch_payload,
            new_plan_id=new_plan_id,
        )
        validate_payload("edit_plan", "1.0", derived_payload)
        new_plan_hash = deterministic_plan_hash(derived_payload)
        render_job_id = stable_v2_id(project_id, new_plan_id, "job", length=20)
        patch_row_id = stable_v2_id(project_id, patch_sha256, base_plan_id, "patch", length=20)

        patch_root = project_root / "patches" / new_plan_id
        patch_root.mkdir(parents=True, exist_ok=False)
        source_copy_path = patch_root / patch_file_name
        shutil.copy2(patch_source, source_copy_path)
        patch_payload_path = patch_root / "AI_EDIT_PATCH.json"
        patch_payload_path.write_text(json.dumps(patch_payload, ensure_ascii=False, indent=2), encoding="utf-8")
        plan_dir = patch_root / "plans"
        plan_dir.mkdir(parents=True, exist_ok=True)
        derived_plan_path = plan_dir / f"{new_plan_id}.json"
        derived_plan_path.write_text(json.dumps(derived_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        backend = FFmpegBackend(project_root=Path(__file__).resolve().parents[3])
        load_and_validate_preview_plan(derived_plan_path, Path(package_row["extracted_root"]), backend)

        report_path = project_root / "renders" / render_job_id / "render_report.json"
        report = build_render_report_stub(
            project_id=project_id,
            package_id=package_row["package_id"],
            handoff_id=package_row["handoff_id"],
            handoff_sha256=package_row["handoff_sha256"],
            edit_plan_id=new_plan_id,
            render_job_id=render_job_id,
            plan_hash=new_plan_hash,
            output_directory=report_path.parent,
        )

        connection.execute("BEGIN")
        try:
            workspace_repo.insert_plan(
                edit_plan_id=new_plan_id,
                project_id=project_id,
                package_id=package_row["package_id"],
                handoff_id=package_row["handoff_id"],
                schema_version=str(derived_payload["schema_version"]),
                plan_sha256=compute_sha256(derived_plan_path),
                plan_hash=new_plan_hash,
                plan_path=derived_plan_path,
                plan_version=int(base_plan_row["plan_version"] or 1) + 1,
                parent_plan_id=base_plan_id,
                patch_id=str(patch_payload["patch_id"]),
                base_plan_hash=str(patch_payload["base_plan_hash"]),
            )
            workspace_repo.insert_patch(
                patch_row_id=patch_row_id,
                patch_id=str(patch_payload["patch_id"]),
                project_id=project_id,
                package_id=package_row["package_id"],
                handoff_id=package_row["handoff_id"],
                patch_sha256=patch_sha256,
                base_plan_id=base_plan_id,
                base_plan_hash=str(patch_payload["base_plan_hash"]),
                new_plan_id=new_plan_id,
                new_plan_hash=new_plan_hash,
                patch_source_path=source_copy_path,
                patch_payload_path=patch_payload_path,
                status="applied",
            )
            queue_repo.enqueue(
                RenderQueueItem(
                    render_job_id=render_job_id,
                    project_id=project_id,
                    package_id=package_row["package_id"],
                    edit_plan_id=new_plan_id,
                    status=QueueItemStatus.PENDING,
                )
            )
            write_render_report_stub(report, report_path)
            queue_repo.insert_render_output(
                output_id=stable_v2_id(render_job_id, "report", length=20),
                render_job_id=render_job_id,
                report_path=report_path,
                renderer_status="not_started",
            )
            workspace_repo.add_event(
                project_id=project_id,
                package_id=package_row["package_id"],
                render_job_id=render_job_id,
                event_type="patch_applied",
                payload={
                    "patch_id": patch_payload["patch_id"],
                    "patch_sha256": patch_sha256,
                    "base_plan_id": base_plan_id,
                    "new_plan_id": new_plan_id,
                    "new_plan_hash": new_plan_hash,
                    "render_job_id": render_job_id,
                },
            )
            connection.commit()
        except Exception:
            connection.rollback()
            if report_path.exists():
                report_path.unlink()
            raise
        return PatchApplyResult(
            project_id=project_id,
            package_id=package_row["package_id"],
            handoff_id=package_row["handoff_id"],
            patch_id=str(patch_payload["patch_id"]),
            patch_sha256=patch_sha256,
            base_plan_id=base_plan_id,
            base_plan_hash=str(patch_payload["base_plan_hash"]),
            new_plan_id=new_plan_id,
            new_plan_hash=new_plan_hash,
            render_job_id=render_job_id,
            render_report_path=report_path,
            patch_root=patch_root,
            duplicate=False,
        )
    except Exception:
        if patch_root and patch_root.exists():
            shutil.rmtree(patch_root, ignore_errors=True)
        if report_path and report_path.exists():
            report_path.unlink()
        raise
    finally:
        if extracted_temp_root and extracted_temp_root.exists():
            shutil.rmtree(extracted_temp_root, ignore_errors=True)
        connection.close()


def _load_patch_payload(patch_source: Path, project_root: Path, patch_sha256: str) -> tuple[dict, str, Path | None]:
    if patch_source.suffix.lower() == ".json":
        payload = json.loads(patch_source.read_text(encoding="utf-8"))
        validate_payload("edit_patch", str(payload["schema_version"]), payload)
        return payload, patch_source.name, None
    if patch_source.suffix.lower() == ".zip":
        temp_root = project_root / "cache" / "patch_imports" / patch_sha256[:20]
        if temp_root.exists():
            shutil.rmtree(temp_root, ignore_errors=True)
        safe_extract_package_zip(patch_source, temp_root)
        candidates = [temp_root / "AI_EDIT_PATCH.json", temp_root / "edit_patch.json"]
        payload_path = next((path for path in candidates if path.exists()), None)
        if payload_path is None:
            raise UnsafePackageError("Patch ZIP does not contain AI_EDIT_PATCH.json or edit_patch.json.")
        payload = json.loads(payload_path.read_text(encoding="utf-8"))
        validate_payload("edit_patch", str(payload["schema_version"]), payload)
        return payload, patch_source.name, temp_root
    raise UnsafePackageError("Patch source must be .json or .zip.")


def _validate_patch_binding(*, patch_payload: dict, project_id: str, base_plan_row: object, package_row: object) -> None:
    if str(patch_payload["project_id"]) != project_id:
        raise UnsafePackageError("Patch project_id does not match workspace project.")
    if str(patch_payload["handoff_id"]) != str(base_plan_row["handoff_id"]):
        raise UnsafePackageError("Patch handoff_id does not match base plan handoff.")
    if str(patch_payload["handoff_sha256"]) != str(package_row["handoff_sha256"]):
        raise UnsafePackageError("Patch handoff_sha256 does not match imported package handoff.")
    if str(patch_payload["base_plan_id"]) != str(base_plan_row["edit_plan_id"]):
        raise UnsafePackageError("Patch base_plan_id does not match selected base plan.")
    if str(patch_payload["base_plan_hash"]) != str(base_plan_row["plan_hash"]):
        raise UnsafePackageError("Patch base_plan_hash does not match selected base plan.")
    package_id = patch_payload.get("package_id")
    if package_id and str(package_id) != str(base_plan_row["package_id"]):
        raise UnsafePackageError("Patch package_id does not match base plan package.")


def _normalize_plan_payload(base_plan_payload: dict, *, plan_version: int) -> dict:
    payload = json.loads(json.dumps(base_plan_payload, ensure_ascii=False))
    payload["plan_version"] = int(payload.get("plan_version") or plan_version or 1)
    for index, operation in enumerate(payload.get("operations", []), start=1):
        operation.setdefault("operation_id", f"op-{index:04d}")
    return payload


def _apply_patch_operations(*, base_plan: dict, patch_payload: dict, new_plan_id: str) -> dict:
    derived = json.loads(json.dumps(base_plan, ensure_ascii=False))
    operations = [dict(item) for item in derived.get("operations", [])]
    assets = {item["asset_id"] for item in derived.get("assets", [])}
    known_ids = {item["operation_id"] for item in operations}

    for patch_op in patch_payload.get("operations", []):
        op_type = str(patch_op["op"])
        if op_type == "update_segment":
            target = _get_operation(operations, str(patch_op.get("target_operation_id") or ""))
            if "asset_id" in patch_op:
                asset_id = str(patch_op["asset_id"])
                if asset_id not in assets:
                    raise UnsafePackageError(f"Patch references unknown asset_id: {asset_id}")
                target["asset_id"] = asset_id
            if "source_in_ms" in patch_op:
                target["source_in_ms"] = int(patch_op["source_in_ms"])
            if "source_out_ms" in patch_op:
                target["source_out_ms"] = int(patch_op["source_out_ms"])
            continue
        if op_type == "remove_segment":
            index = _get_operation_index(operations, str(patch_op.get("target_operation_id") or ""))
            operations.pop(index)
            continue
        if op_type == "duplicate_segment":
            source = _get_operation(operations, str(patch_op.get("target_operation_id") or ""))
            new_operation_id = str(patch_op.get("new_operation_id") or "")
            if not new_operation_id:
                raise UnsafePackageError("duplicate_segment requires new_operation_id.")
            if new_operation_id in known_ids:
                raise UnsafePackageError(f"duplicate_segment new_operation_id already exists: {new_operation_id}")
            source_index = _get_operation_index(operations, source["operation_id"])
            duplicate = dict(source)
            duplicate["operation_id"] = new_operation_id
            operations.insert(source_index + 1, duplicate)
            known_ids.add(new_operation_id)
            continue
        if op_type == "reorder_segments":
            order = [str(value) for value in patch_op.get("order", [])]
            if not order:
                raise UnsafePackageError("reorder_segments requires a non-empty order list.")
            current_ids = [item["operation_id"] for item in operations]
            if sorted(order) != sorted(current_ids):
                raise UnsafePackageError("reorder_segments order must contain every current operation_id exactly once.")
            by_id = {item["operation_id"]: item for item in operations}
            operations = [dict(by_id[operation_id]) for operation_id in order]
            continue
        raise UnsafePackageError(f"Unsupported patch operation: {op_type}")

    if not operations:
        raise UnsafePackageError("Patch cannot remove every segment from the plan.")

    for operation in operations:
        if operation["source_in_ms"] < 0:
            raise UnsafePackageError("Patch produced a negative source_in_ms.")
        if operation["source_out_ms"] <= operation["source_in_ms"]:
            raise UnsafePackageError("Patch produced an invalid trim range.")

    derived["plan_id"] = new_plan_id
    derived["plan_version"] = int(base_plan.get("plan_version") or 1) + 1
    derived["parent_plan_id"] = str(base_plan["plan_id"])
    derived["base_plan_hash"] = str(patch_payload["base_plan_hash"])
    derived["patch_id"] = str(patch_payload["patch_id"])
    derived["created_at"] = utc_now_iso()
    derived["operations"] = operations
    return derived


def _get_operation(operations: list[dict], operation_id: str) -> dict:
    for operation in operations:
        if operation.get("operation_id") == operation_id:
            return operation
    raise UnsafePackageError(f"Patch references unknown operation_id: {operation_id}")


def _get_operation_index(operations: list[dict], operation_id: str) -> int:
    for index, operation in enumerate(operations):
        if operation.get("operation_id") == operation_id:
            return index
    raise UnsafePackageError(f"Patch references unknown operation_id: {operation_id}")
