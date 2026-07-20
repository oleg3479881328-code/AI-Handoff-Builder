from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from handoff_builder import cli
from handoff_builder.v2.errors import InvalidQueueTransitionError, ProjectMismatchError
from handoff_builder.v2.packages.guards import compute_sha256
from handoff_builder.v2.plans.schema import validate_payload
from handoff_builder.v2.services.import_service import import_package_into_workspace
from handoff_builder.v2.storage import apply_migrations, connect_workspace_db
from handoff_builder.v2.storage.repositories import SqliteRenderQueueRepository, WorkspaceRepository
from handoff_builder.v2.workspace import init_project_workspace


def _write_package(zip_path: Path, *, project_id: str = "proj-1", handoff_id: str = "handoff-1") -> tuple[dict, dict]:
    plan = {
        "schema_version": "1.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "plan_id": "plan-1",
        "created_at": "2026-07-20T12:00:00Z",
        "mode": "preview",
        "assets": [
            {
                "asset_id": "asset-1",
                "path": "assets/source.mp4",
                "media_type": "video",
            }
        ],
        "operations": [
            {
                "op": "video_segment",
                "asset_id": "asset-1",
                "source_in_ms": 0,
                "source_out_ms": 500,
            }
        ],
    }
    plan_bytes = json.dumps(plan, ensure_ascii=False).encode("utf-8")
    plan_sha = compute_sha256(_write_temp_file(zip_path.parent / "plan.tmp", plan_bytes))
    (zip_path.parent / "plan.tmp").unlink()
    asset_bytes = b"fake-video-placeholder"
    asset_sha = compute_sha256(_write_temp_file(zip_path.parent / "asset.tmp", asset_bytes))
    (zip_path.parent / "asset.tmp").unlink()
    manifest = {
        "schema_version": "1.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "created_at": "2026-07-20T12:00:00Z",
        "package_files": [
            {"path": "plans/plan-1.json", "sha256": plan_sha, "size_bytes": len(plan_bytes)},
            {"path": "assets/source.mp4", "sha256": asset_sha, "size_bytes": len(asset_bytes)},
        ],
        "plans": [
            {"plan_id": "plan-1", "path": "plans/plan-1.json", "sha256": plan_sha}
        ],
    }
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ai_edit_package.json", json.dumps(manifest))
        archive.writestr("plans/plan-1.json", plan_bytes)
        archive.writestr("assets/source.mp4", asset_bytes)
    return manifest, plan


def _write_temp_file(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def test_database_migration_from_empty_db(tmp_path: Path):
    db_path = tmp_path / "project.sqlite"
    connection = connect_workspace_db(db_path)
    try:
        apply_migrations(connection)
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        connection.close()
    assert {"projects", "ai_packages", "edit_plans", "render_jobs", "render_outputs", "events"} <= tables


def test_foreign_keys_enabled(tmp_path: Path):
    connection = connect_workspace_db(tmp_path / "project.sqlite")
    try:
        value = connection.execute("PRAGMA foreign_keys").fetchone()[0]
    finally:
        connection.close()
    assert value == 1


def test_atomic_successful_import_and_queue(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_package(package_zip)

    result = import_package_into_workspace(package_zip, workspace)

    assert result.project_id == "proj-1"
    assert result.render_report_path.exists()
    report = json.loads(result.render_report_path.read_text(encoding="utf-8"))
    validate_payload("render_report", "1.0", report)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        package_count = connection.execute("SELECT COUNT(*) FROM ai_packages").fetchone()[0]
        plan_count = connection.execute("SELECT COUNT(*) FROM edit_plans").fetchone()[0]
        job_count = connection.execute("SELECT COUNT(*) FROM render_jobs").fetchone()[0]
        event_count = connection.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    finally:
        connection.close()
    assert package_count == plan_count == job_count == event_count == 1


def test_rollback_on_validation_failure(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "bad_project.zip"
    _write_package(package_zip, project_id="wrong-project")
    with pytest.raises(ProjectMismatchError):
        import_package_into_workspace(package_zip, workspace)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        counts = [
            connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("ai_packages", "edit_plans", "render_jobs", "events")
        ]
    finally:
        connection.close()
    assert counts == [0, 0, 0, 0]


def test_rollback_on_persistence_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip)

    original = WorkspaceRepository.insert_plan

    def boom(*args, **kwargs):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(WorkspaceRepository, "insert_plan", boom)
    with pytest.raises(RuntimeError):
        import_package_into_workspace(package_zip, workspace)
    monkeypatch.setattr(WorkspaceRepository, "insert_plan", original)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("ai_packages", "edit_plans", "render_jobs", "render_outputs", "events")
        }
    finally:
        connection.close()
    assert counts == {key: 0 for key in counts}


def test_duplicate_import_idempotency(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip)

    first = import_package_into_workspace(package_zip, workspace)
    second = import_package_into_workspace(package_zip, workspace)

    assert first.render_job_id == second.render_job_id
    assert second.duplicate is True

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        package_count = connection.execute("SELECT COUNT(*) FROM ai_packages").fetchone()[0]
        job_count = connection.execute("SELECT COUNT(*) FROM render_jobs").fetchone()[0]
    finally:
        connection.close()
    assert package_count == 1
    assert job_count == 1


def test_plan_hash_and_package_checksum_persisted(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip)
    result = import_package_into_workspace(package_zip, workspace)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        package_row = connection.execute("SELECT package_sha256 FROM ai_packages").fetchone()
        plan_row = connection.execute("SELECT plan_hash FROM edit_plans").fetchone()
    finally:
        connection.close()
    assert package_row["package_sha256"] == result.package_sha256
    assert plan_row["plan_hash"] == result.plan_hash


def test_queue_valid_transitions_and_claim(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip)
    result = import_package_into_workspace(package_zip, workspace)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        repo = SqliteRenderQueueRepository(connection)
        claimed = repo.claim_next_pending_job("proj-1")
        assert claimed is not None
        assert claimed["status"] == "running"
        repo.mark_completed(result.render_job_id)
        assert repo.get_by_id(result.render_job_id)["status"] == "completed"
    finally:
        connection.close()


def test_queue_invalid_transition_rejected(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip)
    result = import_package_into_workspace(package_zip, workspace)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        repo = SqliteRenderQueueRepository(connection)
        repo.mark_running(result.render_job_id)
        repo.mark_completed(result.render_job_id)
        with pytest.raises(InvalidQueueTransitionError):
            repo.mark_running(result.render_job_id)
    finally:
        connection.close()


def test_cancel_flow_and_retry_flow(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip)
    result = import_package_into_workspace(package_zip, workspace)

    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        repo = SqliteRenderQueueRepository(connection)
        repo.request_cancel(result.render_job_id)
        repo.mark_cancelled(result.render_job_id)
        retry = repo.retry_job(result.render_job_id)
        assert retry["status"] == "pending"
        assert retry["attempt_number"] == 2
        assert retry["parent_render_job_id"] == result.render_job_id
    finally:
        connection.close()


def test_restart_persistence(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip)
    result = import_package_into_workspace(package_zip, workspace)

    connection = connect_workspace_db(workspace / "project.sqlite")
    connection.close()

    reopened = connect_workspace_db(workspace / "project.sqlite")
    try:
        queue_row = reopened.execute("SELECT * FROM render_jobs WHERE render_job_id = ?", (result.render_job_id,)).fetchone()
        report_row = reopened.execute("SELECT * FROM render_outputs WHERE render_job_id = ?", (result.render_job_id,)).fetchone()
    finally:
        reopened.close()
    assert queue_row is not None
    assert Path(report_row["report_path"]).exists()


def test_controlled_workspace_paths_and_unicode_project_path(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "рабочая зона", "проект-1")
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip, project_id="проект-1")
    result = import_package_into_workspace(package_zip, workspace)

    assert str(result.package_root).startswith(str(workspace))
    assert str(result.render_report_path).startswith(str(workspace))
    assert workspace.name == "проект-1"


def test_cli_v2_vertical_slice(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    work_dir = tmp_path / "work"
    assert cli.main(["v2", "init-project", str(work_dir), "--project-id", "proj-1"]) == 0
    init_out = json.loads(capsys.readouterr().out)
    package_zip = tmp_path / "package.zip"
    _write_package(package_zip)
    assert cli.main(["v2", "import-package", str(package_zip), "--workspace", init_out["workspace"]]) == 0
    import_out = json.loads(capsys.readouterr().out)
    assert cli.main(["v2", "queue-list", "--workspace", init_out["workspace"], "--project-id", "proj-1"]) == 0
    queue_list = json.loads(capsys.readouterr().out)
    assert len(queue_list) == 1
    assert cli.main(["v2", "queue-show", import_out["render_job_id"], "--workspace", init_out["workspace"]]) == 0
    queue_item = json.loads(capsys.readouterr().out)
    assert queue_item["render_job_id"] == import_out["render_job_id"]


def test_v1_regression_cli_help_available(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    assert "--input" in capsys.readouterr().out
