from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..common import stable_v2_id, utc_now_iso


class VoiceStudioRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection

    def add_runtime_snapshot(self, *, base_url: str, payload: dict[str, Any]) -> str:
        snapshot_id = stable_v2_id(base_url, utc_now_iso(), length=20)
        self.connection.execute(
            """
            INSERT INTO voice_runtime_snapshots (
                snapshot_id, base_url, payload_json, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (snapshot_id, base_url, json.dumps(payload, ensure_ascii=False), utc_now_iso()),
        )
        return snapshot_id

    def upsert_profile_mapping(
        self,
        *,
        profile_key: str,
        profile_id: str,
        profile_name: str,
        language: str,
        default_engine: str | None,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO voice_profile_mappings (
                profile_key, profile_id, profile_name, language, default_engine,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(profile_key) DO UPDATE SET
                profile_id = excluded.profile_id,
                profile_name = excluded.profile_name,
                language = excluded.language,
                default_engine = excluded.default_engine,
                updated_at = excluded.updated_at
            """,
            (
                profile_key,
                profile_id,
                profile_name,
                language,
                default_engine,
                utc_now_iso(),
                utc_now_iso(),
            ),
        )

    def get_profile_mapping(self, profile_key: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM voice_profile_mappings WHERE profile_key = ?",
            (profile_key,),
        ).fetchone()

    def list_profile_mappings(self) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM voice_profile_mappings ORDER BY profile_key"
            )
        )

    def create_voice_job(
        self,
        *,
        job_id: str,
        project_id: str,
        profile_key: str,
        spec_path: Path,
        spec_hash: str,
        target_duration_ms: int | None,
        status: str,
    ) -> None:
        timestamp = utc_now_iso()
        self.connection.execute(
            """
            INSERT INTO voice_jobs (
                voice_job_id, project_id, profile_key, spec_path, spec_hash,
                target_duration_ms, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                project_id,
                profile_key,
                str(spec_path),
                spec_hash,
                target_duration_ms,
                status,
                timestamp,
                timestamp,
            ),
        )

    def add_voice_job_version(
        self,
        *,
        version_id: str,
        voice_job_id: str,
        version_number: int,
        payload_path: Path,
        payload_hash: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO voice_job_versions (
                voice_job_version_id, voice_job_id, version_number, payload_path, payload_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (version_id, voice_job_id, version_number, str(payload_path), payload_hash, utc_now_iso()),
        )

    def update_voice_job_status(self, voice_job_id: str, status: str) -> None:
        self.connection.execute(
            "UPDATE voice_jobs SET status = ?, updated_at = ? WHERE voice_job_id = ?",
            (status, utc_now_iso(), voice_job_id),
        )

    def create_take(
        self,
        *,
        take_id: str,
        voice_job_id: str,
        generation_id: str,
        take_index: int,
        seed: int | None,
        raw_response_json: dict[str, Any],
        status: str,
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO voice_takes (
                voice_take_id, voice_job_id, generation_id, take_index, seed, status,
                response_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                take_id,
                voice_job_id,
                generation_id,
                take_index,
                seed,
                status,
                json.dumps(raw_response_json, ensure_ascii=False),
                utc_now_iso(),
                utc_now_iso(),
            ),
        )

    def update_take_artifact(
        self,
        *,
        take_id: str,
        status: str,
        raw_audio_path: Path | None = None,
        normalized_audio_path: Path | None = None,
        audio_sha256: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        self.connection.execute(
            """
            UPDATE voice_takes
            SET status = ?,
                raw_audio_path = COALESCE(?, raw_audio_path),
                normalized_audio_path = COALESCE(?, normalized_audio_path),
                audio_sha256 = COALESCE(?, audio_sha256),
                duration_ms = COALESCE(?, duration_ms),
                updated_at = ?
            WHERE voice_take_id = ?
            """,
            (
                status,
                str(raw_audio_path) if raw_audio_path else None,
                str(normalized_audio_path) if normalized_audio_path else None,
                audio_sha256,
                duration_ms,
                utc_now_iso(),
                take_id,
            ),
        )

    def set_take_qc(self, *, take_id: str, payload: dict[str, Any]) -> None:
        row_id = stable_v2_id(take_id, "qc", length=20)
        self.connection.execute(
            """
            INSERT INTO voice_take_qc (
                voice_take_qc_id, voice_take_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?)
            ON CONFLICT(voice_take_id) DO UPDATE SET
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (row_id, take_id, json.dumps(payload, ensure_ascii=False), utc_now_iso()),
        )

    def add_review(
        self,
        *,
        take_id: str,
        review_payload: dict[str, Any],
    ) -> str:
        review_id = stable_v2_id(take_id, utc_now_iso(), "review", length=20)
        self.connection.execute(
            """
            INSERT INTO voice_human_reviews (
                voice_review_id, voice_take_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (review_id, take_id, json.dumps(review_payload, ensure_ascii=False), utc_now_iso()),
        )
        return review_id

    def set_approval(
        self,
        *,
        voice_job_id: str,
        take_id: str,
        approved: bool,
        approval_payload: dict[str, Any],
    ) -> None:
        self.connection.execute(
            "UPDATE voice_approvals SET is_primary = 0 WHERE voice_job_id = ?",
            (voice_job_id,),
        )
        approval_id = stable_v2_id(voice_job_id, take_id, "approval", length=20)
        self.connection.execute(
            """
            INSERT INTO voice_approvals (
                voice_approval_id, voice_job_id, voice_take_id, is_primary, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(voice_take_id) DO UPDATE SET
                is_primary = excluded.is_primary,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (
                approval_id,
                voice_job_id,
                take_id,
                1 if approved else 0,
                json.dumps(approval_payload, ensure_ascii=False),
                utc_now_iso(),
            ),
        )

    def set_alignment(
        self,
        *,
        take_id: str,
        status: str,
        artifact_path: Path | None,
        payload: dict[str, Any],
    ) -> None:
        alignment_id = stable_v2_id(take_id, "alignment", length=20)
        self.connection.execute(
            """
            INSERT INTO voice_alignments (
                voice_alignment_id, voice_take_id, status, artifact_path, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(voice_take_id) DO UPDATE SET
                status = excluded.status,
                artifact_path = excluded.artifact_path,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (
                alignment_id,
                take_id,
                status,
                str(artifact_path) if artifact_path else None,
                json.dumps(payload, ensure_ascii=False),
                utc_now_iso(),
            ),
        )

    def set_mix_profile(
        self,
        *,
        voice_job_id: str,
        profile_key: str,
        payload: dict[str, Any],
    ) -> None:
        row_id = stable_v2_id(voice_job_id, "mix-profile", length=20)
        self.connection.execute(
            """
            INSERT INTO audio_mix_profiles (
                audio_mix_profile_id, voice_job_id, profile_key, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(voice_job_id) DO UPDATE SET
                profile_key = excluded.profile_key,
                payload_json = excluded.payload_json,
                created_at = excluded.created_at
            """,
            (row_id, voice_job_id, profile_key, json.dumps(payload, ensure_ascii=False), utc_now_iso()),
        )

    def add_mix_patch(
        self,
        *,
        voice_job_id: str,
        patch_payload: dict[str, Any],
    ) -> str:
        patch_id = stable_v2_id(voice_job_id, utc_now_iso(), "mix-patch", length=20)
        self.connection.execute(
            """
            INSERT INTO audio_mix_patches (
                audio_mix_patch_id, voice_job_id, payload_json, created_at
            ) VALUES (?, ?, ?, ?)
            """,
            (patch_id, voice_job_id, json.dumps(patch_payload, ensure_ascii=False), utc_now_iso()),
        )
        return patch_id

    def list_mix_patches(self, voice_job_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM audio_mix_patches WHERE voice_job_id = ? ORDER BY created_at, audio_mix_patch_id",
                (voice_job_id,),
            )
        )

    def get_mix_profile(self, voice_job_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM audio_mix_profiles WHERE voice_job_id = ?",
            (voice_job_id,),
        ).fetchone()

    def add_event(
        self,
        *,
        voice_job_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> str:
        event_id = stable_v2_id(voice_job_id, event_type, utc_now_iso(), length=20)
        self.connection.execute(
            """
            INSERT INTO voice_events (
                voice_event_id, voice_job_id, event_type, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (event_id, voice_job_id, event_type, json.dumps(payload, ensure_ascii=False), utc_now_iso()),
        )
        return event_id

    def get_voice_job(self, voice_job_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM voice_jobs WHERE voice_job_id = ?",
            (voice_job_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown voice job: {voice_job_id}")
        return row

    def list_voice_jobs(self, project_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM voice_jobs WHERE project_id = ? ORDER BY created_at, voice_job_id",
                (project_id,),
            )
        )

    def list_takes(self, voice_job_id: str) -> list[sqlite3.Row]:
        return list(
            self.connection.execute(
                "SELECT * FROM voice_takes WHERE voice_job_id = ? ORDER BY take_index, created_at",
                (voice_job_id,),
            )
        )

    def get_take(self, take_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM voice_takes WHERE voice_take_id = ?",
            (take_id,),
        ).fetchone()
        if row is None:
            raise KeyError(f"Unknown take: {take_id}")
        return row

    def get_take_qc(self, take_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM voice_take_qc WHERE voice_take_id = ?",
            (take_id,),
        ).fetchone()

    def get_primary_approval(self, voice_job_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM voice_approvals WHERE voice_job_id = ? AND is_primary = 1",
            (voice_job_id,),
        ).fetchone()

    def get_alignment(self, take_id: str) -> sqlite3.Row | None:
        return self.connection.execute(
            "SELECT * FROM voice_alignments WHERE voice_take_id = ?",
            (take_id,),
        ).fetchone()
