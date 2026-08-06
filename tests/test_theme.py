from __future__ import annotations

import json
from pathlib import Path

from handoff_builder.theme import DEFAULT_THEME, THEMES, ThemeSettingsStore, get_theme_palette


def test_theme_settings_store_persists_choice(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    store = ThemeSettingsStore(settings_path)

    assert store.load_theme_name() == DEFAULT_THEME

    saved = store.save_theme_name("light")

    assert saved == "light"
    assert store.load_theme_name() == "light"
    assert json.loads(settings_path.read_text(encoding="utf-8")) == {"theme": "light"}


def test_theme_settings_store_falls_back_for_invalid_payload(tmp_path: Path):
    settings_path = tmp_path / "settings.json"
    settings_path.write_text("{not-json", encoding="utf-8")

    store = ThemeSettingsStore(settings_path)

    assert store.load_theme_name() == DEFAULT_THEME


def test_theme_palettes_expose_required_semantic_tokens():
    required_keys = {
        "app_bg",
        "surface",
        "surface_alt",
        "surface_elevated",
        "border",
        "text",
        "text_muted",
        "accent",
        "accent_active",
        "accent_text",
        "success",
        "warning",
        "error",
        "selection_bg",
        "selection_text",
        "disabled_bg",
        "disabled_text",
        "input_bg",
        "input_text",
        "focus",
    }

    for theme_name in THEMES:
        palette = get_theme_palette(theme_name)
        tokens = palette.as_dict()
        assert required_keys <= tokens.keys()
        assert all(tokens[key].startswith("#") for key in required_keys)
