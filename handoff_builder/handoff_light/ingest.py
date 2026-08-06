from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from handoff_builder.ffmpeg_tools import FFmpegError, FFmpegTools
from handoff_builder.utils import file_sha256, json_dump, media_type_for, slugify

from .archive import SUPPORTED_SIDECAR_EXTENSIONS, SafeInputDiscoverer
from .models import AssetRecord, IngestLimits, IngestReport, ProjectState
from .project_store import ProjectStore, utc_now_iso
from .reports import REPORT_FILENAMES, write_report


class HandoffLightIngestService:
    def __init__(self, store: ProjectStore, *, limits: IngestLimits | None = None) -> None:
        self.store = store
        self.limits = limits or IngestLimits()

    def ingest(self, state: ProjectState, selections: list[Path]) -> IngestReport:
        self._refresh_missing_statuses(state)
        discoverer = SafeInputDiscoverer(self.limits)
        discovered = discoverer.discover(selections)
        try:
            report = IngestReport(
                damaged_files=list(discovered.damaged_files),
                unsupported_files=list(discovered.unsupported_files) + list(discovered.blocked_archives),
                discovered_file_count=len(discovered.discovered_files),
            )
            by_signature = {(asset.size_bytes, asset.sha256): asset for asset in state.assets}
            ffmpeg_tools = FFmpegTools(project_root=state.root)
            for item in discovered.discovered_files:
                try:
                    size_bytes = item.path.stat().st_size
                    sha256 = file_sha256(item.path)
                except OSError as exc:
                    report.damaged_files.append({
                        "path": str(item.path),
                        "source_chain": item.source_chain,
                        "reason": "unreadable_file",
                        "error": str(exc),
                    })
                    continue
                duplicate = by_signature.get((size_bytes, sha256))
                if duplicate is not None:
                    report.duplicate_assets.append({
                        "asset_id": duplicate.asset_id,
                        "path": str(item.path),
                        "original_name": item.path.name,
                        "source_chain": item.source_chain,
                    })
                    continue
                media_type = media_type_for(item.path)
                if media_type is None and item.path.suffix.lower() not in SUPPORTED_SIDECAR_EXTENSIONS:
                    report.unsupported_files.append({
                        "path": str(item.path),
                        "source_chain": item.source_chain,
                        "reason": "unsupported_extension",
                    })
                    continue
                asset = self._register_asset(state, item.path, item.stable_source_path, item.source_chain, item.archive_depth, size_bytes, sha256, media_type, ffmpeg_tools)
                state.assets.append(asset)
                by_signature[(size_bytes, sha256)] = asset
                report.added_assets.append({
                    "asset_id": asset.asset_id,
                    "original_name": asset.original_name,
                    "media_type": asset.media_type,
                    "source_chain": asset.source_chain,
                })
            self._refresh_missing_statuses(state, report)
            write_report(
                state.reports_dir / REPORT_FILENAMES["new_material"],
                {
                    "schema_version": "1.0",
                    "project_name": state.project_name,
                    "generated_at": utc_now_iso(),
                    "baseline_handoff_version": state.last_handoff_version,
                    "new_assets": report.added_assets,
                    "new_asset_count": len(report.added_assets),
                    "discovered_file_count": report.discovered_file_count,
                },
            )
            write_report(state.reports_dir / REPORT_FILENAMES["duplicates"], {
                "schema_version": "1.0",
                "duplicates": report.duplicate_assets,
                "duplicate_count": len(report.duplicate_assets),
            })
            write_report(state.reports_dir / REPORT_FILENAMES["missing_files"], {
                "schema_version": "1.0",
                "missing_assets": report.missing_assets,
                "missing_asset_count": len(report.missing_assets),
            })
            write_report(state.reports_dir / REPORT_FILENAMES["damaged_files"], {
                "schema_version": "1.0",
                "damaged_files": report.damaged_files,
                "damaged_file_count": len(report.damaged_files),
            })
            write_report(state.reports_dir / REPORT_FILENAMES["unsupported_files"], {
                "schema_version": "1.0",
                "unsupported_files": report.unsupported_files,
                "unsupported_file_count": len(report.unsupported_files),
            })
            state.last_ingest_report = report.as_dict()
            state.ingestion_history.append({
                "ingested_at": utc_now_iso(),
                "selections": [str(path) for path in selections],
                "summary": report.as_dict(),
            })
            self.store.save(state)
            return report
        finally:
            if discovered.temp_root and discovered.temp_root.exists():
                shutil.rmtree(discovered.temp_root, ignore_errors=True)

    def _register_asset(
        self,
        state: ProjectState,
        source_path: Path,
        stable_source_path: Path,
        source_chain: list[str],
        archive_depth: int,
        size_bytes: int,
        sha256: str,
        media_type: str | None,
        ffmpeg_tools: FFmpegTools,
    ) -> AssetRecord:
        asset_id = self._next_asset_id(state, sha256)
        original_name = source_path.name
        metadata_path = state.metadata_dir / f"{asset_id}.json"
        local_copy_path: Path | None = None
        proxy_path: Path | None = None
        package_path: str | None = None
        inspection = self._sanitize_for_package(
            self._inspect_file(source_path, media_type, ffmpeg_tools),
            source_path,
            original_name,
        )
        if media_type == "photo":
            local_copy_path = state.photos_dir / f"{asset_id}_{slugify(original_name, fallback='photo')}"
            shutil.copy2(source_path, local_copy_path)
            package_path = f"PHOTOS/{local_copy_path.name}"
        elif media_type == "audio":
            local_copy_path = state.audio_dir / f"{asset_id}_{slugify(original_name, fallback='audio')}"
            shutil.copy2(source_path, local_copy_path)
            package_path = f"AUDIO/{local_copy_path.name}"
        elif media_type == "video":
            proxy_path = state.proxies_dir / f"{asset_id}.mp4"
            ffmpeg_tools.make_proxy(source_path, proxy_path)
            package_path = f"PROXIES/{proxy_path.name}"
        else:
            local_copy_path = state.metadata_dir / "sidecars" / f"{asset_id}_{slugify(original_name, fallback='sidecar')}"
            local_copy_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, local_copy_path)
            package_path = f"METADATA/sidecars/{local_copy_path.name}"
        json_dump(
            metadata_path,
            {
                "asset_id": asset_id,
                "original_name": original_name,
                "source_chain": source_chain,
                "archive_depth": archive_depth,
                "media_type": media_type or "sidecar",
                "size_bytes": size_bytes,
                "sha256": sha256,
                "inspection": inspection,
            },
        )
        return AssetRecord(
            asset_id=asset_id,
            original_name=original_name,
            media_type=media_type or "sidecar",
            size_bytes=size_bytes,
            sha256=sha256,
            source_path=str(stable_source_path.resolve()),
            source_chain=source_chain,
            archive_depth=archive_depth,
            added_after_handoff_version=state.last_handoff_version,
            created_at=utc_now_iso(),
            local_copy_path=str(local_copy_path) if local_copy_path else None,
            proxy_path=str(proxy_path) if proxy_path else None,
            metadata_path=str(metadata_path),
            package_path=package_path,
            metadata_package_path=f"METADATA/{metadata_path.name}",
            inspection=inspection,
        )

    def _sanitize_for_package(self, value: object, source_path: Path, original_name: str) -> object:
        if isinstance(value, dict):
            return {key: self._sanitize_for_package(item, source_path, original_name) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize_for_package(item, source_path, original_name) for item in value]
        if isinstance(value, str):
            return value.replace(str(source_path), original_name).replace(str(source_path.resolve()), original_name)
        return value

    def _next_asset_id(self, state: ProjectState, sha256: str) -> str:
        return f"asset_{len(state.assets) + 1:05d}_{sha256[:8]}"

    def _inspect_file(self, source_path: Path, media_type: str | None, ffmpeg_tools: FFmpegTools) -> dict[str, object]:
        payload: dict[str, object] = {
            "file_size": source_path.stat().st_size,
        }
        if media_type == "photo":
            try:
                with Image.open(source_path) as image:
                    payload.update({
                        "width": int(image.width),
                        "height": int(image.height),
                        "container": image.format,
                    })
            except (OSError, UnidentifiedImageError) as exc:
                payload["inspection_warning"] = f"photo_inspection_failed: {exc}"
        elif media_type in {"video", "audio"}:
            try:
                probe = ffmpeg_tools.probe(source_path)
                payload.update(probe)
                payload["container"] = source_path.suffix.lower().lstrip(".")
            except (FFmpegError, OSError) as exc:
                payload["inspection_warning"] = f"ffprobe_failed: {exc}"
        return payload

    def _refresh_missing_statuses(self, state: ProjectState, report: IngestReport | None = None) -> None:
        missing_assets: list[dict[str, object]] = []
        for asset in state.assets:
            exists = Path(asset.source_path).exists()
            asset.missing = not exists
            if asset.missing:
                missing_assets.append({
                    "asset_id": asset.asset_id,
                    "source_path": asset.source_path,
                    "original_name": asset.original_name,
                })
        if report is not None:
            report.missing_assets = missing_assets
