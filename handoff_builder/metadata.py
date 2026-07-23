from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
from dataclasses import dataclass
from collections import defaultdict
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image

from .ffmpeg_tools import FFmpegError, run_command
from .models import AssetRecord, BuilderConfig
from .utils import find_executable


METADATA_SCHEMA_VERSION = "1.0"
_GPS_TAG_ID = next(key for key, value in ExifTags.TAGS.items() if value == "GPSInfo")
_GPS_NAME_BY_ID = ExifTags.GPSTAGS
_WHATSAPP_RE = re.compile(
    r"(?i)(?:img|vid)-(?P<date>\d{8})-wa\d+|"
    r"(?:whatsapp|wa)[ _-]+(?:image|video)[ _-]+(?P<date2>\d{4}-\d{2}-\d{2})"
    r"[ _-]+at[ _-]+(?P<time2>\d{1,2}\.\d{2}\.\d{2})(?:[ _-]*(?P<ampm>AM|PM))?"
)
_GENERIC_FILENAME_DT_RE = re.compile(
    r"(?P<year>20\d{2})[-_]?((?P<month>\d{2})[-_]?((?P<day>\d{2})))(?:[T _-]?(?P<hour>\d{2})[._-]?(?P<minute>\d{2})(?:[._-]?(?P<second>\d{2}))?)?"
)


@dataclass(slots=True)
class MetadataBuildResult:
    raw_records: list[dict[str, Any]]
    normalized_records: list[dict[str, Any]]
    local_asset_registry: dict[str, Any]
    device_clock_profiles: dict[str, Any]
    chronology_report: dict[str, Any]
    location_clusters: dict[str, Any]
    warnings_payload: dict[str, Any]
    coverage_summary: dict[str, Any]
    tool_status: dict[str, Any]


class AssetMetadataBuilder:
    def __init__(self, config: BuilderConfig, *, project_root: Path | None = None) -> None:
        self.config = config
        self.project_root = project_root

    def build(self, assets: list[AssetRecord]) -> MetadataBuildResult:
        tool_status = self._detect_tools()
        warnings: list[dict[str, Any]] = []
        exiftool_map = self._run_exiftool(assets, tool_status, warnings)

        raw_records: list[dict[str, Any]] = []
        normalized_records: list[dict[str, Any]] = []
        normalized_by_asset_id: dict[str, dict[str, Any]] = {}

        for source_index, asset in enumerate(assets):
            raw_record, normalized_record = self._build_asset_record(
                asset,
                source_index=source_index,
                exiftool_payload=exiftool_map.get(asset.source_path),
                tool_status=tool_status,
                warnings=warnings,
            )
            raw_records.append(raw_record)
            normalized_records.append(normalized_record)
            normalized_by_asset_id[asset.asset_id] = normalized_record

            asset.metadata_status = normalized_record["metadata_status"]
            asset.capture_time_iso = normalized_record.get("normalized_capture_time")
            asset.capture_time_source = normalized_record.get("capture_time_source")
            asset.capture_time_confidence = normalized_record.get("time_confidence")
            asset.timezone_source = normalized_record.get("timezone_source")
            asset.gps_present = bool(normalized_record.get("location", {}).get("latitude") is not None)
            asset.location_confidence = normalized_record.get("location_confidence")
            asset.device_id = normalized_record.get("device_id")

        location_clusters = self._build_location_clusters(normalized_records)
        cluster_map = {
            item["asset_id"]: item["location_cluster_id"]
            for item in location_clusters["clusters"]
            for _ in item["members"]
        }
        member_cluster_map = {}
        for item in location_clusters["clusters"]:
            for member in item["members"]:
                member_cluster_map[member] = item["location_cluster_id"]
        for asset in assets:
            cluster_id = member_cluster_map.get(asset.asset_id)
            asset.location_cluster_id = cluster_id
            normalized_by_asset_id[asset.asset_id]["location_cluster_id"] = cluster_id

        chronology_report = self._build_chronology(normalized_records)
        for entry in chronology_report["assets"]:
            record = normalized_by_asset_id[entry["asset_id"]]
            record["chronology_rank"] = entry["chronology_rank"]
            asset = next(item for item in assets if item.asset_id == entry["asset_id"])
            asset.chronology_rank = entry["chronology_rank"]

        device_clock_profiles = self._build_device_profiles(normalized_records)
        coverage_summary = self._build_coverage_summary(normalized_records, warnings, tool_status)
        warnings_payload = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "gps_export_mode": self.config.gps_export_mode,
            "tool_status": tool_status,
            "warnings": warnings,
        }
        local_asset_registry = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "source_path": asset.source_path,
                    "relative_source_path": asset.relative_source_path,
                    "original_name": asset.original_name,
                }
                for asset in assets
            ],
        }
        return MetadataBuildResult(
            raw_records=[self._sanitize_raw_record_for_export(item) for item in raw_records],
            normalized_records=[self._sanitize_normalized_record_for_export(item) for item in normalized_records],
            local_asset_registry=local_asset_registry,
            device_clock_profiles=device_clock_profiles,
            chronology_report=chronology_report,
            location_clusters=location_clusters,
            warnings_payload=warnings_payload,
            coverage_summary=coverage_summary,
            tool_status=tool_status,
        )

    def _detect_tools(self) -> dict[str, Any]:
        exiftool_path = self._find_optional_executable("exiftool")
        ffprobe_path = self._find_optional_executable("ffprobe")
        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "exiftool": {
                "available": bool(exiftool_path),
                "path": exiftool_path,
                "status": "available" if exiftool_path else "missing",
            },
            "ffprobe": {
                "available": bool(ffprobe_path),
                "path": ffprobe_path,
                "status": "available" if ffprobe_path else "missing",
            },
        }

    def _find_optional_executable(self, name: str) -> str | None:
        try:
            return find_executable(name, self.project_root)
        except FileNotFoundError:
            return None

    def _run_exiftool(
        self,
        assets: list[AssetRecord],
        tool_status: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        if not tool_status["exiftool"]["available"]:
            warnings.append(
                self._warning(
                    code="exiftool_unavailable",
                    severity="warning",
                    message="ExifTool is unavailable; continuing with Pillow, ffprobe, and filesystem fallbacks.",
                )
            )
            return {}
        result: dict[str, dict[str, Any]] = {}
        grouped_assets: dict[Path, list[AssetRecord]] = defaultdict(list)
        for asset in assets:
            grouped_assets[Path(asset.source_path).resolve().parent].append(asset)

        exiftool_errors: list[str] = []
        exiftool_env = os.environ.copy()
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            exiftool_env.pop(key, None)

        for parent_dir, group in grouped_assets.items():
            args = [
                str(tool_status["exiftool"]["path"]),
                "-json",
                "-n",
                "-G",
                "-api",
                "largefilesupport=1",
            ]
            args.extend(Path(asset.source_path).name for asset in group)
            try:
                completed = run_command(args, cancel_event=None, cwd=parent_dir, env=exiftool_env)
                payload = json.loads(completed.stdout or "[]")
            except (FFmpegError, json.JSONDecodeError) as exc:
                exiftool_errors.append(f"{parent_dir}: {exc}")
                warnings.append(
                    self._warning(
                        code="exiftool_failed",
                        severity="warning",
                        message=f"ExifTool failed in {parent_dir}; continuing with fallbacks. {exc}",
                    )
                )
                continue

            for item in payload:
                source_file = str(item.get("SourceFile") or "")
                if source_file:
                    result[str((parent_dir / source_file).resolve())] = item

        if exiftool_errors and not result:
            tool_status["exiftool"]["status"] = "error"
            tool_status["exiftool"]["error"] = "\n".join(exiftool_errors)
        elif exiftool_errors:
            tool_status["exiftool"]["group_errors"] = exiftool_errors
        return result

    def _build_asset_record(
        self,
        asset: AssetRecord,
        *,
        source_index: int,
        exiftool_payload: dict[str, Any] | None,
        tool_status: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        path = Path(asset.source_path)
        pillow_payload = self._extract_pillow_metadata(path) if asset.media_type == "photo" else {}
        ffprobe_payload = self._extract_ffprobe_metadata(path, tool_status, warnings) if asset.media_type == "video" else {}
        raw_record = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "asset_id": asset.asset_id,
            "original_name": asset.original_name,
            "relative_source_path": asset.relative_source_path,
            "media_type": asset.media_type,
            "tool_sources": {
                "exiftool": bool(exiftool_payload),
                "pillow": bool(pillow_payload),
                "ffprobe": bool(ffprobe_payload),
                "filesystem": True,
            },
            "exiftool": exiftool_payload or {},
            "pillow": pillow_payload,
            "ffprobe": ffprobe_payload,
            "filesystem": self._filesystem_times(path),
        }
        normalized_record = self._normalize_asset_record(
            asset,
            raw_record=raw_record,
            source_index=source_index,
            warnings=warnings,
        )
        return raw_record, normalized_record

    def _extract_pillow_metadata(self, path: Path) -> dict[str, Any]:
        try:
            with Image.open(path) as image:
                exif = image.getexif()
                if not exif:
                    return {}
                payload: dict[str, Any] = {}
                gps_ifd: dict[str, Any] = {}
                get_ifd = getattr(exif, "get_ifd", None)
                if callable(get_ifd):
                    try:
                        raw_gps_ifd = get_ifd(_GPS_TAG_ID)
                    except Exception:
                        raw_gps_ifd = None
                    if isinstance(raw_gps_ifd, dict):
                        gps_ifd = {
                            _GPS_NAME_BY_ID.get(gps_key, str(gps_key)): self._json_safe_value(gps_value)
                            for gps_key, gps_value in raw_gps_ifd.items()
                        }
                for tag_id, value in exif.items():
                    name = ExifTags.TAGS.get(tag_id, str(tag_id))
                    if tag_id == _GPS_TAG_ID:
                        if gps_ifd:
                            payload[name] = gps_ifd
                        elif isinstance(value, dict):
                            gps_payload: dict[str, Any] = {}
                            for gps_key, gps_value in value.items():
                                gps_payload[_GPS_NAME_BY_ID.get(gps_key, str(gps_key))] = self._json_safe_value(gps_value)
                            payload[name] = gps_payload
                    else:
                        payload[name] = self._json_safe_value(value)
                return payload
        except Exception:
            return {}

    def _extract_ffprobe_metadata(
        self,
        path: Path,
        tool_status: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ffprobe_path = tool_status["ffprobe"]["path"]
        if not ffprobe_path:
            return {}
        try:
            completed = run_command(
                [
                    str(ffprobe_path),
                    "-v",
                    "error",
                    "-show_format",
                    "-show_streams",
                    "-of",
                    "json",
                    str(path),
                ],
                cancel_event=None,
            )
            return json.loads(completed.stdout or "{}")
        except (FFmpegError, json.JSONDecodeError) as exc:
            warnings.append(
                self._warning(
                    asset_id=self._stable_asset_key(path),
                    code="ffprobe_metadata_failed",
                    severity="warning",
                    message=f"ffprobe metadata extraction failed for {path.name}: {exc}",
                )
            )
            return {}

    def _normalize_asset_record(
        self,
        asset: AssetRecord,
        *,
        raw_record: dict[str, Any],
        source_index: int,
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        exiftool_payload = raw_record["exiftool"]
        pillow_payload = raw_record["pillow"]
        ffprobe_payload = raw_record["ffprobe"]
        filesystem = raw_record["filesystem"]

        capture = self._resolve_capture_time(
            asset,
            exiftool_payload=exiftool_payload,
            pillow_payload=pillow_payload,
            ffprobe_payload=ffprobe_payload,
            filesystem=filesystem,
            warnings=warnings,
        )
        gps_raw = self._resolve_gps(exiftool_payload, pillow_payload)
        exported_location = self._apply_gps_mode(gps_raw)
        if not gps_raw:
            warnings.append(
                self._warning(
                    asset_id=asset.asset_id,
                    code="gps_missing",
                    severity="info",
                    message=f"No GPS metadata for {asset.original_name}.",
                )
            )

        device = self._resolve_device(exiftool_payload, pillow_payload, ffprobe_payload, asset)
        metadata_status = self._metadata_status(capture["source"], gps_raw, device["device_id"], raw_record)

        record = {
            "schema_version": METADATA_SCHEMA_VERSION,
            "asset_id": asset.asset_id,
            "metadata_status": metadata_status,
            "media_type": asset.media_type,
            "original_name": asset.original_name,
            "relative_source_path": asset.relative_source_path,
            "source_order_index": source_index,
            "capture_time_raw": capture["raw"],
            "capture_time_source": capture["source"],
            "capture_time_corrected": capture["project"],
            "capture_time_utc": capture["utc"],
            "capture_time_project": capture["project"],
            "normalized_capture_time": capture["normalized"],
            "normalized_capture_time_epoch_ms": capture["epoch_ms"],
            "time_source": capture["source"],
            "time_confidence": capture["confidence"],
            "timezone_raw": capture["timezone_raw"],
            "timezone_offset_minutes": capture["timezone_offset_minutes"],
            "timezone_source": capture["timezone_source"],
            "clock_offset_ms": 0,
            "device_id": device["device_id"],
            "device_make": device["make"],
            "device_model": device["model"],
            "camera_make": device["make"],
            "camera_model": device["model"],
            "lens_model": device["lens_model"],
            "gps_export_mode": self.config.gps_export_mode,
            "gps_raw": self._gps_payload_only(gps_raw),
            "gps_source": gps_raw["source"] if gps_raw else None,
            "location": {
                "cluster_id": None,
                "export_mode": self.config.gps_export_mode,
                "source": gps_raw["source"] if gps_raw else None,
                "confidence": self._location_confidence(gps_raw),
                **self._location_payload(exported_location),
            },
            "location_source": gps_raw["source"] if gps_raw else None,
            "location_confidence": self._location_confidence(gps_raw),
            "location_cluster_id": None,
            "chronology_rank": None,
            "filename_time_hint": capture["filename_hint"],
            "filename_time_has_clock": bool(capture["filename_hint"] and capture["filename_hint"].get("has_clock_time")),
            "warnings": capture["warning_codes"],
            "sources": capture["sources"],
        }
        return record

    def _resolve_capture_time(
        self,
        asset: AssetRecord,
        *,
        exiftool_payload: dict[str, Any],
        pillow_payload: dict[str, Any],
        ffprobe_payload: dict[str, Any],
        filesystem: dict[str, Any],
        warnings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        warning_codes: list[str] = []
        sources: list[str] = []
        candidates = self._time_candidates(exiftool_payload, pillow_payload, ffprobe_payload)
        raw_value = None
        normalized = None
        capture_time_utc = None
        capture_time_project = None
        timezone_offset_minutes = None
        timezone_raw = None
        timezone_source = None
        source = "missing"
        confidence = None
        epoch_ms = None

        if candidates:
            best = candidates[0]
            raw_value = best["raw"]
            normalized = best["normalized"]
            capture_time_utc = best["utc"]
            capture_time_project = best["project"]
            timezone_offset_minutes = best["timezone_offset_minutes"]
            timezone_raw = best["timezone_raw"]
            timezone_source = best["timezone_source"]
            source = best["source"]
            confidence = best["confidence"]
            epoch_ms = best["epoch_ms"]
            sources.append(source)
            if best.get("conflict"):
                warning_codes.append("timestamp_conflict")
                warnings.append(
                    self._warning(
                        asset_id=asset.asset_id,
                        code="timestamp_conflict",
                        severity="warning",
                        message=f"Conflicting timestamp candidates for {asset.original_name}; used {source}.",
                    )
                )
            if timezone_offset_minutes is None:
                warning_codes.append("timezone_unknown")
                warnings.append(
                    self._warning(
                        asset_id=asset.asset_id,
                        code="timezone_unknown",
                        severity="warning",
                        message=f"Timezone is unknown for {asset.original_name}.",
                    )
                )
        else:
            filename_hint = self._filename_hint(asset.original_name)
            if filename_hint:
                raw_value = filename_hint["raw"]
                normalized = filename_hint["normalized"]
                capture_time_project = filename_hint["normalized"]
                capture_time_utc = filename_hint.get("utc")
                source = "filename"
                confidence = filename_hint["confidence"]
                epoch_ms = filename_hint["epoch_ms"]
                timezone_source = None
                warning_codes.append("filename_fallback")
                sources.append("filename")
                warnings.append(
                    self._warning(
                        asset_id=asset.asset_id,
                        code="filename_fallback",
                        severity="warning",
                        message=f"Used filename timestamp fallback for {asset.original_name}.",
                    )
                )
            else:
                raw_value = filesystem["modified_at"]
                normalized = filesystem["modified_at"]
                capture_time_utc = filesystem["modified_at"]
                capture_time_project = filesystem["modified_at"]
                source = "filesystem"
                confidence = 0.2
                epoch_ms = self._iso_to_epoch_ms(filesystem["modified_at"])
                warning_codes.append("filesystem_fallback")
                sources.append("filesystem")
                warnings.append(
                    self._warning(
                        asset_id=asset.asset_id,
                        code="filesystem_fallback",
                        severity="warning",
                        message=f"Used filesystem timestamp fallback for {asset.original_name}.",
                    )
                )

        return {
            "raw": raw_value,
            "utc": capture_time_utc,
            "project": capture_time_project,
            "normalized": normalized,
            "epoch_ms": epoch_ms,
            "source": source,
            "confidence": confidence,
            "timezone_raw": timezone_raw,
            "timezone_offset_minutes": timezone_offset_minutes,
            "timezone_source": timezone_source,
            "warning_codes": warning_codes,
            "sources": sources,
            "filename_hint": self._filename_hint(asset.original_name),
        }

    def _time_candidates(
        self,
        exiftool_payload: dict[str, Any],
        pillow_payload: dict[str, Any],
        ffprobe_payload: dict[str, Any],
    ) -> list[dict[str, Any]]:
        candidates: list[dict[str, Any]] = []
        exif_specs = [
            ("DateTimeOriginal", "OffsetTimeOriginal"),
            ("CreateDate", "OffsetTime"),
            ("DateTimeDigitized", "OffsetTimeDigitized"),
            ("MediaCreateDate", None),
            ("TrackCreateDate", None),
            ("CreationDate", None),
        ]
        for time_tag, offset_tag in exif_specs:
            raw_value = self._lookup_tag(exiftool_payload, time_tag) or pillow_payload.get(time_tag)
            if not raw_value:
                continue
            offset_value = self._lookup_tag(exiftool_payload, offset_tag) if offset_tag else None
            candidate = self._normalize_datetime_candidate(
                raw_value,
                source="metadata",
                confidence=0.95,
                timezone_value=offset_value,
                timezone_source=offset_tag if offset_value else None,
            )
            if candidate:
                candidates.append(candidate)

        ffprobe_tags = ffprobe_payload.get("format", {}).get("tags", {})
        for key in ("creation_time", "com.apple.quicktime.creationdate", "date"):
            raw_value = ffprobe_tags.get(key)
            if not raw_value:
                continue
            candidate = self._normalize_datetime_candidate(
                raw_value,
                source="ffprobe",
                confidence=0.8,
                timezone_value=None,
                timezone_source="embedded" if ("Z" in str(raw_value) or "+" in str(raw_value)) else None,
            )
            if candidate:
                candidates.append(candidate)

        by_value = {item["normalized"]: item for item in candidates if item["normalized"]}
        if len(by_value) > 1:
            for item in candidates:
                item["conflict"] = True
        priority = {"metadata": 0, "ffprobe": 1}
        return sorted(
            candidates,
            key=lambda item: (
                priority.get(item["source"], 9),
                0 if item["timezone_offset_minutes"] is not None else 1,
                item["normalized"] or "",
            ),
        )

    def _lookup_tag(self, payload: dict[str, Any], suffix: str | None) -> Any:
        if not payload or not suffix:
            return None
        for key, value in payload.items():
            if key.endswith(f":{suffix}") or key == suffix:
                return value
        return None

    def _normalize_datetime_candidate(
        self,
        raw_value: Any,
        *,
        source: str,
        confidence: float,
        timezone_value: Any,
        timezone_source: str | None,
    ) -> dict[str, Any] | None:
        if raw_value is None:
            return None
        parsed = self._parse_datetime(raw_value, timezone_value)
        if not parsed:
            return None
        return {
            "raw": str(raw_value),
            "normalized": parsed["iso"],
            "utc": parsed["utc"],
            "project": parsed["project"],
            "epoch_ms": parsed["epoch_ms"],
            "source": source,
            "confidence": confidence if parsed["timezone_offset_minutes"] is not None else round(confidence - 0.15, 3),
            "timezone_raw": str(timezone_value) if timezone_value not in (None, "") else None,
            "timezone_offset_minutes": parsed["timezone_offset_minutes"],
            "timezone_source": timezone_source,
        }

    def _parse_datetime(self, raw_value: Any, timezone_value: Any = None) -> dict[str, Any] | None:
        text = str(raw_value).strip()
        if not text or text.startswith("0000:00:00"):
            return None
        normalized_text = text.replace("Z", "+00:00")
        normalized_text = normalized_text.replace(" UTC", "+00:00")
        if re.match(r"^\d{4}:\d{2}:\d{2} ", normalized_text):
            normalized_text = normalized_text.replace(":", "-", 2)
        if re.match(r"^\d{4}-\d{2}-\d{2}T", normalized_text) is None and " " in normalized_text:
            normalized_text = normalized_text.replace(" ", "T", 1)

        tzinfo = self._parse_timezone(timezone_value)
        try:
            parsed = dt.datetime.fromisoformat(normalized_text)
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y:%m:%d %H:%M:%S"):
                try:
                    parsed = dt.datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
        if parsed.tzinfo is None and tzinfo is not None:
            parsed = parsed.replace(tzinfo=tzinfo)
        iso = parsed.isoformat(timespec="seconds")
        return {
            "iso": iso,
            "utc": parsed.astimezone(dt.timezone.utc).isoformat(timespec="seconds") if parsed.tzinfo else None,
            "project": iso,
            "epoch_ms": self._iso_to_epoch_ms(iso) if parsed.tzinfo else None,
            "timezone_offset_minutes": int(parsed.utcoffset().total_seconds() // 60) if parsed.tzinfo else None,
        }

    def _parse_timezone(self, timezone_value: Any) -> dt.tzinfo | None:
        if timezone_value in (None, ""):
            return None
        match = re.match(r"^(?P<sign>[+-])(?P<hours>\d{2}):?(?P<minutes>\d{2})$", str(timezone_value).strip())
        if not match:
            return None
        sign = 1 if match.group("sign") == "+" else -1
        minutes = sign * (int(match.group("hours")) * 60 + int(match.group("minutes")))
        return dt.timezone(dt.timedelta(minutes=minutes))

    def _resolve_gps(self, exiftool_payload: dict[str, Any], pillow_payload: dict[str, Any]) -> dict[str, Any] | None:
        lat = self._lookup_tag(exiftool_payload, "GPSLatitude")
        lon = self._lookup_tag(exiftool_payload, "GPSLongitude")
        alt = self._lookup_tag(exiftool_payload, "GPSAltitude")
        if lat is not None and lon is not None:
            return {
                "latitude": float(lat),
                "longitude": float(lon),
                "altitude": float(alt) if alt is not None else None,
                "source": "EXIF:GPSLatitude/GPSLongitude",
            }
        gps = pillow_payload.get("GPSInfo") or {}
        if not gps:
            return None
        latitude = self._gps_to_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
        longitude = self._gps_to_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
        if latitude is None or longitude is None:
            return None
        altitude_value = gps.get("GPSAltitude")
        try:
            altitude = float(altitude_value) if altitude_value is not None else None
        except Exception:
            altitude = None
        return {
            "latitude": latitude,
            "longitude": longitude,
            "altitude": altitude,
            "source": "Pillow:GPSInfo",
        }

    def _gps_to_decimal(self, value: Any, ref: Any) -> float | None:
        if value is None:
            return None
        parts = list(value)
        if len(parts) != 3:
            return None
        degrees = self._rational_to_float(parts[0])
        minutes = self._rational_to_float(parts[1])
        seconds = self._rational_to_float(parts[2])
        if None in (degrees, minutes, seconds):
            return None
        decimal = degrees + minutes / 60 + seconds / 3600
        if str(ref).upper() in {"S", "W"}:
            decimal *= -1
        return decimal

    def _rational_to_float(self, value: Any) -> float | None:
        try:
            if isinstance(value, tuple) and len(value) == 2:
                return float(value[0]) / float(value[1])
            return float(value)
        except Exception:
            return None

    def _apply_gps_mode(self, gps_raw: dict[str, Any] | None) -> dict[str, Any] | None:
        if not gps_raw or self.config.gps_export_mode == "excluded":
            return None
        if self.config.gps_export_mode == "exact":
            return {
                "latitude": float(gps_raw["latitude"]),
                "longitude": float(gps_raw["longitude"]),
                "altitude": float(gps_raw["altitude"]) if gps_raw.get("altitude") is not None else None,
            }
        if self.config.gps_export_mode == "rounded":
            return {
                "latitude": round(float(gps_raw["latitude"]), 3),
                "longitude": round(float(gps_raw["longitude"]), 3),
                "altitude": round(float(gps_raw["altitude"]), 1) if gps_raw.get("altitude") is not None else None,
            }
        return {
            "latitude": None,
            "longitude": None,
            "altitude": None,
            "venue_label": f"cluster_{round(float(gps_raw['latitude']), 2)}_{round(float(gps_raw['longitude']), 2)}",
        }

    def _resolve_device(
        self,
        exiftool_payload: dict[str, Any],
        pillow_payload: dict[str, Any],
        ffprobe_payload: dict[str, Any],
        asset: AssetRecord,
    ) -> dict[str, Any]:
        make = self._lookup_tag(exiftool_payload, "Make") or pillow_payload.get("Make")
        model = self._lookup_tag(exiftool_payload, "Model") or pillow_payload.get("Model")
        lens_model = self._lookup_tag(exiftool_payload, "LensModel") or pillow_payload.get("LensModel")
        if asset.media_type == "video":
            ffprobe_tags = ffprobe_payload.get("format", {}).get("tags", {})
            make = make or ffprobe_tags.get("com.apple.quicktime.make")
            model = model or ffprobe_tags.get("com.apple.quicktime.model")
            lens_model = lens_model or ffprobe_tags.get("com.apple.quicktime.lens_model")
        device_id = None
        if make or model:
            device_id = hashlib.sha1(f"{make}|{model}|{asset.media_type}".encode("utf-8")).hexdigest()[:12]
        return {
            "device_id": device_id,
            "make": str(make) if make else None,
            "model": str(model) if model else None,
            "lens_model": str(lens_model) if lens_model else None,
        }

    def _metadata_status(
        self,
        time_source: str,
        gps_raw: dict[str, Any] | None,
        device_id: str | None,
        raw_record: dict[str, Any],
    ) -> str:
        if raw_record["tool_sources"]["exiftool"] or raw_record["tool_sources"]["pillow"] or raw_record["tool_sources"]["ffprobe"]:
            if time_source != "missing":
                return "ok" if gps_raw or device_id else "partial"
            return "partial"
        if time_source == "filesystem":
            return "missing"
        return "partial"

    def _build_location_clusters(self, normalized_records: list[dict[str, Any]]) -> dict[str, Any]:
        clusters: dict[tuple[float, float], list[dict[str, Any]]] = {}
        for record in normalized_records:
            gps = record.get("gps_raw")
            if not gps or "latitude" not in gps or "longitude" not in gps:
                continue
            key = (round(float(gps["latitude"]), 2), round(float(gps["longitude"]), 2))
            clusters.setdefault(key, []).append(record)
        items = []
        for index, (key, members) in enumerate(sorted(clusters.items()), start=1):
            cluster_id = f"loc_{index:04d}"
            for record in members:
                record["location_cluster_id"] = cluster_id
            items.append(
                {
                    "location_cluster_id": cluster_id,
                    "centroid": self._cluster_centroid_payload(key),
                    "members": [record["asset_id"] for record in members],
                    "asset_id": members[0]["asset_id"],
                }
            )
        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "gps_export_mode": self.config.gps_export_mode,
            "cluster_count": len(items),
            "clusters": items,
        }

    def _cluster_centroid_payload(self, key: tuple[float, float]) -> dict[str, Any]:
        if self.config.gps_export_mode == "exact":
            return {"latitude": key[0], "longitude": key[1]}
        if self.config.gps_export_mode == "rounded":
            return {"latitude": round(key[0], 3), "longitude": round(key[1], 3)}
        if self.config.gps_export_mode == "venue_label_only":
            return {"latitude": None, "longitude": None, "venue_label": f"cluster_{key[0]}_{key[1]}"}
        return {"latitude": None, "longitude": None}

    def _build_chronology(self, normalized_records: list[dict[str, Any]]) -> dict[str, Any]:
        reliability = self._chronology_reliability(normalized_records)
        ordered = sorted(
            normalized_records,
            key=lambda record: (
                record.get("normalized_capture_time_epoch_ms") is None,
                record.get("normalized_capture_time_epoch_ms") or math.inf,
                0 if record.get("time_source") == "filename" else 1,
                record.get("device_id") or "",
                record.get("source_order_index") or 0,
                record["asset_id"],
            ),
        )
        assets = []
        for rank, record in enumerate(ordered, start=1):
            assets.append(
                {
                    "asset_id": record["asset_id"],
                    "chronology_rank": rank,
                    "normalized_capture_time": record.get("normalized_capture_time"),
                    "time_source": record.get("time_source"),
                }
            )
        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "total_assets": len(normalized_records),
            "chronology_reliability": reliability["status"],
            "chronology_reliability_reasons": reliability["reasons"],
            "assets": assets,
        }

    def _build_device_profiles(self, normalized_records: list[dict[str, Any]]) -> dict[str, Any]:
        devices: dict[str, dict[str, Any]] = {}
        for record in normalized_records:
            device_id = record.get("device_id")
            if not device_id:
                continue
            entry = devices.setdefault(
                device_id,
                {
                    "device_id": device_id,
                    "device_make": record.get("camera_make"),
                    "device_model": record.get("camera_model"),
                    "asset_ids": [],
                    "clock_offset_ms": 0,
                },
            )
            entry["asset_ids"].append(record["asset_id"])
        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "device_count": len(devices),
            "devices": sorted(devices.values(), key=lambda item: item["device_id"]),
        }

    def _build_coverage_summary(
        self,
        normalized_records: list[dict[str, Any]],
        warnings: list[dict[str, Any]],
        tool_status: dict[str, Any],
    ) -> dict[str, Any]:
        metadata_records_total = len(normalized_records)
        capture_time_count = len([item for item in normalized_records if item.get("normalized_capture_time")])
        gps_count = len([item for item in normalized_records if item.get("location_source")])
        device_count = len([item for item in normalized_records if item.get("device_id")])
        filename_fallback_count = len([item for item in normalized_records if item.get("capture_time_source") == "filename"])
        filesystem_fallback_count = len([item for item in normalized_records if item.get("capture_time_source") == "filesystem"])
        missing_metadata_count = len([item for item in normalized_records if item.get("metadata_status") == "missing"])
        extraction_error_count = len([item for item in warnings if item.get("code") in {"exiftool_failed", "ffprobe_metadata_failed"}])
        warning_codes = [str(item.get("code") or "") for item in warnings]
        return {
            "schema_version": METADATA_SCHEMA_VERSION,
            "metadata_records_total": metadata_records_total,
            "assets_with_capture_time": capture_time_count,
            "assets_with_gps": gps_count,
            "assets_with_device_identity": device_count,
            "assets_using_filename_fallback": filename_fallback_count,
            "assets_using_filesystem_fallback": filesystem_fallback_count,
            "missing_metadata_count": missing_metadata_count,
            "extraction_error_count": extraction_error_count,
            "gps_export_mode": self.config.gps_export_mode,
            "metadata_coverage_status": "ok" if missing_metadata_count == 0 else "partial",
            "metadata_completeness": self._metadata_completeness_status(normalized_records),
            "metadata_reliability": self._metadata_reliability_status(normalized_records, warning_codes),
            "tool_status": tool_status,
            "ok_count": len([item for item in normalized_records if item.get("metadata_status") == "ok"]),
            "partial_count": len([item for item in normalized_records if item.get("metadata_status") == "partial"]),
            "missing_count": missing_metadata_count,
            "error_count": len([item for item in normalized_records if item.get("metadata_status") == "error"]),
        }

    def _metadata_completeness_status(self, normalized_records: list[dict[str, Any]]) -> str:
        statuses = {str(item.get("metadata_status") or "missing") for item in normalized_records}
        if not statuses or "error" in statuses or "missing" in statuses:
            return "fail"
        if statuses == {"ok"}:
            return "pass"
        return "partial"

    def _metadata_reliability_status(self, normalized_records: list[dict[str, Any]], warning_codes: list[str]) -> str:
        if any(code in {"timestamp_conflict", "exiftool_failed", "ffprobe_metadata_failed"} for code in warning_codes):
            return "fail"
        if any(
            item.get("capture_time_source") in {"filename", "filesystem"} or item.get("timezone_source") is None
            for item in normalized_records
            if item.get("normalized_capture_time")
        ):
            return "partial"
        return "pass"

    def _chronology_reliability(self, normalized_records: list[dict[str, Any]]) -> dict[str, Any]:
        assets_with_time = [item for item in normalized_records if item.get("normalized_capture_time")]
        if not assets_with_time:
            return {"status": "fail", "reasons": ["no_capture_times"]}
        filename_assets = [item for item in assets_with_time if item.get("capture_time_source") == "filename"]
        unique_filename_times = {str(item.get("normalized_capture_time")) for item in filename_assets}
        unique_times = {str(item.get("normalized_capture_time")) for item in assets_with_time}
        reasons: list[str] = []
        if filename_assets and len(unique_filename_times) == 1 and len(filename_assets) > 1:
            reasons.append("filename_times_collapsed")
        if len(filename_assets) == len(assets_with_time):
            reasons.append("filename_only_timeline")
        if any(item.get("capture_time_source") == "filesystem" for item in assets_with_time):
            reasons.append("filesystem_fallback_present")
        if any(item.get("capture_time_source") == "filename" and not item.get("filename_time_has_clock") for item in assets_with_time):
            reasons.append("date_only_filename_fallback")
        if len(unique_times) == 1 and len(assets_with_time) > 1:
            reasons.append("all_timestamps_identical")
        status = "pass"
        if any(reason in {"filename_times_collapsed", "all_timestamps_identical"} for reason in reasons):
            status = "fail"
        elif reasons:
            status = "partial"
        return {"status": status, "reasons": reasons}

    def _location_confidence(self, gps_raw: dict[str, Any] | None) -> float | None:
        if not gps_raw:
            return None
        if self.config.gps_export_mode == "exact":
            return 0.95
        if self.config.gps_export_mode == "rounded":
            return 0.9
        if self.config.gps_export_mode == "venue_label_only":
            return 0.8
        return None

    def _gps_payload_only(self, gps_raw: dict[str, Any] | None) -> dict[str, Any] | None:
        if not gps_raw:
            return None
        return {
            "latitude": gps_raw["latitude"],
            "longitude": gps_raw["longitude"],
            "altitude": gps_raw.get("altitude"),
        }

    def _location_payload(self, exported_location: dict[str, Any] | None) -> dict[str, Any]:
        if not exported_location:
            return {"latitude": None, "longitude": None, "altitude_m": None}
        return {
            "latitude": exported_location.get("latitude"),
            "longitude": exported_location.get("longitude"),
            "altitude_m": exported_location.get("altitude"),
            **({"venue_label": exported_location["venue_label"]} if "venue_label" in exported_location else {}),
        }

    def _sanitize_raw_record_for_export(self, raw_record: dict[str, Any]) -> dict[str, Any]:
        exported = dict(raw_record)
        exported["filesystem"] = {
            "modified_at": raw_record["filesystem"]["modified_at"],
            "created_at": raw_record["filesystem"]["created_at"],
        }
        exported["exiftool"] = self._json_safe_value(raw_record["exiftool"])
        exported["pillow"] = self._json_safe_value(raw_record["pillow"])
        exported["ffprobe"] = self._json_safe_value(raw_record["ffprobe"])
        if self.config.gps_export_mode != "exact":
            exported["exiftool"] = self._redact_gps_tags(raw_record["exiftool"])
            exported["pillow"] = self._redact_gps_tags(raw_record["pillow"])
        return exported

    def _sanitize_normalized_record_for_export(self, record: dict[str, Any]) -> dict[str, Any]:
        exported = dict(record)
        if self.config.gps_export_mode == "excluded":
            exported["gps_raw"] = None
            exported["location"] = {
                "cluster_id": exported.get("location_cluster_id"),
                "export_mode": self.config.gps_export_mode,
                "source": None,
                "confidence": None,
                "latitude": None,
                "longitude": None,
                "altitude_m": None,
            }
            exported["location_source"] = None
            exported["location_confidence"] = None
        elif self.config.gps_export_mode in {"rounded", "venue_label_only"} and exported.get("gps_raw"):
            exported["gps_raw"] = None
        return exported

    def _redact_gps_tags(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not payload:
            return {}
        redacted: dict[str, Any] = {}
        for key, value in payload.items():
            if "GPS" in str(key):
                continue
            redacted[key] = value
        return redacted

    def _json_safe_value(self, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        if isinstance(value, dict):
            return {str(key): self._json_safe_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe_value(item) for item in value]
        if hasattr(value, "numerator") and hasattr(value, "denominator"):
            try:
                denominator = float(value.denominator)
                if denominator == 0:
                    return str(value)
                return float(value.numerator) / denominator
            except Exception:
                return str(value)
        return str(value)

    def _filename_hint(self, filename: str) -> dict[str, Any] | None:
        whatsapp = _WHATSAPP_RE.search(filename)
        if whatsapp:
            if whatsapp.group("date"):
                date_value = whatsapp.group("date")
                iso = f"{date_value[:4]}-{date_value[4:6]}-{date_value[6:8]}T00:00:00"
                return {
                    "raw": whatsapp.group(0),
                    "normalized": iso,
                    "utc": None,
                    "epoch_ms": self._naive_iso_to_sort_epoch_ms(iso),
                    "confidence": 0.35,
                    "has_clock_time": False,
                }
            if whatsapp.group("date2") and whatsapp.group("time2"):
                iso = self._filename_time_iso(
                    whatsapp.group("date2"),
                    whatsapp.group("time2"),
                    whatsapp.group("ampm"),
                )
                return {
                    "raw": whatsapp.group(0),
                    "normalized": iso,
                    "utc": None,
                    "epoch_ms": self._naive_iso_to_sort_epoch_ms(iso),
                    "confidence": 0.55,
                    "has_clock_time": True,
                }
        generic = _GENERIC_FILENAME_DT_RE.search(filename)
        if not generic:
            return None
        hour = generic.group("hour") or "00"
        minute = generic.group("minute") or "00"
        second = generic.group("second") or "00"
        iso = (
            f"{generic.group('year')}-{generic.group('month')}-{generic.group('day')}"
            f"T{hour}:{minute}:{second}"
        )
        return {
            "raw": generic.group(0),
            "normalized": iso,
            "utc": None,
            "epoch_ms": self._naive_iso_to_sort_epoch_ms(iso),
            "confidence": 0.35,
            "has_clock_time": bool(generic.group("hour")),
        }

    def _filename_time_iso(self, date_value: str, time_value: str, ampm: str | None) -> str:
        hour_text, minute_text, second_text = time_value.split(".")
        hour = int(hour_text)
        if ampm:
            if hour == 12:
                hour = 0
            if ampm.upper() == "PM":
                hour += 12
        return f"{date_value}T{hour:02d}:{minute_text}:{second_text}"

    def _filesystem_times(self, path: Path) -> dict[str, Any]:
        stat = path.stat()
        modified_at = dt.datetime.fromtimestamp(stat.st_mtime, tz=dt.timezone.utc).isoformat(timespec="seconds")
        created_at = dt.datetime.fromtimestamp(stat.st_ctime, tz=dt.timezone.utc).isoformat(timespec="seconds")
        return {
            "modified_at": modified_at,
            "created_at": created_at,
        }

    def _warning(
        self,
        *,
        code: str,
        severity: str,
        message: str,
        asset_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "asset_id": asset_id,
            "code": code,
            "severity": severity,
            "message": message,
        }

    def _stable_asset_key(self, path: Path) -> str:
        return hashlib.sha1(str(path).encode("utf-8")).hexdigest()[:12]

    def _iso_to_epoch_ms(self, iso_value: str | None) -> int | None:
        if not iso_value:
            return None
        try:
            parsed = dt.datetime.fromisoformat(iso_value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return int(parsed.timestamp() * 1000)

    def _naive_iso_to_sort_epoch_ms(self, iso_value: str | None) -> int | None:
        if not iso_value:
            return None
        try:
            parsed = dt.datetime.fromisoformat(iso_value)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return int(parsed.timestamp() * 1000)
