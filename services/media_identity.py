"""Portable media identity and atomic JSON writes for generated event records."""

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def media_identity(path: Path, cached: dict[str, Any] | None = None) -> dict[str, Any]:
    stat = path.stat()
    if cached and (cached.get("size"), cached.get("mtime_ns")) == (stat.st_size, stat.st_mtime_ns):
        return cached
    digest = hashlib.sha256(str(stat.st_size).encode())
    with path.open("rb") as stream:
        digest.update(stream.read(1024 * 1024))
        if stat.st_size > 1024 * 1024:
            stream.seek(max(1024 * 1024, stat.st_size - 1024 * 1024))
            digest.update(stream.read(1024 * 1024))
    after = path.stat()
    if (stat.st_size, stat.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise RuntimeError(f"Media changed while reading: {path.name}")
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "fingerprint": digest.hexdigest()}


def same_content(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (left.get("size"), left.get("fingerprint")) == (right.get("size"), right.get("fingerprint"))


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".ecc-", dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
            stream.close()
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
