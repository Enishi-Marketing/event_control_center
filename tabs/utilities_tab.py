import queue
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from config.config import AppConfig
from services.archive_service import ArchiveCandidate, ArchiveRunResult, ArchiveService
from services.unedited_jpg_service import (
    UneditedJpgProgress,
    UneditedJpgService,
    UneditedJpgSummary,
)
from services.media_count_service import EventRootMediaCountResult, MediaCountService
from services.sync_service import EventRootSyncResult, SyncService


class UtilitiesTab(ttk.Frame):
    """Event repair and regeneration utilities."""

    def __init__(
        self,
        master: ttk.Notebook,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, padding=18)
        self.status_callback = status_callback
        self.unedited_jpg_service = UneditedJpgService()
        self.media_count_service = MediaCountService()
        self.sync_service = SyncService()
        self.archive_service = ArchiveService()
        self.worker_queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker_thread: threading.Thread | None = None
        self.cancel_event: threading.Event | None = None
        self.archive_candidates: list[ArchiveCandidate] = []

        self.event_folder_var = tk.StringVar(value="No event folder selected.")
        self.current_file_var = tk.StringVar(value="")
        self.summary_var = tk.StringVar(value="")
        self.sheets_event_folder_var = tk.StringVar(
            value=f"Event root: {AppConfig.EVENT_ROOT}"
        )
        self.sheets_status_var = tk.StringVar(value="Ready to sync all events.")
        self.counts_event_folder_var = tk.StringVar(
            value=f"Year folder: {AppConfig.EVENT_ROOT}"
        )
        self.counts_status_var = tk.StringVar(value="Ready to update metadata counts.")
        self.archive_source_var = tk.StringVar(
            value=f"Local Events: {AppConfig.ARCHIVE_SOURCE_ROOT}"
        )
        self.archive_drive_var = tk.StringVar(
            value=f"Google Drive Events: {AppConfig.ARCHIVE_DRIVE_ROOT}"
        )
        self.archive_status_var = tk.StringVar(value="Ready to archive local events.")
        self._build_layout()
        self._load_archive_candidates(show_errors=False)
        self.after(100, self._poll_worker_queue)

    def _build_layout(self) -> None:
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.canvas = tk.Canvas(self, borderwidth=0, highlightthickness=0)
        scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.content = ttk.Frame(self.canvas)
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

        jpg_frame = ttk.LabelFrame(
            self.content,
            text="Regenerate Unedited JPGs",
            padding=14,
        )
        jpg_frame.grid(row=0, column=0, sticky="ew")
        jpg_frame.columnconfigure(0, weight=1)

        ttk.Label(jpg_frame, textvariable=self.event_folder_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            jpg_frame,
            text="Choose Event Folder...",
            command=self._browse_event_folder,
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))

        action_row = ttk.Frame(jpg_frame)
        action_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        action_row.columnconfigure(0, weight=1)
        self.generate_missing_button = ttk.Button(
            action_row,
            text="Generate Missing JPGs",
            command=lambda: self._start_generation(regenerate_all=False),
            state="disabled",
            style="Primary.TButton",
        )
        self.generate_missing_button.grid(row=0, column=1, sticky="e")
        self.regenerate_all_button = ttk.Button(
            action_row,
            text="Regenerate All JPGs",
            command=lambda: self._start_generation(regenerate_all=True),
            state="disabled",
        )
        self.regenerate_all_button.grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.cancel_button = ttk.Button(
            action_row,
            text="Cancel",
            command=self._cancel_generation,
            state="disabled",
        )
        self.cancel_button.grid(row=0, column=3, sticky="e", padx=(8, 0))

        self.progress_bar = ttk.Progressbar(jpg_frame, mode="determinate")
        self.progress_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))
        ttk.Label(jpg_frame, textvariable=self.current_file_var).grid(
            row=3, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )
        ttk.Label(jpg_frame, textvariable=self.summary_var).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

        counts_frame = ttk.LabelFrame(
            self.content,
            text="Update Metadata Counts",
            padding=14,
        )
        counts_frame.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        counts_frame.columnconfigure(0, weight=1)

        ttk.Label(counts_frame, textvariable=self.counts_event_folder_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            counts_frame,
            text="Choose Year Folder...",
            command=self._browse_counts_event_root,
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))

        counts_action_row = ttk.Frame(counts_frame)
        counts_action_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        counts_action_row.columnconfigure(0, weight=1)
        ttk.Label(counts_action_row, textvariable=self.counts_status_var).grid(
            row=0, column=0, sticky="w"
        )
        self.update_counts_button = ttk.Button(
            counts_action_row,
            text="Count Photos and Videos",
            command=self._start_media_count_update,
            style="Primary.TButton",
        )
        self.update_counts_button.grid(row=0, column=1, sticky="e")

        self.counts_progress_bar = ttk.Progressbar(counts_frame, mode="indeterminate")
        self.counts_progress_bar.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(16, 0),
        )

        archive_frame = ttk.LabelFrame(
            self.content,
            text="Archive Local Events",
            padding=14,
        )
        archive_frame.grid(row=2, column=0, sticky="ew", pady=(18, 0))
        archive_frame.columnconfigure(0, weight=1)

        ttk.Label(archive_frame, textvariable=self.archive_source_var).grid(
            row=0, column=0, sticky="w"
        )
        archive_source_buttons = ttk.Frame(archive_frame)
        archive_source_buttons.grid(row=0, column=1, sticky="e", padx=(12, 0))
        ttk.Button(
            archive_source_buttons,
            text="Choose Local Events...",
            command=self._browse_archive_source_root,
        ).grid(row=0, column=0)
        ttk.Button(
            archive_source_buttons,
            text="Refresh",
            command=lambda: self._load_archive_candidates(show_errors=True),
        ).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(archive_frame, textvariable=self.archive_drive_var).grid(
            row=1, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Button(
            archive_frame,
            text="Choose Google Drive...",
            command=self._browse_archive_drive_root,
        ).grid(row=1, column=1, sticky="e", padx=(12, 0), pady=(8, 0))

        list_frame = ttk.Frame(archive_frame)
        list_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        list_frame.columnconfigure(0, weight=1)
        self.archive_listbox = tk.Listbox(
            list_frame,
            height=8,
            selectmode=tk.EXTENDED,
            exportselection=False,
        )
        self.archive_listbox.grid(row=0, column=0, sticky="nsew")
        archive_scrollbar = ttk.Scrollbar(
            list_frame,
            orient="vertical",
            command=self.archive_listbox.yview,
        )
        archive_scrollbar.grid(row=0, column=1, sticky="ns")
        self.archive_listbox.configure(yscrollcommand=archive_scrollbar.set)

        archive_action_row = ttk.Frame(archive_frame)
        archive_action_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        archive_action_row.columnconfigure(0, weight=1)
        ttk.Label(archive_action_row, textvariable=self.archive_status_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            archive_action_row,
            text="Select All",
            command=self._select_all_archive_candidates,
        ).grid(row=0, column=1, sticky="e")
        ttk.Button(
            archive_action_row,
            text="Deselect All",
            command=self._deselect_all_archive_candidates,
        ).grid(row=0, column=2, sticky="e", padx=(8, 0))
        self.archive_events_button = ttk.Button(
            archive_action_row,
            text="Archive Selected Events",
            command=self._start_archive_events,
            style="Primary.TButton",
        )
        self.archive_events_button.grid(row=0, column=3, sticky="e", padx=(8, 0))

        self.archive_progress_bar = ttk.Progressbar(archive_frame, mode="indeterminate")
        self.archive_progress_bar.grid(
            row=4,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(14, 0),
        )

        sheets_frame = ttk.LabelFrame(
            self.content,
            text="Google Sheets Sync",
            padding=14,
        )
        sheets_frame.grid(row=3, column=0, sticky="ew", pady=(18, 0))
        sheets_frame.columnconfigure(0, weight=1)

        ttk.Label(sheets_frame, textvariable=self.sheets_event_folder_var).grid(
            row=0, column=0, sticky="w"
        )
        ttk.Button(
            sheets_frame,
            text="Choose Event Root...",
            command=self._browse_sheets_event_root,
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))

        sheets_action_row = ttk.Frame(sheets_frame)
        sheets_action_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(14, 0))
        sheets_action_row.columnconfigure(0, weight=1)
        ttk.Label(sheets_action_row, textvariable=self.sheets_status_var).grid(
            row=0, column=0, sticky="w"
        )
        self.sync_sheets_button = ttk.Button(
            sheets_action_row,
            text="Sync All Events to Google Sheets",
            command=self._start_sheets_sync,
            style="Primary.TButton",
        )
        self.sync_sheets_button.grid(row=0, column=1, sticky="e")

        self.sheets_progress_bar = ttk.Progressbar(sheets_frame, mode="indeterminate")
        self.sheets_progress_bar.grid(
            row=2,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=(16, 0),
        )
        self._bind_mousewheel_area(self.content)

    def _browse_event_folder(self) -> None:
        selected = filedialog.askdirectory(
            title="Choose Event Folder",
            initialdir=AppConfig.EVENT_ROOT,
        )
        if not selected:
            return

        self.event_folder_var.set(selected)
        self.summary_var.set("")
        self.current_file_var.set("")
        self.progress_bar.configure(value=0, maximum=100)
        self._refresh_button_state()

    def _browse_sheets_event_root(self) -> None:
        selected = filedialog.askdirectory(
            title="Select Events Root for Google Sheets Sync",
            initialdir=AppConfig.EVENT_ROOT,
        )
        if not selected:
            return

        self.sheets_event_folder_var.set(f"Event root: {selected}")
        self.sheets_status_var.set("Ready to sync all events.")
        self._refresh_button_state()

    def _browse_counts_event_root(self) -> None:
        selected = filedialog.askdirectory(
            title="Select Year Folder for Metadata Counts",
            initialdir=AppConfig.EVENT_ROOT,
        )
        if not selected:
            return

        self.counts_event_folder_var.set(f"Year folder: {selected}")
        self.counts_status_var.set("Ready to update metadata counts.")
        self._refresh_button_state()

    def _browse_archive_source_root(self) -> None:
        selected = filedialog.askdirectory(
            title="Select Local Events Folder",
            initialdir=AppConfig.ARCHIVE_SOURCE_ROOT,
        )
        if not selected:
            return

        self.archive_source_var.set(f"Local Events: {selected}")
        self._load_archive_candidates(show_errors=True)

    def _browse_archive_drive_root(self) -> None:
        selected = filedialog.askdirectory(
            title="Select Google Drive Events Folder",
            initialdir=AppConfig.ARCHIVE_DRIVE_ROOT,
        )
        if not selected:
            return

        self.archive_drive_var.set(f"Google Drive Events: {selected}")
        self._load_archive_candidates(show_errors=True)

    def refresh_settings(self) -> None:
        self.sheets_event_folder_var.set(f"Event root: {AppConfig.EVENT_ROOT}")
        self.counts_event_folder_var.set(f"Year folder: {AppConfig.EVENT_ROOT}")
        self.archive_source_var.set(f"Local Events: {AppConfig.ARCHIVE_SOURCE_ROOT}")
        self.archive_drive_var.set(f"Google Drive Events: {AppConfig.ARCHIVE_DRIVE_ROOT}")
        self.sheets_status_var.set("Ready to sync all events.")
        self.counts_status_var.set("Ready to update metadata counts.")
        self._load_archive_candidates(show_errors=False)
        self._refresh_button_state()

    def _start_generation(self, regenerate_all: bool) -> None:
        event_folder = self._selected_event_folder()
        if event_folder is None:
            messagebox.showerror("Missing Event Folder", "Please choose an event folder.")
            return

        if regenerate_all and not messagebox.askyesno(
            "Regenerate All JPGs",
            "This will replace every Unedited JPG for this event. Continue?",
            default=messagebox.NO,
        ):
            return

        self.cancel_event = threading.Event()
        self._set_busy(True)
        self.summary_var.set("")
        self.current_file_var.set("")
        self.progress_bar.configure(value=0, maximum=100)
        self._set_status("Generating Unedited JPGs...")

        thread = threading.Thread(
            target=self._generation_worker,
            args=(event_folder, regenerate_all, self.cancel_event),
            daemon=True,
        )
        self.worker_thread = thread
        thread.start()

    def _generation_worker(
        self,
        event_folder: Path,
        regenerate_all: bool,
        cancel_event: threading.Event,
    ) -> None:
        try:
            summary = self.unedited_jpg_service.generate_for_event(
                event_folder=event_folder,
                cancel_event=cancel_event,
                regenerate_all=regenerate_all,
                progress_callback=lambda progress: self.worker_queue.put(
                    ("jpg_progress", progress)
                ),
            )
            self.worker_queue.put(("jpg_success", summary))
        except Exception as exc:
            self.worker_queue.put(("jpg_error", str(exc)))

    def _start_sheets_sync(self) -> None:
        event_root = self._selected_sheets_event_root()
        if event_root is None:
            messagebox.showerror("Missing Event Root", "Please choose an events root folder.")
            return

        self._set_busy(True)
        self.cancel_button.configure(state="disabled")
        self.sheets_status_var.set("Scanning events and syncing to Google Sheets...")
        self.sheets_progress_bar.start(12)
        self._set_status("Syncing all events to Google Sheets...")

        thread = threading.Thread(
            target=self._sheets_sync_worker,
            args=(event_root,),
            daemon=True,
        )
        self.worker_thread = thread
        thread.start()

    def _sheets_sync_worker(self, event_root: Path) -> None:
        try:
            result = self.sync_service.sync_event_root(event_root)
            self.worker_queue.put(("sheets_success", result))
        except Exception as exc:
            self.worker_queue.put(("sheets_error", str(exc)))

    def _start_media_count_update(self) -> None:
        event_root = self._selected_counts_event_root()
        if event_root is None:
            messagebox.showerror("Missing Event Root", "Please choose an events root folder.")
            return

        self._set_busy(True)
        self.cancel_button.configure(state="disabled")
        self.counts_status_var.set("Counting photos and videos...")
        self.counts_progress_bar.start(12)
        self._set_status("Updating metadata counts...")

        thread = threading.Thread(
            target=self._media_count_worker,
            args=(event_root,),
            daemon=True,
        )
        self.worker_thread = thread
        thread.start()

    def _media_count_worker(self, event_root: Path) -> None:
        try:
            result = self.media_count_service.update_event_root_counts(event_root)
            self.worker_queue.put(("counts_success", result))
        except Exception as exc:
            self.worker_queue.put(("counts_error", str(exc)))

    def _start_archive_events(self) -> None:
        source_root = self._selected_archive_source_root()
        archive_root = self._selected_archive_drive_root()
        selected_events = self._selected_archive_events()
        if source_root is None or archive_root is None:
            messagebox.showerror(
                "Missing Archive Folders",
                "Please choose the local Events folder and Google Drive Events folder.",
            )
            return
        if not selected_events:
            messagebox.showerror(
                "No Events Selected",
                "Please select at least one event folder to archive.",
            )
            return

        if not messagebox.askyesno(
            "Archive Selected Events",
            "This will move the selected local event folders to Google Drive and "
            "leave shortcuts in their original locations. Continue?",
            default=messagebox.NO,
        ):
            return

        self._set_busy(True)
        self.cancel_button.configure(state="disabled")
        self.archive_status_var.set("Archiving selected events...")
        self.archive_progress_bar.start(12)
        self._set_status("Archiving selected local events...")

        thread = threading.Thread(
            target=self._archive_events_worker,
            args=(source_root, archive_root, selected_events),
            daemon=True,
        )
        self.worker_thread = thread
        thread.start()

    def _archive_events_worker(
        self,
        source_root: Path,
        archive_root: Path,
        selected_events: list[Path],
    ) -> None:
        try:
            result = self.archive_service.archive_events(
                source_root,
                archive_root,
                selected_events,
            )
            self.worker_queue.put(("archive_success", result))
        except Exception as exc:
            self.worker_queue.put(("archive_error", str(exc)))

    def _cancel_generation(self) -> None:
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
        if message == "jpg_progress" and isinstance(payload, UneditedJpgProgress):
            self._update_progress(payload)
        elif message == "jpg_success" and isinstance(payload, UneditedJpgSummary):
            self._set_busy(False)
            self._show_summary(payload)
        elif message == "jpg_error":
            self._set_busy(False)
            self._set_status("Ready")
            messagebox.showerror("JPG Generation Failed", str(payload))
        elif message == "sheets_success" and isinstance(payload, EventRootSyncResult):
            self._set_busy(False)
            self.sheets_progress_bar.stop()
            self._show_sheets_root_result(payload)
        elif message == "sheets_error":
            self._set_busy(False)
            self.sheets_progress_bar.stop()
            self.sheets_status_var.set("Google Sheets sync failed.")
            self._set_status("Google Sheets sync failed.")
            messagebox.showerror("Google Sheets Sync Failed", str(payload))
        elif message == "counts_success" and isinstance(
            payload,
            EventRootMediaCountResult,
        ):
            self._set_busy(False)
            self.counts_progress_bar.stop()
            self._show_counts_root_result(payload)
        elif message == "counts_error":
            self._set_busy(False)
            self.counts_progress_bar.stop()
            self.counts_status_var.set("Metadata count update failed.")
            self._set_status("Metadata count update failed.")
            messagebox.showerror("Metadata Count Update Failed", str(payload))
        elif message == "archive_success" and isinstance(payload, ArchiveRunResult):
            self._set_busy(False)
            self.archive_progress_bar.stop()
            self._show_archive_result(payload)
        elif message == "archive_error":
            self._set_busy(False)
            self.archive_progress_bar.stop()
            self.archive_status_var.set("Archive failed.")
            self._set_status("Archive failed.")
            messagebox.showerror("Archive Failed", str(payload))

    def _update_progress(self, progress: UneditedJpgProgress) -> None:
        self.progress_bar.configure(maximum=max(progress.total, 1), value=progress.current)
        if progress.current_file is not None:
            remaining = max(progress.total - progress.current, 0)
            self.current_file_var.set(
                f"{progress.current_file.name} - {remaining} remaining"
            )
            self._set_status(
                f"Generating Unedited JPGs... {progress.current} / {progress.total}"
            )
        elif progress.message:
            self.current_file_var.set(progress.message)

    def _show_summary(self, summary: UneditedJpgSummary) -> None:
        title = "JPG Generation Cancelled" if summary.cancelled else "JPG Generation Complete"
        self._set_status(title)
        self.summary_var.set(
            f"Generated: {summary.generated}  "
            f"Skipped: {summary.skipped}  "
            f"Failed: {summary.failed}"
        )
        messagebox.showinfo(
            title,
            f"{title}\n"
            f"Generated:\n{summary.generated}\n"
            f"Skipped:\n{summary.skipped}\n"
            f"Failed:\n{summary.failed}",
        )

    def _show_sheets_root_result(self, result: EventRootSyncResult) -> None:
        total_completed = result.synced + result.partial
        if result.found == 0:
            self.sheets_status_var.set("No event metadata files found.")
            self._set_status("Google Sheets sync found no events.")
            messagebox.showwarning(
                "No Events Found",
                "No event folders with Data/metadata.json were found in:\n"
                f"{result.event_root}",
            )
            return

        summary = (
            f"Found: {result.found}  "
            f"Synced: {result.synced}  "
            f"Partial: {result.partial}  "
            f"Failed: {result.failed}"
        )
        self.sheets_status_var.set(summary)
        self._set_status("Google Sheets sync complete.")

        if result.failed:
            failed_events = "\n".join(
                f"- {error.event_folder.name}: {error.message}"
                for error in result.errors[:8]
            )
            remaining = result.failed - min(result.failed, 8)
            if remaining:
                failed_events += f"\n- ...and {remaining} more"
            messagebox.showwarning(
                "Google Sheets Sync Finished With Errors",
                "Google Sheets sync finished.\n"
                f"Completed:\n{total_completed}\n"
                f"Failed:\n{result.failed}\n\n"
                f"{failed_events}",
            )
            return

        messagebox.showinfo(
            "Google Sheets Sync Complete",
            "Google Sheets sync complete.\n"
            f"Events found:\n{result.found}\n"
            f"Synced:\n{result.synced}\n"
            f"Partial:\n{result.partial}",
        )

    def _show_counts_root_result(self, result: EventRootMediaCountResult) -> None:
        if result.found == 0:
            self.counts_status_var.set("No event metadata files found.")
            self._set_status("Metadata count update found no events.")
            messagebox.showwarning(
                "No Events Found",
                "No event folders with Data/metadata.json were found in:\n"
                f"{result.event_root}",
            )
            return

        summary = (
            f"Found: {result.found}  "
            f"Updated: {result.updated}  "
            f"Unchanged: {result.unchanged}  "
            f"Failed: {result.failed}"
        )
        self.counts_status_var.set(summary)
        self._set_status("Metadata count update complete.")

        if result.failed:
            failed_events = "\n".join(
                f"- {error.event_folder.name}: {error.message}"
                for error in result.errors[:8]
            )
            remaining = result.failed - min(result.failed, 8)
            if remaining:
                failed_events += f"\n- ...and {remaining} more"
            messagebox.showwarning(
                "Metadata Count Update Finished With Errors",
                "Metadata count update finished.\n"
                f"Updated:\n{result.updated}\n"
                f"Failed:\n{result.failed}\n\n"
                f"{failed_events}",
            )
            return

        messagebox.showinfo(
            "Metadata Count Update Complete",
            "Metadata count update complete.\n"
            f"Events found:\n{result.found}\n"
            f"Updated:\n{result.updated}\n"
            f"Unchanged:\n{result.unchanged}",
        )

    def _show_archive_result(self, result: ArchiveRunResult) -> None:
        summary = (
            f"Selected: {result.selected}  "
            f"Moved: {result.moved}  "
            f"Skipped: {result.skipped}  "
            f"Failed: {result.failed}"
        )
        self._set_status("Archive complete.")
        self._load_archive_candidates(show_errors=False)
        self.archive_status_var.set(summary)

        details = [
            f"- {item.source.name}: {item.message}"
            for item in result.results
            if item.status != "moved"
        ][:8]
        detail_text = "\n\n" + "\n".join(details) if details else ""
        if result.failed:
            messagebox.showwarning(
                "Archive Finished With Errors",
                "Archive finished with errors.\n"
                f"Moved:\n{result.moved}\n"
                f"Skipped:\n{result.skipped}\n"
                f"Failed:\n{result.failed}"
                f"{detail_text}",
            )
            return

        messagebox.showinfo(
            "Archive Complete",
            "Archive complete.\n"
            f"Moved:\n{result.moved}\n"
            f"Skipped:\n{result.skipped}"
            f"{detail_text}",
        )

    def _selected_event_folder(self) -> Path | None:
        text = self.event_folder_var.get()
        if not text or text.startswith("No "):
            return None
        return Path(text)

    def _selected_sheets_event_root(self) -> Path | None:
        text = self.sheets_event_folder_var.get()
        prefix = "Event root: "
        if text.startswith(prefix):
            text = text.removeprefix(prefix)
        if not text or text.startswith("No "):
            return None
        return Path(text)

    def _selected_counts_event_root(self) -> Path | None:
        text = self.counts_event_folder_var.get()
        prefix = "Year folder: "
        if text.startswith(prefix):
            text = text.removeprefix(prefix)
        if not text or text.startswith("No "):
            return None
        return Path(text)

    def _selected_archive_source_root(self) -> Path | None:
        text = self.archive_source_var.get()
        prefix = "Local Events: "
        if text.startswith(prefix):
            text = text.removeprefix(prefix)
        if not text:
            return None
        return Path(text)

    def _selected_archive_drive_root(self) -> Path | None:
        text = self.archive_drive_var.get()
        prefix = "Google Drive Events: "
        if text.startswith(prefix):
            text = text.removeprefix(prefix)
        if not text:
            return None
        return Path(text)

    def _selected_archive_events(self) -> list[Path]:
        return [
            self.archive_candidates[index].source
            for index in self.archive_listbox.curselection()
            if 0 <= index < len(self.archive_candidates)
        ]

    def _load_archive_candidates(self, show_errors: bool) -> None:
        source_root = self._selected_archive_source_root()
        archive_root = self._selected_archive_drive_root()
        self.archive_listbox.delete(0, tk.END)
        self.archive_candidates = []
        if source_root is None or archive_root is None:
            self.archive_status_var.set("Choose local and Google Drive folders.")
            self._refresh_button_state()
            return

        try:
            self.archive_candidates = [
                candidate
                for candidate in self.archive_service.discover_candidates(
                    source_root,
                    archive_root,
                )
                if not candidate.already_archived and not candidate.destination_exists
            ]
        except Exception as exc:
            self.archive_status_var.set("Could not scan local events.")
            self._refresh_button_state()
            if show_errors:
                messagebox.showerror("Archive Scan Failed", str(exc))
            return

        for candidate in self.archive_candidates:
            self.archive_listbox.insert(
                tk.END,
                f"{candidate.year}/{candidate.name}",
            )

        self._select_all_archive_candidates()
        if self.archive_candidates:
            self.archive_status_var.set(
                f"Found {len(self.archive_candidates)} local event folders."
            )
        else:
            self.archive_status_var.set("No local event folders found.")
        self._refresh_button_state()

    def _select_all_archive_candidates(self) -> None:
        if self.archive_candidates:
            self.archive_listbox.select_set(0, tk.END)
        self._refresh_button_state()

    def _deselect_all_archive_candidates(self) -> None:
        self.archive_listbox.select_clear(0, tk.END)
        self._refresh_button_state()

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

    def _refresh_button_state(self) -> None:
        state = "normal" if self._selected_event_folder() is not None else "disabled"
        if self.worker_thread is not None and self.worker_thread.is_alive():
            state = "disabled"
        self.generate_missing_button.configure(state=state)
        self.regenerate_all_button.configure(state=state)
        sheets_state = (
            "normal" if self._selected_sheets_event_root() is not None else "disabled"
        )
        counts_state = (
            "normal" if self._selected_counts_event_root() is not None else "disabled"
        )
        archive_state = (
            "normal"
            if self.archive_candidates
            and self._selected_archive_source_root() is not None
            and self._selected_archive_drive_root() is not None
            else "disabled"
        )
        if self.worker_thread is not None and self.worker_thread.is_alive():
            sheets_state = "disabled"
            counts_state = "disabled"
            archive_state = "disabled"
        self.sync_sheets_button.configure(state=sheets_state)
        self.update_counts_button.configure(state=counts_state)
        self.archive_events_button.configure(state=archive_state)

    def _set_busy(self, busy: bool) -> None:
        state = "disabled" if busy else "normal"
        self.generate_missing_button.configure(state=state)
        self.regenerate_all_button.configure(state=state)
        self.sync_sheets_button.configure(state=state)
        self.update_counts_button.configure(state=state)
        self.archive_events_button.configure(state=state)
        self.cancel_button.configure(state="normal" if busy else "disabled")
        if not busy:
            self._refresh_button_state()

    def _set_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)
