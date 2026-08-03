"""JSON command bridge used by the native SwiftUI macOS interface.

The bridge deliberately owns no business rules.  It adapts the existing Python
services to a small, stable command interface so the desktop UI can evolve
without duplicating media, folder, metadata, or configuration logic in Swift.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import Any, Callable

from config.config import AppConfig
from services.folder_service import FolderService
from services.importer import ImportService, MediaScanResult
from services.media_count_service import MediaCountService
from services.metadata_service import MetadataService
from services.search_service import MetadataSearchRecord, MetadataSearchService
from services.unedited_jpg_service import UneditedJpgService


def _config() -> dict[str, str]:
    return {
        "default_event_year": AppConfig.DEFAULT_EVENT_YEAR,
        "default_school_year": AppConfig.DEFAULT_SCHOOL_YEAR,
        "event_root": str(AppConfig.EVENT_ROOT),
        "local_event_root": str(AppConfig.LOCAL_EVENT_ROOT),
        "multimedia_events_root": str(AppConfig.MULTIMEDIA_EVENTS_ROOT),
        "local_events_root": str(AppConfig.LOCAL_EVENTS_ROOT),
    }


def _search_roots(source: str) -> dict[str, Path]:
    if source == "Current year":
        return {
            "Google Drive": AppConfig.EVENT_ROOT,
            "Local Events": AppConfig.LOCAL_EVENT_ROOT,
        }
    if source == "Google Drive":
        return {"Google Drive": AppConfig.ARCHIVE_DRIVE_ROOT}
    if source == "Local Events":
        return {"Local Events": AppConfig.ARCHIVE_SOURCE_ROOT}
    return {
        "Google Drive": AppConfig.ARCHIVE_DRIVE_ROOT,
        "Local Events": AppConfig.ARCHIVE_SOURCE_ROOT,
    }


def _record(record: MetadataSearchRecord) -> dict[str, Any]:
    return {
        "event_folder": str(record.event_folder),
        "source_name": record.source_name,
        "event_name": record.event_name,
        "date": record.date,
        "school_year": record.school_year,
        "grades": record.grades,
        "keywords": record.keywords,
        "description": record.description,
        "photo_count": record.photo_count,
        "video_count": record.video_count,
        "unedited_jpg_count": record.unedited_jpg_count,
        "last_modified": record.last_modified,
    }


def _scan_result(result: MediaScanResult) -> dict[str, Any]:
    return {
        "source": str(result.source),
        "photo_count": result.photo_count,
        "video_count": result.video_count,
        "skipped_count": result.skipped_count,
        "failures": list(result.failures),
        "sessions": [
            {
                "index": session.index,
                "start_time": session.start_time.isoformat(),
                "end_time": session.end_time.isoformat(),
                "photo_count": session.photo_count,
                "video_count": session.video_count,
                "file_count": len(session.files),
            }
            for session in result.sessions
        ],
    }


def _create_event(payload: dict[str, Any]) -> dict[str, Any]:
    event_name = str(payload.get("event_name", "")).strip()
    event_date = str(payload.get("event_date", "")).strip()
    if not event_name:
        raise ValueError("Enter an event name.")
    try:
        datetime.strptime(event_date, "%Y.%m.%d")
    except ValueError as exc:
        raise ValueError("Use the date format YYYY.MM.DD.") from exc

    destination = str(payload.get("destination", "Google Drive"))
    root = AppConfig.LOCAL_EVENT_ROOT if destination == "Local Events Folder" else AppConfig.EVENT_ROOT
    folders = FolderService(root)
    existing = folders.event_exists(event_date, event_name)
    if existing and not bool(payload.get("allow_overwrite", False)):
        raise ValueError("An event with this name and date already exists.")

    result = folders.create_event_folders(event_date, event_name)
    metadata = MetadataService().create_metadata(
        event_name=event_name,
        event_date=event_date,
        school_year=str(payload.get("school_year", AppConfig.DEFAULT_SCHOOL_YEAR)),
        description=str(payload.get("description", "")),
        keywords_text=payload.get("keywords", []),
        grades=[str(value) for value in payload.get("grades", [])],
    )
    MetadataService().write_metadata(result.metadata_path, metadata)
    return {
        "event_folder": str(result.event_folder),
        "already_existed": existing,
        "metadata": metadata,
    }


def _import_media(payload: dict[str, Any]) -> dict[str, Any]:
    source = Path(str(payload["source"]))
    event_folder = Path(str(payload["event_folder"]))
    gap_minutes = max(1, int(payload.get("session_gap_minutes", 20)))
    selected_sessions = {int(value) for value in payload.get("session_indexes", [])}
    scan = ImportService().scan_media(source, gap_minutes)
    selected_files = [
        item
        for session in scan.sessions
        if session.index in selected_sessions
        for item in session.files
    ]
    if not selected_files:
        raise ValueError("Select at least one media session to import.")

    service = ImportService()
    summary = service.import_media(
        selected_files,
        event_folder,
        source,
        Event(),
        skipped_count=scan.skipped_count + len(scan.files) - len(selected_files),
        event_name=str(payload.get("event_name", "")),
    )
    jpg_summary = UneditedJpgService().generate_for_event(event_folder)
    return {
        "photos_imported": summary.photos_imported,
        "videos_imported": summary.videos_imported,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "jpgs_generated": jpg_summary.generated,
        "failures": summary.failures + jpg_summary.failures,
    }


def _generate_jpgs(payload: dict[str, Any]) -> dict[str, Any]:
    summary = UneditedJpgService().generate_for_event(
        Path(str(payload["event_folder"])),
        regenerate_all=bool(payload.get("regenerate_all", False)),
    )
    return asdict(summary)


def _update_media_counts(payload: dict[str, Any]) -> dict[str, Any]:
    result = MediaCountService().update_event_root_counts(Path(str(payload["event_root"])))
    return {
        "found": result.found,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "failed": result.failed,
        "failures": [error.message for error in result.errors],
    }


def _dispatch(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    commands: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "config": lambda _payload: _config(),
        "create_event": _create_event,
        "scan_media": lambda values: _scan_result(
            ImportService().scan_media(
                Path(str(values["source"])),
                max(1, int(values.get("session_gap_minutes", 20))),
            )
        ),
        "import_media": _import_media,
        "generate_jpgs": _generate_jpgs,
        "update_media_counts": _update_media_counts,
        "save_settings": _save_settings,
        "search_events": _search_events,
    }
    try:
        return commands[command](payload)
    except KeyError as exc:
        raise ValueError(f"Unknown backend command: {command}") from exc


def _save_settings(payload: dict[str, Any]) -> dict[str, Any]:
    AppConfig.set_event_roots(
        str(payload.get("multimedia_events_root", "")),
        str(payload.get("local_events_root", "")),
    )
    AppConfig.set_default_event_year(str(payload.get("default_event_year", "")))
    return _config()


def _search_events(payload: dict[str, Any]) -> dict[str, Any]:
    index = MetadataSearchService().build_index(
        _search_roots(str(payload.get("source", "All event folders")))
    )
    return {
        "records": [_record(record) for record in index.records],
        "suggestions": index.suggestions,
        "school_years": index.school_years,
        "grades": index.grades,
        "keywords": index.keywords,
        "errors": index.errors,
    }


def main() -> None:
    try:
        request = json.load(sys.stdin)
        if not isinstance(request, dict):
            raise ValueError("The request must be a JSON object.")
        data = _dispatch(str(request.get("command", "")), request.get("payload", {}))
        print(json.dumps({"ok": True, "data": data}, default=str))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))


if __name__ == "__main__":
    main()
