from __future__ import annotations

import hashlib
import json
import re
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


def validate_payload(schema_type: str, version: str, payload: object) -> None:
    schema = load_schema(schema_type, version)
    _validate_node(payload, schema, path=schema_type)


def _validate_node(value: object, schema: dict, *, path: str) -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(value, dict):
            raise ValueError(f"{path} must be an object.")
        required = schema.get("required", [])
        for name in required:
            if name not in value:
                raise ValueError(f"{path}.{name} is required.")
        if schema.get("additionalProperties") is False:
            allowed = set(schema.get("properties", {}).keys())
            extra = set(value.keys()) - allowed
            if extra:
                raise ValueError(f"{path} has unsupported fields: {sorted(extra)}")
        for name, prop_schema in schema.get("properties", {}).items():
            if name in value:
                _validate_node(value[name], prop_schema, path=f"{path}.{name}")
        return
    if schema_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"{path} must be an array.")
        item_schema = schema.get("items", {})
        for index, item in enumerate(value):
            _validate_node(item, item_schema, path=f"{path}[{index}]")
        return
    if schema_type == "string":
        if not isinstance(value, str):
            raise ValueError(f"{path} must be a string.")
        if "const" in schema and value != schema["const"]:
            raise ValueError(f"{path} must equal {schema['const']}.")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} must be one of {schema['enum']}.")
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            raise ValueError(f"{path} must be at least {min_length} characters.")
        pattern = schema.get("pattern")
        if pattern and not re.fullmatch(pattern, value):
            raise ValueError(f"{path} does not match required pattern.")
        if schema.get("format") == "date-time" and "T" not in value:
            raise ValueError(f"{path} must be a date-time string.")
        return
    if schema_type == "integer":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError(f"{path} must be an integer.")
        if "enum" in schema and value not in schema["enum"]:
            raise ValueError(f"{path} must be one of {schema['enum']}.")
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            raise ValueError(f"{path} must be >= {minimum}.")
        return
    if schema_type == "number":
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{path} must be a number.")
        return
    if schema_type is None:
        if "const" in schema and value != schema["const"]:
            raise ValueError(f"{path} must equal {schema['const']}.")
        return
