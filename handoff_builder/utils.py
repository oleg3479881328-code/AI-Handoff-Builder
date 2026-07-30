from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


PHOTO_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif"
}
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm", ".mts", ".m2ts", ".3gp"
}
AUDIO_EXTENSIONS = {
    ".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"
}
SUPPORTED_MEDIA_EXTENSIONS = PHOTO_EXTENSIONS | VIDEO_EXTENSIONS | AUDIO_EXTENSIONS


@dataclass(frozen=True, slots=True)
class ExtractedZipMedia:
    extracted_files: list[Path]
    ignored_members: list[str]


def slugify(value: str, fallback: str = "project") -> str:
    value = value.strip()
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value)
    value = re.sub(r"\s+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._ ")
    return value or fallback


def stable_asset_id(path: Path, root: Path | None = None) -> str:
    try:
        rel = path.resolve().relative_to(root.resolve()) if root else path.name
    except (ValueError, OSError):
        rel = path.name
    stat = path.stat()
    content_hash = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            content_hash.update(chunk)
    payload = f"{rel}|{stat.st_size}|{content_hash.hexdigest()}".encode("utf-8", "surrogatepass")
    return hashlib.sha1(payload).hexdigest()[:12]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_dump(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def safe_extract_zip(zip_path: Path, destination: Path) -> list[Path]:
    destination = destination.resolve()
    extracted: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            target = _validated_archive_member_path(info, destination)
            if target is None:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target)
    return extracted


def extract_supported_media_from_zip(zip_path: Path, destination: Path) -> ExtractedZipMedia:
    destination = destination.resolve()
    extracted: list[Path] = []
    ignored_members: list[str] = []
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir():
                continue
            if _zip_member_is_link_like(info):
                raise ValueError(f"Unsafe ZIP member type: {info.filename}")
            target = _validated_archive_member_path(info, destination)
            if target is None:
                continue
            if target.suffix.lower() not in SUPPORTED_MEDIA_EXTENSIONS:
                ignored_members.append(info.filename)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            extracted.append(target)
    return ExtractedZipMedia(extracted_files=extracted, ignored_members=ignored_members)


def _validated_archive_member_path(info: zipfile.ZipInfo, destination: Path) -> Path | None:
    member = Path(info.filename.replace("\\", "/"))
    if member.is_absolute():
        raise ValueError(f"Unsafe ZIP member: {info.filename}")
    normalized_parts: list[str] = []
    for part in member.parts:
        if part in {"", "."}:
            continue
        if part == ".." or re.match(r"^[A-Za-z]:$", part) or part.startswith("\\\\"):
            raise ValueError(f"Unsafe ZIP member: {info.filename}")
        normalized_parts.append(part)
    if not normalized_parts:
        return None
    target = (destination / Path(*normalized_parts)).resolve()
    if destination not in target.parents and target != destination:
        raise ValueError(f"ZIP path escapes destination: {info.filename}")
    return target


def _zip_member_is_link_like(info: zipfile.ZipInfo) -> bool:
    mode = (info.external_attr >> 16) & 0o170000
    return mode in {stat.S_IFLNK, stat.S_IFCHR, stat.S_IFBLK, stat.S_IFIFO, stat.S_IFSOCK}


def media_type_for(path: Path) -> str | None:
    ext = path.suffix.lower()
    if ext in PHOTO_EXTENSIONS:
        return "photo"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    if ext in AUDIO_EXTENSIONS:
        return "audio"
    return None


def iter_media(paths: Iterable[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[Path] = set()
    for source in paths:
        source = source.resolve()
        candidates = source.rglob("*") if source.is_dir() else [source]
        for candidate in candidates:
            if not candidate.is_file() or media_type_for(candidate) is None:
                continue
            resolved = candidate.resolve()
            if resolved not in seen:
                seen.add(resolved)
                result.append(resolved)
    return sorted(result, key=lambda p: str(p).lower())


def relative_posix(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def human_bytes(value: int) -> str:
    number = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if number < 1024 or unit == "TB":
            return f"{number:.1f} {unit}"
        number /= 1024
    return f"{value} B"


def find_executable(name: str, project_root: Path | None = None) -> str:
    exe_name = f"{name}.exe" if os.name == "nt" else name
    candidates: list[Path] = []
    if project_root:
        candidates.extend([
            project_root / "bin" / exe_name,
            project_root / exe_name,
        ])
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    found = shutil.which(name) or shutil.which(exe_name)
    if not found:
        raise FileNotFoundError(
            f"{name} was not found. Put {exe_name} in the app's bin folder "
            f"or install FFmpeg and add it to PATH."
        )
    return found
