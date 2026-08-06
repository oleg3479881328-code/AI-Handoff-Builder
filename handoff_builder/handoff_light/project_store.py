from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from handoff_builder.utils import json_dump, slugify

from .models import AssetRecord, ProjectState


def utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ProjectStore:
    def __init__(self, projects_root: Path) -> None:
        self.projects_root = projects_root

    def create_project(self, project_name: str) -> ProjectState:
        slug = slugify(project_name, fallback="handoff_light_project")
        root = self.projects_root / slug
        root.mkdir(parents=True, exist_ok=False)
        for dirname in ("cache", "proxies", "photos", "audio", "metadata", "reports", "handoffs"):
            (root / dirname).mkdir(parents=True, exist_ok=True)
        now = utc_now_iso()
        state = ProjectState(
            project_id=f"hl-{uuid.uuid4()}",
            project_name=project_name.strip(),
            project_slug=slug,
            root=root,
            created_at=now,
            updated_at=now,
        )
        self.save(state)
        return state

    def open_project(self, project_dir: Path) -> ProjectState:
        project_dir = project_dir.resolve()
        project_payload = self._read_json(project_dir / "project.json")
        asset_payload = self._read_json(project_dir / "asset_registry.json")
        history_payload = self._read_json(project_dir / "ingestion_history.json")
        state = ProjectState(
            project_id=str(project_payload["project_id"]),
            project_name=str(project_payload["project_name"]),
            project_slug=str(project_payload["project_slug"]),
            root=project_dir,
            created_at=str(project_payload["created_at"]),
            updated_at=str(project_payload["updated_at"]),
            last_handoff_version=int(project_payload.get("last_handoff_version", 0)),
            last_handoff_filename=project_payload.get("last_handoff_filename"),
            assets=[AssetRecord(**item) for item in asset_payload.get("assets", [])],
            ingestion_history=list(history_payload),
            last_ingest_report=project_payload.get("last_ingest_report", {}),
        )
        self._ensure_dirs(state)
        return state

    def save(self, state: ProjectState) -> None:
        state.updated_at = utc_now_iso()
        self._ensure_dirs(state)
        json_dump(
            state.project_file,
            {
                "project_id": state.project_id,
                "project_name": state.project_name,
                "project_slug": state.project_slug,
                "created_at": state.created_at,
                "updated_at": state.updated_at,
                "last_handoff_version": state.last_handoff_version,
                "last_handoff_filename": state.last_handoff_filename,
                "last_ingest_report": state.last_ingest_report,
            },
        )
        json_dump(
            state.asset_registry_file,
            {
                "schema_version": "1.0",
                "assets": [asdict(asset) for asset in state.assets],
            },
        )
        json_dump(state.ingestion_history_file, state.ingestion_history)

    def _ensure_dirs(self, state: ProjectState) -> None:
        state.root.mkdir(parents=True, exist_ok=True)
        for path in (
            state.cache_dir,
            state.proxies_dir,
            state.photos_dir,
            state.audio_dir,
            state.metadata_dir,
            state.reports_dir,
            state.handoffs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)

    def _read_json(self, path: Path) -> dict | list:
        if not path.exists():
            return {} if path.suffix == ".json" else []
        import json

        return json.loads(path.read_text(encoding="utf-8"))
