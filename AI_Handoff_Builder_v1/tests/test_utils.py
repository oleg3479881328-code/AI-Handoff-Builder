from pathlib import Path
import zipfile

import pytest

from handoff_builder.utils import safe_extract_zip, slugify


def test_slugify_removes_windows_invalid_chars():
    assert slugify('JEFF: BREANNA / test?') == "JEFF_BREANNA_test"


def test_safe_extract_rejects_zip_traversal(tmp_path: Path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../escape.txt", "bad")
    with pytest.raises(ValueError):
        safe_extract_zip(archive, tmp_path / "out")
