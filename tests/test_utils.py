from pathlib import Path
import zipfile

import pytest

from handoff_builder.utils import extract_supported_media_from_zip, safe_extract_zip, slugify


def test_slugify_removes_windows_invalid_chars():
    assert slugify('JEFF: BREANNA / test?') == "JEFF_BREANNA_test"


def test_safe_extract_rejects_zip_traversal(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError):
        safe_extract_zip(archive, tmp_path / "out")


def test_safe_extract_rejects_drive_letter_member(tmp_path: Path):
    archive = tmp_path / "drive.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("C:/evil.txt", "bad")
    with pytest.raises(ValueError):
        safe_extract_zip(archive, tmp_path / "out")


def test_extract_supported_media_ignores_non_media_files(tmp_path: Path):
    archive = tmp_path / "mixed.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("nested/video.mp4", "video")
        zf.writestr("nested/readme.txt", "notes")

    result = extract_supported_media_from_zip(archive, tmp_path / "out")

    assert [path.relative_to(tmp_path / "out").as_posix() for path in result.extracted_files] == ["nested/video.mp4"]
    assert result.ignored_members == ["nested/readme.txt"]
