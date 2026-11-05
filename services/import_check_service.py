"""Account for originals and conversions before offering source cleanup."""

import json
from collections import Counter
from pathlib import Path
from uuid import uuid4

from services.importer import ImportService, ImportSummary, MediaScanResult, PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, is_system_file
from services.media_count_service import MediaCountService
from services.social_video_service import SocialVideoService
from services.unedited_jpg_service import UneditedJpgSummary


class ImportCheckService:
    """Save a count report and the verified source-to-archive mapping."""

    def finalize(
        self, scan: MediaScanResult, selected_count: int, summary: ImportSummary,
        jpgs: UneditedJpgSummary, event_folder: Path,
        preparation_failures: list[str] | None = None,
    ) -> dict[str, object]:
        warnings: list[str] = []
        if preparation_failures:
            warnings.append("Editing-project preparation needs attention. Keep the source and review the project results.")
        scanner = ImportService()
        read_failures = list(scan.failures)
        current_files = [p for p in scanner._walk_source(scan.source, read_failures) if not is_system_file(p)]
        current_paths = {p.resolve() for p in current_files}
        other_files = [p for p in current_files if scanner._media_type(p) is None]
        scanned_paths = {p.resolve() for p in scan.other_files} | {item.path.resolve() for item in scan.files}
        imported_paths = {item.source.resolve() for item in summary.imported_files}
        if current_paths != scanned_paths:
            warnings.append("Source contents changed during import. Scan again before deleting anything.")
        if any(p.is_symlink() for p in current_files):
            warnings.append("The source contains symbolic links. Keep the source and review those files manually.")
        missing_originals = []
        for item in summary.imported_files:
            if (not item.destination.is_file() or not item.source.is_file()
                or item.destination.stat().st_size != item.source.stat().st_size):
                missing_originals.append(str(item.destination))
        if missing_originals:
            warnings.append(f"{len(missing_originals)} original copy/copies are missing or have a different size. Keep the source.")
        missing_photos: list[str] = []
        missing_videos: list[str] = []
        raw_photos = self._files(event_folder / "Raw" / "Photos", PHOTO_EXTENSIONS)
        raw_videos = self._files(event_folder / "Raw" / "Videos", VIDEO_EXTENSIONS)
        for photo in raw_photos:
            output = event_folder / "Unedited JPGs" / "Photos" / f"{photo.stem}.jpg"
            if not self._ready(output):
                missing_photos.append(str(photo.relative_to(event_folder)))
        for video in raw_videos:
            if not self._ready(SocialVideoService.destination_for(video, event_folder)):
                missing_videos.append(str(video.relative_to(event_folder)))

        # Separate originals must not be counted as separate conversions if
        # they would share one JPG filename (possible in manually added media).
        collisions = [stem for stem, count in Counter(p.stem.casefold() for p in raw_photos).items() if count > 1]
        unimported = len(current_paths - imported_paths)
        if unimported:
            warnings.append(f"{unimported} source file(s) were not imported. Keep the source.")
        if other_files:
            warnings.append(f"{len(other_files)} unrecognized file(s) were left on the source; see the full report.")
        if read_failures:
            warnings.append(f"{len(set(read_failures))} source read issue(s); the source count may be incomplete.")
        if summary.failed or summary.cancelled or len(summary.imported_files) != selected_count:
            warnings.append(f"Original count check: {len(summary.imported_files)} of {selected_count} selected files verified.")
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
        check = {
            "source_file_count": len(current_files),
            "source_photo_count": sum(scanner._media_type(p) == "photo" for p in current_files),
            "source_video_count": sum(scanner._media_type(p) == "video" for p in current_files),
            "selected_count": selected_count, "verified_original_count": len(records) - len(missing_originals),
            "unimported_count": unimported,
            "raw_photo_count": len(raw_photos), "raw_video_count": len(raw_videos),
            "jpg_count": len(raw_photos) - len(missing_photos),
            "smaller_video_count": len(raw_videos) - len(missing_videos),
            "warnings": warnings, "cleanup_allowed": bool(records) and not warnings,
            "report_path": str(report_path.resolve()),
        }
        report = {
            "version": 1, "source": str(scan.source.resolve()),
            "event_folder": str(event_folder.resolve()), "check": check,
            "records": records, "unrecognized_files": [str(p) for p in other_files],
            "unimported_files": [str(p) for p in current_files if p.resolve() not in imported_paths],
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

    @staticmethod
    def _files(folder: Path, extensions: set[str]) -> list[Path]:
        return sorted(p for p in folder.rglob("*") if p.is_file() and not is_system_file(p) and p.suffix.casefold() in extensions)
