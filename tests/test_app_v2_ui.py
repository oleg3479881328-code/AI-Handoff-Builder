from __future__ import annotations

import time
from pathlib import Path

import pytest


def _make_app():
    import tkinter as tk
    from app import App

    try:
        app = App()
    except tk.TclError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Tk UI unavailable: {exc}")
    app.withdraw()
    app.geometry("980x620")
    app.update_idletasks()
    return app


def test_v2_tab_uses_scroll_shell_and_collapsible_json():
    app = _make_app()
    try:
        assert app.v2_scroll_canvas.winfo_exists() == 1
        assert app.v2_scrollbar.winfo_exists() == 1
        assert app.v2_backend_name.get() == "ffmpeg"
        assert app.shotcut_build_button.winfo_exists() == 1
        assert app.shotcut_open_button.winfo_exists() == 1
        assert app.v2_diagnostics_visible is False
        assert app.v2_summary_json_frame.winfo_ismapped() == 0

        app._set_v2_diagnostics_visible(True)
        app.update_idletasks()
        assert app.v2_diagnostics_visible is True
        assert app.v2_summary_json_frame.winfo_ismapped() == 1

        app._set_v2_diagnostics_visible(False)
        app.update_idletasks()
        assert app.v2_summary_json_frame.winfo_ismapped() == 0
    finally:
        app.destroy()


def test_v1_settings_start_collapsed_and_toggle_from_button():
    app = _make_app()
    try:
        assert app.v1_settings_expanded is False
        assert app.v1_settings_toggle_button.cget("text") == "Показать настройки"
        assert app.v1_settings_frame.winfo_manager() == ""
        assert app.include_local_path_context.get() is True

        app._toggle_v1_settings()
        app.update_idletasks()
        assert app.v1_settings_expanded is True
        assert app.v1_settings_toggle_button.cget("text") == "Скрыть настройки"
        assert app.v1_settings_frame.winfo_manager() == "pack"

        app._toggle_v1_settings()
        app.update_idletasks()
        assert app.v1_settings_expanded is False
        assert app.v1_settings_toggle_button.cget("text") == "Показать настройки"
        assert app.v1_settings_frame.winfo_manager() == ""
    finally:
        app.destroy()


def test_application_version_is_visible_in_title_and_header():
    from handoff_builder.version import APP_DISPLAY_NAME, APP_VERSION

    app = _make_app()
    try:
        assert app.title() == f"{APP_DISPLAY_NAME} - {APP_VERSION}"
        assert app.app_version_label.cget("text") == f"Version: {APP_VERSION}"
    finally:
        app.destroy()


def test_v2_snapshot_focuses_latest_job_and_scrolls_results_into_view():
    app = _make_app()
    try:
        jobs = [
            {
                "render_job_id": f"job-{index}",
                "status": "pending" if index < 5 else "completed",
                "edit_plan_id": f"plan-{index}",
                "attempt_number": 1,
                "updated_at": f"2026-07-26T12:0{index}:00Z",
            }
            for index in range(1, 6)
        ]
        plans = [
            {
                "edit_plan_id": f"plan-{index}",
                "plan_version": index,
                "parent_plan_id": None if index == 1 else f"plan-{index - 1}",
                "plan_hash": f"hash-{index}",
            }
            for index in range(1, 6)
        ]
        snapshot = {
            "workspace": str(Path("C:/nonexistent/workspace")),
            "project_id": "proj-ui",
            "jobs": jobs,
            "plans": plans,
            "latest_job": jobs[-1],
            "latest_plan": plans[-1],
            "latest_details": {
                "job": {
                    "render_job_id": "job-5",
                    "status": "completed",
                },
                "plan": {
                    "edit_plan_id": "plan-5",
                    "plan_version": 5,
                },
                "report": {},
                "output_directory": "C:/nonexistent/workspace/renders/job-5",
            },
        }

        app._update_v2_snapshot(snapshot)
        app.update_idletasks()

        assert app.v2_queue.selection() == ("job-5",)
        assert app.v2_plans.selection() == ("plan-5",)
        yview = app.v2_scroll_canvas.yview()
        assert yview[0] > 0
    finally:
        app.destroy()


def test_packaged_acceptance_config_is_disabled_by_default(tmp_path: Path) -> None:
    from app import load_packaged_acceptance_config

    source_zip = tmp_path / "Carolyn and Rob.zip"
    source_zip.write_bytes(b"zip")
    payload = {
        "AIHB_ACCEPTANCE_SOURCE_ZIP": str(source_zip.resolve()),
        "AIHB_ACCEPTANCE_EDIT_PLAN_JSON": str((tmp_path / "Carolyn and Rob.json").resolve()),
        "AIHB_ACCEPTANCE_OUTPUT_DIR": str(tmp_path.resolve()),
    }

    assert load_packaged_acceptance_config(payload) is None


def test_packaged_acceptance_config_rejects_relative_paths(tmp_path: Path) -> None:
    from app import load_packaged_acceptance_config

    with pytest.raises(ValueError, match="absolute path"):
        load_packaged_acceptance_config(
            {
                "AIHB_PACKAGED_ACCEPTANCE": "1",
                "AIHB_ACCEPTANCE_SOURCE_ZIP": "Carolyn and Rob.zip",
                "AIHB_ACCEPTANCE_EDIT_PLAN_JSON": str((tmp_path / "Carolyn and Rob.json").resolve()),
                "AIHB_ACCEPTANCE_OUTPUT_DIR": str(tmp_path.resolve()),
            }
        )


def test_acceptance_mode_uses_same_gui_callbacks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import tkinter as tk
    import app as app_module

    source_zip = tmp_path / "Каролина And RÖB.zip"
    source_zip.write_bytes(b"zip")
    edit_plan_json = tmp_path / "Каролина And RÖB.json"
    monkeypatch.setenv("AIHB_PACKAGED_ACCEPTANCE", "1")
    monkeypatch.setenv("AIHB_ACCEPTANCE_SOURCE_ZIP", str(source_zip.resolve()))
    monkeypatch.setenv("AIHB_ACCEPTANCE_EDIT_PLAN_JSON", str(edit_plan_json.resolve()))
    monkeypatch.setenv("AIHB_ACCEPTANCE_OUTPUT_DIR", str(tmp_path.resolve()))

    try:
        ui = app_module.App()
    except tk.TclError as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Tk UI unavailable: {exc}")
    ui.withdraw()
    try:
        assert ui.acceptance_mode_enabled is True
        assert "PACKAGED ACCEPTANCE MODE ACTIVE" in ui.acceptance_banner_text.get()
        assert ui.output_dir.get() == str(tmp_path.resolve())

        seen: list[tuple[str, object]] = []

        monkeypatch.setattr(ui, "_start_with_sources", lambda selected: seen.append(("v1", selected)))
        monkeypatch.setattr(ui, "_v2_import_selected_path", lambda path: seen.append(("v2", path)))
        monkeypatch.setattr(ui, "_shotcut_build_selected_project", lambda: seen.append(("build", None)))
        monkeypatch.setattr(ui, "_shotcut_open_in_shotcut", lambda: seen.append(("open", None)))

        ui._acceptance_start()
        assert seen[0] == ("v1", [source_zip.resolve()])

        edit_plan_json.write_text("{}", encoding="utf-8")
        ui.acceptance_wait_deadline = time.time() + 1
        ui._acceptance_wait_for_plan_json()
        assert seen[1] == ("v2", edit_plan_json.resolve())

        ui.acceptance_expected_job_id = "job-1"
        ui.v2_queue.insert("", "end", iid="job-1", values=("pending", "plan-1", 1, "2026-07-30T00:00:00Z"))
        ui._acceptance_try_build_job()
        ui._acceptance_open_current_project()
        assert ("build", None) in seen
        assert ("open", None) in seen
    finally:
        ui.destroy()
