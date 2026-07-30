from __future__ import annotations

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
