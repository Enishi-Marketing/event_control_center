import hashlib
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event

from services.hash_service import HashService
from services.metadata_service import MetadataService


PHOTO_EXTENSIONS = {
    ".cr3",
    ".cr2",
    ".dng",
    ".nef",
    ".arw",
    ".raf",
    ".orf",
    ".rw2",
    ".jpg",
    ".jpeg",
}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mxf", ".avi", ".mts", ".m2ts"}
THUMBNAIL_SIZE = 160


@dataclass(frozen=True)
class MediaThumbnail:
    """A small preview image generated for a scanned media file."""

    source: Path
    path: Path


@dataclass(frozen=True)
class MediaFile:
    """A supported media file discovered during a source scan."""

    path: Path
    media_type: str
    capture_time: datetime
    size: int


@dataclass(frozen=True)
class MediaSession:
    """A group of media files captured close together in time."""

    index: int
    files: tuple[MediaFile, ...]
    start_thumbnail: MediaThumbnail | None = None
    end_thumbnail: MediaThumbnail | None = None

    @property
    def start_time(self) -> datetime:
        return self.files[0].capture_time

    @property
    def end_time(self) -> datetime:
        return self.files[-1].capture_time

    @property
    def photo_count(self) -> int:
        return sum(1 for item in self.files if item.media_type == "photo")

    @property
    def video_count(self) -> int:
        return sum(1 for item in self.files if item.media_type == "video")

    @property
    def photos(self) -> tuple[MediaFile, ...]:
        return tuple(item for item in self.files if item.media_type == "photo")


@dataclass(frozen=True)
class MediaScanResult:
    """The result of scanning an import source."""

    source: Path
    files: tuple[MediaFile, ...]
    sessions: tuple[MediaSession, ...]
    skipped_count: int = 0
    failures: tuple[str, ...] = ()
    thumbnail_failures: tuple[str, ...] = ()

    @property
    def photo_count(self) -> int:
        return sum(1 for item in self.files if item.media_type == "photo")

    @property
    def video_count(self) -> int:
        return sum(1 for item in self.files if item.media_type == "video")

    @property
    def start_time(self) -> datetime | None:
        return self.files[0].capture_time if self.files else None

    @property
    def end_time(self) -> datetime | None:
        return self.files[-1].capture_time if self.files else None


@dataclass
class ImportProgress:
    """Progress details emitted while importing media."""

    current: int
    total: int
    current_file: Path | None = None
    message: str = ""
    current_bytes: int = 0
    total_bytes: int = 0
    bytes_per_second: float = 0.0
    phase: str = ""


@dataclass
class ImportSummary:
    """Final import outcome."""

    photos_imported: int = 0
    videos_imported: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    imported_sources: list[Path] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)


class ImportService:
    """Scans, groups, copies, verifies, and logs event media imports."""

    def __init__(
        self,
        hash_service: HashService | None = None,
        metadata_service: MetadataService | None = None,
    ) -> None:
        self.hash_service = hash_service or HashService()
        self.metadata_service = metadata_service or MetadataService()

    def scan_media(self, source: Path, session_gap_minutes: int) -> MediaScanResult:
        failures: list[str] = []
        thumbnail_failures: list[str] = []
        files: list[MediaFile] = []
        skipped_count = 0

        if not source.exists() or not source.is_dir():
            raise FileNotFoundError(f"Source folder is not available: {source}")

        for path in self._walk_source(source, failures):
            media_type = self._media_type(path)
            if media_type is None:
                skipped_count += 1
                continue

            media_file = self._build_media_file(path, media_type, failures)
            if media_file is not None:
                files.append(media_file)

        files.sort(key=lambda item: (item.capture_time, str(item.path).casefold()))
        sessions = self.detect_sessions(files, session_gap_minutes)
        sessions = self._with_session_thumbnails(sessions, thumbnail_failures)
        return MediaScanResult(
            source=source,
            files=tuple(files),
            sessions=tuple(sessions),
            skipped_count=skipped_count,
            failures=tuple(failures),
            thumbnail_failures=tuple(thumbnail_failures),
        )

    def detect_sessions(
        self,
        files: list[MediaFile],
        session_gap_minutes: int,
    ) -> list[MediaSession]:
        if not files:
            return []

        sessions: list[MediaSession] = []
        current: list[MediaFile] = [files[0]]
        gap_seconds = max(1, session_gap_minutes) * 60

        for media_file in files[1:]:
            gap = (media_file.capture_time - current[-1].capture_time).total_seconds()
            if gap > gap_seconds:
                sessions.append(MediaSession(len(sessions) + 1, tuple(current)))
                current = []
            current.append(media_file)

        sessions.append(MediaSession(len(sessions) + 1, tuple(current)))
        return sessions

    def files_in_time_range(
        self,
        files: tuple[MediaFile, ...],
        start_time: datetime,
        end_time: datetime,
    ) -> list[MediaFile]:
        return [
            item
            for item in files
            if start_time <= item.capture_time <= end_time
        ]

    def import_media(
        self,
        files: list[MediaFile],
        event_folder: Path,
        source: Path,
        cancel_event: Event,
        progress_callback: Callable[[ImportProgress], None] | None = None,
        skipped_count: int = 0,
        event_name: str | None = None,
    ) -> ImportSummary:
        summary = ImportSummary(skipped=skipped_count)
        total = len(files)
        base_name = self._safe_filename(
            event_name or self._event_name_from_folder(event_folder)
        )
        photo_sequence = self._next_sequence(
            event_folder / "Raw" / "Photos",
            base_name,
        )
        video_sequence = self._next_sequence(
            event_folder / "Raw" / "Videos",
            f"{base_name} clip",
        )

        for index, media_file in enumerate(files, start=1):
            if cancel_event.is_set():
                summary.cancelled = True
                summary.skipped += total - index + 1
                break

            self._emit_progress(
                progress_callback,
                index,
                total,
                media_file.path,
                current_bytes=0,
                total_bytes=media_file.size,
                phase="Copying",
            )
            if media_file.media_type == "photo":
                destination_name = self._renamed_media_name(
                    base_name,
                    photo_sequence,
                    media_file.path.suffix,
                )
                photo_sequence += 1
            else:
                destination_name = self._renamed_media_name(
                    f"{base_name} clip",
                    video_sequence,
                    media_file.path.suffix,
                )
                video_sequence += 1

            try:
                destination = self._copy_and_verify(
                    media_file,
                    event_folder,
                    destination_name,
                    index,
                    total,
                    progress_callback,
                )
            except Exception as exc:
                summary.failed += 1
                summary.failures.append(f"{media_file.path}: {exc}")
                continue

            if destination is None:
                summary.failed += 1
                summary.failures.append(f"{media_file.path}: hash verification failed")
                continue

            if media_file.media_type == "photo":
                summary.photos_imported += 1
            else:
                summary.videos_imported += 1
            summary.imported_sources.append(media_file.path)

        metadata_path = event_folder / "Data" / "metadata.json"
        if metadata_path.exists():
            self.metadata_service.update_import_counts(
                metadata_path,
                summary.photos_imported,
                summary.videos_imported,
            )

        self.write_import_log(event_folder, source, summary)
        self._emit_progress(progress_callback, total, total, None, "Import finished.")
        return summary

    def write_import_log(
        self,
        event_folder: Path,
        source: Path,
        summary: ImportSummary,
    ) -> None:
        log_path = event_folder / "Data" / "import.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        lines = [
            "==================================",
            timestamp,
            "Source:",
            str(source),
            "Destination:",
            event_folder.name,
            "Photos Imported:",
            str(summary.photos_imported),
            "Videos Imported:",
            str(summary.videos_imported),
            "Skipped:",
            str(summary.skipped),
            "Failures:",
            str(summary.failed),
            "Cancelled:",
            str(summary.cancelled),
        ]

        if summary.failures:
            lines.append("Failure Details:")
            lines.extend(summary.failures)

        with log_path.open("a", encoding="utf-8") as file:
            file.write("\n".join(lines) + "\n\n")

    def _walk_source(self, source: Path, failures: list[str]) -> list[Path]:
        found: list[Path] = []
        try:
            for path in source.rglob("*"):
                try:
                    if path.is_file():
                        found.append(path)
                except OSError as exc:
                    failures.append(f"{path}: {exc}")
        except OSError as exc:
            failures.append(f"{source}: {exc}")
        return found

    def _build_media_file(
        self,
        path: Path,
        media_type: str,
        failures: list[str],
    ) -> MediaFile | None:
        try:
            stat = path.stat()
        except OSError as exc:
            failures.append(f"{path}: {exc}")
            return None

        return MediaFile(
            path=path,
            media_type=media_type,
            capture_time=datetime.fromtimestamp(stat.st_mtime).astimezone(),
            size=stat.st_size,
        )

    def _media_type(self, path: Path) -> str | None:
        suffix = path.suffix.casefold()
        if suffix in PHOTO_EXTENSIONS:
            return "photo"
        if suffix in VIDEO_EXTENSIONS:
            return "video"
        return None

    def _with_session_thumbnails(
        self,
        sessions: list[MediaSession],
        thumbnail_failures: list[str],
    ) -> list[MediaSession]:
        updated: list[MediaSession] = []
        for session in sessions:
            photos = session.photos
            if not photos:
                updated.append(session)
                continue

            start_thumbnail = self._build_thumbnail(photos[0], thumbnail_failures)
            end_thumbnail = (
                start_thumbnail
                if photos[-1].path == photos[0].path
                else self._build_thumbnail(photos[-1], thumbnail_failures)
            )
            updated.append(
                MediaSession(
                    index=session.index,
                    files=session.files,
                    start_thumbnail=start_thumbnail,
                    end_thumbnail=end_thumbnail,
                )
            )
        return updated

    def _build_thumbnail(
        self,
        media_file: MediaFile,
        thumbnail_failures: list[str],
    ) -> MediaThumbnail | None:
        cache_path = self._thumbnail_cache_path(media_file.path)
        if cache_path.exists():
            return MediaThumbnail(source=media_file.path, path=cache_path)

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        converters = [
            [
                "sips",
                "-s",
                "format",
                "png",
                "-Z",
                str(THUMBNAIL_SIZE),
                str(media_file.path),
                "--out",
                str(cache_path),
            ],
            [
                "magick",
                str(media_file.path),
                "-auto-orient",
                "-thumbnail",
                f"{THUMBNAIL_SIZE}x{THUMBNAIL_SIZE}",
                str(cache_path),
            ],
        ]

        for command in converters:
            if shutil.which(command[0]) is None:
                continue
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    timeout=20,
                    text=True,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                thumbnail_failures.append(f"Thumbnail {media_file.path}: {exc}")
                continue

            if completed.returncode == 0 and cache_path.exists():
                return MediaThumbnail(source=media_file.path, path=cache_path)

        cache_path.unlink(missing_ok=True)
        thumbnail_failures.append(
            f"Thumbnail {media_file.path}: preview could not be generated"
        )
        return None

    def _thumbnail_cache_path(self, source: Path) -> Path:
        try:
            stat = source.stat()
            fingerprint = f"{source}|{stat.st_mtime_ns}|{stat.st_size}"
        except OSError:
            fingerprint = str(source)
        digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()
        return (
            Path(tempfile.gettempdir())
            / "event_control_center_thumbnails"
            / f"{digest}.png"
        )

    def _copy_and_verify(
        self,
        media_file: MediaFile,
        event_folder: Path,
        destination_name: str,
        current: int,
        total: int,
        progress_callback: Callable[[ImportProgress], None] | None,
    ) -> Path | None:
        folder = event_folder / "Raw" / (
            "Photos" if media_file.media_type == "photo" else "Videos"
        )
        folder.mkdir(parents=True, exist_ok=True)
        destination = self._unique_destination(folder / destination_name)

        self._copy_with_progress(
            media_file,
            destination,
            current,
            total,
            progress_callback,
        )
        try:
            self._emit_progress(
                progress_callback,
                current,
                total,
                media_file.path,
                current_bytes=media_file.size,
                total_bytes=media_file.size,
                phase="Verifying",
            )
            if self.hash_service.verify(media_file.path, destination):
                return destination
            destination.unlink(missing_ok=True)
            return None
        except Exception:
            destination.unlink(missing_ok=True)
            raise

    def _copy_with_progress(
        self,
        media_file: MediaFile,
        destination: Path,
        current: int,
        total: int,
        progress_callback: Callable[[ImportProgress], None] | None,
    ) -> None:
        total_bytes = media_file.size
        copied = 0
        started_at = time.monotonic()
        last_emit_at = started_at
        chunk_size = 1024 * 1024 * 4

        with (
            media_file.path.open("rb") as source_file,
            destination.open("wb") as dest_file,
        ):
            while True:
                chunk = source_file.read(chunk_size)
                if not chunk:
                    break

                dest_file.write(chunk)
                copied += len(chunk)
                now = time.monotonic()
                if now - last_emit_at >= 0.1 or copied >= total_bytes:
                    elapsed = max(now - started_at, 0.001)
                    self._emit_progress(
                        progress_callback,
                        current,
                        total,
                        media_file.path,
                        current_bytes=copied,
                        total_bytes=total_bytes,
                        bytes_per_second=copied / elapsed,
                        phase="Copying",
                    )
                    last_emit_at = now

        shutil.copystat(media_file.path, destination, follow_symlinks=True)

    def _unique_destination(self, destination: Path) -> Path:
        if not destination.exists():
            return destination

        stem = destination.stem
        suffix = destination.suffix
        for number in range(1, 1000):
            candidate = destination.with_name(f"{stem}_{number:03d}{suffix}")
            if not candidate.exists():
                return candidate

        raise FileExistsError(f"No available filename for {destination.name}")

    def _event_name_from_folder(self, event_folder: Path) -> str:
        folder_name = event_folder.name
        if " - " in folder_name:
            return folder_name.split(" - ", 1)[1]
        return folder_name

    def _safe_filename(self, name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "-", name.strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" .") or "Event"

    def _renamed_media_name(self, prefix: str, sequence: int, suffix: str) -> str:
        return f"{prefix} {sequence:03d}{suffix}"

    def _next_sequence(self, folder: Path, prefix: str) -> int:
        if not folder.exists():
            return 1

        pattern = re.compile(rf"^{re.escape(prefix)} (?P<number>\d{{3,}})(?:_|$)")
        highest = 0
        for path in folder.iterdir():
            if not path.is_file():
                continue
            match = pattern.match(path.stem)
            if match is not None:
                highest = max(highest, int(match.group("number")))

        return highest + 1

    def _emit_progress(
        self,
        progress_callback: Callable[[ImportProgress], None] | None,
        current: int,
        total: int,
        current_file: Path | None,
        message: str = "",
        current_bytes: int = 0,
        total_bytes: int = 0,
        bytes_per_second: float = 0.0,
        phase: str = "",
    ) -> None:
        if progress_callback is not None:
            progress_callback(
                ImportProgress(
                    current,
                    total,
                    current_file,
                    message,
                    current_bytes,
                    total_bytes,
                    bytes_per_second,
                    phase,
                )
            )


class Importer(ImportService):
    """Backward-compatible alias for the media import service."""
