from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from handoff_builder.v2.hyperframes_lab import HyperFramesAdapter, HyperFramesLabError


def _make_project(root: Path, html: str | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "index.html").write_text(
        html
        or """
<!doctype html>
<html lang="en">
  <body>
    <main data-composition-id="main" data-duration="3" data-width="1080" data-height="1920"></main>
  </body>
</html>
""".strip(),
        encoding="utf-8",
    )
    return root


def test_rejects_project_path_escape(tmp_path: Path):
    trusted = _make_project(tmp_path / "trusted")
    outside = _make_project(tmp_path / "outside")
    adapter = HyperFramesAdapter(trusted_prototype_root=trusted)
    with pytest.raises(HyperFramesLabError):
        adapter.resolve_project_dir(outside)


@pytest.mark.parametrize(
    "html",
    [
        '<html><body><script src="https://example.com/x.js"></script></body></html>',
        '<html><body><iframe src="https://example.com"></iframe></body></html>',
        '<html><body><script>fetch("https://example.com")</script></body></html>',
    ],
)
def test_rejects_remote_or_network_patterns(tmp_path: Path, html: str):
    trusted = _make_project(tmp_path / "trusted", html=html)
    adapter = HyperFramesAdapter(trusted_prototype_root=trusted)
    with pytest.raises(HyperFramesLabError):
        adapter.resolve_project_dir(trusted)


def test_missing_executable_is_structured_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    trusted = _make_project(tmp_path / "trusted")
    adapter = HyperFramesAdapter(trusted_prototype_root=trusted)
    monkeypatch.setattr("handoff_builder.v2.hyperframes_lab.find_executable", lambda *args, **kwargs: (_ for _ in ()).throw(FileNotFoundError("missing")))
    with pytest.raises(HyperFramesLabError, match="HyperFrames executable was not found"):
        adapter.discover_executable()


def test_preview_uses_argument_array_and_returns_url(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    trusted = _make_project(tmp_path / "trusted")
    adapter = HyperFramesAdapter(trusted_prototype_root=trusted)
    seen: list[list[str]] = []
    monkeypatch.setattr(adapter, "discover_executable", lambda: "hyperframes")

    def fake_run(args, **kwargs):
        seen.append(args)
        assert isinstance(args, list)
        return subprocess.CompletedProcess(args, 0, "Studio http://127.0.0.1:3002", "")

    monkeypatch.setattr("handoff_builder.v2.hyperframes_lab.run_command", fake_run)
    result = adapter.open_preview(trusted)
    assert result.success is True
    assert result.metadata["studio_root_url"] == "http://127.0.0.1:3002"
    assert result.metadata["studio_url"] == "http://127.0.0.1:3002#project/trusted?v=1&t=0&tab=renders&rc=1"
    assert seen[0][:3] == ["hyperframes", "preview", str(trusted.resolve())]


def test_failed_render_does_not_report_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    trusted = _make_project(tmp_path / "trusted")
    adapter = HyperFramesAdapter(trusted_prototype_root=trusted)
    monkeypatch.setattr(adapter, "discover_executable", lambda: "hyperframes")
    monkeypatch.setattr(
        "handoff_builder.v2.hyperframes_lab.run_command",
        lambda args, **kwargs: subprocess.CompletedProcess(args, 2, "", "render failed"),
    )
    result = adapter.render(trusted)
    assert result.success is False
    assert result.returncode == 2
    assert "output_path" in result.metadata


def test_gitignore_keeps_personal_hyperframes_material_untracked():
    gitignore = Path("C:/Users/oleg3/Documents/AI Handoff Builder v1/.gitignore").read_text(encoding="utf-8")
    assert "prototypes/hyperframes/assets/" in gitignore
    assert "prototypes/hyperframes/out/" in gitignore
