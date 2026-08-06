from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import APP_BUNDLE_NAME, APP_DISPLAY_NAME, APP_VERSION, DEFAULT_PROJECTS_DIRNAME
from .ingest import HandoffLightIngestService
from .packager import HandoffLightPackager
from .project_store import ProjectStore


class HandoffLightApp:
    def __init__(self, root: tk.Tk, *, projects_root: Path | None = None) -> None:
        self.root = root
        self.projects_root = projects_root or (Path.home() / "Documents" / DEFAULT_PROJECTS_DIRNAME)
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.store = ProjectStore(self.projects_root)
        self.ingest_service = HandoffLightIngestService(self.store)
        self.packager = HandoffLightPackager(self.store)
        self.current_project = None
        self._event_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._busy = False
        self.status_vars = {
            "project": tk.StringVar(value="No project open"),
            "registered_assets": tk.StringVar(value="0"),
            "new_assets": tk.StringVar(value="0"),
            "duplicates": tk.StringVar(value="0"),
            "missing": tk.StringVar(value="0"),
            "last_version": tk.StringVar(value="V000"),
            "next_version": tk.StringVar(value="V001"),
            "status": tk.StringVar(value="Ready"),
        }
        self._build_ui()
        self.root.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        self.root.title(f"{APP_BUNDLE_NAME} - {APP_DISPLAY_NAME}")
        self.root.geometry("700x360")
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)
        header = ttk.Label(outer, text=f"{APP_DISPLAY_NAME} {APP_VERSION}", font=("Segoe UI", 15, "bold"))
        header.pack(anchor="w")
        buttons = ttk.Frame(outer)
        buttons.pack(fill="x", pady=(12, 12))
        self.new_button = ttk.Button(buttons, text="New Project", command=self.new_project)
        self.open_button = ttk.Button(buttons, text="Open Project", command=self.open_project)
        self.add_button = ttk.Button(buttons, text="Add Material", command=self.add_material)
        self.build_button = ttk.Button(buttons, text="Build Handoff ZIP", command=self.build_handoff)
        self.package_button = ttk.Button(buttons, text="Open Package Folder", command=self.open_package_folder)
        for widget in (self.new_button, self.open_button, self.add_button, self.build_button, self.package_button):
            widget.pack(side="left", padx=(0, 8))
        summary = ttk.LabelFrame(outer, text="Status", padding=12)
        summary.pack(fill="both", expand=True)
        rows = [
            ("Project", "project"),
            ("Registered assets", "registered_assets"),
            ("New assets since previous handoff", "new_assets"),
            ("Duplicates skipped", "duplicates"),
            ("Missing files", "missing"),
            ("Last handoff version", "last_version"),
            ("Next handoff version", "next_version"),
        ]
        for index, (label, key) in enumerate(rows):
            ttk.Label(summary, text=label).grid(row=index, column=0, sticky="w", padx=(0, 16), pady=4)
            ttk.Label(summary, textvariable=self.status_vars[key]).grid(row=index, column=1, sticky="w", pady=4)
        ttk.Label(summary, text="Activity").grid(row=len(rows), column=0, sticky="w", padx=(0, 16), pady=(12, 4))
        ttk.Label(summary, textvariable=self.status_vars["status"], wraplength=480).grid(row=len(rows), column=1, sticky="w", pady=(12, 4))
        summary.columnconfigure(1, weight=1)
        self._update_button_state()

    def new_project(self) -> None:
        if self._busy:
            return
        project_name = simpledialog.askstring("New Project", "Project name:", parent=self.root)
        if not project_name:
            return
        try:
            self.current_project = self.store.create_project(project_name)
        except FileExistsError:
            messagebox.showerror("Project Exists", "A project with this name already exists.")
            return
        self.status_vars["status"].set(f"Created project at {self.current_project.root}")
        self._refresh_status()

    def open_project(self) -> None:
        if self._busy:
            return
        selected = filedialog.askdirectory(initialdir=self.projects_root, title="Open Handoff Light Project")
        if not selected:
            return
        try:
            self.current_project = self.store.open_project(Path(selected))
        except Exception as exc:
            messagebox.showerror("Open Project Failed", str(exc))
            return
        self.status_vars["status"].set(f"Opened project {self.current_project.project_name}")
        self._refresh_status()

    def add_material(self) -> None:
        if self._busy:
            return
        if self.current_project is None:
            messagebox.showinfo("No Project", "Create or open a project first.")
            return
        selections = list(filedialog.askopenfilenames(title="Add Material"))
        folder = filedialog.askdirectory(title="Add Folder (optional)")
        paths = [Path(item) for item in selections]
        if folder:
            paths.append(Path(folder))
        if not paths:
            return
        self._run_background("Scanning and ingesting material...", self.ingest_service.ingest, self.current_project, paths)

    def build_handoff(self) -> None:
        if self._busy:
            return
        if self.current_project is None:
            messagebox.showinfo("No Project", "Create or open a project first.")
            return
        self._run_background("Building handoff ZIP...", self.packager.build_handoff_zip, self.current_project)

    def open_package_folder(self) -> None:
        if self.current_project is None:
            messagebox.showinfo("No Project", "Create or open a project first.")
            return
        self.current_project.handoffs_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(self.current_project.handoffs_dir)  # type: ignore[attr-defined]
        except AttributeError:
            pass

    def _run_background(self, status: str, func, *args) -> None:
        self._busy = True
        self.status_vars["status"].set(status)
        self._update_button_state()

        def worker() -> None:
            try:
                result = func(*args)
                self._event_queue.put(("success", result))
            except Exception as exc:  # pragma: no cover - UI surface
                self._event_queue.put(("error", exc))

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()

    def _poll_queue(self) -> None:
        try:
            while True:
                event, payload = self._event_queue.get_nowait()
                self._busy = False
                if event == "success":
                    if self.current_project is not None:
                        self.current_project = self.store.open_project(self.current_project.root)
                    if isinstance(payload, Path):
                        self.status_vars["status"].set(f"Built {payload.name}")
                    else:
                        self.status_vars["status"].set("Ingestion complete")
                    self._refresh_status()
                else:
                    self.status_vars["status"].set(f"Failed: {payload}")
                    messagebox.showerror("Handoff Light", str(payload))
                self._update_button_state()
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _refresh_status(self) -> None:
        if self.current_project is None:
            return
        report = self.current_project.last_ingest_report or {}
        self.status_vars["project"].set(self.current_project.project_name)
        self.status_vars["registered_assets"].set(str(len(self.current_project.assets)))
        self.status_vars["new_assets"].set(str(len(report.get("added_assets", []))))
        self.status_vars["duplicates"].set(str(len(report.get("duplicate_assets", []))))
        self.status_vars["missing"].set(str(sum(1 for asset in self.current_project.assets if asset.missing)))
        self.status_vars["last_version"].set(f"V{self.current_project.last_handoff_version:03d}")
        self.status_vars["next_version"].set(f"V{self.current_project.last_handoff_version + 1:03d}")
        self._update_button_state()

    def _update_button_state(self) -> None:
        state = "disabled" if self._busy else "normal"
        self.new_button.configure(state=state)
        self.open_button.configure(state=state)
        has_project = self.current_project is not None
        self.add_button.configure(state=state if has_project else "disabled")
        self.build_button.configure(state=state if has_project else "disabled")
        self.package_button.configure(state=state if has_project else "disabled")


def launch_handoff_light(projects_root: Path | None = None) -> HandoffLightApp:
    root = tk.Tk()
    app = HandoffLightApp(root, projects_root=projects_root)
    root.mainloop()
    return app
