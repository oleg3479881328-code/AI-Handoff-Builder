from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


def _settings_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "AI Handoff Builder"
    return Path.home() / ".ai_handoff_builder" / "AI Handoff Builder"


def get_shotcut_settings_path() -> Path:
    return _settings_root() / "shotcut_settings.json"


@dataclass(frozen=True, slots=True)
class ShotcutAppSettings:
    runtime_dir: str = ""
    server_script: str = ""

    def runtime_path(self) -> Path | None:
        return Path(self.runtime_dir).expanduser().resolve() if self.runtime_dir else None

    def server_script_path(self) -> Path | None:
        return Path(self.server_script).expanduser().resolve() if self.server_script else None

    def with_defaults(self) -> ShotcutAppSettings:
        defaults = autodetect_shotcut_settings()
        return ShotcutAppSettings(
            runtime_dir=self.runtime_dir or defaults.runtime_dir,
            server_script=self.server_script or defaults.server_script,
        )


class ShotcutSettingsStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or get_shotcut_settings_path()

    def load(self) -> ShotcutAppSettings:
        if not self.path.exists():
            return ShotcutAppSettings().with_defaults()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return ShotcutAppSettings().with_defaults()
        return ShotcutAppSettings(
            runtime_dir=str(payload.get("runtime_dir") or ""),
            server_script=str(payload.get("server_script") or ""),
        ).with_defaults()

    def save(self, settings: ShotcutAppSettings) -> ShotcutAppSettings:
        normalized = ShotcutAppSettings(
            runtime_dir=str(settings.runtime_path()) if settings.runtime_dir else "",
            server_script=str(settings.server_script_path()) if settings.server_script else "",
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "runtime_dir": normalized.runtime_dir,
                    "server_script": normalized.server_script,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return normalized

    def reset(self) -> None:
        if self.path.exists():
            self.path.unlink()


def autodetect_shotcut_settings() -> ShotcutAppSettings:
    runtime_dir = _first_existing_dir(
        [
            Path.home() / "Documents" / "AIHB_issue25_shotcut_proof" / "runtime" / "shotcut-portable" / "Shotcut",
            Path(os.environ.get("PROGRAMFILES", "")) / "Shotcut",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Shotcut",
        ]
    )
    server_script = _first_existing_file(
        [
            Path.home()
            / "Documents"
            / "AIHB_issue25_shotcut_proof"
            / "runtime"
            / "shotcut-mcp"
            / "scripts"
            / "shotcut_mcp_server.py",
        ]
    )
    return ShotcutAppSettings(
        runtime_dir=str(runtime_dir) if runtime_dir else "",
        server_script=str(server_script) if server_script else "",
    )


def _first_existing_dir(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if not str(candidate):
            continue
        resolved = candidate.expanduser()
        if (resolved / "shotcut.exe").exists() and (resolved / "melt.exe").exists():
            return resolved.resolve()
    return None


def _first_existing_file(candidates: list[Path]) -> Path | None:
    for candidate in candidates:
        if not str(candidate):
            continue
        resolved = candidate.expanduser()
        if resolved.is_file():
            return resolved.resolve()
    return None
