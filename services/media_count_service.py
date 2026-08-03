from dataclasses import dataclass
from pathlib import Path

from services.importer import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS
from services.metadata_service import MetadataService


@dataclass(frozen=True)
class EventMediaCountResult:
    """Counts found for one event folder."""

    event_folder: Path
    photo_count: int
    video_count: int
    updated: bool


@dataclass(frozen=True)
class EventMediaCountError:
    """Details for one event whose counts could not be updated."""

    event_folder: Path
    message: str


@dataclass(frozen=True)
class EventRootMediaCountResult:
    """Summary of refreshing media counts for an event root."""

    event_root: Path
    found: int
    updated: int
    unchanged: int
    failed: int
    results: list[EventMediaCountResult]
    errors: list[EventMediaCountError]


class MediaCountService:
    """Counts imported event media and writes the current counts to metadata."""

    def __init__(self, metadata_service: MetadataService | None = None) -> None:
        self.metadata_service = metadata_service or MetadataService()

    def update_event_root_counts(self, event_root: Path) -> EventRootMediaCountResult:
        event_folders = self.discover_event_folders(event_root)
        results: list[EventMediaCountResult] = []
        errors: list[EventMediaCountError] = []

        for event_folder in event_folders:
            try:
                results.append(self.update_event_counts(event_folder))
            except Exception as exc:
                errors.append(
                    EventMediaCountError(event_folder=event_folder, message=str(exc))
                )

        updated = sum(1 for result in results if result.updated)
        return EventRootMediaCountResult(
            event_root=event_root,
            found=len(event_folders),
            updated=updated,
            unchanged=len(results) - updated,
            failed=len(errors),
            results=results,
            errors=errors,
        )

    def update_event_counts(self, event_folder: Path) -> EventMediaCountResult:
        metadata_path = event_folder / "Data" / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError("This event folder is missing Data/metadata.json.")

        photo_count = self._count_supported_files(
            event_folder / "Raw" / "Photos",
            PHOTO_EXTENSIONS,
        )
        video_count = self._count_supported_files(
            event_folder / "Raw" / "Videos",
            VIDEO_EXTENSIONS,
        )

        metadata = self.metadata_service.read_metadata(metadata_path)
        updated = (
            int(metadata.get("photo_count", -1) or 0) != photo_count
            or int(metadata.get("video_count", -1) or 0) != video_count
        )
        if updated:
            self.metadata_service.update_media_counts(
                metadata_path,
                photo_count,
                video_count,
            )

        return EventMediaCountResult(
            event_folder=event_folder,
            photo_count=photo_count,
            video_count=video_count,
            updated=updated,
        )

    def discover_event_folders(self, event_root: Path) -> list[Path]:
        if not event_root.exists() or not event_root.is_dir():
            raise FileNotFoundError("The configured event root folder was not found.")

        event_folders: list[Path] = []
        for child in sorted(event_root.iterdir(), key=lambda path: path.name.casefold()):
            if not child.is_dir():
                continue
            if (child / "Data" / "metadata.json").exists():
                event_folders.append(child)
        return event_folders

    def _count_supported_files(self, folder: Path, extensions: set[str]) -> int:
        if not folder.exists():
            return 0
        if not folder.is_dir():
            raise NotADirectoryError(f"Expected a folder: {folder}")

        count = 0
        for path in folder.rglob("*"):
            if path.is_file() and path.suffix.casefold() in extensions:
                count += 1
        return count
