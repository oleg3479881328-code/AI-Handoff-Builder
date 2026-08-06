from __future__ import annotations

import json
import zipfile
from pathlib import Path

from handoff_builder.handoff_light.ingest import HandoffLightIngestService
from handoff_builder.handoff_light.packager import HandoffLightPackager
from handoff_builder.handoff_light.project_store import ProjectStore


def test_build_handoff_zip_versions_and_no_absolute_paths(tmp_path: Path):
    projects_root = tmp_path / "projects"
    store = ProjectStore(projects_root)
    state = store.create_project("Build Package")
    photo = tmp_path / "frame.jpg"
    photo.write_bytes(b"fake-photo")
    ingest = HandoffLightIngestService(store)
    packager = HandoffLightPackager(store)

    ingest.ingest(state, [photo])
    first_zip = packager.build_handoff_zip(store.open_project(state.root))
    second_zip = packager.build_handoff_zip(store.open_project(state.root))

    assert first_zip.name.startswith("V001_")
    assert second_zip.name.startswith("V002_")
    assert first_zip.exists()
    assert second_zip.exists()
    with zipfile.ZipFile(second_zip) as archive:
        names = archive.namelist()
        assert "handoff_manifest.json" in names
        assert "asset_registry.json" in names
        payload = json.loads(archive.read("asset_registry.json").decode("utf-8"))
        serialized = json.dumps(payload)
        assert "C:\\" not in serialized
        assert "\\Users\\" not in serialized


def test_build_handoff_zip_includes_validation_report(tmp_path: Path):
    projects_root = tmp_path / "projects"
    store = ProjectStore(projects_root)
    state = store.create_project("Validation")
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"voice")
    ingest = HandoffLightIngestService(store)
    packager = HandoffLightPackager(store)

    ingest.ingest(state, [audio])
    zip_path = packager.build_handoff_zip(store.open_project(state.root))

    with zipfile.ZipFile(zip_path) as archive:
        report = json.loads(archive.read("REPORTS/BUILD_VALIDATION_REPORT.json").decode("utf-8"))
        assert report["crc_ok"] is True
        assert report["no_absolute_paths"] is True
