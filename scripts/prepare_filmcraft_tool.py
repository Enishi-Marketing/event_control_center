#!/usr/bin/env python3
"""Prepare the pinned, official FilmCraft CLI for source runs and packaging."""

import argparse
import hashlib
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path


VERSION = "0.17.1"
ARCHIVE = f"filmcraft-cli-{VERSION}-macos-universal.zip"
SHA256 = "ca0749fecd44c51caee419d90938d24ce322340d7af1d1660605166f1ecd2755"
ROOT = Path(__file__).resolve().parents[1]


def prepare(archive: Path | None = None) -> Path:
    destination = ROOT / "build" / "filmcraft-tool"
    executable = destination / "filmcraft-cli"
    if (executable.is_file() and (destination / "VERSION").is_file()
        and (destination / "OFL-noto-sans-cjk-sc.txt").is_file()
        and (destination / "VERSION").read_text().strip() == VERSION):
        return executable
    with tempfile.TemporaryDirectory(prefix="ecc-filmcraft-tool-") as directory:
        directory = Path(directory)
        if archive is None:
            archive = directory / ARCHIVE
            urllib.request.urlretrieve(f"https://github.com/storytold/filmcraft/releases/download/v{VERSION}/{ARCHIVE}", archive)
        with archive.open("rb") as stream:
            checksum = hashlib.sha256()
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                checksum.update(block)
            digest = checksum.hexdigest()
        if digest != SHA256:
            raise RuntimeError("FilmCraft tool archive checksum does not match the pinned release.")
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as package:
            prefix = f"filmcraft-cli-{VERSION}-macos-universal/"
            for entry in package.namelist():
                name = entry.removeprefix(prefix)
                if "/" in name or not (name in {"filmcraft-cli", "LICENSE-APACHE", "LICENSE-MIT", "NOTICE"} or name.startswith("OFL-")):
                    continue
                with package.open(entry) as source, (destination / name).open("wb") as target:
                    shutil.copyfileobj(source, target)
        executable.chmod(0o755)
        (destination / "VERSION").write_text(VERSION + "\n")
    return executable


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, help="An already downloaded official ZIP (its checksum is still verified).")
    print(prepare(parser.parse_args().archive))
