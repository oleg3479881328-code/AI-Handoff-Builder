from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from handoff_builder import cli
from handoff_builder.v2.errors import UnsafePackageError
from handoff_builder.v2.packages.guards import compute_sha256
from handoff_builder.v2.services import (
    apply_patch_in_workspace,
    import_package_into_workspace,
    list_plans,
    render_job,
    show_plan,
)
from handoff_builder.v2.storage.db import connect_workspace_db
from handoff_builder.v2.workspace import init_project_workspace


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_video(path: Path, *, duration_seconds: float, with_audio: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if with_audio:
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=30",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=660:sample_rate=48000",
            "-t",
            f"{duration_seconds:.2f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(path),
        ]
    else:
        command = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=1280x720:rate=30",
            "-t",
            f"{duration_seconds:.2f}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
    import subprocess

    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _write_render_package(zip_path: Path, *, project_id: str = "proj-1", handoff_id: str = "handoff-1") -> dict:
    temp_dir = zip_path.parent / "build_pkg"
    temp_dir.mkdir(parents=True, exist_ok=True)
    asset1 = temp_dir / "seg1.mp4"
    asset2 = temp_dir / "seg2.mp4"
    _make_video(asset1, duration_seconds=1.6, with_audio=True)
    _make_video(asset2, duration_seconds=1.3, with_audio=False)
    asset1_bytes = asset1.read_bytes()
    asset2_bytes = asset2.read_bytes()
    plan = {
        "schema_version": "1.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "plan_id": "plan-1",
        "created_at": "2026-07-20T12:00:00Z",
        "mode": "preview",
        "assets": [
            {"asset_id": "asset-1", "path": "assets/seg1.mp4", "media_type": "video"},
            {"asset_id": "asset-2", "path": "assets/seg2.mp4", "media_type": "video"},
        ],
        "operations": [
            {
                "op": "video_segment",
                "asset_id": "asset-1",
                "source_in_ms": 0,
                "source_out_ms": 700,
            },
            {
                "op": "video_segment",
                "asset_id": "asset-2",
                "source_in_ms": 100,
                "source_out_ms": 700,
            },
        ],
    }
    plan_bytes = json.dumps(plan, ensure_ascii=False).encode("utf-8")
    manifest = {
        "schema_version": "1.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "created_at": "2026-07-20T12:00:00Z",
        "package_files": [
            {"path": "plans/plan-1.json", "sha256": compute_sha256(_write_temp(zip_path.parent / "plan.tmp", plan_bytes)), "size_bytes": len(plan_bytes)},
            {"path": "assets/seg1.mp4", "sha256": compute_sha256(_write_temp(zip_path.parent / "a1.tmp", asset1_bytes)), "size_bytes": len(asset1_bytes)},
            {"path": "assets/seg2.mp4", "sha256": compute_sha256(_write_temp(zip_path.parent / "a2.tmp", asset2_bytes)), "size_bytes": len(asset2_bytes)},
        ],
        "plans": [{"plan_id": "plan-1", "path": "plans/plan-1.json", "sha256": compute_sha256(zip_path.parent / "plan.tmp")}],
    }
    for temp_name in ("plan.tmp", "a1.tmp", "a2.tmp"):
        temp_file = zip_path.parent / temp_name
        if temp_file.exists():
            temp_file.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ai_edit_package.json", json.dumps(manifest))
        archive.writestr("plans/plan-1.json", plan_bytes)
        archive.writestr("assets/seg1.mp4", asset1_bytes)
        archive.writestr("assets/seg2.mp4", asset2_bytes)
    return plan


def _write_temp(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _write_patch(path: Path, payload: dict) -> Path:
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("AI_EDIT_PATCH.json", json.dumps(payload, ensure_ascii=False))
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _base_patch(*, project_id: str, handoff_id: str, base_plan_id: str, base_plan_hash: str, package_id: str | None = None) -> dict:
    payload = {
        "schema_version": "1.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "patch_id": "patch-1",
        "base_plan_id": base_plan_id,
        "base_plan_hash": base_plan_hash,
        "created_at": "2026-07-20T12:30:00Z",
        "operations": [],
    }
    if package_id:
        payload["package_id"] = package_id
    return payload


def _prepare_workspace(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "Рабочая папка & Oleg's", "proj-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_render_package(package_zip)
    imported = import_package_into_workspace(package_zip, workspace)
    return workspace, imported


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_apply_patch_creates_immutable_plan_and_new_render_job(tmp_path: Path):
    workspace, imported = _prepare_workspace(tmp_path)
    patch = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    patch["operations"] = [
        {"op": "duplicate_segment", "target_operation_id": "op-0001", "new_operation_id": "op-0003"},
        {"op": "update_segment", "target_operation_id": "op-0003", "source_in_ms": 200, "source_out_ms": 650},
        {"op": "reorder_segments", "order": ["op-0002", "op-0003", "op-0001"]},
    ]
    patch_path = _write_patch(tmp_path / "AI_EDIT_PATCH.json", patch)

    result = apply_patch_in_workspace(patch_path, workspace)
    assert result.base_plan_id == imported.edit_plan_id
    assert result.new_plan_id != imported.edit_plan_id
    assert result.new_plan_hash != imported.plan_hash

    plans = list_plans(workspace)
    assert len(plans) == 2
    derived = next(item for item in plans if item["edit_plan_id"] == result.new_plan_id)
    assert derived["parent_plan_id"] == imported.edit_plan_id
    assert derived["plan_version"] == 2
    payload = show_plan(workspace, result.new_plan_id)["payload"]
    assert [item["operation_id"] for item in payload["operations"]] == ["op-0002", "op-0003", "op-0001"]
    assert payload["operations"][1]["source_in_ms"] == 200
    assert payload["operations"][1]["source_out_ms"] == 650


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_patch_rerender_preserves_old_output_and_creates_new_output(tmp_path: Path):
    workspace, imported = _prepare_workspace(tmp_path)
    first = render_job(workspace, imported.render_job_id)
    first_reel = Path(first["output_directory"]) / "reel.mp4"
    assert first_reel.exists()

    patch = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    patch["operations"] = [
        {"op": "update_segment", "target_operation_id": "op-0001", "source_in_ms": 100, "source_out_ms": 600},
        {"op": "reorder_segments", "order": ["op-0002", "op-0001"]},
    ]
    patch_path = _write_patch(tmp_path / "AI_EDIT_PATCH.zip", patch)
    applied = apply_patch_in_workspace(patch_path, workspace)
    second = render_job(workspace, applied.render_job_id)
    second_reel = Path(second["output_directory"]) / "reel.mp4"

    assert second_reel.exists()
    assert first_reel.exists()
    assert first_reel != second_reel
    assert applied.render_job_id != imported.render_job_id


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_duplicate_patch_idempotency(tmp_path: Path):
    workspace, imported = _prepare_workspace(tmp_path)
    patch = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    patch["operations"] = [{"op": "remove_segment", "target_operation_id": "op-0002"}]
    patch_path = _write_patch(tmp_path / "AI_EDIT_PATCH.json", patch)

    first = apply_patch_in_workspace(patch_path, workspace)
    second = apply_patch_in_workspace(patch_path, workspace)

    assert second.duplicate is True
    assert first.new_plan_id == second.new_plan_id
    assert first.render_job_id == second.render_job_id


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_patch_rejects_wrong_project_and_stale_hash_without_persistence(tmp_path: Path):
    workspace, imported = _prepare_workspace(tmp_path)
    wrong_project = _base_patch(
        project_id="wrong-project",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    wrong_project["operations"] = [{"op": "remove_segment", "target_operation_id": "op-0002"}]
    wrong_project_path = _write_patch(tmp_path / "wrong_project_patch.json", wrong_project)
    with pytest.raises(UnsafePackageError):
        apply_patch_in_workspace(wrong_project_path, workspace)

    stale = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash="b" * 64,
        package_id=imported.package_id,
    )
    stale["operations"] = [{"op": "remove_segment", "target_operation_id": "op-0002"}]
    stale_path = _write_patch(tmp_path / "stale_patch.json", stale)
    with pytest.raises(UnsafePackageError):
        apply_patch_in_workspace(stale_path, workspace)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        plan_count = connection.execute("SELECT COUNT(*) FROM edit_plans").fetchone()[0]
        patch_count = connection.execute("SELECT COUNT(*) FROM edit_patches").fetchone()[0]
        job_count = connection.execute("SELECT COUNT(*) FROM render_jobs").fetchone()[0]
    finally:
        connection.close()
    assert plan_count == 1
    assert patch_count == 0
    assert job_count == 1


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_patch_rejects_unsupported_missing_asset_invalid_trim_and_raw_field(tmp_path: Path):
    workspace, imported = _prepare_workspace(tmp_path)

    unsupported = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    unsupported["operations"] = [{"op": "explode_segment", "target_operation_id": "op-0001"}]
    unsupported_path = _write_patch(tmp_path / "unsupported_patch.json", unsupported)
    with pytest.raises(ValueError):
        apply_patch_in_workspace(unsupported_path, workspace)

    missing_asset = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    missing_asset["operations"] = [{"op": "update_segment", "target_operation_id": "op-0001", "asset_id": "asset-404"}]
    missing_asset_path = _write_patch(tmp_path / "missing_asset_patch.json", missing_asset)
    with pytest.raises(UnsafePackageError):
        apply_patch_in_workspace(missing_asset_path, workspace)

    invalid_trim = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    invalid_trim["operations"] = [{"op": "update_segment", "target_operation_id": "op-0001", "source_in_ms": 900, "source_out_ms": 200}]
    invalid_trim_path = _write_patch(tmp_path / "invalid_trim_patch.json", invalid_trim)
    with pytest.raises(UnsafePackageError):
        apply_patch_in_workspace(invalid_trim_path, workspace)

    raw_field = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    raw_field["operations"] = [{"op": "update_segment", "target_operation_id": "op-0001", "ffmpeg_filter": "scale=1:1"}]
    raw_field_path = _write_patch(tmp_path / "raw_field_patch.json", raw_field)
    with pytest.raises(ValueError):
        apply_patch_in_workspace(raw_field_path, workspace)


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_patch_transaction_rollback_on_enqueue_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace, imported = _prepare_workspace(tmp_path)
    patch = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=imported.edit_plan_id,
        base_plan_hash=imported.plan_hash,
        package_id=imported.package_id,
    )
    patch["operations"] = [{"op": "remove_segment", "target_operation_id": "op-0002"}]
    patch_path = _write_patch(tmp_path / "AI_EDIT_PATCH.json", patch)

    from handoff_builder.v2.storage.repositories import SqliteRenderQueueRepository

    original = SqliteRenderQueueRepository.enqueue

    def boom(self, item):
        raise RuntimeError("queue insert failed")

    monkeypatch.setattr(SqliteRenderQueueRepository, "enqueue", boom)
    with pytest.raises(RuntimeError):
        apply_patch_in_workspace(patch_path, workspace)
    monkeypatch.setattr(SqliteRenderQueueRepository, "enqueue", original)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        plan_count = connection.execute("SELECT COUNT(*) FROM edit_plans").fetchone()[0]
        patch_count = connection.execute("SELECT COUNT(*) FROM edit_patches").fetchone()[0]
        job_count = connection.execute("SELECT COUNT(*) FROM render_jobs").fetchone()[0]
    finally:
        connection.close()
    assert plan_count == 1
    assert patch_count == 0
    assert job_count == 1
    assert not any((workspace / "patches").iterdir())


def test_exact_workspace_path_contract(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "exact-workspace", "proj-1")
    assert workspace == (tmp_path / "exact-workspace").resolve()
    assert (workspace / "project.json").exists()
    reopened = init_project_workspace(tmp_path / "exact-workspace", "proj-1")
    assert reopened == workspace


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_cli_apply_patch_plan_list_plan_show(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    workspace_path = tmp_path / "work"
    assert cli.main(["v2", "init-project", str(workspace_path), "--project-id", "proj-1"]) == 0
    init_out = json.loads(capsys.readouterr().out)
    package_zip = tmp_path / "package.zip"
    _write_render_package(package_zip)
    assert cli.main(["v2", "import-package", str(package_zip), "--workspace", init_out["workspace"]]) == 0
    import_out = json.loads(capsys.readouterr().out)

    patch = _base_patch(
        project_id="proj-1",
        handoff_id="handoff-1",
        base_plan_id=import_out["edit_plan_id"],
        base_plan_hash=import_out["plan_hash"],
        package_id=import_out["package_id"],
    )
    patch["operations"] = [{"op": "remove_segment", "target_operation_id": "op-0002"}]
    patch_path = _write_patch(tmp_path / "AI_EDIT_PATCH.json", patch)

    assert cli.main(["v2", "apply-patch", str(patch_path), "--workspace", init_out["workspace"]]) == 0
    patch_out = json.loads(capsys.readouterr().out)
    assert cli.main(["v2", "plan-list", "--workspace", init_out["workspace"], "--project-id", "proj-1"]) == 0
    plans_out = json.loads(capsys.readouterr().out)
    assert len(plans_out) == 2
    assert cli.main(["v2", "plan-show", patch_out["new_plan_id"], "--workspace", init_out["workspace"]]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["metadata"]["edit_plan_id"] == patch_out["new_plan_id"]
    assert shown["payload"]["patch_id"] == "patch-1"
