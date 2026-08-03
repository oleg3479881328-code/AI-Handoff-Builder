from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

from .common import utc_now_iso
from .errors import UnsafePackageError
from .plans.schema import load_bounded_json_object
from .workspace import load_project_config


def _registry_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AI Handoff Builder"
    return Path.home() / ".ai_handoff_builder" / "AI Handoff Builder"


def get_project_registry_path() -> Path:
    return _registry_root() / "project_registry.json"


def get_local_handoff_index_path(project_root: Path) -> Path:
    return project_root.resolve() / "analysis" / "handoff_index.json"


class ProjectRegistryStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_project_registry_path()

    def load(self) -> dict:
        if not self.path.exists():
            return {"schema_version": "1.0", "projects": []}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"schema_version": "1.0", "projects": []}
        projects = payload.get("projects")
        if not isinstance(projects, list):
            return {"schema_version": "1.0", "projects": []}
        return {"schema_version": "1.0", "projects": projects}

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def register_project(
        self,
        *,
        project_root: Path,
        project_id: str,
        project_name: str | None = None,
        handoff_id: str,
        handoff_sha256: str,
        handoff_content_hash: str | None = None,
        source_zip_path: Path | None = None,
        source_plan_path: Path | None = None,
        archive_path: Path | None = None,
    ) -> None:
        payload = self.load()
        updated_at = utc_now_iso()
        normalized_root = str(project_root.resolve())
        entries = [
            entry
            for entry in payload["projects"]
            if not (
                str(entry.get("project_root")) == normalized_root
                and str(entry.get("project_id")) == project_id
                and str(entry.get("handoff_id")) == handoff_id
                and str(entry.get("handoff_sha256")) == handoff_sha256
                and str(entry.get("handoff_content_hash") or "") == str(handoff_content_hash or "")
            )
        ]
        entries.append(
            {
                "project_root": normalized_root,
                "project_id": project_id,
                "project_name": project_name,
                "handoff_id": handoff_id,
                "handoff_sha256": handoff_sha256,
                "handoff_content_hash": handoff_content_hash,
                "source_zip_path": str(source_zip_path.resolve()) if source_zip_path else None,
                "source_plan_path": str(source_plan_path.resolve()) if source_plan_path else None,
                "archive_path": str(archive_path.resolve()) if archive_path else None,
                "updated_at": updated_at,
            }
        )
        payload["projects"] = entries[-200:]
        self.save(payload)

    def resolve_project_root(
        self,
        *,
        project_id: str,
        handoff_id: str,
        handoff_sha256: str | None = None,
        handoff_content_hash: str | None = None,
        allow_project_id_fallback: bool = True,
    ) -> Path | None:
        payload = self.load()
        exact = [
            Path(entry["project_root"])
            for entry in payload["projects"]
            if str(entry.get("project_id")) == project_id
            and str(entry.get("handoff_id")) == handoff_id
            and (
                (handoff_content_hash and str(entry.get("handoff_content_hash") or "") == handoff_content_hash)
                or (handoff_sha256 and str(entry.get("handoff_sha256")) == handoff_sha256)
            )
        ]
        if exact:
            return exact[-1].resolve()
        if not allow_project_id_fallback:
            return None
        project_only = [
            Path(entry["project_root"])
            for entry in payload["projects"]
            if str(entry.get("project_id")) == project_id
        ]
        if len(project_only) == 1:
            return project_only[0].resolve()
        return None


def read_package_identity(package_zip: Path) -> dict[str, str]:
    with zipfile.ZipFile(package_zip) as archive:
        try:
            raw = archive.read("ai_edit_package.json")
        except KeyError as exc:
            raise UnsafePackageError("Package manifest ai_edit_package.json is missing.") from exc
    payload = json.loads(raw.decode("utf-8"))
    return {
        "project_id": str(payload["project_id"]),
        "handoff_id": str(payload["handoff_id"]),
        "handoff_sha256": str(payload["handoff_sha256"]),
    }


def read_plan_identity(plan_json: Path) -> dict[str, str]:
    payload = load_bounded_json_object(plan_json)
    return {
        "project_id": str(payload["project_id"]),
        "handoff_id": str(payload["handoff_id"]),
        "handoff_content_hash": str(payload["handoff_content_hash"]),
        "project_name": str(payload.get("project_name") or ""),
    }


def record_local_handoff(
    *,
    project_root: Path,
    project_id: str,
    project_name: str | None = None,
    handoff_id: str,
    handoff_sha256: str,
    handoff_content_hash: str | None = None,
    source_zip_path: Path | None = None,
    source_plan_path: Path | None = None,
    archive_path: Path | None = None,
) -> Path:
    index_path = get_local_handoff_index_path(project_root)
    payload = {"schema_version": "1.0", "handoffs": []}
    if index_path.exists():
        try:
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if isinstance(loaded.get("handoffs"), list):
                payload = {"schema_version": "1.0", "handoffs": loaded["handoffs"]}
        except (OSError, json.JSONDecodeError):
            payload = {"schema_version": "1.0", "handoffs": []}
    entries = [
        entry
        for entry in payload["handoffs"]
        if not (
            str(entry.get("project_id")) == project_id
            and str(entry.get("handoff_id")) == handoff_id
            and str(entry.get("handoff_sha256")) == handoff_sha256
            and str(entry.get("handoff_content_hash") or "") == str(handoff_content_hash or "")
        )
    ]
    entries.append(
        {
            "project_id": project_id,
            "project_name": project_name,
            "handoff_id": handoff_id,
            "handoff_sha256": handoff_sha256,
            "handoff_content_hash": handoff_content_hash,
            "source_zip_path": str(source_zip_path.resolve()) if source_zip_path else None,
            "source_plan_path": str(source_plan_path.resolve()) if source_plan_path else None,
            "archive_path": str(archive_path.resolve()) if archive_path else None,
            "updated_at": utc_now_iso(),
        }
    )
    payload["handoffs"] = entries[-50:]
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return index_path


def verify_project_identity(
    project_root: Path,
    *,
    project_id: str,
    handoff_id: str,
    handoff_sha256: str | None = None,
    handoff_content_hash: str | None = None,
) -> Path:
    resolved_root = project_root.resolve()
    config = load_project_config(resolved_root)
    if str(config["project_id"]) != project_id:
        raise UnsafePackageError(
            f"Fallback project mismatch: {config['project_id']} != {project_id}"
        )
    index_path = get_local_handoff_index_path(resolved_root)
    if not index_path.exists():
        raise UnsafePackageError(
            "Project handoff identity is missing. Rebuild the ANALYSIS_HANDOFF.zip once in the original project folder."
        )
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    for entry in payload.get("handoffs", []):
        if (
            str(entry.get("project_id")) == project_id
            and str(entry.get("handoff_id")) == handoff_id
            and (
                (handoff_content_hash and str(entry.get("handoff_content_hash") or "") == handoff_content_hash)
                or (handoff_sha256 and str(entry.get("handoff_sha256")) == handoff_sha256)
            )
        ):
            return resolved_root
    raise UnsafePackageError(
        "Selected project folder does not match the saved handoff identity."
    )


def find_local_handoff_entry(
    project_root: Path,
    *,
    project_id: str,
    handoff_id: str,
    handoff_sha256: str | None = None,
    handoff_content_hash: str | None = None,
) -> dict | None:
    index_path = get_local_handoff_index_path(project_root.resolve())
    if not index_path.exists():
        return None
    payload = json.loads(index_path.read_text(encoding="utf-8"))
    for entry in payload.get("handoffs", []):
        if (
            str(entry.get("project_id")) == project_id
            and str(entry.get("handoff_id")) == handoff_id
            and (
                (handoff_content_hash and str(entry.get("handoff_content_hash") or "") == handoff_content_hash)
                or (handoff_sha256 and str(entry.get("handoff_sha256")) == handoff_sha256)
            )
        ):
            return dict(entry)
    return None


def resolve_workspace_from_hint(hint_path: Path) -> Path:
    resolved = hint_path.resolve()
    if resolved.is_file() and resolved.suffix.lower() == ".zip":
        return resolved.parent / resolved.stem
    return resolved.parent if resolved.is_file() else resolved

