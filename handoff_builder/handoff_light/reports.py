from __future__ import annotations

from pathlib import Path

from handoff_builder.utils import json_dump


REPORT_FILENAMES = {
    "new_material": "NEW_MATERIAL.json",
    "duplicates": "DUPLICATES.json",
    "missing_files": "MISSING_FILES.json",
    "damaged_files": "DAMAGED_FILES.json",
    "unsupported_files": "UNSUPPORTED_FILES.json",
    "build_validation": "BUILD_VALIDATION_REPORT.json",
}


def write_report(path: Path, payload: dict[str, object]) -> None:
    json_dump(path, payload)
