from dataclasses import dataclass
import json
import logging
from pathlib import Path
import re
import time

from services.metadata_service import MetadataService


SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
LOGGER = logging.getLogger(__name__)
HEADER_ROW = [
    "Event ID",
    "Date",
    "Event Name",
    "School Year",
    "Grades",
    "Keywords",
    "Photos",
    "Videos",
    "Unedited JPGs",
    "Google Drive",
    "Last Sync",
    "Status",
    "Local Folder",
]
GRADE_STAGING_SHEET_NAME = "Grade_Staging"
GRADE_STAGING_HEADER_ROW = [
    "Event ID",
    "Row Number",
    "Event Name",
    "Grade",
    "Source Metadata Path",
    "Last Synced",
]
CANONICAL_GRADES = [
    "All",
    "Staff",
    "Parents",
    "ELC",
    "PYP",
    "MYP",
    "DP",
    "Foundation",
    "Preschool",
    "PreK",
    "Kindergarten",
    *[f"Grade {grade}" for grade in range(1, 13)],
]
GRADE_ALIASES = {
    **{f"g{grade}": f"Grade {grade}" for grade in range(1, 13)},
    **{f"grade{grade}": f"Grade {grade}" for grade in range(1, 13)},
    **{f"year{grade}": f"Grade {grade}" for grade in range(1, 13)},
    "pre-k": "PreK",
    "pre k": "PreK",
    "prek": "PreK",
}
CANONICAL_GRADES_BY_KEY = {
    re.sub(r"[^a-z0-9]+", "", grade.casefold()): grade for grade in CANONICAL_GRADES
}
CANONICAL_GRADES_BY_KEY.update(GRADE_ALIASES)
DRIVE_FOLDER_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
RETRYABLE_REASONS = {
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "quotaExceeded",
    "backendError",
}
WRITE_INTERVAL_SECONDS = 1.1


@dataclass(frozen=True)
class GoogleSheetsSyncResult:
    """Outcome returned after a Google Sheets row is created or updated."""

    action: str
    row_number: int
    status: str = "Synced"
    log_messages: tuple[str, ...] = ()


class GoogleSheetsService:
    """Synchronizes event metadata with a configured Google Sheets worksheet."""

    def __init__(
        self,
        credentials_file: str | Path,
        spreadsheet_id: str,
        worksheet_name: str,
    ) -> None:
        self.credentials_file_text = str(credentials_file).strip()
        self.credentials_file = (
            Path(self.credentials_file_text).expanduser()
            if self.credentials_file_text
            else None
        )
        self.spreadsheet_id = spreadsheet_id.strip()
        self.worksheet_name = worksheet_name.strip()
        self._service: object | None = None
        self._worksheet_values: list[list[str]] | None = None
        self._event_id_rows: dict[str, int] | None = None
        self._last_write_at = 0.0
        self.metadata_service = MetadataService()

    def sync_event(
        self,
        metadata: dict[str, object],
        event_folder: Path,
        last_sync: str,
        metadata_path: Path | None = None,
    ) -> GoogleSheetsSyncResult:
        """Create or update the event row, using event_id as the primary key."""
        self._validate_config()
        self._ensure_service()
        values = self._get_values()
        self._ensure_header(values)

        event_id = str(metadata.get("event_id", "")).strip()
        if not event_id:
            raise ValueError("metadata.json is missing event_id.")

        row_number = self._verified_sheet_row(metadata, event_id)
        if row_number is None:
            row_number = self._find_row_by_event_id(event_id)

        row_data = self._build_row(metadata, event_folder, last_sync)
        if row_number is None:
            row_number = self._append_row(row_data)
            log_messages = self._sync_grade_staging(
                metadata,
                row_number,
                metadata_path or event_folder / "Data" / "metadata.json",
                last_sync,
            )
            return GoogleSheetsSyncResult(
                "Created new row",
                row_number,
                log_messages=log_messages,
            )

        self._update_row(row_number, row_data)
        log_messages = self._sync_grade_staging(
            metadata,
            row_number,
            metadata_path or event_folder / "Data" / "metadata.json",
            last_sync,
        )
        return GoogleSheetsSyncResult(
            "Updated existing row",
            row_number,
            log_messages=log_messages,
        )

    def _validate_config(self) -> None:
        if self.credentials_file is None:
            raise ValueError("Google Sheets credentials file is not configured.")
        if not self.credentials_file.exists():
            raise FileNotFoundError(
                f"Google Sheets credentials file was not found: {self.credentials_file}"
            )
        if not self.spreadsheet_id:
            raise ValueError("Google Sheets spreadsheet ID is not configured.")
        if not self.worksheet_name:
            raise ValueError("Google Sheets worksheet name is not configured.")

    def _ensure_service(self) -> None:
        if self._service is not None:
            return

        try:
            from google.oauth2.service_account import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Sheets support requires google-api-python-client and google-auth."
            ) from exc

        try:
            credentials = Credentials.from_service_account_file(
                str(self.credentials_file),
                scopes=[SHEETS_SCOPE],
            )
            self._service = build("sheets", "v4", credentials=credentials)
        except Exception as exc:
            raise RuntimeError(
                "Could not authenticate with the Google Sheets service account."
            ) from exc

    def _read_values(self) -> list[list[str]]:
        assert self._service is not None
        try:
            response = self._execute(
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=self._range("A:M"),
                )
            )
        except Exception as exc:
            raise RuntimeError(self._read_error_message(exc)) from exc

        values = response.get("values", [])
        if not isinstance(values, list):
            return []
        return values

    def _get_values(self) -> list[list[str]]:
        if self._worksheet_values is None:
            self._worksheet_values = self._read_values()
            self._event_id_rows = self._build_event_id_rows(self._worksheet_values)
        return self._worksheet_values

    def _ensure_header(self, values: list[list[str]]) -> None:
        if values:
            return

        assert self._service is not None
        try:
            self._wait_for_write_slot()
            self._execute(
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.spreadsheet_id,
                    range=self._range("A1:M1"),
                    valueInputOption="USER_ENTERED",
                    body={"values": [HEADER_ROW]},
                )
            )
            self._remember_write()
        except Exception as exc:
            raise RuntimeError("Could not write the Google Sheets header row.") from exc

        values.append(HEADER_ROW)
        self._event_id_rows = {}

    def _verified_sheet_row(
        self,
        metadata: dict[str, object],
        event_id: str,
    ) -> int | None:
        raw_row = metadata.get("sheet_row")
        try:
            row_number = int(raw_row)
        except (TypeError, ValueError):
            return None

        if row_number < 2:
            return None

        row_event_id = self._cached_event_id_at_row(row_number)
        if row_event_id == event_id:
            return row_number
        return None

    def _cached_event_id_at_row(self, row_number: int) -> str:
        values = self._get_values()
        index = row_number - 1
        if index < 0 or index >= len(values) or not values[index]:
            return ""
        return str(values[index][0]).strip()

    def _find_row_by_event_id(self, event_id: str) -> int | None:
        if self._event_id_rows is None:
            self._event_id_rows = self._build_event_id_rows(self._get_values())
        return self._event_id_rows.get(event_id)

    def _append_row(self, row_data: list[object]) -> int:
        assert self._service is not None
        try:
            self._wait_for_write_slot()
            response = self._execute(
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range=self._range("A:M"),
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": [row_data]},
                )
            )
            self._remember_write()
        except Exception as exc:
            raise RuntimeError(self._write_error_message("append a new", exc)) from exc

        updated_range = response.get("updates", {}).get("updatedRange", "")
        row_number = self._row_number_from_range(updated_range)
        if row_number is None:
            row_number = len(self._get_values()) + 1
        self._remember_row(row_number, row_data)
        return row_number

    def _update_row(self, row_number: int, row_data: list[object]) -> None:
        assert self._service is not None
        try:
            self._wait_for_write_slot()
            self._execute(
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.spreadsheet_id,
                    range=self._range(f"A{row_number}:M{row_number}"),
                    valueInputOption="USER_ENTERED",
                    body={"values": [row_data]},
                )
            )
            self._remember_write()
        except Exception as exc:
            raise RuntimeError(self._write_error_message("update the existing", exc)) from exc

        self._remember_row(row_number, row_data)

    def _build_row(
        self,
        metadata: dict[str, object],
        event_folder: Path,
        last_sync: str,
    ) -> list[object]:
        return [
            str(metadata.get("event_id", "")).strip(),
            str(metadata.get("date", "")).strip(),
            str(metadata.get("event_name", "")).strip(),
            str(metadata.get("school_year", "")).strip(),
            "",
            self._join_keywords(metadata.get("keywords")),
            int(metadata.get("photo_count", 0) or 0),
            int(metadata.get("video_count", 0) or 0),
            int(metadata.get("unedited_jpg_count", 0) or 0),
            self._drive_link_formula(metadata),
            last_sync,
            "Synced",
            str(event_folder),
        ]

    def _sync_grade_staging(
        self,
        metadata: dict[str, object],
        row_number: int,
        metadata_path: Path,
        last_sync: str,
    ) -> tuple[str, ...]:
        event_id = str(metadata.get("event_id", "")).strip()
        event_name = str(metadata.get("event_name", "")).strip()
        grades = self._normalize_grades(metadata.get("grades"), event_id)
        log_messages: list[str] = []

        message = "Main!E left blank for badge/chip generation"
        log_messages.append(message)
        LOGGER.info(message)
        staging_sheet_id = self._ensure_grade_staging_sheet()
        existing_values = self._read_grade_staging_values()
        cleared_count = self._delete_grade_staging_rows(
            staging_sheet_id,
            existing_values,
            event_id,
        )
        message = (
            f"Cleared {cleared_count} old grade staging rows for Event ID {event_id}"
        )
        log_messages.append(message)
        LOGGER.info(message)

        if not grades:
            message = (
                f"No valid grades found for Event ID {event_id}; "
                "Grade_Staging rows skipped."
            )
            log_messages.append(message)
            LOGGER.warning(message)
            return tuple(log_messages)

        staging_rows = [
            [
                event_id,
                row_number,
                event_name,
                grade,
                str(metadata_path),
                last_sync,
            ]
            for grade in grades
        ]
        self._append_grade_staging_rows(staging_rows)
        message = (
            f"Wrote {len(staging_rows)} grade staging rows for Event ID {event_id}"
        )
        log_messages.append(message)
        LOGGER.info(message)
        return tuple(log_messages)

    def _normalize_grades(self, value: object, event_id: str) -> list[str]:
        if not isinstance(value, list):
            LOGGER.warning(
                "Invalid grades value for Event ID %s; expected a list.",
                event_id,
            )
            return []

        grades: list[str] = []
        seen: set[str] = set()
        invalid_grades: list[str] = []
        for item in value:
            grade = self._normalize_grade(item)
            if not grade:
                invalid_grades.append(str(item))
                continue
            grade_key = grade.casefold()
            if grade_key in seen:
                continue
            seen.add(grade_key)
            grades.append(grade)

        if invalid_grades:
            LOGGER.warning(
                "Skipped invalid grade values for Event ID %s: %s",
                event_id,
                ", ".join(invalid_grades),
            )
        return grades

    def _normalize_grade(self, value: object) -> str:
        raw_grade = str(value or "").strip()
        if not raw_grade:
            return ""

        grade_key = re.sub(r"[^a-z0-9]+", "", raw_grade.casefold())
        return CANONICAL_GRADES_BY_KEY.get(grade_key, "")

    def _ensure_grade_staging_sheet(self) -> int:
        sheet_id = self._sheet_id_for_title(GRADE_STAGING_SHEET_NAME)
        if sheet_id is None:
            sheet_id = self._create_sheet(GRADE_STAGING_SHEET_NAME)

        values = self._read_grade_staging_values()
        if not values or values[0] != GRADE_STAGING_HEADER_ROW:
            self._write_grade_staging_header()
        return sheet_id

    def _sheet_id_for_title(self, sheet_name: str) -> int | None:
        assert self._service is not None
        response = self._execute(
            self._service.spreadsheets()
            .get(
                spreadsheetId=self.spreadsheet_id,
                fields="sheets(properties(sheetId,title))",
            )
        )
        sheets = response.get("sheets", [])
        if not isinstance(sheets, list):
            return None

        for sheet in sheets:
            if not isinstance(sheet, dict):
                continue
            properties = sheet.get("properties", {})
            if not isinstance(properties, dict):
                continue
            if properties.get("title") != sheet_name:
                continue
            sheet_id = properties.get("sheetId")
            try:
                return int(sheet_id)
            except (TypeError, ValueError):
                return None
        return None

    def _create_sheet(self, sheet_name: str) -> int:
        assert self._service is not None
        try:
            self._wait_for_write_slot()
            response = self._execute(
                self._service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={
                        "requests": [
                            {"addSheet": {"properties": {"title": sheet_name}}}
                        ]
                    },
                )
            )
            self._remember_write()
        except Exception as exc:
            raise RuntimeError(f"Could not create {sheet_name} sheet.") from exc

        replies = response.get("replies", [])
        if not isinstance(replies, list) or not replies:
            raise RuntimeError(f"Could not read the new {sheet_name} sheet ID.")
        properties = replies[0].get("addSheet", {}).get("properties", {})
        sheet_id = properties.get("sheetId")
        try:
            return int(sheet_id)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"Could not read the new {sheet_name} sheet ID."
            ) from exc

    def _read_grade_staging_values(self) -> list[list[str]]:
        assert self._service is not None
        try:
            response = self._execute(
                self._service.spreadsheets()
                .values()
                .get(
                    spreadsheetId=self.spreadsheet_id,
                    range=self._grade_staging_range("A:F"),
                )
            )
        except Exception as exc:
            raise RuntimeError("Could not read the Grade_Staging sheet.") from exc

        values = response.get("values", [])
        if not isinstance(values, list):
            return []
        return values

    def _write_grade_staging_header(self) -> None:
        assert self._service is not None
        try:
            self._wait_for_write_slot()
            self._execute(
                self._service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.spreadsheet_id,
                    range=self._grade_staging_range("A1:F1"),
                    valueInputOption="USER_ENTERED",
                    body={"values": [GRADE_STAGING_HEADER_ROW]},
                )
            )
            self._remember_write()
        except Exception as exc:
            raise RuntimeError("Could not write the Grade_Staging header row.") from exc

    def _delete_grade_staging_rows(
        self,
        staging_sheet_id: int,
        values: list[list[str]],
        event_id: str,
    ) -> int:
        row_numbers = [
            index
            for index, row in enumerate(values, start=1)
            if index > 1 and row and str(row[0]).strip() == event_id
        ]
        if not row_numbers:
            return 0

        assert self._service is not None
        requests = [
            {
                "deleteDimension": {
                    "range": {
                        "sheetId": staging_sheet_id,
                        "dimension": "ROWS",
                        "startIndex": row_number - 1,
                        "endIndex": row_number,
                    }
                }
            }
            for row_number in sorted(row_numbers, reverse=True)
        ]
        try:
            self._wait_for_write_slot()
            self._execute(
                self._service.spreadsheets()
                .batchUpdate(
                    spreadsheetId=self.spreadsheet_id,
                    body={"requests": requests},
                )
            )
            self._remember_write()
        except Exception as exc:
            raise RuntimeError("Could not clear old Grade_Staging rows.") from exc
        return len(row_numbers)

    def _append_grade_staging_rows(self, staging_rows: list[list[object]]) -> None:
        assert self._service is not None
        try:
            self._wait_for_write_slot()
            self._execute(
                self._service.spreadsheets()
                .values()
                .append(
                    spreadsheetId=self.spreadsheet_id,
                    range=self._grade_staging_range("A:F"),
                    valueInputOption="USER_ENTERED",
                    insertDataOption="INSERT_ROWS",
                    body={"values": staging_rows},
                )
            )
            self._remember_write()
        except Exception as exc:
            raise RuntimeError("Could not write Grade_Staging rows.") from exc

    def _drive_link_formula(self, metadata: dict[str, object]) -> str:
        drive_url = str(metadata.get("drive_url", "")).strip()
        if drive_url:
            return f'=HYPERLINK("{self._escape_formula_text(drive_url)}","Open")'

        folder_id = str(metadata.get("google_drive_folder_id", "")).strip()
        if not folder_id:
            return ""
        if not DRIVE_FOLDER_ID_PATTERN.fullmatch(folder_id):
            raise ValueError("metadata.json has an invalid Google Drive folder ID.")

        url = f"https://drive.google.com/drive/folders/{folder_id}"
        return f'=HYPERLINK("{url}","Open")'

    def _range(self, a1_range: str) -> str:
        worksheet = self.worksheet_name.replace("'", "''")
        return f"'{worksheet}'!{a1_range}"

    def _grade_staging_range(self, a1_range: str) -> str:
        worksheet = GRADE_STAGING_SHEET_NAME.replace("'", "''")
        return f"'{worksheet}'!{a1_range}"

    def _row_number_from_range(self, updated_range: str) -> int | None:
        match = re.search(r"![A-Z]+(\d+):", updated_range)
        if match is None:
            match = re.search(r"![A-Z]+(\d+)$", updated_range)
        if match is None:
            return None
        return int(match.group(1))

    def _join_list(self, value: object) -> str:
        if isinstance(value, list):
            return ", ".join(str(item).strip() for item in value if str(item).strip())
        return str(value or "").strip()

    def _join_keywords(self, value: object) -> str:
        return ", ".join(self.metadata_service.normalize_keywords(value))

    def _escape_formula_text(self, value: str) -> str:
        return value.replace('"', '""')

    def _read_error_message(self, exc: Exception) -> str:
        error_text = self._error_text(exc)
        reason = self._error_reason(exc)

        if reason in RETRYABLE_REASONS or self._error_status(exc) in RETRYABLE_STATUS_CODES:
            return (
                "Google Sheets is temporarily rate limiting requests. "
                "The app will retry slower on the next sync."
            )

        if "SERVICE_DISABLED" in error_text:
            return (
                "The Google Sheets API is disabled for the service account project. "
                "Enable the Google Sheets API in Google Cloud, wait a few minutes, "
                "then try syncing again."
            )

        return (
            "Could not read the Google Sheets worksheet. Check sharing, "
            "spreadsheet ID, and worksheet name."
        )

    def _write_error_message(self, action: str, exc: Exception) -> str:
        reason = self._error_reason(exc)
        if reason in RETRYABLE_REASONS or self._error_status(exc) in RETRYABLE_STATUS_CODES:
            return (
                f"Could not {action} Google Sheets row because Google is rate limiting "
                "requests. Wait a few minutes, then sync again."
            )
        return f"Could not {action} Google Sheets row."

    def _execute(self, request: object) -> dict[str, object]:
        last_exc: Exception | None = None
        for attempt in range(5):
            try:
                return request.execute()
            except Exception as exc:
                last_exc = exc
                if not self._is_retryable_error(exc) or attempt == 4:
                    raise
                time.sleep(2**attempt)
        assert last_exc is not None
        raise last_exc

    def _is_retryable_error(self, exc: Exception) -> bool:
        return (
            self._error_status(exc) in RETRYABLE_STATUS_CODES
            or self._error_reason(exc) in RETRYABLE_REASONS
        )

    def _error_status(self, exc: Exception) -> int | None:
        status = getattr(getattr(exc, "resp", None), "status", None)
        try:
            return int(status)
        except (TypeError, ValueError):
            return None

    def _error_reason(self, exc: Exception) -> str:
        data = self._error_data(exc)
        details = data.get("error", {}).get("details", [])
        if isinstance(details, list):
            for detail in details:
                if not isinstance(detail, dict):
                    continue
                reason = detail.get("reason")
                if isinstance(reason, str):
                    return reason
        errors = data.get("error", {}).get("errors", [])
        if isinstance(errors, list):
            for error in errors:
                if not isinstance(error, dict):
                    continue
                reason = error.get("reason")
                if isinstance(reason, str):
                    return reason
        return ""

    def _error_data(self, exc: Exception) -> dict[str, object]:
        error_text = self._error_text(exc)
        try:
            data = json.loads(error_text)
        except json.JSONDecodeError:
            return {}
        if isinstance(data, dict):
            return data
        return {}

    def _error_text(self, exc: Exception) -> str:
        content = getattr(exc, "content", b"")
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return str(content)

    def _wait_for_write_slot(self) -> None:
        elapsed = time.monotonic() - self._last_write_at
        if elapsed < WRITE_INTERVAL_SECONDS:
            time.sleep(WRITE_INTERVAL_SECONDS - elapsed)

    def _remember_write(self) -> None:
        self._last_write_at = time.monotonic()

    def _build_event_id_rows(self, values: list[list[str]]) -> dict[str, int]:
        rows: dict[str, int] = {}
        for index, row in enumerate(values, start=1):
            if index == 1 or not row:
                continue
            event_id = str(row[0]).strip()
            if event_id:
                rows[event_id] = index
        return rows

    def _remember_row(self, row_number: int, row_data: list[object]) -> None:
        values = self._get_values()
        row = [str(value) for value in row_data]
        while len(values) < row_number:
            values.append([])
        values[row_number - 1] = row

        event_id = str(row_data[0]).strip()
        if event_id:
            if self._event_id_rows is None:
                self._event_id_rows = {}
            self._event_id_rows[event_id] = row_number
