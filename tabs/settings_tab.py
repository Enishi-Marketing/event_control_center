import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk

from config.config import AppConfig


class SettingsTab(ttk.Frame):
    """Application settings that rarely change."""

    def __init__(
        self,
        master: ttk.Notebook,
        settings_changed_callback: Callable[[], None] | None = None,
        status_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(master, padding=18)
        self.settings_changed_callback = settings_changed_callback
        self.status_callback = status_callback
        self.event_year_var = tk.StringVar(value=AppConfig.DEFAULT_EVENT_YEAR)
        self.school_year_var = tk.StringVar(value=AppConfig.DEFAULT_SCHOOL_YEAR)
        self.google_drive_var = tk.StringVar(value=str(AppConfig.EVENT_ROOT))
        self.local_events_var = tk.StringVar(value=str(AppConfig.LOCAL_EVENT_ROOT))
        self.google_drive_root_var = tk.StringVar(value=str(AppConfig.MULTIMEDIA_EVENTS_ROOT))
        self.local_events_root_var = tk.StringVar(value=str(AppConfig.LOCAL_EVENTS_ROOT))

        self.event_year_var.trace_add("write", self._event_year_changed)
        self._build_layout()

    def _build_layout(self) -> None:
        self.columnconfigure(0, weight=1)

        year_frame = ttk.LabelFrame(self, text="Default Event Year", padding=14)
        year_frame.grid(row=0, column=0, sticky="ew")
        year_frame.columnconfigure(1, weight=1)

        ttk.Label(year_frame, text="Year folder").grid(row=0, column=0, sticky="w")
        ttk.Entry(year_frame, textvariable=self.event_year_var, width=16).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(12, 0),
        )
        ttk.Button(
            year_frame,
            text="Save Default Year",
            command=self._save_default_year,
            style="Primary.TButton",
        ).grid(row=0, column=2, sticky="e", padx=(12, 0))

        ttk.Label(year_frame, text="School year").grid(
            row=1,
            column=0,
            sticky="w",
            pady=(12, 0),
        )
        ttk.Label(year_frame, textvariable=self.school_year_var).grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="w",
            padx=(12, 0),
            pady=(12, 0),
        )

        ttk.Label(year_frame, text="Shared-drive event folder").grid(
            row=2,
            column=0,
            sticky="w",
            pady=(12, 0),
        )
        ttk.Entry(year_frame, textvariable=self.google_drive_root_var).grid(
            row=2,
            column=1,
            columnspan=2,
            sticky="w",
            padx=(12, 0),
            pady=(12, 0),
        )

        ttk.Label(year_frame, text="Local event folder").grid(
            row=3,
            column=0,
            sticky="w",
            pady=(12, 0),
        )
        ttk.Entry(year_frame, textvariable=self.local_events_root_var).grid(
            row=3,
            column=1,
            sticky="w",
            padx=(12, 0),
            pady=(12, 0),
        )
        ttk.Button(
            year_frame,
            text="Save Locations",
            command=self._save_event_roots,
        ).grid(row=3, column=2, sticky="e", padx=(12, 0), pady=(12, 0))

        ttk.Label(year_frame, text="Shared-drive destination").grid(
            row=4, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Label(year_frame, textvariable=self.google_drive_var, wraplength=680).grid(
            row=4, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=(12, 0)
        )
        ttk.Label(year_frame, text="Local destination").grid(
            row=5, column=0, sticky="w", pady=(12, 0)
        )
        ttk.Label(year_frame, textvariable=self.local_events_var, wraplength=680).grid(
            row=5, column=1, columnspan=2, sticky="w", padx=(12, 0), pady=(12, 0)
        )

        ttk.Label(
            year_frame,
            text="Use the short folder format, for example 2026-27.",
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(14, 0))

    def _event_year_changed(self, *_args: object) -> None:
        event_year = self.event_year_var.get().strip()
        if self._valid_event_year(event_year):
            start_year = int(event_year[:4])
            end_year = (start_year // 100) * 100 + int(event_year[-2:])
            if end_year < start_year:
                end_year += 100
            self.school_year_var.set(f"{start_year}-{end_year}")
            self.google_drive_var.set(str(AppConfig.MULTIMEDIA_EVENTS_ROOT / event_year))
            self.local_events_var.set(str(AppConfig.LOCAL_EVENTS_ROOT / event_year))
            return

        self.school_year_var.set("Enter a year like 2026-27")
        self.google_drive_var.set("")
        self.local_events_var.set("")

    def _save_default_year(self) -> None:
        event_year = self.event_year_var.get().strip()
        if not self._valid_event_year(event_year):
            messagebox.showerror(
                "Invalid Event Year",
                "Please enter the year folder in short format, like 2026-27.",
            )
            return

        try:
            AppConfig.set_default_event_year(event_year)
        except Exception as exc:
            messagebox.showerror("Settings Not Saved", str(exc))
            return

        self._event_year_changed()
        if self.settings_changed_callback is not None:
            self.settings_changed_callback()
        self._set_status("Default event year saved.")
        messagebox.showinfo(
            "Default Event Year Saved",
            "The default event year has been saved.\n"
            f"New event folders will use:\n{AppConfig.EVENT_ROOT}",
        )

    def _save_event_roots(self) -> None:
        try:
            AppConfig.set_event_roots(
                self.google_drive_root_var.get(), self.local_events_root_var.get()
            )
        except Exception as exc:
            messagebox.showerror("Locations Not Saved", str(exc))
            return

        self._event_year_changed()
        if self.settings_changed_callback is not None:
            self.settings_changed_callback()
        self._set_status("Event locations saved.")
        messagebox.showinfo("Locations Saved", "Event locations have been saved for this computer.")

    def _valid_event_year(self, event_year: str) -> bool:
        if len(event_year) != 7 or event_year[4] != "-":
            return False
        return event_year[:4].isdigit() and event_year[5:].isdigit()

    def _set_status(self, message: str) -> None:
        if self.status_callback is not None:
            self.status_callback(message)
