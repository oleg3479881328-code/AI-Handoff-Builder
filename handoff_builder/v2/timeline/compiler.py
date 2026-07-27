from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import UnsafePackageError
from ..plans.schema import deterministic_plan_hash, validate_payload


@dataclass(frozen=True, slots=True)
class NormalizedTimeline:
    """Render-ready normalized timeline, renderer-agnostic.

    All time values use rational timebase (fps_num/fps_den) for frames
    and microseconds for source positions. This is the authoritative
    intermediate representation produced by the Package Compiler.
    """
    payload: dict
    timeline_hash: str
    track_count: int
    total_duration_frames: int
    fps_num: int
    fps_den: int


def compile_normalized_timeline(
    edit_plan_payload: dict,
    resolved_assets: list[dict],
    *,
    fps_num: int = 30,
    fps_den: int = 1,
) -> NormalizedTimeline:
    """Compile a validated edit_plan 3.0 + resolved assets into Normalized Timeline 1.0.

    This is the authoritative compilation step. No renderer parses
    AI_EDIT_PACKAGE independently — all renderers consume Normalized Timeline.
    """
    schema_version = str(edit_plan_payload.get("schema_version", ""))
    if schema_version != "3.0":
        raise UnsafePackageError(
            f"Normalized Timeline compilation requires edit_plan 3.0, got {schema_version}"
        )

    validate_payload("edit_plan", "3.0", edit_plan_payload)

    # Build asset lookup from resolved assets
    asset_by_id: dict[str, dict] = {}
    for asset in resolved_assets:
        asset_id = str(asset["asset_id"])
        asset_by_id[asset_id] = asset

    # Build audio_items lookup by item_id
    audio_items_by_id: dict[str, dict] = {}
    for audio_item in edit_plan_payload.get("audio_items", []):
        item_id = str(audio_item["item_id"])
        audio_items_by_id[item_id] = audio_item

    # Build a single video track from visual_items
    items: list[dict] = []
    current_frame: int = 0

    for visual_item in edit_plan_payload.get("visual_items", []):
        asset_id = str(visual_item["asset_id"])
        asset_info = asset_by_id.get(asset_id)
        if asset_info is None:
            raise UnsafePackageError(
                f"Normalized Timeline: unresolved asset_id {asset_id}"
            )

        source_in_us = int(visual_item["source_in_us"])
        source_out_us = int(visual_item["source_out_us"])
        duration_frames = int(visual_item["duration_frames"])
        timeline_start_frame = int(visual_item.get("timeline_start_frame", current_frame))

        # Build normalized item
        normalized_item: dict = {
            "asset_id": asset_id,
            "source_path": str(asset_info.get("source_path", "")),
            "source_in_us": source_in_us,
            "source_out_us": source_out_us,
            "duration_frames": duration_frames,
            "timeline_start_frame": timeline_start_frame,
            "media_type": str(asset_info.get("media_type", "video")),
            "source_audio_policy": str(visual_item.get("source_audio_policy", "discard")),
        }

        # Audio item reference (from visual_item's audio_item_id)
        audio_item_id = visual_item.get("audio_item_id")
        if audio_item_id:
            audio_item = audio_items_by_id.get(str(audio_item_id))
            if audio_item:
                normalized_item["audio_item_id"] = str(audio_item_id)
                normalized_item["audio_source_path"] = str(
                    audio_item.get("source_path", "")
                )
                normalized_item["audio_source_in_us"] = int(
                    audio_item.get("source_in_us", 0)
                )
                normalized_item["audio_source_out_us"] = int(
                    audio_item.get("source_out_us", 0)
                )
                normalized_item["audio_gain_db"] = float(
                    audio_item.get("gain", 0.0)
                )

        # Effects (transform, crop)
        transform = visual_item.get("transform")
        if transform:
            normalized_item["transform"] = dict(transform)
        crop = visual_item.get("crop")
        if crop:
            normalized_item["crop"] = dict(crop)

        items.append(normalized_item)
        current_frame = timeline_start_frame + duration_frames

    total_duration_frames = current_frame

    tracks: list[dict] = [
        {
            "track_index": 0,
            "track_type": "video",
            "items": items,
        }
    ]

    timeline_payload: dict = {
        "schema_version": "1.0",
        "timeline": {
            "fps_num": fps_num,
            "fps_den": fps_den,
            "total_duration_frames": total_duration_frames,
            "tracks": tracks,
        },
        "source": {
            "edit_plan_schema_version": "3.0",
            "plan_id": str(edit_plan_payload.get("plan_id", "")),
        },
    }

    timeline_hash = deterministic_plan_hash(timeline_payload)

    return NormalizedTimeline(
        payload=timeline_payload,
        timeline_hash=timeline_hash,
        track_count=len(tracks),
        total_duration_frames=total_duration_frames,
        fps_num=fps_num,
        fps_den=fps_den,
    )
