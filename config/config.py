from pathlib import Path
from datetime import date
import os
import re
import sys


def _unquote_path(value: str) -> str:
    """Accept paths pasted with a matching pair of shell-style quotes."""
    value = value.strip()
    if len(value) >= 2 and value[0] in {"'", '"'} and value[-1] == value[0]:
        return value[1:-1]
    return value


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
        value = _unquote_path(value)
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


def _current_event_year() -> str:
    today = date.today()
    start = today.year if today.month >= 8 else today.year - 1
    return f"{start}-{(start + 1) % 100:02d}"


def _template_override(key: str, legacy_default: Path) -> str:
    """Treat paths auto-saved by older releases as the new bundled default."""
    value = os.environ.get(key, "").strip()
    return "" if value and Path(value).expanduser() == legacy_default else value


class AppConfig:
    """Central location for application-level paths and defaults."""

    APP_NAME = "Event Control Center"
    MIN_WIDTH = 900
    MIN_HEIGHT = 700
    PROJECT_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    BUNDLED_TEMPLATE_ROOT = PROJECT_ROOT / ("templates" if getattr(sys, "frozen", False) else "assets/templates")
    BUNDLED_LIGHTROOM_TEMPLATE_DIR = BUNDLED_TEMPLATE_ROOT / "Blank_Lightroom"
    BUNDLED_PREMIERE_TEMPLATE = BUNDLED_TEMPLATE_ROOT / "Blank_Premiere_Project.prproj"
    LOCAL_SETTINGS_PATH = _local_settings_path(APP_NAME)
    _load_local_settings(LOCAL_SETTINGS_PATH)
    # Staff choose a shared-drive folder on first launch; never bake in a
    # developer's account-specific CloudStorage path.
    LOCAL_EVENTS_ROOT = Path(
        os.environ.get("LOCAL_EVENTS_ROOT", str(Path.home() / "Documents" / "Events"))
    ).expanduser()
    SHARED_DRIVE_CONFIGURED = bool(os.environ.get("MULTIMEDIA_EVENTS_ROOT", "").strip())
    MULTIMEDIA_EVENTS_ROOT = Path(
        os.environ.get("MULTIMEDIA_EVENTS_ROOT", "")
    ).expanduser()
    DEFAULT_EVENT_YEAR = os.environ.get(
        "DEFAULT_EVENT_YEAR",
        _school_year_to_event_year(os.environ.get("DEFAULT_SCHOOL_YEAR", _current_event_year())),
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
    LIGHTROOM_TEMPLATE_OVERRIDE = _template_override(
        "LIGHTROOM_TEMPLATE_DIR", Path.home() / "Documents" / "Blank_Lightroom"
    )
    PREMIERE_TEMPLATE_OVERRIDE = _template_override(
        "PREMIERE_TEMPLATE", Path.home() / "Documents" / "Blank_Premiere" / "Blank_Premiere_Project.prproj"
    )
    LIGHTROOM_TEMPLATE_DIR = Path(
        LIGHTROOM_TEMPLATE_OVERRIDE or str(BUNDLED_LIGHTROOM_TEMPLATE_DIR)
    ).expanduser()
    PREMIERE_TEMPLATE = Path(
        PREMIERE_TEMPLATE_OVERRIDE or str(BUNDLED_PREMIERE_TEMPLATE)
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
        multimedia_events_root = _unquote_path(multimedia_events_root)
        local_events_root = _unquote_path(local_events_root)
        if not multimedia_events_root or not local_events_root:
            raise ValueError("Choose both the shared-drive and local event folders.")

        cls.MULTIMEDIA_EVENTS_ROOT = Path(multimedia_events_root).expanduser()
        cls.SHARED_DRIVE_CONFIGURED = True
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

    @classmethod
    def set_google_sheets(
        cls,
        credentials_file: str,
        spreadsheet_id: str,
        worksheet_name: str,
    ) -> None:
        """Save the local Google Sheets connection settings."""
        credentials_file = credentials_file.strip()
        spreadsheet_id = spreadsheet_id.strip()
        worksheet_name = worksheet_name.strip() or "Events"
        if bool(credentials_file) != bool(spreadsheet_id):
            raise ValueError(
                "Set both the Google service-account JSON file and spreadsheet ID."
            )

        cls.GOOGLE_SHEETS_CREDENTIALS_FILE = credentials_file
        cls.GOOGLE_SHEETS_SPREADSHEET_ID = spreadsheet_id
        cls.GOOGLE_SHEETS_WORKSHEET_NAME = worksheet_name
        _write_local_settings(
            cls.LOCAL_SETTINGS_PATH,
            {
                "GOOGLE_SHEETS_CREDENTIALS_FILE": credentials_file,
                "GOOGLE_SHEETS_SPREADSHEET_ID": spreadsheet_id,
                "GOOGLE_SHEETS_WORKSHEET_NAME": worksheet_name,
            },
        )

    @classmethod
    def set_project_templates(cls, lightroom_dir: str, premiere_file: str) -> None:
        lightroom_dir = lightroom_dir.strip()
        premiere_file = premiere_file.strip()
        os.environ["LIGHTROOM_TEMPLATE_DIR"] = lightroom_dir
        os.environ["PREMIERE_TEMPLATE"] = premiere_file
        cls.LIGHTROOM_TEMPLATE_OVERRIDE = lightroom_dir
        cls.PREMIERE_TEMPLATE_OVERRIDE = premiere_file
        cls.LIGHTROOM_TEMPLATE_DIR = Path(lightroom_dir).expanduser() if lightroom_dir else cls.BUNDLED_LIGHTROOM_TEMPLATE_DIR
        cls.PREMIERE_TEMPLATE = Path(premiere_file).expanduser() if premiere_file else cls.BUNDLED_PREMIERE_TEMPLATE
        _write_local_settings(
            cls.LOCAL_SETTINGS_PATH,
            {
                "LIGHTROOM_TEMPLATE_DIR": lightroom_dir,
                "PREMIERE_TEMPLATE": premiere_file,
            },
        )
