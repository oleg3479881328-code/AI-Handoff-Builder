from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

import pytest

from handoff_builder import cli
from handoff_builder.v2.errors import UnsafePackageError
from handoff_builder.v2.packages.guards import compute_sha256
from handoff_builder.v2.qc.inspect import inspect_preview_output
from handoff_builder.v2.render.compiler import compile_preview_render_plan
from handoff_builder.v2.render.ffmpeg_backend import FFmpegBackend
from handoff_builder.v2.services.import_service import import_package_into_workspace
from handoff_builder.v2.services.render_service import render_job, render_next_pending_job
from handoff_builder.v2.storage.db import connect_workspace_db
from handoff_builder.v2.storage.repositories import SqliteRenderQueueRepository
from handoff_builder.v2.workspace import init_project_workspace
from handoff_builder.v2.plans.semantic import load_and_validate_preview_plan


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
            "sine=frequency=880:sample_rate=48000",
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


def _write_render_package(
    zip_path: Path,
    *,
    project_id: str = "proj-1",
    handoff_id: str = "handoff-1",
    bad_operation: bool = False,
    missing_source: bool = False,
    raw_command_field: bool = False,
    out_of_range: bool = False,
    workspace_chars: bool = False,
) -> tuple[dict, dict]:
    temp_dir = zip_path.parent / "build_pkg"
    temp_dir.mkdir(parents=True, exist_ok=True)
    asset1 = temp_dir / "seg1.mp4"
    asset2 = temp_dir / ("seg two & Oleg's.mp4" if workspace_chars else "seg2.mp4")
    _make_video(asset1, duration_seconds=1.4, with_audio=True)
    _make_video(asset2, duration_seconds=1.2, with_audio=False)
    asset1_bytes = asset1.read_bytes()
    asset2_bytes = asset2.read_bytes()
    op_name = "raw" if bad_operation else "video_segment"
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
            {
                "asset_id": "asset-2",
                "path": "assets/missing.mp4" if missing_source else f"assets/{asset2.name}",
                "media_type": "video",
            },
        ],
        "operations": [
            {
                "op": op_name,
                "asset_id": "asset-1",
                "source_in_ms": 0,
                "source_out_ms": 700,
            },
            {
                "op": "video_segment",
                "asset_id": "asset-2",
                "source_in_ms": 0,
                "source_out_ms": 5000 if out_of_range else 600,
            },
        ],
    }
    if raw_command_field:
        plan["operations"][0]["ffmpeg_filter"] = "scale=1:1"

    plan_bytes = json.dumps(plan, ensure_ascii=False).encode("utf-8")
    manifest = {
        "schema_version": "1.0",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "handoff_sha256": "a" * 64,
        "created_at": "2026-07-20T12:00:00Z",
        "package_files": [
            {"path": "plans/plan-1.json", "sha256": compute_sha256(_write_tmp(zip_path.parent / "plan.tmp", plan_bytes)), "size_bytes": len(plan_bytes)},
            {"path": "assets/seg1.mp4", "sha256": compute_sha256(_write_tmp(zip_path.parent / "a1.tmp", asset1_bytes)), "size_bytes": len(asset1_bytes)},
        ],
        "plans": [{"plan_id": "plan-1", "path": "plans/plan-1.json", "sha256": compute_sha256(zip_path.parent / "plan.tmp")}],
    }
    if not missing_source:
        manifest["package_files"].append(
            {
                "path": f"assets/{asset2.name}",
                "sha256": compute_sha256(_write_tmp(zip_path.parent / "a2.tmp", asset2_bytes)),
                "size_bytes": len(asset2_bytes),
            }
        )
    for temp_name in ("plan.tmp", "a1.tmp", "a2.tmp"):
        temp_file = zip_path.parent / temp_name
        if temp_file.exists():
            temp_file.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ai_edit_package.json", json.dumps(manifest))
        archive.writestr("plans/plan-1.json", plan_bytes)
        archive.writestr("assets/seg1.mp4", asset1_bytes)
        if not missing_source:
            archive.writestr(f"assets/{asset2.name}", asset2_bytes)
    return manifest, plan


def _write_tmp(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _import_fixture_package(tmp_path: Path, *, workspace_name: str = "work", project_id: str = "proj-1", **kwargs):
    workspace = init_project_workspace(tmp_path / workspace_name, project_id)
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_render_package(package_zip, project_id=project_id, **kwargs)
    result = import_package_into_workspace(package_zip, workspace)
    return workspace, result


def test_semantic_validator_success(tmp_path: Path):
    workspace, result = _import_fixture_package(tmp_path)
    backend = FFmpegBackend(project_root=Path.cwd())
    plan_row_path = connect_workspace_db(workspace / "project.sqlite").execute(
        "SELECT plan_path FROM edit_plans WHERE edit_plan_id = ?",
        (result.edit_plan_id,),
    ).fetchone()["plan_path"]
    validated = load_and_validate_preview_plan(Path(plan_row_path), result.package_root, backend)
    assert validated.planned_duration_ms > 0
    assert len(validated.operations) == 2


def test_missing_source_rejected(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "bad.zip"
    _write_render_package(package_zip, project_id="proj-1", missing_source=True)
    result = import_package_into_workspace(package_zip, workspace)
    with pytest.raises(UnsafePackageError):
        render_job(workspace, result.render_job_id)


def test_out_of_range_trim_rejected(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "bad.zip"
    _write_render_package(package_zip, project_id="proj-1", out_of_range=True)
    result = import_package_into_workspace(package_zip, workspace)
    with pytest.raises(UnsafePackageError):
        render_job(workspace, result.render_job_id)


def test_unsupported_operation_and_raw_command_rejected(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "bad.zip"
    _write_render_package(package_zip, project_id="proj-1", bad_operation=True)
    with pytest.raises(Exception):
        import_package_into_workspace(package_zip, workspace)

    package_zip2 = tmp_path / "bad2.zip"
    _write_render_package(package_zip2, project_id="proj-1", raw_command_field=True)
    with pytest.raises(Exception):
        import_package_into_workspace(package_zip2, workspace)


def test_deterministic_compiler_result(tmp_path: Path):
    workspace, result = _import_fixture_package(tmp_path)
    backend = FFmpegBackend(project_root=Path.cwd())
    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        plan_path = Path(connection.execute("SELECT plan_path FROM edit_plans").fetchone()["plan_path"])
    finally:
        connection.close()
    validated = load_and_validate_preview_plan(plan_path, result.package_root, backend)
    first = compile_preview_render_plan(validated, ffmpeg_path=backend.ffmpeg, output_path=workspace / "renders" / "job" / "reel.mp4")
    second = compile_preview_render_plan(validated, ffmpeg_path=backend.ffmpeg, output_path=workspace / "renders" / "job" / "reel.mp4")
    assert first.compiled_plan_hash == second.compiled_plan_hash
    assert first.ffmpeg_args == second.ffmpeg_args


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_worker_success_lifecycle_and_qc(tmp_path: Path):
    workspace, result = _import_fixture_package(tmp_path)
    payload = render_job(workspace, result.render_job_id)
    assert payload["status"] == "completed"
    output_dir = Path(payload["output_directory"])
    assert (output_dir / "reel.mp4").exists()
    assert (output_dir / "render_plan.json").exists()
    assert (output_dir / "ffmpeg_command.json").exists()
    assert (output_dir / "first_frame.jpg").exists()
    report = json.loads((output_dir / "render_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "completed"
    assert report["renderer_status"] == "completed"
    assert report["outputs"][0]["width"] == 720
    assert report["outputs"][0]["height"] == 1280
    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        row = connection.execute(
            "SELECT status, started_at, finished_at FROM render_jobs WHERE render_job_id = ?",
            (result.render_job_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row["status"] == "completed"
    assert row["started_at"] is not None
    assert row["finished_at"] is not None


def test_worker_failure_lifecycle(tmp_path: Path):
    workspace = init_project_workspace(tmp_path / "work", "proj-1")
    package_zip = tmp_path / "bad.zip"
    _write_render_package(package_zip, project_id="proj-1", missing_source=True)
    result = import_package_into_workspace(package_zip, workspace)
    with pytest.raises(UnsafePackageError):
        render_job(workspace, result.render_job_id)
    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        row = connection.execute("SELECT status, failed_stage, error_code FROM render_jobs WHERE render_job_id = ?", (result.render_job_id,)).fetchone()
    finally:
        connection.close()
    assert row["status"] == "failed"
    assert row["failed_stage"] is not None
    assert row["error_code"] is not None


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_render_next_and_completed_job_idempotency(tmp_path: Path):
    workspace, result = _import_fixture_package(tmp_path)
    payload = render_next_pending_job(workspace)
    assert payload["status"] == "completed"
    second = render_job(workspace, result.render_job_id)
    assert second["already_completed"] is True


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_unicode_special_windows_path_render(tmp_path: Path):
    workspace, result = _import_fixture_package(
        tmp_path,
        workspace_name="Рабочая папка & Oleg's",
        project_id="proj-special",
        workspace_chars=True,
    )
    payload = render_job(workspace, result.render_job_id)
    assert payload["status"] == "completed"


def test_v1_cli_regression_with_new_commands(capsys: pytest.CaptureFixture[str]):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--help"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "--input" in out
