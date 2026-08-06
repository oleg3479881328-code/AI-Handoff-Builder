from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from handoff_builder.handoff_light.ingest import HandoffLightIngestService
from handoff_builder.handoff_light.models import IngestLimits
from handoff_builder.handoff_light.project_store import ProjectStore


def _write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def test_ingest_nested_zip_and_deduplicate(tmp_path: Path):
    projects_root = tmp_path / "projects"
    inputs_root = tmp_path / "inputs"
    store = ProjectStore(projects_root)
    state = store.create_project("Nested ZIP")
    inner_zip = inputs_root / "inner.zip"
    outer_zip = inputs_root / "outer.zip"
    _write_bytes(inputs_root / "dup.mp3", b"same-audio")
    with zipfile.ZipFile(inner_zip, "w") as zf:
        zf.writestr("phones/clip.mp3", b"same-audio")
        zf.writestr("phones/note.txt", b"hello")
    with zipfile.ZipFile(outer_zip, "w") as zf:
        zf.write(inner_zip, arcname="Guest Uploads/Weekend.zip")
        zf.writestr("Guest Uploads/photo.jpg", b"not-a-real-photo")
    service = HandoffLightIngestService(store)

    report = service.ingest(state, [outer_zip, inputs_root / "dup.mp3"])

    reloaded = store.open_project(state.root)
    assert report.discovered_file_count >= 3
    assert len(reloaded.assets) == 3
    assert len(report.duplicate_assets) == 1
    assert any(asset.archive_depth == 2 for asset in reloaded.assets)
    assert all(asset.missing is False for asset in reloaded.assets)
    assert (reloaded.reports_dir / "NEW_MATERIAL.json").exists()


def test_ingest_blocks_path_traversal_zip(tmp_path: Path):
    projects_root = tmp_path / "projects"
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.mp3", b"x")
    store = ProjectStore(projects_root)
    state = store.create_project("Traversal")
    service = HandoffLightIngestService(store)

    report = service.ingest(state, [archive])

    assert any(item["reason"] in {"zip_read_failed", "unsupported_extension"} or "archive" in item["reason"] for item in report.damaged_files + report.unsupported_files)


def test_incremental_ingest_marks_missing_sources(tmp_path: Path):
    projects_root = tmp_path / "projects"
    media = tmp_path / "take.wav"
    media.write_bytes(b"audio-1")
    store = ProjectStore(projects_root)
    state = store.create_project("Incremental")
    service = HandoffLightIngestService(store)

    service.ingest(state, [media])
    media.unlink()
    reloaded = store.open_project(state.root)
    service.ingest(reloaded, [])
    refreshed = store.open_project(state.root)

    assert refreshed.assets[0].missing is True
    missing_report = json.loads((refreshed.reports_dir / "MISSING_FILES.json").read_text(encoding="utf-8"))
    assert missing_report["missing_asset_count"] == 1


def test_same_filename_different_content_registers_two_assets(tmp_path: Path):
    projects_root = tmp_path / "projects"
    folder_a = tmp_path / "a"
    folder_b = tmp_path / "b"
    _write_bytes(folder_a / "clip.mp3", b"aaa")
    _write_bytes(folder_b / "clip.mp3", b"bbb")
    store = ProjectStore(projects_root)
    state = store.create_project("Same Name")
    service = HandoffLightIngestService(store)

    service.ingest(state, [folder_a / "clip.mp3", folder_b / "clip.mp3"])
    refreshed = store.open_project(state.root)

    assert len(refreshed.assets) == 2
    assert {asset.sha256 for asset in refreshed.assets} != set()


def test_ingest_blocks_expansion_limit(tmp_path: Path):
    projects_root = tmp_path / "projects"
    archive = tmp_path / "large.zip"
    payload = b"x" * 2048
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("big.wav", payload)
    store = ProjectStore(projects_root)
    state = store.create_project("Expansion Limit")
    service = HandoffLightIngestService(store, limits=IngestLimits(max_expanded_bytes=128))

    report = service.ingest(state, [archive])

    assert any(item["reason"] == "zip_read_failed" for item in report.damaged_files)
    assert any("Maximum expanded bytes exceeded" in str(item.get("error", "")) for item in report.damaged_files)
