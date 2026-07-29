from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import InternalRenderBoundaryError


_FINALIZING_STATUS_NOTE = "The render supervisor exited before finalizing the job."


class ShotcutBackendError(InternalRenderBoundaryError):
    """Raised when the isolated Shotcut MCP boundary cannot be used safely."""


@dataclass(frozen=True, slots=True)
class ShotcutProfile:
    width: int
    height: int
    fps_num: int = 30
    fps_den: int = 1

    def to_create_project_args(self) -> dict[str, int]:
        if self.width < 16 or self.height < 16:
            raise ShotcutBackendError("Shotcut profile dimensions must be >= 16.")
        if self.fps_num < 1 or self.fps_den < 1:
            raise ShotcutBackendError("Shotcut profile timebase must be positive.")
        return {
            "width": self.width,
            "height": self.height,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
        }


@dataclass(frozen=True, slots=True)
class ShotcutClipIntent:
    media_path: Path
    track: str = "V1"
    position_frame: int | None = None
    in_frame: int | None = None
    out_frame: int | None = None
    caption: str | None = None

    def to_clip_args(self) -> dict[str, Any]:
        if self.position_frame is not None and self.position_frame < 0:
            raise ShotcutBackendError("position_frame must be >= 0.")
        if self.in_frame is not None and self.in_frame < 0:
            raise ShotcutBackendError("in_frame must be >= 0.")
        if self.out_frame is not None and self.out_frame < 0:
            raise ShotcutBackendError("out_frame must be >= 0.")
        if self.in_frame is not None and self.out_frame is not None and self.out_frame < self.in_frame:
            raise ShotcutBackendError("out_frame must be >= in_frame.")
        payload: dict[str, Any] = {
            "track": self.track,
            "path": str(self.media_path),
        }
        if self.position_frame is not None:
            payload["position_frame"] = self.position_frame
        if self.in_frame is not None:
            payload["in_frame"] = self.in_frame
        if self.out_frame is not None:
            payload["out_frame"] = self.out_frame
        if self.caption:
            payload["caption"] = self.caption
        return payload


@dataclass(frozen=True, slots=True)
class ShotcutTrackIntent:
    kind: str
    name: str | None = None

    def to_track_args(self) -> dict[str, str]:
        if self.kind not in {"video", "audio"}:
            raise ShotcutBackendError("Shotcut track kind must be 'video' or 'audio'.")
        payload = {"kind": self.kind}
        if self.name:
            payload["name"] = self.name
        return payload


@dataclass(frozen=True, slots=True)
class ShotcutRenderJob:
    job_id: str
    output_path: Path
    raw: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ShotcutBackendPaths:
    server_script: Path
    allowed_roots: tuple[Path, ...]
    shotcut_path: Path | None = None
    melt_path: Path | None = None
    ffmpeg_path: Path | None = None
    ffprobe_path: Path | None = None
    python_executable: str = sys.executable


def redact_private_paths(value: Any, allowed_roots: tuple[Path, ...]) -> Any:
    if isinstance(value, dict):
        return {key: redact_private_paths(item, allowed_roots) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_private_paths(item, allowed_roots) for item in value]
    if isinstance(value, str):
        return _redact_string(value, allowed_roots)
    return value


def select_render_backend(
    name: str,
    *,
    shotcut_backend: ShotcutMcpBackend | None = None,
    ffmpeg_backend: Any | None = None,
) -> Any:
    normalized = name.strip().lower()
    if normalized == "ffmpeg":
        if ffmpeg_backend is None:
            raise ShotcutBackendError("FFmpeg backend instance was not provided.")
        return ffmpeg_backend
    if normalized in {"shotcut", "shotcut-mcp"}:
        if shotcut_backend is None:
            raise ShotcutBackendError("Shotcut backend instance was not provided.")
        return shotcut_backend
    raise ShotcutBackendError(f"Unsupported render backend: {name}")


class ShotcutMcpBackend:
    def __init__(
        self,
        paths: ShotcutBackendPaths,
        *,
        timeout_seconds: int = 240,
        allow_network_resources: bool = False,
        allow_unsafe_consumer_properties: bool = False,
        require_absolute_paths: bool = True,
        extra_env: dict[str, str] | None = None,
    ) -> None:
        self.paths = paths
        self.timeout_seconds = timeout_seconds
        self.extra_env = dict(extra_env or {})
        if allow_network_resources:
            raise ShotcutBackendError("Network resources must stay disabled for Shotcut MCP.")
        if allow_unsafe_consumer_properties:
            raise ShotcutBackendError("Unsafe consumer properties must stay disabled for Shotcut MCP.")
        if not require_absolute_paths:
            raise ShotcutBackendError("Absolute paths must stay required for Shotcut MCP.")
        self._validate_paths()

    def status(self) -> dict[str, Any]:
        return self._invoke_tool("shotcut_status", {})

    def doctor(self) -> dict[str, Any]:
        return self._invoke_tool("shotcut_doctor", {})

    def capabilities(self) -> dict[str, Any]:
        status = self.status()
        doctor = self.doctor()
        return {
            "backend": "shotcut-mcp",
            "mode": "real" if status.get("ready") and doctor.get("compatible") else "degraded",
            "status": status,
            "doctor": doctor,
            "supported_operations": [
                "probe_media",
                "create_project",
                "inspect_project",
                "plan_project_edit",
                "edit_project",
                "validate_project",
                "render_preview",
                "render_contact_sheet",
                "open_in_shotcut",
                "start_render",
                "render_status",
            ],
        }

    def probe_media(self, media_path: Path) -> dict[str, Any]:
        return self._invoke_tool("probe_media", {"path": str(self._authorize_path(media_path))})

    def create_disposable_project(
        self,
        project_path: Path,
        *,
        profile: ShotcutProfile,
        clips: list[ShotcutClipIntent],
        tracks: list[ShotcutTrackIntent] | None = None,
        overwrite: bool = True,
    ) -> dict[str, Any]:
        if not clips:
            raise ShotcutBackendError("At least one linked clip is required.")
        payload = {
            "project_path": str(self._authorize_path(project_path, must_exist=False)),
            "overwrite": overwrite,
            "clips": [clip.to_clip_args() for clip in clips],
            **profile.to_create_project_args(),
        }
        if tracks:
            payload["tracks"] = [track.to_track_args() for track in tracks]
        return self._invoke_tool("create_project", payload)

    def inspect_project(self, project_path: Path) -> dict[str, Any]:
        return self._invoke_tool("inspect_project", {"path": str(self._authorize_path(project_path))})

    def append_linked_clip(
        self,
        project_path: Path,
        *,
        expected_revision: str,
        clip: ShotcutClipIntent,
    ) -> dict[str, Any]:
        return self.edit_operations(
            project_path,
            expected_revision=expected_revision,
            operations=[{"op": "add_clip", **clip.to_clip_args()}],
        )

    def trim_linked_clip(
        self,
        project_path: Path,
        *,
        expected_revision: str,
        item_ref: str,
        in_frame: int | None = None,
        out_frame: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"op": "trim_item", "item_ref": item_ref}
        if in_frame is not None:
            payload["in_frame"] = in_frame
        if out_frame is not None:
            payload["out_frame"] = out_frame
        if in_frame is None and out_frame is None:
            raise ShotcutBackendError("trim_linked_clip requires in_frame, out_frame, or both.")
        return self.edit_operations(
            project_path,
            expected_revision=expected_revision,
            operations=[payload],
        )

    def plan_operations(
        self,
        project_path: Path,
        *,
        expected_revision: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._invoke_tool(
            "plan_project_edit",
            {
                "project_path": str(self._authorize_path(project_path)),
                "expected_revision": expected_revision,
                "operations": operations,
            },
        )

    def edit_operations(
        self,
        project_path: Path,
        *,
        expected_revision: str,
        operations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return self._invoke_tool(
            "edit_project",
            {
                "project_path": str(self._authorize_path(project_path)),
                "expected_revision": expected_revision,
                "operations": operations,
            },
        )

    def validate_project(self, project_path: Path) -> dict[str, Any]:
        return self._invoke_tool("validate_project", {"path": str(self._authorize_path(project_path))})

    def render_preview(self, project_path: Path, output_path: Path, *, frame: int = 0, overwrite: bool = False) -> dict[str, Any]:
        return self._invoke_tool(
            "render_preview",
            {
                "project_path": str(self._authorize_path(project_path)),
                "output_path": str(self._authorize_path(output_path, must_exist=False)),
                "frame": frame,
                "overwrite": overwrite,
            },
        )

    def render_contact_sheet(
        self,
        project_path: Path,
        output_path: Path,
        *,
        sample_count: int = 12,
        columns: int = 4,
        cell_width: int = 320,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        return self._invoke_tool(
            "render_contact_sheet",
            {
                "project_path": str(self._authorize_path(project_path)),
                "output_path": str(self._authorize_path(output_path, must_exist=False)),
                "sample_count": sample_count,
                "columns": columns,
                "cell_width": cell_width,
                "overwrite": overwrite,
            },
        )

    def open_in_shotcut(self, project_path: Path) -> dict[str, Any]:
        return self._invoke_tool("open_in_shotcut", {"path": str(self._authorize_path(project_path))})

    def start_render(
        self,
        project_path: Path,
        output_path: Path,
        *,
        preset: str = "h264-web",
        marker_id: str | None = None,
        in_frame: int | None = None,
        out_frame: int | None = None,
        overwrite: bool = False,
    ) -> ShotcutRenderJob:
        payload: dict[str, Any] = {
            "project_path": str(self._authorize_path(project_path)),
            "output_path": str(self._authorize_path(output_path, must_exist=False)),
            "preset": preset,
            "overwrite": overwrite,
        }
        if marker_id is not None:
            payload["marker_id"] = marker_id
        if in_frame is not None:
            payload["in_frame"] = in_frame
        if out_frame is not None:
            payload["out_frame"] = out_frame
        result = self._invoke_tool("start_render", payload)
        return ShotcutRenderJob(
            job_id=str(result["job_id"]),
            output_path=Path(result["output_path"]),
            raw=result,
        )

    def cancel_render(self, job_id: str) -> dict[str, Any]:
        return self._invoke_tool("cancel_render", {"job_id": job_id})

    def render_status(self, job_id: str) -> dict[str, Any]:
        result = self._invoke_tool("render_status", {"job_id": job_id})
        return self._stabilize_render_status(result)

    def await_render(self, job_id: str, *, timeout_seconds: int = 300, poll_interval_seconds: float = 1.0) -> dict[str, Any]:
        deadline = time.time() + timeout_seconds
        latest: dict[str, Any] | None = None
        while time.time() < deadline:
            latest = self.render_status(job_id)
            if latest.get("status") != "running":
                return latest
            time.sleep(poll_interval_seconds)
        raise ShotcutBackendError(f"Render job {job_id} did not reach a terminal state in time.")

    def verify_rendered_media(self, media_path: Path) -> dict[str, Any]:
        return self.probe_media(media_path)

    def _validate_paths(self) -> None:
        server_script = self.paths.server_script.resolve()
        if not server_script.is_file():
            raise ShotcutBackendError(f"Shotcut MCP server script was not found: {server_script}")
        if not self.paths.allowed_roots:
            raise ShotcutBackendError("At least one allowed root is required for Shotcut MCP.")
        for root in self.paths.allowed_roots:
            if not root.is_absolute():
                raise ShotcutBackendError("Shotcut allowed roots must be absolute paths.")

    def _authorize_path(self, path: Path, *, must_exist: bool = True) -> Path:
        resolved = path.resolve(strict=must_exist)
        for root in self.paths.allowed_roots:
            root_resolved = root.resolve()
            if resolved == root_resolved or root_resolved in resolved.parents:
                return resolved
        raise ShotcutBackendError(f"Shotcut path escaped the allowed roots: {path}")

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        donor_root = self.paths.server_script.resolve().parents[1]
        env["SHOTCUT_MCP_SERVER_SCRIPT"] = str(self.paths.server_script.resolve())
        env["SHOTCUT_MCP_ALLOWED_ROOTS"] = ";".join(
            str(root.resolve()) for root in self.paths.allowed_roots
        )
        env["SHOTCUT_MCP_REQUIRE_ABSOLUTE_PATHS"] = "1"
        env["SHOTCUT_MCP_ALLOW_NETWORK_RESOURCES"] = "0"
        env["SHOTCUT_MCP_ALLOW_UNSAFE_CONSUMER_PROPERTIES"] = "0"
        if self.paths.shotcut_path:
            env["SHOTCUT_PATH"] = str(self.paths.shotcut_path.resolve())
        if self.paths.melt_path:
            env["SHOTCUT_MELT_PATH"] = str(self.paths.melt_path.resolve())
        if self.paths.ffmpeg_path:
            env["SHOTCUT_FFMPEG_PATH"] = str(self.paths.ffmpeg_path.resolve())
        if self.paths.ffprobe_path:
            env["SHOTCUT_FFPROBE_PATH"] = str(self.paths.ffprobe_path.resolve())
        existing_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            str(donor_root)
            if not existing_pythonpath
            else str(donor_root) + os.pathsep + existing_pythonpath
        )
        env.update(self.extra_env)
        if env.get("SHOTCUT_MCP_ALLOW_NETWORK_RESOURCES") != "0":
            raise ShotcutBackendError("Shotcut MCP network resources must remain disabled.")
        if env.get("SHOTCUT_MCP_ALLOW_UNSAFE_CONSUMER_PROPERTIES") != "0":
            raise ShotcutBackendError("Shotcut MCP unsafe consumer properties must remain disabled.")
        if env.get("SHOTCUT_MCP_REQUIRE_ABSOLUTE_PATHS") != "1":
            raise ShotcutBackendError("Shotcut MCP absolute path policy must remain enabled.")
        return env

    def _invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        payloads = [
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "ai-handoff-builder", "version": "1.0"},
                },
            },
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            },
        ]
        blob = "".join(
            json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
            for item in payloads
        )
        try:
            completed = subprocess.run(
                [self.paths.python_executable, str(self.paths.server_script.resolve())],
                input=blob,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=self._build_env(),
                timeout=self.timeout_seconds,
            )
        except OSError as exc:
            raise ShotcutBackendError(f"Shotcut MCP process failed to start: {exc}") from exc
        if completed.returncode != 0:
            raise ShotcutBackendError(
                "Shotcut MCP process returned a non-zero exit code.\n"
                + completed.stderr[-4000:]
            )
        messages: list[dict[str, Any]] = []
        for line in completed.stdout.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            try:
                messages.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ShotcutBackendError(f"Shotcut MCP returned malformed JSON: {exc}") from exc
        response = next((item for item in messages if item.get("id") == 2), None)
        if response is None:
            raise ShotcutBackendError("Shotcut MCP returned no tool response.")
        if "error" in response:
            raise ShotcutBackendError(json.dumps(response["error"], ensure_ascii=False, indent=2))
        result = response.get("result")
        if not isinstance(result, dict):
            raise ShotcutBackendError("Shotcut MCP returned no structured result.")
        if result.get("isError"):
            raise ShotcutBackendError(json.dumps(result, ensure_ascii=False, indent=2))
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise ShotcutBackendError("Shotcut MCP result is missing structuredContent.")
        return structured

    def _stabilize_render_status(self, result: dict[str, Any]) -> dict[str, Any]:
        if result.get("status") != "failed" or result.get("status_note") != _FINALIZING_STATUS_NOTE:
            return result
        log_path = result.get("log_path")
        output_path = result.get("output_path")
        if not isinstance(log_path, str) or not isinstance(output_path, str):
            return result
        metadata_path = Path(log_path).with_suffix(".json")
        output = Path(output_path)
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                metadata = None
            if isinstance(metadata, dict) and metadata.get("status") == "completed" and output.is_file():
                return metadata
        time.sleep(2.0)
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                metadata = None
            if isinstance(metadata, dict) and metadata.get("status") in {"completed", "promotion_failed"}:
                return metadata
        return result


def _redact_string(value: str, allowed_roots: tuple[Path, ...]) -> str:
    for index, root in enumerate(allowed_roots, start=1):
        root_text = str(root.resolve())
        normalized_root = root_text.replace("/", "\\").rstrip("\\")
        normalized_value = value.replace("/", "\\")
        if normalized_value == normalized_root:
            return f"<allowed-root-{index}>"
        if normalized_value.startswith(normalized_root + "\\"):
            suffix = normalized_value[len(normalized_root) + 1 :].replace("\\", "/")
            return f"<allowed-root-{index}>/{suffix}"
    return value
