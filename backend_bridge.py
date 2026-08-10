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
from services.archive_service import ArchiveService
from services.drive_detector import DriveDetector
from services.folder_service import FolderService
from services.importer import ImportProgress, ImportService, MediaScanResult
from services.media_count_service import MediaCountService
from services.metadata_service import MetadataService
from services.project_service import ProjectService
from services.search_service import MetadataSearchRecord, MetadataSearchService
from services.source_cleanup_service import SourceCleanupService
from services.sync_service import SyncService
from services.unedited_jpg_service import UneditedJpgProgress, UneditedJpgService


def _config() -> dict[str, str]:
    return {
        "default_event_year": AppConfig.DEFAULT_EVENT_YEAR,
        "default_school_year": AppConfig.DEFAULT_SCHOOL_YEAR,
        "event_root": str(AppConfig.EVENT_ROOT),
        "local_event_root": str(AppConfig.LOCAL_EVENT_ROOT),
        "multimedia_events_root": str(AppConfig.MULTIMEDIA_EVENTS_ROOT),
        "local_events_root": str(AppConfig.LOCAL_EVENTS_ROOT),
        "google_sheets_credentials_file": AppConfig.GOOGLE_SHEETS_CREDENTIALS_FILE,
        "google_sheets_spreadsheet_id": AppConfig.GOOGLE_SHEETS_SPREADSHEET_ID,
        "google_sheets_worksheet_name": AppConfig.GOOGLE_SHEETS_WORKSHEET_NAME,
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
                "start_thumbnail": (
                    str(session.start_thumbnail.path)
                    if session.start_thumbnail is not None
                    else None
                ),
                "end_thumbnail": (
                    str(session.end_thumbnail.path)
                    if session.end_thumbnail is not None
                    else None
                ),
            }
            for session in result.sessions
        ],
    }


def _available_sources(_payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "sources": [
            {
                "name": source.name,
                "path": str(source.path),
                "is_removable": source.is_removable,
            }
            for source in DriveDetector().available_sources()
        ]
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


def _import_media(
    payload: dict[str, Any],
    progress_callback: Callable[[ImportProgress], None] | None = None,
) -> dict[str, Any]:
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
        progress_callback=progress_callback,
        skipped_count=scan.skipped_count + len(scan.files) - len(selected_files),
        event_name=str(payload.get("event_name", "")),
    )
    if progress_callback is not None:
        progress_callback(
            ImportProgress(
                current=len(selected_files),
                total=len(selected_files),
                message="Generating JPG previews…",
                phase="Generating previews",
            )
        )
    jpg_summary = UneditedJpgService().generate_for_event(event_folder)
    return {
        "photos_imported": summary.photos_imported,
        "videos_imported": summary.videos_imported,
        "skipped": summary.skipped,
        "failed": summary.failed,
        "jpgs_generated": jpg_summary.generated,
        "failures": summary.failures + jpg_summary.failures,
        "imported_sources": [str(path) for path in summary.imported_sources],
    }


def _emit_stream_event(event_type: str, **values: object) -> None:
    print(json.dumps({"type": event_type, **values}, default=str), flush=True)


def _stream_import_media(payload: dict[str, Any]) -> None:
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
        _emit_stream_event("error", error="Select at least one media session to import.")
        return

    import_count = len(selected_files)
    jpeg_estimate = sum(item.media_type == "photo" for item in selected_files)
    project_estimate = int(jpeg_estimate > 0) + int(
        any(item.media_type == "video" for item in selected_files)
    )
    overall_total = max(import_count + jpeg_estimate + project_estimate, 1)

    def import_progress_callback(progress: ImportProgress) -> None:
        if progress.total_bytes:
            overall_completed = max(progress.current - 1, 0) + (
                progress.current_bytes / progress.total_bytes
            )
        elif progress.current >= progress.total:
            overall_completed = progress.current
        else:
            overall_completed = max(progress.current - 1, 0)
        _emit_stream_event(
            "progress",
            current=progress.current,
            total=progress.total,
            current_file=str(progress.current_file) if progress.current_file else "",
            message=progress.message,
            current_bytes=progress.current_bytes,
            total_bytes=progress.total_bytes,
            bytes_per_second=progress.bytes_per_second,
            phase=progress.phase,
            overall_completed=overall_completed,
            overall_total=overall_total,
        )

    def jpg_progress_callback(progress: UneditedJpgProgress) -> None:
        _emit_stream_event(
            "progress",
            current=progress.current,
            total=progress.total,
            current_file=str(progress.current_file) if progress.current_file else "",
            message=progress.message or "Generating JPG previews…",
            phase="Generating previews",
            overall_completed=import_count + min(progress.current, jpeg_estimate),
            overall_total=overall_total,
        )

    try:
        _emit_stream_event(
            "progress",
            message="Preparing import…",
            phase="Preparing",
            overall_completed=0,
            overall_total=overall_total,
        )
        service = ImportService()
        summary = service.import_media(
            selected_files,
            event_folder,
            source,
            Event(),
            progress_callback=import_progress_callback,
            skipped_count=scan.skipped_count + len(scan.files) - len(selected_files),
            event_name=str(payload.get("event_name", "")),
        )
        jpg_service = UneditedJpgService()
        jpeg_destination = event_folder / "Unedited JPGs" / "Photos"
        jpeg_estimate = sum(
            1
            for photo in jpg_service.supported_photos(event_folder / "Raw" / "Photos")
            if not (jpeg_destination / f"{photo.stem}.jpg").exists()
        )
        has_photos = summary.photos_imported > 0
        has_videos = summary.videos_imported > 0
        project_estimate = int(has_photos) + int(has_videos)
        overall_total = max(import_count + jpeg_estimate + project_estimate, 1)
        jpg_summary = jpg_service.generate_for_event(
            event_folder,
            progress_callback=jpg_progress_callback,
        )
        projects_to_create = int(has_photos) + int(has_videos)
        if projects_to_create:
            _emit_stream_event(
                "progress",
                message="Creating blank editing project files…",
                phase="Creating projects",
                overall_completed=import_count + jpeg_estimate,
                overall_total=overall_total,
            )
        project_summary = ProjectService().create_projects(
            event_folder,
            str(payload.get("event_name", "")),
            has_photos,
            has_videos,
        )
        outcome = {
            "photos_imported": summary.photos_imported,
            "videos_imported": summary.videos_imported,
            "skipped": summary.skipped,
            "failed": summary.failed,
            "jpgs_generated": jpg_summary.generated,
            "failures": summary.failures + jpg_summary.failures + project_summary.failures,
            "imported_sources": [str(path) for path in summary.imported_sources],
        }
    except Exception as exc:
        _emit_stream_event("error", error=str(exc))
        return

    _emit_stream_event(
        "progress",
        message="Import complete.",
        phase="Finishing",
        overall_completed=overall_total,
        overall_total=overall_total,
    )
    _emit_stream_event("completed", outcome=outcome)


def _generate_jpgs(payload: dict[str, Any]) -> dict[str, Any]:
    summary = UneditedJpgService().generate_for_event(
        Path(str(payload["event_folder"])),
        regenerate_all=bool(payload.get("regenerate_all", False)),
    )
    return asdict(summary)


def _cleanup_imported_media(payload: dict[str, Any]) -> dict[str, Any]:
    result = SourceCleanupService().cleanup_imported_files(
        [Path(str(path)) for path in payload.get("files", [])],
        Path(str(payload["source"])),
    )
    return {
        "deleted": result.deleted,
        "delete_failures": result.delete_failures,
        "ejected": result.ejected,
        "eject_message": result.eject_message,
    }


def _update_media_counts(payload: dict[str, Any]) -> dict[str, Any]:
    result = MediaCountService().update_event_root_counts(Path(str(payload["event_root"])))
    return {
        "found": result.found,
        "updated": result.updated,
        "unchanged": result.unchanged,
        "failed": result.failed,
        "failures": [error.message for error in result.errors],
    }


def _sync_google_sheets(payload: dict[str, Any]) -> dict[str, Any]:
    result = SyncService().sync_event_root(Path(str(payload["event_root"])))
    return {
        "found": result.found,
        "synced": result.synced,
        "partial": result.partial,
        "failed": result.failed,
        "failures": [
            f"{error.event_folder.name}: {error.message}" for error in result.errors
        ],
    }


def _archive_candidates(payload: dict[str, Any]) -> dict[str, Any]:
    source_root = Path(str(payload["source_root"])).expanduser()
    archive_root = Path(str(payload["archive_root"])).expanduser()
    candidates = ArchiveService().discover_candidates(source_root, archive_root)
    return {
        "candidates": [
            {
                "source": str(candidate.source),
                "year": candidate.year,
                "name": candidate.name,
                "destination": str(candidate.destination),
                "already_archived": candidate.already_archived,
                "destination_exists": candidate.destination_exists,
            }
            for candidate in candidates
        ]
    }


def _archive_events(payload: dict[str, Any]) -> dict[str, Any]:
    source_root = Path(str(payload["source_root"])).expanduser()
    archive_root = Path(str(payload["archive_root"])).expanduser()
    event_folders = [
        Path(str(path)).expanduser() for path in payload.get("event_folders", [])
    ]
    if not event_folders:
        raise ValueError("Select at least one event to archive.")

    result = ArchiveService().archive_events(source_root, archive_root, event_folders)
    return {
        "source_root": str(result.source_root),
        "archive_root": str(result.archive_root),
        "selected": result.selected,
        "moved": result.moved,
        "skipped": result.skipped,
        "failed": result.failed,
        "results": [
            {
                "source": str(item.source),
                "destination": str(item.destination),
                "status": item.status,
                "message": item.message,
            }
            for item in result.results
        ],
    }


def _dispatch(command: str, payload: dict[str, Any]) -> dict[str, Any]:
    commands: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
        "config": lambda _payload: _config(),
        "available_sources": _available_sources,
        "create_event": _create_event,
        "scan_media": lambda values: _scan_result(
            ImportService().scan_media(
                Path(str(values["source"])),
                max(1, int(values.get("session_gap_minutes", 20))),
            )
        ),
        "import_media": _import_media,
        "generate_jpgs": _generate_jpgs,
        "cleanup_imported_media": _cleanup_imported_media,
        "update_media_counts": _update_media_counts,
        "sync_google_sheets": _sync_google_sheets,
        "archive_candidates": _archive_candidates,
        "archive_events": _archive_events,
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
    AppConfig.set_google_sheets(
        str(payload.get("google_sheets_credentials_file", "")),
        str(payload.get("google_sheets_spreadsheet_id", "")),
        str(payload.get("google_sheets_worksheet_name", "Events")),
    )
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
        command = str(request.get("command", ""))
        payload = request.get("payload", {})
        if command == "import_media_stream":
            _stream_import_media(payload)
            return
        data = _dispatch(command, payload)
        print(json.dumps({"ok": True, "data": data}, default=str))
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))


if __name__ == "__main__":
    main()
