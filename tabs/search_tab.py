import os
import queue
import subprocess
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import messagebox, ttk

from config.config import AppConfig
from services.search_service import (
    MetadataSearchIndex,
    MetadataSearchRecord,
    MetadataSearchService,
)


class SearchTab(ttk.Frame):
    """Searches event folders using their Data/metadata.json files."""

    SORT_OPTIONS = (
        "Date newest first",
        "Date oldest first",
        "Event name A-Z",
        "Most photos",
        "Most videos",
        "Recently modified",
    )
    SOURCE_OPTIONS = ("All event folders", "Current year", "Google Drive", "Local Events")

    def __init__(
        self,
        master: ttk.Notebook,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, padding=18)
        self.status_callback = status_callback
        self.search_service = MetadataSearchService()
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.index = MetadataSearchIndex([], [], [], [], [], [])
        self.filtered_records: list[MetadataSearchRecord] = []
        self.records_by_id: dict[str, MetadataSearchRecord] = {}

        self.query_var = tk.StringVar()
        self.source_var = tk.StringVar(value=self.SOURCE_OPTIONS[0])
        self.school_year_var = tk.StringVar(value="Any school year")
        self.grade_var = tk.StringVar(value="Any grade")
        self.keyword_var = tk.StringVar(value="Any keyword")
        self.sort_var = tk.StringVar(value=self.SORT_OPTIONS[0])
        self.status_var = tk.StringVar(value="Ready to search event metadata.")
        self.details_var = tk.StringVar(value="Select an event to see its metadata.")
        self.root_summary_var = tk.StringVar()

        self._build_layout()
        self._refresh_roots_label()
        self._refresh_index()
        self.after(100, self._poll_worker_queue)

    def _build_layout(self) -> None:
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        controls = ttk.LabelFrame(self, text="Search Event Metadata", padding=14)
        controls.grid(row=0, column=0, sticky="ew")
        controls.columnconfigure(1, weight=1)
        controls.columnconfigure(3, weight=1)

        ttk.Label(controls, text="Search").grid(row=0, column=0, sticky="w")
        self.search_combo = ttk.Combobox(
            controls,
            textvariable=self.query_var,
            values=[],
        )
        self.search_combo.grid(row=0, column=1, columnspan=3, sticky="ew", padx=(12, 8))
        self.search_combo.bind("<<ComboboxSelected>>", self._filters_changed)
        self.search_combo.bind("<KeyRelease>", self._filters_changed)
        ttk.Button(controls, text="Clear", command=self._clear_filters).grid(
            row=0,
            column=4,
            sticky="e",
        )

        ttk.Label(controls, text="Source").grid(row=1, column=0, sticky="w", pady=(12, 0))
        self.source_combo = ttk.Combobox(
            controls,
            textvariable=self.source_var,
            values=self.SOURCE_OPTIONS,
            state="readonly",
            width=18,
        )
        self.source_combo.grid(row=1, column=1, sticky="ew", padx=(12, 8), pady=(12, 0))
        self.source_combo.bind("<<ComboboxSelected>>", self._refresh_index)

        ttk.Label(controls, text="School Year").grid(
            row=1,
            column=2,
            sticky="w",
            pady=(12, 0),
        )
        self.school_year_combo = ttk.Combobox(
            controls,
            textvariable=self.school_year_var,
            state="readonly",
            width=18,
        )
        self.school_year_combo.grid(
            row=1,
            column=3,
            sticky="ew",
            padx=(12, 8),
            pady=(12, 0),
        )
        self.school_year_combo.bind("<<ComboboxSelected>>", self._filters_changed)

        ttk.Button(controls, text="Refresh", command=self._refresh_index).grid(
            row=1,
            column=4,
            sticky="e",
            pady=(12, 0),
        )

        ttk.Label(controls, text="Grade").grid(row=2, column=0, sticky="w", pady=(12, 0))
        self.grade_combo = ttk.Combobox(
            controls,
            textvariable=self.grade_var,
            state="readonly",
            width=18,
        )
        self.grade_combo.grid(row=2, column=1, sticky="ew", padx=(12, 8), pady=(12, 0))
        self.grade_combo.bind("<<ComboboxSelected>>", self._filters_changed)

        ttk.Label(controls, text="Keyword").grid(
            row=2,
            column=2,
            sticky="w",
            pady=(12, 0),
        )
        self.keyword_combo = ttk.Combobox(
            controls,
            textvariable=self.keyword_var,
            state="readonly",
            width=18,
        )
        self.keyword_combo.grid(row=2, column=3, sticky="ew", padx=(12, 8), pady=(12, 0))
        self.keyword_combo.bind("<<ComboboxSelected>>", self._filters_changed)

        ttk.Label(controls, text="Sort").grid(row=3, column=0, sticky="w", pady=(12, 0))
        self.sort_combo = ttk.Combobox(
            controls,
            textvariable=self.sort_var,
            values=self.SORT_OPTIONS,
            state="readonly",
            width=22,
        )
        self.sort_combo.grid(row=3, column=1, sticky="ew", padx=(12, 8), pady=(12, 0))
        self.sort_combo.bind("<<ComboboxSelected>>", self._filters_changed)

        ttk.Label(controls, textvariable=self.root_summary_var, wraplength=720).grid(
            row=4,
            column=0,
            columnspan=5,
            sticky="w",
            pady=(12, 0),
        )

        results_frame = ttk.Frame(self)
        results_frame.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        results_frame.rowconfigure(0, weight=1)
        results_frame.columnconfigure(0, weight=1)

        columns = ("date", "event", "school_year", "grades", "keywords", "photos", "videos")
        self.results_tree = ttk.Treeview(
            results_frame,
            columns=columns,
            show="headings",
            selectmode="browse",
        )
        headings = {
            "date": "Date",
            "event": "Event",
            "school_year": "School Year",
            "grades": "Grades",
            "keywords": "Keywords",
            "photos": "Photos",
            "videos": "Videos",
        }
        widths = {
            "date": 100,
            "event": 220,
            "school_year": 110,
            "grades": 150,
            "keywords": 220,
            "photos": 70,
            "videos": 70,
        }
        for column in columns:
            self.results_tree.heading(column, text=headings[column])
            self.results_tree.column(
                column,
                width=widths[column],
                minwidth=60,
                stretch=column in {"event", "grades", "keywords"},
            )
        self.results_tree.grid(row=0, column=0, sticky="nsew")
        self.results_tree.bind("<<TreeviewSelect>>", self._selection_changed)
        self.results_tree.bind("<Double-1>", self._open_selected_folder)

        scrollbar = ttk.Scrollbar(
            results_frame,
            orient="vertical",
            command=self.results_tree.yview,
        )
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.results_tree.configure(yscrollcommand=scrollbar.set)

        footer = ttk.Frame(self)
        footer.grid(row=2, column=0, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        ttk.Button(footer, text="Open Event Folder", command=self._open_selected_folder).grid(
            row=0,
            column=1,
            sticky="e",
        )

        details = ttk.LabelFrame(self, text="Selected Event", padding=12)
        details.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        details.columnconfigure(0, weight=1)
        ttk.Label(details, textvariable=self.details_var, wraplength=820).grid(
            row=0,
            column=0,
            sticky="w",
        )

    def refresh_settings(self) -> None:
        self._refresh_roots_label()
        self._refresh_index()

    def _refresh_index(self, _event: tk.Event | None = None) -> None:
        if self.worker_thread is not None and self.worker_thread.is_alive():
            return

        roots = self._selected_roots()
        self.status_var.set("Loading metadata files...")
        self._set_status("Loading search metadata...")
        self.worker_thread = threading.Thread(
            target=self._build_index_worker,
            args=(roots,),
            daemon=True,
        )
        self.worker_thread.start()

    def _build_index_worker(self, roots: dict[str, Path]) -> None:
        try:
            self.worker_queue.put(("index", self.search_service.build_index(roots)))
        except Exception as exc:
            self.worker_queue.put(("error", str(exc)))

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                message, payload = self.worker_queue.get_nowait()
                if message == "index" and isinstance(payload, MetadataSearchIndex):
                    self._show_index(payload)
                elif message == "error":
                    self.status_var.set("Metadata search failed.")
                    self._set_status("Metadata search failed.")
                    messagebox.showerror("Search Failed", str(payload))
        except queue.Empty:
            pass
        self.after(100, self._poll_worker_queue)

    def _show_index(self, index: MetadataSearchIndex) -> None:
        self.index = index
        self.search_combo.configure(values=index.suggestions)
        self.school_year_combo.configure(values=["Any school year", *index.school_years])
        self.grade_combo.configure(values=["Any grade", *index.grades])
        self.keyword_combo.configure(values=["Any keyword", *index.keywords])
        self._ensure_filter_values()
        self._apply_filters()

        if index.errors:
            self.status_var.set(
                f"Loaded {len(index.records)} events. "
                f"{len(index.errors)} metadata file(s) could not be read."
            )
            self._set_status("Search metadata loaded with warnings.")
            return

        self.status_var.set(f"Loaded {len(index.records)} events.")
        self._set_status("Search metadata loaded.")

    def _apply_filters(self) -> None:
        query = self.query_var.get().strip().casefold()
        school_year = self.school_year_var.get()
        grade = self.grade_var.get()
        keyword = self.keyword_var.get()

        records = []
        for record in self.index.records:
            if query and query not in record.searchable_text:
                continue
            if school_year != "Any school year" and record.school_year != school_year:
                continue
            if grade != "Any grade" and grade not in record.grades:
                continue
            if keyword != "Any keyword" and keyword not in record.keywords:
                continue
            records.append(record)

        self.filtered_records = self._sort_records(records)
        self._render_results()

    def _sort_records(
        self,
        records: list[MetadataSearchRecord],
    ) -> list[MetadataSearchRecord]:
        sort_option = self.sort_var.get()
        if sort_option == "Date oldest first":
            return sorted(records, key=lambda record: (record.date, record.event_name.casefold()))
        if sort_option == "Event name A-Z":
            return sorted(records, key=lambda record: record.event_name.casefold())
        if sort_option == "Most photos":
            return sorted(records, key=lambda record: record.photo_count, reverse=True)
        if sort_option == "Most videos":
            return sorted(records, key=lambda record: record.video_count, reverse=True)
        if sort_option == "Recently modified":
            return sorted(records, key=lambda record: record.last_modified, reverse=True)
        return sorted(records, key=lambda record: record.date, reverse=True)

    def _render_results(self) -> None:
        self.results_tree.delete(*self.results_tree.get_children())
        self.records_by_id.clear()

        for index, record in enumerate(self.filtered_records):
            item_id = str(index)
            self.records_by_id[item_id] = record
            self.results_tree.insert(
                "",
                "end",
                iid=item_id,
                values=(
                    record.date,
                    record.event_name or record.event_folder.name,
                    record.school_year,
                    ", ".join(record.grades),
                    ", ".join(record.keywords),
                    record.photo_count,
                    record.video_count,
                ),
            )

        if self.filtered_records:
            self.details_var.set("Select an event to see its metadata.")
        else:
            self.details_var.set("No events match the current search.")
        self.status_var.set(
            f"Showing {len(self.filtered_records)} of {len(self.index.records)} events."
        )

    def _filters_changed(self, _event: tk.Event | None = None) -> None:
        self._apply_filters()

    def _selection_changed(self, _event: tk.Event | None = None) -> None:
        record = self._selected_record()
        if record is None:
            return

        self.details_var.set(
            f"{record.event_name or record.event_folder.name}\n"
            f"Date: {record.date or 'Unknown'} | School year: "
            f"{record.school_year or 'Unknown'} | Source: {record.source_name}\n"
            f"Grades: {', '.join(record.grades) or 'None'}\n"
            f"Keywords: {', '.join(record.keywords) or 'None'}\n"
            f"Media: {record.photo_count} photos, {record.video_count} videos, "
            f"{record.unedited_jpg_count} unedited JPGs\n"
            f"Folder: {record.event_folder}"
        )

    def _open_selected_folder(self, _event: tk.Event | None = None) -> None:
        record = self._selected_record()
        if record is None:
            messagebox.showinfo("No Event Selected", "Select an event first.")
            return

        try:
            if os.name == "posix":
                subprocess.Popen(["open", str(record.event_folder)])
            else:
                os.startfile(record.event_folder)  # type: ignore[attr-defined]
        except Exception as exc:
            messagebox.showerror("Folder Not Opened", str(exc))

    def _selected_record(self) -> MetadataSearchRecord | None:
        selection = self.results_tree.selection()
        if not selection:
            return None
        return self.records_by_id.get(selection[0])

    def _clear_filters(self) -> None:
        self.query_var.set("")
        self.school_year_var.set("Any school year")
        self.grade_var.set("Any grade")
        self.keyword_var.set("Any keyword")
        self._apply_filters()

    def _ensure_filter_values(self) -> None:
        if self.school_year_var.get() not in {"Any school year", *self.index.school_years}:
            self.school_year_var.set("Any school year")
        if self.grade_var.get() not in {"Any grade", *self.index.grades}:
            self.grade_var.set("Any grade")
        if self.keyword_var.get() not in {"Any keyword", *self.index.keywords}:
            self.keyword_var.set("Any keyword")

    def _selected_roots(self) -> dict[str, Path]:
        source = self.source_var.get()
        if source == "Current year":
            return {
                "Google Drive": AppConfig.EVENT_ROOT,
                "Local Events": AppConfig.LOCAL_EVENT_ROOT,
            }
        if source == "Google Drive":
            return {"Google Drive": AppConfig.ARCHIVE_DRIVE_ROOT}
        if source == "Local Events":
            return {"Local Events": AppConfig.ARCHIVE_SOURCE_ROOT}
        return {
            "Google Drive": AppConfig.ARCHIVE_DRIVE_ROOT,
            "Local Events": AppConfig.ARCHIVE_SOURCE_ROOT,
        }

    def _refresh_roots_label(self) -> None:
        self.root_summary_var.set(
            "Searching metadata in configured event folders. "
            f"Current year: {AppConfig.EVENT_ROOT} and {AppConfig.LOCAL_EVENT_ROOT}"
        )

    def _set_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)
