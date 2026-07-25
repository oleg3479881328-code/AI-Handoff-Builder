from __future__ import annotations

import json
from pathlib import Path

from handoff_builder.utils import file_sha256

from ..errors import UnsafePackageError


ACTIVE_REGISTRY_FILENAME = "local_asset_registry.json"


def _active_registry_path(workspace: Path) -> Path:
    return workspace.resolve() / "analysis" / ACTIVE_REGISTRY_FILENAME


def load_active_local_registry(workspace: Path, *, fallback_dir: Path | None = None) -> dict:
    registry_path = _active_registry_path(workspace)
    if registry_path.exists():
        return _read_registry(registry_path)
    if fallback_dir is not None:
        candidate = fallback_dir.resolve() / ACTIVE_REGISTRY_FILENAME
        if candidate.exists():
            payload = _read_registry(candidate)
            persist_active_local_registry(workspace, payload)
            return payload
    raise UnsafePackageError(
        "Active local_asset_registry.json is missing. Put it in the workspace analysis folder or next to the imported AI_EDIT_PACKAGE.zip."
    )


def persist_active_local_registry(workspace: Path, payload: dict) -> Path:
    target = _active_registry_path(workspace)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def resolve_plan_assets_against_registry(plan_assets: list[dict], registry_payload: dict) -> dict:
    registry_assets = registry_payload.get("assets")
    if not isinstance(registry_assets, list):
        raise UnsafePackageError("local_asset_registry.json must contain an assets array.")

    by_asset_id: dict[str, list[dict]] = {}
    for item in registry_assets:
        asset_id = str(item.get("asset_id") or "")
        if not asset_id:
            continue
        by_asset_id.setdefault(asset_id, []).append(item)

    results: list[dict] = []
    resolved_count = 0
    for plan_asset in plan_assets:
        asset_id = str(plan_asset["asset_id"])
        matches = by_asset_id.get(asset_id, [])
        if not matches:
            raise UnsafePackageError(f"Asset resolution failed: missing asset_id {asset_id}")
        if len(matches) > 1:
            raise UnsafePackageError(f"Asset resolution failed: ambiguous asset_id {asset_id}")

        registry_asset = matches[0]
        source_path = Path(str(registry_asset.get("source_path") or "")).expanduser()
        if not source_path.exists():
            raise UnsafePackageError(f"Asset resolution failed: source file missing for {asset_id}")
        if not source_path.is_file():
            raise UnsafePackageError(f"Asset resolution failed: unreadable source path for {asset_id}")

        expected_sha256 = str(plan_asset.get("sha256") or registry_asset.get("sha256") or "")
        if not expected_sha256:
            raise UnsafePackageError(f"Asset resolution failed: missing sha256 for {asset_id}")
        actual_sha256 = file_sha256(source_path)
        if actual_sha256 != expected_sha256:
            raise UnsafePackageError(
                f"Asset resolution failed: checksum mismatch for {asset_id}: {actual_sha256} != {expected_sha256}"
            )

        expected_size = int(plan_asset.get("size_bytes") or registry_asset.get("size_bytes") or 0)
        actual_size = source_path.stat().st_size
        if expected_size and actual_size != expected_size:
            raise UnsafePackageError(
                f"Asset resolution failed: size mismatch for {asset_id}: {actual_size} != {expected_size}"
            )

        resolved_count += 1
        results.append(
            {
                "asset_id": asset_id,
                "status": "resolved",
                "source_path": str(source_path.resolve()),
                "media_type": str(registry_asset.get("media_type") or plan_asset.get("media_type") or ""),
                "sha256": actual_sha256,
                "size_bytes": actual_size,
                "original_name": registry_asset.get("original_name"),
                "capture_time": registry_asset.get("capture_time"),
                "analysis_preview_paths": registry_asset.get("analysis_preview_paths") or {},
            }
        )

    return {
        "registry_schema_version": str(registry_payload.get("schema_version") or ""),
        "resolved_asset_count": resolved_count,
        "assets": results,
    }


def _read_registry(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise UnsafePackageError(f"Invalid local asset registry: {path}")
    return payload
