from __future__ import annotations

import datetime as dt
import threading
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image, ImageOps

from .contact_sheets import build_contact_sheet, paginate_contact_sheets
from .ffmpeg_tools import FFmpegTools
from .metadata import AssetMetadataBuilder, METADATA_SCHEMA_VERSION
from .models import AssetRecord, BuildResult, BuilderConfig, SceneRecord
from .utils import (
    human_bytes,
    iter_media,
    json_dump,
    media_type_for,
    relative_posix,
    safe_extract_zip,
    slugify,
    stable_asset_id,
)


ProgressCallback = Callable[[float, str], None]
LogCallback = Callable[[str], None]


def _noop_progress(value: float, message: str) -> None:
    pass


def _noop_log(message: str) -> None:
    pass


class HandoffBuilder:
    def __init__(
        self,
        config: BuilderConfig,
        *,
        progress: ProgressCallback | None = None,
        log: LogCallback | None = None,
        project_root: Path | None = None,
    ) -> None:
        self.config = config
        self.progress = progress or _noop_progress
        self.log = log or _noop_log
        self.project_root = project_root
        self.cancel_event = threading.Event()
        self.ffmpeg = FFmpegTools(project_root, cancel_event=self.cancel_event)
        self.metadata = AssetMetadataBuilder(config, project_root=project_root)

    def cancel(self) -> None:
        self.cancel_event.set()

    def _ensure_not_canceled(self) -> None:
        if self.cancel_event.is_set():
            raise RuntimeError("Processing was canceled by the user.")

    def _prepare_sources(self, inputs: Iterable[Path], workspace: Path) -> tuple[list[Path], Path]:
        source_root = workspace / "source"
        source_root.mkdir(parents=True, exist_ok=True)
        prepared: list[Path] = []

        for index, item in enumerate(inputs, start=1):
            self._ensure_not_canceled()
            item = item.resolve()
            if item.suffix.lower() == ".zip":
                target = source_root / f"zip_{index:03d}_{slugify(item.stem)}"
                self.log(f"Extracting ZIP: {item.name}")
                safe_extract_zip(item, target)
                prepared.append(target)
            elif item.is_dir():
                target = source_root / f"folder_{index:03d}_{slugify(item.name)}"
                self.log(f"Copying folder registry: {item}")
                # Do not duplicate large media. A marker/symlink is not reliable on Windows,
                # so we scan the original directory directly.
                prepared.append(item)
            elif item.is_file():
                prepared.append(item)
            else:
                self.log(f"Skipped missing input: {item}")

        return prepared, source_root

    def _process_photo(self, source: Path, asset: AssetRecord, package_root: Path) -> None:
        self._ensure_not_canceled()
        destination = package_root / "photo_analysis_copies" / f"asset_{asset.asset_id}.jpg"
        destination.parent.mkdir(parents=True, exist_ok=True)

        with Image.open(source) as image:
            image = ImageOps.exif_transpose(image)
            image = image.convert("RGB")
            width, height = image.size
            asset.width, asset.height = width, height
            longest = max(width, height)
            if longest > self.config.photo_long_side:
                scale = self.config.photo_long_side / longest
                image = image.resize(
                    (max(1, round(width * scale)), max(1, round(height * scale))),
                    Image.Resampling.LANCZOS,
                )
            image.save(
                destination,
                "JPEG",
                quality=self.config.photo_quality,
                optimize=True,
            )

        asset.analysis_copy = relative_posix(destination, package_root)
        asset.status = "processed"

    def _process_video(
        self,
        source: Path,
        asset: AssetRecord,
        package_root: Path,
    ) -> list[SceneRecord]:
        self._ensure_not_canceled()
        meta = self.ffmpeg.probe(source)
        duration = float(meta["duration"])
        asset.duration_ms = round(duration * 1000)
        asset.width = meta["width"]
        asset.height = meta["height"]
        asset.rotation = meta["rotation"]
        asset.fps = meta.get("fps")
        asset.audio_present = bool(meta.get("audio_present"))

        if self.config.include_video_proxies:
            proxy = package_root / "video_proxies" / f"asset_{asset.asset_id}.mp4"
            self.ffmpeg.make_proxy(source, proxy, self.config.proxy_height)
            asset.proxy = relative_posix(proxy, package_root)

        segments, mode = self.ffmpeg.scene_segments(
            source,
            duration,
            threshold=self.config.scene_threshold,
            short_seconds=self.config.short_video_seconds,
            fallback_segment_seconds=self.config.fallback_segment_seconds,
            max_segments=self.config.max_segments_per_video,
        )

        scenes: list[SceneRecord] = []
        storyboard_items: list[tuple[Path, str]] = []
        for index, (start, end) in enumerate(segments, start=1):
            self._ensure_not_canceled()
            scene_id = f"{asset.asset_id}_s{index:04d}"
            midpoint = start + (end - start) / 2
            keyframe = package_root / "scene_keyframes" / f"{scene_id}.jpg"
            preview = package_root / "scene_previews" / f"{scene_id}.mp4"
            self.ffmpeg.extract_frame(source, midpoint, keyframe)

            preview_duration = min(
                self.config.preview_seconds,
                max(0.35, end - start),
            )
            preview_start = max(start, midpoint - preview_duration / 2)
            if preview_start + preview_duration > end:
                preview_start = max(start, end - preview_duration)
            self.ffmpeg.make_preview(source, preview_start, preview_duration, preview)

            scene = SceneRecord(
                scene_id=scene_id,
                asset_id=asset.asset_id,
                scene_index=index,
                start_ms=round(start * 1000),
                end_ms=round(end * 1000),
                duration_ms=round((end - start) * 1000),
                detection_mode=mode,
                keyframe_time_ms=round(midpoint * 1000),
                keyframe_path=relative_posix(keyframe, package_root),
                preview_path=relative_posix(preview, package_root),
            )
            scenes.append(scene)
            asset.scene_ids.append(scene_id)
            storyboard_items.append((keyframe, f"{index:02d}  {start:.1f}–{end:.1f}s"))

        storyboard = package_root / "video_storyboards" / f"asset_{asset.asset_id}.jpg"
        build_contact_sheet(
            storyboard_items[: self.config.storyboard_frames],
            storyboard,
            columns=4,
            thumb_size=(320, 220),
        )
        asset.storyboard = relative_posix(storyboard, package_root)
        asset.status = "processed"
        return scenes

    def _process_asset(
        self,
        source: Path,
        asset: AssetRecord,
        package_root: Path,
    ) -> list[SceneRecord]:
        if asset.media_type == "photo":
            self._process_photo(source, asset, package_root)
            return []
        return self._process_video(source, asset, package_root)

    def build(self, inputs: list[Path]) -> BuildResult:
        if not inputs:
            raise ValueError("No input files or folders were selected.")

        self.cancel_event.clear()
        timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        project_slug = slugify(self.config.project_name)
        job_root = self.config.output_dir.resolve() / f"{project_slug}_{timestamp}"
        package_root = job_root / "package"
        package_root.mkdir(parents=True, exist_ok=False)

        self.log(f"Project workspace: {job_root}")
        prepared, source_root = self._prepare_sources(inputs, job_root)
        media_files = iter_media(prepared)
        if not media_files:
            raise ValueError("No supported photo or video files were found.")

        assets: list[AssetRecord] = []
        scenes: list[SceneRecord] = []
        asset_index: dict[str, AssetRecord] = {}
        work_items: list[tuple[Path, AssetRecord]] = []
        registry_failures: list[tuple[Path, str]] = []

        total = len(media_files)
        for source in media_files:
            self._ensure_not_canceled()
            media_type = media_type_for(source)
            assert media_type is not None
            root_for_id = source.parent
            asset_id = stable_asset_id(source, root_for_id)
            try:
                relative_source = source.name
                for prepared_root in prepared:
                    if prepared_root.is_dir():
                        try:
                            relative_source = source.relative_to(prepared_root).as_posix()
                            break
                        except ValueError:
                            pass
                category = Path(relative_source).parts[0] if len(Path(relative_source).parts) > 1 else None
                asset = AssetRecord(
                    asset_id=asset_id,
                    media_type=media_type,
                    original_name=source.name,
                    source_path=str(source),
                    relative_source_path=relative_source,
                    extension=source.suffix.lower(),
                    size_bytes=source.stat().st_size,
                    folder_category=category,
                )
                assets.append(asset)
                asset_index[asset.asset_id] = asset
                work_items.append((source, asset))
            except Exception as exc:
                registry_failures.append((source, str(exc)))
                self.log(f"REGISTRY FAILED: {source}: {exc}")

        completed = 0
        max_workers = max(1, min(int(self.config.worker_count or 1), 2))
        if max_workers == 1:
            for source, asset in work_items:
                self._ensure_not_canceled()
                self.log(f"[{completed + 1}/{total}] {asset.media_type}: {source}")
                try:
                    scenes.extend(self._process_asset(source, asset, package_root))
                except Exception as exc:
                    asset.status = "failed"
                    asset.error = str(exc)
                    self.log(f"FAILED: {source.name}: {exc}")
                completed += 1
                self.progress(completed / total, f"{completed}/{total}: {source.name}")
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(self._process_asset, source, asset, package_root): (source, asset)
                    for source, asset in work_items
                }
                for future in as_completed(futures):
                    source, asset = futures[future]
                    self._ensure_not_canceled()
                    self.log(f"[{completed + 1}/{total}] {asset.media_type}: {source}")
                    try:
                        scenes.extend(future.result())
                    except Exception as exc:
                        asset.status = "failed"
                        asset.error = str(exc)
                        self.log(f"FAILED: {source.name}: {exc}")
                    completed += 1
                    self.progress(completed / total, f"{completed}/{total}: {source.name}")

        metadata_result = self.metadata.build(assets)

        photo_items = [
            (package_root / asset.analysis_copy, asset.relative_source_path)
            for asset in assets
            if asset.media_type == "photo" and asset.analysis_copy
        ]
        video_items = [
            (package_root / asset.storyboard, asset.relative_source_path)
            for asset in assets
            if asset.media_type == "video" and asset.storyboard
        ]
        keyframe_items = [
            (package_root / scene.keyframe_path, scene.scene_id)
            for scene in scenes
        ]

        contact_dir = package_root / "contact_sheets"
        photo_sheets = paginate_contact_sheets(
            photo_items, contact_dir, prefix="photos", page_size=20
        )
        video_sheets = paginate_contact_sheets(
            video_items, contact_dir, prefix="videos", page_size=12
        )
        scene_sheets = paginate_contact_sheets(
            keyframe_items, contact_dir, prefix="scenes", page_size=20
        )

        source_videos = [asset for asset in assets if asset.media_type == "video"]
        source_photos = [asset for asset in assets if asset.media_type == "photo"]
        failed = [asset for asset in assets if asset.status != "processed"]
        for source, error in registry_failures:
            failed.append(
                AssetRecord(
                    asset_id=stable_asset_id(source),
                    media_type=media_type_for(source) or "unknown",
                    original_name=source.name,
                    source_path=str(source),
                    relative_source_path=source.name,
                    extension=source.suffix.lower(),
                    size_bytes=source.stat().st_size if source.exists() else 0,
                    status="failed",
                    error=error,
                )
            )
        videos_without_scenes = [
            asset for asset in source_videos if not asset.scene_ids
        ]
        photos_without_copies = [
            asset for asset in source_photos if not asset.analysis_copy
        ]
        missing_paths: list[str] = []
        for asset in assets:
            for rel in (asset.analysis_copy, asset.proxy, asset.storyboard):
                if rel and not (package_root / rel).exists():
                    missing_paths.append(rel)
        for scene in scenes:
            source_asset = asset_index.get(scene.asset_id)
            if source_asset:
                scene.chronology_rank = source_asset.chronology_rank
                scene.location_cluster_id = source_asset.location_cluster_id
                scene.capture_time_iso = source_asset.capture_time_iso
            for rel in (scene.keyframe_path, scene.preview_path):
                if not (package_root / rel).exists():
                    missing_paths.append(rel)
        scenes = self._stable_scene_order(scenes)

        metadata_dir = package_root / "metadata"
        local_asset_registry_path = job_root / "local_asset_registry.json"
        json_dump(local_asset_registry_path, metadata_result.local_asset_registry)
        json_dump(
            metadata_dir / "asset_metadata_raw.json",
            {
                "schema_version": METADATA_SCHEMA_VERSION,
                "tool_status": metadata_result.tool_status,
                "assets": metadata_result.raw_records,
            },
        )
        json_dump(
            metadata_dir / "asset_metadata_normalized.json",
            {
                "schema_version": METADATA_SCHEMA_VERSION,
                "gps_export_mode": self.config.gps_export_mode,
                "assets": metadata_result.normalized_records,
            },
        )
        json_dump(metadata_dir / "device_clock_profiles.json", metadata_result.device_clock_profiles)
        json_dump(metadata_dir / "chronology_report.json", metadata_result.chronology_report)
        json_dump(metadata_dir / "location_clusters.json", metadata_result.location_clusters)
        json_dump(metadata_dir / "metadata_warnings.json", metadata_result.warnings_payload)

        metadata_by_asset_id = {record["asset_id"]: record for record in metadata_result.normalized_records}
        metadata_ids = [record["asset_id"] for record in metadata_result.normalized_records]
        duplicate_metadata_ids = sorted({value for value in metadata_ids if metadata_ids.count(value) > 1})
        metadata_hard_failures: list[str] = []
        if len(metadata_result.normalized_records) != len(assets):
            metadata_hard_failures.append("metadata record count does not match asset count")
        if len(metadata_ids) != len(set(metadata_ids)):
            metadata_hard_failures.append("duplicate asset_id in metadata records")
        if any(not value for value in metadata_ids):
            metadata_hard_failures.append("missing asset_id in metadata records")
        missing_manifest_metadata = sorted(asset.asset_id for asset in assets if asset.asset_id not in set(metadata_ids))
        if missing_manifest_metadata:
            metadata_hard_failures.append("manifest references assets without metadata records")
            raise ValueError(
                "manifest references assets without metadata records: "
                + ", ".join(missing_manifest_metadata)
            )
        metadata_hard_failures.extend(self._metadata_contract_failures(metadata_result.normalized_records))

        validation = {
            "schema_version": "1.0",
            "project_name": self.config.project_name,
            "source_asset_count": len(assets),
            "source_video_count": len(source_videos),
            "source_photo_count": len(source_photos),
            "processed_asset_count": len([a for a in assets if a.status == "processed"]),
            "failed_asset_count": len(failed),
            "video_assets_represented": len(source_videos) - len(videos_without_scenes),
            "photo_assets_represented": len(source_photos) - len(photos_without_copies),
            "scene_count": len(scenes),
            "metadata_records_total": metadata_result.coverage_summary["metadata_records_total"],
            "assets_with_capture_time": metadata_result.coverage_summary["assets_with_capture_time"],
            "assets_with_gps": metadata_result.coverage_summary["assets_with_gps"],
            "assets_with_device_identity": metadata_result.coverage_summary["assets_with_device_identity"],
            "assets_using_filename_fallback": metadata_result.coverage_summary["assets_using_filename_fallback"],
            "assets_using_filesystem_fallback": metadata_result.coverage_summary["assets_using_filesystem_fallback"],
            "missing_metadata_count": metadata_result.coverage_summary["missing_metadata_count"],
            "extraction_error_count": metadata_result.coverage_summary["extraction_error_count"],
            "gps_export_mode": metadata_result.coverage_summary["gps_export_mode"],
            "metadata_coverage_status": metadata_result.coverage_summary["metadata_coverage_status"],
            "metadata_status_counts": {
                "ok": metadata_result.coverage_summary["ok_count"],
                "partial": metadata_result.coverage_summary["partial_count"],
                "missing": metadata_result.coverage_summary["missing_count"],
                "error": metadata_result.coverage_summary["error_count"],
            },
            "metadata_tool_status": metadata_result.tool_status,
            "metadata_warning_count": len(metadata_result.warnings_payload["warnings"]),
            "metadata_warning_path": "metadata/metadata_warnings.json",
            "metadata_report_paths": {
                "raw": "metadata/asset_metadata_raw.json",
                "normalized": "metadata/asset_metadata_normalized.json",
                "device_clock_profiles": "metadata/device_clock_profiles.json",
                "chronology_report": "metadata/chronology_report.json",
                "location_clusters": "metadata/location_clusters.json",
                "warnings": "metadata/metadata_warnings.json",
            },
            "metadata_hard_failures": metadata_hard_failures,
            "missing_manifest_metadata": missing_manifest_metadata,
            "duplicate_metadata_ids": duplicate_metadata_ids,
            "videos_without_scenes": [a.asset_id for a in videos_without_scenes],
            "photos_without_analysis_copies": [a.asset_id for a in photos_without_copies],
            "failed_assets": [
                {
                    "asset_id": asset.asset_id,
                    "source_path": asset.source_path,
                    "error": asset.error,
                }
                for asset in failed
            ],
            "missing_artifact_paths": missing_paths,
            "coverage_ok": (
                not failed
                and not videos_without_scenes
                and not photos_without_copies
                and not missing_paths
                and not metadata_hard_failures
            ),
        }

        manifest = {
            "schema_version": "1.0",
            "project_name": self.config.project_name,
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "settings": {
                "include_video_proxies": self.config.include_video_proxies,
                "photo_long_side": self.config.photo_long_side,
                "photo_quality": self.config.photo_quality,
                "proxy_height": self.config.proxy_height,
                "scene_threshold": self.config.scene_threshold,
                "short_video_seconds": self.config.short_video_seconds,
                "fallback_segment_seconds": self.config.fallback_segment_seconds,
                "max_segments_per_video": self.config.max_segments_per_video,
                "gps_export_mode": self.config.gps_export_mode,
            },
            "summary": validation,
            "assets": [self._build_asset_manifest_entry(asset, metadata_by_asset_id[asset.asset_id]) for asset in assets],
            "contact_sheets": [
                relative_posix(path, package_root)
                for path in photo_sheets + video_sheets + scene_sheets
            ],
        }
        scene_manifest = {
            "schema_version": "1.0",
            "project_name": self.config.project_name,
            "scene_count": len(scenes),
            "gps_export_mode": self.config.gps_export_mode,
            "scenes": [self._build_scene_manifest_entry(scene, metadata_by_asset_id.get(scene.asset_id)) for scene in scenes],
        }

        json_dump(package_root / "handoff_manifest.json", manifest)
        json_dump(package_root / "scene_manifest.json", scene_manifest)
        json_dump(package_root / "validation_report.json", validation)

        readme = f"""AI HANDOFF BUILDER v1

PROJECT
{self.config.project_name}

SUMMARY
- Assets: {len(assets)}
- Videos: {len(source_videos)}
- Photos: {len(source_photos)}
- Scenes/coverage segments: {len(scenes)}
- Failed assets: {len(failed)}
- Coverage OK: {validation['coverage_ok']}
- Metadata records: {validation['metadata_records_total']}
- Assets with capture time: {validation['assets_with_capture_time']}
- Assets with GPS: {validation['assets_with_gps']}
- Metadata warnings: {validation['metadata_warning_count']}

IMPORTANT
Every source video must have at least one keyframe and one preview.
Short videos are represented as one full-video scene.
Long videos use detected cuts or uniform coverage segments.
Photos are resized from every source folder, not just one category.

FILES
- handoff_manifest.json
- scene_manifest.json
- validation_report.json
- metadata/asset_metadata_raw.json
- metadata/asset_metadata_normalized.json
- metadata/device_clock_profiles.json
- metadata/chronology_report.json
- metadata/location_clusters.json
- metadata/metadata_warnings.json
- photo_analysis_copies/
- video_proxies/
- scene_keyframes/
- scene_previews/
- video_storyboards/
- contact_sheets/
"""
        (package_root / "README.txt").write_text(readme, encoding="utf-8")

        archive_path = self.config.output_dir.resolve() / f"{project_slug}_ANALYSIS_HANDOFF.zip"
        if archive_path.exists():
            archive_path.unlink()
        self.progress(0.98, "Creating final ZIP...")
        with zipfile.ZipFile(
            archive_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=6,
            allowZip64=True,
        ) as archive:
            for file_path in sorted(package_root.rglob("*")):
                if file_path.is_file():
                    archive.write(file_path, file_path.relative_to(package_root).as_posix())

        self.progress(1.0, f"Done: {archive_path.name}")
        self.log(
            f"Created {archive_path} ({human_bytes(archive_path.stat().st_size)}), "
            f"coverage_ok={validation['coverage_ok']}"
        )
        return BuildResult(
            archive_path=archive_path,
            job_root=job_root,
            package_root=package_root,
            validation_path=package_root / "validation_report.json",
            validation=validation,
            failed_sources=[asset.source_path for asset in failed if asset.source_path],
            metadata_warnings_path=metadata_dir / "metadata_warnings.json",
            local_asset_registry_path=local_asset_registry_path,
            canceled=False,
        )

    def _stable_scene_order(self, scenes: list[SceneRecord]) -> list[SceneRecord]:
        return sorted(
            scenes,
            key=lambda scene: (
                scene.chronology_rank if scene.chronology_rank is not None else 10**9,
                scene.capture_time_iso or "",
                scene.asset_id,
                scene.scene_index,
                scene.scene_id,
            ),
        )

    def _build_asset_manifest_entry(self, asset: AssetRecord, metadata_record: dict[str, object]) -> dict[str, object]:
        location = dict(metadata_record.get("location") or {})
        location["cluster_id"] = metadata_record.get("location_cluster_id")
        return {
            **asset.to_dict(),
            "type": asset.media_type,
            "resolution": {"width": asset.width, "height": asset.height},
            "orientation": self._orientation_for(asset.width, asset.height, asset.rotation),
            "fps": asset.fps,
            "audio_present": asset.audio_present,
            "capture_time": metadata_record.get("capture_time_project"),
            "capture_time_utc": metadata_record.get("capture_time_utc"),
            "capture_time_source": metadata_record.get("capture_time_source"),
            "time_confidence": metadata_record.get("time_confidence"),
            "location": location,
            "location_confidence": metadata_record.get("location_confidence"),
            "metadata_warnings": metadata_record.get("warnings", []),
        }

    def _build_scene_manifest_entry(self, scene: SceneRecord, metadata_record: dict[str, object] | None) -> dict[str, object]:
        payload = scene.to_dict()
        payload["metadata_asset_id"] = scene.asset_id
        payload["device_id"] = metadata_record.get("device_id") if metadata_record else None
        payload["time_confidence"] = metadata_record.get("time_confidence") if metadata_record else None
        payload["location_confidence"] = metadata_record.get("location_confidence") if metadata_record else None
        payload["normalized_start_time"] = self._shift_iso_by_ms(
            metadata_record.get("capture_time_project") if metadata_record else None,
            scene.start_ms,
        )
        payload["normalized_end_time"] = self._shift_iso_by_ms(
            metadata_record.get("capture_time_project") if metadata_record else None,
            scene.end_ms,
        )
        return payload

    def _shift_iso_by_ms(self, iso_value: object, offset_ms: int) -> str | None:
        if not iso_value:
            return None
        try:
            parsed = dt.datetime.fromisoformat(str(iso_value))
        except ValueError:
            return None
        return (parsed + dt.timedelta(milliseconds=offset_ms)).isoformat(timespec="seconds")

    def _orientation_for(self, width: int | None, height: int | None, rotation: int | None) -> str | None:
        if not width or not height:
            return None
        portrait = height > width
        if rotation in {90, 270}:
            portrait = not portrait
        return "portrait" if portrait else "landscape"

    def _metadata_contract_failures(self, normalized_records: list[dict[str, object]]) -> list[str]:
        failures: list[str] = []
        for record in normalized_records:
            asset_id = str(record["asset_id"])
            if record.get("normalized_capture_time") and (not record.get("capture_time_source") or record.get("time_confidence") is None):
                failures.append(f"computed capture time missing source/confidence for {asset_id}")
            location = record.get("location") or {}
            if any(location.get(key) is not None for key in ("latitude", "longitude", "venue_label")):
                if not record.get("location_source") or record.get("location_confidence") is None:
                    failures.append(f"computed location missing source/confidence for {asset_id}")
        return sorted(set(failures))
