from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from handoff_builder.ffmpeg_tools import run_command
from handoff_builder.utils import find_executable

from .errors import InternalRenderBoundaryError
from .render.ffmpeg_backend import FFmpegBackend


FORBIDDEN_HTML_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<script[^>]+src\s*=\s*['\"]https?://", re.IGNORECASE),
    re.compile(r"<iframe\b", re.IGNORECASE),
    re.compile(r"\bfetch\s*\(", re.IGNORECASE),
    re.compile(r"\bXMLHttpRequest\b", re.IGNORECASE),
    re.compile(r"\bEventSource\b", re.IGNORECASE),
    re.compile(r"\bWebSocket\b", re.IGNORECASE),
    re.compile(r"@import\s+url\s*\(\s*['\"]?https?://", re.IGNORECASE),
    re.compile(r"<link[^>]+href\s*=\s*['\"]https?://", re.IGNORECASE),
)


class HyperFramesLabError(InternalRenderBoundaryError):
    """Raised when the HyperFrames Lab adapter crosses its safety boundary."""


@dataclass(slots=True)
class HyperFramesCommandResult:
    success: bool
    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    metadata: dict


class HyperFramesAdapter:
    def __init__(
        self,
        *,
        trusted_prototype_root: Path,
        workspace_root: Path | None = None,
        project_root: Path | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        self.trusted_prototype_root = trusted_prototype_root.resolve()
        self.workspace_root = workspace_root.resolve() if workspace_root else None
        self.project_root = project_root.resolve() if project_root else None
        self.cancel_event = cancel_event
        self.ffmpeg_backend = FFmpegBackend(project_root=project_root)

    def default_project_dir(self) -> Path:
        return self.trusted_prototype_root

    def resolve_project_dir(self, project_dir: Path) -> Path:
        resolved = project_dir.expanduser().resolve()
        allowed_roots = [self.trusted_prototype_root]
        if self.workspace_root is not None:
            allowed_roots.append(self.workspace_root)
        if not any(_is_relative_to(resolved, root) for root in allowed_roots):
            raise HyperFramesLabError(
                f"HyperFrames project must stay inside the trusted prototype root or active workspace:\n{resolved}"
            )
        index_path = resolved / "index.html"
        if not index_path.exists():
            raise HyperFramesLabError(f"HyperFrames project is missing index.html:\n{resolved}")
        self._validate_project_html(resolved)
        return resolved

    def discover_executable(self) -> str:
        try:
            return find_executable("hyperframes", self.project_root)
        except FileNotFoundError as exc:
            raise HyperFramesLabError(
                "HyperFrames executable was not found. Install the official CLI or add it to PATH."
            ) from exc

    def doctor(self) -> HyperFramesCommandResult:
        command = [self.discover_executable(), "doctor", "--json"]
        completed = run_command(command, check=False, cancel_event=self.cancel_event)
        payload = _extract_json_payload(completed.stdout or "")
        checks = payload.get("checks", []) if isinstance(payload, dict) else []
        required_failures = [item for item in checks if item.get("name") in {"Version", "Node.js", "FFmpeg", "FFprobe", "Chrome"} and not item.get("ok")]
        return HyperFramesCommandResult(
            success=completed.returncode == 0 and not required_failures,
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            metadata={"payload": payload, "required_failures": required_failures},
        )

    def open_preview(self, project_dir: Path) -> HyperFramesCommandResult:
        safe_project = self.resolve_project_dir(project_dir)
        command = [self.discover_executable(), "preview", str(safe_project), "--background", "--no-open", "--force-new"]
        completed = run_command(command, check=False, cancel_event=self.cancel_event)
        studio_root_url = _extract_studio_url(completed.stdout or "")
        studio_url = _build_project_studio_url(studio_root_url, safe_project) if studio_root_url else None
        return HyperFramesCommandResult(
            success=completed.returncode == 0 and bool(studio_url),
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            metadata={"project_dir": str(safe_project), "studio_url": studio_url, "studio_root_url": studio_root_url},
        )

    def render(self, project_dir: Path, *, output_name: str = "hyperframes_lab_render.mp4") -> HyperFramesCommandResult:
        safe_project = self.resolve_project_dir(project_dir)
        output_path = (safe_project / "out" / output_name).resolve()
        if not _is_relative_to(output_path, safe_project):
            raise HyperFramesLabError(f"HyperFrames output path escaped the project root:\n{output_path}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        command = [self.discover_executable(), "render", str(safe_project), "-o", str(output_path)]
        completed = run_command(command, check=False, cancel_event=self.cancel_event)
        metadata = {"project_dir": str(safe_project), "output_path": str(output_path)}
        if completed.returncode == 0 and output_path.exists():
            probe = self.ffmpeg_backend.probe(output_path)
            metadata["probe"] = probe
            metadata["sha256"] = _compute_sha256(output_path)
        return HyperFramesCommandResult(
            success=completed.returncode == 0 and output_path.exists(),
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
            metadata=metadata,
        )

    def _validate_project_html(self, project_dir: Path) -> None:
        html_files = [project_dir / "index.html"]
        compositions_dir = project_dir / "compositions"
        if compositions_dir.exists():
            html_files.extend(sorted(compositions_dir.rglob("*.html")))
        for html_path in html_files:
            text = html_path.read_text(encoding="utf-8")
            for pattern in FORBIDDEN_HTML_PATTERNS:
                if pattern.search(text):
                    raise HyperFramesLabError(
                        f"HyperFrames trusted composition contains a forbidden remote/network pattern in {html_path.name}."
                    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _extract_json_payload(text: str) -> dict:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return {}
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return {}


def _extract_studio_url(text: str) -> str | None:
    match = re.search(r"https?://[^\s]+", text)
    return match.group(0) if match else None


def _build_project_studio_url(studio_url: str, project_dir: Path) -> str:
    parsed = urlsplit(studio_url)
    if not parsed.scheme or not parsed.netloc:
        return studio_url
    fragment = f"project/{quote(project_dir.name)}?v=1&t=0&tab=renders&rc=1"
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, parsed.query, fragment))


def _compute_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest().upper()
