from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, ttk

from PIL import Image, ImageTk

from handoff_builder.models import BuildResult, BuilderConfig
from handoff_builder.pipeline import HandoffBuilder
from handoff_builder.theme import ThemePalette, ThemeSettingsStore, get_theme_palette
from handoff_builder.v2.coordinator_bridge import CoordinatorDraft, build_coordinator_draft, draft_to_payload, draft_to_summary
from handoff_builder.v2.gui_controller import V2RunnerController
from handoff_builder.v2.hyperframes_lab import HyperFramesAdapter, HyperFramesLabError
from handoff_builder.v2.services.import_service import resolve_workspace_for_package
from handoff_builder.v2.services import (
    list_voice_jobs,
    show_plan,
    show_render_job,
    voice_align,
    voice_approve,
    voice_generate,
    voice_health,
    voice_job_status,
    voice_profiles,
)

if os.name == "nt":
    import winsound
else:
    winsound = None


def _app_runtime_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _app_resource_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass).resolve()
    return Path(__file__).resolve().parent


def _default_hyperframes_project_root() -> Path:
    candidates = [
        _app_resource_root() / "prototypes" / "hyperframes",
        _app_runtime_root() / "prototypes" / "hyperframes",
    ]
    for candidate in candidates:
        if (candidate / "index.html").exists():
            return candidate
    return candidates[0]


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI Handoff Builder")
        self.geometry("1200x860")
        self.minsize(980, 720)
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        self.theme_store = ThemeSettingsStore()
        self.theme_mode = tk.StringVar(value=self.theme_store.load_theme_name())
        self.theme_palette: ThemePalette = get_theme_palette(self.theme_mode.get())
        self.theme_text_widgets: list[tk.Text] = []
        self.theme_listboxes: list[tk.Listbox] = []
        self.theme_windows: list[tk.Misc] = [self]

        self.sources: list[Path] = []
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop"))
        self.project_name = tk.StringVar(value="WEDDING_PROJECT")
        self.include_proxies = tk.BooleanVar(value=True)
        self.gps_export_mode = tk.StringVar(value="rounded")
        self.progress_value = tk.DoubleVar(value=0.0)
        self.status_text = tk.StringVar(value="Добавьте ZIP, папку или медиафайлы.")
        self.metadata_status_text = tk.StringVar(value="ExifTool: unknown")
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.last_output: Path | None = None
        self.last_result: BuildResult | None = None
        self.last_failed_sources: list[Path] = []
        self.active_builder: HandoffBuilder | None = None
        self.worker_count = tk.IntVar(value=2)
        self.retry_only_failed = False

        self.v2_controller = V2RunnerController(self.events)
        self.v2_workspace_path = tk.StringVar(value=str(Path.home() / "Desktop" / "AI Handoff Workspace"))
        self.v2_project_id = tk.StringVar(value="proj-1")
        self.v2_status_text = tk.StringVar(value="Выберите AI_EDIT_PACKAGE.zip или откройте workspace вручную.")
        self.v2_summary_text = ""
        self.v2_qc_text = ""
        self.v2_current_details: dict | None = None
        self.v2_current_snapshot: dict | None = None
        self.v2_first_frame_image: ImageTk.PhotoImage | None = None
        self.v2_busy = False
        self.main_notebook: ttk.Notebook | None = None
        self.voice_tab_loaded_once = False
        self.voice_base_url = tk.StringVar(value="http://127.0.0.1:17493")
        self.voice_profile_key = tk.StringVar(value="olga-polo-en-v1")
        self.voice_language = tk.StringVar(value="en-US")
        self.voice_engine = tk.StringVar(value="qwen")
        self.voice_model_size = tk.StringVar(value="0.6B")
        self.voice_target_duration_ms = tk.StringVar(value="")
        self.voice_status_text = tk.StringVar(value="Откройте вкладку Voice Studio и загрузите workspace.")
        self.voice_runtime_text = tk.StringVar(value="Runtime: not checked")
        self.voice_profile_text = tk.StringVar(value="Profile: not checked")
        self.voice_job_choice = tk.StringVar(value="")
        self.voice_jobs_map: dict[str, dict] = {}
        self.voice_current_job: dict | None = None
        self.voice_selected_take_id: str | None = None
        self.voice_playing_path: Path | None = None
        self.voice_similarity = tk.IntVar(value=5)
        self.voice_naturalness = tk.IntVar(value=5)
        self.voice_pronunciation = tk.IntVar(value=5)
        self.voice_pacing = tk.IntVar(value=5)
        self.voice_emotion = tk.IntVar(value=5)
        self.voice_artifacts = tk.StringVar(value="minor")
        self.hyperframes_project_path = tk.StringVar(value=str(_default_hyperframes_project_root()))
        self.hyperframes_status_text = tk.StringVar(value="HyperFrames Lab: trusted local prototype or workspace composition only.")
        self.hyperframes_runtime_text = tk.StringVar(value="Doctor: not checked")
        self.hyperframes_preview_url = tk.StringVar(value="")
        self.hyperframes_last_result: dict | None = None
        self.hyperframes_cancel_event: threading.Event | None = None
        self.coordinator_status_text = tk.StringVar(value="Вставьте coordinator brief и соберите trusted local draft.")
        self.coordinator_last_draft: CoordinatorDraft | None = None
        self.coordinator_last_saved_dir: Path | None = None

        self._build_ui()
        self._apply_theme()
        self.after(120, self._poll_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12, style="App.TFrame")
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="App.TFrame")
        header.pack(fill="x", pady=(0, 10))
        header.columnconfigure(0, weight=1)

        title_col = ttk.Frame(header, style="App.TFrame")
        title_col.grid(row=0, column=0, sticky="w")
        ttk.Label(title_col, text="AI Handoff Builder", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            title_col,
            text="v1 Prepare Handoff + v2 Local Edit Runner в одном Windows приложении",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(2, 0))

        theme_col = ttk.Frame(header, style="App.TFrame")
        theme_col.grid(row=0, column=1, sticky="e")
        ttk.Label(theme_col, text="Theme", style="Muted.TLabel").pack(anchor="e")
        ttk.Frame(theme_col, height=2, style="App.TFrame").pack()
        ttk.Radiobutton(
            theme_col,
            text="Dark",
            value="dark",
            variable=self.theme_mode,
            command=self._on_theme_changed,
            style="App.TRadiobutton",
        ).pack(side="left", padx=(0, 8))
        ttk.Radiobutton(
            theme_col,
            text="Light",
            value="light",
            variable=self.theme_mode,
            command=self._on_theme_changed,
            style="App.TRadiobutton",
        ).pack(side="left")

        self.main_notebook = ttk.Notebook(outer, style="App.TNotebook")
        self.main_notebook.pack(fill="both", expand=True)

        self.v1_tab = ttk.Frame(self.main_notebook, padding=14, style="App.TFrame")
        self.v2_tab = ttk.Frame(self.main_notebook, padding=14, style="App.TFrame")
        self.voice_tab = ttk.Frame(self.main_notebook, padding=14, style="App.TFrame")
        self.main_notebook.add(self.v1_tab, text="Prepare Handoff (v1)")
        self.main_notebook.add(self.v2_tab, text="Local Edit Runner (v2)")
        self.main_notebook.add(self.voice_tab, text="Voice Studio")
        self.main_notebook.bind("<<NotebookTabChanged>>", self._on_main_tab_changed)

        self._build_v1_tab()
        self._build_v2_tab()
        self._build_voice_tab()

    def _on_main_tab_changed(self, _event: object | None = None) -> None:
        if self.main_notebook is None:
            return
        current_tab = self.main_notebook.nametowidget(self.main_notebook.select())
        if current_tab is self.voice_tab and not self.voice_tab_loaded_once:
            self.voice_tab_loaded_once = True
            self._voice_start_refresh()

    def _build_v1_tab(self) -> None:
        outer = self.v1_tab

        ttk.Label(
            outer,
            text="ZIP / папка / файлы → один проверенный PROJECT_ANALYSIS_HANDOFF.zip",
        ).pack(anchor="w", pady=(0, 12))

        source_frame = ttk.LabelFrame(outer, text="Исходные материалы", padding=10)
        source_frame.pack(fill="both", expand=True)

        buttons = ttk.Frame(source_frame)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Добавить ZIP/файлы", command=self._add_files, style="Secondary.TButton").pack(side="left")
        ttk.Button(buttons, text="Добавить папку", command=self._add_folder, style="Secondary.TButton").pack(side="left", padx=6)
        ttk.Button(buttons, text="Удалить выбранное", command=self._remove_selected, style="Secondary.TButton").pack(side="left")
        ttk.Button(buttons, text="Очистить", command=self._clear, style="Secondary.TButton").pack(side="left", padx=6)

        self.source_list = tk.Listbox(source_frame, height=10)
        self.source_list.pack(fill="both", expand=True, pady=(10, 0))
        self._register_listbox(self.source_list)

        settings = ttk.LabelFrame(outer, text="Настройки", padding=10)
        settings.pack(fill="x", pady=12)

        ttk.Label(settings, text="Название проекта:").grid(row=0, column=0, sticky="w")
        ttk.Entry(settings, textvariable=self.project_name).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(settings, text="Куда сохранить:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(settings, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Button(settings, text="Выбрать", command=self._choose_output).grid(row=1, column=2, padx=(8, 0), pady=(8, 0))
        ttk.Checkbutton(
            settings,
            text="Включить лёгкие 720p video proxies в ZIP",
            variable=self.include_proxies,
        ).grid(row=2, column=1, sticky="w", pady=(8, 0))
        ttk.Label(settings, text="GPS export mode:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(
            settings,
            textvariable=self.gps_export_mode,
            values=("exact", "rounded", "venue_label_only", "excluded"),
            state="readonly",
        ).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(settings, text="Параллельных workers:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(settings, from_=1, to=2, textvariable=self.worker_count, width=8).grid(
            row=4, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )
        settings.columnconfigure(1, weight=1)

        ttk.Progressbar(outer, variable=self.progress_value, maximum=100).pack(fill="x")
        ttk.Label(outer, textvariable=self.status_text).pack(anchor="w", pady=(6, 6))
        ttk.Label(outer, textvariable=self.metadata_status_text).pack(anchor="w", pady=(0, 6))

        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="ПОДГОТОВИТЬ ДЛЯ CHATGPT", command=self._start, style="Accent.TButton")
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Отменить", command=self._cancel, state="disabled", style="Secondary.TButton")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.retry_button = ttk.Button(actions, text="Повторить failed", command=self._retry_failed, state="disabled", style="Secondary.TButton")
        self.retry_button.pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(actions, text="Открыть результат", command=self._open_result, state="disabled", style="Secondary.TButton")
        self.open_button.pack(side="left", padx=8)

        self.log = tk.Text(outer, height=9, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=False, pady=(10, 0))
        self._register_text_widget(self.log)

    def _build_v2_tab(self) -> None:
        outer = self.v2_tab
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(6, weight=1)

        workspace_frame = ttk.LabelFrame(outer, text="Workspace", padding=10)
        workspace_frame.grid(row=0, column=0, sticky="ew")
        workspace_frame.columnconfigure(1, weight=1)

        ttk.Label(workspace_frame, text="Workspace path:").grid(row=0, column=0, sticky="w")
        ttk.Entry(workspace_frame, textvariable=self.v2_workspace_path).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(workspace_frame, text="Выбрать", command=self._v2_choose_workspace).grid(row=0, column=2)
        ttk.Button(workspace_frame, text="Открыть workspace", command=self._v2_open_workspace).grid(row=0, column=3, padx=(8, 0))

        ttk.Label(workspace_frame, text="Project ID:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(workspace_frame, textvariable=self.v2_project_id).grid(row=1, column=1, sticky="ew", padx=(8, 8), pady=(8, 0))
        ttk.Button(workspace_frame, text="Создать workspace", command=self._v2_create_workspace).grid(row=1, column=2, pady=(8, 0))
        ttk.Button(workspace_frame, text="Открыть папку", command=self._v2_open_workspace_dir).grid(row=1, column=3, padx=(8, 0), pady=(8, 0))

        action_frame = ttk.Frame(outer)
        action_frame.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        self.v2_import_package_button = ttk.Button(action_frame, text="Import AI_EDIT_PACKAGE.zip", command=self._v2_import_package)
        self.v2_import_package_button.pack(side="left")
        self.v2_import_patch_button = ttk.Button(action_frame, text="Import AI_EDIT_PATCH", command=self._v2_import_patch)
        self.v2_import_patch_button.pack(side="left", padx=(8, 0))
        self.v2_refresh_button = ttk.Button(action_frame, text="Refresh", command=self._v2_refresh)
        self.v2_refresh_button.pack(side="left", padx=(8, 0))
        self.v2_run_next_button = ttk.Button(action_frame, text="Run Next Pending", command=self._v2_run_next)
        self.v2_run_next_button.pack(side="left", padx=(16, 0))
        self.v2_run_selected_button = ttk.Button(action_frame, text="Run Selected Job", command=self._v2_run_selected)
        self.v2_run_selected_button.pack(side="left", padx=(8, 0))
        self.v2_cancel_button = ttk.Button(action_frame, text="Request Cancel", command=self._v2_cancel_selected)
        self.v2_cancel_button.pack(side="left", padx=(8, 0))
        self.v2_retry_button = ttk.Button(action_frame, text="Retry Job", command=self._v2_retry_selected)
        self.v2_retry_button.pack(side="left", padx=(8, 0))
        ttk.Button(action_frame, text="Open Voice Studio", command=self._v2_open_voice_studio).pack(side="right")

        ttk.Label(outer, textvariable=self.v2_status_text).grid(row=2, column=0, sticky="w", pady=(8, 8))

        coordinator_frame = ttk.LabelFrame(outer, text="Coordinator Bridge", padding=10)
        coordinator_frame.grid(row=3, column=0, sticky="ew")
        coordinator_frame.columnconfigure(0, weight=3)
        coordinator_frame.columnconfigure(1, weight=2)
        coordinator_frame.rowconfigure(1, weight=1)
        ttk.Label(coordinator_frame, text="Coordinator Brief / Сценарный расклад").grid(row=0, column=0, sticky="w")
        self.coordinator_brief_text = tk.Text(coordinator_frame, height=7, wrap="word")
        self.coordinator_brief_text.grid(row=1, column=0, sticky="nsew", padx=(0, 12))
        self._register_text_widget(self.coordinator_brief_text)
        self.coordinator_brief_text.insert(
            "1.0",
            "Title: Warm Cafe Promise\n"
            "Voice: Your wedding should feel warm, confident, and alive.\n"
            "Visual: Gentle cafe light, polished portrait transitions, local-only render.\n"
            "Shots:\n- Wide room opening\n- Medium smile at the table\n- Close portrait finish\n"
            "Overlay:\n- HYPERFRAMES LAB\n- WARM AND ALIVE",
        )

        right_col = ttk.Frame(coordinator_frame, style="App.TFrame")
        right_col.grid(row=1, column=1, sticky="nsew")
        right_col.columnconfigure(0, weight=1)
        ttk.Label(right_col, text="Trusted Local Draft Summary").grid(row=0, column=0, sticky="w")
        self.coordinator_summary = tk.Text(right_col, height=7, wrap="word", state="disabled")
        self.coordinator_summary.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self._register_text_widget(self.coordinator_summary)

        button_row = ttk.Frame(coordinator_frame, style="App.TFrame")
        button_row.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(button_row, text="Build Draft", command=self._coordinator_build_draft).pack(side="left")
        ttk.Button(button_row, text="Apply Script to Voice Studio", command=self._coordinator_apply_voice_script).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="Save Draft File", command=self._coordinator_save_draft).pack(side="left", padx=(8, 0))
        ttk.Button(button_row, text="Open Draft Folder", command=self._coordinator_open_draft_folder).pack(side="left", padx=(8, 0))
        ttk.Label(coordinator_frame, textvariable=self.coordinator_status_text, wraplength=980, justify="left").grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        hyperframes_frame = ttk.LabelFrame(outer, text="HyperFrames Lab", padding=10)
        hyperframes_frame.grid(row=4, column=0, sticky="ew", pady=(10, 0))
        hyperframes_frame.columnconfigure(1, weight=1)
        ttk.Label(hyperframes_frame, text="Project dir:").grid(row=0, column=0, sticky="w")
        ttk.Entry(hyperframes_frame, textvariable=self.hyperframes_project_path).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        self.hyperframes_choose_button = ttk.Button(hyperframes_frame, text="Choose", command=self._hyperframes_choose_project)
        self.hyperframes_choose_button.grid(row=0, column=2, sticky="ew")
        action_row = ttk.Frame(hyperframes_frame)
        action_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        self.hyperframes_doctor_button = ttk.Button(action_row, text="Refresh Doctor", command=self._hyperframes_refresh_doctor)
        self.hyperframes_doctor_button.pack(side="left")
        self.hyperframes_preview_button = ttk.Button(action_row, text="Open Preview", command=self._hyperframes_open_preview)
        self.hyperframes_preview_button.pack(side="left", padx=(8, 0))
        self.hyperframes_render_button = ttk.Button(action_row, text="Render MP4", command=self._hyperframes_render)
        self.hyperframes_render_button.pack(side="left", padx=(8, 0))
        self.hyperframes_cancel_button = ttk.Button(action_row, text="Cancel", command=self._hyperframes_request_cancel)
        self.hyperframes_cancel_button.pack(side="left", padx=(8, 0))
        self.hyperframes_output_button = ttk.Button(action_row, text="Open Output Folder", command=self._hyperframes_open_output_dir)
        self.hyperframes_output_button.pack(side="left", padx=(16, 0))
        ttk.Label(hyperframes_frame, textvariable=self.hyperframes_runtime_text, wraplength=900, justify="left").grid(
            row=2, column=0, columnspan=3, sticky="w", pady=(8, 0)
        )
        ttk.Label(hyperframes_frame, textvariable=self.hyperframes_status_text, wraplength=900, justify="left").grid(
            row=3, column=0, columnspan=3, sticky="w", pady=(6, 0)
        )

        summary_frame = ttk.LabelFrame(outer, text="Import AI Plan / Patch Summary", padding=10)
        summary_frame.grid(row=5, column=0, sticky="nsew", pady=(10, 0))
        summary_frame.columnconfigure(0, weight=1)
        summary_frame.rowconfigure(0, weight=1)
        self.v2_summary = tk.Text(summary_frame, height=10, wrap="word", state="disabled")
        self.v2_summary.grid(row=0, column=0, sticky="nsew")
        self._register_text_widget(self.v2_summary)

        lower = ttk.Panedwindow(outer, orient="horizontal")
        lower.grid(row=6, column=0, sticky="nsew", pady=(10, 0))

        queue_frame = ttk.Frame(lower, padding=4)
        queue_frame.columnconfigure(0, weight=1)
        queue_frame.rowconfigure(1, weight=1)
        lower.add(queue_frame, weight=3)

        plans_frame = ttk.Frame(lower, padding=4)
        plans_frame.columnconfigure(0, weight=1)
        plans_frame.rowconfigure(1, weight=1)
        lower.add(plans_frame, weight=2)

        results_frame = ttk.Frame(lower, padding=4)
        results_frame.columnconfigure(0, weight=1)
        results_frame.rowconfigure(2, weight=1)
        lower.add(results_frame, weight=4)

        ttk.Label(queue_frame, text="Render Queue", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.v2_queue = ttk.Treeview(
            queue_frame,
            columns=("status", "plan", "attempt", "updated"),
            show="headings",
            height=10,
        )
        self.v2_queue.heading("status", text="Status")
        self.v2_queue.heading("plan", text="Plan ID")
        self.v2_queue.heading("attempt", text="Attempt")
        self.v2_queue.heading("updated", text="Updated")
        self.v2_queue.column("status", width=110, anchor="w")
        self.v2_queue.column("plan", width=170, anchor="w")
        self.v2_queue.column("attempt", width=70, anchor="center")
        self.v2_queue.column("updated", width=150, anchor="w")
        self.v2_queue.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.v2_queue.bind("<<TreeviewSelect>>", self._v2_on_queue_selected)

        queue_actions = ttk.Frame(queue_frame)
        queue_actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(queue_actions, text="Open Output Dir", command=self._v2_open_output_dir).pack(side="left")
        ttk.Button(queue_actions, text="Open Reel", command=self._v2_open_reel).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Open Report", command=self._v2_open_report).pack(side="left", padx=(8, 0))
        ttk.Button(queue_actions, text="Open FFmpeg Command", command=self._v2_open_ffmpeg_command).pack(side="left", padx=(8, 0))

        ttk.Label(plans_frame, text="Plan Versions", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.v2_plans = ttk.Treeview(
            plans_frame,
            columns=("version", "parent", "hash"),
            show="headings",
            height=10,
        )
        self.v2_plans.heading("version", text="Version")
        self.v2_plans.heading("parent", text="Parent Plan")
        self.v2_plans.heading("hash", text="Plan Hash")
        self.v2_plans.column("version", width=70, anchor="center")
        self.v2_plans.column("parent", width=150, anchor="w")
        self.v2_plans.column("hash", width=180, anchor="w")
        self.v2_plans.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.v2_plans.bind("<<TreeviewSelect>>", self._v2_on_plan_selected)

        ttk.Label(results_frame, text="Results / QC", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.v2_result_meta = ttk.Label(results_frame, text="Нет выбранного render job.", wraplength=360, justify="left")
        self.v2_result_meta.grid(row=1, column=0, sticky="ew", pady=(6, 8))
        qc_body = ttk.Frame(results_frame)
        qc_body.grid(row=2, column=0, sticky="nsew")
        qc_body.columnconfigure(1, weight=1)
        qc_body.rowconfigure(0, weight=1)

        image_frame = ttk.LabelFrame(qc_body, text="First Frame", padding=8)
        image_frame.grid(row=0, column=0, sticky="nsw")
        self.v2_first_frame_label = ttk.Label(image_frame, text="first_frame.jpg unavailable", width=42)
        self.v2_first_frame_label.pack()

        qc_frame = ttk.LabelFrame(qc_body, text="QC / Errors", padding=8)
        qc_frame.grid(row=0, column=1, sticky="nsew", padx=(10, 0))
        qc_frame.columnconfigure(0, weight=1)
        qc_frame.rowconfigure(0, weight=1)
        self.v2_qc = tk.Text(qc_frame, height=14, wrap="word", state="disabled")
        self.v2_qc.grid(row=0, column=0, sticky="nsew")
        self._register_text_widget(self.v2_qc)

    def _build_voice_tab(self) -> None:
        outer = self.voice_tab
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(4, weight=1)

        ttk.Label(outer, text="Voice Studio / Озвучка", style="Title.TLabel").grid(row=0, column=0, sticky="w")

        top = ttk.Frame(outer)
        top.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        top.columnconfigure(0, weight=1)
        top.columnconfigure(1, weight=1)

        runtime_frame = ttk.LabelFrame(top, text="Runtime / Profile", padding=10)
        runtime_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        runtime_frame.columnconfigure(1, weight=1)
        ttk.Label(runtime_frame, text="Base URL:").grid(row=0, column=0, sticky="w")
        ttk.Entry(runtime_frame, textvariable=self.voice_base_url).grid(row=0, column=1, sticky="ew", padx=(8, 8))
        ttk.Button(runtime_frame, text="Refresh Runtime", command=self._voice_start_refresh).grid(row=0, column=2)
        ttk.Label(runtime_frame, textvariable=self.voice_runtime_text, wraplength=500, justify="left").grid(row=1, column=0, columnspan=3, sticky="w", pady=(8, 4))
        ttk.Label(runtime_frame, textvariable=self.voice_profile_text, wraplength=500, justify="left").grid(row=2, column=0, columnspan=3, sticky="w")

        job_frame = ttk.LabelFrame(top, text="Generate 3 Olga Takes", padding=10)
        job_frame.grid(row=0, column=1, sticky="nsew")
        job_frame.columnconfigure(1, weight=1)
        ttk.Label(job_frame, text="Profile Key:").grid(row=0, column=0, sticky="w")
        ttk.Entry(job_frame, textvariable=self.voice_profile_key).grid(row=0, column=1, sticky="ew", padx=(8, 0))
        ttk.Label(job_frame, text="Language:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(job_frame, textvariable=self.voice_language).grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(job_frame, text="Engine:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(job_frame, textvariable=self.voice_engine).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(job_frame, text="Model Size:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(job_frame, textvariable=self.voice_model_size).grid(row=3, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Label(job_frame, text="Target Duration ms:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(job_frame, textvariable=self.voice_target_duration_ms).grid(row=4, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))
        ttk.Button(job_frame, text="Generate 3 Takes", command=self._voice_start_generate).grid(row=5, column=1, sticky="e", pady=(10, 0))

        script_frame = ttk.LabelFrame(outer, text="Script / Текст озвучки", padding=10)
        script_frame.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        script_frame.columnconfigure(0, weight=1)
        self.voice_script_text = tk.Text(script_frame, height=5, wrap="word")
        self.voice_script_text.grid(row=0, column=0, sticky="ew")
        self._register_text_widget(self.voice_script_text)
        self.voice_script_text.insert(
            "1.0",
            "Your wedding should feel warm, confident, and alive, like every promise, every laugh, and every dance is still glowing in the room.",
        )
        ttk.Label(outer, textvariable=self.voice_status_text).grid(row=3, column=0, sticky="nw", pady=(8, 6))

        body = ttk.Panedwindow(outer, orient="horizontal")
        body.grid(row=4, column=0, sticky="nsew")

        left = ttk.Frame(body, padding=4)
        center = ttk.Frame(body, padding=4)
        right = ttk.Frame(body, padding=4)
        for frame in (left, center, right):
            frame.columnconfigure(0, weight=1)
            frame.rowconfigure(1, weight=1)
        body.add(left, weight=2)
        body.add(center, weight=3)
        body.add(right, weight=3)

        ttk.Label(left, text="Voice Jobs", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.voice_job_combo = ttk.Combobox(left, textvariable=self.voice_job_choice, state="readonly")
        self.voice_job_combo.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.voice_job_combo.bind("<<ComboboxSelected>>", self._voice_on_job_selected)
        ttk.Button(left, text="Refresh Jobs", command=self._voice_start_refresh).grid(row=2, column=0, sticky="w", pady=(8, 0))

        ttk.Label(center, text="Takes / Прослушивание", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        self.voice_takes = ttk.Treeview(
            center,
            columns=("idx", "status", "duration", "sha"),
            show="headings",
            height=12,
        )
        self.voice_takes.heading("idx", text="#")
        self.voice_takes.heading("status", text="Status")
        self.voice_takes.heading("duration", text="Duration ms")
        self.voice_takes.heading("sha", text="SHA-256")
        self.voice_takes.column("idx", width=45, anchor="center")
        self.voice_takes.column("status", width=180, anchor="w")
        self.voice_takes.column("duration", width=100, anchor="center")
        self.voice_takes.column("sha", width=210, anchor="w")
        self.voice_takes.grid(row=1, column=0, sticky="nsew", pady=(6, 0))
        self.voice_takes.bind("<<TreeviewSelect>>", self._voice_on_take_selected)

        play_actions = ttk.Frame(center)
        play_actions.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(play_actions, text="Play Selected", command=self._voice_play_selected_take).pack(side="left")
        ttk.Button(play_actions, text="Stop", command=self._voice_stop_playback).pack(side="left", padx=(8, 0))
        ttk.Button(play_actions, text="Open WAV", command=self._voice_open_selected_take).pack(side="left", padx=(8, 0))
        ttk.Button(play_actions, text="Align", command=self._voice_start_align_selected).pack(side="left", padx=(16, 0))

        ttk.Label(right, text="QC / Review / Approve", style="SectionTitle.TLabel").grid(row=0, column=0, sticky="w")
        review_top = ttk.Frame(right)
        review_top.grid(row=1, column=0, sticky="ew", pady=(6, 6))
        for col in range(4):
            review_top.columnconfigure(col, weight=1)
        ttk.Label(review_top, text="Similarity").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(review_top, from_=1, to=5, textvariable=self.voice_similarity, width=5).grid(row=0, column=1, sticky="w")
        ttk.Label(review_top, text="Naturalness").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(review_top, from_=1, to=5, textvariable=self.voice_naturalness, width=5).grid(row=0, column=3, sticky="w")
        ttk.Label(review_top, text="Pronunciation").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(review_top, from_=1, to=5, textvariable=self.voice_pronunciation, width=5).grid(row=1, column=1, sticky="w", pady=(6, 0))
        ttk.Label(review_top, text="Pacing").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Spinbox(review_top, from_=1, to=5, textvariable=self.voice_pacing, width=5).grid(row=1, column=3, sticky="w", pady=(6, 0))
        ttk.Label(review_top, text="Emotion").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Spinbox(review_top, from_=1, to=5, textvariable=self.voice_emotion, width=5).grid(row=2, column=1, sticky="w", pady=(6, 0))
        ttk.Label(review_top, text="Artifacts").grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Combobox(review_top, textvariable=self.voice_artifacts, values=("none", "minor", "major"), state="readonly", width=10).grid(row=2, column=3, sticky="w", pady=(6, 0))

        notes_frame = ttk.LabelFrame(right, text="Review Notes", padding=8)
        notes_frame.grid(row=2, column=0, sticky="ew")
        notes_frame.columnconfigure(0, weight=1)
        self.voice_notes = tk.Text(notes_frame, height=4, wrap="word")
        self.voice_notes.grid(row=0, column=0, sticky="ew")
        self._register_text_widget(self.voice_notes)

        action_row = ttk.Frame(right)
        action_row.grid(row=3, column=0, sticky="ew", pady=(8, 8))
        ttk.Button(action_row, text="Approve Selected Take", command=self._voice_start_approve_selected, style="Accent.TButton").pack(side="left")

        qc_frame = ttk.LabelFrame(right, text="Take Details", padding=8)
        qc_frame.grid(row=4, column=0, sticky="nsew")
        qc_frame.columnconfigure(0, weight=1)
        qc_frame.rowconfigure(0, weight=1)
        right.rowconfigure(4, weight=1)
        self.voice_qc = tk.Text(qc_frame, height=18, wrap="word", state="disabled")
        self.voice_qc.grid(row=0, column=0, sticky="nsew")
        self._register_text_widget(self.voice_qc)

    def _register_text_widget(self, widget: tk.Text) -> None:
        self.theme_text_widgets.append(widget)

    def _register_listbox(self, widget: tk.Listbox) -> None:
        self.theme_listboxes.append(widget)

    def _register_window(self, widget: tk.Misc) -> None:
        if widget not in self.theme_windows:
            self.theme_windows.append(widget)

    def _on_theme_changed(self) -> None:
        theme_name = self.theme_store.save_theme_name(self.theme_mode.get())
        self.theme_mode.set(theme_name)
        self._apply_theme()

    def _apply_theme(self) -> None:
        palette = get_theme_palette(self.theme_mode.get())
        self.theme_palette = palette
        self.configure(bg=palette.app_bg)
        self.option_add("*Font", "{Segoe UI} 10")
        self.style.configure(".", background=palette.surface, foreground=palette.text, font=("Segoe UI", 10))
        self.style.map(".", foreground=[("disabled", palette.disabled_text)])

        self.style.configure("App.TFrame", background=palette.app_bg)
        self.style.configure("Surface.TFrame", background=palette.surface)
        self.style.configure("Elevated.TFrame", background=palette.surface_elevated)
        self.style.configure("App.TLabel", background=palette.app_bg, foreground=palette.text)
        self.style.configure("Muted.TLabel", background=palette.app_bg, foreground=palette.text_muted)
        self.style.configure("Title.TLabel", background=palette.app_bg, foreground=palette.text, font=("Segoe UI Semibold", 22))
        self.style.configure("Subtitle.TLabel", background=palette.app_bg, foreground=palette.text_muted, font=("Segoe UI", 11))
        self.style.configure("SectionTitle.TLabel", background=palette.surface, foreground=palette.text, font=("Segoe UI Semibold", 11))
        self.style.configure(
            "TLabel",
            background=palette.app_bg,
            foreground=palette.text,
        )
        self.style.configure(
            "TLabelframe",
            background=palette.surface,
            bordercolor=palette.border,
            relief="solid",
            borderwidth=1,
        )
        self.style.configure(
            "TLabelframe.Label",
            background=palette.surface,
            foreground=palette.text,
            font=("Segoe UI Semibold", 10),
        )
        self.style.configure(
            "TButton",
            background=palette.surface_alt,
            foreground=palette.text,
            bordercolor=palette.border,
            focusthickness=1,
            focuscolor=palette.focus,
            padding=(10, 6),
        )
        self.style.map(
            "TButton",
            background=[("active", palette.surface_elevated), ("disabled", palette.disabled_bg)],
            foreground=[("disabled", palette.disabled_text)],
            bordercolor=[("focus", palette.focus)],
        )
        self.style.configure(
            "Secondary.TButton",
            background=palette.surface_alt,
            foreground=palette.text,
            bordercolor=palette.border,
        )
        self.style.configure(
            "Accent.TButton",
            background=palette.accent,
            foreground=palette.accent_text,
            bordercolor=palette.accent,
            font=("Segoe UI Semibold", 10),
        )
        self.style.map(
            "Accent.TButton",
            background=[("active", palette.accent_active), ("disabled", palette.disabled_bg)],
            foreground=[("disabled", palette.disabled_text)],
        )
        self.style.configure(
            "Success.TButton",
            background=palette.success,
            foreground=palette.accent_text,
            bordercolor=palette.success,
        )
        self.style.configure(
            "Warning.TButton",
            background=palette.warning,
            foreground=palette.accent_text,
            bordercolor=palette.warning,
        )
        self.style.configure(
            "Danger.TButton",
            background=palette.error,
            foreground=palette.accent_text,
            bordercolor=palette.error,
        )
        self.style.configure(
            "TEntry",
            fieldbackground=palette.input_bg,
            foreground=palette.input_text,
            insertcolor=palette.input_text,
            bordercolor=palette.border,
            lightcolor=palette.border,
            darkcolor=palette.border,
        )
        self.style.configure(
            "TCombobox",
            fieldbackground=palette.input_bg,
            foreground=palette.input_text,
            arrowcolor=palette.text,
            bordercolor=palette.border,
        )
        self.style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette.input_bg), ("disabled", palette.disabled_bg)],
            foreground=[("readonly", palette.input_text), ("disabled", palette.disabled_text)],
            selectbackground=[("readonly", palette.selection_bg)],
            selectforeground=[("readonly", palette.selection_text)],
        )
        self.style.configure(
            "TSpinbox",
            fieldbackground=palette.input_bg,
            foreground=palette.input_text,
            bordercolor=palette.border,
            arrowcolor=palette.text,
        )
        self.style.configure("TCheckbutton", background=palette.surface, foreground=palette.text)
        self.style.configure("App.TRadiobutton", background=palette.app_bg, foreground=palette.text)
        self.style.map("App.TRadiobutton", foreground=[("disabled", palette.disabled_text)])
        self.style.configure(
            "App.TNotebook",
            background=palette.app_bg,
            borderwidth=0,
            tabmargins=(0, 0, 0, 0),
        )
        self.style.configure(
            "App.TNotebook.Tab",
            background=palette.surface_alt,
            foreground=palette.text_muted,
            padding=(16, 8),
            bordercolor=palette.border,
        )
        self.style.map(
            "App.TNotebook.Tab",
            background=[("selected", palette.surface), ("active", palette.surface_elevated)],
            foreground=[("selected", palette.text), ("active", palette.text)],
        )
        self.style.configure("TPanedwindow", background=palette.app_bg, sashwidth=8)
        self.style.configure(
            "Treeview",
            background=palette.input_bg,
            foreground=palette.input_text,
            fieldbackground=palette.input_bg,
            bordercolor=palette.border,
            rowheight=24,
        )
        self.style.map(
            "Treeview",
            background=[("selected", palette.selection_bg)],
            foreground=[("selected", palette.selection_text)],
        )
        self.style.configure(
            "Treeview.Heading",
            background=palette.surface_elevated,
            foreground=palette.text,
            bordercolor=palette.border,
            font=("Segoe UI Semibold", 10),
        )
        self.style.map("Treeview.Heading", background=[("active", palette.surface_alt)])
        self.style.configure(
            "Horizontal.TProgressbar",
            background=palette.accent,
            troughcolor=palette.surface_alt,
            bordercolor=palette.border,
            lightcolor=palette.accent,
            darkcolor=palette.accent,
        )

        for window in list(self.theme_windows):
            try:
                window.configure(bg=palette.app_bg)
            except tk.TclError:
                continue
        for widget in list(self.theme_text_widgets):
            try:
                widget.configure(
                    bg=palette.input_bg,
                    fg=palette.input_text,
                    insertbackground=palette.input_text,
                    selectbackground=palette.selection_bg,
                    selectforeground=palette.selection_text,
                    disabledbackground=palette.input_bg,
                    disabledforeground=palette.text_muted,
                    highlightthickness=1,
                    highlightbackground=palette.border,
                    highlightcolor=palette.focus,
                    relief="flat",
                    borderwidth=0,
                )
            except tk.TclError:
                continue
        for widget in list(self.theme_listboxes):
            try:
                widget.configure(
                    bg=palette.input_bg,
                    fg=palette.input_text,
                    selectbackground=palette.selection_bg,
                    selectforeground=palette.selection_text,
                    highlightthickness=1,
                    highlightbackground=palette.border,
                    highlightcolor=palette.focus,
                    relief="flat",
                    borderwidth=0,
                )
            except tk.TclError:
                continue

    def _show_dialog(self, level: str, title: str, message: str) -> None:
        palette = self.theme_palette
        accent_style = {
            "info": "Accent.TButton",
            "warning": "Warning.TButton",
            "error": "Danger.TButton",
        }.get(level, "Accent.TButton")
        badge_fg = {
            "info": palette.accent,
            "warning": palette.warning,
            "error": palette.error,
        }.get(level, palette.accent)
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.configure(bg=palette.app_bg)
        self._register_window(dialog)

        outer = ttk.Frame(dialog, padding=16, style="App.TFrame")
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=title, style="Title.TLabel").pack(anchor="w")
        tk.Label(
            outer,
            text=level.upper(),
            fg=badge_fg,
            bg=palette.app_bg,
            font=("Segoe UI Semibold", 10),
        ).pack(anchor="w", pady=(4, 10))
        text = tk.Text(outer, width=64, height=max(4, min(14, message.count("\n") + 2)), wrap="word")
        text.pack(fill="both", expand=True)
        self._register_text_widget(text)
        self._apply_theme()
        text.insert("1.0", message)
        text.configure(state="disabled")
        ttk.Button(outer, text="OK", command=dialog.destroy, style=accent_style).pack(anchor="e", pady=(14, 0))
        dialog.update_idletasks()
        dialog.geometry(f"+{self.winfo_rootx() + 80}+{self.winfo_rooty() + 80}")
        dialog.wait_window()

    def _show_info(self, title: str, message: str) -> None:
        self._show_dialog("info", title, message)

    def _show_warning(self, title: str, message: str) -> None:
        self._show_dialog("warning", title, message)

    def _show_error(self, title: str, message: str) -> None:
        self._show_dialog("error", title, message)

    def _add_files(self) -> None:
        values = filedialog.askopenfilenames(
            title="Выберите ZIP, фото или видео",
            filetypes=[
                ("Media and ZIP", "*.zip *.jpg *.jpeg *.png *.webp *.tif *.tiff *.mp4 *.mov *.m4v *.avi *.mkv *.webm *.mts *.m2ts"),
                ("All files", "*.*"),
            ],
        )
        self._add_paths([Path(value) for value in values])

    def _add_folder(self) -> None:
        value = filedialog.askdirectory(title="Выберите папку с материалами")
        if value:
            self._add_paths([Path(value)])

    def _add_paths(self, paths: list[Path]) -> None:
        existing = {path.resolve() for path in self.sources}
        for path in paths:
            resolved = path.resolve()
            if resolved not in existing:
                self.sources.append(resolved)
                existing.add(resolved)
                self.source_list.insert("end", str(resolved))

    def _remove_selected(self) -> None:
        selected = list(self.source_list.curselection())
        for index in reversed(selected):
            self.source_list.delete(index)
            del self.sources[index]

    def _clear(self) -> None:
        self.sources.clear()
        self.source_list.delete(0, "end")

    def _choose_output(self) -> None:
        value = filedialog.askdirectory(title="Куда сохранить готовый ZIP")
        if value:
            self.output_dir.set(value)

    def _append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _start(self) -> None:
        self.retry_only_failed = False
        self._start_with_sources(self.sources.copy())

    def _start_with_sources(self, selected_sources: list[Path]) -> None:
        if not selected_sources:
            if self.retry_only_failed:
                self._show_warning("Нет failed", "Нет файлов для повторной обработки.")
            else:
                self._show_warning("Нет материалов", "Добавьте ZIP, папку или файлы.")
            return
        if self._owner_project_root_from_sources(selected_sources) is None and not self.project_name.get().strip():
            self._show_warning("Нет названия", "Введите название проекта.")
            return
        output = Path(self.output_dir.get()).expanduser()
        output.mkdir(parents=True, exist_ok=True)

        self.start_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.retry_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
        self.progress_value.set(0)
        self.status_text.set("Запуск...")
        self.last_output = None
        self.last_result = None

        thread = threading.Thread(target=self._run_builder, args=(selected_sources,), daemon=True)
        thread.start()

    def _run_builder(self, selected_sources: list[Path]) -> None:
        try:
            owner_project_root = self._owner_project_root_from_sources(selected_sources)
            project_name = owner_project_root.name if owner_project_root is not None else self.project_name.get().strip()
            config = BuilderConfig(
                project_name=project_name,
                output_dir=Path(self.output_dir.get()).expanduser(),
                workspace_root=owner_project_root,
                source_zip_path=selected_sources[0].resolve()
                if owner_project_root is not None and len(selected_sources) == 1 and selected_sources[0].suffix.lower() == ".zip"
                else None,
                include_video_proxies=self.include_proxies.get(),
                gps_export_mode=self.gps_export_mode.get(),
                worker_count=max(1, min(2, int(self.worker_count.get()))),
            )
            builder = HandoffBuilder(
                config,
                progress=lambda value, message: self.events.put(("progress", (value, message))),
                log=lambda message: self.events.put(("log", message)),
                project_root=_app_resource_root(),
            )
            self.active_builder = builder
            result = builder.build(selected_sources)
            self.events.put(("done", result))
        except Exception as exc:
            self.events.put(("error", str(exc)))
        finally:
            self.active_builder = None

    def _cancel(self) -> None:
        if self.active_builder:
            self.active_builder.cancel()
            self.status_text.set("Отмена...")
            self._append_log("Cancellation requested.")

    def _retry_failed(self) -> None:
        self.retry_only_failed = True
        self._start_with_sources(self.last_failed_sources.copy())

    def _show_summary(self, result: BuildResult) -> None:
        summary = result.validation
        window = tk.Toplevel(self)
        window.title("Итоговая сводка")
        window.geometry("520x320")
        window.transient(self)
        window.grab_set()
        self._register_window(window)
        self._apply_theme()

        body = ttk.Frame(window, padding=16, style="App.TFrame")
        body.pack(fill="both", expand=True)

        coverage_ok = bool(summary.get("coverage_ok"))
        tk.Label(
            body,
            text="Coverage OK" if coverage_ok else "Coverage needs attention",
            font=("Segoe UI Semibold", 18),
            fg=self.theme_palette.success if coverage_ok else self.theme_palette.error,
            bg=self.theme_palette.app_bg,
        ).pack(anchor="w")

        lines = [
            f"{summary.get('source_video_count', 0)} videos found",
            f"{summary.get('video_assets_represented', 0)} videos represented",
            f"{summary.get('source_photo_count', 0)} photos found",
            f"{summary.get('photo_assets_represented', 0)} photos represented",
            f"{summary.get('metadata_records_total', 0)} metadata records",
            f"{summary.get('assets_with_capture_time', 0)} assets with capture time",
            f"{summary.get('assets_with_gps', 0)} assets with GPS",
            f"{summary.get('metadata_status_counts', {}).get('partial', 0)} partial metadata records",
            f"{summary.get('failed_asset_count', 0)} lost files",
            f"Coverage OK: {coverage_ok}",
        ]
        for line in lines:
            ttk.Label(body, text=line).pack(anchor="w", pady=(10 if line == lines[0] else 4, 0))

        if not coverage_ok:
            failed = summary.get("failed_assets", [])
            ttk.Label(
                body,
                text=f"Export is not a green success because coverage_ok=false. Failed assets: {len(failed)}",
                wraplength=460,
            ).pack(anchor="w", pady=(14, 0))

        metadata_tool = summary.get("metadata_tool_status", {}).get("exiftool", {})
        ttk.Label(
            body,
            text=(
                f"ExifTool status: {metadata_tool.get('status', 'unknown')} | "
                f"GPS mode: {summary.get('gps_export_mode', '-')}"
            ),
            wraplength=460,
        ).pack(anchor="w", pady=(14, 0))

        ttk.Label(
            body,
            text=f"Metadata warnings: {summary.get('metadata_warning_count', 0)} at metadata/metadata_warnings.json",
            wraplength=460,
        ).pack(anchor="w", pady=(8, 0))

        ttk.Button(body, text="Закрыть", command=window.destroy, style="Accent.TButton").pack(anchor="e", pady=(18, 0))

    def _v2_choose_workspace(self) -> None:
        value = filedialog.askdirectory(title="Выберите exact workspace folder")
        if value:
            self.v2_workspace_path.set(value)

    def _v2_create_workspace(self) -> None:
        workspace = Path(self.v2_workspace_path.get()).expanduser()
        project_id = self.v2_project_id.get().strip()
        if not project_id:
            self._show_warning("Нет project ID", "Введите project ID для нового workspace.")
            return
        self._v2_set_busy(True, "Создание v2 workspace...")
        self.v2_controller.start_open_workspace(workspace, project_id=project_id, create=True)

    def _v2_open_workspace(self) -> None:
        workspace = Path(self.v2_workspace_path.get()).expanduser()
        self._v2_set_busy(True, "Открытие v2 workspace...")
        self.v2_controller.start_open_workspace(workspace, create=False)

    def _v2_import_package(self) -> None:
        value = filedialog.askopenfilename(
            title="Выберите AI_EDIT_PACKAGE.zip",
            filetypes=[("AI Edit Package", "*.zip"), ("All files", "*.*")],
        )
        if value:
            package_zip = Path(value)
            fallback_path: Path | None = None
            if self.v2_controller.workspace is None:
                try:
                    resolved_workspace = resolve_workspace_for_package(package_zip)
                    self.v2_workspace_path.set(str(resolved_workspace))
                    self.v2_project_id.set(resolved_workspace.name)
                except Exception:
                    fallback_path = self._ask_emergency_project_hint()
                    if fallback_path is None:
                        return
            self._v2_set_busy(True, "Импорт AI_EDIT_PACKAGE.zip...")
            self.v2_controller.start_import_package(package_zip, fallback_path=fallback_path)

    def _v2_import_patch(self) -> None:
        if not self.v2_controller.workspace:
            self._show_warning("Нет workspace", "Сначала откройте или создайте v2 workspace.")
            return
        value = filedialog.askopenfilename(
            title="Выберите AI_EDIT_PATCH.json или AI_EDIT_PATCH.zip",
            filetypes=[("AI Edit Patch", "*.json *.zip"), ("All files", "*.*")],
        )
        if value:
            self._v2_set_busy(True, "Импорт AI_EDIT_PATCH...")
            self.v2_controller.start_apply_patch(Path(value))

    def _v2_refresh(self) -> None:
        if not self.v2_controller.workspace:
            self._show_warning("Нет workspace", "Сначала откройте или создайте v2 workspace.")
            return
        self._v2_set_busy(True, "Обновление состояния workspace...")
        self.v2_controller.start_refresh()

    def _v2_run_next(self) -> None:
        if not self.v2_controller.workspace:
            self._show_warning("Нет workspace", "Сначала откройте или создайте v2 workspace.")
            return
        self._v2_set_busy(True, "Запуск next pending render job...")
        self.v2_controller.start_render_next()

    def _v2_run_selected(self) -> None:
        job_id = self._v2_selected_job_id()
        if not job_id:
            self._show_warning("Нет job", "Выберите render job в очереди.")
            return
        self._v2_set_busy(True, f"Запуск render job {job_id}...")
        self.v2_controller.start_render_job(job_id)

    def _v2_cancel_selected(self) -> None:
        job_id = self._v2_selected_job_id()
        if not job_id:
            self._show_warning("Нет job", "Выберите render job в очереди.")
            return
        self.v2_controller.request_cancel(job_id)

    def _v2_retry_selected(self) -> None:
        job_id = self._v2_selected_job_id()
        if not job_id:
            self._show_warning("Нет job", "Выберите failed/cancelled job в очереди.")
            return
        self._v2_set_busy(True, f"Создание retry job для {job_id}...")
        self.v2_controller.start_retry_job(job_id)

    def _v2_on_queue_selected(self, _event=None) -> None:
        job_id = self._v2_selected_job_id()
        if not job_id or not self.v2_controller.workspace:
            return
        try:
            details = show_render_job(self.v2_controller.workspace, job_id)
        except Exception as exc:
            self.v2_status_text.set(f"Не удалось загрузить job details: {exc}")
            return
        self.v2_current_details = details
        self._v2_update_results(details)

    def _v2_on_plan_selected(self, _event=None) -> None:
        plan_id = self._v2_selected_plan_id()
        if not plan_id or not self.v2_controller.workspace:
            return
        try:
            plan = show_plan(self.v2_controller.workspace, plan_id)
        except Exception as exc:
            self.v2_status_text.set(f"Не удалось загрузить plan details: {exc}")
            return
        self._v2_write_text(self.v2_summary, self._format_plan_only_summary(plan))

    def _v2_selected_job_id(self) -> str | None:
        selected = self.v2_queue.selection()
        return selected[0] if selected else None

    def _v2_selected_plan_id(self) -> str | None:
        selected = self.v2_plans.selection()
        return selected[0] if selected else None

    def _v2_open_workspace_dir(self) -> None:
        if self.v2_controller.workspace:
            self._open_path(self.v2_controller.workspace)

    def _owner_project_root_from_sources(self, selected_sources: list[Path]) -> Path | None:
        if len(selected_sources) != 1:
            return None
        candidate = selected_sources[0].resolve()
        if candidate.is_file() and candidate.suffix.lower() == ".zip":
            return candidate.parent
        return None

    def _ask_emergency_project_hint(self) -> Path | None:
        prompt = tk.Toplevel(self)
        prompt.title("Восстановить project link")
        prompt.geometry("540x220")
        prompt.transient(self)
        prompt.grab_set()
        self._register_window(prompt)
        self._apply_theme()

        chosen: dict[str, Path | None] = {"path": None}
        body = ttk.Frame(prompt, padding=16, style="App.TFrame")
        body.pack(fill="both", expand=True)
        ttk.Label(
            body,
            text=(
                "Сохранённая привязка проекта не найдена. "
                "Укажите original project folder или original source ZIP один раз, "
                "и связь с этим AI_EDIT_PACKAGE будет восстановлена."
            ),
            wraplength=490,
            justify="left",
        ).pack(anchor="w")

        actions = ttk.Frame(body, style="App.TFrame")
        actions.pack(fill="x", pady=(18, 0))

        def choose_folder() -> None:
            value = filedialog.askdirectory(title="Выберите original project folder")
            if value:
                chosen["path"] = Path(value)
            prompt.destroy()

        def choose_zip() -> None:
            value = filedialog.askopenfilename(
                title="Выберите original source ZIP",
                filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
            )
            if value:
                chosen["path"] = Path(value)
            prompt.destroy()

        ttk.Button(actions, text="Project Folder", command=choose_folder).pack(side="left")
        ttk.Button(actions, text="Source ZIP", command=choose_zip).pack(side="left", padx=(8, 0))
        ttk.Button(actions, text="Отмена", command=prompt.destroy, style="Secondary.TButton").pack(side="right")
        self.wait_window(prompt)
        return chosen["path"]

    def _v2_open_output_dir(self) -> None:
        if self.v2_current_details:
            self._open_path(Path(self.v2_current_details["output_directory"]))

    def _v2_open_reel(self) -> None:
        if self.v2_current_details:
            self._open_path(Path(self.v2_current_details["reel_path"]))

    def _v2_open_report(self) -> None:
        if self.v2_current_details:
            self._open_path(Path(self.v2_current_details["report_path"]))

    def _v2_open_ffmpeg_command(self) -> None:
        if self.v2_current_details:
            self._open_path(Path(self.v2_current_details["ffmpeg_command_path"]))

    def _hyperframes_choose_project(self) -> None:
        value = filedialog.askdirectory(title="Выберите trusted HyperFrames project folder")
        if value:
            self.hyperframes_project_path.set(value)

    def _hyperframes_adapter(self, *, workspace_root: Path | None = None) -> HyperFramesAdapter:
        return HyperFramesAdapter(
            trusted_prototype_root=_default_hyperframes_project_root(),
            workspace_root=workspace_root,
            project_root=_app_resource_root(),
            cancel_event=self.hyperframes_cancel_event,
        )

    def _hyperframes_set_busy(self, busy: bool, message: str | None = None) -> None:
        state = "disabled" if busy else "normal"
        for button in (
            self.hyperframes_choose_button,
            self.hyperframes_doctor_button,
            self.hyperframes_preview_button,
            self.hyperframes_render_button,
            self.hyperframes_output_button,
        ):
            button.configure(state=state)
        self.hyperframes_cancel_button.configure(state="normal" if busy else "disabled")
        if message:
            self.hyperframes_status_text.set(message)

    def _hyperframes_refresh_doctor(self) -> None:
        self._hyperframes_start("doctor")

    def _hyperframes_open_preview(self) -> None:
        self._hyperframes_start("preview")

    def _hyperframes_render(self) -> None:
        self._hyperframes_start("render")

    def _hyperframes_request_cancel(self) -> None:
        if self.hyperframes_cancel_event is not None:
            self.hyperframes_cancel_event.set()
            self.hyperframes_status_text.set("HyperFrames: cancel requested...")

    def _hyperframes_open_output_dir(self) -> None:
        result = self.hyperframes_last_result or {}
        output_path = result.get("metadata", {}).get("output_path")
        if not output_path:
            self._show_warning("Нет output", "Сначала выполните HyperFrames render.")
            return
        self._open_path(Path(output_path).parent)

    def _hyperframes_start(self, action: str) -> None:
        self.hyperframes_cancel_event = threading.Event()
        project_dir = Path(self.hyperframes_project_path.get()).expanduser()
        workspace_root = self.v2_controller.workspace
        if workspace_root is None:
            candidate = Path(self.v2_workspace_path.get()).expanduser()
            workspace_root = candidate if candidate.exists() else None
        labels = {
            "doctor": "HyperFrames doctor...",
            "preview": "Запуск локального HyperFrames preview...",
            "render": "HyperFrames render MP4...",
        }
        self._hyperframes_set_busy(True, labels.get(action, "HyperFrames..."))
        threading.Thread(target=self._hyperframes_worker, args=(action, project_dir, workspace_root), daemon=True).start()

    def _hyperframes_worker(self, action: str, project_dir: Path, workspace_root: Path | None) -> None:
        try:
            adapter = self._hyperframes_adapter(workspace_root=workspace_root)
            if action == "doctor":
                result = adapter.doctor()
            elif action == "preview":
                result = adapter.open_preview(project_dir)
            elif action == "render":
                result = adapter.render(project_dir)
            else:
                raise HyperFramesLabError(f"Unknown HyperFrames action: {action}")
            self.events.put(("hyperframes_result", {"action": action, "result": result}))
        except Exception as exc:
            self.events.put(("hyperframes_error", str(exc)))

    def _v2_set_busy(self, busy: bool, message: str | None = None) -> None:
        self.v2_busy = busy
        state = "disabled" if busy else "normal"
        for button in (
            self.v2_import_package_button,
            self.v2_import_patch_button,
            self.v2_refresh_button,
            self.v2_run_next_button,
            self.v2_run_selected_button,
            self.v2_retry_button,
        ):
            button.configure(state=state)
        self.v2_cancel_button.configure(state="normal")
        if message:
            self.v2_status_text.set(message)

    def _hyperframes_handle_result(self, payload: dict) -> None:
        action = payload["action"]
        result = payload["result"]
        self.hyperframes_last_result = {
            "action": action,
            "command": result.command,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "metadata": result.metadata,
            "success": result.success,
        }
        self._hyperframes_set_busy(False)
        if action == "doctor":
            checks = result.metadata.get("payload", {}).get("checks", [])
            chrome_status = next((item.get("detail") for item in checks if item.get("name") == "Chrome"), "unknown")
            ffmpeg_status = next((item.get("detail") for item in checks if item.get("name") == "FFmpeg"), "unknown")
            self.hyperframes_runtime_text.set(
                f"Doctor: success={result.success} | returncode={result.returncode} | Chrome={chrome_status} | FFmpeg={ffmpeg_status}"
            )
            self.hyperframes_status_text.set("HyperFrames doctor завершён.")
            return
        if action == "preview":
            studio_url = result.metadata.get("studio_url") or ""
            self.hyperframes_preview_url.set(studio_url)
            self.hyperframes_status_text.set(f"HyperFrames preview готов: {studio_url or 'url not found'}")
            if studio_url:
                webbrowser.open(studio_url)
            return
        if action == "render":
            metadata = result.metadata
            probe = metadata.get("probe", {})
            output_path = metadata.get("output_path", "-")
            sha256 = metadata.get("sha256", "-")
            self.hyperframes_status_text.set(
                "HyperFrames render completed: "
                f"{probe.get('width', '-')}x{probe.get('height', '-')} | "
                f"{probe.get('duration', '-')}s | "
                f"fps={probe.get('fps', '-')} | sha256={sha256}"
            )
            self.hyperframes_runtime_text.set(f"Output: {output_path}")

    def _write_text(self, widget: tk.Text, value: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.configure(state="disabled")

    def _format_import_summary(self, summary: dict) -> str:
        warnings = summary.get("warnings") or []
        validation = summary.get("validation_summary") or {}
        lines = [
            f"Project ID: {summary.get('project_id')}",
            f"Package ID: {summary.get('package_id')}",
            f"Handoff ID: {summary.get('handoff_id')}",
            f"Schema Version: {summary.get('schema_version')}",
            f"Plan ID: {summary.get('plan_id')}",
            f"Plan Version: {summary.get('plan_version')}",
            f"Parent Plan ID: {summary.get('parent_plan_id') or '-'}",
            f"Plan Hash: {summary.get('plan_hash')}",
            f"Assets: {summary.get('asset_count')}",
            f"Operations: {summary.get('operation_count')}",
            f"Warnings: {len(warnings)}",
            f"Validation Summary: {json.dumps(validation, ensure_ascii=False)}",
        ]
        patch = summary.get("patch")
        if patch:
            lines.extend(
                [
                    "",
                    f"Patch ID: {patch.get('patch_id')}",
                    f"Patch SHA-256: {patch.get('patch_sha256')}",
                    f"Base Plan ID: {patch.get('base_plan_id')}",
                    f"Base Plan Hash: {patch.get('base_plan_hash')}",
                    f"Duplicate Apply: {patch.get('duplicate')}",
                ]
            )
        if warnings:
            lines.extend(["", "Warnings:"] + [f"- {item}" for item in warnings])
        return "\n".join(lines)

    def _format_plan_only_summary(self, plan: dict) -> str:
        meta = plan["metadata"]
        payload = plan["payload"]
        return "\n".join(
            [
                f"Plan ID: {meta['edit_plan_id']}",
                f"Plan Version: {meta['plan_version']}",
                f"Parent Plan ID: {meta['parent_plan_id'] or '-'}",
                f"Patch ID: {meta['patch_id'] or '-'}",
                f"Plan Hash: {meta['plan_hash']}",
                f"Assets: {len(payload.get('assets', []))}",
                f"Operations: {len(payload.get('operations', []))}",
                "",
                json.dumps(payload, ensure_ascii=False, indent=2),
            ]
        )

    def _update_v2_snapshot(self, snapshot: dict) -> None:
        self.v2_current_snapshot = snapshot
        self.v2_workspace_path.set(snapshot.get("workspace", self.v2_workspace_path.get()))
        self.v2_project_id.set(snapshot.get("project_id", self.v2_project_id.get()))

        self.v2_queue.delete(*self.v2_queue.get_children())
        for job in snapshot.get("jobs", []):
            self.v2_queue.insert(
                "",
                "end",
                iid=str(job["render_job_id"]),
                values=(job["status"], job["edit_plan_id"], job["attempt_number"], job["updated_at"]),
            )

        self.v2_plans.delete(*self.v2_plans.get_children())
        for plan in snapshot.get("plans", []):
            self.v2_plans.insert(
                "",
                "end",
                iid=str(plan["edit_plan_id"]),
                values=(plan["plan_version"], plan["parent_plan_id"] or "-", plan["plan_hash"]),
            )

        latest_details = snapshot.get("latest_details")
        if latest_details:
            self.v2_current_details = latest_details
            self._v2_update_results(latest_details)

    def _v2_update_results(self, details: dict) -> None:
        self.v2_current_details = details
        job = details["job"]
        plan = details["plan"]
        report = details.get("report") or {}
        self.v2_result_meta.configure(
            text=(
                f"Render Job: {job['render_job_id']}\n"
                f"Status: {job['status']}\n"
                f"Plan ID: {plan['edit_plan_id']}\n"
                f"Plan Version: {int(plan['plan_version'] or 1)}\n"
                f"Output Dir: {details['output_directory']}"
            )
        )

        outputs = report.get("outputs") or []
        first_output = outputs[0] if outputs else {}
        qc_lines = [
            f"Renderer Status: {report.get('renderer_status', '-')}",
            f"Error Code: {report.get('error_code', '-')}",
            f"Failed Stage: {report.get('failed_stage', '-')}",
            f"Error Message: {report.get('error_message', '-')}",
            f"QC Checks: {', '.join(report.get('qc_checks', [])) or '-'}",
            f"Width: {first_output.get('width', '-')}",
            f"Height: {first_output.get('height', '-')}",
            f"FPS: {first_output.get('fps', '-')}",
            f"Duration: {first_output.get('duration_seconds', '-')}",
            f"Audio Present: {first_output.get('audio_present', '-')}",
            f"SHA-256: {first_output.get('sha256', '-')}",
        ]
        self._write_text(self.v2_qc, "\n".join(qc_lines))

        first_frame_path = Path(details["first_frame_path"])
        if first_frame_path.exists():
            try:
                image = Image.open(first_frame_path)
                image.thumbnail((340, 340))
                self.v2_first_frame_image = ImageTk.PhotoImage(image)
                self.v2_first_frame_label.configure(image=self.v2_first_frame_image, text="")
            except Exception as exc:
                self.v2_first_frame_label.configure(image="", text=f"Не удалось открыть first_frame.jpg\n{exc}")
                self.v2_first_frame_image = None
        else:
            self.v2_first_frame_label.configure(image="", text="first_frame.jpg unavailable")
            self.v2_first_frame_image = None

    def _v2_open_voice_studio(self) -> None:
        if self.main_notebook is None:
            return
        self.main_notebook.select(self.voice_tab)
        self.voice_tab_loaded_once = True
        self.voice_status_text.set("Voice Studio открыта во вкладке main app.")
        self._voice_start_refresh()

    def _coordinator_build_draft(self) -> CoordinatorDraft | None:
        raw_text = self.coordinator_brief_text.get("1.0", "end").strip()
        if not raw_text:
            self._show_warning("Нет brief", "Вставьте coordinator brief.")
            return None
        try:
            draft = build_coordinator_draft(raw_text)
        except Exception as exc:
            self.coordinator_status_text.set(f"Coordinator draft error: {exc}")
            self._show_error("Coordinator Bridge", str(exc))
            return None

        self.coordinator_last_draft = draft
        self._write_text(self.coordinator_summary, draft_to_summary(draft))
        self.coordinator_status_text.set(
            "Trusted local draft собран. Можно перенести текст в Voice Studio или сохранить draft в workspace."
        )
        return draft

    def _coordinator_apply_voice_script(self) -> None:
        draft = self.coordinator_last_draft or self._coordinator_build_draft()
        if draft is None:
            return
        self.voice_script_text.delete("1.0", "end")
        self.voice_script_text.insert("1.0", draft.voice_script)
        self.voice_status_text.set(f"Voice script загружен из coordinator draft: {draft.title}")
        self._v2_open_voice_studio()

    def _coordinator_save_draft(self) -> None:
        draft = self.coordinator_last_draft or self._coordinator_build_draft()
        if draft is None:
            return
        workspace = self._voice_workspace()
        draft_dir = workspace / "coordinator_bridge"
        draft_dir.mkdir(parents=True, exist_ok=True)

        payload_path = draft_dir / "coordinator_draft.json"
        summary_path = draft_dir / "coordinator_draft_summary.txt"
        payload_path.write_text(json.dumps(draft_to_payload(draft), ensure_ascii=False, indent=2), encoding="utf-8")
        summary_path.write_text(draft_to_summary(draft), encoding="utf-8")

        self.coordinator_last_saved_dir = draft_dir
        self.coordinator_status_text.set(f"Draft сохранён: {draft_dir}")

    def _coordinator_open_draft_folder(self) -> None:
        if self.coordinator_last_saved_dir is None or not self.coordinator_last_saved_dir.exists():
            self._show_warning("Нет draft folder", "Сначала сохраните coordinator draft.")
            return
        self._open_path(self.coordinator_last_saved_dir)

    def _voice_workspace(self) -> Path:
        if self.v2_controller.workspace:
            return self.v2_controller.workspace
        return Path(self.v2_workspace_path.get()).expanduser().resolve()

    def _voice_current_job_id(self) -> str | None:
        choice = self.voice_job_choice.get()
        return self.voice_jobs_map.get(choice, {}).get("voice_job_id")

    def _voice_selected_take(self) -> dict | None:
        if not self.voice_current_job:
            return None
        for take in self.voice_current_job.get("takes", []):
            if take["voice_take_id"] == self.voice_selected_take_id:
                return take
        return None

    def _voice_audio_path(self, take: dict | None) -> Path | None:
        if not take:
            return None
        candidate = take.get("normalized_audio_path") or take.get("raw_audio_path")
        return Path(candidate) if candidate else None

    def _voice_start_refresh(self) -> None:
        self.voice_status_text.set("Обновление Voice Studio...")
        workspace = self._voice_workspace()
        base_url = self.voice_base_url.get().strip() or "http://127.0.0.1:17493"
        current_job_id = self._voice_current_job_id()
        threading.Thread(target=self._voice_refresh_worker, args=(workspace, base_url, current_job_id), daemon=True).start()

    def _voice_refresh_worker(self, workspace: Path, base_url: str, current_job_id: str | None) -> None:
        try:
            jobs_payload = list_voice_jobs(workspace)
            runtime = voice_health(base_url=base_url)
            profiles = voice_profiles(base_url=base_url)
            job_id = current_job_id
            if not job_id and jobs_payload["jobs"]:
                job_id = str(jobs_payload["jobs"][-1]["voice_job_id"])
            job_details = voice_job_status(workspace, job_id) if job_id else None
            self.events.put(
                (
                    "voice_refreshed",
                    {
                        "workspace": str(workspace),
                        "runtime": runtime,
                        "profiles": profiles,
                        "jobs_payload": jobs_payload,
                        "job_details": job_details,
                        "selected_job_id": job_id,
                    },
                )
            )
        except Exception as exc:
            self.events.put(("voice_error", str(exc)))

    def _voice_start_generate(self) -> None:
        script = self.voice_script_text.get("1.0", "end").strip()
        if not script:
            self._show_warning("Нет текста", "Введите текст для озвучки.")
            return
        self.voice_status_text.set("Генерация 3 реальных Olga takes...")
        workspace = self._voice_workspace()
        target_text = self.voice_target_duration_ms.get().strip()
        threading.Thread(
            target=self._voice_generate_worker,
            args=(
                workspace,
                script,
                self.voice_profile_key.get().strip(),
                self.voice_language.get().strip() or "en-US",
                self.voice_engine.get().strip() or "qwen",
                self.voice_model_size.get().strip() or "0.6B",
                int(target_text) if target_text else None,
                self.voice_base_url.get().strip() or "http://127.0.0.1:17493",
            ),
            daemon=True,
        ).start()

    def _voice_generate_worker(
        self,
        workspace: Path,
        script: str,
        profile_key: str,
        language: str,
        engine: str,
        model_size: str,
        target_duration_ms: int | None,
        base_url: str,
    ) -> None:
        try:
            result = voice_generate(
                workspace,
                profile_key=profile_key,
                text=script,
                language=language,
                takes=3,
                engine=engine,
                model_size=model_size,
                target_duration_ms=target_duration_ms,
                base_url=base_url,
            )
            self.events.put(("voice_generated", result))
        except Exception as exc:
            self.events.put(("voice_error", str(exc)))

    def _voice_on_job_selected(self, _event=None) -> None:
        self._voice_start_refresh()

    def _voice_on_take_selected(self, _event=None) -> None:
        selected = self.voice_takes.selection()
        self.voice_selected_take_id = selected[0] if selected else None
        self._voice_render_take_details()

    def _voice_render_take_details(self) -> None:
        take = self._voice_selected_take()
        if not take:
            self._write_text(self.voice_qc, "Выберите take.")
            return
        qc = take.get("qc") or {}
        alignment = take.get("alignment") or {}
        lines = [
            f"Take ID: {take.get('voice_take_id')}",
            f"Generation ID: {take.get('generation_id')}",
            f"Status: {take.get('status')}",
            f"Duration ms: {take.get('duration_ms')}",
            f"Audio Path: {take.get('normalized_audio_path') or take.get('raw_audio_path') or '-'}",
            f"SHA-256: {take.get('audio_sha256') or '-'}",
            "",
            f"QC Transcript: {qc.get('transcript') or '-'}",
            f"QC Warnings: {', '.join(qc.get('warnings', [])) or '-'}",
            f"QC Errors: {', '.join(qc.get('errors', [])) or '-'}",
            f"Integrated LUFS: {qc.get('integrated_lufs', '-')}",
            f"Peak dBFS: {qc.get('sample_peak_dbfs', '-')}",
            f"Leading Silence ms: {qc.get('leading_silence_ms', '-')}",
            f"Trailing Silence ms: {qc.get('trailing_silence_ms', '-')}",
            "",
            f"Alignment Status: {alignment.get('status', '-')}",
            f"voice_words.json: {alignment.get('artifact_path', '-')}",
            f"subtitle_path: {alignment.get('subtitle_path', '-')}",
            f"karaoke_ass_path: {alignment.get('karaoke_ass_path', '-')}",
        ]
        self._write_text(self.voice_qc, "\n".join(lines))

    def _voice_play_selected_take(self) -> None:
        take = self._voice_selected_take()
        audio_path = self._voice_audio_path(take)
        if audio_path is None or not audio_path.exists():
            self._show_warning("Нет audio", "Для выбранного take не найден WAV.")
            return
        self.voice_playing_path = audio_path
        if winsound is not None:
            winsound.PlaySound(str(audio_path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            self.voice_status_text.set(f"Воспроизведение: {audio_path.name}")
        else:
            self._open_path(audio_path)
            self.voice_status_text.set(f"WAV открыт внешним приложением: {audio_path.name}")

    def _voice_stop_playback(self) -> None:
        if winsound is not None:
            winsound.PlaySound(None, 0)
        self.voice_playing_path = None

    def _voice_open_selected_take(self) -> None:
        take = self._voice_selected_take()
        audio_path = self._voice_audio_path(take)
        if audio_path is None:
            self._show_warning("Нет audio", "Для выбранного take не найден WAV.")
            return
        self._open_path(audio_path)

    def _voice_start_align_selected(self) -> None:
        take = self._voice_selected_take()
        if not take:
            self._show_warning("Нет take", "Выберите take.")
            return
        self.voice_status_text.set(f"Alignment для {take['voice_take_id']}...")
        workspace = self._voice_workspace()
        threading.Thread(target=self._voice_align_worker, args=(workspace, str(take["voice_take_id"])), daemon=True).start()

    def _voice_align_worker(self, workspace: Path, take_id: str) -> None:
        try:
            result = voice_align(workspace, take_id=take_id)
            self.events.put(("voice_aligned", {"take_id": take_id, "result": result}))
        except Exception as exc:
            self.events.put(("voice_error", str(exc)))

    def _voice_start_approve_selected(self) -> None:
        take = self._voice_selected_take()
        if not take:
            self._show_warning("Нет take", "Выберите take.")
            return
        self.voice_status_text.set(f"Approve для {take['voice_take_id']}...")
        notes = self.voice_notes.get("1.0", "end").strip()
        workspace = self._voice_workspace()
        threading.Thread(
            target=self._voice_approve_worker,
            args=(
                workspace,
                str(take["voice_take_id"]),
                int(self.voice_similarity.get()),
                int(self.voice_naturalness.get()),
                int(self.voice_pronunciation.get()),
                int(self.voice_pacing.get()),
                int(self.voice_emotion.get()),
                self.voice_artifacts.get(),
                notes,
            ),
            daemon=True,
        ).start()

    def _voice_approve_worker(
        self,
        workspace: Path,
        take_id: str,
        similarity: int,
        naturalness: int,
        pronunciation: int,
        pacing: int,
        emotion_style_fit: int,
        artifacts: str,
        notes: str,
    ) -> None:
        try:
            result = voice_approve(
                workspace,
                take_id=take_id,
                similarity=similarity,
                naturalness=naturalness,
                pronunciation=pronunciation,
                pacing=pacing,
                emotion_style_fit=emotion_style_fit,
                artifacts=artifacts,
                approve=True,
                notes=notes,
            )
            self.events.put(("voice_approved", {"take_id": take_id, "result": result}))
        except Exception as exc:
            self.events.put(("voice_error", str(exc)))

    def _voice_update_ui(self, payload: dict) -> None:
        runtime = payload["runtime"]
        profiles = payload["profiles"]
        jobs_payload = payload["jobs_payload"]
        self.voice_runtime_text.set(
            "Runtime: "
            f"{runtime.get('status')} | API {runtime.get('api_version')} | model_loaded={runtime.get('model_loaded')} | "
            f"model_size={runtime.get('model_size')} | backend={runtime.get('backend_type')}/{runtime.get('backend_variant')}"
        )
        olga = next((item for item in profiles if str(item.get("name", "")).lower() == "olga"), None)
        if olga:
            self.voice_profile_text.set(
                f"Profile: Olga | id={olga.get('profile_id')} | language={olga.get('language')} | engine={olga.get('default_engine')}"
            )
        else:
            self.voice_profile_text.set("Profile: Olga not found in runtime")

        self.voice_jobs_map = {}
        values: list[str] = []
        for job in jobs_payload["jobs"]:
            label = (
                f"{job['voice_job_id']} | {job['status']} | takes={job.get('take_count', 0)}"
                f" | approved={'yes' if job.get('has_primary_approval') else 'no'}"
            )
            self.voice_jobs_map[label] = job
            values.append(label)
        self.voice_job_combo["values"] = values

        selected_job_id = payload.get("selected_job_id")
        chosen_label = next((label for label, job in self.voice_jobs_map.items() if job["voice_job_id"] == selected_job_id), "")
        if chosen_label:
            self.voice_job_choice.set(chosen_label)
        elif values:
            self.voice_job_choice.set(values[-1])
        else:
            self.voice_job_choice.set("")

        self.voice_current_job = payload.get("job_details")
        self.voice_takes.delete(*self.voice_takes.get_children())
        self.voice_selected_take_id = None
        if self.voice_current_job:
            for take in self.voice_current_job.get("takes", []):
                self.voice_takes.insert(
                    "",
                    "end",
                    iid=str(take["voice_take_id"]),
                    values=(
                        take.get("take_index"),
                        take.get("status"),
                        take.get("duration_ms"),
                        str(take.get("audio_sha256") or "")[:16],
                    ),
                )
            takes = self.voice_current_job.get("takes", [])
            if takes:
                last_take = str(takes[-1]["voice_take_id"])
                self.voice_takes.selection_set(last_take)
                self.voice_selected_take_id = last_take
        self._voice_render_take_details()
        self.voice_status_text.set("Voice Studio готов. Можно прослушать takes и нажать Approve.")

    def _poll_events(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "progress":
                    value, message = payload
                    self.progress_value.set(float(value) * 100)
                    self.status_text.set(str(message))
                elif kind == "log":
                    self._append_log(str(payload))
                elif kind == "done":
                    result = payload
                    assert isinstance(result, BuildResult)
                    self.last_result = result
                    self.last_output = result.archive_path
                    if result.project_root is not None:
                        self.v2_workspace_path.set(str(result.project_root))
                        self.v2_project_id.set(result.project_root.name)
                        self.v2_status_text.set("Project root подготовлен. Позже можно сразу выбрать AI_EDIT_PACKAGE.zip.")
                    self.last_failed_sources = [Path(value) for value in result.failed_sources if value]
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.retry_button.configure(state="normal" if self.last_failed_sources else "disabled")
                    self.open_button.configure(state="normal")
                    coverage_ok = bool(result.validation.get("coverage_ok"))
                    exiftool_status = (
                        result.validation.get("metadata_tool_status", {})
                        .get("exiftool", {})
                        .get("status", "unknown")
                    )
                    self.metadata_status_text.set(f"ExifTool: {exiftool_status}")
                    if coverage_ok:
                        self.status_text.set(f"Готово: {self.last_output.name}")
                        self._show_info("Готово", f"Создан файл:\n{self.last_output}")
                    else:
                        self.status_text.set("Завершено с проблемами покрытия")
                        self._show_warning(
                            "Проверка покрытия не пройдена",
                            f"Архив создан, но coverage_ok=false.\n\n{self.last_output}",
                        )
                    self._show_summary(result)
                elif kind == "error":
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.retry_button.configure(state="normal" if self.last_failed_sources else "disabled")
                    self.status_text.set("Ошибка")
                    self.metadata_status_text.set("ExifTool: unknown")
                    self._append_log(f"ERROR: {payload}")
                    self._show_error("Ошибка", str(payload))
                elif kind == "v2_state":
                    self.v2_status_text.set(f"State: {payload}")
                elif kind in {"workspace_ready", "workspace_refreshed"}:
                    self._v2_set_busy(False, "Workspace готов.")
                    self._update_v2_snapshot(payload)
                    latest_plan = payload.get("latest_plan")
                    if latest_plan and self.v2_controller.workspace:
                        self._write_text(
                            self.v2_summary,
                            self._format_plan_only_summary(show_plan(self.v2_controller.workspace, latest_plan["edit_plan_id"])),
                        )
                elif kind == "package_imported":
                    self._v2_set_busy(False, "Пакет импортирован и preview job поставлен в очередь.")
                    self._write_text(self.v2_summary, self._format_import_summary(payload))
                    self.v2_current_details = payload.get("job_details")
                    if self.v2_current_details:
                        self._v2_update_results(self.v2_current_details)
                    self.v2_controller.start_refresh()
                elif kind == "patch_applied":
                    self._v2_set_busy(False, "Patch применён, создан новый immutable plan и pending render job.")
                    self._write_text(self.v2_summary, self._format_import_summary(payload))
                    self.v2_current_details = payload.get("job_details")
                    if self.v2_current_details:
                        self._v2_update_results(self.v2_current_details)
                    self.v2_controller.start_refresh()
                elif kind == "render_completed":
                    self._v2_set_busy(False, "Preview render completed.")
                    self._v2_update_results(payload)
                    self.v2_controller.start_refresh()
                elif kind == "render_failed":
                    self._v2_set_busy(False, "Preview render failed.")
                    self._v2_update_results(payload)
                    self._show_error("Render failed", payload.get("report", {}).get("error_message", "Unknown render failure."))
                    self.v2_controller.start_refresh()
                elif kind == "render_cancelled":
                    self._v2_set_busy(False, "Render cancelled.")
                    self._v2_update_results(payload)
                    self.v2_controller.start_refresh()
                elif kind == "render_retried":
                    self._v2_set_busy(False, f"Создан retry job: {payload['render_job_id']}")
                    self.v2_controller.start_refresh()
                elif kind == "render_cancel_requested":
                    self.v2_status_text.set(f"Cancel requested for {payload['render_job_id']}")
                    self.v2_controller.start_refresh()
                elif kind == "v2_error":
                    self._v2_set_busy(False, "Ошибка v2 workflow.")
                    self.v2_status_text.set(f"Ошибка: {payload}")
                    self._show_error("V2 workflow error", str(payload))
                elif kind == "voice_refreshed":
                    self._voice_update_ui(payload)
                elif kind == "voice_generated":
                    self.voice_status_text.set(f"Генерация завершена: job {payload['job']['voice_job_id']}")
                    self.voice_job_choice.set("")
                    self._voice_start_refresh()
                elif kind == "voice_aligned":
                    self.voice_status_text.set(f"Alignment готов для {payload['take_id']}")
                    self._voice_start_refresh()
                elif kind == "voice_approved":
                    result = payload["result"]
                    self.voice_status_text.set(f"Approve result: {result['status']} for {payload['take_id']}")
                    self._voice_start_refresh()
                elif kind == "voice_error":
                    self.voice_status_text.set(f"Voice Studio error: {payload}")
                    self._show_error("Voice Studio error", str(payload))
                elif kind == "hyperframes_result":
                    self._hyperframes_handle_result(payload)
                elif kind == "hyperframes_error":
                    self._hyperframes_set_busy(False, "HyperFrames operation failed.")
                    self._show_error("HyperFrames Lab", str(payload))
        except queue.Empty:
            pass
        self.after(120, self._poll_events)

    def _open_result(self) -> None:
        if self.last_output:
            self._open_path(self.last_output.parent)

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            self._show_warning("Нет файла", f"Путь не найден:\n{path}")
            return
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])


if __name__ == "__main__":
    App().mainloop()
