from __future__ import annotations

import json
from pathlib import Path

from .common import utc_now_iso
from .storage import apply_migrations, connect_workspace_db
from .storage.repositories import WorkspaceRepository
from .errors import UnsafePackageError


def init_project_workspace(workspace_dir: Path, project_id: str) -> Path:
    project_root = workspace_dir.resolve()
    project_file = project_root / "project.json"
    if project_file.exists():
        config = json.loads(project_file.read_text(encoding="utf-8"))
        existing_project_id = str(config["project_id"])
        if existing_project_id != project_id:
            raise UnsafePackageError(
                f"Workspace already belongs to another project: {existing_project_id} != {project_id}"
            )
    else:
        project_root.mkdir(parents=True, exist_ok=True)
    for relative in (
        "handoffs",
        "incoming_ai_packages",
        "ai_packages",
        "patches",
        "renders",
        "logs",
        "cache",
        "analysis",
        "proxies",
        "voice",
        "voice/runtime",
        "voice/profiles",
        "voice/reports",
    ):
        (project_root / relative).mkdir(parents=True, exist_ok=True)

    project_file.write_text(
        json.dumps(
            {
                "project_id": project_id,
                "created_at": utc_now_iso(),
                "workspace_path": str(project_root),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (project_root / "source_snapshot.json").write_text(
        json.dumps({"project_id": project_id, "sources": []}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    connection = connect_workspace_db(project_root / "project.sqlite")
    try:
        apply_migrations(connection)
        WorkspaceRepository(connection).create_project(project_id, project_root)
        connection.commit()
    finally:
        connection.close()
    return project_root


def load_project_config(project_root: Path) -> dict:
    return json.loads((project_root / "project.json").read_text(encoding="utf-8"))
