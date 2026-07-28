from __future__ import annotations

from typing import Any

from .ffmpeg_backend import FFmpegBackend
from .shotcut_backend import ShotcutMcpBackend, select_render_backend

__all__ = ["FFmpegBackend", "ShotcutMcpBackend", "select_render_backend", "resolve_backend_name"]


def resolve_backend_name(name: str) -> str:
    normalized = name.strip().lower()
    if normalized == "ffmpeg":
        return "ffmpeg"
    if normalized in {"shotcut", "shotcut-mcp"}:
        return "shotcut-mcp"
    raise ValueError(f"Unsupported render backend: {name}")
