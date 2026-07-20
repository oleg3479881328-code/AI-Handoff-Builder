from __future__ import annotations

import sqlite3


MIGRATIONS: tuple[tuple[str, str], ...] = (
    (
        "0001_initial_workspace",
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            migration_id TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS imported_handoffs (
            handoff_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            handoff_sha256 TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS render_queue (
            render_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            handoff_id TEXT NOT NULL,
            plan_id TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """,
    ),
)


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN")
    try:
        for migration_id, sql in MIGRATIONS:
            exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE migration_id = ?",
                (migration_id,),
            ).fetchone()
            if exists:
                continue
            connection.executescript(sql)
            connection.execute(
                "INSERT INTO schema_migrations (migration_id) VALUES (?)",
                (migration_id,),
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
