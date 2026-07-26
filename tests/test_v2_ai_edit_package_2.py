from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from handoff_builder.utils import file_sha256
from handoff_builder.v2.errors import UnsafePackageError
from handoff_builder.v2.services.import_service import import_package_into_workspace
from handoff_builder.v2.services.render_service import render_job
from handoff_builder.v2.workspace import init_project_workspace


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_photo(path: Path, *, color: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1600, 1200), color=color).save(path, "JPEG")


def _write_plan_only_package(
    zip_path: Path,
    assets: list[dict],
    operations: list[dict],
    *,
    schema_version: str = "2.0",
    project_id: str = "proj-1",
    handoff_id: str = "handoff-1",
    include_media_payload: bool = False,
) -> None:
    plan = {
        "schema_version": schema_version,
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "plan_id": "plan-photo-1",
        "created_at": "2026-07-25T12:00:00Z",
        "mode": "preview",
        "output": {"width": 1080, "height": 1920, "fps": 30, "audio": False},
        "assets": assets,
        "operations": operations,
    }
    plan_bytes = json.dumps(plan, ensure_ascii=False).encode("utf-8")
    plan_path = zip_path.parent / "plan-photo-1.json"
    plan_path.write_bytes(plan_bytes)
    plan_sha = file_sha256(plan_path)
    plan_path.unlink()
    manifest = {
        "schema_version": schema_version,
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "created_at": "2026-07-25T12:00:00Z",
        "plans": [{"plan_id": "plan-photo-1", "path": "plans/plan-photo-1.json", "sha256": plan_sha}],
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ai_edit_package.json", json.dumps(manifest))
        archive.writestr("plans/plan-photo-1.json", plan_bytes)
        if include_media_payload:
            archive.writestr("assets/forbidden.jpg", b"forbidden")


def _write_registry(path: Path, rows: list[dict]) -> None:
    path.write_text(json.dumps({"schema_version": "1.0", "assets": rows}, ensure_ascii=False, indent=2), encoding="utf-8")


def _asset_entry(source_path: Path, *, asset_id: str) -> tuple[dict, dict]:
    sha256 = file_sha256(source_path)
    size_bytes = source_path.stat().st_size
    return (
        {
            "asset_id": asset_id,
            "media_type": "photo",
            "sha256": sha256,
            "size_bytes": size_bytes,
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
            "capture_time": "2026-07-25T12:00:00Z",
            "analysis_preview_paths": {"analysis_copy": f"photo_analysis_copies/{source_path.stem}.jpg"},
        },
    )


def _asset_entry_handoff_only(source_path: Path, *, asset_id: str) -> tuple[dict, dict]:
    _asset_20, registry_row = _asset_entry(source_path, asset_id=asset_id)
    return (
        {
            "asset_id": asset_id,
            "media_type": "photo",
            "original_name": source_path.name,
        },
        registry_row,
    )


def test_import_package_2_uses_neighbor_registry_and_writes_resolution_report(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="red")
    asset, registry_row = _asset_entry(photo, asset_id="asset-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(
        package_zip,
        [asset],
        [
            {"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000},
            {"op": "text_overlay", "asset_id": "asset-1", "text": "Фото 1", "position": "bottom_center"},
        ],
    )
    _write_registry(tmp_path / "local_asset_registry.json", [registry_row])

    result = import_package_into_workspace(package_zip, workspace)

    active_registry = workspace / "analysis" / "local_asset_registry.json"
    resolution_report = workspace / "renders" / result.render_job_id / "asset_resolution.json"
    assert active_registry.exists()
    assert resolution_report.exists()
    payload = json.loads(resolution_report.read_text(encoding="utf-8"))
    assert payload["resolved_asset_count"] == 1
    assert payload["assets"][0]["asset_id"] == "asset-1"


def test_import_package_21_uses_active_workspace_registry_without_sidecar(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="green")
    asset, registry_row = _asset_entry_handoff_only(photo, asset_id="asset-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(
        package_zip,
        [asset],
        [
            {"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000},
            {"op": "text_overlay", "asset_id": "asset-1", "text": "Фото 1", "position": "bottom_center"},
        ],
        schema_version="2.1",
    )
    _write_registry(workspace / "analysis" / "local_asset_registry.json", [registry_row])

    result = import_package_into_workspace(package_zip, workspace)

    resolution_report = workspace / "renders" / result.render_job_id / "asset_resolution.json"
    assert resolution_report.exists()
    payload = json.loads(resolution_report.read_text(encoding="utf-8"))
    assert payload["resolved_asset_count"] == 1
    assert payload["assets"][0]["asset_id"] == "asset-1"
    assert payload["assets"][0]["sha256"] == registry_row["sha256"]
    assert payload["assets"][0]["size_bytes"] == registry_row["size_bytes"]


def test_import_package_2_rejects_missing_registry(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="red")
    asset, _registry_row = _asset_entry(photo, asset_id="asset-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(package_zip, [asset], [{"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000}])

    with pytest.raises(UnsafePackageError, match="Active local_asset_registry.json is missing"):
        import_package_into_workspace(package_zip, workspace)


def test_import_package_2_rejects_checksum_mismatch(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="red")
    asset, registry_row = _asset_entry(photo, asset_id="asset-1")
    asset["sha256"] = "b" * 64
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(package_zip, [asset], [{"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000}])
    _write_registry(tmp_path / "local_asset_registry.json", [registry_row])

    with pytest.raises(UnsafePackageError, match="checksum mismatch"):
        import_package_into_workspace(package_zip, workspace)


def test_import_package_2_rejects_ambiguous_asset_id(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="red")
    asset, registry_row = _asset_entry(photo, asset_id="asset-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(package_zip, [asset], [{"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000}])
    _write_registry(tmp_path / "local_asset_registry.json", [registry_row, dict(registry_row)])

    with pytest.raises(UnsafePackageError, match="ambiguous asset_id"):
        import_package_into_workspace(package_zip, workspace)


def test_import_package_2_rejects_media_payloads(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="red")
    asset, registry_row = _asset_entry(photo, asset_id="asset-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(
        package_zip,
        [asset],
        [{"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000}],
        include_media_payload=True,
    )
    _write_registry(tmp_path / "local_asset_registry.json", [registry_row])

    with pytest.raises(UnsafePackageError, match="must not contain media payloads"):
        import_package_into_workspace(package_zip, workspace)


def test_import_package_21_rejects_missing_active_registry(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="red")
    asset, _registry_row = _asset_entry_handoff_only(photo, asset_id="asset-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(
        package_zip,
        [asset],
        [{"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000}],
        schema_version="2.1",
    )

    with pytest.raises(UnsafePackageError, match="Active local_asset_registry.json is missing"):
        import_package_into_workspace(package_zip, workspace)


def test_import_package_21_rejects_checksum_mismatch_from_registry(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="purple")
    asset, registry_row = _asset_entry_handoff_only(photo, asset_id="asset-1")
    registry_row["sha256"] = "b" * 64
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(
        package_zip,
        [asset],
        [{"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000}],
        schema_version="2.1",
    )
    _write_registry(workspace / "analysis" / "local_asset_registry.json", [registry_row])

    with pytest.raises(UnsafePackageError, match="checksum mismatch"):
        import_package_into_workspace(package_zip, workspace)


def test_import_package_21_rejects_size_mismatch_from_registry(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo = tmp_path / "originals" / "photo-1.jpg"
    _make_photo(photo, color="orange")
    asset, registry_row = _asset_entry_handoff_only(photo, asset_id="asset-1")
    registry_row["size_bytes"] = registry_row["size_bytes"] + 1
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(
        package_zip,
        [asset],
        [{"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000}],
        schema_version="2.1",
    )
    _write_registry(workspace / "analysis" / "local_asset_registry.json", [registry_row])

    with pytest.raises(UnsafePackageError, match="size mismatch"):
        import_package_into_workspace(package_zip, workspace)


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_render_job_2_photo_slideshow(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo1 = tmp_path / "originals" / "photo-1.jpg"
    photo2 = tmp_path / "originals" / "photo-2.jpg"
    _make_photo(photo1, color="red")
    _make_photo(photo2, color="blue")
    asset1, registry1 = _asset_entry(photo1, asset_id="asset-1")
    asset2, registry2 = _asset_entry(photo2, asset_id="asset-2")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(
        package_zip,
        [asset1, asset2],
        [
            {"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000},
            {"op": "text_overlay", "asset_id": "asset-1", "text": "Фото 1", "position": "bottom_center"},
            {"op": "image_hold", "asset_id": "asset-2", "duration_ms": 1000},
            {"op": "text_overlay", "asset_id": "asset-2", "text": "Фото 2", "position": "bottom_center"},
        ],
    )
    _write_registry(tmp_path / "local_asset_registry.json", [registry1, registry2])

    result = import_package_into_workspace(package_zip, workspace)
    rendered = render_job(workspace, result.render_job_id)

    report = json.loads((Path(rendered["output_directory"]) / "render_report.json").read_text(encoding="utf-8"))
    assert rendered["status"] == "completed"
    assert report["outputs"][0]["width"] == 1080
    assert report["outputs"][0]["height"] == 1920
    assert report["outputs"][0]["audio_present"] == 0


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_render_job_21_photo_slideshow(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    photo1 = tmp_path / "originals" / "photo-1.jpg"
    photo2 = tmp_path / "originals" / "photo-2.jpg"
    _make_photo(photo1, color="red")
    _make_photo(photo2, color="blue")
    asset1, registry1 = _asset_entry_handoff_only(photo1, asset_id="asset-1")
    asset2, registry2 = _asset_entry_handoff_only(photo2, asset_id="asset-2")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_plan_only_package(
        package_zip,
        [asset1, asset2],
        [
            {"op": "image_hold", "asset_id": "asset-1", "duration_ms": 1000},
            {"op": "text_overlay", "asset_id": "asset-1", "text": "Фото 1", "position": "bottom_center"},
            {"op": "image_hold", "asset_id": "asset-2", "duration_ms": 1000},
            {"op": "text_overlay", "asset_id": "asset-2", "text": "Фото 2", "position": "bottom_center"},
        ],
        schema_version="2.1",
    )
    _write_registry(workspace / "analysis" / "local_asset_registry.json", [registry1, registry2])

    result = import_package_into_workspace(package_zip, workspace)
    rendered = render_job(workspace, result.render_job_id)

    report = json.loads((Path(rendered["output_directory"]) / "render_report.json").read_text(encoding="utf-8"))
    resolution = json.loads((Path(rendered["output_directory"]) / "asset_resolution.json").read_text(encoding="utf-8"))
    assert rendered["status"] == "completed"
    assert resolution["resolved_asset_count"] == 2
    assert report["outputs"][0]["width"] == 1080
    assert report["outputs"][0]["height"] == 1920
    assert report["outputs"][0]["audio_present"] == 0
