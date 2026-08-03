import tkinter as tk
from tkinter import ttk

from tabs.import_tab import ImportTab
from tabs.metadata_tab import MetadataTab
from tabs.search_tab import SearchTab
from tabs.settings_tab import SettingsTab
from tabs.utilities_tab import UtilitiesTab


class MainWindow(ttk.Frame):
    """Main application window containing tabs and status bar."""

    def __init__(self, master: tk.Tk) -> None:
        super().__init__(master)
        self.status_text = tk.StringVar(value="Ready")

        self.grid(row=0, column=0, sticky="nsew")
        master.rowconfigure(0, weight=1)
        master.columnconfigure(0, weight=1)

        self._build_layout()

    def set_status(self, message: str) -> None:
        self.status_text.set(message)

    def _build_layout(self) -> None:
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        notebook = ttk.Notebook(self)
        notebook.grid(row=0, column=0, sticky="nsew")

        self.import_tab = ImportTab(notebook, status_callback=self.set_status)
        self.search_tab = SearchTab(notebook, status_callback=self.set_status)
        self.utilities_tab = UtilitiesTab(notebook, status_callback=self.set_status)
        self.settings_tab = SettingsTab(
            notebook,
            settings_changed_callback=self.refresh_settings,
            status_callback=self.set_status,
        )

        notebook.add(self.import_tab, text="Import")
        notebook.add(self.search_tab, text="Search")
        notebook.add(MetadataTab(notebook), text="Metadata")
        notebook.add(self.utilities_tab, text="Utilities")
        notebook.add(self.settings_tab, text="Settings")

        status_bar = ttk.Label(
            self,
            textvariable=self.status_text,
            style="Status.TLabel",
            anchor="w",
        )
        status_bar.grid(row=1, column=0, sticky="ew")

    def refresh_settings(self) -> None:
        self.import_tab.refresh_settings()
        self.search_tab.refresh_settings()
        self.utilities_tab.refresh_settings()
