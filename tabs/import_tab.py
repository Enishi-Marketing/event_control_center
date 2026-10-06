import json
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from config.config import AppConfig
from services.drive_detector import DriveDetector, ImportSource
from services.folder_service import EventFolderResult, FolderService
from services.importer import (
    ImportProgress,
    ImportService,
    MediaFile,
    MediaScanResult,
    MediaSession,
)
from services.keyword_service import KeywordVocabulary, keyword_key
from services.metadata_service import MetadataService
from services.project_service import ProjectCreationSummary, ProjectService
from services.search_service import MetadataSearchService
from services.source_cleanup_service import SourceCleanupResult, SourceCleanupService
from services.unedited_jpg_service import (
    UneditedJpgProgress,
    UneditedJpgService,
    UneditedJpgSummary,
)


class KeywordPillInput(ttk.Frame):
    """Reusable free-form keyword pills with event vocabulary suggestions."""

    def __init__(
        self,
        master: tk.Widget,
        vocabulary: KeywordVocabulary | None = None,
    ) -> None:
        super().__init__(master)
        self.vocabulary = vocabulary or KeywordVocabulary()
        self.keywords: list[str] = []
        self.pending_var = tk.StringVar()
        self.matches: list[str] = []

        self.columnconfigure(1, weight=1)
        self.pills_frame = ttk.Frame(self)
        self.pills_frame.grid(row=0, column=0, sticky="w")
        self.entry = ttk.Entry(self, textvariable=self.pending_var)
        self.entry.grid(row=0, column=1, sticky="ew")
        self.entry.bind("<Return>", self._return_pressed)
        self.entry.bind("<Down>", self._move_selection)
        self.entry.bind("<Up>", self._move_selection)
        self.entry.bind("<Escape>", self._close_suggestions)
        self.entry.bind("<BackSpace>", self._backspace)
        self.entry.bind("<FocusOut>", self._focus_out)
        self.pending_var.trace_add("write", self._keywords_typed)
        self.suggestion_list = tk.Listbox(self, height=6, exportselection=False)
        self.suggestion_list.grid(row=1, column=1, sticky="ew")
        self.suggestion_list.grid_remove()
        self.suggestion_list.bind("<ButtonRelease-1>", self._select_suggestion)

    def set_vocabulary(self, vocabulary: KeywordVocabulary) -> None:
        self.vocabulary = vocabulary
        self.keywords = vocabulary.canonicalize(self.keywords)
        self._render_pills()
        self._show_suggestions()

    def get_text(self) -> str:
        return ", ".join(self.get_keywords())

    def get_keywords(self) -> list[str]:
        self._commit_pending(keep_tail=False)
        return list(self.keywords)

    def _keywords_typed(self, *_args: object) -> None:
        if "," in self.pending_var.get():
            self._commit_pending(keep_tail=True)
        self._show_suggestions()

    def _show_suggestions(self) -> None:
        query = self.pending_var.get().strip()
        self.suggestion_list.delete(0, tk.END)
        if not query:
            self.suggestion_list.grid_remove()
            return
        self.matches = [entry.display_value for entry in self.vocabulary.suggest(query, self.keywords)]
        for display in self.matches:
            self.suggestion_list.insert(tk.END, display)
        if keyword_key(query) not in self.vocabulary.by_key:
            self.suggestion_list.insert(tk.END, f'Add "{query}" as new keyword')
        if self.suggestion_list.size():
            self.suggestion_list.configure(height=min(self.suggestion_list.size(), 7))
            self.suggestion_list.grid()
        else:
            self.suggestion_list.grid_remove()

    def _move_selection(self, event: tk.Event) -> str:
        if not self.suggestion_list.winfo_ismapped():
            self._show_suggestions()
        count = self.suggestion_list.size()
        if count:
            current = self.suggestion_list.curselection()
            step = 1 if event.keysym == "Down" else -1
            selected = min(max((current[0] if current else -1) + step, 0), count - 1)
            self.suggestion_list.selection_clear(0, tk.END)
            self.suggestion_list.selection_set(selected)
        return "break"

    def _return_pressed(self, _event: tk.Event) -> str:
        selected = self.suggestion_list.curselection() if self.suggestion_list.winfo_ismapped() else ()
        if selected and selected[0] < len(self.matches):
            self._add_keyword(self.matches[selected[0]])
        elif not selected and self.suggestion_list.winfo_ismapped() and self.matches:
            self._add_keyword(self.matches[0])
        else:
            self._commit_pending(keep_tail=False)
        return "break"

    def _select_suggestion(self, _event: tk.Event) -> None:
        selected = self.suggestion_list.curselection()
        if selected:
            self._add_keyword(self.matches[selected[0]] if selected[0] < len(self.matches) else self.pending_var.get())
            self.entry.focus_set()

    def _close_suggestions(self, _event: tk.Event) -> str:
        self.suggestion_list.grid_remove()
        return "break"

    def _backspace(self, _event: tk.Event) -> str | None:
        if not self.pending_var.get() and self.keywords:
            self.keywords.pop()
            self._render_pills()
            return "break"
        return None

    def _focus_out(self, _event: tk.Event) -> None:
        self.after(100, self._commit_if_unfocused)

    def _commit_if_unfocused(self) -> None:
        if self.focus_get() not in {self.entry, self.suggestion_list}:
            self._commit_pending(keep_tail=False)
            self.suggestion_list.grid_remove()

    def _commit_pending(self, keep_tail: bool) -> None:
        pending = self.pending_var.get()
        if keep_tail:
            parts = pending.split(",")
            values_to_commit = parts[:-1]
            tail = parts[-1]
        else:
            values_to_commit = [pending]
            tail = ""

        normalized = self.vocabulary.canonicalize([*self.keywords, *values_to_commit])
        if normalized != self.keywords:
            self.keywords = normalized
            self._render_pills()
        self.pending_var.set(tail.lstrip())

    def _add_keyword(self, keyword: str) -> None:
        self.keywords = self.vocabulary.canonicalize([*self.keywords, keyword])
        self._render_pills()
        self.pending_var.set("")
        self.suggestion_list.grid_remove()

    def _render_pills(self) -> None:
        for child in self.pills_frame.winfo_children():
            child.destroy()

        for keyword in self.keywords:
            pill = tk.Frame(self.pills_frame, bg="#dfe7f3", padx=8, pady=2)
            pill.pack(side="left", padx=(0, 6), pady=1)
            tk.Label(
                pill,
                text=keyword,
                bg="#dfe7f3",
                fg="#202428",
                borderwidth=0,
            ).pack(side="left")
            tk.Button(
                pill,
                text="x",
                command=lambda value=keyword: self._remove_keyword(value),
                bg="#dfe7f3",
                fg="#202428",
                activebackground="#cfd9e8",
                activeforeground="#202428",
                borderwidth=0,
                highlightthickness=0,
                padx=4,
                pady=0,
            ).pack(side="left", padx=(4, 0))

    def _remove_keyword(self, keyword: str) -> None:
        self.keywords = [value for value in self.keywords if value != keyword]
        self._render_pills()


class ImportTab(ttk.Frame):
    """Creates event folders and imports verified media into them."""

    GRADE_GROUPS = {
        "School-wide": ["All", "Staff", "Parents"],
        "School Sections": ["ELC", "PYP", "MYP", "DP"],
        "Early Years": ["Foundation", "Preschool", "PreK", "Kindergarten"],
        "Year Levels": [f"Grade {grade}" for grade in range(1, 13)],
    }

    def __init__(
        self,
        master: tk.Widget,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, padding=0)
        self.status_callback = status_callback
        self.metadata_service = MetadataService()
        self.destination_roots = self._destination_roots()
        self.folder_service = FolderService(AppConfig.EVENT_ROOT)
        self.drive_detector = DriveDetector()
        self.import_service = ImportService()
        self.unedited_jpg_service = UneditedJpgService()
        self.project_service = ProjectService()
        self.source_cleanup_service = SourceCleanupService()

        self.grade_variables: dict[str, tk.BooleanVar] = {}
        self.session_variables: dict[int, tk.BooleanVar] = {}
        self.sources: list[ImportSource] = []
        self.scan_result: MediaScanResult | None = None
        self.current_event: EventFolderResult | None = None
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self._keyword_load_sequence = 0
        self.cancel_event: threading.Event | None = None
        self.worker_thread: threading.Thread | None = None
        self.thumbnail_images: list[tk.PhotoImage] = []

        self.event_name_var = tk.StringVar()
        self.event_date_var = tk.StringVar(value=datetime.now().strftime("%Y.%m.%d"))
        self.destination_var = tk.StringVar(value="Google Drive")
        self.school_year_var = tk.StringVar(value=AppConfig.DEFAULT_SCHOOL_YEAR)
        self.source_var = tk.StringVar()
        self.source_path_var = tk.StringVar(value="No source selected")
        self.session_gap_var = tk.IntVar(value=AppConfig.DEFAULT_SESSION_GAP_MINUTES)
        self.scan_summary_var = tk.StringVar(value="Scan a source to see media counts.")
        self.event_folder_var = tk.StringVar(value="No event folder created yet.")
        self.current_file_var = tk.StringVar(value="")
        self.current_file_detail_var = tk.StringVar(value="")
        self.transfer_speed_var = tk.StringVar(value="")
        self.activity_var = tk.StringVar(value="")
        self.timeline_start_var = tk.StringVar()
        self.timeline_end_var = tk.StringVar()
        self.timeline_count_var = tk.StringVar(value="")
        self.spinner_running = False
        self.spinner_index = 0

        self.event_name_var.trace_add("write", self._event_identity_changed)
        self.event_date_var.trace_add("write", self._event_identity_changed)
        self.destination_var.trace_add("write", self._event_identity_changed)
        self._build_layout()
        self._load_sources()
        self.after(100, self._poll_worker_queue)
        self._load_keyword_vocabulary()

    def _load_keyword_vocabulary(self) -> None:
        self._keyword_load_sequence += 1
        sequence = self._keyword_load_sequence
        roots = {"Local Events": AppConfig.ARCHIVE_SOURCE_ROOT}
        if AppConfig.SHARED_DRIVE_CONFIGURED:
            roots["Google Drive"] = AppConfig.ARCHIVE_DRIVE_ROOT
        threading.Thread(
            target=self._keyword_vocabulary_worker, args=(roots, sequence), daemon=True
        ).start()

    def _keyword_vocabulary_worker(self, roots: dict[str, Path], sequence: int) -> None:
        try:
            self.worker_queue.put(("keyword_vocabulary", (sequence, self._build_keyword_vocabulary(roots))))
        except Exception:
            pass  # Free-form entry remains available if a root cannot be scanned.

    @staticmethod
    def _build_keyword_vocabulary(roots: dict[str, Path]) -> KeywordVocabulary:
        index = MetadataSearchService().build_index(roots)
        return KeywordVocabulary.from_events(index.records)

    def _build_layout(self) -> None:
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas, padding=18)
        self.window_id = self.canvas.create_window(
            (0, 0),
            window=self.content,
            anchor="nw",
        )
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.canvas.bind("<Configure>", self._resize_content)
        self.content.bind("<Configure>", self._update_scroll_region)

        self.content.columnconfigure(0, weight=1)
        self._build_event_details()
        self._build_import_source()
        self._build_scan_results()
        self._build_progress()
        self._bind_mousewheel_area(self.content)

    def _build_event_details(self) -> None:
        details_frame = ttk.LabelFrame(self.content, text="Event Details", padding=14)
        details_frame.grid(row=0, column=0, sticky="ew")
        details_frame.columnconfigure(1, weight=1)

        ttk.Label(details_frame, text="Event Name").grid(row=0, column=0, sticky="w")
        ttk.Entry(details_frame, textvariable=self.event_name_var).grid(
            row=0, column=1, sticky="ew", padx=(12, 0), pady=(0, 10)
        )

        ttk.Label(details_frame, text="Event Date").grid(row=1, column=0, sticky="w")
        ttk.Entry(details_frame, textvariable=self.event_date_var).grid(
            row=1, column=1, sticky="ew", padx=(12, 0), pady=(0, 10)
        )

        ttk.Label(details_frame, text="Import To").grid(row=2, column=0, sticky="w")
        destination_frame = ttk.Frame(details_frame)
        destination_frame.grid(
            row=2,
            column=1,
            sticky="w",
            padx=(12, 0),
            pady=(0, 10),
        )
        for column, destination in enumerate(self.destination_roots):
            ttk.Radiobutton(
                destination_frame,
                text=destination,
                value=destination,
                variable=self.destination_var,
            ).grid(row=0, column=column, sticky="w", padx=(0, 18))

        ttk.Label(details_frame, text="School Year").grid(row=3, column=0, sticky="w")
        ttk.Entry(details_frame, textvariable=self.school_year_var).grid(
            row=3, column=1, sticky="ew", padx=(12, 0), pady=(0, 10)
        )

        ttk.Label(details_frame, text="Keywords").grid(row=4, column=0, sticky="w")
        self.keyword_input = KeywordPillInput(
            details_frame,
        )
        self.keyword_input.grid(
            row=4, column=1, sticky="ew", padx=(12, 0), pady=(0, 10)
        )

        ttk.Label(details_frame, text="Description").grid(row=5, column=0, sticky="nw")
        self.description_text = tk.Text(
            details_frame,
            height=4,
            wrap="word",
            borderwidth=1,
            relief="solid",
            highlightthickness=0,
        )
        self.description_text.grid(row=5, column=1, sticky="ew", padx=(12, 0))

        grades_frame = ttk.LabelFrame(self.content, text="Grades", padding=14)
        grades_frame.grid(row=1, column=0, sticky="nsew", pady=(16, 0))
        grades_frame.columnconfigure((0, 1), weight=1, uniform="grade_columns")

        for index, (group_name, values) in enumerate(self.GRADE_GROUPS.items()):
            group = ttk.LabelFrame(grades_frame, text=group_name, padding=10)
            group.grid(
                row=index // 2,
                column=index % 2,
                sticky="nsew",
                padx=(0 if index % 2 == 0 else 8, 0),
                pady=(0, 12),
            )
            self._add_grade_checkboxes(group, values)

        event_row = ttk.Frame(self.content)
        event_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        event_row.columnconfigure(0, weight=1)
        ttk.Label(event_row, textvariable=self.event_folder_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            event_row,
            text="Create Event",
            command=self._create_event,
            style="Primary.TButton",
        ).grid(row=0, column=1, sticky="e")

    def _build_import_source(self) -> None:
        source_frame = ttk.LabelFrame(self.content, text="Import Source", padding=14)
        source_frame.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        source_frame.columnconfigure(1, weight=1)

        ttk.Label(source_frame, text="Camera SD Card").grid(row=0, column=0, sticky="w")
        self.source_combo = ttk.Combobox(
            source_frame,
            textvariable=self.source_var,
            state="readonly",
        )
        self.source_combo.grid(row=0, column=1, sticky="ew", padx=(12, 8))
        self.source_combo.bind("<<ComboboxSelected>>", self._source_selected)

        ttk.Button(source_frame, text="Refresh", command=self._load_sources).grid(
            row=0, column=2, sticky="e"
        )
        ttk.Button(source_frame, text="Browse...", command=self._browse_source).grid(
            row=0, column=3, sticky="e", padx=(8, 0)
        )

        ttk.Label(source_frame, textvariable=self.source_path_var).grid(
            row=1, column=1, columnspan=3, sticky="w", padx=(12, 0), pady=(8, 10)
        )
        ttk.Label(source_frame, text="Session Gap").grid(row=2, column=0, sticky="w")
        ttk.Spinbox(
            source_frame,
            from_=1,
            to=120,
            textvariable=self.session_gap_var,
            width=8,
        ).grid(row=2, column=1, sticky="w", padx=(12, 0))
        ttk.Label(source_frame, text="minutes").grid(
            row=2,
            column=1,
            sticky="w",
            padx=(82, 0),
        )

        self.scan_button = ttk.Button(
            source_frame,
            text="Scan Media",
            command=self._start_scan,
            style="Primary.TButton",
        )
        self.scan_button.grid(row=2, column=3, sticky="e", pady=(4, 0))

    def _build_scan_results(self) -> None:
        self.scan_frame = ttk.LabelFrame(self.content, text="Media Scan", padding=14)
        self.scan_frame.grid(row=4, column=0, sticky="ew", pady=(18, 0))
        self.scan_frame.columnconfigure(0, weight=1)

        ttk.Label(self.scan_frame, textvariable=self.scan_summary_var).grid(
            row=0, column=0, sticky="w"
        )
        self.selection_frame = ttk.Frame(self.scan_frame)
        self.selection_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))
        self.selection_frame.columnconfigure(0, weight=1)

        action_row = ttk.Frame(self.scan_frame)
        action_row.grid(row=2, column=0, sticky="ew", pady=(14, 0))
        action_row.columnconfigure(0, weight=1)
        self.import_button = ttk.Button(
            action_row,
            text="Import Selected Media",
            command=self._start_import,
            state="disabled",
            style="Primary.TButton",
        )
        self.import_button.grid(row=0, column=1, sticky="e")
        self.cancel_button = ttk.Button(
            action_row,
            text="Cancel",
            command=self._cancel_import,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=2, sticky="e", padx=(8, 0))

    def _build_progress(self) -> None:
        progress_frame = ttk.LabelFrame(self.content, text="Progress", padding=14)
        progress_frame.grid(row=5, column=0, sticky="ew", pady=(18, 0))
        progress_frame.columnconfigure(0, weight=1)

        status_row = ttk.Frame(progress_frame)
        status_row.grid(row=0, column=0, sticky="ew")
        status_row.columnconfigure(1, weight=1)
        ttk.Label(status_row, textvariable=self.activity_var, width=3).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(status_row, textvariable=self.current_file_var).grid(
            row=0, column=1, sticky="w"
        )

        ttk.Label(progress_frame, text="Overall").grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        self.progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.progress_bar.grid(row=2, column=0, sticky="ew", pady=(4, 0))
        ttk.Label(progress_frame, text="Current file").grid(
            row=3, column=0, sticky="w", pady=(8, 0)
        )
        self.file_progress_bar = ttk.Progressbar(progress_frame, mode="determinate")
        self.file_progress_bar.grid(row=4, column=0, sticky="ew", pady=(4, 0))
        detail_row = ttk.Frame(progress_frame)
        detail_row.grid(row=5, column=0, sticky="ew", pady=(6, 0))
        detail_row.columnconfigure(0, weight=1)
        ttk.Label(detail_row, textvariable=self.current_file_detail_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(detail_row, textvariable=self.transfer_speed_var).grid(
            row=0, column=1, sticky="e"
        )

    def _add_grade_checkboxes(self, parent: ttk.LabelFrame, values: list[str]) -> None:
        columns = 2 if len(values) > 4 else 1
        for index, value in enumerate(values):
            variable = tk.BooleanVar(value=False)
            self.grade_variables[value] = variable
            ttk.Checkbutton(parent, text=value, variable=variable).grid(
                row=index // columns,
                column=index % columns,
                sticky="w",
                padx=(0, 18),
                pady=3,
            )

    def _create_event(self) -> bool:
        if not self._validate_inputs():
            return False

        event_name = self.event_name_var.get().strip()
        event_date = self.event_date_var.get().strip()
        self.folder_service = FolderService(self._selected_event_root())

        if self.folder_service.event_exists(event_date, event_name):
            if not self._confirm_metadata_overwrite():
                self._set_status("Ready")
                return False

        self._set_status("Creating folders...")
        folder_result = self.folder_service.create_event_folders(event_date, event_name)

        self._set_status("Writing metadata...")
        roots = {"Local Events": AppConfig.ARCHIVE_SOURCE_ROOT}
        if AppConfig.SHARED_DRIVE_CONFIGURED:
            roots["Google Drive"] = AppConfig.ARCHIVE_DRIVE_ROOT
        self.keyword_input.set_vocabulary(self._build_keyword_vocabulary(roots))
        metadata = self.metadata_service.create_metadata(
            event_name=event_name,
            event_date=event_date,
            school_year=self.school_year_var.get(),
            description=self.description_text.get("1.0", "end").strip(),
            keywords_text=self.keyword_input.get_text(),
            grades=self._selected_grades(),
            keyword_vocabulary=self.keyword_input.vocabulary,
        )
        self.metadata_service.write_metadata(folder_result.metadata_path, metadata)
        self._load_keyword_vocabulary()

        self.current_event = folder_result
        self.event_folder_var.set(f"Event folder: {folder_result.event_folder}")
        print(json.dumps(metadata, indent=4), flush=True)
        self._set_status("Done.")
        self._show_success(folder_result.event_folder.name)
        self._refresh_import_state()
        return True

    def _selected_event_root(self) -> Path:
        return self.destination_roots.get(
            self.destination_var.get(),
            AppConfig.EVENT_ROOT,
        )

    def refresh_settings(self) -> None:
        self.destination_roots = self._destination_roots()
        self.school_year_var.set(AppConfig.DEFAULT_SCHOOL_YEAR)
        self._event_identity_changed()
        self._load_keyword_vocabulary()

    def _destination_roots(self) -> dict[str, Path]:
        return {
            "Google Drive": AppConfig.EVENT_ROOT,
            "Local Events Folder": AppConfig.LOCAL_EVENT_ROOT,
        }

    def _load_sources(self) -> None:
        self.sources = self.drive_detector.available_sources()
        values = [source.name for source in self.sources]
        self.source_combo.configure(values=values)

        if self.sources:
            self.source_combo.current(0)
            self._set_source(self.sources[0])
        else:
            self.source_var.set("")
            self.source_path_var.set("No removable media detected. Browse for a folder.")
            self._reset_scan_card("Scan a source to see media counts.")

    def _source_selected(self, _event: tk.Event) -> None:
        index = self.source_combo.current()
        if 0 <= index < len(self.sources):
            self._set_source(self.sources[index])

    def _set_source(self, source: ImportSource) -> None:
        self.source_var.set(source.name)
        self.source_path_var.set(str(source.path))
        self._reset_scan_card("Scan this source to see media counts.")

    def _reset_scan_card(self, summary_text: str) -> None:
        self.scan_result = None
        self.scan_summary_var.set(summary_text)
        self._clear_selection_frame()
        self._refresh_import_state()

    def _browse_source(self) -> None:
        selected = filedialog.askdirectory(title="Choose Import Source")
        if not selected:
            return

        source = ImportSource(name=Path(selected).name or selected, path=Path(selected))
        self.sources.append(source)
        self.source_combo.configure(values=[item.name for item in self.sources])
        self.source_combo.current(len(self.sources) - 1)
        self._set_source(source)

    def _start_scan(self) -> None:
        source = self._selected_source_path()
        if source is None:
            messagebox.showerror("Missing Source", "Please choose an import source.")
            return

        self._set_busy(True)
        self._set_status("Scanning Media...")
        self.scan_summary_var.set("Scanning Media...")
        self.current_file_var.set("")
        self.current_file_detail_var.set("")
        self.transfer_speed_var.set("")
        self.progress_bar.configure(value=0, maximum=100)
        self.file_progress_bar.configure(value=0, maximum=100)
        self._set_progress_active(True)

        gap_minutes = max(1, int(self.session_gap_var.get()))
        thread = threading.Thread(
            target=self._scan_worker,
            args=(source, gap_minutes),
            daemon=True,
        )
        self.worker_thread = thread
        thread.start()

    def _scan_worker(self, source: Path, gap_minutes: int) -> None:
        try:
            result = self.import_service.scan_media(source, gap_minutes)
            self.worker_queue.put(("scan_success", result))
        except Exception as exc:
            self.worker_queue.put(("scan_error", str(exc)))

    def _show_scan_result(self, result: MediaScanResult) -> None:
        self.scan_result = result
        time_text = self._capture_time_text(result)
        failure_text = (
            f"\nRead Issues: {len(result.failures)}" if result.failures else ""
        )
        preview_text = (
            f"\nPreview Issues: {len(result.thumbnail_failures)}"
            if result.thumbnail_failures
            else ""
        )
        self.scan_summary_var.set(
            "Found:\n"
            f"{result.photo_count} Photos\n"
            f"{result.video_count} Videos\n"
            f"Capture Time: {time_text}"
            f"{failure_text}"
            f"{preview_text}"
        )
        self._render_selection_controls(result)
        self._set_status(
            f"Found {result.photo_count} photos and {result.video_count} videos."
        )
        self._refresh_import_state()

    def _render_selection_controls(self, result: MediaScanResult) -> None:
        self._clear_selection_frame()
        if len(result.sessions) <= 6:
            self._render_session_cards(result)
        else:
            self._render_timeline_mode(result)

    def _render_session_cards(self, result: MediaScanResult) -> None:
        self.session_variables = {}
        self.thumbnail_images = []
        controls = ttk.Frame(self.selection_frame)
        controls.grid(row=0, column=0, sticky="ew")
        ttk.Button(
            controls,
            text="Select All Sessions",
            command=self._select_all_sessions,
        ).grid(row=0, column=0, sticky="w")
        ttk.Button(
            controls,
            text="Select None",
            command=self._select_no_sessions,
        ).grid(row=0, column=1, sticky="w", padx=(8, 0))

        for row, session in enumerate(result.sessions, start=1):
            variable = tk.BooleanVar(value=True)
            self.session_variables[session.index] = variable
            label = (
                f"Session {session.index}\n"
                f"{session.start_time:%H:%M} - {session.end_time:%H:%M}\n"
                f"{session.photo_count} Photos\n"
                f"{session.video_count} Videos"
            )
            session_frame = ttk.Frame(self.selection_frame)
            session_frame.grid(row=row, column=0, sticky="ew", pady=(8, 0))
            session_frame.columnconfigure(1, weight=1)
            ttk.Checkbutton(
                session_frame,
                text=label,
                variable=variable,
                command=self._refresh_import_state,
            ).grid(row=0, column=0, sticky="nw")
            self._render_session_thumbnails(session_frame, session)

    def _render_timeline_mode(self, result: MediaScanResult) -> None:
        times = [
            item.capture_time.strftime("%Y-%m-%d %H:%M:%S")
            for item in result.files
        ]
        ttk.Label(self.selection_frame, text="Start Time").grid(
            row=0,
            column=0,
            sticky="w",
        )
        start_combo = ttk.Combobox(
            self.selection_frame,
            textvariable=self.timeline_start_var,
            values=times,
            state="readonly",
            width=24,
        )
        start_combo.grid(row=0, column=1, sticky="w", padx=(12, 0))

        ttk.Label(self.selection_frame, text="End Time").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(8, 0),
        )
        end_combo = ttk.Combobox(
            self.selection_frame,
            textvariable=self.timeline_end_var,
            values=times,
            state="readonly",
            width=24,
        )
        end_combo.grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(8, 0))

        self.timeline_start_var.set(times[0])
        self.timeline_end_var.set(times[-1])
        start_combo.bind("<<ComboboxSelected>>", self._timeline_changed)
        end_combo.bind("<<ComboboxSelected>>", self._timeline_changed)

        ttk.Label(self.selection_frame, textvariable=self.timeline_count_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(10, 0)
        )
        self._timeline_changed()

    def _timeline_changed(self, _event: tk.Event | None = None) -> None:
        files = self._selected_files()
        photos = sum(1 for item in files if item.media_type == "photo")
        videos = sum(1 for item in files if item.media_type == "video")
        self.timeline_count_var.set(f"{photos} Photos, {videos} Videos selected")
        self._refresh_import_state()

    def _start_import(self) -> None:
        if self.current_event is None and not self._create_event():
            return

        if self.current_event is None:
            return

        files = self._selected_files()
        if not files:
            messagebox.showerror("No Media Selected", "Please select media to import.")
            return

        source = self._selected_source_path()
        if source is None:
            messagebox.showerror("Missing Source", "Please choose an import source.")
            return

        self.cancel_event = threading.Event()
        self._set_busy(True, importing=True)
        self.progress_bar.configure(value=0, maximum=len(files))
        self.file_progress_bar.configure(value=0, maximum=100)
        self.current_file_var.set("")
        self.current_file_detail_var.set("")
        self.transfer_speed_var.set("")
        self._set_status(f"Importing 0 / {len(files)} Files")
        self._set_progress_active(True)

        thread = threading.Thread(
            target=self._import_worker,
            args=(files, self.current_event.event_folder, source, self.cancel_event),
            daemon=True,
        )
        self.worker_thread = thread
        thread.start()

    def _import_worker(
        self,
        files: list[MediaFile],
        event_folder: Path,
        source: Path,
        cancel_event: threading.Event,
    ) -> None:
        try:
            summary = self.import_service.import_media(
                files=files,
                event_folder=event_folder,
                source=source,
                cancel_event=cancel_event,
                skipped_count=self._skipped_count_for(files),
                event_name=self.event_name_var.get(),
                progress_callback=lambda progress: self.worker_queue.put(
                    ("import_progress", progress)
                ),
            )
            jpg_summary = UneditedJpgSummary(cancelled=True)
            if not summary.cancelled:
                self.worker_queue.put(("stage_progress", "Generating Unedited JPGs..."))
                jpg_summary = self.unedited_jpg_service.generate_for_event(
                    event_folder=event_folder,
                    cancel_event=cancel_event,
                    progress_callback=lambda progress: self.worker_queue.put(
                        ("jpg_progress", progress)
                    ),
                )
            project_summary = ProjectCreationSummary()
            if not summary.cancelled:
                self.worker_queue.put(
                    ("project_progress", "Creating editing projects...")
                )
                project_summary = self.project_service.create_projects(
                    event_folder=event_folder,
                    event_name=self.event_name_var.get(),
                    has_photos=summary.photos_imported > 0,
                    has_videos=summary.videos_imported > 0,
                )
            self.worker_queue.put(
                ("import_success", (summary, jpg_summary, project_summary, source))
            )
        except Exception as exc:
            self.worker_queue.put(("import_error", str(exc)))

    def _source_cleanup_worker(self, files: list[Path], source: Path) -> None:
        try:
            result = self.source_cleanup_service.cleanup_imported_files(files, source)
            self.worker_queue.put(("source_cleanup_success", result))
        except Exception as exc:
            self.worker_queue.put(("source_cleanup_error", str(exc)))

    def _cancel_import(self) -> None:
        if self.cancel_event is not None:
            self.cancel_event.set()
            self._set_status("Cancelling after the current file...")

    def _poll_worker_queue(self) -> None:
        try:
            while True:
                message, payload = self.worker_queue.get_nowait()
                self._handle_worker_message(message, payload)
        except queue.Empty:
            pass
        finally:
            self.after(100, self._poll_worker_queue)

    def _handle_worker_message(self, message: str, payload: object) -> None:
        if message == "keyword_vocabulary" and isinstance(payload, tuple):
            sequence, vocabulary = payload
            if sequence == self._keyword_load_sequence:
                self.keyword_input.set_vocabulary(vocabulary)
        elif message == "scan_success" and isinstance(payload, MediaScanResult):
            self._set_busy(False)
            self._set_progress_active(False)
            self._show_scan_result(payload)
        elif message == "scan_error":
            self._set_busy(False)
            self._set_progress_active(False)
            self._show_error("Scan Failed", str(payload))
        elif message == "import_progress" and isinstance(payload, ImportProgress):
            self._update_import_progress(payload)
        elif message == "jpg_progress" and isinstance(payload, UneditedJpgProgress):
            self._update_jpg_progress(payload)
        elif message == "stage_progress":
            self.current_file_var.set(str(payload))
            self.current_file_detail_var.set("")
            self.transfer_speed_var.set("")
            self.file_progress_bar.configure(value=0, maximum=100)
            self._set_status(str(payload))
        elif message == "project_progress":
            self.current_file_var.set(str(payload))
            self.current_file_detail_var.set("Finishing project setup")
            self.transfer_speed_var.set("")
            self.file_progress_bar.configure(value=0, maximum=100)
            self._set_status(str(payload))
        elif message == "import_success":
            self._set_busy(False)
            self._set_progress_active(False)
            self._show_import_summary(payload)
        elif message == "import_error":
            self._set_busy(False)
            self._set_progress_active(False)
            self._show_error("Import Failed", str(payload))
        elif message == "source_cleanup_success" and isinstance(
            payload, SourceCleanupResult
        ):
            self._set_busy(False)
            self._set_progress_active(False)
            self._show_source_cleanup_result(payload)
        elif message == "source_cleanup_error":
            self._set_busy(False)
            self._set_progress_active(False)
            self._show_error("Delete and Eject Failed", str(payload))

    def _update_import_progress(self, progress: ImportProgress) -> None:
        self.progress_bar.configure(
            maximum=max(progress.total, 1),
            value=progress.current,
        )
        if progress.current_file is not None:
            phase = progress.phase or "Importing"
            self.current_file_var.set(f"{phase}: {progress.current_file.name}")
            self._update_file_progress(progress)
            self._set_status(f"Importing {progress.current} / {progress.total} Files")
        elif progress.message:
            self.current_file_var.set(progress.message)
            self.current_file_detail_var.set("")
            self.transfer_speed_var.set("")
            self.file_progress_bar.configure(value=100, maximum=100)

    def _update_jpg_progress(self, progress: UneditedJpgProgress) -> None:
        self.progress_bar.configure(
            maximum=max(progress.total, 1),
            value=progress.current,
        )
        self.file_progress_bar.configure(value=0, maximum=100)
        self.transfer_speed_var.set("")
        if progress.current_file is not None:
            remaining = max(progress.total - progress.current, 0)
            self.current_file_var.set(
                f"{progress.current_file.name} - {remaining} remaining"
            )
            self.current_file_detail_var.set("Generating JPG preview copy")
            self._set_status(
                f"Generating Unedited JPGs... {progress.current} / {progress.total}"
            )
        elif progress.message:
            self.current_file_var.set(progress.message)
            self.current_file_detail_var.set("")

    def _update_file_progress(self, progress: ImportProgress) -> None:
        total_bytes = max(progress.total_bytes, 0)
        current_bytes = min(max(progress.current_bytes, 0), total_bytes)
        if total_bytes <= 0:
            self.file_progress_bar.configure(value=0, maximum=100)
            self.current_file_detail_var.set("")
            self.transfer_speed_var.set("")
            return

        percent = current_bytes / total_bytes * 100
        self.file_progress_bar.configure(maximum=total_bytes, value=current_bytes)
        self.current_file_detail_var.set(
            f"{self._format_bytes(current_bytes)} of {self._format_bytes(total_bytes)} "
            f"({percent:.0f}%)"
        )
        if progress.bytes_per_second > 0:
            self.transfer_speed_var.set(
                f"{self._format_bytes(progress.bytes_per_second)}/s"
            )
        elif progress.phase == "Verifying":
            self.transfer_speed_var.set("Verifying")
        else:
            self.transfer_speed_var.set("")

    def _show_import_summary(self, summary: object) -> None:
        import_summary = summary
        jpg_summary = UneditedJpgSummary()
        project_summary = ProjectCreationSummary()
        source = self._selected_source_path()
        if isinstance(summary, tuple):
            if len(summary) == 2:
                import_summary, jpg_summary = summary
            elif len(summary) == 3:
                import_summary, jpg_summary, project_summary = summary
            elif len(summary) == 4:
                import_summary, jpg_summary, project_summary, source = summary

        photos = getattr(import_summary, "photos_imported", 0)
        videos = getattr(import_summary, "videos_imported", 0)
        skipped = getattr(import_summary, "skipped", 0)
        failed = getattr(import_summary, "failed", 0)
        cancelled = getattr(import_summary, "cancelled", False)
        jpg_generated = getattr(jpg_summary, "generated", 0)
        jpg_skipped = getattr(jpg_summary, "skipped", 0)
        jpg_failed = getattr(jpg_summary, "failed", 0)
        project_failures = getattr(project_summary, "failures", [])
        project_warning_text = (
            "\n" + "\n".join(str(failure) for failure in project_failures)
            if project_failures
            else ""
        )
        lightroom_text = self._project_status_text(
            getattr(project_summary, "lightroom_created", False),
            getattr(project_summary, "lightroom_skipped", False),
            photos > 0,
        )
        premiere_text = self._project_status_text(
            getattr(project_summary, "premiere_created", False),
            getattr(project_summary, "premiere_skipped", False),
            videos > 0,
        )
        title = "Import Cancelled" if cancelled else "Import Complete"
        self._set_status(title)
        self.current_file_var.set(title)
        self.current_file_detail_var.set("")
        self.transfer_speed_var.set("")
        self.file_progress_bar.configure(value=0, maximum=100)
        messagebox.showinfo(
            title,
            f"{title}\n"
            f"Photos Imported:\n{photos}\n"
            f"Videos Imported:\n{videos}\n"
            f"Skipped:\n{skipped}\n"
            f"Failed:\n{failed}\n"
            f"Unedited JPGs Generated:\n{jpg_generated}\n"
            f"Unedited JPGs Skipped:\n{jpg_skipped}\n"
            f"Unedited JPG Failures:\n{jpg_failed}\n"
            f"Lightroom Project:\n{lightroom_text}\n"
            f"Premiere Project:\n{premiere_text}\n"
            f"Project Warnings:\n{len(project_failures)}"
            f"{project_warning_text}",
        )
        self._prompt_source_cleanup(import_summary, source)

    def _prompt_source_cleanup(
        self,
        import_summary: object,
        source: Path | None,
    ) -> None:
        if source is None:
            return

        cancelled = getattr(import_summary, "cancelled", False)
        imported_sources = list(getattr(import_summary, "imported_sources", []))
        if cancelled or not imported_sources:
            return

        failed = getattr(import_summary, "failed", 0)
        warning = (
            f"\n\n{failed} files failed import and will stay on the source."
            if failed
            else ""
        )
        confirmed = messagebox.askyesno(
            "Delete and Eject Source?",
            "Do you want to delete the verified imported files from the source "
            "and eject it now?\n\n"
            "Only files that were copied and verified will be deleted."
            f"{warning}",
            icon="warning",
        )
        if not confirmed:
            return

        self._set_busy(True)
        self._set_progress_active(True)
        self.current_file_var.set("Deleting imported files and ejecting source...")
        self.current_file_detail_var.set("")
        self.transfer_speed_var.set("")
        self._set_status("Deleting imported files and ejecting source...")

        thread = threading.Thread(
            target=self._source_cleanup_worker,
            args=(imported_sources, source),
            daemon=True,
        )
        self.worker_thread = thread
        thread.start()

    def _show_source_cleanup_result(self, result: SourceCleanupResult) -> None:
        title = "Source Ejected" if result.ejected else "Source Cleanup Complete"
        self._set_status(title)
        self.current_file_var.set(title)
        self.current_file_detail_var.set("")
        self.transfer_speed_var.set("")
        self.file_progress_bar.configure(value=0, maximum=100)
        if result.ejected:
            self._load_sources()
        else:
            self._reset_scan_card(
                "Source cleanup complete. Scan this source again to see media counts."
            )

        failure_text = (
            "\n" + "\n".join(result.delete_failures)
            if result.delete_failures
            else ""
        )
        messagebox.showinfo(
            title,
            f"Deleted From Source:\n{result.deleted}\n"
            f"Delete Failures:\n{len(result.delete_failures)}"
            f"{failure_text}\n"
            f"Ejected:\n{'Yes' if result.ejected else 'No'}\n"
            f"Eject Details:\n{result.eject_message}",
        )

    def _project_status_text(
        self,
        created: bool,
        skipped: bool,
        expected: bool,
    ) -> str:
        if created:
            return "Created"
        if skipped:
            return "Already exists"
        if expected:
            return "Not created"
        return "Not needed"

    def _selected_source_path(self) -> Path | None:
        text = self.source_path_var.get()
        if not text or text.startswith("No "):
            return None
        return Path(text)

    def _event_identity_changed(self, *_args: object) -> None:
        if self.current_event is None:
            return

        self.current_event = None
        self.event_folder_var.set(
            "Event details changed. Create the event again before importing."
        )
        self._refresh_import_state()

    def _selected_files(self) -> list[MediaFile]:
        if self.scan_result is None:
            return []

        if len(self.scan_result.sessions) <= 6:
            selected: list[MediaFile] = []
            for session in self.scan_result.sessions:
                variable = self.session_variables.get(session.index)
                if variable is not None and variable.get():
                    selected.extend(session.files)
            return selected

        try:
            start = datetime.strptime(
                self.timeline_start_var.get(), "%Y-%m-%d %H:%M:%S"
            ).astimezone()
            end = datetime.strptime(
                self.timeline_end_var.get(),
                "%Y-%m-%d %H:%M:%S",
            ).astimezone()
        except ValueError:
            return []

        if end < start:
            start, end = end, start
        return self.import_service.files_in_time_range(
            self.scan_result.files,
            start,
            end,
        )

    def _skipped_count_for(self, selected_files: list[MediaFile]) -> int:
        if self.scan_result is None:
            return 0

        return (
            self.scan_result.skipped_count
            + len(self.scan_result.files)
            - len(selected_files)
        )

    def _select_all_sessions(self) -> None:
        for variable in self.session_variables.values():
            variable.set(True)
        self._refresh_import_state()

    def _select_no_sessions(self) -> None:
        for variable in self.session_variables.values():
            variable.set(False)
        self._refresh_import_state()

    def _render_session_thumbnails(
        self,
        parent: ttk.Frame,
        session: MediaSession,
    ) -> None:
        preview_frame = ttk.Frame(parent)
        preview_frame.grid(row=0, column=1, sticky="w", padx=(18, 0))

        thumbnails = [
            ("Earliest", session.start_thumbnail),
            ("Latest", session.end_thumbnail),
        ]
        for column, (label, thumbnail) in enumerate(thumbnails):
            item_frame = ttk.Frame(preview_frame)
            item_frame.grid(row=0, column=column, sticky="n", padx=(0, 10))
            ttk.Label(item_frame, text=label).grid(row=0, column=0)
            if thumbnail is None:
                ttk.Label(item_frame, text="No preview").grid(row=1, column=0)
                continue

            try:
                image = tk.PhotoImage(file=str(thumbnail.path))
            except tk.TclError:
                ttk.Label(item_frame, text="No preview").grid(row=1, column=0)
                continue

            self.thumbnail_images.append(image)
            ttk.Label(item_frame, image=image).grid(row=1, column=0, pady=(3, 0))

    def _refresh_import_state(self) -> None:
        state = "normal" if self.scan_result and self._selected_files() else "disabled"
        if self.worker_thread is not None and self.worker_thread.is_alive():
            state = "disabled"
        self.import_button.configure(state=state)

    def _set_busy(self, busy: bool, importing: bool = False) -> None:
        state = "disabled" if busy else "normal"
        self.scan_button.configure(state=state)
        self.import_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if importing else "disabled")
        if not busy:
            self._refresh_import_state()
            if not importing:
                self._set_progress_active(False)

    def _set_progress_active(self, active: bool) -> None:
        if active and not self.spinner_running:
            self.spinner_running = True
            self._animate_spinner()
            return

        if not active:
            self.spinner_running = False
            self.activity_var.set("")

    def _animate_spinner(self) -> None:
        if not self.spinner_running:
            self.activity_var.set("")
            return

        frames = ("|", "/", "-", "\\")
        self.activity_var.set(frames[self.spinner_index % len(frames)])
        self.spinner_index += 1
        self.after(120, self._animate_spinner)

    def _format_bytes(self, value: float) -> str:
        units = ("B", "KB", "MB", "GB", "TB")
        amount = float(value)
        for unit in units:
            if amount < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{amount:.0f} {unit}"
                return f"{amount:.1f} {unit}"
            amount /= 1024

    def _validate_inputs(self) -> bool:
        if not self.event_name_var.get().strip():
            messagebox.showerror("Missing Event Name", "Please enter an event name.")
            return False

        if not self._is_valid_event_date(self.event_date_var.get().strip()):
            messagebox.showerror(
                "Invalid Event Date",
                "Please enter the event date in YYYY.MM.DD format.",
            )
            return False

        if not self.school_year_var.get().strip():
            messagebox.showerror("Missing School Year", "Please enter a school year.")
            return False

        return True

    def _is_valid_event_date(self, event_date: str) -> bool:
        try:
            datetime.strptime(event_date, "%Y.%m.%d")
        except ValueError:
            return False
        return True

    def _confirm_metadata_overwrite(self) -> bool:
        return messagebox.askokcancel(
            "Event Already Exists",
            "This event already exists.\nDo you want to overwrite the metadata?",
            default=messagebox.CANCEL,
        )

    def _show_success(self, folder_name: str) -> None:
        messagebox.showinfo(
            "Event Created",
            f"Event created successfully.\nFolder:\n{folder_name}",
        )

    def _show_error(self, title: str, message: str) -> None:
        self._set_status("Ready")
        messagebox.showerror(title, message)

    def _capture_time_text(self, result: MediaScanResult) -> str:
        if result.start_time is None or result.end_time is None:
            return "No capture times found"
        return f"{result.start_time:%Y-%m-%d %H:%M} - {result.end_time:%Y-%m-%d %H:%M}"

    def _clear_selection_frame(self) -> None:
        for child in self.selection_frame.winfo_children():
            child.destroy()
        self.session_variables = {}
        self.thumbnail_images = []
        self.timeline_count_var.set("")

    def _resize_content(self, event: tk.Event) -> None:
        self.canvas.itemconfigure(self.window_id, width=event.width)

    def _update_scroll_region(self, _event: tk.Event) -> None:
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _bind_mousewheel_area(self, widget: tk.Widget) -> None:
        widget.bind("<Enter>", self._bind_mousewheel, add="+")
        widget.bind("<Leave>", self._unbind_mousewheel, add="+")
        for child in widget.winfo_children():
            self._bind_mousewheel_area(child)

    def _bind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel)

    def _unbind_mousewheel(self, _event: tk.Event) -> None:
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event: tk.Event) -> str:
        if not self._content_overflows():
            return "break"

        if getattr(event, "num", None) == 4:
            steps = -3
        elif getattr(event, "num", None) == 5:
            steps = 3
        else:
            delta = getattr(event, "delta", 0)
            if delta == 0:
                return "break"
            if abs(delta) >= 120:
                steps = int(-delta / 120)
            else:
                steps = -1 if delta > 0 else 1

        self.canvas.yview_scroll(steps, "units")
        return "break"

    def _content_overflows(self) -> bool:
        scroll_region = self.canvas.bbox("all")
        if scroll_region is None:
            return False

        return (scroll_region[3] - scroll_region[1]) > self.canvas.winfo_height()

    def _set_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)

    def _selected_grades(self) -> list[str]:
        return [
            grade
            for grade, variable in self.grade_variables.items()
            if variable.get()
        ]
