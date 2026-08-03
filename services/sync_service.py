from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from config.config import AppConfig
from services.google_sheets_service import GoogleSheetsService, GoogleSheetsSyncResult
from services.metadata_service import MetadataService


@dataclass(frozen=True)
class EventSyncResult:
    """UI-friendly summary of a Google Sheets sync attempt."""

    event_folder: Path
    event_name: str
    action: str
    row_number: int | None
    status: str
    started_at: str
    completed_at: str
    message: str = ""


@dataclass(frozen=True)
class EventSyncError:
    """Details for one event that could not be synced."""

    event_folder: Path
    message: str


@dataclass(frozen=True)
class EventRootSyncResult:
    """Summary of syncing every event found under an event root folder."""

    event_root: Path
    found: int
    synced: int
    partial: int
    failed: int
    results: list[EventSyncResult]
    errors: list[EventSyncError]


class SyncService:
    """Coordinates metadata updates, Google Sheets sync, and append-only logging."""

    def __init__(
        self,
        metadata_service: MetadataService | None = None,
        google_sheets_service: GoogleSheetsService | None = None,
    ) -> None:
        self.metadata_service = metadata_service or MetadataService()
        self.google_sheets_service = google_sheets_service or GoogleSheetsService(
            AppConfig.GOOGLE_SHEETS_CREDENTIALS_FILE,
            AppConfig.GOOGLE_SHEETS_SPREADSHEET_ID,
            AppConfig.GOOGLE_SHEETS_WORKSHEET_NAME,
        )

    def sync_event_folder(self, event_folder: Path) -> EventSyncResult:
        """Sync an event folder's Data/metadata.json into Google Sheets."""
        started_at = self._timestamp()
        metadata_path = event_folder / "Data" / "metadata.json"

        if not event_folder.exists() or not event_folder.is_dir():
            raise FileNotFoundError("Please choose an existing event folder.")
        if not metadata_path.exists():
            raise FileNotFoundError("This event folder is missing Data/metadata.json.")

        metadata = self.metadata_service.read_metadata(metadata_path)
        event_name = str(metadata.get("event_name") or event_folder.name)
        metadata_changed = self._ensure_event_id(metadata)
        if metadata_changed:
            self.metadata_service.write_metadata(metadata_path, metadata)

        try:
            sheet_result = self.google_sheets_service.sync_event(
                metadata,
                event_folder,
                started_at,
                metadata_path,
            )
        except Exception:
            completed_at = self._timestamp()
            self._safe_update_metadata(metadata_path, metadata, "Failed")
            self._safe_append_log(
                event_folder,
                event_name,
                "Failed before row update",
                None,
                "Failed",
                started_at,
                completed_at,
            )
            raise

        completed_at = self._timestamp()
        return self._finish_success(
            metadata_path,
            metadata,
            event_folder,
            event_name,
            sheet_result,
            started_at,
            completed_at,
        )

    def sync_event_root(self, event_root: Path) -> EventRootSyncResult:
        """Sync every immediate child event that contains Data/metadata.json."""
        event_folders = self.discover_event_folders(event_root)
        event_folders.sort(key=self._sync_priority)
        results: list[EventSyncResult] = []
        errors: list[EventSyncError] = []

        for event_folder in event_folders:
            try:
                results.append(self.sync_event_folder(event_folder))
            except Exception as exc:
                errors.append(EventSyncError(event_folder=event_folder, message=str(exc)))

        synced = sum(1 for result in results if result.status == "Synced")
        partial = sum(1 for result in results if result.status == "Partial")
        return EventRootSyncResult(
            event_root=event_root,
            found=len(event_folders),
            synced=synced,
            partial=partial,
            failed=len(errors),
            results=results,
            errors=errors,
        )

    def discover_event_folders(self, event_root: Path) -> list[Path]:
        """Find event folders under the root by looking for Data/metadata.json."""
        if not event_root.exists() or not event_root.is_dir():
            raise FileNotFoundError("The configured event root folder was not found.")

        event_folders: list[Path] = []
        for child in sorted(event_root.iterdir(), key=lambda path: path.name.casefold()):
            if not child.is_dir():
                continue
            if (child / "Data" / "metadata.json").exists():
                event_folders.append(child)
        return event_folders

    def _sync_priority(self, event_folder: Path) -> tuple[int, str]:
        metadata_path = event_folder / "Data" / "metadata.json"
        try:
            metadata = self.metadata_service.read_metadata(metadata_path)
        except Exception:
            return (0, event_folder.name.casefold())

        status = str(metadata.get("sync_status", "")).strip()
        priority = 1 if status == "Synced" else 0
        return (priority, event_folder.name.casefold())

    def _finish_success(
        self,
        metadata_path: Path,
        metadata: dict[str, object],
        event_folder: Path,
        event_name: str,
        sheet_result: GoogleSheetsSyncResult,
        started_at: str,
        completed_at: str,
    ) -> EventSyncResult:
        metadata["sheet_row"] = sheet_result.row_number
        metadata["last_sync"] = completed_at
        metadata["sync_status"] = "Synced"
        metadata["last_modified"] = completed_at

        status = "Synced"
        message = ""
        try:
            self.metadata_service.write_metadata(metadata_path, metadata)
        except Exception as exc:
            status = "Partial"
            message = f"Google Sheets updated, but metadata.json could not be saved: {exc}"

        if status == "Partial":
            self._safe_update_metadata(metadata_path, metadata, "Partial")

        self._safe_append_log(
            event_folder,
            event_name,
            sheet_result.action,
            sheet_result.row_number,
            status,
            started_at,
            completed_at,
            sheet_result.log_messages,
        )

        return EventSyncResult(
            event_folder=event_folder,
            event_name=event_name,
            action=sheet_result.action,
            row_number=sheet_result.row_number,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            message=message,
        )

    def _ensure_event_id(self, metadata: dict[str, object]) -> bool:
        event_id = str(metadata.get("event_id", "")).strip()
        if event_id:
            return False
        metadata["event_id"] = str(uuid4())
        metadata["last_modified"] = self._timestamp()
        return True

    def _safe_update_metadata(
        self,
        metadata_path: Path,
        metadata: dict[str, object],
        sync_status: str,
    ) -> None:
        try:
            metadata["sync_status"] = sync_status
            metadata["last_modified"] = self._timestamp()
            self.metadata_service.write_metadata(metadata_path, metadata)
        except Exception:
            return

    def _safe_append_log(
        self,
        event_folder: Path,
        event_name: str,
        action: str,
        row_number: int | None,
        status: str,
        started_at: str,
        completed_at: str,
        details: tuple[str, ...] = (),
    ) -> None:
        try:
            self._append_log(
                event_folder,
                event_name,
                action,
                row_number,
                status,
                started_at,
                completed_at,
                details,
            )
        except Exception:
            return

    def _append_log(
        self,
        event_folder: Path,
        event_name: str,
        action: str,
        row_number: int | None,
        status: str,
        started_at: str,
        completed_at: str,
        details: tuple[str, ...] = (),
    ) -> None:
        log_path = event_folder / "Data" / "import.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            "==================================",
            "Google Sheets Sync",
            "Started:",
            started_at,
            "Event:",
            event_name,
            "Action:",
            action,
            "Sheet Row:",
            str(row_number or ""),
            "Status:",
            status,
            "Completed:",
            completed_at,
        ]
        if details:
            lines.extend(["Details:", *details])

        with log_path.open("a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n\n")

    def _timestamp(self) -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")
