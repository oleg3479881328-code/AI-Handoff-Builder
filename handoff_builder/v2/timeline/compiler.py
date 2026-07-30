from __future__ import annotations

from dataclasses import dataclass

from ..errors import UnsafePackageError
from ..packages.guards import compute_content_hash
from ..plans.schema import validate_payload


@dataclass(frozen=True, slots=True)
class NormalizedTimeline:
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
    source_package_content_hash: str,
) -> NormalizedTimeline:
    schema_version = str(edit_plan_payload.get("schema_version", ""))
    if schema_version != "3.0":
        raise UnsafePackageError(
            f"Normalized Timeline compilation requires edit_plan 3.0, got {schema_version}"
        )

    validate_payload("edit_plan", "3.0", edit_plan_payload)

    asset_by_id = {str(asset["asset_id"]): asset for asset in resolved_assets}
    timebase = edit_plan_payload["timebase"]
    fps_num = int(timebase["fps_num"])
    fps_den = int(timebase["fps_den"])
    plan_version = int(edit_plan_payload["plan_version"])
    plan_id = str(edit_plan_payload["plan_id"])
    project_id = str(edit_plan_payload["project_id"])
    handoff_id = str(edit_plan_payload["handoff_id"])
    renderer = dict(edit_plan_payload["renderer"])

    visual_items: list[dict] = []
    audio_items: list[dict] = []
    text_items: list[dict] = []
    tracks_by_id: dict[str, dict] = {}
    max_end_frame = 0

    def ensure_track(track_id: str, track_type: str) -> None:
        if track_id not in tracks_by_id:
            tracks_by_id[track_id] = {
                "track_id": track_id,
                "track_type": track_type,
                "index": len(tracks_by_id),
            }

    for visual_item in edit_plan_payload.get("visual_items", []):
        asset_id = str(visual_item["asset_id"])
        asset_info = asset_by_id.get(asset_id)
        if asset_info is None:
            raise UnsafePackageError(f"Normalized Timeline: unresolved asset_id {asset_id}")
        track_id = str(visual_item["track_id"])
        timeline_start_frame = int(visual_item["timeline_start_frame"])
        duration_frames = int(visual_item["duration_frames"])
        max_end_frame = max(max_end_frame, timeline_start_frame + duration_frames)
        ensure_track(track_id, "video")
        item = {
            "item_id": str(visual_item["item_id"]),
            "asset_id": asset_id,
            "media_type": str(visual_item["media_type"]),
            "track_id": track_id,
            "timeline_start_frame": timeline_start_frame,
            "duration_frames": duration_frames,
            "source_in_us": int(visual_item["source_in_us"]),
            "source_out_us": int(visual_item["source_out_us"]),
            "source_audio_policy": str(visual_item["source_audio_policy"]),
            "resolved_source_path": str(asset_info["source_path"]),
            "resolved_sha256": str(asset_info["sha256"]),
            "resolved_size_bytes": int(asset_info["size_bytes"]),
        }
        if visual_item.get("transform"):
            item["transform"] = dict(visual_item["transform"])
        if visual_item.get("crop"):
            item["crop"] = dict(visual_item["crop"])
        visual_items.append(item)

    for audio_item in edit_plan_payload.get("audio_items", []):
        audio_id = str(audio_item["audio_id"])
        asset_info = asset_by_id.get(audio_id)
        if asset_info is None:
            raise UnsafePackageError(f"Normalized Timeline: unresolved audio asset_id {audio_id}")
        track_id = str(audio_item.get("track_id") or f"audio:{audio_item['role']}:{audio_id}")
        ensure_track(track_id, "audio")
        timeline_start_frame = int(audio_item["timeline_start_frame"])
        duration_frames = int(audio_item["duration_frames"])
        max_end_frame = max(max_end_frame, timeline_start_frame + duration_frames)
        audio_items.append(
            {
                "item_id": str(audio_item["item_id"]),
                "audio_id": audio_id,
                "role": str(audio_item["role"]),
                "track_id": track_id,
                "timeline_start_frame": timeline_start_frame,
                "duration_frames": duration_frames,
                "source_in_us": int(audio_item.get("source_in_us", 0)),
                "source_out_us": int(audio_item.get("source_out_us", 0)),
                "gain": float(audio_item.get("gain", 0.0)),
                "fade_in_ms": int(audio_item.get("fade_in_ms", 0)),
                "fade_out_ms": int(audio_item.get("fade_out_ms", 0)),
                "resolved_audio_path": str(asset_info["source_path"]),
                "resolved_sha256": str(asset_info["sha256"]),
                "resolved_size_bytes": int(asset_info["size_bytes"]),
            }
        )

    for text_item in edit_plan_payload.get("text_items", []):
        timeline_start_frame = int(text_item["timeline_start_frame"])
        duration_frames = int(text_item["duration_frames"])
        max_end_frame = max(max_end_frame, timeline_start_frame + duration_frames)
        ensure_track("subtitle:default", "subtitle")
        text_items.append(
            {
                "item_id": str(text_item["item_id"]),
                "text": str(text_item["text"]),
                "timeline_start_frame": timeline_start_frame,
                "duration_frames": duration_frames,
            }
        )

    timeline_payload = {
        "schema_version": "1.0",
        "timeline_id": f"{project_id}:{plan_id}:{plan_version}",
        "project_id": project_id,
        "handoff_id": handoff_id,
        "plan_id": plan_id,
        "plan_version": plan_version,
        "source_package_content_hash": source_package_content_hash,
        "normalized_timeline_hash": "0" * 64,
        "primary_renderer": "shotcut",
        "timebase": {"fps_num": fps_num, "fps_den": fps_den},
        "canvas": dict(edit_plan_payload["canvas"]),
        "tracks": list(tracks_by_id.values()),
        "visual_items": visual_items,
        "audio_items": audio_items,
        "text_items": text_items,
        "renderer_requirements": renderer,
    }
    timeline_hash = compute_content_hash(
        timeline_payload,
        self_hash_field="normalized_timeline_hash",
    )
    timeline_payload["normalized_timeline_hash"] = timeline_hash
    validate_payload("normalized_timeline", "1.0", timeline_payload)
    return NormalizedTimeline(
        payload=timeline_payload,
        timeline_hash=timeline_hash,
        track_count=len(tracks_by_id),
        total_duration_frames=max_end_frame,
        fps_num=fps_num,
        fps_den=fps_den,
    )
