"""Capture metadata and full-resolution photo intermediates for FilmCraft."""

import os
import re
import subprocess
import tempfile
from functools import lru_cache
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener


register_heif_opener()


@lru_cache(maxsize=256)
def _video_header(path: str, size: int, modified: int) -> str:
    result = subprocess.run(
        [get_ffmpeg_exe(), "-hide_banner", "-nostdin", "-i", path, "-t", "0", "-f", "null", "-"],
        capture_output=True, text=True, timeout=45,
    )
    return result.stderr.split("Output #", 1)[0]


def video_rotation(path: Path) -> float:
    """Original display-matrix rotation, recorded for provenance, not re-applied.

    FilmCraft's decoder already returns oriented display dimensions and frames.
    """
    stat = path.stat()
    header = _video_header(str(path), stat.st_size, stat.st_mtime_ns)
    match = re.search(r"displaymatrix: rotation of ([-+\d.]+) degrees", header)
    if not match:
        match = re.search(r"^\s*rotate\s*:\s*([-+\d.]+)", header, re.MULTILINE)
    return -float(match.group(1)) if match else 0.0


def parse_capture_time(value: object, default_zone, offset: object = None) -> datetime | None:
    text = str(value or "").strip().strip("\x00")
    if not text or text.startswith(("0000", "1904-01-01", "1970-01-01")):
        return None
    text = re.sub(r"^(\d{4}):(\d{2}):(\d{2})", r"\1-\2-\3", text).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            if offset and re.fullmatch(r"[+-]\d{2}:\d{2}", str(offset)):
                parsed = datetime.fromisoformat(parsed.isoformat() + str(offset))
            else:
                parsed = parsed.replace(tzinfo=default_zone)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def capture_time(path: Path, media_type: str, hint: str | None, zone_name: str | None) -> tuple[str, str]:
    zone = ZoneInfo(zone_name) if zone_name else datetime.now().astimezone().tzinfo
    if media_type == "photo":
        try:
            with Image.open(path) as image:
                exif = image.getexif()
                nested = exif.get_ifd(34665) if 34665 in exif else {}
                for date_tag, offset_tag in ((36867, 36881), (36868, 36882), (306, 36880)):
                    value = nested.get(date_tag) or exif.get(date_tag)
                    offset = nested.get(offset_tag) or exif.get(offset_tag)
                    parsed = parse_capture_time(value, zone, offset)
                    if parsed:
                        return parsed.isoformat(), "EXIF" if offset else "EXIF (assumed event/local timezone)"
        except (OSError, ValueError, SyntaxError):
            pass
    else:
        stat = path.stat()
        header = _video_header(str(path), stat.st_size, stat.st_mtime_ns)
        for tag in ("com.apple.quicktime.creationdate", "creation_time", "date"):
            for value in re.findall(rf"^\s*{re.escape(tag)}\s*:\s*(.+)$", header, re.MULTILINE):
                parsed = parse_capture_time(value, zone)
                if parsed:
                    return parsed.isoformat(), "Original container metadata"
    parsed = parse_capture_time(hint, zone)
    if parsed:
        return parsed.isoformat(), "ECC import/session metadata"
    return datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat(), "Filesystem modification time"


def photo_intermediate(source: Path, target: Path) -> None:
    """A lossless full-size representation, only for a source FilmCraft cannot decode.

    Never uses the resized/brightened browsing JPG. Raw originals remain untouched.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".photo-", dir=target.parent) as directory:
        directory = Path(directory)
        try:
            image = Image.open(source)
        except (OSError, ValueError):
            converted = directory / "decoded.tiff"
            subprocess.run(["sips", "-s", "format", "tiff", str(source), "--out", str(converted)],
                           check=True, capture_output=True, timeout=120)
            image = Image.open(converted)
        with image:
            oriented = ImageOps.exif_transpose(image)
            icc = oriented.info.get("icc_profile")
            output = directory / "image.png"
            if oriented.mode not in {"RGB", "RGBA", "L", "LA", "I;16", "I"}:
                oriented = oriented.convert("RGBA" if "transparency" in oriented.info else "RGB")
            options = {"icc_profile": icc} if icc else {}
            oriented.save(output, "PNG", **options)
            with Image.open(output) as checked:
                checked.verify()
            with output.open("rb") as stream:
                os.fsync(stream.fileno())
            os.replace(output, target)
