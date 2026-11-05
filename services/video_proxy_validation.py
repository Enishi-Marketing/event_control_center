"""Provenance for ECC's existing Smaller Videos, including legacy copies."""

import fcntl
import json
import math
import subprocess
from array import array
from pathlib import Path

from imageio_ffmpeg import get_ffmpeg_exe

from services.media_identity import atomic_json, media_identity, same_content


def record_proxy(event: Path, source: Path, proxy: Path, source_identity: dict, proxy_identity: dict) -> None:
    if not source.is_relative_to(event / "Raw" / "Videos"):
        return
    data = event / "Data"
    data.mkdir(parents=True, exist_ok=True)
    with (data / ".smaller-videos.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = data / "smaller_video_manifest.json"
        document = json.loads(path.read_text()) if path.exists() else {"version": 1, "videos": {}}
        document["videos"][str(source.relative_to(event))] = {
            "proxy": str(proxy.relative_to(event)), "source_identity": source_identity,
            "proxy_identity": proxy_identity,
        }
        atomic_json(path, document)


def _sample(path: Path, seconds: float, audio: bool = False) -> bytes:
    arguments = [get_ffmpeg_exe(), "-v", "error", "-nostdin", "-ss", str(max(0, seconds)), "-i", str(path)]
    if audio:
        arguments += ["-map", "0:a:0", "-t", "0.25", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"]
    else:
        arguments += ["-map", "0:v:0", "-frames:v", "1", "-vf",
                      "scale=iw*sar:ih,setsar=1,scale=32:32:force_original_aspect_ratio=decrease,pad=32:32:(ow-iw)/2:(oh-ih)/2",
                      "-pix_fmt", "rgb24", "-f", "rawvideo", "-"]
    result = subprocess.run(arguments, capture_output=True, timeout=60)
    if result.returncode or not result.stdout:
        raise ValueError(f"Cannot verify proxy content for {path.name}: {result.stderr.decode(errors='replace')[:300]}")
    return result.stdout


def verify_proxy_origin(event: Path, source: Path, proxy: Path, source_info: dict) -> None:
    manifest = event / "Data" / "smaller_video_manifest.json"
    record = json.loads(manifest.read_text()).get("videos", {}).get(str(source.relative_to(event)), {}) if manifest.exists() else {}
    original = media_identity(source, record.get("source_identity"))
    smaller = media_identity(proxy, record.get("proxy_identity"))
    if record:
        if (record.get("proxy") != str(proxy.relative_to(event))
            or not same_content(original, record.get("source_identity", {}))
            or not same_content(smaller, record.get("proxy_identity", {}))):
            raise ValueError("The Smaller Videos provenance no longer matches the original and proxy. Rebuild this smaller copy.")
        return
    # Older ECC copies have no provenance manifest. Check content as well as the
    # engine's separate exact frame-rate / one-frame duration compatibility check.
    duration = source_info["duration"] / 254_016_000_000
    for fraction in (0.1, 0.65):
        seconds = duration * fraction
        left, right = _sample(source, seconds), _sample(proxy, seconds)
        if len(left) != 3072 or len(right) != len(left):
            raise ValueError("Proxy frame dimensions could not be verified.")
        error = math.sqrt(sum((a - b) ** 2 for a, b in zip(left, right)) / len(left)) / 255
        if error > 0.08:
            raise ValueError("The smaller video's picture does not match this original.")
    if source_info.get("audio_streams"):
        left, right = array("h", _sample(source, duration * 0.4, True)), array("h", _sample(proxy, duration * 0.4, True))
        count = min(len(left), len(right))
        if count < 200:
            raise ValueError("Proxy audio could not be verified.")
        energy = sum(x * x for x in left[:count])
        # AAC encoder priming can shift a decoded sample window by a few ms.
        # Compare overlapping PCM windows within one 30-fps frame, rather than
        # rejecting the correct proxy over the encoder's padding.
        def normalized_error(lag):
            a = left[max(0, lag):min(count, count + lag)]
            b = right[max(0, -lag):min(count, count - lag)]
            return sum((x-y)**2 for x, y in zip(a, b)) / max(1, sum(x*x for x in a))
        difference = min(normalized_error(lag) for lag in range(-240, 241)) if energy > count * 25 else 0
        if (energy > count * 25 and difference > 0.25) or (energy <= count * 25 and sum(x*x for x in right[:count]) > count * 100):
            raise ValueError("The smaller video's audio does not match this original.")
    if not same_content(original, media_identity(source)) or not same_content(smaller, media_identity(proxy)):
        raise ValueError("Media changed while checking proxy correspondence.")
    record_proxy(event, source, proxy, original, smaller)
