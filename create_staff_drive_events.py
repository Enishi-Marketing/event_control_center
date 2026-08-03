#!/usr/bin/env python3
import argparse
from pathlib import Path
import re

SUBFOLDERS = ["Forms", "Reports", "Planning"]

EVENT_FOLDER_PATTERN = re.compile(r"^\d{4}\.\d{2}\.\d{2} - .+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create staff-drive folders for every matching event folder."
    )
    parser.add_argument("source_root", type=Path, help="Event-year folder to copy from")
    parser.add_argument("dest_root", type=Path, help="Archive folder to create in")
    return parser.parse_args()


def main(source_root: Path, dest_root: Path) -> None:
    source_root = source_root.expanduser()
    dest_root = dest_root.expanduser()
    if not source_root.exists():
        raise FileNotFoundError(f"Source folder not found:\n{source_root}")

    dest_root.mkdir(parents=True, exist_ok=True)

    created = 0
    skipped = 0

    for item in source_root.iterdir():
        if not item.is_dir():
            continue

        if not EVENT_FOLDER_PATTERN.match(item.name):
            continue

        dest_event_folder = dest_root / item.name

        if dest_event_folder.exists():
            skipped += 1
            print(f"Skipped existing: {item.name}")
        else:
            dest_event_folder.mkdir(parents=True)
            created += 1
            print(f"Created: {item.name}")

        for subfolder in SUBFOLDERS:
            (dest_event_folder / subfolder).mkdir(exist_ok=True)

    print("\nDone.")
    print(f"Created event folders: {created}")
    print(f"Skipped existing event folders: {skipped}")


if __name__ == "__main__":
    args = parse_args()
    main(args.source_root, args.dest_root)
