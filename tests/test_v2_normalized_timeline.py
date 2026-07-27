"""Tests for Normalized Timeline 1.0 compilation."""

import json
from pathlib import Path

import pytest

from handoff_builder.v2.errors import UnsafePackageError
from handoff_builder.v2.timeline.compiler import (
    NormalizedTimeline,
    compile_normalized_timeline,
)

VALID_SHA256 = "abcdef0123456789abcdef0123456789abcdef0123456789abcdef0123456789"

SAMPLE_EDIT_PLAN_3 = {
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
            "media_type": "video",
        },
        {
            "asset_id": "asset-002",
            "media_type": "video",
        },
    ],
    "visual_items": [
        {
            "item_id": "item-001",
            "asset_id": "asset-001",
            "media_type": "video",
            "timeline_start_frame": 0,
            "duration_frames": 90,
            "source_in_us": 0,
            "source_out_us": 3_000_000,
            "source_audio_policy": "discard",
        },
        {
            "item_id": "item-002",
            "asset_id": "asset-002",
            "media_type": "video",
            "timeline_start_frame": 90,
            "duration_frames": 60,
            "source_in_us": 1_000_000,
            "source_out_us": 3_000_000,
            "source_audio_policy": "discard",
        },
    ],
    "audio_items": [],
    "renderer": {"primary_renderer": "davinci"},
}

RESOLVED_ASSETS = [
    {
        "asset_id": "asset-001",
        "source_path": "/workspace/analysis/assets/video1.mp4",
        "media_type": "video",
        "sha256": "aaa",
        "size_bytes": 1000,
    },
    {
        "asset_id": "asset-002",
        "source_path": "/workspace/analysis/assets/video2.mp4",
        "media_type": "video",
        "sha256": "bbb",
        "size_bytes": 2000,
    },
]


class TestCompileNormalizedTimeline:
    def test_basic_compilation(self):
        """Basic compilation produces correct Normalized Timeline."""
        result = compile_normalized_timeline(
            SAMPLE_EDIT_PLAN_3,
            RESOLVED_ASSETS,
            fps_num=30,
            fps_den=1,
        )
        assert isinstance(result, NormalizedTimeline)
        assert result.track_count == 1
        assert result.total_duration_frames == 150  # 90 + 60
        assert result.fps_num == 30
        assert result.fps_den == 1
        assert result.timeline_hash is not None
        assert len(result.timeline_hash) == 64

    def test_payload_structure(self):
        """Normalized Timeline payload has correct structure."""
        result = compile_normalized_timeline(
            SAMPLE_EDIT_PLAN_3,
            RESOLVED_ASSETS,
        )
        payload = result.payload
        assert payload["schema_version"] == "1.0"
        assert payload["source"]["edit_plan_schema_version"] == "3.0"
        assert payload["source"]["plan_id"] == "plan-001"
        timeline = payload["timeline"]
        assert timeline["fps_num"] == 30
        assert timeline["fps_den"] == 1
        assert timeline["total_duration_frames"] == 150
        assert len(timeline["tracks"]) == 1

    def test_track_items(self):
        """Track items have correct normalized fields."""
        result = compile_normalized_timeline(
            SAMPLE_EDIT_PLAN_3,
            RESOLVED_ASSETS,
        )
        track = result.payload["timeline"]["tracks"][0]
        assert track["track_type"] == "video"
        assert len(track["items"]) == 2

        # First item starts at frame 0
        item0 = track["items"][0]
        assert item0["asset_id"] == "asset-001"
        assert item0["source_in_us"] == 0
        assert item0["source_out_us"] == 3_000_000
        assert item0["duration_frames"] == 90
        assert item0["timeline_start_frame"] == 0
        assert item0["source_path"] == "/workspace/analysis/assets/video1.mp4"

        # Second item starts at frame 90
        item1 = track["items"][1]
        assert item1["asset_id"] == "asset-002"
        assert item1["timeline_start_frame"] == 90
        assert item1["duration_frames"] == 60

    def test_rejects_non_3_0(self):
        """Compilation rejects non-3.0 edit plans."""
        bad_plan = dict(SAMPLE_EDIT_PLAN_3, schema_version="2.0")
        with pytest.raises(UnsafePackageError, match="requires edit_plan 3.0"):
            compile_normalized_timeline(bad_plan, RESOLVED_ASSETS)

    def test_rejects_unresolved_asset(self):
        """Compilation rejects visual_items referencing unresolved assets."""
        bad_plan = {
            **SAMPLE_EDIT_PLAN_3,
            "visual_items": [
                {
                    "item_id": "item-001",
                    "asset_id": "asset-unknown",
                    "media_type": "video",
                    "timeline_start_frame": 0,
                    "duration_frames": 30,
                    "source_in_us": 0,
                    "source_out_us": 1_000_000,
                    "source_audio_policy": "discard",
                },
            ],
        }
        with pytest.raises(UnsafePackageError, match="unresolved asset_id"):
            compile_normalized_timeline(bad_plan, RESOLVED_ASSETS)

    def test_audio_item_reference(self):
        """Visual items with audio_item_id reference are resolved."""
        plan_with_audio = {
            **SAMPLE_EDIT_PLAN_3,
            "audio_items": [
                {
                    "item_id": "audio-001",
                    "audio_id": "music-001",
                    "role": "music",
                    "timeline_start_frame": 0,
                    "duration_frames": 90,
                    "source_in_us": 0,
                    "source_out_us": 3_000_000,
                    "gain": -3.0,
                },
            ],
            "visual_items": [
                {
                    "item_id": "item-001",
                    "asset_id": "asset-001",
                    "media_type": "video",
                    "timeline_start_frame": 0,
                    "duration_frames": 90,
                    "source_in_us": 0,
                    "source_out_us": 3_000_000,
                    "source_audio_policy": "discard",
                    "audio_item_id": "audio-001",
                },
            ],
        }
        result = compile_normalized_timeline(plan_with_audio, RESOLVED_ASSETS)
        item = result.payload["timeline"]["tracks"][0]["items"][0]
        assert item["audio_item_id"] == "audio-001"

    def test_deterministic_hash(self):
        """Same input produces same timeline hash."""
        a = compile_normalized_timeline(SAMPLE_EDIT_PLAN_3, RESOLVED_ASSETS)
        b = compile_normalized_timeline(SAMPLE_EDIT_PLAN_3, RESOLVED_ASSETS)
        assert a.timeline_hash == b.timeline_hash

    def test_empty_visual_items_rejected(self):
        """Empty visual_items are rejected by schema validation (minItems: 1)."""
        plan_empty = {
            **SAMPLE_EDIT_PLAN_3,
            "visual_items": [],
        }
        with pytest.raises((UnsafePackageError, ValueError), match="at least|minItems"):
            compile_normalized_timeline(plan_empty, RESOLVED_ASSETS)
