from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from handoff_builder.models import BuildResult, BuilderConfig
from handoff_builder.pipeline import HandoffBuilder
from handoff_builder.v2.gui_controller import V2RunnerController
from handoff_builder.v2.services import show_plan, show_render_job


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI Handoff Builder")
        self.geometry("1200x860")
        self.minsize(980, 720)

        self.sources: list[Path] = []
        self.output_dir = tk.StringVar(value=str(Path.home() / "Desktop"))
        self.project_name = tk.StringVar(value="WEDDING_PROJECT")
        self.include_proxies = tk.BooleanVar(value=True)
        self.progress_value = tk.DoubleVar(value=0.0)
        self.status_text = tk.StringVar(value="Добавьте ZIP, папку или медиафайлы.")
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
        self.v2_status_text = tk.StringVar(value="Откройте или создайте v2 workspace.")
        self.v2_summary_text = ""
        self.v2_qc_text = ""
        self.v2_current_details: dict | None = None
        self.v2_current_snapshot: dict | None = None
        self.v2_first_frame_image: ImageTk.PhotoImage | None = None
        self.v2_busy = False

        self._build_ui()
        self.after(120, self._poll_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="AI Handoff Builder", font=("Arial", 22, "bold")).pack(anchor="w")
        ttk.Label(
            outer,
            text="v1 Prepare Handoff + v2 Local Edit Runner в одном Windows приложении",
        ).pack(anchor="w", pady=(0, 10))

        notebook = ttk.Notebook(outer)
        notebook.pack(fill="both", expand=True)

        self.v1_tab = ttk.Frame(notebook, padding=14)
        self.v2_tab = ttk.Frame(notebook, padding=14)
        notebook.add(self.v1_tab, text="Prepare Handoff (v1)")
        notebook.add(self.v2_tab, text="Local Edit Runner (v2)")

        self._build_v1_tab()
        self._build_v2_tab()

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
        ttk.Button(buttons, text="Добавить ZIP/файлы", command=self._add_files).pack(side="left")
        ttk.Button(buttons, text="Добавить папку", command=self._add_folder).pack(side="left", padx=6)
        ttk.Button(buttons, text="Удалить выбранное", command=self._remove_selected).pack(side="left")
        ttk.Button(buttons, text="Очистить", command=self._clear).pack(side="left", padx=6)

        self.source_list = tk.Listbox(source_frame, height=10)
        self.source_list.pack(fill="both", expand=True, pady=(10, 0))

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
        ttk.Label(settings, text="Параллельных workers:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Spinbox(settings, from_=1, to=2, textvariable=self.worker_count, width=8).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0)
        )
        settings.columnconfigure(1, weight=1)

        ttk.Progressbar(outer, variable=self.progress_value, maximum=100).pack(fill="x")
        ttk.Label(outer, textvariable=self.status_text).pack(anchor="w", pady=(6, 6))

        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.start_button = ttk.Button(actions, text="ПОДГОТОВИТЬ ДЛЯ CHATGPT", command=self._start)
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Отменить", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.retry_button = ttk.Button(actions, text="Повторить failed", command=self._retry_failed, state="disabled")
        self.retry_button.pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(actions, text="Открыть результат", command=self._open_result, state="disabled")
        self.open_button.pack(side="left", padx=8)

        self.log = tk.Text(outer, height=9, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=False, pady=(10, 0))

    def _build_v2_tab(self) -> None:
        outer = self.v2_tab
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)
        outer.rowconfigure(4, weight=1)

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

        ttk.Label(outer, textvariable=self.v2_status_text).grid(row=2, column=0, sticky="w", pady=(8, 8))

        summary_frame = ttk.LabelFrame(outer, text="Import AI Plan / Patch Summary", padding=10)
        summary_frame.grid(row=3, column=0, sticky="nsew")
        summary_frame.columnconfigure(0, weight=1)
        summary_frame.rowconfigure(0, weight=1)
        self.v2_summary = tk.Text(summary_frame, height=10, wrap="word", state="disabled")
        self.v2_summary.grid(row=0, column=0, sticky="nsew")

        lower = ttk.Panedwindow(outer, orient="horizontal")
        lower.grid(row=4, column=0, sticky="nsew", pady=(10, 0))

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

        ttk.Label(queue_frame, text="Render Queue", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w")
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

        ttk.Label(plans_frame, text="Plan Versions", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w")
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

        ttk.Label(results_frame, text="Results / QC", font=("Arial", 11, "bold")).grid(row=0, column=0, sticky="w")
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
                messagebox.showwarning("Нет failed", "Нет файлов для повторной обработки.")
            else:
                messagebox.showwarning("Нет материалов", "Добавьте ZIP, папку или файлы.")
            return
        if not self.project_name.get().strip():
            messagebox.showwarning("Нет названия", "Введите название проекта.")
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
            config = BuilderConfig(
                project_name=self.project_name.get().strip(),
                output_dir=Path(self.output_dir.get()).expanduser(),
                include_video_proxies=self.include_proxies.get(),
                worker_count=max(1, min(2, int(self.worker_count.get()))),
            )
            builder = HandoffBuilder(
                config,
                progress=lambda value, message: self.events.put(("progress", (value, message))),
                log=lambda message: self.events.put(("log", message)),
                project_root=Path(__file__).resolve().parent,
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

        body = ttk.Frame(window, padding=16)
        body.pack(fill="both", expand=True)

        coverage_ok = bool(summary.get("coverage_ok"))
        ttk.Label(
            body,
            text="Coverage OK" if coverage_ok else "Coverage needs attention",
            font=("Arial", 18, "bold"),
            foreground="#1b7f3a" if coverage_ok else "#b2441f",
        ).pack(anchor="w")

        lines = [
            f"{summary.get('source_video_count', 0)} videos found",
            f"{summary.get('video_assets_represented', 0)} videos represented",
            f"{summary.get('source_photo_count', 0)} photos found",
            f"{summary.get('photo_assets_represented', 0)} photos represented",
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

        ttk.Button(body, text="Закрыть", command=window.destroy).pack(anchor="e", pady=(18, 0))

    def _v2_choose_workspace(self) -> None:
        value = filedialog.askdirectory(title="Выберите exact workspace folder")
        if value:
            self.v2_workspace_path.set(value)

    def _v2_create_workspace(self) -> None:
        workspace = Path(self.v2_workspace_path.get()).expanduser()
        project_id = self.v2_project_id.get().strip()
        if not project_id:
            messagebox.showwarning("Нет project ID", "Введите project ID для нового workspace.")
            return
        self._v2_set_busy(True, "Создание v2 workspace...")
        self.v2_controller.start_open_workspace(workspace, project_id=project_id, create=True)

    def _v2_open_workspace(self) -> None:
        workspace = Path(self.v2_workspace_path.get()).expanduser()
        self._v2_set_busy(True, "Открытие v2 workspace...")
        self.v2_controller.start_open_workspace(workspace, create=False)

    def _v2_import_package(self) -> None:
        if not self.v2_controller.workspace:
            messagebox.showwarning("Нет workspace", "Сначала откройте или создайте v2 workspace.")
            return
        value = filedialog.askopenfilename(
            title="Выберите AI_EDIT_PACKAGE.zip",
            filetypes=[("AI Edit Package", "*.zip"), ("All files", "*.*")],
        )
        if value:
            self._v2_set_busy(True, "Импорт AI_EDIT_PACKAGE.zip...")
            self.v2_controller.start_import_package(Path(value))

    def _v2_import_patch(self) -> None:
        if not self.v2_controller.workspace:
            messagebox.showwarning("Нет workspace", "Сначала откройте или создайте v2 workspace.")
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
            messagebox.showwarning("Нет workspace", "Сначала откройте или создайте v2 workspace.")
            return
        self._v2_set_busy(True, "Обновление состояния workspace...")
        self.v2_controller.start_refresh()

    def _v2_run_next(self) -> None:
        if not self.v2_controller.workspace:
            messagebox.showwarning("Нет workspace", "Сначала откройте или создайте v2 workspace.")
            return
        self._v2_set_busy(True, "Запуск next pending render job...")
        self.v2_controller.start_render_next()

    def _v2_run_selected(self) -> None:
        job_id = self._v2_selected_job_id()
        if not job_id:
            messagebox.showwarning("Нет job", "Выберите render job в очереди.")
            return
        self._v2_set_busy(True, f"Запуск render job {job_id}...")
        self.v2_controller.start_render_job(job_id)

    def _v2_cancel_selected(self) -> None:
        job_id = self._v2_selected_job_id()
        if not job_id:
            messagebox.showwarning("Нет job", "Выберите render job в очереди.")
            return
        self.v2_controller.request_cancel(job_id)

    def _v2_retry_selected(self) -> None:
        job_id = self._v2_selected_job_id()
        if not job_id:
            messagebox.showwarning("Нет job", "Выберите failed/cancelled job в очереди.")
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
                    self.last_failed_sources = [Path(value) for value in result.failed_sources if value]
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.retry_button.configure(state="normal" if self.last_failed_sources else "disabled")
                    self.open_button.configure(state="normal")
                    coverage_ok = bool(result.validation.get("coverage_ok"))
                    if coverage_ok:
                        self.status_text.set(f"Готово: {self.last_output.name}")
                        messagebox.showinfo("Готово", f"Создан файл:\n{self.last_output}")
                    else:
                        self.status_text.set("Завершено с проблемами покрытия")
                        messagebox.showwarning(
                            "Проверка покрытия не пройдена",
                            f"Архив создан, но coverage_ok=false.\n\n{self.last_output}",
                        )
                    self._show_summary(result)
                elif kind == "error":
                    self.start_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.retry_button.configure(state="normal" if self.last_failed_sources else "disabled")
                    self.status_text.set("Ошибка")
                    self._append_log(f"ERROR: {payload}")
                    messagebox.showerror("Ошибка", str(payload))
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
                    messagebox.showerror("Render failed", payload.get("report", {}).get("error_message", "Unknown render failure."))
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
                    messagebox.showerror("V2 workflow error", str(payload))
        except queue.Empty:
            pass
        self.after(120, self._poll_events)

    def _open_result(self) -> None:
        if self.last_output:
            self._open_path(self.last_output.parent)

    def _open_path(self, path: Path) -> None:
        if not path.exists():
            messagebox.showwarning("Нет файла", f"Путь не найден:\n{path}")
            return
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(path)])


if __name__ == "__main__":
    App().mainloop()
