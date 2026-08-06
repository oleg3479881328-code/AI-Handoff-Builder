from __future__ import annotations

import json
import queue
import shutil
import zipfile
from pathlib import Path

import pytest

from handoff_builder.v2.gui_controller import V2RunnerController
from handoff_builder.v2.packages.guards import compute_sha256
from handoff_builder.v2.project_registry import ProjectRegistryStore, record_local_handoff
from handoff_builder.v2.workspace import init_project_workspace


def _ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _make_video(path: Path, *, duration_seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
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
        "sine=frequency=440:sample_rate=48000",
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
    import subprocess

    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _write_package(zip_path: Path) -> None:
    build_dir = zip_path.parent / "build"
    build_dir.mkdir(parents=True, exist_ok=True)
    asset1 = build_dir / "seg1.mp4"
    asset2 = build_dir / "seg2.mp4"
    _make_video(asset1, duration_seconds=1.5)
    _make_video(asset2, duration_seconds=1.2)
    asset1_bytes = asset1.read_bytes()
    asset2_bytes = asset2.read_bytes()
    plan = {
        "schema_version": "1.0",
        "project_id": "proj-1",
        "handoff_id": "handoff-1",
        "handoff_sha256": "a" * 64,
        "plan_id": "plan-1",
        "created_at": "2026-07-20T12:00:00Z",
        "mode": "preview",
        "assets": [
            {"asset_id": "asset-1", "path": "assets/seg1.mp4", "media_type": "video"},
            {"asset_id": "asset-2", "path": "assets/seg2.mp4", "media_type": "video"},
        ],
        "operations": [
            {"op": "video_segment", "asset_id": "asset-1", "source_in_ms": 0, "source_out_ms": 700},
            {"op": "video_segment", "asset_id": "asset-2", "source_in_ms": 100, "source_out_ms": 700},
        ],
    }
    plan_bytes = json.dumps(plan, ensure_ascii=False).encode("utf-8")
    manifest = {
        "schema_version": "1.0",
        "project_id": "proj-1",
        "handoff_id": "handoff-1",
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


def _write_temp(path: Path, data: bytes) -> Path:
    path.write_bytes(data)
    return path


def _write_patch(path: Path, *, base_plan_id: str, base_plan_hash: str) -> None:
    payload = {
        "schema_version": "1.0",
        "project_id": "proj-1",
        "handoff_id": "handoff-1",
        "handoff_sha256": "a" * 64,
        "package_id": compute_sha256(path.parent / "AI_EDIT_PACKAGE.zip")[:16] if (path.parent / "AI_EDIT_PACKAGE.zip").exists() else None,
        "patch_id": "patch-1",
        "base_plan_id": base_plan_id,
        "base_plan_hash": base_plan_hash,
        "created_at": "2026-07-20T12:30:00Z",
        "operations": [
            {"op": "remove_segment", "target_operation_id": "op-0002"}
        ],
    }
    if payload["package_id"] is None:
        del payload["package_id"]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _wait_for_event(events: queue.Queue[tuple[str, object]], expected: str, *, timeout_seconds: float = 30.0):
    import time

    deadline = time.time() + timeout_seconds
    seen: list[tuple[str, object]] = []
    while time.time() < deadline:
        try:
            item = events.get(timeout=0.2)
        except queue.Empty:
            continue
        seen.append(item)
        if item[0] == expected:
            return item, seen
        if item[0] == "v2_error":
            raise AssertionError(f"Unexpected controller error: {item[1]}")
    raise AssertionError(f"Timed out waiting for {expected}. Seen: {seen}")


@pytest.mark.skipif(not _ffmpeg_available(), reason="FFmpeg not available")
def test_gui_controller_state_transitions_without_display(tmp_path: Path):
    events: queue.Queue[tuple[str, object]] = queue.Queue()
    controller = V2RunnerController(events)
    workspace = tmp_path / "Рабочая папка & Oleg's"
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_package(package_zip)

    controller.start_open_workspace(workspace, project_id="proj-1", create=True)
    event, _seen = _wait_for_event(events, "workspace_ready")
    assert controller.state == "workspace_ready"
    snapshot = event[1]
    assert snapshot["project_id"] == "proj-1"

    controller.start_import_package(package_zip)
    event, _seen = _wait_for_event(events, "package_imported")
    assert controller.state == "render_pending"
    summary = event[1]
    assert summary["operation_count"] == 2

    controller.start_render_job(summary["render_job_id"])
    event, _seen = _wait_for_event(events, "render_completed")
    assert controller.state == "render_completed"
    details = event[1]
    assert details["job"]["status"] == "completed"

    patch_path = tmp_path / "AI_EDIT_PATCH.json"
    _write_patch(patch_path, base_plan_id=summary["plan_id"], base_plan_hash=summary["plan_hash"])
    controller.start_apply_patch(patch_path)
    event, _seen = _wait_for_event(events, "patch_applied")
    assert controller.state == "patch_applied"
    patch_summary = event[1]
    assert patch_summary["plan_version"] == 2


def test_gui_controller_import_resolves_saved_project_mapping_without_manual_open(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    events: queue.Queue[tuple[str, object]] = queue.Queue()
    controller = V2RunnerController(events)
    workspace = init_project_workspace(tmp_path / "WEDDING_PROJECT", "proj-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_package(package_zip)
    record_local_handoff(
        project_root=workspace,
        project_id="proj-1",
        handoff_id="handoff-1",
        handoff_sha256="a" * 64,
        archive_path=workspace / "handoffs" / "proj-1_ANALYSIS_HANDOFF.zip",
    )
    ProjectRegistryStore().register_project(
        project_root=workspace,
        project_id="proj-1",
        handoff_id="handoff-1",
        handoff_sha256="a" * 64,
    )

    controller.start_import_package(package_zip)
    event, _seen = _wait_for_event(events, "package_imported")

    assert controller.workspace == workspace.resolve()
    assert controller.project_id == "proj-1"
    assert event[1]["project_id"] == "proj-1"


def test_gui_controller_import_can_restore_link_from_project_folder_fallback(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    events: queue.Queue[tuple[str, object]] = queue.Queue()
    controller = V2RunnerController(events)
    workspace = init_project_workspace(tmp_path / "WEDDING_PROJECT", "proj-1")
    package_zip = tmp_path / "AI_EDIT_PACKAGE.zip"
    _write_package(package_zip)
    record_local_handoff(
        project_root=workspace,
        project_id="proj-1",
        handoff_id="handoff-1",
        handoff_sha256="a" * 64,
        archive_path=workspace / "handoffs" / "proj-1_ANALYSIS_HANDOFF.zip",
    )

    controller.start_import_package(package_zip, fallback_path=workspace)
    event, _seen = _wait_for_event(events, "package_imported")

    assert controller.workspace == workspace.resolve()
    assert event[1]["project_id"] == "proj-1"
