"""Account for originals and conversions before offering source cleanup."""

import json
from collections import Counter
from collections.abc import Sequence
from pathlib import Path
from uuid import uuid4

from services.importer import (
    PHOTO_EXTENSIONS,
    ImportService,
    ImportSummary,
    MediaFile,
    MediaScanResult,
    is_system_file,
)
from services.media_count_service import MediaCountService
from services.social_video_service import SocialVideoService
from services.unedited_jpg_service import UneditedJpgSummary


class ImportCheckService:
    """Save a count report and the verified source-to-archive mapping."""

    def finalize(
        self, scan: MediaScanResult, selected_files: Sequence[MediaFile], summary: ImportSummary,
        jpgs: UneditedJpgSummary, event_folder: Path,
        preparation_failures: list[str] | None = None,
    ) -> dict[str, object]:
        warnings: list[str] = []
        if preparation_failures:
            warnings.append("Editing-project preparation needs attention. Keep the source and review the project results.")
        scanner = ImportService()
        read_failures = list(scan.failures)
        current_files = [p for p in scanner._walk_source(scan.source, read_failures) if not is_system_file(p)]
        current_media = {p for p in current_files if scanner._media_type(p) is not None}
        other_files = [p for p in current_files if p not in current_media]
        scanned_media = {item.path for item in scan.files}
        selected_paths = {item.path for item in selected_files}
        imported_paths = {item.source for item in summary.imported_files}
        unselected_files = sorted(current_media - selected_paths)
        unimported_files = sorted(selected_paths - imported_paths)
        selected_count = len(selected_files)
        if current_media != scanned_media:
            warnings.append("Photos or videos on the source changed during import. Scan again before deleting anything.")
        if any(p.is_symlink() for p in current_media):
            warnings.append("The source contains linked photos or videos. Keep the source and review those files manually.")
        missing_originals = []
        for item in summary.imported_files:
            if (not item.destination.is_file() or not item.source.is_file()
                or item.destination.stat().st_size != item.source.stat().st_size):
                missing_originals.append(str(item.destination))
        if missing_originals:
            warnings.append(f"{len(missing_originals)} original copy/copies are missing or have a different size. Keep the source.")
        missing_photos: list[str] = []
        missing_videos: list[str] = []
        raw_photos = summary.imported_photos
        raw_videos = [item.destination for item in summary.imported_files if item.media_type == "video"]
        for photo in raw_photos:
            output = event_folder / "Unedited JPGs" / "Photos" / f"{photo.stem}.jpg"
            if not self._ready(output):
                missing_photos.append(str(photo.relative_to(event_folder)))
        for video in raw_videos:
            if not self._ready(SocialVideoService.destination_for(video, event_folder)):
                missing_videos.append(str(video.relative_to(event_folder)))

        # Check for shared JPG names only where an original from this import
        # could be mistaken for another photo already in the archive.
        imported_stems = {p.stem.casefold() for p in raw_photos}
        archive_stems = Counter(
            p.stem.casefold() for p in (event_folder / "Raw" / "Photos").rglob("*")
            if p.stem.casefold() in imported_stems and p.suffix.casefold() in PHOTO_EXTENSIONS
            and not is_system_file(p) and p.is_file()
        ) if imported_stems else Counter()
        collisions = sorted(stem for stem, count in archive_stems.items() if count > 1)
        if read_failures:
            warnings.append(f"{len(set(read_failures))} source read issue(s); the source count may be incomplete.")
        verified_count = len(summary.imported_files) - len(missing_originals)
        if summary.failed or summary.cancelled or unimported_files or len(summary.imported_files) != selected_count:
            warnings.append(f"Original count check: {verified_count} of {selected_count} selected files verified.")
        if missing_photos:
            warnings.append(f"{len(missing_photos)} photo(s) have no JPG conversion. Originals remain in Raw/Photos.")
        if missing_videos:
            warnings.append(f"{len(missing_videos)} video(s) have no smaller copy. Originals remain in Raw/Videos.")
        if collisions:
            warnings.append(f"{len(collisions)} photo filename collision(s) prevent a separate JPG for each original.")
        if jpgs.failed or jpgs.cancelled or summary.social_videos_failed:
            warnings.append("Some conversions failed or were cancelled. Keep the source and review the report.")

        records = []
        for imported in summary.imported_files:
            conversion = (
                event_folder / "Unedited JPGs" / "Photos" / f"{imported.destination.stem}.jpg"
                if imported.media_type == "photo"
                else SocialVideoService.destination_for(imported.destination, event_folder)
            )
            records.append({
                "source": str(imported.source.resolve()),
                "destination": str(imported.destination.resolve()),
                "conversion": str(conversion.resolve()), "media_type": imported.media_type,
                "capture_time": imported.capture_time.isoformat() if imported.capture_time else None,
            })

        report_dir = event_folder / "Data" / "Import Checks"
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path = report_dir / f"{uuid4().hex}.json"
        cleanup_allowed = bool(records) and not warnings and selected_paths == imported_paths
        check = {
            "source_file_count": len(current_media),
            "source_photo_count": sum(scanner._media_type(p) == "photo" for p in current_media),
            "source_video_count": sum(scanner._media_type(p) == "video" for p in current_media),
            "selected_count": selected_count, "verified_original_count": verified_count,
            "unimported_count": len(unimported_files), "unselected_count": len(unselected_files),
            "raw_photo_count": len(raw_photos), "raw_video_count": len(raw_videos),
            "jpg_count": len(raw_photos) - len(missing_photos),
            "smaller_video_count": len(raw_videos) - len(missing_videos),
            "warnings": warnings, "cleanup_allowed": cleanup_allowed,
            "report_path": str(report_path.resolve()),
        }
        report = {
            "version": 2, "source": str(scan.source.resolve()),
            "event_folder": str(event_folder.resolve()), "check": check,
            "records": records,
            "source_media": sorted(str(p.relative_to(scan.source)) for p in current_media),
            "unrecognized_files": [str(p) for p in other_files],
            "unselected_files": [str(p) for p in unselected_files],
            "unimported_files": [str(p) for p in unimported_files],
            "missing_jpgs": missing_photos, "missing_smaller_videos": missing_videos,
            "missing_originals": missing_originals,
            "conversion_collisions": collisions, "scan_failures": read_failures,
            "import_failures": summary.failures, "jpg_failures": jpgs.failures,
            "preparation_failures": preparation_failures or [],
        }
        report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        summary.check = check
        metadata = event_folder / "Data" / "metadata.json"
        if metadata.exists():
            MediaCountService().update_event_counts(event_folder)
        with (event_folder / "Data" / "import.log").open("a", encoding="utf-8") as log:
            log.write("Count check:\n" + json.dumps(check, indent=2) + "\n")
        return check

    @staticmethod
    def _ready(path: Path) -> bool:
        return path.is_file() and path.stat().st_size > 0
