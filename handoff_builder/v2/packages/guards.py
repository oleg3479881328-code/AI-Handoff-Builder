from __future__ import annotations

import hashlib
import shutil
import zipfile
from pathlib import Path

from handoff_builder.utils import safe_extract_zip

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
