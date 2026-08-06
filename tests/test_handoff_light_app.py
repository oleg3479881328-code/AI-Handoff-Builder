from __future__ import annotations

import tkinter as tk
from pathlib import Path

import pytest

from handoff_builder.handoff_light.app import HandoffLightApp


def test_app_initial_status(tmp_path: Path):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable in this environment: {exc}")
    root.withdraw()
    try:
        app = HandoffLightApp(root, projects_root=tmp_path / "projects")
        assert app.status_vars["project"].get() == "No project open"
        assert app.status_vars["next_version"].get() == "V001"
    finally:
        root.destroy()


def test_app_refresh_status_after_create(tmp_path: Path):
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"Tk unavailable in this environment: {exc}")
    root.withdraw()
    try:
        app = HandoffLightApp(root, projects_root=tmp_path / "projects")
        app.current_project = app.store.create_project("App Project")
        app._refresh_status()
        assert app.status_vars["project"].get() == "App Project"
        assert app.status_vars["registered_assets"].get() == "0"
        assert str(app.add_button.cget("state")) == "normal"
    finally:
        root.destroy()
