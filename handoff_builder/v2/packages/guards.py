from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

from handoff_builder.utils import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, safe_extract_zip

from ..errors import ChecksumMismatchError, UnsafePackageError


def _zip_member_is_symlink(info: zipfile.ZipInfo) -> bool:
    mode = info.external_attr >> 16
    return (mode & 0o170000) == 0o120000


def safe_extract_package_zip(
    zip_path: Path,
    destination: Path,
    *,
    max_total_bytes: int = 512 * 1024 * 1024,
) -> list[Path]:
    total_bytes = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if _zip_member_is_symlink(info):
                raise UnsafePackageError(f"Symlink ZIP member is not allowed: {info.filename}")
            total_bytes += int(info.file_size)
            if total_bytes > max_total_bytes:
                raise UnsafePackageError(
                    f"Package exceeds size limit: {total_bytes} > {max_total_bytes}"
                )
    return safe_extract_zip(zip_path, destination)


def ensure_allowed_package_path(path: str) -> None:
    normalized = path.replace("\\", "/").strip("/")
    allowed_prefixes = (
        "plans/",
        "patches/",
        "assets/",
        "manifests/",
        "reports/",
        "voice/",
    )
    if normalized in {"ai_edit_package.json", "edit_plan.json", "edit_patch.json", "render_report.json"}:
        return
    if not normalized.startswith(allowed_prefixes):
        raise UnsafePackageError(f"Package path is not allowlisted: {path}")


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_package_checksums(root: Path, files: list[dict]) -> tuple[tuple[str, str, int], ...]:
    verified: list[tuple[str, str, int]] = []
    for file_entry in files:
        rel_path = str(file_entry["path"])
        ensure_allowed_package_path(rel_path)
        target = (root / rel_path).resolve()
        if root.resolve() not in target.parents and target != root.resolve():
            raise UnsafePackageError(f"Package file escapes root: {rel_path}")
        if not target.exists():
            raise UnsafePackageError(f"Declared package file is missing: {rel_path}")
        digest = compute_sha256(target)
        expected = str(file_entry["sha256"])
        if digest != expected:
            raise ChecksumMismatchError(
                f"Checksum mismatch for {rel_path}: {digest} != {expected}"
            )
        verified.append((rel_path, digest, int(file_entry["size_bytes"])))
    return tuple(verified)


def reject_media_payloads(root: Path) -> tuple[str, ...]:
    forbidden_exts = set(PHOTO_EXTENSIONS) | set(VIDEO_EXTENSIONS) | {
        ".mp3", ".wav", ".aac", ".m4a", ".flac", ".ogg"
    }
    offenders: list[str] = []
    for file_path in root.rglob("*"):
        if not file_path.is_file():
            continue
        rel_path = file_path.relative_to(root).as_posix()
        ensure_allowed_package_path(rel_path)
        if file_path.suffix.lower() in forbidden_exts:
            offenders.append(rel_path)
    if offenders:
        raise UnsafePackageError(f"AI edit package 2.0 must not contain media payloads: {sorted(offenders)}")
    return tuple(sorted(offenders))


def verify_exact_inventory(
    zip_path: Path,
    declared_inventory: list[dict],
) -> tuple[tuple[str, str, int], ...]:
    """Verify that ZIP entries exactly match the declared file_inventory.

    Every declared entry must exist in the ZIP with matching size and sha256.
    Every ZIP entry must be declared. Path traversal and absolute paths are rejected.
    Returns sorted tuple of (path, sha256, size_bytes).
    """
    declared_by_path: dict[str, dict] = {}
    for entry in declared_inventory:
        raw_path = str(entry["path"])
        normalized = raw_path.replace("\\", "/")
        if normalized.startswith("/") or normalized.startswith(".."):
            raise UnsafePackageError(f"Path traversal or absolute path in inventory: {raw_path}")
        if normalized in declared_by_path:
            raise UnsafePackageError(f"Duplicate inventory entry: {normalized}")
        declared_by_path[normalized] = entry

    verified: list[tuple[str, str, int]] = []
    with zipfile.ZipFile(zip_path) as archive:
        zip_names = set(archive.namelist())

        # Check every declared entry exists in ZIP
        for norm_path, entry in declared_by_path.items():
            if norm_path not in zip_names:
                raise UnsafePackageError(f"Declared inventory entry missing from ZIP: {norm_path}")
            info = archive.getinfo(norm_path)
            actual_size = info.file_size
            expected_size = int(entry["size_bytes"])
            if actual_size != expected_size:
                raise UnsafePackageError(
                    f"Inventory size mismatch for {norm_path}: {actual_size} != {expected_size}"
                )
            # Compute sha256 from ZIP member data
            member_data = archive.read(norm_path)
            actual_sha256 = hashlib.sha256(member_data).hexdigest()
            expected_sha256 = str(entry["sha256"])
            if actual_sha256 != expected_sha256:
                raise ChecksumMismatchError(
                    f"Inventory checksum mismatch for {norm_path}: {actual_sha256} != {expected_sha256}"
                )
            verified.append((norm_path, actual_sha256, actual_size))

        # Check no undeclared entries in ZIP
        declared_set = set(declared_by_path.keys())
        undeclared = zip_names - declared_set
        if undeclared:
            raise UnsafePackageError(
                f"ZIP contains undeclared entries: {sorted(undeclared)}"
            )

    return tuple(sorted(verified, key=lambda x: x[0]))


def compute_content_hash(payload: dict) -> str:
    """Compute canonical content hash using RFC 8785 / JCS semantics.

    Same semantic content always produces the same hash regardless of
    key ordering, whitespace, or ZIP metadata.
    """
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()
