"""FilmCraft's released headless command engine; never connects to the live app."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


FILMCRAFT_VERSION = "0.17.1"


def find_filmcraft_cli() -> Path:
    override = os.environ.get("ECC_FILMCRAFT_CLI")
    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    candidates = [
        Path(override) if override else None,
        root / "filmcraft" / "filmcraft-cli",
        root / "build" / "filmcraft-tool" / "filmcraft-cli",
        Path(shutil.which("filmcraft-cli")) if shutil.which("filmcraft-cli") else None,
    ]
    for path in candidates:
        if path and path.is_file() and os.access(path, os.X_OK):
            return path
    raise RuntimeError("FilmCraft preparation needs its bundled command engine. For source runs, run .venv/bin/python scripts/prepare_filmcraft_tool.py.")


class FilmcraftClient:
    def __init__(self, executable: Path | None = None) -> None:
        self.executable = executable or find_filmcraft_cli()
        version = subprocess.run([str(self.executable), "--version"], capture_output=True, text=True, timeout=10)
        if version.returncode or FILMCRAFT_VERSION not in version.stdout.split():
            raise RuntimeError(f"ECC requires its validated FilmCraft {FILMCRAFT_VERSION} command engine. Run scripts/prepare_filmcraft_tool.py.")

    def _call(self, arguments: list[str], data_dir: Path, text: str | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(self.executable), "--data-dir", str(data_dir), *arguments],
            input=text, capture_output=True, text=True, timeout=600,
            env={key: value for key, value in os.environ.items() if not key.startswith("FILMCRAFT_CONTROL_")},
        )

    def run(self, project: Path, steps: list[dict[str, Any]], data_dir: Path) -> list[dict[str, Any]]:
        if not steps:
            return []
        result = self._call(
            ["--project", str(project), "--save", "--keep-going", "run", "-"], data_dir,
            "\n".join(json.dumps(step) for step in steps) + "\n",
        )
        rows = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        if len(rows) != len(steps):
            raise RuntimeError(result.stderr.strip() or "FilmCraft did not finish the requested commands.")
        return rows

    def probe(self, path: Path, data_dir: Path) -> dict[str, Any]:
        result = self._call(["probe", str(path)], data_dir)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or f"FilmCraft cannot read {path.name}.")
        return json.loads(result.stdout)

    def validate(self, project: Path, data_dir: Path) -> None:
        result = self._call(["--project", str(project), "inspect", "project"], data_dir)
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "FilmCraft refused the generated project.")
        json.loads(result.stdout)
