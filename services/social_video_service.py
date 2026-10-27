"""Create compressed staff download copies while preserving event originals."""

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from threading import Event

from imageio_ffmpeg import get_ffmpeg_exe


SMALLER_VIDEO_FOLDER = Path("Raw") / "Smaller Videos"
VIDEO_BITRATE_LIMIT = "5M"
AUDIO_BITRATE = "128k"
# The filter is an identity operation for 1080p and smaller clips. FFmpeg
# applies rotation metadata before scaling, so portrait video stays portrait.
DOWNLOAD_SCALE = (
    "scale=w='if(gte(iw,ih),min(iw,1920),min(iw,1080))':"
    "h='if(gte(iw,ih),min(ih,1080),min(ih,1920))':"
    "force_original_aspect_ratio=decrease:force_divisible_by=2"
)


@dataclass(frozen=True)
class SocialVideoProgress:
    current: int
    total: int
    current_file: Path | None = None
    message: str = ""


@dataclass
class SocialVideoSummary:
    generated: int = 0
    skipped: int = 0
    failed: int = 0
    cancelled: bool = False
    source_bytes: int = 0
    output_bytes: int = 0
    failures: list[str] = field(default_factory=list)


class SocialVideoService:
    """Export H.264/AAC MP4s at up to 1080p with a 5 Mbps video ceiling."""

    @staticmethod
    def prepare_folder(event_folder: Path) -> Path:
        """Move earlier top-level copies under Raw without overwriting."""
        destination = event_folder / SMALLER_VIDEO_FOLDER
        destination.parent.mkdir(parents=True, exist_ok=True)
        for legacy in (event_folder / "Smaller Videos", event_folder / "Social Videos"):
            if legacy.is_dir() and not destination.exists():
                legacy.rename(destination)
        destination.mkdir(parents=True, exist_ok=True)
        return destination

    def generate_for_event(
        self, event_folder: Path, regenerate_all: bool = False,
        cancel_event: Event | None = None,
        progress_callback: Callable[[SocialVideoProgress], None] | None = None,
    ) -> SocialVideoSummary:
        # Import here to share the scanner's extension set without a module cycle.
        from services.importer import VIDEO_EXTENSIONS

        if not (event_folder / "Raw").is_dir():
            raise ValueError("Choose an event folder containing its Raw folder.")
        self.prepare_folder(event_folder)
        sources = sorted(
            (path for path in (event_folder / "Raw" / "Videos").rglob("*")
             if path.is_file() and path.suffix.casefold() in VIDEO_EXTENSIONS),
            key=lambda path: str(path).casefold(),
        )
        summary = SocialVideoSummary()
        for index, source in enumerate(sources, start=1):
            if cancel_event is not None and cancel_event.is_set():
                summary.cancelled = True
                break
            if progress_callback:
                progress_callback(SocialVideoProgress(index, len(sources), source, "Compressing staff download copy…"))
            try:
                if self.create_copy(source, event_folder, regenerate_all):
                    summary.generated += 1
                    summary.source_bytes += source.stat().st_size
                    summary.output_bytes += self.destination_for(source, event_folder).stat().st_size
                else:
                    summary.skipped += 1
            except Exception as exc:
                summary.failed += 1
                summary.failures.append(f"{source.name}: {exc}")
        if progress_callback:
            completed = summary.generated + summary.skipped + summary.failed
            progress_callback(SocialVideoProgress(completed, len(sources), message="Video compression finished."))
        return summary

    @staticmethod
    def destination_for(source: Path, event_folder: Path) -> Path:
        """Preserve subfolders and distinguish equal stems with different formats."""
        raw = event_folder / "Raw" / "Videos"
        relative = source.relative_to(raw) if source.is_relative_to(raw) else Path(source.name)
        # Include the original extension to avoid camera.mov/camera.mp4 collisions.
        name = f"{relative.name}.mp4" if relative.suffix.casefold() != ".mp4" else relative.name
        return event_folder / SMALLER_VIDEO_FOLDER / relative.parent / name

    def create_copy(self, source: Path, event_folder: Path, replace_existing: bool = False) -> bool:
        """Publish a complete compressed copy atomically, preserving originals."""
        self.prepare_folder(event_folder)
        destination = self.destination_for(source, event_folder)
        if destination.exists() and not replace_existing:
            return False
        destination_folder = destination.parent
        destination_folder.mkdir(parents=True, exist_ok=True)

        with tempfile.TemporaryDirectory(prefix=".social-video-", dir=destination_folder) as workdir:
            staged = Path(workdir) / "output.mp4"
            completed = subprocess.run(
                [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-nostdin",
                 "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                 "-vf", DOWNLOAD_SCALE, "-c:v", "libx264", "-preset", "medium",
                 "-crf", "23", "-maxrate", VIDEO_BITRATE_LIMIT, "-bufsize", "10M",
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                 "-ac", "2", "-movflags", "+faststart", "-map_metadata", "-1", str(staged)],
                capture_output=True, text=True,
            )
            if completed.returncode:
                detail = (completed.stderr or completed.stdout).strip()
                raise RuntimeError(detail or "The encoder could not compress this video.")
            if not staged.is_file() or staged.stat().st_size == 0:
                raise RuntimeError("The video converter did not produce a complete MP4.")
            shutil.copystat(source, staged)
            if replace_existing:
                os.replace(staged, destination)
            else:
                try:
                    os.link(staged, destination)
                except FileExistsError:
                    return False
        return True
