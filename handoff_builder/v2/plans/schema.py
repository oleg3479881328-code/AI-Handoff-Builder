from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..errors import UnsupportedSchemaVersionError


SCHEMA_ROOT = Path(__file__).resolve().parents[3] / "schemas"
SCHEMA_TYPES = ("ai_edit_package", "edit_plan", "edit_patch", "render_report")
SUPPORTED_SCHEMA_VERSIONS = {
    schema_type: {"1.0": SCHEMA_ROOT / schema_type / "1.0.json"}
    for schema_type in SCHEMA_TYPES
}


def schema_dispatch(schema_type: str, version: str) -> Path:
    try:
        return SUPPORTED_SCHEMA_VERSIONS[schema_type][version]
    except KeyError as exc:
        raise UnsupportedSchemaVersionError(
            f"Unsupported schema version for {schema_type}: {version}"
        ) from exc


def load_schema(schema_type: str, version: str) -> dict:
    path = schema_dispatch(schema_type, version)
    return json.loads(path.read_text(encoding="utf-8"))


def deterministic_plan_hash(payload: dict) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
