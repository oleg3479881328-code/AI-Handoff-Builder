"""Tests for exact inventory verification and content hash computation."""

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from handoff_builder.v2.errors import ChecksumMismatchError, UnsafePackageError
from handoff_builder.v2.packages.guards import (
    compute_content_hash,
    verify_exact_inventory,
)


def _make_zip(tmp_path: Path, entries: dict[str, bytes]) -> Path:
    """Create a ZIP file with given entries (name -> content)."""
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in entries.items():
            zf.writestr(name, content)
    return zip_path


def _entry_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _entry_size(content: bytes) -> int:
    return len(content)


class TestVerifyExactInventory:
    def test_exact_match(self, tmp_path: Path):
        """All declared entries exist in ZIP with correct sizes and hashes."""
        entries = {
            "plans/plan.json": b'{"plan": "test"}',
            "assets/video.mp4": b"fake video content",
        }
        zip_path = _make_zip(tmp_path, entries)
        inventory = [
            {"path": "plans/plan.json", "sha256": _entry_sha256(entries["plans/plan.json"]), "size_bytes": _entry_size(entries["plans/plan.json"])},
            {"path": "assets/video.mp4", "sha256": _entry_sha256(entries["assets/video.mp4"]), "size_bytes": _entry_size(entries["assets/video.mp4"])},
        ]
        result = verify_exact_inventory(zip_path, inventory)
        assert len(result) == 2
        assert result[0][0] == "assets/video.mp4"
        assert result[1][0] == "plans/plan.json"

    def test_missing_declared_entry(self, tmp_path: Path):
        """Declared entry missing from ZIP raises error."""
        entries = {"plans/plan.json": b'{"plan": "test"}'}
        zip_path = _make_zip(tmp_path, entries)
        inventory = [
            {"path": "plans/plan.json", "sha256": _entry_sha256(entries["plans/plan.json"]), "size_bytes": _entry_size(entries["plans/plan.json"])},
            {"path": "assets/missing.mp4", "sha256": "abc", "size_bytes": 100},
        ]
        with pytest.raises(UnsafePackageError, match="missing from ZIP"):
            verify_exact_inventory(zip_path, inventory)

    def test_undeclared_entry(self, tmp_path: Path):
        """Undeclared entry in ZIP raises error."""
        entries = {
            "plans/plan.json": b'{"plan": "test"}',
            "assets/extra.mp4": b"extra content",
        }
        zip_path = _make_zip(tmp_path, entries)
        inventory = [
            {"path": "plans/plan.json", "sha256": _entry_sha256(entries["plans/plan.json"]), "size_bytes": _entry_size(entries["plans/plan.json"])},
        ]
        with pytest.raises(UnsafePackageError, match="undeclared"):
            verify_exact_inventory(zip_path, inventory)

    def test_checksum_mismatch(self, tmp_path: Path):
        """Wrong sha256 in inventory raises ChecksumMismatchError."""
        entries = {"plans/plan.json": b'{"plan": "test"}'}
        zip_path = _make_zip(tmp_path, entries)
        inventory = [
            {"path": "plans/plan.json", "sha256": "0000000000000000000000000000000000000000000000000000000000000000", "size_bytes": _entry_size(entries["plans/plan.json"])},
        ]
        with pytest.raises(ChecksumMismatchError, match="checksum mismatch"):
            verify_exact_inventory(zip_path, inventory)

    def test_size_mismatch(self, tmp_path: Path):
        """Wrong size_bytes in inventory raises error."""
        entries = {"plans/plan.json": b'{"plan": "test"}'}
        zip_path = _make_zip(tmp_path, entries)
        inventory = [
            {"path": "plans/plan.json", "sha256": _entry_sha256(entries["plans/plan.json"]), "size_bytes": 999},
        ]
        with pytest.raises(UnsafePackageError, match="size mismatch"):
            verify_exact_inventory(zip_path, inventory)

    def test_path_traversal_rejected(self, tmp_path: Path):
        """Path traversal in inventory entry is rejected."""
        entries = {"safe.txt": b"content"}
        zip_path = _make_zip(tmp_path, entries)
        inventory = [
            {"path": "../escape.txt", "sha256": "abc", "size_bytes": 10},
        ]
        with pytest.raises(UnsafePackageError, match="Path traversal"):
            verify_exact_inventory(zip_path, inventory)

    def test_absolute_path_rejected(self, tmp_path: Path):
        """Absolute path in inventory entry is rejected."""
        entries = {"safe.txt": b"content"}
        zip_path = _make_zip(tmp_path, entries)
        inventory = [
            {"path": "/etc/passwd", "sha256": "abc", "size_bytes": 10},
        ]
        with pytest.raises(UnsafePackageError, match="absolute path"):
            verify_exact_inventory(zip_path, inventory)

    def test_duplicate_inventory_entry(self, tmp_path: Path):
        """Duplicate path in inventory is rejected."""
        entries = {"plans/plan.json": b'{"plan": "test"}'}
        zip_path = _make_zip(tmp_path, entries)
        inventory = [
            {"path": "plans/plan.json", "sha256": _entry_sha256(entries["plans/plan.json"]), "size_bytes": _entry_size(entries["plans/plan.json"])},
            {"path": "plans/plan.json", "sha256": _entry_sha256(entries["plans/plan.json"]), "size_bytes": _entry_size(entries["plans/plan.json"])},
        ]
        with pytest.raises(UnsafePackageError, match="Duplicate"):
            verify_exact_inventory(zip_path, inventory)


class TestComputeContentHash:
    def test_deterministic(self):
        """Same content produces same hash regardless of key order."""
        a = {"b": 2, "a": 1}
        b = {"a": 1, "b": 2}
        assert compute_content_hash(a) == compute_content_hash(b)

    def test_different_content_different_hash(self):
        """Different content produces different hash."""
        a = {"version": "1.0", "name": "test"}
        b = {"version": "1.0", "name": "other"}
        assert compute_content_hash(a) != compute_content_hash(b)

    def test_nested_objects(self):
        """Nested objects are canonicalized correctly."""
        a = {"outer": {"z": 3, "a": 1}}
        b = {"outer": {"a": 1, "z": 3}}
        assert compute_content_hash(a) == compute_content_hash(b)

    def test_array_order_preserved(self):
        """Array order is preserved (not sorted)."""
        a = {"items": [3, 1, 2]}
        b = {"items": [1, 2, 3]}
        assert compute_content_hash(a) != compute_content_hash(b)

    def test_output_format(self):
        """Hash is a 64-character hex string."""
        result = compute_content_hash({"test": "data"})
        assert isinstance(result, str)
        assert len(result) == 64
        int(result, 16)  # should not raise
