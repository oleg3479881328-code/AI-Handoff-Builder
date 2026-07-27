from __future__ import annotations

import json
from pathlib import Path

from ..domain.records import ImportedPackage, PackageFile
from ..errors import ChecksumMismatchError, ProjectMismatchError, UnsafePackageError
from ..plans.schema import validate_payload
from .guards import compute_sha256, ensure_allowed_package_path, reject_media_payloads, safe_extract_package_zip, verify_package_checksums


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def import_edit_package(
    zip_path: Path,
    staging_dir: Path,
    *,
    expected_project_id: str | None = None,
    max_total_bytes: int = 512 * 1024 * 1024,
    package_root: Path | None = None,
) -> ImportedPackage:
    package_root = package_root or (staging_dir / zip_path.stem)
    if package_root.exists():
        raise UnsafePackageError(f"Import destination already exists: {package_root}")

    safe_extract_package_zip(zip_path, package_root, max_total_bytes=max_total_bytes)
    manifest_path = package_root / "ai_edit_package.json"
    if not manifest_path.exists():
        raise UnsafePackageError("Package manifest ai_edit_package.json is missing.")

    manifest = _read_json(manifest_path)
    schema_version = str(manifest["schema_version"])
    validate_payload("ai_edit_package", schema_version, manifest)

    project_id = str(manifest["project_id"])
    if expected_project_id and project_id != expected_project_id:
        raise ProjectMismatchError(
            f"Package project mismatch: {project_id} != {expected_project_id}"
        )

    files = verify_package_checksums(package_root, list(manifest.get("package_files", [])))
    if schema_version in {"2.0", "2.1"}:
        reject_media_payloads(package_root)
        files = verify_package_checksums(
            package_root,
            [
                {
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "size_bytes": int((package_root / str(item["path"])).stat().st_size),
                }
                for item in manifest.get("plans", [])
            ],
        )
    elif schema_version == "3.0":
        reject_media_payloads(package_root, allow_audio=True)
        audio_track = manifest.get("audio_track")
        if audio_track:
            audio_path = str(audio_track["path"])
            ensure_allowed_package_path(audio_path)
            audio_file = package_root / audio_path
            if not audio_file.exists():
                raise UnsafePackageError(f"Declared audio track is missing: {audio_path}")
            actual_sha = compute_sha256(audio_file)
            if actual_sha != audio_track["sha256"]:
                raise ChecksumMismatchError(
                    f"Checksum mismatch for audio track {audio_path}: {actual_sha} != {audio_track['sha256']}"
                )
            actual_size = audio_file.stat().st_size
            if actual_size != audio_track["size_bytes"]:
                raise UnsafePackageError(
                    f"Size mismatch for audio track {audio_path}: {actual_size} != {audio_track['size_bytes']}"
                )
        files = verify_package_checksums(
            package_root,
            [
                {
                    "path": item["path"],
                    "sha256": item["sha256"],
                    "size_bytes": int((package_root / str(item["path"])).stat().st_size),
                }
                for item in manifest.get("plans", [])
            ],
        )
    package_sha256 = compute_sha256(zip_path)
    plan_ids = tuple(
        str(item["plan_id"]) for item in manifest.get("plans", [])
    )
    package_files = tuple(
        PackageFile(path=rel_path, sha256=digest, size_bytes=size_bytes)
        for rel_path, digest, size_bytes in files
    )
    return ImportedPackage(
        package_id=package_sha256[:16],
        project_id=project_id,
        handoff_id=str(manifest["handoff_id"]),
        handoff_sha256=str(manifest["handoff_sha256"]),
        package_sha256=package_sha256,
        schema_version=schema_version,
        source_zip=zip_path.resolve(),
        extracted_root=package_root.resolve(),
        files=package_files,
        plan_ids=plan_ids,
    )
