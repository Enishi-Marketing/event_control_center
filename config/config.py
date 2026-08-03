from pathlib import Path
import os
import re
import sys


def _load_local_settings(settings_path: Path) -> None:
    """Load simple KEY=value pairs without overriding real env vars."""
    if not settings_path.exists():
        return

    for raw_line in settings_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key and key not in os.environ:
            os.environ[key] = value


def _event_year_to_school_year(event_year: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{2}|\d{4})", event_year.strip())
    if not match:
        return event_year.strip()

    start_year = int(match.group(1))
    end_text = match.group(2)
    end_year = int(end_text) if len(end_text) == 4 else (start_year // 100) * 100 + int(end_text)
    if end_year < start_year:
        end_year += 100
    return f"{start_year}-{end_year}"


def _school_year_to_event_year(school_year: str) -> str:
    match = re.fullmatch(r"(\d{4})-(\d{4})", school_year.strip())
    if not match:
        return school_year.strip()
    return f"{match.group(1)}-{match.group(2)[-2:]}"


def _write_local_settings(settings_path: Path, updates: dict[str, str]) -> None:
    lines = settings_path.read_text(encoding="utf-8").splitlines() if settings_path.exists() else []
    seen: set[str] = set()
    updated_lines: list[str] = []

    for raw_line in lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            updated_lines.append(raw_line)
            continue

        key = raw_line.split("=", 1)[0].strip()
        if key in updates:
            updated_lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            updated_lines.append(raw_line)

    for key, value in updates.items():
        if key not in seen:
            updated_lines.append(f"{key}={value}")

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text("\n".join(updated_lines) + "\n", encoding="utf-8")


def _local_settings_path(app_name: str) -> Path:
    """Return a writable settings path for packaged apps."""
    source_path = Path(__file__).resolve().parent.parent / "config" / "local_settings.conf"
    if not getattr(sys, "frozen", False):
        return source_path

    return Path.home() / "Library" / "Application Support" / app_name / "local_settings.conf"


class AppConfig:
    """Central location for application-level paths and defaults."""

    APP_NAME = "Event Control Center"
    MIN_WIDTH = 900
    MIN_HEIGHT = 700
    PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    LOCAL_SETTINGS_PATH = _local_settings_path(APP_NAME)
    _load_local_settings(LOCAL_SETTINGS_PATH)
    # These paths intentionally have no computer- or account-specific defaults.
    # Configure shared storage in local_settings.conf on each computer.
    LOCAL_EVENTS_ROOT = Path(
        os.environ.get("LOCAL_EVENTS_ROOT", str(Path.home() / "Documents" / "Events"))
    ).expanduser()
    MULTIMEDIA_EVENTS_ROOT = Path(
        os.environ.get("MULTIMEDIA_EVENTS_ROOT", str(LOCAL_EVENTS_ROOT))
    ).expanduser()
    DEFAULT_EVENT_YEAR = os.environ.get(
        "DEFAULT_EVENT_YEAR",
        _school_year_to_event_year(os.environ.get("DEFAULT_SCHOOL_YEAR", "2025-2026")),
    )
    DEFAULT_SCHOOL_YEAR = os.environ.get(
        "DEFAULT_SCHOOL_YEAR",
        _event_year_to_school_year(DEFAULT_EVENT_YEAR),
    )
    EVENT_ROOT = MULTIMEDIA_EVENTS_ROOT / DEFAULT_EVENT_YEAR
    LOCAL_EVENT_ROOT = LOCAL_EVENTS_ROOT / DEFAULT_EVENT_YEAR
    ARCHIVE_SOURCE_ROOT = Path(
        os.environ.get("ARCHIVE_SOURCE_ROOT", str(LOCAL_EVENTS_ROOT))
    )
    ARCHIVE_DRIVE_ROOT = Path(
        os.environ.get("ARCHIVE_DRIVE_ROOT", str(MULTIMEDIA_EVENTS_ROOT))
    )
    DEFAULT_SESSION_GAP_MINUTES = 20
    LIGHTROOM_TEMPLATE_DIR = Path(
        os.environ.get(
            "LIGHTROOM_TEMPLATE_DIR", str(Path.home() / "Documents" / "Blank_Lightroom")
        )
    ).expanduser()
    PREMIERE_TEMPLATE = Path(
        os.environ.get(
            "PREMIERE_TEMPLATE",
            str(Path.home() / "Documents" / "Blank_Premiere" / "Blank_Premiere_Project.prproj"),
        )
    ).expanduser()
    GOOGLE_SHEETS_CREDENTIALS_FILE = os.environ.get(
        "GOOGLE_SHEETS_CREDENTIALS_FILE",
        "",
    )
    GOOGLE_SHEETS_SPREADSHEET_ID = os.environ.get(
        "GOOGLE_SHEETS_SPREADSHEET_ID",
        "",
    )
    GOOGLE_SHEETS_WORKSHEET_NAME = os.environ.get(
        "GOOGLE_SHEETS_WORKSHEET_NAME",
        "Events",
    )

    @classmethod
    def set_default_event_year(cls, event_year: str) -> None:
        event_year = event_year.strip()
        if not re.fullmatch(r"\d{4}-\d{2}", event_year):
            raise ValueError("Use the short year folder format, like 2026-27.")

        school_year = _event_year_to_school_year(event_year)
        os.environ["DEFAULT_EVENT_YEAR"] = event_year
        os.environ["DEFAULT_SCHOOL_YEAR"] = school_year

        cls.DEFAULT_EVENT_YEAR = event_year
        cls.DEFAULT_SCHOOL_YEAR = school_year
        cls.EVENT_ROOT = cls.MULTIMEDIA_EVENTS_ROOT / event_year
        cls.LOCAL_EVENT_ROOT = cls.LOCAL_EVENTS_ROOT / event_year
        cls.ARCHIVE_SOURCE_ROOT = Path(
            os.environ.get("ARCHIVE_SOURCE_ROOT", str(cls.LOCAL_EVENTS_ROOT))
        )
        cls.ARCHIVE_DRIVE_ROOT = Path(
            os.environ.get("ARCHIVE_DRIVE_ROOT", str(cls.MULTIMEDIA_EVENTS_ROOT))
        )

        _write_local_settings(
            cls.LOCAL_SETTINGS_PATH,
            {
                "DEFAULT_EVENT_YEAR": event_year,
                "DEFAULT_SCHOOL_YEAR": school_year,
            },
        )

    @classmethod
    def set_event_roots(cls, multimedia_events_root: str, local_events_root: str) -> None:
        """Save the per-computer event locations and refresh derived paths."""
        multimedia_events_root = multimedia_events_root.strip()
        local_events_root = local_events_root.strip()
        if not multimedia_events_root or not local_events_root:
            raise ValueError("Choose both the shared-drive and local event folders.")

        cls.MULTIMEDIA_EVENTS_ROOT = Path(multimedia_events_root).expanduser()
        cls.LOCAL_EVENTS_ROOT = Path(local_events_root).expanduser()
        cls.EVENT_ROOT = cls.MULTIMEDIA_EVENTS_ROOT / cls.DEFAULT_EVENT_YEAR
        cls.LOCAL_EVENT_ROOT = cls.LOCAL_EVENTS_ROOT / cls.DEFAULT_EVENT_YEAR
        cls.ARCHIVE_SOURCE_ROOT = Path(
            os.environ.get("ARCHIVE_SOURCE_ROOT", str(cls.LOCAL_EVENTS_ROOT))
        )
        cls.ARCHIVE_DRIVE_ROOT = Path(
            os.environ.get("ARCHIVE_DRIVE_ROOT", str(cls.MULTIMEDIA_EVENTS_ROOT))
        )

        _write_local_settings(
            cls.LOCAL_SETTINGS_PATH,
            {
                "MULTIMEDIA_EVENTS_ROOT": str(cls.MULTIMEDIA_EVENTS_ROOT),
                "LOCAL_EVENTS_ROOT": str(cls.LOCAL_EVENTS_ROOT),
            },
        )
