from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from handoff_builder.v2.render.shotcut_backend import (
    ShotcutBackendError,
    ShotcutBackendPaths,
    ShotcutClipIntent,
    ShotcutMcpBackend,
    ShotcutProfile,
    redact_private_paths,
    select_render_backend,
)


def _server_script(tmp_path: Path) -> Path:
    donor_root = tmp_path / "vendor" / "shotcut-mcp"
    script = donor_root / "scripts" / "shotcut_mcp_server.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("print('stub')\n", encoding="utf-8")
    return script


def _backend(tmp_path: Path, **kwargs) -> ShotcutMcpBackend:
    allowed_root = tmp_path / "workspace"
    allowed_root.mkdir(parents=True, exist_ok=True)
    return ShotcutMcpBackend(
        ShotcutBackendPaths(
            server_script=_server_script(tmp_path),
            allowed_roots=(allowed_root,),
        ),
        **kwargs,
    )


def _completed_process(*messages: dict, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    stdout = "\n".join(json.dumps(message, ensure_ascii=False) for message in messages) + "\n"
    return subprocess.CompletedProcess(args=["python"], returncode=returncode, stdout=stdout, stderr="")


def test_backend_rejects_relative_allowed_root(tmp_path: Path) -> None:
    script = _server_script(tmp_path)
    with pytest.raises(ShotcutBackendError, match="absolute paths"):
        ShotcutMcpBackend(
            ShotcutBackendPaths(
                server_script=script,
                allowed_roots=(Path("relative-root"),),
            )
        )


def test_backend_rejects_network_and_unsafe_flags(tmp_path: Path) -> None:
    with pytest.raises(ShotcutBackendError, match="Network resources"):
        _backend(tmp_path, allow_network_resources=True)
    with pytest.raises(ShotcutBackendError, match="Unsafe consumer properties"):
        _backend(tmp_path, allow_unsafe_consumer_properties=True)


def test_status_invokes_server_with_safe_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return _completed_process(
            {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "shotcut-mcp"}}},
            {"jsonrpc": "2.0", "id": 2, "result": {"isError": False, "structuredContent": {"ready": True}}},
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = backend.status()

    assert result["ready"] is True
    env = captured["kwargs"]["env"]
    assert env["SHOTCUT_MCP_REQUIRE_ABSOLUTE_PATHS"] == "1"
    assert env["SHOTCUT_MCP_ALLOW_NETWORK_RESOURCES"] == "0"
    assert env["SHOTCUT_MCP_ALLOW_UNSAFE_CONSUMER_PROPERTIES"] == "0"
    assert "PYTHONPATH" in env
    assert str(backend.paths.allowed_roots[0].resolve()) in env["SHOTCUT_MCP_ALLOWED_ROOTS"]


def test_backend_rejects_malformed_json_response(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=["python"], returncode=0, stdout="{bad json}\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ShotcutBackendError, match="malformed JSON"):
        backend.status()


def test_backend_rejects_jsonrpc_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)

    def fake_run(*args, **kwargs):
        return _completed_process(
            {"jsonrpc": "2.0", "id": 2, "error": {"code": -32602, "message": "bad args"}}
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ShotcutBackendError, match="bad args"):
        backend.status()


def test_backend_rejects_tool_iserror_true(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)

    def fake_run(*args, **kwargs):
        return _completed_process(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "result": {
                    "isError": True,
                    "structuredContent": {"error_code": "invalid"},
                },
            }
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ShotcutBackendError, match="invalid"):
        backend.status()


def test_backend_rejects_process_start_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)

    def fake_run(*args, **kwargs):
        raise OSError("spawn failed")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(ShotcutBackendError, match="failed to start"):
        backend.status()


def test_redact_private_paths_recurses(tmp_path: Path) -> None:
    root = (tmp_path / "workspace").resolve()
    root.mkdir()
    payload = {
        "path": str(root / "renders" / "proof.mp4"),
        "nested": [str(root), {"other": str(root / "plans" / "plan.json")}],
        "untouched": "C:/external/file.mp4",
    }
    redacted = redact_private_paths(payload, (root,))
    assert redacted["path"] == "<allowed-root-1>/renders/proof.mp4"
    assert redacted["nested"][0] == "<allowed-root-1>"
    assert redacted["nested"][1]["other"] == "<allowed-root-1>/plans/plan.json"
    assert redacted["untouched"] == "C:/external/file.mp4"


def test_create_disposable_project_validates_profile_and_clip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)
    project_path = backend.paths.allowed_roots[0] / "proof.mlt"
    media_path = backend.paths.allowed_roots[0] / "source.mp4"
    media_path.write_bytes(b"data")
    captured: dict[str, object] = {}

    def fake_invoke(tool_name: str, arguments: dict) -> dict:
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return {"path": str(project_path), "revision": "a" * 64}

    monkeypatch.setattr(backend, "_invoke_tool", fake_invoke)
    result = backend.create_disposable_project(
        project_path,
        profile=ShotcutProfile(width=1920, height=1080, fps_num=30, fps_den=1),
        clips=[ShotcutClipIntent(media_path=media_path, in_frame=0, out_frame=89)],
    )
    assert result["revision"] == "a" * 64
    assert captured["tool_name"] == "create_project"
    assert captured["arguments"]["clips"][0]["path"] == str(media_path.resolve())


def test_append_linked_clip_uses_add_clip_operation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)
    project_path = backend.paths.allowed_roots[0] / "proof.mlt"
    project_path.write_text("<mlt/>", encoding="utf-8")
    media_path = backend.paths.allowed_roots[0] / "source.mp4"
    media_path.write_bytes(b"data")
    captured: dict[str, object] = {}

    def fake_invoke(tool_name: str, arguments: dict) -> dict:
        captured["tool_name"] = tool_name
        captured["arguments"] = arguments
        return {"changed": True}

    monkeypatch.setattr(backend, "_invoke_tool", fake_invoke)
    backend.append_linked_clip(
        project_path,
        expected_revision="b" * 64,
        clip=ShotcutClipIntent(media_path=media_path, track="V1", in_frame=10, out_frame=20),
    )
    assert captured["tool_name"] == "edit_project"
    assert captured["arguments"]["operations"] == [
        {
            "op": "add_clip",
            "track": "V1",
            "path": str(media_path.resolve()),
            "in_frame": 10,
            "out_frame": 20,
        }
    ]


def test_trim_linked_clip_requires_selector_change(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    project_path = backend.paths.allowed_roots[0] / "proof.mlt"
    project_path.write_text("<mlt/>", encoding="utf-8")
    with pytest.raises(ShotcutBackendError, match="requires in_frame, out_frame, or both"):
        backend.trim_linked_clip(project_path, expected_revision="c" * 64, item_ref="item:1")


def test_render_status_recovers_from_supervisor_race(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    log_path = backend.paths.allowed_roots[0] / "job.log"
    metadata_path = log_path.with_suffix(".json")
    output_path = backend.paths.allowed_roots[0] / "render.mp4"
    output_path.write_bytes(b"video")
    metadata_path.write_text(
        json.dumps(
            {
                "status": "completed",
                "output_path": str(output_path),
                "output_size_bytes": 5,
            }
        ),
        encoding="utf-8",
    )
    stabilized = backend._stabilize_render_status(
        {
            "status": "failed",
            "status_note": "The render supervisor exited before finalizing the job.",
            "log_path": str(log_path),
            "output_path": str(output_path),
        }
    )
    assert stabilized["status"] == "completed"


def test_await_render_polls_until_completed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    backend = _backend(tmp_path)
    statuses = iter(
        [
            {"status": "running"},
            {"status": "running"},
            {"status": "completed", "output_path": "proof.mp4"},
        ]
    )
    monkeypatch.setattr(backend, "render_status", lambda job_id: next(statuses))
    result = backend.await_render("job-1", timeout_seconds=5, poll_interval_seconds=0)
    assert result["status"] == "completed"


def test_select_render_backend_validates_supported_names(tmp_path: Path) -> None:
    backend = _backend(tmp_path)
    ffmpeg = object()
    assert select_render_backend("shotcut", shotcut_backend=backend) is backend
    assert select_render_backend("ffmpeg", ffmpeg_backend=ffmpeg) is ffmpeg
    with pytest.raises(ShotcutBackendError, match="Unsupported render backend"):
        select_render_backend("davinci")
