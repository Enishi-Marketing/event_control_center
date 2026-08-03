import re
import shutil
from dataclasses import dataclass
from pathlib import Path


EVENT_FOLDER_PATTERN = re.compile(r"^[0-9]{4}\.[0-9]{2}\.[0-9]{2}")


@dataclass(frozen=True)
class ArchiveCandidate:
    """A local event folder that can be moved to the Drive archive."""

    source: Path
    year: str
    name: str
    destination: Path
    already_archived: bool
    destination_exists: bool


@dataclass(frozen=True)
class ArchiveEventResult:
    """Result for one attempted event archive."""

    source: Path
    destination: Path
    status: str
    message: str = ""


@dataclass(frozen=True)
class ArchiveRunResult:
    """Summary of an archive run."""

    source_root: Path
    archive_root: Path
    selected: int
    moved: int
    skipped: int
    failed: int
    results: list[ArchiveEventResult]


class ArchiveService:
    """Moves local event folders to Drive and leaves shortcuts behind."""

    def discover_candidates(
        self,
        source_root: Path,
        archive_root: Path,
    ) -> list[ArchiveCandidate]:
        if not source_root.exists() or not source_root.is_dir():
            raise FileNotFoundError("The local Events folder was not found.")

        candidates: list[ArchiveCandidate] = []
        for event_folder, year in self._event_folders(source_root):
            name = event_folder.name
            destination = archive_root / year / name
            candidates.append(
                ArchiveCandidate(
                    source=event_folder,
                    year=year,
                    name=name,
                    destination=destination,
                    already_archived=event_folder.is_symlink(),
                    destination_exists=destination.exists(),
                )
            )

        return sorted(candidates, key=lambda item: (item.year, item.name.casefold()))

    def archive_events(
        self,
        source_root: Path,
        archive_root: Path,
        event_folders: list[Path],
    ) -> ArchiveRunResult:
        results: list[ArchiveEventResult] = []

        for event_folder in event_folders:
            try:
                results.append(self.archive_event(event_folder, archive_root))
            except Exception as exc:
                year = event_folder.parent.name
                destination = archive_root / year / event_folder.name
                results.append(
                    ArchiveEventResult(
                        source=event_folder,
                        destination=destination,
                        status="failed",
                        message=str(exc),
                    )
                )

        moved = sum(1 for result in results if result.status == "moved")
        skipped = sum(1 for result in results if result.status == "skipped")
        failed = sum(1 for result in results if result.status == "failed")
        return ArchiveRunResult(
            source_root=source_root,
            archive_root=archive_root,
            selected=len(event_folders),
            moved=moved,
            skipped=skipped,
            failed=failed,
            results=results,
        )

    def archive_event(self, event_folder: Path, archive_root: Path) -> ArchiveEventResult:
        if not EVENT_FOLDER_PATTERN.match(event_folder.name):
            return ArchiveEventResult(
                source=event_folder,
                destination=archive_root / event_folder.parent.name / event_folder.name,
                status="skipped",
                message="Not a date-named event folder.",
            )

        if event_folder.is_symlink():
            return ArchiveEventResult(
                source=event_folder,
                destination=event_folder.resolve(),
                status="skipped",
                message="Already archived shortcut.",
            )

        if not event_folder.exists() or not event_folder.is_dir():
            raise FileNotFoundError("Local event folder was not found.")

        year = event_folder.parent.name
        year_destination = archive_root / year
        destination = year_destination / event_folder.name
        year_destination.mkdir(parents=True, exist_ok=True)

        if destination.exists():
            return ArchiveEventResult(
                source=event_folder,
                destination=destination,
                status="skipped",
                message="Already exists in Google Drive; no overwrite.",
            )

        moved_path = Path(shutil.move(str(event_folder), str(year_destination)))
        try:
            event_folder.symlink_to(moved_path, target_is_directory=True)
        except Exception:
            if moved_path.exists() and not event_folder.exists():
                shutil.move(str(moved_path), str(event_folder))
            raise

        return ArchiveEventResult(
            source=event_folder,
            destination=moved_path,
            status="moved",
            message="Moved to Google Drive and left a shortcut.",
        )

    def _event_folders(self, source_root: Path) -> list[tuple[Path, str]]:
        event_folders: list[tuple[Path, str]] = []

        for child in source_root.iterdir():
            if child.is_dir() and EVENT_FOLDER_PATTERN.match(child.name):
                event_folders.append((child, source_root.name))

        for year_folder in source_root.iterdir():
            if not year_folder.is_dir() or year_folder.is_symlink():
                continue
            for event_folder in year_folder.iterdir():
                if event_folder.is_dir() and EVENT_FOLDER_PATTERN.match(event_folder.name):
                    event_folders.append((event_folder, year_folder.name))

        return event_folders
