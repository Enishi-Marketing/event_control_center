"""Add event RAW originals to a native LightCraft library."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from services.importer import PHOTO_EXTENSIONS, is_system_file


RAW_EXTENSIONS = PHOTO_EXTENSIONS - {
    ".jpg", ".jpeg", ".heic", ".heif", ".png", ".webp", ".tif", ".tiff",
    ".gif", ".bmp", ".avif", ".psd", ".psb",
}


def _find_cli() -> Path:
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    override = os.environ.get("ECC_LIGHTCRAFT_CLI")
    candidates = [Path(override)] if override else [
        root / "lightcraft" / "lightcraft-cli",
        root / "build" / "lightcraft-tool" / "lightcraft-cli",
    ]
    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError("LightCraft CLI is missing. For source runs, run scripts/prepare_lightcraft_tool.py.")


def _import_raws(cli: Path, library: Path, originals: list[Path]) -> list[str]:
    command = {"command": "library.import", "params": {
        "paths": [str(path) for path in originals], "mode": "add", "onDeleted": "skip",
    }}
    result = subprocess.run(
        [str(cli), "run", "--library", str(library), "--script", "-"],
        input=json.dumps(command) + "\n", capture_output=True, text=True, timeout=1800,
        env={**os.environ, "LIGHTCRAFT_NO_PREFS": "1"},
    )
    row = json.loads(result.stdout) if result.stdout.strip() else {}
    if result.returncode or not row.get("ok"):
        raise RuntimeError(row.get("error") or result.stderr.strip() or "LightCraft import failed.")
    report = row["result"]
    if not (library / "catalog.snap").is_file():
        raise RuntimeError("LightCraft did not save the library.")
    return [f"{Path(path).name}: {reason}" for path, reason in report.get("failed", [])]


def prepare_lightcraft(event: Path, catalog_folder: Path, name: str) -> tuple[Path | None, list[str]]:
    """Create the library on first import or let LightCraft add to it under its own lock."""
    originals = sorted(
        path.absolute() for path in (event / "Raw" / "Photos").rglob("*")
        if path.suffix.casefold() in RAW_EXTENSIONS and not is_system_file(path) and path.is_file()
    )
    if not originals:
        return None, []
    cli = _find_cli()
    library = catalog_folder / f"{name} LightCraft Library"
    snapshot = library / "catalog.snap"
    if library.exists():
        if not snapshot.is_file():
            raise RuntimeError(f"Existing folder has no LightCraft catalog: {library.name}")
        return snapshot, _import_raws(cli, library, originals)

    catalog_folder.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ecc-lightcraft-", dir=catalog_folder) as temporary:
        draft = Path(temporary) / library.name
        failures = _import_raws(cli, draft, originals)
        if len(failures) == len(originals):
            return None, failures
        # A completed library is nonempty, so rename cannot replace a library
        # another process has published since the existence check.
        draft.rename(library)
    return snapshot, failures
