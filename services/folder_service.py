from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EventFolderResult:
    """Details about a prepared event folder."""

    event_folder: Path
    metadata_path: Path
    already_exists: bool


class FolderService:
    """Creates the event directory structure."""

    SUBFOLDERS = (
        Path("Data"),
        Path("Raw"),
        Path("Finals"),
    )

    def __init__(self, event_root: Path) -> None:
        self.event_root = event_root

    def build_event_folder_name(self, event_date: str, event_name: str) -> str:
        return f"{event_date} - {event_name.strip()}"

    def get_event_folder(self, event_date: str, event_name: str) -> Path:
        return self.event_root / self.build_event_folder_name(event_date, event_name)

    def event_exists(self, event_date: str, event_name: str) -> bool:
        return self.get_event_folder(event_date, event_name).exists()

    def create_event_folders(self, event_date: str, event_name: str) -> EventFolderResult:
        event_folder = self.get_event_folder(event_date, event_name)
        already_exists = event_folder.exists()

        event_folder.mkdir(parents=True, exist_ok=True)
        for subfolder in self.SUBFOLDERS:
            (event_folder / subfolder).mkdir(parents=True, exist_ok=True)

        return EventFolderResult(
            event_folder=event_folder,
            metadata_path=event_folder / "Data" / "metadata.json",
            already_exists=already_exists,
        )
