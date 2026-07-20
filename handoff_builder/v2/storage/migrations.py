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

        CREATE TABLE IF NOT EXISTS projects (
            project_id TEXT NOT NULL,
            workspace_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (project_id)
        );

        CREATE TABLE IF NOT EXISTS ai_packages (
            package_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            handoff_id TEXT NOT NULL,
            handoff_sha256 TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            package_sha256 TEXT NOT NULL,
            source_zip_name TEXT NOT NULL,
            extracted_root TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (project_id, package_sha256)
        );

        CREATE TABLE IF NOT EXISTS edit_plans (
            edit_plan_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            package_id TEXT NOT NULL REFERENCES ai_packages(package_id) ON DELETE RESTRICT,
            handoff_id TEXT NOT NULL,
            schema_version TEXT NOT NULL,
            plan_sha256 TEXT NOT NULL,
            plan_hash TEXT NOT NULL,
            plan_path TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (package_id, plan_hash)
        );

        CREATE TABLE IF NOT EXISTS render_jobs (
            render_job_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            package_id TEXT NOT NULL REFERENCES ai_packages(package_id) ON DELETE RESTRICT,
            edit_plan_id TEXT NOT NULL REFERENCES edit_plans(edit_plan_id) ON DELETE RESTRICT,
            status TEXT NOT NULL,
            attempt_number INTEGER NOT NULL,
            parent_render_job_id TEXT REFERENCES render_jobs(render_job_id) ON DELETE RESTRICT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS render_outputs (
            output_id TEXT PRIMARY KEY,
            render_job_id TEXT NOT NULL REFERENCES render_jobs(render_job_id) ON DELETE CASCADE,
            report_path TEXT NOT NULL,
            renderer_status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            package_id TEXT REFERENCES ai_packages(package_id) ON DELETE RESTRICT,
            render_job_id TEXT REFERENCES render_jobs(render_job_id) ON DELETE RESTRICT,
            event_type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_ai_packages_project ON ai_packages(project_id);
        CREATE INDEX IF NOT EXISTS idx_edit_plans_project ON edit_plans(project_id);
        CREATE INDEX IF NOT EXISTS idx_render_jobs_project ON render_jobs(project_id);
        CREATE INDEX IF NOT EXISTS idx_render_jobs_status ON render_jobs(status, created_at);
        CREATE INDEX IF NOT EXISTS idx_events_project ON events(project_id, created_at);
        """,
    ),
    (
        "0002_render_job_lifecycle_fields",
        """
        ALTER TABLE render_jobs ADD COLUMN started_at TEXT;
        ALTER TABLE render_jobs ADD COLUMN finished_at TEXT;
        ALTER TABLE render_jobs ADD COLUMN failed_stage TEXT;
        ALTER TABLE render_jobs ADD COLUMN error_code TEXT;
        ALTER TABLE render_jobs ADD COLUMN error_message TEXT;
        ALTER TABLE render_jobs ADD COLUMN ffmpeg_exit_code INTEGER;
        """,
    ),
    (
        "0003_patch_lineage",
        """
        ALTER TABLE edit_plans ADD COLUMN plan_version INTEGER NOT NULL DEFAULT 1;
        ALTER TABLE edit_plans ADD COLUMN parent_plan_id TEXT REFERENCES edit_plans(edit_plan_id) ON DELETE RESTRICT;
        ALTER TABLE edit_plans ADD COLUMN patch_id TEXT;
        ALTER TABLE edit_plans ADD COLUMN base_plan_hash TEXT;

        CREATE TABLE IF NOT EXISTS edit_patches (
            patch_row_id TEXT PRIMARY KEY,
            patch_id TEXT NOT NULL,
            project_id TEXT NOT NULL REFERENCES projects(project_id) ON DELETE RESTRICT,
            package_id TEXT NOT NULL REFERENCES ai_packages(package_id) ON DELETE RESTRICT,
            handoff_id TEXT NOT NULL,
            patch_sha256 TEXT NOT NULL,
            base_plan_id TEXT NOT NULL REFERENCES edit_plans(edit_plan_id) ON DELETE RESTRICT,
            base_plan_hash TEXT NOT NULL,
            new_plan_id TEXT NOT NULL REFERENCES edit_plans(edit_plan_id) ON DELETE RESTRICT,
            new_plan_hash TEXT NOT NULL,
            patch_source_path TEXT NOT NULL,
            patch_payload_path TEXT NOT NULL,
            status TEXT NOT NULL,
            error_code TEXT,
            error_message TEXT,
            created_at TEXT NOT NULL,
            applied_at TEXT NOT NULL,
            UNIQUE (project_id, patch_sha256, base_plan_id),
            UNIQUE (new_plan_id)
        );

        CREATE INDEX IF NOT EXISTS idx_edit_plans_parent_plan ON edit_plans(parent_plan_id);
        CREATE INDEX IF NOT EXISTS idx_edit_plans_patch_id ON edit_plans(patch_id);
        CREATE INDEX IF NOT EXISTS idx_edit_patches_project ON edit_patches(project_id, applied_at);
        CREATE INDEX IF NOT EXISTS idx_edit_patches_base_plan ON edit_patches(base_plan_id, applied_at);
        """,
    ),
)


def apply_migrations(connection: sqlite3.Connection) -> None:
    connection.execute("BEGIN")
    try:
        for migration_id, sql in MIGRATIONS:
            migrations_table_exists = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'schema_migrations'
                """
            ).fetchone()
            exists = None
            if migrations_table_exists:
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
