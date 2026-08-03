from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

from app.ui import MainWindow


def _resource_path(relative_path: str) -> Path:
    """Resolve bundled resources when running from a PyInstaller app."""
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    return base_path / relative_path


class EventControlCenterApp:
    """Application bootstrapper for Event Control Center."""

    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Event Control Center")
        self.root.minsize(900, 700)
        self.root.geometry("1000x760")
        self._set_window_icon()

        self._configure_style()
        self.main_window = MainWindow(self.root)

    def run(self) -> None:
        self.root.mainloop()

    def _set_window_icon(self) -> None:
        icon_path = _resource_path("assets/app_logo.png")
        if not icon_path.exists():
            return

        try:
            self._icon_image = tk.PhotoImage(file=str(icon_path))
            self.root.iconphoto(True, self._icon_image)
        except tk.TclError:
            pass

    def _configure_style(self) -> None:
        style = ttk.Style(self.root)
        if "clam" in style.theme_names():
            style.theme_use("clam")

        style.configure("TFrame", background="#f6f7f8")
        style.configure("TLabel", background="#f6f7f8", foreground="#202428")
        style.configure("TLabelframe", background="#f6f7f8")
        style.configure("TLabelframe.Label", background="#f6f7f8", foreground="#202428")
        style.configure("Status.TLabel", background="#e8eaed", padding=(10, 5))
        style.configure("Primary.TButton", padding=(14, 8))
