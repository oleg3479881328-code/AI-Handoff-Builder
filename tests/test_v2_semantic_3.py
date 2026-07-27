"""Tests for edit_plan 3.0 semantic validation."""

import json
from pathlib import Path

import pytest

from handoff_builder.v2.errors import UnsafePackageError
from handoff_builder.v2.plans.semantic import (
    EDIT_PLAN_3_SCHEMA_VERSIONS,
    ValidatedEditPlan3,
    load_and_validate_edit_plan_3,
)

VALID_SHA256 = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"


def _make_plan_file(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "edit_plan.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _make_asset(tmp_path: Path, name: str, content: bytes = b"fake video content") -> Path:
    path = tmp_path / "assets" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


class FakeBackend:
    """Minimal FFmpegBackend stub for testing."""

    def probe(self, path: Path) -> dict:
        return {
            "codec": "h264",
            "duration": 10.0,
            "width": 1920,
            "height": 1080,
            "rotation": 0,
            "has_audio": True,
        }


SAMPLE_PLAN_3 = {
    "schema_version": "3.0",
    "plan_id": "plan-001",
    "project_id": "proj-001",
    "handoff_id": "handoff-001",
    "handoff_sha256": VALID_SHA256,
    "canvas": {"width": 1920, "height": 1080},
    "timebase": {"fps_num": 30, "fps_den": 1},
    "assets": [
        {
            "asset_id": "asset-001",
            "path": "assets/video1.mp4",
            "media_type": "video",
        },
    ],
    "audio_items": [],
    "visual_items": [
        {
            "item_id": "item-001",
            "asset_id": "asset-001",
            "media_type": "video",
            "source_in_us": 0,
            "source_out_us": 3_000_000,
            "duration_frames": 90,
            "timeline_start_frame": 0,
            "source_audio_policy": "discard",
        },
    ],
    "renderer": {"primary_renderer": "davinci"},
}


class TestLoadAndValidateEditPlan3:
    def test_basic_validation(self, tmp_path: Path):
        """Basic 3.0 plan validates successfully."""
        _make_asset(tmp_path, "video1.mp4")
        plan_path = _make_plan_file(tmp_path, SAMPLE_PLAN_3)
        result = load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())
        assert isinstance(result, ValidatedEditPlan3)
        assert result.fps_num == 30
        assert result.fps_den == 1
        assert result.total_duration_frames == 90
        assert "asset-001" in result.assets

    def test_invalid_rational_timebase(self, tmp_path: Path):
        """Zero or negative fps_num/fps_den raises error (schema catches minimum first)."""
        _make_asset(tmp_path, "video1.mp4")
        for bad_tb in [
            {"timebase": {"fps_num": 0, "fps_den": 1}},
            {"timebase": {"fps_num": 30, "fps_den": 0}},
            {"timebase": {"fps_num": -1, "fps_den": 1}},
        ]:
            plan = dict(SAMPLE_PLAN_3, **bad_tb)
            plan_path = _make_plan_file(tmp_path, plan)
            with pytest.raises((UnsafePackageError, ValueError), match="Invalid|must be >=|minimum"):
                load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())

    def test_source_audio_policy_visual_item(self, tmp_path: Path):
        """Invalid source_audio_policy in visual_item raises error."""
        _make_asset(tmp_path, "video1.mp4")
        plan = {
            **SAMPLE_PLAN_3,
            "visual_items": [
                {
                    "item_id": "item-001",
                    "asset_id": "asset-001",
                    "media_type": "video",
                    "source_in_us": 0,
                    "source_out_us": 3_000_000,
                    "duration_frames": 90,
                    "timeline_start_frame": 0,
                    "source_audio_policy": "invalid_policy",
                },
            ],
        }
        plan_path = _make_plan_file(tmp_path, plan)
        with pytest.raises((UnsafePackageError, ValueError), match="Invalid|must be one of"):
            load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())

    def test_valid_source_audio_policies(self, tmp_path: Path):
        """All valid source_audio_policy values are accepted."""
        _make_asset(tmp_path, "video1.mp4")
        for policy in ("discard", "keep", "duck_under_music", "replace"):
            plan = {
                **SAMPLE_PLAN_3,
                "visual_items": [
                    {
                        "item_id": "item-001",
                        "asset_id": "asset-001",
                        "media_type": "video",
                        "source_in_us": 0,
                        "source_out_us": 3_000_000,
                        "duration_frames": 90,
                        "timeline_start_frame": 0,
                        "source_audio_policy": policy,
                    },
                ],
            }
            plan_path = _make_plan_file(tmp_path, plan)
            result = load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())
            assert result.total_duration_frames == 90

    def test_negative_source_position(self, tmp_path: Path):
        """Negative source_in_us or source_out_us raises error (schema catches minimum first)."""
        _make_asset(tmp_path, "video1.mp4")
        for bad_us in [{"source_in_us": -1}, {"source_out_us": -1}]:
            plan = {
                **SAMPLE_PLAN_3,
                "visual_items": [
                    {
                        "item_id": "item-001",
                        "asset_id": "asset-001",
                        "media_type": "video",
                        "source_in_us": 0,
                        "source_out_us": 3_000_000,
                        "duration_frames": 90,
                        "timeline_start_frame": 0,
                        "source_audio_policy": "discard",
                        **bad_us,
                    },
                ],
            }
            plan_path = _make_plan_file(tmp_path, plan)
            with pytest.raises((UnsafePackageError, ValueError), match="Negative|must be >=|minimum"):
                load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())

    def test_source_out_less_than_in(self, tmp_path: Path):
        """source_out_us <= source_in_us raises error."""
        _make_asset(tmp_path, "video1.mp4")
        plan = {
            **SAMPLE_PLAN_3,
            "visual_items": [
                {
                    "item_id": "item-001",
                    "asset_id": "asset-001",
                    "media_type": "video",
                    "source_in_us": 3_000_000,
                    "source_out_us": 1_000_000,
                    "duration_frames": 90,
                    "timeline_start_frame": 0,
                    "source_audio_policy": "discard",
                },
            ],
        }
        plan_path = _make_plan_file(tmp_path, plan)
        with pytest.raises(UnsafePackageError, match="source_out_us must be >"):
            load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())

    def test_unknown_asset_id(self, tmp_path: Path):
        """Visual item referencing unknown asset_id raises error."""
        _make_asset(tmp_path, "video1.mp4")
        plan = {
            **SAMPLE_PLAN_3,
            "visual_items": [
                {
                    "item_id": "item-001",
                    "asset_id": "unknown-asset",
                    "media_type": "video",
                    "source_in_us": 0,
                    "source_out_us": 3_000_000,
                    "duration_frames": 90,
                    "timeline_start_frame": 0,
                    "source_audio_policy": "discard",
                },
            ],
        }
        plan_path = _make_plan_file(tmp_path, plan)
        with pytest.raises(UnsafePackageError, match="unknown asset_id"):
            load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())

    def test_forbidden_keys_rejected(self, tmp_path: Path):
        """Forbidden keys like ffmpeg, command, shell are rejected by schema validation."""
        _make_asset(tmp_path, "video1.mp4")
        for key in ("ffmpeg", "command", "shell"):
            plan = {**SAMPLE_PLAN_3, key: "/usr/bin/ffmpeg"}
            plan_path = _make_plan_file(tmp_path, plan)
            with pytest.raises((UnsafePackageError, ValueError), match="unsupported|Forbidden"):
                load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())

    def test_edit_plan_3_schema_versions(self):
        """EDIT_PLAN_3_SCHEMA_VERSIONS contains only 3.0."""
        assert EDIT_PLAN_3_SCHEMA_VERSIONS == {"3.0"}

    def test_missing_canvas_rejected(self, tmp_path: Path):
        """Missing canvas raises validation error."""
        _make_asset(tmp_path, "video1.mp4")
        plan = {k: v for k, v in SAMPLE_PLAN_3.items() if k != "canvas"}
        plan_path = _make_plan_file(tmp_path, plan)
        with pytest.raises((UnsafePackageError, ValueError), match="required"):
            load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())

    def test_missing_timebase_rejected(self, tmp_path: Path):
        """Missing timebase raises validation error (required in schema)."""
        _make_asset(tmp_path, "video1.mp4")
        plan = {k: v for k, v in SAMPLE_PLAN_3.items() if k != "timebase"}
        plan_path = _make_plan_file(tmp_path, plan)
        with pytest.raises((UnsafePackageError, ValueError), match="required"):
            load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())

    def test_missing_renderer_rejected(self, tmp_path: Path):
        """Missing renderer raises validation error."""
        _make_asset(tmp_path, "video1.mp4")
        plan = {k: v for k, v in SAMPLE_PLAN_3.items() if k != "renderer"}
        plan_path = _make_plan_file(tmp_path, plan)
        with pytest.raises((UnsafePackageError, ValueError), match="required"):
            load_and_validate_edit_plan_3(plan_path, tmp_path, FakeBackend())
