from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from PIL import Image

from handoff_builder.utils import file_sha256
from handoff_builder.v2.hyperframes_preview import (
    build_preview_project,
    preview_project_dir,
    resolve_active_preview_plan_id,
)
from handoff_builder.v2.services.import_service import import_package_into_workspace
from handoff_builder.v2.services.query_service import show_plan
from handoff_builder.v2.workspace import init_project_workspace


def _make_photo(path: Path, *, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1600, 1200), color=color).save(path, "JPEG")


def _write_registry(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema_version": "1.0", "assets": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def _asset_entry_handoff_only(source_path: Path, *, asset_id: str) -> tuple[dict, dict]:
    sha256 = file_sha256(source_path)
    size_bytes = source_path.stat().st_size
    return (
        {
            "asset_id": asset_id,
            "media_type": "photo",
            "original_name": source_path.name,
        },
        {
            "asset_id": asset_id,
            "source_path": str(source_path.resolve()),
            "relative_source_path": source_path.name,
            "original_name": source_path.name,
            "media_type": "photo",
            "size_bytes": size_bytes,
            "sha256": sha256,
            "capture_time": "2026-07-26T12:00:00Z",
            "analysis_preview_paths": {"analysis_copy": f"photo_analysis_copies/{source_path.stem}.jpg"},
        },
    )


def _write_photo_package(
    zip_path: Path,
    *,
    project_id: str,
    handoff_id: str,
    plan_id: str,
    overlays: list[str],
    colors: list[str],
) -> None:
    assets = []
    operations = []
    registry_rows = []
    for index, color in enumerate(colors, start=1):
        source = zip_path.parent / "originals" / f"{plan_id}_{index}.jpg"
        _make_photo(source, color=color)
        asset, registry_row = _asset_entry_handoff_only(source, asset_id=f"asset-{index}")
        assets.append(asset)
        registry_rows.append(registry_row)
        operations.append({"op": "image_hold", "asset_id": asset["asset_id"], "duration_ms": 1000})
        operations.append({"op": "text_overlay", "asset_id": asset["asset_id"], "text": overlays[index - 1], "position": "bottom_center"})
    _write_registry(zip_path.parent / "registry.json", registry_rows)

    plan = {
        "schema_version": "2.1",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "plan_id": plan_id,
        "created_at": "2026-07-26T12:00:00Z",
        "mode": "preview",
        "output": {"width": 1080, "height": 1920, "fps": 30, "audio": False},
        "assets": assets,
        "operations": operations,
    }
    plan_bytes = json.dumps(plan, ensure_ascii=False).encode("utf-8")
    plan_path = zip_path.parent / f"{plan_id}.json"
    plan_path.write_bytes(plan_bytes)
    plan_sha = file_sha256(plan_path)
    plan_path.unlink()
    manifest = {
        "schema_version": "2.1",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "created_at": "2026-07-26T12:00:00Z",
        "plans": [{"plan_id": plan_id, "path": f"plans/{plan_id}.json", "sha256": plan_sha}],
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ai_edit_package.json", json.dumps(manifest))
        archive.writestr(f"plans/{plan_id}.json", plan_bytes)


def test_preview_bridge_uses_latest_plan_until_explicit_selection(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "samarkand-project")
    snapshot_a = {
        "plans": [{"edit_plan_id": "plan-marusia"}],
        "latest_plan": {"edit_plan_id": "plan-marusia"},
    }
    snapshot_b = {
        "plans": [{"edit_plan_id": "plan-marusia"}, {"edit_plan_id": "plan-samarkand"}],
        "latest_plan": {"edit_plan_id": "plan-samarkand"},
    }

    assert resolve_active_preview_plan_id(snapshot_a, None) == "plan-marusia"
    assert resolve_active_preview_plan_id(snapshot_b, None) == "plan-samarkand"
    assert resolve_active_preview_plan_id(snapshot_b, "plan-marusia") == "plan-marusia"
    assert resolve_active_preview_plan_id(snapshot_b, "missing") == "plan-samarkand"


def test_build_preview_project_replaces_old_identity_with_new_plan(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "samarkand-project")

    marusia_zip = tmp_path / "Marusia_AI_EDIT_PACKAGE.zip"
    _write_photo_package(
        marusia_zip,
        project_id="samarkand-project",
        handoff_id="handoff-marusia",
        plan_id="plan-marusia",
        overlays=["Marusia 1", "Marusia 2"],
        colors=["red", "blue"],
    )
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    _write_registry(workspace / "analysis" / "local_asset_registry.json", registry["assets"])
    marusia_import = import_package_into_workspace(marusia_zip, workspace)
    marusia_plan = show_plan(workspace, marusia_import.edit_plan_id)
    marusia_preview = build_preview_project(workspace, marusia_plan)

    samarkand_zip = tmp_path / "Samarkand_AI_EDIT_PACKAGE.zip"
    _write_photo_package(
        samarkand_zip,
        project_id="samarkand-project",
        handoff_id="handoff-samarkand",
        plan_id="plan-samarkand",
        overlays=["Samarkand 1", "Samarkand 2"],
        colors=["green", "purple"],
    )
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    _write_registry(workspace / "analysis" / "local_asset_registry.json", registry["assets"])
    samarkand_import = import_package_into_workspace(samarkand_zip, workspace)
    samarkand_plan = show_plan(workspace, samarkand_import.edit_plan_id)
    samarkand_preview = build_preview_project(workspace, samarkand_plan)

    assert marusia_preview.project_dir != samarkand_preview.project_dir
    assert samarkand_preview.project_dir == preview_project_dir(workspace, samarkand_plan)
    html = (samarkand_preview.project_dir / "index.html").read_text(encoding="utf-8")
    assert "Samarkand 1" in html
    assert "Samarkand 2" in html
    assert "Marusia 1" not in html
    assert "Marusia 2" not in html
    assert "Eyebrow" not in html
    assert "Progress Bar" not in html
    identity = json.loads((samarkand_preview.project_dir / "preview_identity.json").read_text(encoding="utf-8"))
    assert identity["plan_id"] == samarkand_plan["metadata"]["edit_plan_id"]
    assert identity["plan_hash"] == samarkand_plan["metadata"]["plan_hash"]
    assert samarkand_preview.asset_count == 2
    assert samarkand_preview.operation_count == 4


def test_build_preview_project_is_stable_after_restart_like_reload(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "samarkand-project")
    package_zip = tmp_path / "Samarkand_AI_EDIT_PACKAGE.zip"
    _write_photo_package(
        package_zip,
        project_id="samarkand-project",
        handoff_id="handoff-samarkand",
        plan_id="plan-samarkand",
        overlays=["Samarkand 1", "Samarkand 2"],
        colors=["green", "purple"],
    )
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))
    _write_registry(workspace / "analysis" / "local_asset_registry.json", registry["assets"])
    imported = import_package_into_workspace(package_zip, workspace)
    plan = show_plan(workspace, imported.edit_plan_id)

    first = build_preview_project(workspace, plan)
    second = build_preview_project(workspace, plan)

    assert first.project_dir == second.project_dir
    assert json.loads((second.project_dir / "preview_identity.json").read_text(encoding="utf-8"))["plan_id"] == "plan-samarkand"
