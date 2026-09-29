import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from PIL import Image

from services.importer import PHOTO_EXTENSIONS
from services.metadata_service import MetadataService
from services.photo_brightness import brighten, extra_brightness_amount


JPEG_EXTENSIONS = {".jpg", ".jpeg"}
MAX_LONG_EDGE = 2500
JPEG_QUALITY = "90"


@dataclass
class UneditedJpgProgress:
    """Progress details emitted while generating browsing JPEGs."""

    current: int
    total: int
    current_file: Path | None = None
    message: str = ""


@dataclass
class UneditedJpgSummary:
    """Final JPEG generation outcome."""

    generated: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    failures: list[str] = field(default_factory=list)


class UneditedJpgService:
    """Creates resized, gently brightened JPEG copies from event photos."""

    def __init__(self, metadata_service: MetadataService | None = None) -> None:
        self.metadata_service = metadata_service or MetadataService()

    def generate_for_event(
        self,
        event_folder: Path,
        cancel_event: Event | None = None,
        progress_callback: Callable[[UneditedJpgProgress], None] | None = None,
        regenerate_all: bool = False,
        brightness: int = 0,
    ) -> UneditedJpgSummary:
        extra_brightness_amount(brightness)
        summary = UneditedJpgSummary()
        source_folder = event_folder / "Raw" / "Photos"
        destination_folder = event_folder / "Unedited JPGs" / "Photos"

        sources = self.supported_photos(source_folder)
        if not sources:
            self._update_metadata_count(event_folder, destination_folder)
            self._emit_progress(
                progress_callback,
                0,
                0,
                None,
                "No photos found for JPEG generation.",
            )
            return summary

        destination_folder.mkdir(parents=True, exist_ok=True)
        total = len(sources)

        for index, source in enumerate(sources, start=1):
            if cancel_event is not None and cancel_event.is_set():
                summary.cancelled = True
                summary.skipped += total - index + 1
                break

            self._emit_progress(progress_callback, index, total, source)
            destination = destination_folder / f"{source.stem}.jpg"

            if destination.exists() and not regenerate_all:
                summary.skipped += 1
                continue

            try:
                created = self._create_or_replace_jpeg(source, destination, regenerate_all, brightness)
            except Exception as exc:
                summary.failed += 1
                summary.failures.append(f"{source}: {exc}")
                continue

            if created:
                summary.generated += 1
            else:
                summary.skipped += 1

        self._update_metadata_count(event_folder, destination_folder)
        self._emit_progress(progress_callback, total, total, None, "JPEG generation finished.")
        return summary

    def supported_photos(self, source_folder: Path) -> list[Path]:
        if not source_folder.exists():
            return []

        return sorted(
            (
                path
                for path in source_folder.iterdir()
                if path.is_file() and path.suffix.casefold() in PHOTO_EXTENSIONS
            ),
            key=lambda path: path.name.casefold(),
        )

    def _create_jpeg(self, source: Path, destination: Path, brightness: int) -> None:
        suffix = source.suffix.casefold()
        dimensions = self._image_dimensions(source)
        long_edge = max(dimensions) if dimensions is not None else None
        prepared = source

        if suffix not in JPEG_EXTENSIONS or long_edge is None or long_edge > MAX_LONG_EDGE:
            prepared = destination.with_name("converted.jpg")
            command = [
                "sips",
                "-s",
                "format",
                "jpeg",
                "-s",
                "formatOptions",
                JPEG_QUALITY,
                "--resampleHeightWidthMax",
                str(MAX_LONG_EDGE),
                str(source),
                "--out",
                str(prepared),
            ]
            subprocess.run(command, check=True, capture_output=True, text=True)

        with Image.open(prepared) as image:
            brightened = brighten(image, brightness)
            if brightened is image:
                shutil.copy2(prepared, destination)
            else:
                exif = image.info.get("exif")
                icc_profile = image.info.get("icc_profile")
                options: dict[str, object] = {"quality": int(JPEG_QUALITY)}
                if exif:
                    options["exif"] = exif
                if icc_profile and brightened.mode == image.mode:
                    options["icc_profile"] = icc_profile
                brightened.save(destination, format="JPEG", **options)
        shutil.copystat(source, destination, follow_symlinks=True)

    def _create_or_replace_jpeg(
        self,
        source: Path,
        destination: Path,
        replace_existing: bool,
        brightness: int,
    ) -> bool:
        with tempfile.TemporaryDirectory(prefix=".jpg-", dir=destination.parent) as workdir:
            staged = Path(workdir) / "output.jpg"
            self._create_jpeg(source, staged, brightness)
            if replace_existing:
                os.replace(staged, destination)
            else:
                try:
                    os.link(staged, destination)
                except FileExistsError:
                    return False
        return True

    def _image_dimensions(self, source: Path) -> tuple[int, int] | None:
        command = ["sips", "-g", "pixelWidth", "-g", "pixelHeight", str(source)]
        try:
            completed = subprocess.run(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError:
            return None

        width: int | None = None
        height: int | None = None

        for line in completed.stdout.splitlines():
            text = line.strip()
            if text.startswith("pixelWidth:"):
                width = self._parse_dimension(text)
            elif text.startswith("pixelHeight:"):
                height = self._parse_dimension(text)

        if width is None or height is None:
            return None
        return width, height

    def _parse_dimension(self, text: str) -> int | None:
        try:
            return int(text.split(":", 1)[1].strip())
        except (IndexError, ValueError):
            return None

    def _update_metadata_count(self, event_folder: Path, destination_folder: Path) -> None:
        metadata_path = event_folder / "Data" / "metadata.json"
        if not metadata_path.exists():
            return

        count = sum(
            1
            for path in destination_folder.iterdir()
            if path.is_file() and path.suffix.casefold() in JPEG_EXTENSIONS
        ) if destination_folder.exists() else 0
        self.metadata_service.update_unedited_jpg_count(metadata_path, count)

    def _emit_progress(
        self,
        progress_callback: Callable[[UneditedJpgProgress], None] | None,
        current: int,
        total: int,
        current_file: Path | None,
        message: str = "",
    ) -> None:
        if progress_callback is not None:
            progress_callback(
                UneditedJpgProgress(current, total, current_file, message)
            )
