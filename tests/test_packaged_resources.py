from __future__ import annotations

from pathlib import Path


def test_pyinstaller_spec_includes_hyperframes_and_schemas() -> None:
    spec_path = Path(__file__).resolve().parents[1] / "AI Handoff Builder.spec"
    text = spec_path.read_text(encoding="utf-8")

    assert "('prototypes\\\\hyperframes', 'prototypes\\\\hyperframes')" in text
    assert "('schemas', 'schemas')" in text


def test_build_script_includes_hyperframes_and_schemas() -> None:
    build_script = Path(__file__).resolve().parents[1] / "build_exe.bat"
    text = build_script.read_text(encoding="utf-8")

    assert '--add-data "prototypes\\hyperframes;prototypes\\hyperframes"' in text
    assert '--add-data "schemas;schemas"' in text
