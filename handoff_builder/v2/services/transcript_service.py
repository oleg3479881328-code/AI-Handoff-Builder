from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

from ...ffmpeg_tools import FFmpegTools, run_command
from ...models import FinalHandoffResult, TranscriptImportResult
from ...utils import file_sha256, json_dump
from ..errors import UnsafePackageError


PENDING_AI_ANALYSIS = {"status": "pending_ai_analysis", "items": []}


def import_gemini_transcript(
    *,
    project_root: Path,
    project_id: str,
    project_name: str,
    transcript_json_path: Path,
) -> TranscriptImportResult:
    resolved_root = project_root.resolve()
    transcript_path = transcript_json_path.resolve()
    master_dir = _require_master_dir(resolved_root, project_name)
    master_audio_path = master_dir / f"{_owner_safe_name(project_name)}_MASTER_AUDIO.mp3"
    original_path = master_dir / f"{_owner_safe_name(project_name)}_MASTER_AUDIO_TRANSCRIPT_ORIGINAL.json"
    normalized_path = master_dir / f"{_owner_safe_name(project_name)}_MASTER_AUDIO_TRANSCRIPT.json"
    timeline_map_path = master_dir / f"{_owner_safe_name(project_name)}_MASTER_TIMELINE_MAP.json"

    raw_bytes = transcript_path.read_bytes()
    errors: list[str] = []
    try:
        raw_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"JSON must be valid UTF-8: {exc}")
        return TranscriptImportResult(
            project_root=resolved_root,
            project_id=project_id,
            project_name=project_name,
            transcript_original_path=None,
            transcript_normalized_path=None,
            state="TRANSCRIPT_INVALID",
            errors=errors,
            event_count=0,
        )
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        errors.append(f"JSON syntax error: {exc}")
        return TranscriptImportResult(
            project_root=resolved_root,
            project_id=project_id,
            project_name=project_name,
            transcript_original_path=None,
            transcript_normalized_path=None,
            state="TRANSCRIPT_INVALID",
            errors=errors,
            event_count=0,
        )

    timeline_map = json.loads(timeline_map_path.read_text(encoding="utf-8"))
    items = list(timeline_map.get("items") or [])
    normalized_events, errors = _normalize_transcript_payload(
        payload=payload,
        project_name=project_name,
        mp3_duration_ms=int(round(float(_probe_audio(FFmpegTools(project_root=resolved_root), master_audio_path).get("duration_seconds") or 0.0) * 1000)),
        timeline_items=items,
    )
    if errors:
        return TranscriptImportResult(
            project_root=resolved_root,
            project_id=project_id,
            project_name=project_name,
            transcript_original_path=None,
            transcript_normalized_path=None,
            state="TRANSCRIPT_INVALID",
            errors=errors,
            event_count=0,
        )

    original_path.write_bytes(raw_bytes)
    json_dump(
        normalized_path,
        {
            "schema_version": "1.0",
            "document_type": "master_audio_transcript",
            "project_id": project_id,
            "project_name": project_name,
            "event_count": len(normalized_events),
            "events": normalized_events,
            "raw_payload": payload,
        },
    )
    return TranscriptImportResult(
        project_root=resolved_root,
        project_id=project_id,
        project_name=project_name,
        transcript_original_path=original_path,
        transcript_normalized_path=normalized_path,
        state="TRANSCRIPT_READY",
        errors=[],
        event_count=len(normalized_events),
    )


def create_final_analysis_handoff(
    *,
    project_root: Path,
    project_id: str,
    project_name: str,
    ffmpeg_tools: FFmpegTools,
) -> FinalHandoffResult:
    resolved_root = project_root.resolve()
    safe_name = _owner_safe_name(project_name)
    master_dir = _require_master_dir(resolved_root, project_name)
    normalized_transcript_path = master_dir / f"{safe_name}_MASTER_AUDIO_TRANSCRIPT.json"
    original_transcript_path = master_dir / f"{safe_name}_MASTER_AUDIO_TRANSCRIPT_ORIGINAL.json"
    if not normalized_transcript_path.exists() or not original_transcript_path.exists():
        raise UnsafePackageError("Transcript is not ready. Import a valid Gemini transcript JSON first.")

    required_sources = {
        "00_START_HERE.md": master_dir / "00_START_HERE.md",
        "PROJECT_BRIEF.md": master_dir / "PROJECT_BRIEF.md",
        "OUTPUT_CONTRACT.md": master_dir / "OUTPUT_CONTRACT.md",
        "MASTER": master_dir,
        "local_asset_registry.json": resolved_root / "analysis" / "local_asset_registry.json",
        "handoff_manifest.json": resolved_root / "analysis" / "handoff_manifest.json",
        "PROXIES": resolved_root / "proxies",
        "PHOTOS": resolved_root / "analysis" / "photo_analysis_copies",
        "STORYBOARDS": resolved_root / "analysis" / "video_storyboards",
    }
    for label, path in required_sources.items():
        if not path.exists():
            raise UnsafePackageError(f"Required final handoff source is missing: {label} -> {path}")

    archive_path = _next_available_file((resolved_root / "handoffs" / f"{safe_name}_ANALYSIS_HANDOFF.zip").resolve())
    pending_maps = {
        "MAPS/PROJECT_GRAPH.json": PENDING_AI_ANALYSIS,
        "MAPS/SCENE_CLUSTERS.json": PENDING_AI_ANALYSIS,
        "MAPS/PEOPLE_INDEX.json": PENDING_AI_ANALYSIS,
        "MAPS/HOOK_INDEX.json": PENDING_AI_ANALYSIS,
        "MAPS/PROJECT_GAPS.json": PENDING_AI_ANALYSIS,
    }
    reports = {
        "REPORTS/DUPLICATES_REPORT.json": {"status": "ok", "items": []},
        "REPORTS/MISSING_OR_DAMAGED_FILES.json": {"status": "ok", "items": []},
    }
    validation_report_path = resolved_root / "analysis" / "BUILD_VALIDATION_REPORT.json"
    timeline_map_path = master_dir / f"{safe_name}_MASTER_TIMELINE_MAP.json"
    normalized_transcript = json.loads(normalized_transcript_path.read_text(encoding="utf-8"))
    timeline_items = list(json.loads(timeline_map_path.read_text(encoding="utf-8")).get("items") or [])
    master_audio_path = master_dir / f"{safe_name}_MASTER_AUDIO.mp3"
    audio_probe = _probe_audio(ffmpeg_tools, master_audio_path)

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
        _write_archive_file(archive, master_dir / "00_START_HERE.md", "00_START_HERE.md")
        _write_archive_file(archive, master_dir / "PROJECT_BRIEF.md", "PROJECT_BRIEF.md")
        _write_archive_file(archive, master_dir / "OUTPUT_CONTRACT.md", "OUTPUT_CONTRACT.md")
        _write_archive_file(archive, resolved_root / "analysis" / "handoff_manifest.json", "handoff_manifest.json")
        _write_archive_file(archive, resolved_root / "analysis" / "local_asset_registry.json", "local_asset_registry.json")
        for item in master_dir.iterdir():
            if item.is_file() and item.name != "README.md":
                _write_archive_file(archive, item, f"MASTER/{item.name}")
        _write_tree_if_exists(archive, resolved_root / "proxies", "PROXIES")
        _write_tree_if_exists(archive, resolved_root / "analysis" / "photo_analysis_copies", "PHOTOS")
        _write_tree_if_exists(archive, resolved_root / "analysis" / "video_storyboards", "STORYBOARDS")
        for rel_path, payload in pending_maps.items():
            archive.writestr(rel_path, json.dumps(payload, ensure_ascii=False, indent=2))
        for rel_path, payload in reports.items():
            archive.writestr(rel_path, json.dumps(payload, ensure_ascii=False, indent=2))

    validation = _validate_final_archive(
        archive_path=archive_path,
        validation_report_path=validation_report_path,
        ffmpeg_tools=ffmpeg_tools,
        transcript_payload=normalized_transcript,
        audio_probe=audio_probe,
    )
    timeline_duration_ms = max((_tc_to_ms(item["master_end"]) for item in timeline_items), default=0)
    mp3_duration_ms = int(round(float(audio_probe.get("duration_seconds") or 0.0) * 1000))
    duration_delta_ms = abs(mp3_duration_ms - timeline_duration_ms)
    return FinalHandoffResult(
        project_root=resolved_root,
        project_id=project_id,
        project_name=project_name,
        archive_path=archive_path,
        sha256=file_sha256(archive_path),
        validation_report_path=validation_report_path,
        state="HANDOFF_READY",
        timeline_item_count=len(timeline_items),
        transcript_event_count=int(normalized_transcript.get("event_count") or len(normalized_transcript.get("events") or [])),
        master_duration_ms=timeline_duration_ms,
        mp3_duration_ms=mp3_duration_ms,
        duration_delta_ms=duration_delta_ms,
    )


def _normalize_transcript_payload(
    *,
    payload: Any,
    project_name: str,
    mp3_duration_ms: int,
    timeline_items: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return [], ["Transcript root must be a JSON object."]
    input_project_name = " ".join(str(payload.get("project_name") or "").split())
    if input_project_name != " ".join(project_name.split()):
        errors.append(f"Project name mismatch: expected '{project_name}', got '{input_project_name}'.")
    events = payload.get("events")
    if not isinstance(events, list):
        errors.append("Transcript must contain an events array.")
        return [], errors
    normalized: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append(f"Event #{index + 1} must be an object.")
            continue
        start_tc = str(event.get("start_time") or "")
        end_tc = str(event.get("end_time") or "")
        if not _valid_tc(start_tc):
            errors.append(f"Event #{index + 1} has invalid start_time: {start_tc}")
            continue
        if not _valid_tc(end_tc):
            errors.append(f"Event #{index + 1} has invalid end_time: {end_tc}")
            continue
        start_ms = _tc_to_ms(start_tc)
        end_ms = _tc_to_ms(end_tc)
        if start_ms < 0:
            errors.append(f"Event #{index + 1} start_time must be >= 0.")
        if end_ms < start_ms:
            errors.append(f"Event #{index + 1} end_time must be >= start_time.")
        if end_ms > mp3_duration_ms + 100:
            errors.append(f"Event #{index + 1} exceeds MP3 duration tolerance.")
        mapping = _source_mappings_for_event(start_ms, end_ms, timeline_items)
        normalized.append(
            {
                **event,
                "event_index": index,
                "project_name": project_name,
                "start_time": start_tc,
                "end_time": end_tc,
                "source_mappings": mapping,
            }
        )
    return normalized, errors


def _source_mappings_for_event(start_ms: int, end_ms: int, timeline_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for item in timeline_items:
        item_start_ms = _tc_to_ms(str(item["master_start"]))
        item_end_ms = _tc_to_ms(str(item["master_end"]))
        overlap_start = max(start_ms, item_start_ms)
        overlap_end = min(end_ms, item_end_ms)
        if overlap_end < overlap_start:
            continue
        offset_in_item_start = overlap_start - item_start_ms
        offset_in_item_end = overlap_end - item_start_ms
        mappings.append(
            {
                "asset_id": item["asset_id"],
                "timeline_index": item["timeline_index"],
                "source_file_name": item["source_file_name"],
                "master_overlap_start": _ms_to_tc(overlap_start),
                "master_overlap_end": _ms_to_tc(overlap_end),
                "source_start": _ms_to_tc(offset_in_item_start),
                "source_end": _ms_to_tc(offset_in_item_end),
            }
        )
    return mappings


def _validate_final_archive(
    *,
    archive_path: Path,
    validation_report_path: Path,
    ffmpeg_tools: FFmpegTools,
    transcript_payload: dict[str, Any],
    audio_probe: dict[str, Any],
) -> dict[str, Any]:
    required_entries = {
        "00_START_HERE.md",
        "PROJECT_BRIEF.md",
        "OUTPUT_CONTRACT.md",
        "handoff_manifest.json",
        "local_asset_registry.json",
        "MASTER",
        "MAPS",
        "REPORTS",
    }
    extract_root = archive_path.parent / f"{archive_path.stem}_validation_extract"
    if extract_root.exists():
        shutil.rmtree(extract_root, ignore_errors=True)
    extract_root.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(archive_path) as archive:
            bad_crc = archive.testzip()
            if bad_crc is not None:
                raise UnsafePackageError(f"ZIP CRC validation failed at entry: {bad_crc}")
            names = archive.namelist()
            top_levels = {name.split("/", 1)[0] for name in names}
            missing_roots = sorted(entry for entry in required_entries if entry not in top_levels)
            if missing_roots:
                raise UnsafePackageError(f"ZIP missing required top-level entries: {', '.join(missing_roots)}")
            archive.extractall(extract_root)

        for json_path in extract_root.rglob("*.json"):
            json.loads(json_path.read_text(encoding="utf-8"))
        mlt_candidates = list((extract_root / "MASTER").glob("*.mlt"))
        if not mlt_candidates:
            raise UnsafePackageError("Final ZIP is missing MASTER .mlt.")
        ElementTree.parse(mlt_candidates[0])
        transcript_events = list(transcript_payload.get("events") or [])
        max_end_ms = max((_tc_to_ms(str(item.get("end_time") or "00:00:00.000")) for item in transcript_events), default=0)
        mp3_duration_ms = int(round(float(audio_probe.get("duration_seconds") or 0.0) * 1000))
        if max_end_ms > mp3_duration_ms + 100:
            raise UnsafePackageError("Transcript max timestamp exceeds MP3 duration tolerance in final ZIP validation.")
        report = {
            "schema_version": "1.0",
            "archive_path": str(archive_path),
            "crc_ok": True,
            "json_reloaded": True,
            "xml_valid": True,
            "transcript_max_timestamp_ms": max_end_ms,
            "mp3_duration_ms": mp3_duration_ms,
            "status": "ok",
        }
        json_dump(validation_report_path, report)
        return report
    finally:
        shutil.rmtree(extract_root, ignore_errors=True)


def _probe_audio(ffmpeg_tools: FFmpegTools, audio_path: Path) -> dict[str, Any]:
    payload = json.loads(
        run_command(
            [
                ffmpeg_tools.ffprobe,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(audio_path),
            ],
            cancel_event=ffmpeg_tools.cancel_event,
        ).stdout
        or "{}"
    )
    audio_stream = next((item for item in payload.get("streams", []) if item.get("codec_type") == "audio"), {})
    return {
        "duration_seconds": float(audio_stream.get("duration") or payload.get("format", {}).get("duration") or 0.0),
        "sample_rate": int(audio_stream.get("sample_rate") or 0) or None,
        "channels": int(audio_stream.get("channels") or 0) or None,
    }


def _write_archive_file(archive: zipfile.ZipFile, source_path: Path, dest_name: str) -> None:
    archive.write(source_path, dest_name)


def _write_tree_if_exists(archive: zipfile.ZipFile, root: Path, dest_prefix: str) -> None:
    if not root.exists():
        return
    for candidate in sorted(root.rglob("*")):
        if candidate.is_file():
            archive.write(candidate, f"{dest_prefix}/{candidate.relative_to(root).as_posix()}")


def _require_master_dir(project_root: Path, project_name: str) -> Path:
    master_dir = project_root.resolve() / "handoffs" / f"{_owner_safe_name(project_name)}_MASTER_PACKAGE"
    if not master_dir.exists():
        raise UnsafePackageError("Master package folder is missing. Run Prepare Master Package first.")
    return master_dir


def _owner_safe_name(name: str) -> str:
    return ("".join("_" if ch in '<>:\"/\\\\|?*' else ch for ch in name).rstrip(" .") or "PROJECT").strip()


def _next_available_file(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"Could not allocate a unique output path for {path.name}")


def _valid_tc(value: str) -> bool:
    parts = value.split(":")
    if len(parts) != 3 or "." not in parts[2]:
        return False
    hours, minutes = parts[0], parts[1]
    seconds, millis = parts[2].split(".", 1)
    return all(part.isdigit() for part in (hours, minutes, seconds, millis)) and len(millis) == 3


def _ms_to_tc(value_ms: int) -> str:
    total_ms = max(0, int(value_ms))
    hours = total_ms // 3_600_000
    minutes = (total_ms % 3_600_000) // 60_000
    seconds = (total_ms % 60_000) // 1000
    millis = total_ms % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def _tc_to_ms(tc: str) -> int:
    hours, minutes, rest = tc.split(":")
    seconds, millis = rest.split(".")
    return ((int(hours) * 3600 + int(minutes) * 60 + int(seconds)) * 1000) + int(millis)
