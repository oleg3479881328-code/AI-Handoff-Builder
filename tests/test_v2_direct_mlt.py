from __future__ import annotations

from pathlib import Path

import pytest

from handoff_builder.v2.direct_mlt import (
    build_direct_shotcut_mlt_from_context_payload,
    validate_direct_mlt_resources,
)
from handoff_builder.v2.errors import UnsafePackageError


def test_direct_mlt_builder_uses_only_original_paths_and_allows_unrelated_output_folder(tmp_path: Path) -> None:
    original = tmp_path / "OneDrive - Oleg3" / "Carolyn and Rob" / "originals" / "cover image.jpg"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"photo")
    output_path = tmp_path / "Downloads unrelated" / "Carolyn and Rob ready.mlt"
    backend = _FakeBackend(original)
    context = _context_payload(tmp_path, original)

    summary = build_direct_shotcut_mlt_from_context_payload(
        context,
        backend=backend,
        output_path=output_path,
    )

    assert output_path.exists()
    assert backend.created["project_path"] == str(output_path)
    assert backend.created["clips"][0]["path"] == str(original.resolve())
    assert backend.created["clips"][0]["image_duration_seconds"] == 3.0
    assert summary["resource_validation"]["uses_only_originals"] is True
    assert summary["resource_validation"]["missing_resources"] == []


def test_direct_mlt_builder_hard_fails_when_selected_asset_has_no_original_mapping(tmp_path: Path) -> None:
    original = tmp_path / "project" / "originals" / "cover.jpg"
    original.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"photo")
    context = _context_payload(tmp_path, original)
    context["asset_map"]["asset-photo-1"]["original_path"] = ""
    backend = _FakeBackend(original)

    with pytest.raises(UnsafePackageError, match="no mapped original path"):
        build_direct_shotcut_mlt_from_context_payload(
            context,
            backend=backend,
            output_path=tmp_path / "Downloads" / "ready.mlt",
        )


def test_direct_mlt_validation_rejects_proxy_resources_and_percent20_filenames(tmp_path: Path) -> None:
    original = tmp_path / "project" / "originals" / "cover.jpg"
    proxy = tmp_path / "project" / "proxies" / "asset_cover.mp4"
    original.parent.mkdir(parents=True, exist_ok=True)
    proxy.parent.mkdir(parents=True, exist_ok=True)
    original.write_bytes(b"photo")
    proxy.write_bytes(b"proxy")
    context = _context_payload(tmp_path, original, proxy=proxy)

    with pytest.raises(UnsafePackageError, match="proxy media resources"):
        validate_direct_mlt_resources(
            context,
            inspect_result={"resources": [{"resolved_path": str(proxy.resolve())}], "missing_resources": []},
            output_path=tmp_path / "Downloads" / "ready.mlt",
        )

    with pytest.raises(UnsafePackageError, match="%20"):
        validate_direct_mlt_resources(
            context,
            inspect_result={"resources": [{"resolved_path": str(original.resolve())}], "missing_resources": []},
            output_path=tmp_path / "Downloads" / "Carolyn%20and%20Rob.mlt",
        )


def _context_payload(tmp_path: Path, original: Path, *, proxy: Path | None = None) -> dict:
    project_root = tmp_path / "project"
    return {
        "schema_version": "1.0",
        "document_type": "assistant_context",
        "project_id": "carolyn_and_rob",
        "project_name": "Carolyn and Rob",
        "handoff_id": "handoff-1",
        "created_at": "2026-07-31T00:00:00+00:00",
        "preferred_edit_source": "originals",
        "must_use_absolute_original_media_paths": True,
        "mlt_may_be_opened_from_any_folder": True,
        "user_file_movement_required": False,
        "direct_mlt_support": {"available": True, "reason_unavailable": None},
        "project_root": str(project_root.resolve()),
        "originals_root": str((project_root / "originals").resolve()),
        "proxies_root": str((project_root / "proxies").resolve()),
        "asset_map": {
            "asset-photo-1": {
                "asset_id": "asset-photo-1",
                "media_type": "photo",
                "original_name": original.name,
                "original_filename": original.name,
                "original_path": str(original.resolve()),
                "original_project_path": "originals/cover image.jpg",
                "proxy_filename": proxy.name if proxy else None,
                "proxy_path": str(proxy.resolve()) if proxy else None,
                "proxy_project_path": "proxies/asset_cover.mp4" if proxy else None,
            }
        },
    }


class _FakeBackend:
    def __init__(self, original: Path) -> None:
        self.original = original.resolve()
        self.created: dict[str, object] = {}

    def probe_media(self, path: Path) -> dict:
        return {"streams": [{"type": "video", "frame_rate": 30.0, "width": 1080, "height": 1920}]}

    def create_disposable_project(self, project_path: Path, *, profile, clips, overwrite: bool) -> dict:
        project_path.parent.mkdir(parents=True, exist_ok=True)
        project_path.write_text("<mlt/>", encoding="utf-8")
        self.created = {
            "project_path": str(project_path),
            "profile": profile.to_create_project_args(),
            "clips": [clip.to_clip_args() for clip in clips],
            "overwrite": overwrite,
        }
        return {"path": str(project_path), "revision": "a" * 64}

    def inspect_project(self, project_path: Path) -> dict:
        return {"resources": [{"resolved_path": str(self.original)}], "missing_resources": []}

    def validate_project(self, project_path: Path) -> dict:
        return {"valid": True, "ready": True}
