from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from handoff_builder.models import BuildResult, BuilderConfig
from handoff_builder.pipeline import HandoffBuilder


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("AI Handoff Builder v1")
        self.geometry("860x680")
        self.minsize(760, 580)

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

        self._build_ui()
        self.after(120, self._poll_events)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(
            outer,
            text="AI Handoff Builder",
            font=("Arial", 20, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            outer,
            text="ZIP / папка / файлы → один проверенный PROJECT_ANALYSIS_HANDOFF.zip",
        ).pack(anchor="w", pady=(0, 14))

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
        ttk.Entry(settings, textvariable=self.project_name).grid(
            row=0, column=1, sticky="ew", padx=(8, 0)
        )
        ttk.Label(settings, text="Куда сохранить:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(settings, textvariable=self.output_dir).grid(
            row=1, column=1, sticky="ew", padx=(8, 0), pady=(8, 0)
        )
        ttk.Button(settings, text="Выбрать", command=self._choose_output).grid(
            row=1, column=2, padx=(8, 0), pady=(8, 0)
        )
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

        ttk.Progressbar(
            outer,
            variable=self.progress_value,
            maximum=100,
        ).pack(fill="x")
        ttk.Label(outer, textvariable=self.status_text).pack(anchor="w", pady=(6, 6))

        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        self.start_button = ttk.Button(
            actions,
            text="ПОДГОТОВИТЬ ДЛЯ CHATGPT",
            command=self._start,
        )
        self.start_button.pack(side="left")
        self.cancel_button = ttk.Button(
            actions,
            text="Отменить",
            command=self._cancel,
            state="disabled",
        )
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.retry_button = ttk.Button(
            actions,
            text="Повторить failed",
            command=self._retry_failed,
            state="disabled",
        )
        self.retry_button.pack(side="left", padx=(8, 0))
        self.open_button = ttk.Button(
            actions,
            text="Открыть результат",
            command=self._open_result,
            state="disabled",
        )
        self.open_button.pack(side="left", padx=8)

        self.log = tk.Text(outer, height=9, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=False, pady=(10, 0))

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
                progress=lambda value, message: self.events.put(
                    ("progress", (value, message))
                ),
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
                    self.retry_button.configure(
                        state="normal" if self.last_failed_sources else "disabled"
                    )
                    self.open_button.configure(state="normal")
                    coverage_ok = bool(result.validation.get("coverage_ok"))
                    if coverage_ok:
                        self.status_text.set(f"Готово: {self.last_output.name}")
                        messagebox.showinfo(
                            "Готово",
                            f"Создан файл:\n{self.last_output}",
                        )
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
                    self.retry_button.configure(
                        state="normal" if self.last_failed_sources else "disabled"
                    )
                    self.status_text.set("Ошибка")
                    self._append_log(f"ERROR: {payload}")
                    messagebox.showerror("Ошибка", str(payload))
        except queue.Empty:
            pass
        self.after(120, self._poll_events)

    def _open_result(self) -> None:
        if not self.last_output:
            return
        if os.name == "nt":
            os.startfile(self.last_output.parent)  # type: ignore[attr-defined]
        else:
            import subprocess
            subprocess.Popen(["xdg-open", str(self.last_output.parent)])


if __name__ == "__main__":
    App().mainloop()
