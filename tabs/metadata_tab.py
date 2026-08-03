from tkinter import ttk


class MetadataTab(ttk.Frame):
    """Placeholder for future metadata editing features."""

    def __init__(self, master: ttk.Notebook) -> None:
        super().__init__(master, padding=18)
        self._build_layout()

    def _build_layout(self) -> None:
        ttk.Label(self, text="Coming Soon").pack(expand=True)
