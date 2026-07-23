from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ThemePalette:
    name: str
    mode: str
    app_bg: str
    surface: str
    surface_alt: str
    surface_elevated: str
    border: str
    text: str
    text_muted: str
    accent: str
    accent_active: str
    accent_text: str
    success: str
    warning: str
    error: str
    selection_bg: str
    selection_text: str
    disabled_bg: str
    disabled_text: str
    input_bg: str
    input_text: str
    focus: str

    def as_dict(self) -> dict[str, str]:
        return {
            "name": self.name,
            "mode": self.mode,
            "app_bg": self.app_bg,
            "surface": self.surface,
            "surface_alt": self.surface_alt,
            "surface_elevated": self.surface_elevated,
            "border": self.border,
            "text": self.text,
            "text_muted": self.text_muted,
            "accent": self.accent,
            "accent_active": self.accent_active,
            "accent_text": self.accent_text,
            "success": self.success,
            "warning": self.warning,
            "error": self.error,
            "selection_bg": self.selection_bg,
            "selection_text": self.selection_text,
            "disabled_bg": self.disabled_bg,
            "disabled_text": self.disabled_text,
            "input_bg": self.input_bg,
            "input_text": self.input_text,
            "focus": self.focus,
        }


THEMES: dict[str, ThemePalette] = {
    "dark": ThemePalette(
        name="Dark",
        mode="dark",
        app_bg="#071426",
        surface="#0D1D33",
        surface_alt="#10253F",
        surface_elevated="#132842",
        border="#23415F",
        text="#F3F7FC",
        text_muted="#9FB3C8",
        accent="#4DA3FF",
        accent_active="#78BAFF",
        accent_text="#071426",
        success="#35C78A",
        warning="#F2B84B",
        error="#FF6B78",
        selection_bg="#1A3B61",
        selection_text="#F3F7FC",
        disabled_bg="#13233A",
        disabled_text="#6C8097",
        input_bg="#0B1A2F",
        input_text="#F3F7FC",
        focus="#7DBDFF",
    ),
    "light": ThemePalette(
        name="Light",
        mode="light",
        app_bg="#EAF2FA",
        surface="#F7FBFF",
        surface_alt="#EDF5FC",
        surface_elevated="#FFFFFF",
        border="#B8CCE1",
        text="#10253F",
        text_muted="#4E6987",
        accent="#2F7DD6",
        accent_active="#195EA8",
        accent_text="#F7FBFF",
        success="#16885D",
        warning="#C98716",
        error="#C94C5C",
        selection_bg="#CFE4FA",
        selection_text="#10253F",
        disabled_bg="#DCE6F0",
        disabled_text="#70859B",
        input_bg="#FFFFFF",
        input_text="#10253F",
        focus="#2F7DD6",
    ),
}

DEFAULT_THEME = "dark"


def get_theme_palette(theme_name: str | None) -> ThemePalette:
    key = (theme_name or DEFAULT_THEME).strip().lower()
    return THEMES.get(key, THEMES[DEFAULT_THEME])


def get_settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        root = Path(local_app_data)
    else:
        root = Path.home() / ".ai_handoff_builder"
    return root / "AI Handoff Builder" / "settings.json"


class ThemeSettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_settings_path()

    def load_theme_name(self) -> str:
        if not self.path.exists():
            return DEFAULT_THEME
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return DEFAULT_THEME
        return get_theme_palette(str(payload.get("theme", DEFAULT_THEME))).mode

    def save_theme_name(self, theme_name: str) -> str:
        palette = get_theme_palette(theme_name)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"theme": palette.mode}, ensure_ascii=False, indent=2), encoding="utf-8")
        return palette.mode
