from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from handoff_builder.utils import file_sha256
from handoff_builder.v2.errors import UnsafePackageError
from handoff_builder.v2.plans.schema import load_bounded_json_object, validate_payload
from handoff_builder.v2.project_registry import record_local_handoff
from handoff_builder.v2.render.ffmpeg_backend import FFmpegBackend
from handoff_builder.v2.services.import_service import import_plan_into_workspace
from handoff_builder.v2.storage import connect_workspace_db
from handoff_builder.v2.timeline.compiler import compile_normalized_timeline
from handoff_builder.v2.workspace import init_project_workspace


def _make_photo(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (1080, 1920), color="green").save(path, "JPEG")


def _registry_payload(asset_path: Path) -> dict:
    return {
        "schema_version": "1.0",
        "assets": [
            {
                "asset_id": "asset-photo-1",
                "media_type": "photo",
                "source_path": str(asset_path.resolve()),
                "sha256": file_sha256(asset_path),
                "size_bytes": asset_path.stat().st_size,
                "original_name": asset_path.name,
            }
        ],
    }


def _plan_payload() -> dict:
    return {
        "schema_version": "3.0",
        "document_type": "edit_plan",
        "project_id": "carolyn_and_rob",
        "project_name": "Carolyn and Rob",
        "handoff_id": "handoff-1",
        "handoff_content_hash": "b" * 64,
        "plan_id": "plan-1",
        "plan_version": 1,
        "canvas": {"width": 1080, "height": 1920},
        "timebase": {"fps_num": 30, "fps_den": 1},
        "assets": [
            {"asset_id": "asset-photo-1", "media_type": "photo", "original_name": "cover.jpg"}
        ],
        "visual_items": [
            {
                "item_id": "item-1",
                "asset_id": "asset-photo-1",
                "media_type": "photo",
                "track_id": "V1",
                "timeline_start_frame": 0,
                "duration_frames": 90,
                "source_in_us": 0,
                "source_out_us": 0,
                "source_audio_policy": "discard",
            }
        ],
        "audio_items": [],
        "text_items": [],
        "renderer": {"primary_renderer": "shotcut", "capabilities": []},
    }


def test_standalone_edit_plan_json_imports_without_zip_wrapper(tmp_path: Path) -> None:
    workspace = init_project_workspace(tmp_path / "workspace", "carolyn_and_rob")
    photo = tmp_path / "source" / "cover.jpg"
    _make_photo(photo)
    registry_path = workspace / "analysis" / "local_asset_registry.json"
    registry_path.write_text(json.dumps(_registry_payload(photo), ensure_ascii=False, indent=2), encoding="utf-8")
    record_local_handoff(
        project_root=workspace,
        project_id="carolyn_and_rob",
        project_name="Carolyn and Rob",
        handoff_id="handoff-1",
        handoff_sha256="a" * 64,
        handoff_content_hash="b" * 64,
    )
    plan_path = tmp_path / "Carolyn and Rob.json"
    plan_path.write_text(json.dumps(_plan_payload(), ensure_ascii=False, indent=2), encoding="utf-8")

    result = import_plan_into_workspace(plan_path, workspace)

    assert result.edit_plan_id == "plan-1"
    assert result.render_report_path.exists()
    assert (result.package_root / "Carolyn and Rob.json").exists()
    assert (result.package_root / "normalized_timeline.json").exists()
    connection = connect_workspace_db(workspace / "project.sqlite")
    try:
        assert connection.execute("SELECT COUNT(*) FROM ai_packages").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM edit_plans").fetchone()[0] == 1
    finally:
        connection.close()


def test_normalized_timeline_is_deterministic_for_same_valid_json(tmp_path: Path) -> None:
    workspace = init_project_workspace(tmp_path / "workspace", "carolyn_and_rob")
    photo = tmp_path / "source" / "cover.jpg"
    _make_photo(photo)
    (workspace / "analysis" / "local_asset_registry.json").write_text(
        json.dumps(_registry_payload(photo), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    payload = _plan_payload()
    backend = FFmpegBackend(project_root=tmp_path)
    resolved_assets = [
        {
            "asset_id": "asset-photo-1",
            "source_path": str(photo.resolve()),
            "sha256": file_sha256(photo),
            "size_bytes": photo.stat().st_size,
        }
    ]

    hashes = {
        compile_normalized_timeline(
            payload,
            resolved_assets,
            source_package_content_hash="b" * 64,
        ).timeline_hash
        for _ in range(100)
    }

    assert len(hashes) == 1


def test_direct_json_loader_rejects_empty_file(tmp_path: Path) -> None:
    path = tmp_path / "empty.json"
    path.write_bytes(b"")

    with pytest.raises(UnsafePackageError, match="empty"):
        load_bounded_json_object(path)


def test_direct_json_loader_rejects_oversized_file(tmp_path: Path) -> None:
    path = tmp_path / "huge.json"
    path.write_bytes(b"{" + b"a" * (10 * 1024 * 1024) + b"}")

    with pytest.raises(UnsafePackageError, match="exceeds size limit"):
        load_bounded_json_object(path)


def test_direct_json_loader_rejects_invalid_utf8(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(b'{"project_id":"x","bad":"\x80"}')

    with pytest.raises(UnsafePackageError, match="UTF-8"):
        load_bounded_json_object(path)


def test_direct_json_loader_rejects_non_object_root(tmp_path: Path) -> None:
    path = tmp_path / "array.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(UnsafePackageError, match="root must be one object"):
        load_bounded_json_object(path)


def test_direct_json_loader_keeps_unknown_schema_fail_closed(tmp_path: Path) -> None:
    path = tmp_path / "unknown.json"
    payload = _plan_payload()
    payload["schema_version"] = "9.9"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    loaded = load_bounded_json_object(path)

    with pytest.raises(Exception, match="Unsupported schema version"):
        validate_payload("edit_plan", str(loaded["schema_version"]), loaded)
