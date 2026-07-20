from __future__ import annotations

import json
from pathlib import Path

from .common import utc_now_iso
from .storage import apply_migrations, connect_workspace_db
from .storage.repositories import WorkspaceRepository


def init_project_workspace(work_dir: Path, project_id: str) -> Path:
    project_root = work_dir / project_id
    for relative in (
        "handoffs",
        "ai_packages",
        "renders",
        "logs",
        "cache",
        "analysis",
        "proxies",
    ):
        (project_root / relative).mkdir(parents=True, exist_ok=True)

    (project_root / "project.json").write_text(
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
