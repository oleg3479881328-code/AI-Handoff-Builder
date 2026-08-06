from __future__ import annotations

import shutil
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from handoff_builder.utils import _validated_archive_member_path, media_type_for

from .models import DiscoveredFile, IngestLimits


EXECUTABLE_EXTENSIONS = {
    ".exe", ".dll", ".bat", ".cmd", ".com", ".ps1", ".msi", ".scr", ".vbs", ".js"
}
SUPPORTED_SIDECAR_EXTENSIONS = {".srt", ".vtt", ".xmp", ".json", ".txt"}
ZIP_EXTENSIONS = {".zip"}


@dataclass(slots=True)
class DiscoveryResult:
    discovered_files: list[DiscoveredFile] = field(default_factory=list)
    damaged_files: list[dict[str, object]] = field(default_factory=list)
    unsupported_files: list[dict[str, object]] = field(default_factory=list)
    blocked_archives: list[dict[str, object]] = field(default_factory=list)
    expanded_bytes: int = 0
    temp_root: Path | None = None


class SafeInputDiscoverer:
    def __init__(self, limits: IngestLimits) -> None:
        self.limits = limits

    def discover(self, selections: list[Path]) -> DiscoveryResult:
        result = DiscoveryResult()
        temp_root = Path(tempfile.mkdtemp(prefix="handoff-light-"))
        result.temp_root = temp_root
        for selection in selections:
            resolved = selection.resolve()
            self._walk_path(resolved, resolved, [selection.name], 0, temp_root, result)
        return result

    def _walk_path(
        self,
        path: Path,
        stable_source_path: Path,
        source_chain: list[str],
        archive_depth: int,
        temp_root: Path,
        result: DiscoveryResult,
    ) -> None:
        if len(result.discovered_files) >= self.limits.max_discovered_files:
            raise ValueError("Maximum discovered file count exceeded.")
        if path.is_dir():
            for child in sorted(path.iterdir(), key=lambda item: item.name.lower()):
                self._walk_path(child, child, source_chain + [child.name], archive_depth, temp_root, result)
            return
        if not path.exists():
            result.damaged_files.append({
                "path": str(path),
                "source_chain": source_chain,
                "reason": "missing_input",
            })
            return
        if path.suffix.lower() in ZIP_EXTENSIONS:
            self._walk_zip(path, stable_source_path, source_chain, archive_depth, temp_root, result)
            return
        suffix = path.suffix.lower()
        if suffix in EXECUTABLE_EXTENSIONS:
            result.unsupported_files.append({
                "path": str(path),
                "source_chain": source_chain,
                "reason": "executable_payload_rejected",
            })
            return
        if media_type_for(path) is None and suffix not in SUPPORTED_SIDECAR_EXTENSIONS:
            result.unsupported_files.append({
                "path": str(path),
                "source_chain": source_chain,
                "reason": "unsupported_extension",
            })
            return
        result.discovered_files.append(
            DiscoveredFile(
                path=path,
                stable_source_path=stable_source_path,
                source_chain=source_chain,
                archive_depth=archive_depth,
                extracted_from_archive=archive_depth > 0,
            )
        )

    def _walk_zip(
        self,
        zip_path: Path,
        stable_source_path: Path,
        source_chain: list[str],
        archive_depth: int,
        temp_root: Path,
        result: DiscoveryResult,
    ) -> None:
        if archive_depth >= self.limits.max_archive_depth:
            result.blocked_archives.append({
                "path": str(zip_path),
                "source_chain": source_chain,
                "reason": "archive_depth_limit",
            })
            return
        try:
            with zipfile.ZipFile(zip_path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    if info.flag_bits & 0x1:
                        result.blocked_archives.append({
                            "path": str(zip_path),
                            "source_chain": source_chain + [info.filename],
                            "reason": "encrypted_archive_member",
                        })
                        continue
                    if info.file_size < 0:
                        result.blocked_archives.append({
                            "path": str(zip_path),
                            "source_chain": source_chain + [info.filename],
                            "reason": "invalid_archive_member_size",
                        })
                        continue
                    ratio = info.file_size / max(info.compress_size, 1)
                    if ratio > self.limits.max_compression_ratio:
                        result.blocked_archives.append({
                            "path": str(zip_path),
                            "source_chain": source_chain + info.filename.replace("\\", "/").split("/"),
                            "reason": "compression_ratio_limit",
                        })
                        continue
                    result.expanded_bytes += int(info.file_size)
                    if result.expanded_bytes > self.limits.max_expanded_bytes:
                        raise ValueError("Maximum expanded bytes exceeded.")
                    extraction_root = temp_root / f"archive_{len(result.discovered_files)}_{archive_depth}"
                    extraction_root.mkdir(parents=True, exist_ok=True)
                    target = _validated_archive_member_path(info, extraction_root)
                    if target is None:
                        continue
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as src, target.open("wb") as dst:
                        shutil.copyfileobj(src, dst)
                    member_chain = source_chain + list(target.relative_to(extraction_root).parts)
                    self._walk_path(target, stable_source_path, list(member_chain), archive_depth + 1, temp_root, result)
        except (OSError, ValueError, zipfile.BadZipFile, RuntimeError) as exc:
            result.damaged_files.append({
                "path": str(zip_path),
                "source_chain": source_chain,
                "reason": "zip_read_failed",
                "error": str(exc),
            })
