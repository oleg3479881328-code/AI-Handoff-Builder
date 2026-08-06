from __future__ import annotations

import json
import re
import shutil
import zipfile
from pathlib import Path

from handoff_builder.utils import json_dump

from .models import PACKAGE_SCHEMA_VERSION, ProjectState
from .project_store import ProjectStore, utc_now_iso
from .reports import REPORT_FILENAMES


class HandoffLightPackager:
    def __init__(self, store: ProjectStore) -> None:
        self.store = store

    def build_handoff_zip(self, state: ProjectState) -> Path:
        next_version = state.last_handoff_version + 1
        filename = f"V{next_version:03d}_{state.project_slug}_HANDOFF.zip"
        build_root = state.cache_dir / f"build_v{next_version:03d}"
        if build_root.exists():
            shutil.rmtree(build_root)
        build_root.mkdir(parents=True, exist_ok=True)
        asset_registry = self._portable_asset_registry(state)
        manifest = {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "project_id": state.project_id,
            "project_name": state.project_name,
            "handoff_version": next_version,
            "handoff_filename": filename,
            "created_at": utc_now_iso(),
            "previous_handoff": state.last_handoff_filename,
            "asset_count": len(asset_registry["assets"]),
            "new_asset_count": sum(1 for asset in state.assets if asset.added_after_handoff_version == state.last_handoff_version),
            "duplicate_count": len(state.last_ingest_report.get("duplicate_assets", [])),
            "missing_asset_count": sum(1 for asset in state.assets if asset.missing),
            "application_version": "V0.1.0",
        }
        self._stage_required_files(state, build_root, manifest, asset_registry)
        json_dump(
            build_root / "REPORTS" / REPORT_FILENAMES["build_validation"],
            {
                "schema_version": "1.0",
                "status": "pre_validation_placeholder",
                "application_version": "V0.1.0",
            },
        )
        zip_path = state.handoffs_dir / filename
        self._zip_directory(build_root, zip_path)
        validation = self._validate_handoff_zip(zip_path, asset_registry)
        json_dump(build_root / "REPORTS" / REPORT_FILENAMES["build_validation"], validation)
        self._zip_directory(build_root, zip_path)
        final_validation = self._validate_handoff_zip(zip_path, asset_registry)
        state.last_handoff_version = next_version
        state.last_handoff_filename = filename
        state.ingestion_history.append({
            "built_at": utc_now_iso(),
            "handoff_version": next_version,
            "handoff_filename": filename,
            "validation": final_validation,
        })
        self.store.save(state)
        return zip_path

    def _stage_required_files(
        self,
        state: ProjectState,
        build_root: Path,
        manifest: dict[str, object],
        asset_registry: dict[str, object],
    ) -> None:
        (build_root / "PROXIES").mkdir(parents=True, exist_ok=True)
        (build_root / "PHOTOS").mkdir(parents=True, exist_ok=True)
        (build_root / "AUDIO").mkdir(parents=True, exist_ok=True)
        (build_root / "METADATA").mkdir(parents=True, exist_ok=True)
        (build_root / "REPORTS").mkdir(parents=True, exist_ok=True)
        (build_root / "METADATA" / "sidecars").mkdir(parents=True, exist_ok=True)
        (build_root / "00_START_HERE.md").write_text(
            "# START HERE\n\nReview `PROJECT_BRIEF.md`, `handoff_manifest.json`, `asset_registry.json`, and the JSON reports under `REPORTS/`.\n",
            encoding="utf-8",
        )
        (build_root / "PROJECT_BRIEF.md").write_text(
            (
                f"# {state.project_name}\n\n"
                f"- Application: Handoff Light V0.1.0\n"
                f"- Handoff version: V{state.last_handoff_version + 1:03d}\n"
                f"- Registered assets: {len(state.assets)}\n"
            ),
            encoding="utf-8",
        )
        json_dump(build_root / "handoff_manifest.json", manifest)
        json_dump(build_root / "asset_registry.json", asset_registry)
        for asset in state.assets:
            if asset.package_path:
                source = Path(asset.proxy_path or asset.local_copy_path or "")
                if source.exists():
                    shutil.copy2(source, build_root / asset.package_path)
            if asset.metadata_path:
                shutil.copy2(Path(asset.metadata_path), build_root / (asset.metadata_package_path or f"METADATA/{Path(asset.metadata_path).name}"))
        for report_key, filename in REPORT_FILENAMES.items():
            if report_key == "build_validation":
                continue
            source = state.reports_dir / filename
            if source.exists():
                shutil.copy2(source, build_root / "REPORTS" / filename)

    def _portable_asset_registry(self, state: ProjectState) -> dict[str, object]:
        return {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "project_id": state.project_id,
            "project_name": state.project_name,
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "original_name": asset.original_name,
                    "media_type": asset.media_type,
                    "size_bytes": asset.size_bytes,
                    "sha256": asset.sha256,
                    "package_path": asset.package_path,
                    "metadata_path": asset.metadata_package_path,
                    "source_chain": asset.source_chain,
                    "archive_depth": asset.archive_depth,
                    "missing": asset.missing,
                    "inspection": self._sanitize_portable_value(asset.inspection),
                }
                for asset in state.assets
            ],
        }

    def _sanitize_portable_value(self, value: object) -> object:
        if isinstance(value, dict):
            return {key: self._sanitize_portable_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._sanitize_portable_value(item) for item in value]
        if isinstance(value, str):
            return re.sub(r"[A-Za-z]:\\\\[^\"'\n\r]+", "<redacted-local-path>", value)
        return value

    def _zip_directory(self, source_dir: Path, zip_path: Path) -> None:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(source_dir.rglob("*"), key=lambda item: item.as_posix().lower()):
                if path.is_dir():
                    continue
                archive.write(path, arcname=path.relative_to(source_dir).as_posix())

    def _validate_handoff_zip(self, zip_path: Path, asset_registry: dict[str, object]) -> dict[str, object]:
        required_entries = {
            "00_START_HERE.md",
            "PROJECT_BRIEF.md",
            "handoff_manifest.json",
            "asset_registry.json",
            "REPORTS/NEW_MATERIAL.json",
            "REPORTS/DUPLICATES.json",
            "REPORTS/MISSING_FILES.json",
            "REPORTS/DAMAGED_FILES.json",
            "REPORTS/UNSUPPORTED_FILES.json",
            "REPORTS/BUILD_VALIDATION_REPORT.json",
        }
        for asset in asset_registry["assets"]:
            if asset["package_path"]:
                required_entries.add(str(asset["package_path"]))
            if asset["metadata_path"]:
                required_entries.add(str(asset["metadata_path"]))
        entries: set[str] = set()
        with zipfile.ZipFile(zip_path) as archive:
            crc_result = archive.testzip()
            for info in archive.infolist():
                if info.is_dir():
                    continue
                entries.add(info.filename)
                if Path(info.filename).is_absolute():
                    raise ValueError(f"Absolute path leaked into package: {info.filename}")
                data = archive.read(info.filename)
                if info.filename.endswith(".json"):
                    json.loads(data.decode("utf-8"))
            missing_entries = sorted(required_entries - entries)
            if missing_entries:
                raise ValueError(f"Missing required package entries: {missing_entries}")
            return {
                "schema_version": "1.0",
                "zip_path": str(zip_path),
                "crc_ok": crc_result is None,
                "entry_count": len(entries),
                "required_entries_present": sorted(required_entries),
                "no_absolute_paths": True,
            }
