from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from handoff_builder.v2.errors import (
    ChecksumMismatchError,
    ProjectMismatchError,
    UnsupportedSchemaVersionError,
    UnsafePackageError,
)
from handoff_builder.v2.packages.importer import import_edit_package
from handoff_builder.v2.packages.guards import safe_extract_package_zip
from handoff_builder.v2.plans.schema import deterministic_plan_hash, load_schema, schema_dispatch


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _build_package_zip(
    zip_path: Path,
    *,
    project_id: str = "project-1",
    handoff_id: str = "handoff-1",
    manifest_sha: str = "a" * 64,
    plan_bytes: bytes = (
        b'{"schema_version":"1.0","project_id":"project-1","handoff_id":"handoff-1",'
        b'"handoff_sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
        b'"plan_id":"plan-1","created_at":"2026-07-20T12:00:00Z","mode":"preview",'
        b'"assets":[{"asset_id":"asset-1","path":"assets/source.mp4","media_type":"video"}],'
        b'"operations":[{"op":"video_segment","asset_id":"asset-1","source_in_ms":0,"source_out_ms":1000}]}'
    ),
    declared_plan_sha: str | None = None,
) -> None:
    declared_plan_sha = declared_plan_sha or _sha256(plan_bytes)
    asset_bytes = b"fake-video-placeholder"
    asset_sha = _sha256(asset_bytes)
    manifest = {
        "schema_version": "1.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": manifest_sha,
        "created_at": "2026-07-20T12:00:00Z",
        "package_files": [
            {
                "path": "plans/plan-1.json",
                "sha256": declared_plan_sha,
                "size_bytes": len(plan_bytes),
            },
            {
                "path": "assets/source.mp4",
                "sha256": asset_sha,
                "size_bytes": len(asset_bytes),
            },
        ],
        "plans": [
            {
                "plan_id": "plan-1",
                "path": "plans/plan-1.json",
                "sha256": declared_plan_sha,
            }
        ]
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ai_edit_package.json", json.dumps(manifest))
        archive.writestr("plans/plan-1.json", plan_bytes)
        archive.writestr("assets/source.mp4", asset_bytes)


def test_schema_loads():
    schema = load_schema("ai_edit_package", "1.0")
    assert schema["title"] == "AI Edit Package"
    assert schema["properties"]["schema_version"]["const"] == "1.0"


def test_supported_schema_dispatch():
    path = schema_dispatch("edit_plan", "1.0")
    assert path.name == "1.0.json"
    assert path.exists()


def test_unsupported_version_rejection():
    with pytest.raises(UnsupportedSchemaVersionError):
        schema_dispatch("edit_plan", "9.9")


def test_project_mismatch(tmp_path: Path):
    archive = tmp_path / "package.zip"
    _build_package_zip(archive, project_id="project-a")
    with pytest.raises(ProjectMismatchError):
        import_edit_package(archive, tmp_path / "stage", expected_project_id="project-b")


def test_checksum_mismatch(tmp_path: Path):
    archive = tmp_path / "package.zip"
    _build_package_zip(archive, declared_plan_sha="b" * 64)
    with pytest.raises(ChecksumMismatchError):
        import_edit_package(archive, tmp_path / "stage", expected_project_id="project-1")


def test_zip_traversal_rejection_for_v2_package_guard(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError):
        safe_extract_package_zip(archive, tmp_path / "out")


def test_symlink_escape_rejection(tmp_path: Path):
    archive = tmp_path / "symlink.zip"
    info = zipfile.ZipInfo("plans/link.json")
    info.create_system = 3
    info.external_attr = 0o120777 << 16
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(info, "target")
    with pytest.raises(UnsafePackageError):
        safe_extract_package_zip(archive, tmp_path / "out")


def test_deterministic_plan_hash():
    left = {"operations": [{"op": "trim", "params": {"start": 1, "end": 3}}], "plan_id": "p1"}
    right = {"plan_id": "p1", "operations": [{"params": {"end": 3, "start": 1}, "op": "trim"}]}
    assert deterministic_plan_hash(left) == deterministic_plan_hash(right)


def test_v2_modules_import_cleanly():
    import handoff_builder.v2 as v2

    assert hasattr(v2, "import_edit_package")
    assert hasattr(v2, "deterministic_plan_hash")


def test_import_edit_package_success(tmp_path: Path):
    archive = tmp_path / "ok.zip"
    _build_package_zip(archive)
    result = import_edit_package(archive, tmp_path / "stage", expected_project_id="project-1")
    assert result.project_id == "project-1"
    assert result.plan_ids == ("plan-1",)
    assert result.files[0].path == "plans/plan-1.json"
