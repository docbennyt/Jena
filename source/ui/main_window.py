from __future__ import annotations

import json
import os
import queue
import threading
import tkinter as tk
from pathlib import Path, PurePosixPath
from tkinter import filedialog, ttk

try:
    import customtkinter as ctk
except ImportError:  # pragma: no cover - fallback for development without dependency
    ctk = None

from core.models import Finding, RiskLevel
from core.compression import ArchiveFormat, find_7zip_executable
from core.explorer import open_in_explorer
from core.file_actions import build_delete_plan, permanently_delete_paths, recycle_paths
from core.operations import recycle_findings, restore_from_manifest
from core.project_library import (
    ProjectRecord,
    ProjectState,
    analyze_and_cache_project,
    archive_recommendations,
    archive_project,
    archived_project_records,
    discover_project_library,
    project_record_from_cache,
    quick_discover_project_roots,
    restore_project,
    set_project_state,
    stable_library_id,
    state_display,
)
from core.preview import PreviewService
from core.scanner import ScanOptions, Scanner
from core.safety import can_move_to_review, review_folder
from core.tasks import TaskEvent, TaskManager, TaskState
from core.workstation import build_workstation_summary
from storage.database import Database
from storage.settings import Settings
from ui.dialogs import confirm_recycle, show_error, show_info
from utils.formatting import format_bytes, format_date
from utils.disk import drive_usage
from utils.labels import risk_label, tag_label, tags_label
from utils.paths import data_dir, known_folder
from version import APP_NAME, APP_VERSION


class StoragePilotApp:
    def __init__(self) -> None:
        self.db = Database()
        self.settings = Settings()
        self.queue: queue.Queue = queue.Queue()
        self.task_manager = TaskManager(self.queue)
        self.cancel_event = threading.Event()
        self.scan_thread: threading.Thread | None = None
        self.findings: list[Finding] = self.db.latest_findings()
        self.filtered_findings: list[Finding] = list(self.findings)
        self.download_findings: list[Finding] = []
        self.project_records: list[ProjectRecord] = []
        self.project_tasks: set[str] = set()
        self.preview_service = PreviewService(data_dir() / "preview-cache")
        self.preview_task_id: str | None = None
        self.preview_photo = None
        self.delete_task_id: str | None = None
        self.selected_ids: set[str] = set()

        if ctk:
            ctk.set_appearance_mode(self.settings.get("theme"))
            ctk.set_default_color_theme("blue")
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("1120x720")
        self.root.minsize(960, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self._build()
        self.refresh_dashboard()
        self.refresh_findings()
        self.poll_queue()

    def run(self) -> None:
        self.root.mainloop()

    def _frame(self, parent, **kwargs):
        if ctk:
            return ctk.CTkFrame(parent, corner_radius=8, **kwargs)
        return ttk.Frame(parent, padding=10)

    def _button(self, parent, text: str, command, **kwargs):
        if ctk:
            return ctk.CTkButton(parent, text=text, command=command, corner_radius=6, **kwargs)
        return ttk.Button(parent, text=text, command=command)

    def _label(self, parent, text: str, **kwargs):
        if ctk:
            return ctk.CTkLabel(parent, text=text, **kwargs)
        return ttk.Label(parent, text=text)

    def _build(self) -> None:
        self.root.columnconfigure(1, weight=1)
        self.root.rowconfigure(0, weight=1)

        nav = self._frame(self.root, width=170)
        nav.grid(row=0, column=0, sticky="ns")
        nav.grid_propagate(False)
        self._label(nav, text=APP_NAME, font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=16, pady=(18, 8))
        self._label(nav, text=f"v{APP_VERSION}", font=("Segoe UI", 11)).pack(anchor="w", padx=16, pady=(0, 18))
        for label, page in [
            ("Home", "dashboard"),
            ("Downloads", "downloads"),
            ("Projects", "projects"),
            ("Storage", "findings"),
            ("Activity", "review"),
            ("Settings", "settings"),
        ]:
            self._button(nav, label, lambda p=page: self.show_page(p)).pack(fill="x", padx=12, pady=4)

        self.content = self._frame(self.root)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(0, weight=1)

        self.pages: dict[str, tk.Widget] = {}
        self._build_dashboard()
        self._build_downloads()
        self._build_findings()
        self._build_projects()
        self._build_review()
        self._build_settings()

        self.status = tk.StringVar(value="Ready")
        status_bar = ttk.Label(self.root, textvariable=self.status, anchor="w", padding=6)
        status_bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.show_page("dashboard")

    def _build_dashboard(self) -> None:
        page = self._frame(self.content)
        self.pages["dashboard"] = page
        header = self._label(page, text="I need space.", font=("Segoe UI", 22, "bold"))
        header.pack(anchor="w", padx=18, pady=(18, 4))
        self._label(page, text="Nothing is permanently deleted automatically.", font=("Segoe UI", 13)).pack(anchor="w", padx=18)
        self.drive_var = tk.StringVar(value="Checking C: drive...")
        ttk.Label(page, textvariable=self.drive_var, font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=18, pady=(12, 0))
        self.target_var = tk.StringVar(value="")
        ttk.Label(page, textvariable=self.target_var, font=("Segoe UI", 11)).pack(anchor="w", padx=18, pady=(4, 0))

        cards = ttk.Frame(page)
        cards.pack(fill="x", padx=18, pady=18)
        self.metric_vars = {}
        for key, title in [
            ("recoverable", "Potentially Recoverable"),
            ("dev_cache", "Development Cache"),
            ("duplicate", "Duplicate Space"),
            ("findings", "Findings"),
        ]:
            frame = ttk.LabelFrame(cards, text=title, padding=12)
            frame.pack(side="left", fill="x", expand=True, padx=5)
            var = tk.StringVar(value="0 B")
            self.metric_vars[key] = var
            ttk.Label(frame, textvariable=var, font=("Segoe UI", 17, "bold")).pack(anchor="w")

        actions = ttk.LabelFrame(page, text="Recovery", padding=12)
        actions.pack(fill="x", padx=18, pady=8)
        self._button(actions, "Build a recovery plan", self.build_recovery_plan).pack(side="left", padx=5)
        self._button(actions, "Scan Downloads", lambda: self.start_scan(known_folder("Downloads"), "Downloads")).pack(side="left", padx=5)
        self._button(actions, "Choose Folder", self.choose_folder).pack(side="left", padx=5)
        self.cancel_button = self._button(actions, "Cancel Scan", self.cancel_scan)
        self.cancel_button.pack(side="left", padx=5)
        self.progress = ttk.Progressbar(page, mode="indeterminate")
        self.progress.pack(fill="x", padx=18, pady=8)

        self.folder_table = ttk.Treeview(page, columns=("size", "findings", "recoverable"), show="headings", height=5)
        for column, title in [("size", "Folder"), ("findings", "Findings"), ("recoverable", "Potential cleanup")]:
            self.folder_table.heading(column, text=title)
        self.folder_table.pack(fill="x", padx=18, pady=12)

        planner = ttk.LabelFrame(page, text="Recommended next steps", padding=12)
        planner.pack(fill="both", expand=True, padx=18, pady=8)
        self.opportunity_table = ttk.Treeview(
            planner,
            columns=("gain", "risk", "effort", "confidence", "why", "recovery"),
            show="tree headings",
            height=6,
        )
        self.opportunity_table.heading("#0", text="Action")
        self.opportunity_table.column("#0", width=220, anchor="w")
        for column, title, width in [
            ("gain", "Space", 90),
            ("risk", "Risk", 80),
            ("effort", "Effort", 110),
            ("confidence", "Confidence", 90),
            ("why", "Why", 300),
            ("recovery", "Recovery path", 260),
        ]:
            self.opportunity_table.heading(column, text=title)
            self.opportunity_table.column(column, width=width, anchor="w")
        self.opportunity_table.pack(fill="both", expand=True)

        warnings = ttk.LabelFrame(page, text="Local-only warnings", padding=12)
        warnings.pack(fill="x", padx=18, pady=8)
        self.local_only_var = tk.StringVar(value="No protected local-only items found in the latest scan.")
        ttk.Label(warnings, textvariable=self.local_only_var, wraplength=840).pack(anchor="w")

    def _build_downloads(self) -> None:
        page = self._frame(self.content)
        self.pages["downloads"] = page
        ttk.Label(page, text="Deal with the mess.", font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=18, pady=(18, 4))
        ttk.Label(page, text="Downloads are grouped by type. Recycle only the items you select.").pack(anchor="w", padx=18)
        actions = ttk.Frame(page)
        actions.pack(fill="x", padx=18, pady=12)
        self._button(actions, "Scan Downloads", lambda: self.start_scan(known_folder("Downloads"), "Downloads")).pack(side="left", padx=(0, 8))
        self._button(actions, "Recycle Selected", self.recycle_selected_downloads).pack(side="left")

        body = ttk.PanedWindow(page, orient="horizontal")
        body.pack(fill="both", expand=True, padx=18, pady=8)
        category_frame = ttk.LabelFrame(body, text="Categories", padding=8)
        file_frame = ttk.LabelFrame(body, text="Files", padding=8)
        preview_frame = ttk.LabelFrame(body, text="Preview", padding=8)
        body.add(category_frame, weight=1)
        body.add(file_frame, weight=3)
        body.add(preview_frame, weight=2)

        self.download_category_table = ttk.Treeview(category_frame, columns=("count", "size"), show="tree headings", height=8)
        self.download_category_table.heading("#0", text="Category")
        self.download_category_table.heading("count", text="Items")
        self.download_category_table.heading("size", text="Size")
        self.download_category_table.column("#0", width=150)
        self.download_category_table.pack(fill="both", expand=True)
        self.download_category_table.bind("<<TreeviewSelect>>", lambda _event: self.populate_download_files())

        self.download_file_table = ttk.Treeview(
            file_frame,
            columns=("name", "size", "modified", "reason", "path"),
            show="headings",
            selectmode="extended",
        )
        for column, title, width in [
            ("name", "Name", 180),
            ("size", "Size", 90),
            ("modified", "Modified", 110),
            ("reason", "Why review", 260),
            ("path", "Path", 420),
        ]:
            self.download_file_table.heading(column, text=title)
            self.download_file_table.column(column, width=width, anchor="w")
        self.download_file_table.pack(fill="both", expand=True)
        self.download_file_table.bind("<<TreeviewSelect>>", lambda _event: self.preview_selected_download())
        self.download_file_table.bind("<Delete>", lambda event: self.delete_key_selected_downloads(event, permanent=False))
        self.download_file_table.bind("<Shift-Delete>", lambda event: self.delete_key_selected_downloads(event, permanent=True))
        self.download_file_table.bind("<Button-3>", lambda event: self.show_file_context_menu(event, "downloads"))
        self.download_detail_var = tk.StringVar(value="Select a category to review Downloads.")
        ttk.Label(file_frame, textvariable=self.download_detail_var, wraplength=720).pack(anchor="w", pady=(8, 0))
        self.preview_title_var = tk.StringVar(value="Select a file.")
        self.preview_image_label = ttk.Label(preview_frame)
        self.preview_image_label.pack(fill="both", expand=False)
        ttk.Label(preview_frame, textvariable=self.preview_title_var, wraplength=320, justify="left").pack(fill="x", expand=False, pady=(8, 0))
        self.archive_browser_frame = ttk.Frame(preview_frame)
        self.archive_browser = ttk.Treeview(
            self.archive_browser_frame,
            columns=("size",),
            show="tree headings",
            height=12,
        )
        self.archive_browser.heading("#0", text="Archive contents")
        self.archive_browser.heading("size", text="Size")
        self.archive_browser.column("#0", width=230, anchor="w")
        self.archive_browser.column("size", width=80, anchor="e")
        archive_scroll = ttk.Scrollbar(self.archive_browser_frame, orient="vertical", command=self.archive_browser.yview)
        self.archive_browser.configure(yscrollcommand=archive_scroll.set)
        self.archive_browser.pack(side="left", fill="both", expand=True)
        archive_scroll.pack(side="right", fill="y")

    def _build_findings(self) -> None:
        page = self._frame(self.content)
        self.pages["findings"] = page
        top = ttk.Frame(page)
        top.pack(fill="x", padx=12, pady=12)
        self.search_var = tk.StringVar()
        search = ttk.Entry(top, textvariable=self.search_var)
        search.pack(side="left", fill="x", expand=True, padx=(0, 8))
        search.bind("<KeyRelease>", lambda _event: self.apply_filters())
        self.risk_var = tk.StringVar(value="All")
        risk = ttk.Combobox(top, textvariable=self.risk_var, values=["All", *[risk_label(r) for r in RiskLevel]], state="readonly", width=24)
        risk.pack(side="left")
        risk.bind("<<ComboboxSelected>>", lambda _event: self.apply_filters())

        columns = ("name", "size", "risk", "category", "modified", "path")
        self.findings_table = ttk.Treeview(page, columns=columns, show="headings", selectmode="extended")
        for column, title, width in [
            ("name", "Name", 180), ("size", "Size", 90), ("risk", "Risk", 150),
            ("category", "Category", 150), ("modified", "Modified", 110), ("path", "Path", 420),
        ]:
            self.findings_table.heading(column, text=title, command=lambda c=column: self.sort_findings(c))
            self.findings_table.column(column, width=width, anchor="w")
        self.findings_table.pack(fill="both", expand=True, padx=12, pady=(0, 8))
        self.findings_table.bind("<<TreeviewSelect>>", lambda _event: self.update_selection_summary())
        self.findings_table.bind("<<TreeviewSelect>>", lambda _event: (self.update_selection_summary(), self.preview_selected_finding()))
        self.findings_table.bind("<Delete>", lambda event: self.delete_key_selected_findings(event, permanent=False))
        self.findings_table.bind("<Shift-Delete>", lambda event: self.delete_key_selected_findings(event, permanent=True))
        self.findings_table.bind("<Button-3>", lambda event: self.show_file_context_menu(event, "storage"))

        bottom = ttk.Frame(page)
        bottom.pack(fill="x", padx=12, pady=8)
        self.selection_var = tk.StringVar(value="No items selected")
        ttk.Label(bottom, textvariable=self.selection_var).pack(side="left")
        self._button(bottom, "Move to Recycle Bin", self.recycle_selected).pack(side="right")
        self.storage_preview_var = tk.StringVar(value="Select a file to preview.")
        ttk.Label(page, textvariable=self.storage_preview_var, wraplength=900, justify="left").pack(fill="x", padx=12, pady=(0, 8))

    def _build_projects(self) -> None:
        page = self._frame(self.content)
        self.pages["projects"] = page
        ttk.Label(page, text="What am I actually working on?", font=("Segoe UI", 20, "bold")).pack(anchor="w", padx=12, pady=(12, 4))
        library_row = ttk.Frame(page)
        library_row.pack(fill="x", padx=12, pady=8)
        self.project_library_var = tk.StringVar(value=self.settings.get("project_library_root") or "Choose your Project Library")
        ttk.Label(library_row, textvariable=self.project_library_var).pack(side="left", fill="x", expand=True)
        self._button(library_row, "Choose Project Library", self.choose_project_library).pack(side="right", padx=4)
        self._button(library_row, "Refresh", self.refresh_project_library).pack(side="right", padx=4)
        self._button(library_row, "Cancel", self.cancel_project_jobs).pack(side="right", padx=4)
        self.project_notice_var = tk.StringVar(value="")
        ttk.Label(page, textvariable=self.project_notice_var, wraplength=900).pack(anchor="w", padx=12)

        self.projects_table = ttk.Treeview(
            page,
            columns=("name", "state", "size", "regenerable", "modified", "candidate", "type", "path"),
            show="headings",
            selectmode="browse",
        )
        for column, title in [
            ("name", "Project"),
            ("state", "State"),
            ("size", "Size"),
            ("regenerable", "Dependencies/Caches"),
            ("modified", "Last changed"),
            ("candidate", "Archive candidate"),
            ("type", "Type"),
            ("path", "Path"),
        ]:
            self.projects_table.heading(column, text=title)
        self.projects_table.pack(fill="both", expand=True, padx=12, pady=12)
        self.projects_table.bind("<<TreeviewSelect>>", lambda _event: self.show_project_detail())
        controls = ttk.Frame(page)
        controls.pack(fill="x", padx=12, pady=(0, 8))
        for label, state in [
            ("Mark Active", ProjectState.ACTIVE),
            ("Mark Paused", ProjectState.PAUSED),
            ("Mark Inactive", ProjectState.INACTIVE),
            ("Never Archive", ProjectState.NEVER_ARCHIVE),
        ]:
            self._button(controls, label, lambda s=state: self.set_selected_project_state(s)).pack(side="left", padx=4)
        self._button(controls, "Open in Explorer", self.open_selected_project_in_explorer).pack(side="left", padx=14)
        self._button(controls, "Archive", self.archive_selected_project).pack(side="left", padx=14)
        self._button(controls, "Restore", self.restore_selected_project_archive).pack(side="left", padx=4)
        self._button(controls, "Archive Candidates", self.show_archive_candidates).pack(side="left", padx=4)
        self.project_detail_var = tk.StringVar(value="Choose a Project Library to discover projects.")
        ttk.Label(page, textvariable=self.project_detail_var, wraplength=900).pack(anchor="w", padx=12, pady=(0, 12))

    def _build_review(self) -> None:
        page = self._frame(self.content)
        self.pages["review"] = page
        ttk.Label(page, text="Activity", font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=12, pady=12)
        self.review_table = ttk.Treeview(page, columns=("date", "items", "mode", "manifest"), show="headings")
        for column, title in [("date", "Operation"), ("items", "Items"), ("mode", "Mode"), ("manifest", "Manifest")]:
            self.review_table.heading(column, text=title)
        self.review_table.pack(fill="both", expand=True, padx=12, pady=8)
        self._button(page, "Restore Selected Operation", self.restore_selected).pack(anchor="e", padx=12, pady=8)

    def _build_settings(self) -> None:
        page = self._frame(self.content)
        self.pages["settings"] = page
        ttk.Label(page, text="Settings", font=("Segoe UI", 16, "bold")).pack(anchor="w", padx=12, pady=12)
        ttk.Label(page, text="Jena runs locally and offline. Normal delete actions move items to the Windows Recycle Bin.").pack(anchor="w", padx=12, pady=8)
        target_row = ttk.Frame(page)
        target_row.pack(fill="x", padx=12, pady=8)
        ttk.Label(target_row, text="Keep at least this much free on C:").pack(side="left")
        self.target_free_var = tk.StringVar(value=str(self.settings.get("target_free_gb")))
        ttk.Entry(target_row, textvariable=self.target_free_var, width=8).pack(side="left", padx=8)
        ttk.Label(target_row, text="GB").pack(side="left")
        self._button(target_row, "Save Target", self.save_target_free_space).pack(side="left", padx=12)
        ttk.Label(page, text=f"Legacy review folder, if needed: {review_folder()}").pack(anchor="w", padx=12)
        archive_row = ttk.Frame(page)
        archive_row.pack(fill="x", padx=12, pady=8)
        ttk.Label(archive_row, text="Project archive format").pack(side="left")
        self.archive_format_var = tk.StringVar(
            value="ZIP · easiest recovery" if self.settings.get("archive_format") != "7z" else "7z · smaller archives"
        )
        archive_format = ttk.Combobox(
            archive_row,
            textvariable=self.archive_format_var,
            values=["ZIP · easiest recovery", "7z · smaller archives"],
            state="readonly",
            width=28,
        )
        archive_format.pack(side="left", padx=8)
        archive_format.bind("<<ComboboxSelected>>", lambda _event: self.save_archive_format())
        engine_status = "7-Zip engine ready" if find_7zip_executable() else "ZIP fallback ready · 7z format unavailable"
        ttk.Label(page, text=engine_status).pack(anchor="w", padx=12, pady=(0, 8))

    def show_page(self, page_name: str) -> None:
        for page in self.pages.values():
            page.grid_forget()
        self.pages[page_name].grid(row=0, column=0, sticky="nsew")
        if page_name == "review":
            self.refresh_review()
        if page_name == "projects":
            self.refresh_projects()
        if page_name == "downloads":
            self.refresh_downloads()

    def refresh_dashboard(self) -> None:
        metrics = self.db.dashboard_metrics()
        target_free_bytes = int(self.settings.get("target_free_gb")) * 1024 * 1024 * 1024
        summary = build_workstation_summary(self.findings, target_free_bytes)
        self.drive_var.set(f"C: drive · {format_bytes(summary.volume.free_bytes)} free of {format_bytes(summary.volume.total_bytes)}")
        if summary.target_met:
            self.target_var.set(f"Target reserve met: {format_bytes(summary.volume.target_free_bytes)} free.")
        else:
            self.target_var.set(f"Target reserve: {format_bytes(summary.volume.target_free_bytes)} · Gap: {format_bytes(summary.volume.free_gap_bytes)}")
        self.metric_vars["recoverable"].set(format_bytes(metrics["recoverable"]))
        self.metric_vars["dev_cache"].set(format_bytes(metrics["dev_cache"]))
        self.metric_vars["duplicate"].set(format_bytes(metrics["duplicate"]))
        self.metric_vars["findings"].set(str(metrics["finding_count"]))
        self.opportunity_table.delete(*self.opportunity_table.get_children())
        for opportunity in summary.opportunities[:6]:
            self.opportunity_table.insert("", "end", text=opportunity.title, values=(
                format_bytes(opportunity.space_gain_bytes),
                opportunity.risk,
                opportunity.user_effort,
                f"{opportunity.confidence_percent}%",
                opportunity.why,
                opportunity.recovery_path,
            ))
        if summary.local_only_warnings:
            names = ", ".join(item.name for item in summary.local_only_warnings[:5])
            self.local_only_var.set(f"Protected items with no verified backup recorded yet: {names}")
        else:
            self.local_only_var.set("No protected local-only items found in the latest scan.")

    def build_recovery_plan(self) -> None:
        target_free_bytes = int(self.settings.get("target_free_gb")) * 1024 * 1024 * 1024
        summary = build_workstation_summary(self.findings, target_free_bytes)
        if not summary.opportunities:
            show_info(self.root, "Recovery plan", "Scan Downloads, Storage, or your Project Library first so Jena can build a realistic plan.")
            return
        remaining = summary.volume.free_gap_bytes
        lines = [
            f"C: {format_bytes(summary.volume.free_bytes)} free · Target: {format_bytes(summary.volume.target_free_bytes)} · Need: {format_bytes(remaining)} more",
            "",
        ]
        expected = summary.volume.free_bytes
        for opportunity in summary.opportunities:
            if expected >= summary.volume.target_free_bytes:
                break
            expected += opportunity.space_gain_bytes
            lines.append(f"{opportunity.title} -> +{format_bytes(opportunity.space_gain_bytes)}")
        lines.append("")
        lines.append(f"Expected result: {format_bytes(expected)} free.")
        lines.append("Nothing has been changed. Approve actions from Downloads, Projects, or Storage.")
        show_info(self.root, "Recovery plan", "\n".join(lines))

    def save_target_free_space(self) -> None:
        try:
            target = int(self.target_free_var.get())
        except ValueError:
            show_error(self.root, "Invalid target", "Enter a whole number of GB.")
            return
        if target < 1:
            show_error(self.root, "Invalid target", "Target free space must be at least 1 GB.")
            return
        self.settings.set("target_free_gb", target)
        self.refresh_dashboard()
        self.status.set(f"Target free space saved · {target} GB")

    def start_scan(self, folder: Path, scope: str | None = None) -> None:
        if self.scan_thread and self.scan_thread.is_alive():
            show_info(self.root, "Scan already running", "Please cancel or wait for the current scan to finish.")
            return
        self.cancel_event.clear()
        self.progress.start(12)
        self.status.set(f"Scanning {folder}...")
        options = ScanOptions(
            large_file_mb=int(self.settings.get("large_file_mb")),
            large_folder_mb=int(self.settings.get("large_folder_mb")),
            duplicate_min_mb=int(self.settings.get("duplicate_min_mb")),
        )

        def worker():
            try:
                scanner = Scanner(options)
                result = scanner.scan(folder, scope or folder.name, self.cancel_event, lambda p: self.queue.put(("progress", p)))
                self.queue.put(("scan_complete", result))
            except Exception as exc:
                self.queue.put(("error", str(exc)))

        self.scan_thread = threading.Thread(target=worker, daemon=True)
        self.scan_thread.start()

    def choose_folder(self) -> None:
        folder = filedialog.askdirectory(title="Choose a folder to scan")
        if folder:
            self.start_scan(Path(folder), Path(folder).name)

    def cancel_scan(self) -> None:
        self.cancel_event.set()
        self.status.set("Cancelling scan...")

    def poll_queue(self) -> None:
        try:
            while True:
                event = self.queue.get_nowait()
                if isinstance(event, TaskEvent):
                    self.handle_task_event(event)
                    continue
                kind, payload = event
                if kind == "progress":
                    self.status.set(f"Scanning... {payload['items']} items · {format_bytes(payload['bytes'])} · {payload['findings']} findings")
                elif kind == "scan_complete":
                    self.progress.stop()
                    scan_id = self.db.save_scan(payload)
                    self.findings = self.db.latest_findings()
                    self.refresh_dashboard()
                    self.refresh_findings()
                    self.refresh_downloads()
                    self.status.set(f"Scan complete · {payload.scanned_items} items · {len(payload.findings)} findings · saved scan {scan_id}")
                    self.show_page("downloads" if payload.source_scope == "Downloads" else "findings")
                elif kind == "error":
                    self.progress.stop()
                    self.status.set("Ready")
                    show_error(self.root, "Scan failed", payload)
        except queue.Empty:
            pass
        self.root.after(150, self.poll_queue)

    def handle_task_event(self, event: TaskEvent) -> None:
        if event.name.startswith("projects."):
            self.handle_project_task_event(event)
        elif event.name == "preview.generate":
            self.handle_preview_event(event)
        elif event.name == "files.delete":
            self.handle_delete_event(event)
        elif event.name in {"projects.archive", "projects.restore"}:
            self.handle_archive_restore_event(event)
        else:
            if event.kind == "failed":
                self.status.set("Task failed")
                show_error(self.root, "Task failed", event.error)

    def preview_selected_download(self) -> None:
        selected = self.selected_download_findings()
        self.start_preview(Path(selected[0].path) if selected else None, target="downloads")

    def preview_selected_finding(self) -> None:
        selected = self.selected_findings()
        self.start_preview(Path(selected[0].path) if selected else None, target="storage")

    def start_preview(self, path: Path | None, target: str) -> None:
        if self.preview_task_id:
            self.task_manager.cancel(self.preview_task_id)
        if not path:
            self.set_preview_text("Select a file.", target)
            return
        self.set_preview_text("Generating preview...", target)
        task = self.task_manager.submit("preview.generate", self._preview_job, path, target)
        self.preview_task_id = task.id
        self.status.set("Generating preview...")

    def _preview_job(self, token, progress, path: Path, target: str) -> dict:
        result = self.preview_service.preview(path, token=token)
        return {
            "target": target,
            "path": result.path,
            "kind": result.kind,
            "title": result.title,
            "text": result.text,
            "image_path": result.image_path,
            "metadata": result.metadata or {},
        }

    def handle_preview_event(self, event: TaskEvent) -> None:
        if event.kind == "cancelled":
            return
        if event.kind == "failed":
            self.set_preview_text(f"Preview failed: {event.error}", "downloads")
            self.set_archive_entries([])
            self.status.set("Preview failed")
            return
        if event.kind != "completed":
            return
        payload = event.payload or {}
        target = payload.get("target", "downloads")
        text = f"{payload.get('title', '')}\n\n{payload.get('text', '')}".strip()
        self.set_preview_text(text, target)
        image_path = payload.get("image_path")
        if target == "downloads":
            self.set_preview_image(image_path)
            self.set_archive_entries(payload.get("metadata", {}).get("entries", []) if payload.get("kind") == "archive" else [])
        self.status.set("Preview ready")

    def set_preview_text(self, text: str, target: str) -> None:
        if target == "storage" and hasattr(self, "storage_preview_var"):
            self.storage_preview_var.set(text)
        elif hasattr(self, "preview_title_var"):
            self.preview_title_var.set(text)

    def set_preview_image(self, image_path: str | None) -> None:
        if not hasattr(self, "preview_image_label"):
            return
        if not image_path:
            self.preview_image_label.configure(image="")
            self.preview_photo = None
            return
        try:
            from PIL import Image, ImageTk

            image = Image.open(image_path)
            image.thumbnail((340, 260))
            self.preview_photo = ImageTk.PhotoImage(image)
            self.preview_image_label.configure(image=self.preview_photo)
        except Exception:
            self.preview_image_label.configure(image="")
            self.preview_photo = None

    def set_archive_entries(self, entries: list[dict]) -> None:
        if not hasattr(self, "archive_browser"):
            return
        self.archive_browser.delete(*self.archive_browser.get_children())
        if not entries:
            self.archive_browser_frame.pack_forget()
            return
        nodes: dict[str, str] = {}
        for entry in entries:
            parts = PurePosixPath(str(entry.get("path", "")).replace("\\", "/")).parts
            parent = ""
            accumulated: list[str] = []
            for index, part in enumerate(parts):
                accumulated.append(part)
                key = "/".join(accumulated)
                if key not in nodes:
                    iid = f"archive-entry-{len(nodes)}"
                    is_leaf = index == len(parts) - 1 and not entry.get("is_dir", False)
                    size = format_bytes(int(entry.get("size_bytes", 0))) if is_leaf else ""
                    self.archive_browser.insert(parent, "end", iid=iid, text=part, values=(size,), open=index == 0)
                    nodes[key] = iid
                parent = nodes[key]
        self.archive_browser_frame.pack(fill="both", expand=True, pady=(8, 0))

    def delete_key_selected_downloads(self, event, permanent: bool):
        self.delete_selected_paths([Path(item.path) for item in self.selected_download_findings()], permanent)
        return "break"

    def delete_key_selected_findings(self, event, permanent: bool):
        self.delete_selected_paths([Path(item.path) for item in self.selected_findings()], permanent)
        return "break"

    def show_file_context_menu(self, event, source: str) -> None:
        menu = tk.Menu(self.root, tearoff=False)
        if source == "downloads":
            paths = [Path(item.path) for item in self.selected_download_findings()]
            preview_command = self.preview_selected_download
        else:
            paths = [Path(item.path) for item in self.selected_findings()]
            preview_command = self.preview_selected_finding
        menu.add_command(label="Preview", command=preview_command)
        menu.add_command(label="Open", command=lambda: self.open_path(paths[0]) if paths else None)
        menu.add_command(label="Open File Location", command=lambda: self.open_path(paths[0].parent) if paths else None)
        menu.add_command(label="Copy Path", command=lambda: self.copy_path(paths[0]) if paths else None)
        menu.add_separator()
        menu.add_command(label="Recycle\tDel", command=lambda: self.delete_selected_paths(paths, permanent=False))
        menu.add_command(label="Permanently Delete\tShift+Del", command=lambda: self.delete_selected_paths(paths, permanent=True))
        menu.tk_popup(event.x_root, event.y_root)

    def open_path(self, path: Path) -> None:
        try:
            os.startfile(str(path))
        except Exception as exc:
            show_error(self.root, "Open failed", str(exc))

    def copy_path(self, path: Path) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(str(path))
        self.status.set("Path copied")

    def delete_selected_paths(self, paths: list[Path], permanent: bool) -> None:
        if not paths:
            show_info(self.root, "No selection", "Select one or more filesystem items first.")
            return
        plan = build_delete_plan(paths)
        if plan.blocked:
            show_error(self.root, "Blocked", "\n".join(plan.blocked[:8]))
            return
        if not self.confirm_delete_plan(plan, permanent):
            return
        task = self.task_manager.submit("files.delete", self._delete_job, plan.targets, permanent)
        self.delete_task_id = task.id
        self.status.set("Permanently deleting..." if permanent else "Recycling...")

    def confirm_delete_plan(self, plan, permanent: bool) -> bool:
        from tkinter import messagebox

        if permanent:
            title = "Permanent deletion requires extra confirmation" if plan.high_risk else "Permanently delete?"
            lines = [
                f"Permanently delete {len(plan.targets)} item(s)?",
                format_bytes(plan.total_bytes),
                "",
                "These items will bypass the Windows Recycle Bin.",
                "This action cannot be undone by Jena.",
            ]
            if plan.high_risk:
                return self.confirm_high_risk_delete(title, "\n".join(lines[:2] + ["", "This selection includes: " + ", ".join(plan.risk_reasons[:5])] + lines[2:]))
            return messagebox.askyesno(title, "\n".join(lines), parent=self.root)
        return messagebox.askyesno(
            "Move to Recycle Bin?",
            f"Move {len(plan.targets)} item(s) to the Windows Recycle Bin?\n\n{format_bytes(plan.total_bytes)}",
            parent=self.root,
        )

    def confirm_high_risk_delete(self, title: str, message: str) -> bool:
        dialog = tk.Toplevel(self.root)
        dialog.title(title)
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        result = tk.BooleanVar(value=False)
        understood = tk.BooleanVar(value=False)
        ttk.Label(dialog, text=message, padding=12, justify="left", wraplength=460).pack(fill="x")
        checkbox = ttk.Checkbutton(dialog, text="I understand this deletion is permanent.", variable=understood)
        checkbox.pack(anchor="w", padx=12, pady=(0, 12))
        buttons = ttk.Frame(dialog, padding=12)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=4)

        delete_button = ttk.Button(buttons, text="Permanently Delete", command=lambda: (result.set(True), dialog.destroy()))
        delete_button.pack(side="right", padx=4)
        delete_button.state(["disabled"])

        def sync_button(*_args):
            if understood.get():
                delete_button.state(["!disabled"])
            else:
                delete_button.state(["disabled"])

        understood.trace_add("write", sync_button)
        checkbox.focus_set()
        self.root.wait_window(dialog)
        return result.get()

    def _delete_job(self, token, progress, paths: list[Path], permanent: bool) -> dict:
        if permanent:
            return permanently_delete_paths(paths, progress=progress, token=token)
        return recycle_paths(paths, progress=progress, token=token)

    def handle_delete_event(self, event: TaskEvent) -> None:
        if event.kind == "progress":
            payload = event.payload or {}
            self.status.set(f"Deleting... {payload.get('processed', 0)} of {payload.get('total', 0)}")
            return
        if event.kind == "failed":
            self.status.set("Delete failed")
            show_error(self.root, "Delete failed", event.error)
            return
        if event.kind != "completed":
            return
        manifest = event.payload
        self.db.save_operation(manifest)
        deleted_sources = {item["source"] for item in manifest.get("items", []) if item.get("status") in {"DELETED", "RECYCLED"}}
        self.findings = [item for item in self.findings if item.path not in deleted_sources]
        self.download_findings = [item for item in self.download_findings if item.path not in deleted_sources]
        self.refresh_findings()
        self.refresh_downloads()
        self.refresh_dashboard()
        self.refresh_review()
        self.status.set(f"{manifest.get('operation')} {manifest.get('result', '').lower()}")

    def refresh_findings(self) -> None:
        self.apply_filters()

    def apply_filters(self) -> None:
        query = self.search_var.get().lower() if hasattr(self, "search_var") else ""
        risk = self.risk_var.get() if hasattr(self, "risk_var") else "All"
        self.filtered_findings = []
        for finding in self.findings:
            haystack = f"{finding.name} {finding.path} {finding.category} {finding.project_root or ''}".lower()
            if query and query not in haystack:
                continue
            if risk != "All" and risk_label(finding.risk_level) != risk:
                continue
            self.filtered_findings.append(finding)
        self.populate_findings()

    def populate_findings(self) -> None:
        self.findings_table.delete(*self.findings_table.get_children())
        for finding in self.filtered_findings:
            self.findings_table.insert("", "end", iid=finding.id, values=(
                finding.name,
                format_bytes(finding.size_bytes),
                risk_label(finding.risk_level),
                tags_label(finding.tags),
                format_date(finding.modified_at),
                finding.path,
            ))
        self.update_selection_summary()

    def sort_findings(self, column: str) -> None:
        key_map = {
            "name": lambda f: f.name.lower(),
            "size": lambda f: f.size_bytes,
            "risk": lambda f: risk_label(f.risk_level),
            "category": lambda f: tags_label(f.tags),
            "modified": lambda f: f.modified_at,
            "path": lambda f: f.path.lower(),
        }
        self.filtered_findings.sort(key=key_map[column], reverse=column in {"size", "modified"})
        self.populate_findings()

    def selected_findings(self) -> list[Finding]:
        selected = set(self.findings_table.selection())
        by_id = {finding.id: finding for finding in self.findings}
        return [by_id[item_id] for item_id in selected if item_id in by_id]

    def refresh_downloads(self) -> None:
        if not hasattr(self, "download_category_table"):
            return
        self.download_findings = [item for item in self.db.latest_findings("Downloads") if item.item_type == "file"]
        self.download_category_table.delete(*self.download_category_table.get_children())
        grouped = {name: [] for name in ["Installers", "Archives", "Images", "Documents", "Videos", "Other"]}
        for finding in self.download_findings:
            grouped[self.download_category_for(finding)].append(finding)
        for name, items in grouped.items():
            self.download_category_table.insert("", "end", iid=name, text=name, values=(len(items), format_bytes(sum(item.size_bytes for item in items))))
        self.populate_download_files()

    def download_category_for(self, finding: Finding) -> str:
        suffix = Path(finding.path).suffix.lower()
        if suffix in {".exe", ".msi", ".msix", ".appx"}:
            return "Installers"
        if suffix in {".zip", ".7z", ".rar", ".tar", ".gz"}:
            return "Archives"
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}:
            return "Images"
        if suffix in {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt"}:
            return "Documents"
        if suffix in {".mp4", ".mov", ".avi", ".mkv", ".webm"}:
            return "Videos"
        return "Other"

    def populate_download_files(self) -> None:
        self.download_file_table.delete(*self.download_file_table.get_children())
        selection = self.download_category_table.selection()
        category = selection[0] if selection else None
        items = [item for item in self.download_findings if category is None or self.download_category_for(item) == category]
        for finding in items:
            self.download_file_table.insert("", "end", iid=finding.id, values=(
                finding.name,
                format_bytes(finding.size_bytes),
                format_date(finding.modified_at),
                finding.reason,
                finding.path,
            ))
        if category:
            total = sum(item.size_bytes for item in items)
            self.download_detail_var.set(f"{category}: {len(items)} item(s), {format_bytes(total)}. Select files and recycle only what you approve.")
        else:
            self.download_detail_var.set("Select a category to review Downloads.")

    def selected_download_findings(self) -> list[Finding]:
        selected = set(self.download_file_table.selection())
        by_id = {finding.id: finding for finding in self.download_findings}
        return [by_id[item_id] for item_id in selected if item_id in by_id]

    def recycle_selected_downloads(self) -> None:
        selected = self.selected_download_findings()
        if not selected:
            show_info(self.root, "No selection", "Select one or more Downloads first.")
            return
        self.delete_selected_paths([Path(item.path) for item in selected], permanent=False)

    def update_selection_summary(self) -> None:
        selected = self.selected_findings() if hasattr(self, "findings_table") else []
        total = sum(item.size_bytes for item in selected)
        self.selection_var.set(f"{len(selected)} selected · {format_bytes(total)}")

    def recycle_selected(self) -> None:
        selected = self.selected_findings()
        if not selected:
            show_info(self.root, "No selection", "Select one or more findings first.")
            return
        movable = []
        blocked = []
        for item in selected:
            allowed, reason = can_move_to_review(item)
            if allowed:
                movable.append(item)
            else:
                blocked.append(f"{item.name}: {reason}")
        if not movable:
            show_error(self.root, "Nothing can be moved", "\n".join(blocked[:8]))
            return
        self.delete_selected_paths([Path(item.path) for item in movable], permanent=False)

    def choose_project_library(self) -> None:
        folder = filedialog.askdirectory(title="Where do you keep your projects?")
        if not folder:
            return
        self.settings.set("project_library_root", folder)
        self.project_library_var.set(folder)
        self.refresh_project_library()

    def refresh_project_library(self) -> None:
        root = self.settings.get("project_library_root")
        if not root:
            show_info(self.root, "Project Library", "Choose where you keep your projects first.")
            return
        self.project_records = archived_project_records(data_dir())
        self.projects_table.delete(*self.projects_table.get_children())
        for record in self.project_records:
            self.insert_or_update_project(record)
        self.project_detail_var.set("Discovering projects...")
        self.project_notice_var.set(self.project_library_notice(Path(root)))
        library_id = stable_library_id(Path(root))
        task = self.task_manager.submit("projects.discover", self._project_discovery_job, Path(root), data_dir(), library_id)
        self.project_tasks.add(task.id)
        self.status.set("Discovering projects · 0 found")

    def _project_discovery_job(self, token, progress, root: Path, data_root: Path, library_id: str) -> list[str]:
        found: list[str] = []

        def on_project(project_path: Path) -> None:
            found.append(str(project_path))
            progress({"event": "project_found", "path": str(project_path), "found": len(found), "library_id": library_id})

        def on_progress(payload: dict) -> None:
            payload["event"] = "discovering"
            progress(payload)

        quick_discover_project_roots(root, max_depth=3, token=token, on_project=on_project, on_progress=on_progress)
        return found

    def _project_analysis_job(self, token, progress, project_path: Path, data_root: Path, library_id: str) -> dict:
        record = analyze_and_cache_project(project_path, data_root, token=token, progress=progress, library_id=library_id)
        return {
            "path": record.path,
            "name": record.name,
            "size_bytes": record.size_bytes,
            "regenerable_bytes": record.breakdown.regenerable_bytes,
        }

    def handle_project_task_event(self, event: TaskEvent) -> None:
        if event.kind == "progress":
            payload = event.payload or {}
            if payload.get("event") == "project_found":
                project_path = Path(payload["path"])
                library_id = payload.get("library_id") or stable_library_id(project_path.parent)
                record = project_record_from_cache(project_path, data_dir(), library_id=library_id)
                existing = next((index for index, item in enumerate(self.project_records) if item.path == record.path), None)
                if existing is None:
                    self.project_records.append(record)
                else:
                    self.project_records[existing] = record
                self.insert_or_update_project(record)
                analysis = self.task_manager.submit("projects.analyze", self._project_analysis_job, project_path, data_dir(), library_id)
                self.project_tasks.add(analysis.id)
                self.status.set(f"Discovering projects · {payload.get('found', len(self.project_records))} found")
            elif "project" in payload:
                self.status.set(f"Analyzing {Path(payload['project']).name} · {format_bytes(payload.get('bytes', 0))} scanned")
            elif "current" in payload:
                self.status.set(f"Discovering projects · {payload.get('found', len(self.project_records))} found")
            return
        if event.kind == "completed" and event.name == "projects.analyze":
            payload = event.payload or {}
            for index, record in enumerate(self.project_records):
                if record.path == payload.get("path"):
                    self.project_records[index] = project_record_from_cache(Path(record.path), data_dir(), library_id=record.library_id)
                    self.insert_or_update_project(self.project_records[index])
                    break
            self.status.set(f"Analyzed {payload.get('name', 'project')}")
        elif event.kind == "completed" and event.name == "projects.discover":
            self.status.set(f"Project discovery complete · {len(self.project_records)} found")
            self.project_detail_var.set("Project discovery complete. Sizes continue updating as analysis finishes.")
        elif event.kind == "cancelled":
            self.status.set("Project work cancelled")
            self.project_detail_var.set("Cancelled. Already discovered projects remain usable.")
        elif event.kind == "failed":
            self.status.set("Project work failed")
            show_error(self.root, "Project work failed", event.error)
        self.refresh_projects()
        self.status.set(f"Project Library refreshed · {len(self.project_records)} project(s)")

    def refresh_projects(self) -> None:
        self.projects_table.delete(*self.projects_table.get_children())
        for project in self.project_records:
            self.insert_or_update_project(project)

    def insert_or_update_project(self, project: ProjectRecord, iid: str | None = None) -> None:
        iid = iid or self.project_iid(project.path)
        size = format_bytes(project.size_bytes) if project.size_bytes else "Calculating..."
        regenerable = format_bytes(project.breakdown.regenerable_bytes) if project.breakdown.regenerable_bytes else "Calculating..."
        recommendations = archive_recommendations(
            [project],
            inactive_days=int(self.settings.get("archive_inactive_days") or 90),
        )
        candidate = f"{recommendations[0].days_inactive} days" if recommendations else ""
        values = (
            project.name,
            state_display(project.state),
            size,
            regenerable,
            format_date(project.modified_at),
            candidate,
            project.project_type,
            project.path,
        )
        if self.projects_table.exists(iid):
            self.projects_table.item(iid, values=values)
        else:
            self.projects_table.insert("", "end", iid=iid, values=values)

    def show_archive_candidates(self) -> None:
        recommendations = archive_recommendations(
            self.project_records,
            inactive_days=int(self.settings.get("archive_inactive_days") or 90),
        )
        if not recommendations:
            show_info(
                self.root,
                "Archive candidates",
                "No inactive projects have crossed the archive age yet. Active and Never Archive projects are always excluded.",
            )
            return
        lines = [
            f"{item.project_name} · {format_bytes(item.project_bytes)} · unchanged {item.days_inactive} days"
            for item in recommendations[:8]
        ]
        first_iid = self.project_iid(recommendations[0].project_path)
        if self.projects_table.exists(first_iid):
            self.projects_table.selection_set(first_iid)
            self.projects_table.focus(first_iid)
            self.projects_table.see(first_iid)
            self.show_project_detail()
        show_info(
            self.root,
            "Archive candidates",
            "Jena recommends review only; nothing was archived automatically.\n\n" + "\n".join(lines),
        )

    def project_iid(self, path: str) -> str:
        record = next((item for item in self.project_records if item.path == path), None)
        if record and record.project_id:
            return record.project_id
        return str(abs(hash(path)))

    def project_library_notice(self, root: Path) -> str:
        broad = {Path.home().resolve(), (Path.home() / "Documents").resolve()}
        try:
            resolved = root.resolve()
        except OSError:
            resolved = root
        if resolved in broad:
            return "Jena will search this folder to a limited depth and skip dependency/cache folders."
        return ""

    def cancel_project_jobs(self) -> None:
        for task_id in list(self.project_tasks):
            self.task_manager.cancel(task_id)

    def selected_project(self) -> ProjectRecord | None:
        selection = self.projects_table.selection()
        if not selection:
            return None
        selected_path = self.projects_table.item(selection[0], "values")[7]
        return next((record for record in self.project_records if record.path == selected_path), None)

    def show_project_detail(self) -> None:
        project = self.selected_project()
        if not project:
            return
        b = project.breakdown
        evidence = " ".join(project.activity_evidence or [])
        self.project_detail_var.set(
            f"{project.name}: Source {format_bytes(b.source_bytes)} · Dependencies {format_bytes(b.dependencies_bytes)} · "
            f"Caches {format_bytes(b.caches_bytes)} · Assets {format_bytes(b.assets_bytes)} · "
            f"Build output {format_bytes(b.build_output_bytes)} · Other {format_bytes(b.other_bytes)} · "
            f"Last meaningful activity {format_date(project.last_meaningful_activity or project.modified_at)}. {evidence}"
        )

    def save_archive_format(self) -> None:
        value = "7z" if self.archive_format_var.get().startswith("7z") else "zip"
        self.settings.set("archive_format", value)
        self.status.set(f"Project archives will use {value.upper() if value == 'zip' else '7z'}")

    def set_selected_project_state(self, state: ProjectState) -> None:
        project = self.selected_project()
        if not project:
            show_info(self.root, "No project selected", "Select a project first.")
            return
        set_project_state(data_dir(), Path(project.path), state, library_id=project.library_id)
        for index, record in enumerate(self.project_records):
            if record.path == project.path:
                record.state = state
                self.project_records[index] = record
                self.insert_or_update_project(record)
                break

    def open_selected_project_in_explorer(self) -> None:
        project = self.selected_project()
        if not project:
            show_info(self.root, "No project selected", "Select a project first.")
            return
        try:
            open_in_explorer(Path(project.path))
        except OSError as exc:
            show_error(self.root, "Open in Explorer failed", str(exc))

    def archive_selected_project(self) -> None:
        project = self.selected_project()
        if not project:
            show_info(self.root, "No project selected", "Select an inactive project first.")
            return
        if project.state == ProjectState.NEVER_ARCHIVE:
            show_error(self.root, "Protected project", "This project is marked Never Archive.")
            return
        if project.state == ProjectState.ARCHIVED:
            show_info(self.root, "Already archived", "This project is already archived. Use Restore to bring it back.")
            return
        if project.state == ProjectState.ACTIVE:
            show_error(self.root, "Active project", "Mark the project Inactive before archiving it.")
            return
        archive_dir = filedialog.askdirectory(title="Choose archive destination")
        if not archive_dir:
            return
        format_value = self.settings.get("archive_format") or "zip"
        archive_format = ArchiveFormat(format_value)
        recovery_note = (
            "ZIP opens directly in Windows."
            if archive_format == ArchiveFormat.ZIP
            else "7z is usually smaller and requires Jena or 7-Zip to restore."
        )
        expected_archive_bytes = max(project.size_bytes - project.breakdown.regenerable_bytes, 0)
        expected_recovered_bytes = max(project.size_bytes - expected_archive_bytes, 0)
        message = (
            f"Archive {project.name}?\n\n"
            f"Current size: {format_bytes(project.size_bytes)}\n"
            f"Excluded regenerable data: {format_bytes(project.breakdown.regenerable_bytes)}\n"
            f"Expected archive: no more than about {format_bytes(expected_archive_bytes)} before compression\n"
            f"Minimum expected space recovered: {format_bytes(expected_recovered_bytes)}\n\n"
            f"Format: {archive_format.value.upper()} · {recovery_note}\n\n"
            "Jena will run an integrity test and verify every file hash before moving the original project to the Windows Recycle Bin."
        )
        from tkinter import messagebox
        if not messagebox.askyesno("Archive project", message, parent=self.root):
            return
        task = self.task_manager.submit(
            "projects.archive",
            self._archive_job,
            Path(project.path),
            Path(archive_dir),
            archive_format,
        )
        self.project_tasks.add(task.id)
        self.status.set(f"Archiving {project.name}...")

    def _archive_job(self, token, progress, project_path: Path, archive_dir: Path, archive_format: ArchiveFormat) -> dict:
        result = archive_project(
            project_path,
            archive_dir,
            data_dir(),
            recycle_original=True,
            archive_format=archive_format,
            token=token,
            progress=progress,
        )
        return {
            "operation_id": f"archive-{Path(result.manifest_path).stem}",
            "created_at": result.manifest_path,
            "operation": "project archive",
            "items": [{"source": result.project_path, "destination": result.archive_path, "status": "ARCHIVED"}],
            "manifest_path": result.manifest_path,
            "archive_path": result.archive_path,
            "engine": result.engine,
            "archive_format": result.archive_format,
        }

    def restore_selected_project_archive(self) -> None:
        project = self.selected_project()
        if not project or not project.archive_manifest:
            show_info(self.root, "No archive selected", "Select an archived project with a manifest.")
            return
        destination = filedialog.askdirectory(title="Restore project into which folder?")
        if not destination:
            return
        task = self.task_manager.submit("projects.restore", self._restore_project_job, Path(project.archive_manifest), Path(destination))
        self.project_tasks.add(task.id)
        self.status.set(f"Restoring {project.name}...")

    def _restore_project_job(self, token, progress, manifest_path: Path, destination: Path) -> dict:
        result = restore_project(manifest_path, destination, token=token, progress=progress)
        return {
            "operation_id": f"restore-{Path(result.manifest_path).stem}",
            "created_at": result.manifest_path,
            "operation": "project restore",
            "items": [{"source": result.archive_path, "destination": result.restored_to, "status": "RESTORED"}],
            "manifest_path": result.manifest_path,
            "restored_to": result.restored_to,
        }

    def handle_archive_restore_event(self, event: TaskEvent) -> None:
        if event.kind == "progress":
            payload = event.payload or {}
            phase = str(payload.get("phase", "working")).replace("_", " ").title()
            completed = payload.get("completed")
            total = payload.get("total")
            suffix = f" · {completed}/{total}" if completed is not None and total else ""
            self.status.set(f"{phase}{suffix}")
            return
        if event.kind == "cancelled":
            self.status.set("Project archive operation cancelled")
            return
        if event.kind == "failed":
            self.status.set("Project operation failed")
            show_error(self.root, "Project operation failed", event.error)
            return
        if event.kind != "completed":
            return
        manifest = event.payload
        self.db.save_operation(manifest)
        self.refresh_review()
        self.refresh_project_library()
        if manifest.get("operation") == "project archive":
            show_info(
                self.root,
                "Archive complete",
                f"Verified {str(manifest.get('archive_format', 'zip')).upper()} archive created with {manifest.get('engine', 'the compression engine')}:\n{manifest.get('archive_path')}",
            )
        else:
            show_info(self.root, "Restore complete", f"Project restored and verified:\n{manifest.get('restored_to')}")

    def refresh_review(self) -> None:
        self.review_table.delete(*self.review_table.get_children())
        for operation in self.db.operations():
            self.review_table.insert("", "end", values=(
                operation.get("created_at", ""),
                len(operation.get("items", [])),
                operation.get("operation", "legacy move"),
                operation.get("manifest_path", ""),
            ))

    def restore_selected(self) -> None:
        selection = self.review_table.selection()
        if not selection:
            show_info(self.root, "No operation selected", "Select an executed review operation first.")
            return
        manifest_path = self.review_table.item(selection[0], "values")[3]
        if not manifest_path:
            show_error(self.root, "Cannot restore", "Dry-run operations do not have moved files to restore.")
            return
        result = restore_from_manifest(Path(manifest_path))
        restored = sum(1 for row in result["results"] if row["status"] == "RESTORED")
        self.status.set(f"Restored {restored} item(s)")
        show_info(self.root, "Restore complete", f"Restored {restored} item(s).")

    def on_close(self) -> None:
        self.task_manager.cancel_all()
        if self.scan_thread and self.scan_thread.is_alive():
            self.cancel_event.set()
        self.db.close()
        self.root.destroy()
