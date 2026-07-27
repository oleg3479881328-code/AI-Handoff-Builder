from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..assets import load_active_local_registry, resolve_plan_assets_against_registry
from ..errors import UnsafePackageError
from ..packages.guards import compute_content_hash, compute_sha256
from ..packages.importer import import_edit_package
from ..plans.schema import validate_payload
from ..timeline.compiler import NormalizedTimeline, compile_normalized_timeline


@dataclass(frozen=True, slots=True)
class CompiledPackage:
    """Result of the authoritative Package Compiler pipeline.

    The Package Compiler is the ONE place where AI_EDIT_PACKAGE 3.0
    is validated, assets are resolved, and Normalized Timeline is compiled.
    No renderer parses AI_EDIT_PACKAGE independently.
    """
    imported_package: object  # ImportedPackage
    edit_plan_payload: dict
    resolved_assets: list[dict]
    normalized_timeline: NormalizedTimeline
    content_hash: str
    plan_hash: str


def compile_package(
    zip_path: Path,
    workspace: Path,
    *,
    expected_project_id: str | None = None,
    fps_num: int = 30,
    fps_den: int = 1,
) -> CompiledPackage:
    """Authoritative Package Compiler: validate → resolve → compile.

    Steps:
    1. Import and validate AI_EDIT_PACKAGE 3.0
    2. Load and validate edit_plan 3.0
    3. Resolve assets against local registry
    4. Compile Normalized Timeline 1.0
    5. Compute content hash for identity tracking
    """
    project_root = workspace.resolve()

    # Step 1: Import package (validates manifest, inventory, checksums)
    imported = import_edit_package(
        zip_path,
        project_root / "ai_packages",
        expected_project_id=expected_project_id,
        package_root=project_root / "ai_packages" / compute_sha256(zip_path)[:16],
    )

    if imported.schema_version != "3.0":
        raise UnsafePackageError(
            f"Package Compiler requires AI_EDIT_PACKAGE 3.0, got {imported.schema_version}"
        )

    # Step 2: Load and validate edit_plan 3.0
    manifest = json.loads(
        (imported.extracted_root / "ai_edit_package.json").read_text(encoding="utf-8")
    )
    if not manifest.get("plans"):
        raise UnsafePackageError("AI edit package 3.0 must declare at least one plan.")

    active_plan = manifest["plans"][0]
    plan_path = (imported.extracted_root / str(active_plan["path"])).resolve()
    if imported.extracted_root not in plan_path.parents:
        raise UnsafePackageError("Plan path escapes package root.")

    edit_plan_payload = json.loads(plan_path.read_text(encoding="utf-8"))
    plan_version = str(edit_plan_payload["schema_version"])
    if plan_version != "3.0":
        raise UnsafePackageError(
            f"Package Compiler requires edit_plan 3.0, got {plan_version}"
        )

    validate_payload("edit_plan", "3.0", edit_plan_payload)

    # Verify identity chain
    if str(edit_plan_payload["project_id"]) != imported.project_id:
        raise UnsafePackageError("Edit plan project_id does not match package.")
    if str(edit_plan_payload["handoff_id"]) != imported.handoff_id:
        raise UnsafePackageError("Edit plan handoff_id does not match package.")
    if str(edit_plan_payload["handoff_sha256"]) != imported.handoff_sha256:
        raise UnsafePackageError("Edit plan handoff_sha256 does not match package.")

    # Step 3: Resolve assets against local registry
    registry_payload = load_active_local_registry(project_root)
    resolution_report = resolve_plan_assets_against_registry(
        list(edit_plan_payload["assets"]),
        registry_payload,
        require_declared_integrity=True,
    )
    resolved_assets = resolution_report["assets"]

    # Step 4: Compile Normalized Timeline
    normalized_timeline = compile_normalized_timeline(
        edit_plan_payload,
        resolved_assets,
        fps_num=fps_num,
        fps_den=fps_den,
    )

    # Step 5: Compute content hash
    content_hash = compute_content_hash(manifest)

    plan_hash = normalized_timeline.timeline_hash

    return CompiledPackage(
        imported_package=imported,
        edit_plan_payload=edit_plan_payload,
        resolved_assets=resolved_assets,
        normalized_timeline=normalized_timeline,
        content_hash=content_hash,
        plan_hash=plan_hash,
    )
