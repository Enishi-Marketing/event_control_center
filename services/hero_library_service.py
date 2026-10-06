"""Local Hero catalog and selective, bandwidth-aware media publishing.

Discovery reads directory entries and Finder tag metadata only. Image bytes are
read only for a deliberately selected staging, preview, or publish operation.
"""

from __future__ import annotations

import hashlib
import ctypes
import json
import os
import plistlib
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from collections import defaultdict
from contextlib import closing
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

from config.config import AppConfig
from services.keyword_service import KeywordVocabulary
from services.metadata_service import MetadataService


STATES = {"UNREVIEWED", "NEEDS_EDIT", "IN_LIGHTROOM", "APPROVED_AS_IS", "READY_TO_PUBLISH", "PUBLISHED"}
CATEGORIES = {"Learning", "Community", "Sports", "Arts", "Campus", "Events", "Portrait"}
BROWSE_GROUPS = {"Students", "Teachers & Staff", "Campus", "Community"}
SECTION_FOLDERS = {"ELC": "Early Years", "PYP": "Primary School", "MYP": "Middle School", "DP": "High School"}
GRADES = {"All", "Staff", "Parents", "Foundation", "Preschool", "PreK", "Kindergarten", *(f"Grade {n}" for n in range(1, 13))}
SECTIONS = {"ELC", "PYP", "MYP", "DP"}
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic", ".cr2", ".cr3", ".nef", ".arw", ".dng"}
PUBLISHABLE_SUFFIXES = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic"}
ASSET_RE = re.compile(r"^(EIS-H\d{6})(?:\b|[_ .-])", re.IGNORECASE)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False)


def _safe_name(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", value).strip(" .") or "Untitled"


def _sidecar(path: Path) -> Path:
    return path.with_suffix(".xmp")


def _natural_name_key(value: str) -> tuple:
    stem = Path(value).stem
    return (tuple((0, int(part)) if part.isdigit() else (1, part.casefold())
                  for part in re.split(r"(\d+)", stem)), Path(value).suffix.casefold())


class HeroLibraryService:
    def __init__(self, catalog_path: Path | None = None) -> None:
        self.catalog_path = catalog_path or AppConfig.HERO_CATALOG_PATH
        self.catalog_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata = MetadataService()
        with closing(self._connect()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id TEXT UNIQUE, source_path TEXT NOT NULL UNIQUE,
                source_size INTEGER, event_photo_number INTEGER,
                source_kind TEXT NOT NULL DEFAULT 'FINDER_TAG',
                original_filename TEXT NOT NULL, event_folder TEXT, event_name TEXT,
                event_date TEXT, school_year TEXT, event_id TEXT NOT NULL DEFAULT '',
                event_description TEXT NOT NULL DEFAULT '',
                event_grades TEXT NOT NULL DEFAULT '[]',
                event_sections TEXT NOT NULL DEFAULT '[]',
                event_keywords TEXT NOT NULL DEFAULT '[]', grades TEXT NOT NULL DEFAULT '[]',
                sections TEXT NOT NULL DEFAULT '[]', category TEXT NOT NULL DEFAULT '',
                browse_group TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '', setting TEXT NOT NULL DEFAULT '',
                extra_keywords TEXT NOT NULL DEFAULT '[]', featured INTEGER NOT NULL DEFAULT 0,
                edit_state TEXT NOT NULL DEFAULT 'UNREVIEWED', export_path TEXT,
                sha256 TEXT, capture_date TEXT, width INTEGER, height INTEGER,
                orientation TEXT, file_type TEXT, master_path TEXT, web_path TEXT,
                needs_edit_path TEXT, thumbnail_path TEXT, matched_library_path TEXT,
                removed_at TEXT, removed_manifest TEXT NOT NULL DEFAULT '[]',
                discovered_at TEXT NOT NULL, updated_at TEXT NOT NULL, published_at TEXT
            )""")
            db.execute("CREATE INDEX IF NOT EXISTS hero_hash ON assets(sha256)")
            columns = {row[1] for row in db.execute("PRAGMA table_info(assets)")}
            additions = {
                "event_id": "TEXT NOT NULL DEFAULT ''",
                "event_description": "TEXT NOT NULL DEFAULT ''",
                "event_sections": "TEXT NOT NULL DEFAULT '[]'",
                "needs_edit_path": "TEXT",
                "thumbnail_path": "TEXT",
                "matched_library_path": "TEXT",
                "removed_at": "TEXT",
                "removed_manifest": "TEXT NOT NULL DEFAULT '[]'",
                "browse_group": "TEXT NOT NULL DEFAULT ''",
                "source_kind": "TEXT NOT NULL DEFAULT 'FINDER_TAG'",
                "source_size": "INTEGER",
                "event_photo_number": "INTEGER",
            }
            for name, sql_type in additions.items():
                if name not in columns:
                    db.execute(f"ALTER TABLE assets ADD COLUMN {name} {sql_type}")
            self._assign_event_photo_numbers(db)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.catalog_path)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _event_group(row: sqlite3.Row | dict) -> tuple[str, ...]:
        if row["event_id"]:
            return ("id", str(row["event_id"]))
        if row["event_folder"]:
            return ("folder", str(row["event_folder"]))
        return ("fallback", str(row["event_name"] or "").casefold(),
                str(row["event_date"] or ""), str(row["school_year"] or ""),
                str(Path(row["source_path"]).parent))

    @classmethod
    def _assign_event_photo_numbers(cls, db: sqlite3.Connection) -> None:
        """Give each catalogued event photo a stable, human-readable position."""
        rows = db.execute("""SELECT id, event_id, event_folder, event_name,
            event_date, school_year, source_path, original_filename,
            event_photo_number FROM assets""").fetchall()
        groups: dict[tuple[str, ...], list[sqlite3.Row]] = defaultdict(list)
        for row in rows:
            groups[cls._event_group(row)].append(row)
        for group in groups.values():
            used = {row["event_photo_number"] for row in group if row["event_photo_number"] is not None}
            next_number = max(used, default=0) + 1
            missing = sorted((row for row in group if row["event_photo_number"] is None),
                             key=lambda row: (_natural_name_key(row["original_filename"]),
                                              row["source_path"].casefold(), row["id"]))
            for row in missing:
                db.execute("UPDATE assets SET event_photo_number=? WHERE id=?", (next_number, row["id"]))
                next_number += 1

    @staticmethod
    def _finder_tags(path: Path) -> list[str]:
        try:
            raw = HeroLibraryService._read_xattr(path, "com.apple.metadata:_kMDItemUserTags")
            tags = plistlib.loads(raw)
            return [str(tag).split("\n", 1)[0] for tag in tags]
        except (OSError, ValueError, TypeError, plistlib.InvalidFileException):
            return []

    @staticmethod
    @lru_cache(maxsize=1)
    def _darwin_getxattr():
        library = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        function = library.getxattr
        function.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                             ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
        function.restype = ctypes.c_ssize_t
        return function

    @staticmethod
    def _read_xattr(path: Path, name: str) -> bytes:
        if hasattr(os, "getxattr"):
            return os.getxattr(path, name)
        if sys.platform != "darwin":
            raise OSError("Finder tags require macOS extended attributes.")
        function = HeroLibraryService._darwin_getxattr()
        path_bytes, name_bytes = os.fsencode(path), name.encode("utf-8")
        size = function(path_bytes, name_bytes, None, 0, 0, 0)
        if size < 0:
            raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()), str(path))
        buffer = ctypes.create_string_buffer(size)
        actual = function(path_bytes, name_bytes, buffer, size, 0, 0)
        if actual < 0:
            raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()), str(path))
        return buffer.raw[:actual]

    @staticmethod
    def _tagged_paths(root: Path):
        """Yield paths without stat, image reads, symlink traversal, or downloads."""
        stack = [root]
        while stack:
            folder = stack.pop()
            try:
                with os.scandir(folder) as entries:
                    for entry in entries:
                        try:
                            if entry.is_dir(follow_symlinks=False):
                                stack.append(Path(entry.path))
                            elif entry.is_file(follow_symlinks=False) and Path(entry.name).suffix.lower() in IMAGE_SUFFIXES:
                                path = Path(entry.path)
                                if "Hero Shot" in HeroLibraryService._finder_tags(path):
                                    yield path
                        except OSError:
                            continue
            except OSError:
                continue

    def _event_metadata(self, path: Path, root: Path) -> tuple[str, dict]:
        folder = path.parent
        fallback: tuple[str, dict] | None = None
        while folder == root or root in folder.parents:
            for data_folder in ("Data", "data"):
                metadata_file = folder / data_folder / "metadata.json"
                if metadata_file.is_file():
                    try:
                        return str(folder), self.metadata.read_metadata(metadata_file)
                    except (OSError, ValueError, json.JSONDecodeError):
                        pass
            if fallback is None:
                match = re.fullmatch(r"(\d{4})[.-](\d{2})[.-](\d{2}) - (.+)", folder.name)
                if match:
                    school_year = ""
                    year_match = re.fullmatch(r"(\d{4})-(\d{2})", folder.parent.name)
                    if year_match:
                        start = int(year_match.group(1))
                        end = start // 100 * 100 + int(year_match.group(2))
                        if end <= start:
                            end += 100
                        school_year = f"{start}-{end}"
                    fallback = (str(folder), {
                        "event_name": match.group(4).strip(),
                        "date": f"{match.group(1)}.{match.group(2)}.{match.group(3)}",
                        "school_year": school_year,
                        "grades": [], "keywords": [],
                    })
            if folder == root:
                break
            folder = folder.parent
        return fallback or ("", {})

    def scan(self, roots: list[str] | None = None) -> dict:
        configured = roots if roots is not None else AppConfig.HERO_SOURCE_ROOTS
        found = 0
        added = 0
        errors: list[str] = []
        library_index = self._existing_library_index()
        with closing(self._connect()) as db, db:
            for raw_root in configured:
                root = Path(raw_root).expanduser()
                if not root.is_dir():
                    errors.append(f"Source folder unavailable: {root}")
                    continue
                for path in self._tagged_paths(root):
                    found += 1
                    try:
                        source_size = path.stat().st_size
                        library_match = library_index.get((path.name.casefold(), source_size))
                    except OSError:
                        source_size = None
                        library_match = None
                    event_folder, event = self._event_metadata(path, root)
                    timestamp = _now()
                    event_grades = event.get("grades", [])
                    if not isinstance(event_grades, list):
                        event_grades = []
                    event_grades = [str(value).strip() for value in event_grades if str(value).strip()]
                    raw_sections = event.get("sections", [])
                    if not isinstance(raw_sections, list):
                        raw_sections = []
                    event_sections = sorted({value.upper() for value in [*event_grades, *map(str, raw_sections)]
                                             if value.upper() in SECTIONS})
                    event_keywords = KeywordVocabulary().canonicalize(event.get("keywords", []))
                    cursor = db.execute("""INSERT OR IGNORE INTO assets
                        (source_path, source_size, original_filename, event_folder, event_name,
                         event_date, school_year, event_id, event_description,
                         event_grades, event_sections, event_keywords,
                         file_type, matched_library_path, discovered_at, updated_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (str(path), source_size, path.name, event_folder, str(event.get("event_name", "")),
                         str(event.get("date", "")), str(event.get("school_year", "")),
                         str(event.get("event_id") or ""), str(event.get("description") or ""),
                         _json(event_grades), _json(event_sections), _json(event_keywords),
                         path.suffix.lower().lstrip("."), str(library_match) if library_match else None,
                         timestamp, timestamp))
                    if cursor.rowcount:
                        asset_id = f"EIS-H{cursor.lastrowid:06d}"
                        db.execute("UPDATE assets SET asset_id=? WHERE id=?", (asset_id, cursor.lastrowid))
                        added += 1
                    elif event_folder:
                        db.execute("""UPDATE assets SET event_folder=?, event_name=?, event_date=?,
                            school_year=?, event_id=?, event_description=?, event_grades=?,
                            event_sections=?, event_keywords=?, source_size=?, matched_library_path=?, updated_at=?
                            WHERE source_path=?""",
                            (event_folder, str(event.get("event_name", "")), str(event.get("date", "")),
                             str(event.get("school_year", "")), str(event.get("event_id") or ""),
                             str(event.get("description") or ""), _json(event_grades),
                             _json(event_sections), _json(event_keywords), source_size,
                             str(library_match) if library_match else None, timestamp, str(path)))
            self._assign_event_photo_numbers(db)
        return {"found": found, "added": added, "errors": errors, "assets": self.list_assets()}

    @staticmethod
    def _record(row: sqlite3.Row) -> dict:
        record = dict(row)
        for key in ("event_grades", "event_sections", "event_keywords", "grades", "sections", "extra_keywords", "removed_manifest"):
            record[key] = json.loads(record[key])
        record["featured"] = bool(record["featured"])
        return record

    @staticmethod
    def _published_stem(asset: dict) -> str:
        number = asset.get("event_photo_number")
        if not isinstance(number, int) or number < 1:
            raise ValueError(f"{asset['asset_id']} has no event photo number.")
        title = str(asset.get("event_name") or "").strip() or "General School Life"
        title = title[:110].rstrip()
        date = str(asset.get("event_date") or asset.get("school_year") or "").strip()
        return _safe_name(f"{title} - {date} - {number:03d}" if date else f"{title} - {number:03d}")

    def list_assets(self) -> list[dict]:
        with closing(self._connect()) as db, db:
            return [self._record(row) for row in db.execute("SELECT * FROM assets ORDER BY id DESC")]

    @staticmethod
    def _browse_group(asset: dict) -> str:
        """Choose one shallow browse location; keep other facets in metadata."""
        chosen = asset.get("browse_group") or ""
        if chosen in BROWSE_GROUPS:
            return chosen
        categories = {str(asset.get("category") or "").casefold()}
        tags = {str(value).casefold() for value in [
            *asset.get("grades", []), *asset.get("event_grades", []),
            *asset.get("event_keywords", []), *asset.get("extra_keywords", []),
        ]}
        if "Campus".casefold() in categories:
            return "Campus"
        if "staff" in tags or "teachers" in tags or "teacher" in tags:
            return "Teachers & Staff"
        if categories & {"community", "events"} or "parents" in tags:
            return "Community"
        return "Students"

    @staticmethod
    def _browse_path(asset: dict) -> Path:
        group = HeroLibraryService._browse_group(asset)
        if group != "Students":
            return Path(group)
        sections = {str(value).upper() for value in (asset.get("sections") or asset.get("event_sections") or [])}
        sections &= SECTIONS
        if len(sections) > 1:
            section = "Mixed Sections"
        elif sections:
            section = SECTION_FOLDERS[next(iter(sections))]
        else:
            section = "Section To Review"
        return Path("Students") / section

    def _needs_edit_destination(self, asset: dict) -> Path:
        filename = f"{asset['asset_id']} - {_safe_name(Path(asset['original_filename']).stem)}{Path(asset['original_filename']).suffix}"
        return AppConfig.HERO_WORKSPACE_ROOT / "Needs Edit" / "Queued" / filename

    @staticmethod
    def workspace_paths() -> dict[str, str]:
        root = AppConfig.HERO_WORKSPACE_ROOT
        return {
            "catalog_path": str(root / "Hero Library Catalog" / "Hero Library Catalog.lrcat"),
            "queue_path": str(root / "Needs Edit" / "Queued"),
            "incoming_path": str(root / "Needs Edit" / "Incoming"),
            "working_path": str(root / "Needs Edit" / "Working Lightroom Edits"),
            "export_path": str(root / "Needs Edit" / "Exports"),
        }

    def ensure_catalog(self) -> dict[str, str]:
        paths = self.workspace_paths()
        catalog = Path(paths["catalog_path"])
        for key in ("queue_path", "incoming_path", "working_path", "export_path"):
            Path(paths[key]).mkdir(parents=True, exist_ok=True)
        legacy_exports = Path(paths["working_path"]) / "Exports"
        if legacy_exports.is_dir():
            for old_file in legacy_exports.rglob("*"):
                if not old_file.is_file():
                    continue
                new_file = Path(paths["export_path"]) / old_file.relative_to(legacy_exports)
                if new_file.exists():
                    raise FileExistsError(f"Lightroom export already exists at {new_file}; move the old file manually.")
                new_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(old_file), str(new_file))
            for old_dir in sorted((item for item in legacy_exports.rglob("*") if item.is_dir()),
                                  key=lambda item: len(item.parts), reverse=True):
                old_dir.rmdir()
            legacy_exports.rmdir()
        if not catalog.is_file():
            template = AppConfig.LIGHTROOM_TEMPLATE_DIR / "Blank_Lightroom.lrcat"
            if not template.is_file():
                raise FileNotFoundError(f"Included Lightroom catalog missing: {template}")
            catalog.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template, catalog)
        return paths

    @staticmethod
    def _existing_library_index() -> dict[tuple[str, int], Path]:
        """Index only the smaller published library by filename and file size."""
        root = AppConfig.HERO_PUBLISH_ROOT
        matches: dict[tuple[str, int], Path] = {}
        manifest = root / "Hero_Catalog.json"
        if manifest.is_file():
            try:
                entries = json.loads(manifest.read_text(encoding="utf-8")).get("assets", [])
                for item in entries:
                    original = str(item.get("original_filename") or "")
                    size = item.get("source_size")
                    relative = Path(str(item.get("master") or ""))
                    if not original or not isinstance(size, int) or relative.is_absolute() or ".." in relative.parts:
                        continue
                    master = root / relative
                    if master.is_file():
                        matches.setdefault((original.casefold(), size), master)
            except (OSError, ValueError, TypeError, AttributeError):
                pass
        libraries = [root]
        legacy = root.parent / "Photo_Library"
        if legacy != root:
            libraries.append(legacy)
        for library in libraries:
            if not library.is_dir():
                continue
            for folder, directories, files in os.walk(library):
                directories[:] = [name for name in directories if name not in {"Needs Edit", "_Removed"}]
                for name in files:
                    path = Path(folder) / name
                    if path.suffix.lower() not in IMAGE_SUFFIXES:
                        continue
                    try:
                        size = path.stat().st_size
                    except OSError:
                        continue
                    normalized = re.sub(r"^EIS-H\d{6}\s*-\s*", "", name, flags=re.IGNORECASE)
                    matches.setdefault((normalized.casefold(), size), path)
        return matches

    @staticmethod
    def _local_copy(asset: dict) -> Path | None:
        root = AppConfig.HERO_WORKSPACE_ROOT / "Needs Edit"
        name = f"{asset['asset_id']} - {_safe_name(Path(asset['original_filename']).stem)}{Path(asset['original_filename']).suffix}"
        for candidate in (root / "Queued" / name, root / "Incoming" / name,
                          root / "Working Lightroom Edits" / name):
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _make_thumbnail(source: Path, asset_id: str) -> Path | None:
        destination = AppConfig.HERO_WORKSPACE_ROOT / "Thumbnails" / f"{asset_id}.jpg"
        if destination.is_file():
            return destination
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with Image.open(source) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail((320, 320), Image.Resampling.LANCZOS)
                image.convert("RGB").save(destination, "JPEG", quality=75)
            return destination
        except (OSError, ValueError):
            destination.unlink(missing_ok=True)
            return None

    def refresh(self, limit: int | None = None) -> dict:
        """Discover by metadata, then stage only new tagged originals locally."""
        if limit is not None:
            limit = max(1, int(limit))
        scan = self.scan()
        synced = 0
        skipped = 0
        errors = list(scan["errors"])
        paths = self.ensure_catalog()
        workspace = AppConfig.HERO_WORKSPACE_ROOT
        with closing(self._connect()) as db, db:
            rows = db.execute("""SELECT * FROM assets WHERE removed_at IS NULL
                AND edit_state != 'PUBLISHED' ORDER BY id""").fetchall()
            for row in rows:
                asset = self._record(row)
                if asset["matched_library_path"]:
                    skipped += 1
                    continue
                source = Path(asset["source_path"])
                try:
                    if asset["source_kind"] != "STAFF_DRIVE" and "Hero Shot" not in self._finder_tags(source):
                        continue
                except OSError as exc:
                    errors.append(f"{asset['asset_id']}: {exc}")
                    continue
                destination = self._needs_edit_destination(asset)
                try:
                    local_copy = self._local_copy(asset)
                    if local_copy:
                        thumbnail = self._make_thumbnail(local_copy, asset["asset_id"])
                        db.execute("""UPDATE assets SET needs_edit_path=?, thumbnail_path=?,
                            edit_state=CASE WHEN edit_state='UNREVIEWED' THEN 'NEEDS_EDIT' ELSE edit_state END,
                            updated_at=? WHERE asset_id=?""",
                            (str(local_copy), str(thumbnail) if thumbnail else None, _now(), asset["asset_id"]))
                        continue
                    size = source.stat().st_size
                    if shutil.disk_usage(workspace).free < size * 2 + 768 * 1024 * 1024:
                        errors.append("Stopped staging because local disk space is low. Already staged photos remain in Needs Edit.")
                        break
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    old_path = Path(asset["needs_edit_path"]) if asset["needs_edit_path"] else None
                    if old_path and old_path.is_file() and old_path.is_relative_to(AppConfig.HERO_PUBLISH_ROOT / "Needs Edit") and old_path.name.startswith(asset["asset_id"]):
                        shutil.move(str(old_path), str(destination))
                    elif not destination.is_file() or destination.stat().st_size != size:
                        fd, temp_name = tempfile.mkstemp(prefix=".ecc-copy-", dir=destination.parent)
                        os.close(fd)
                        try:
                            shutil.copy2(source, temp_name)
                            os.replace(temp_name, destination)
                        finally:
                            Path(temp_name).unlink(missing_ok=True)
                    thumbnail = self._make_thumbnail(destination, asset["asset_id"])
                    db.execute("""UPDATE assets SET needs_edit_path=?, thumbnail_path=?,
                        edit_state=CASE WHEN edit_state='UNREVIEWED' THEN 'NEEDS_EDIT' ELSE edit_state END,
                        updated_at=? WHERE asset_id=?""",
                        (str(destination), str(thumbnail) if thumbnail else None, _now(), asset["asset_id"]))
                    db.commit()
                    synced += 1
                    if limit is not None and synced >= limit:
                        break
                except (OSError, ValueError) as exc:
                    errors.append(f"{asset['asset_id']}: {exc}")
            pending = db.execute("""SELECT COUNT(*) FROM assets WHERE removed_at IS NULL
                AND needs_edit_path IS NULL AND matched_library_path IS NULL
                AND edit_state != 'PUBLISHED'""").fetchone()[0]
        return {"found": scan["found"], "added": scan["added"], "synced": synced,
                "skipped": skipped, "pending": pending, "errors": errors,
                "workspace": paths, "assets": self.list_assets()}

    @staticmethod
    def _managed_files(asset: dict) -> list[Path]:
        files: list[Path] = []
        for key in ("needs_edit_path", "thumbnail_path", "export_path", "master_path", "web_path"):
            if asset.get(key):
                path = Path(asset[key])
                files.append(path)
                files.extend((_sidecar(path), path.with_suffix(path.suffix + ".xmp")))
        if asset.get("asset_id"):
            files.append(AppConfig.HERO_PUBLISH_ROOT / "_Metadata" / f"{asset['asset_id']}.xmp")
        local = HeroLibraryService._local_copy(asset)
        if local:
            files.append(local)
        return list(dict.fromkeys(files))

    def remove(self, asset_ids: list[str]) -> list[dict]:
        if not asset_ids:
            raise ValueError("Select at least one Hero asset.")
        with closing(self._connect()) as db, db:
            for asset_id in asset_ids:
                row = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
                if row is None:
                    raise ValueError(f"Unknown asset: {asset_id}")
                asset = self._record(row)
                if asset["removed_at"]:
                    continue
                moved: list[dict[str, str]] = []
                try:
                    for path in self._managed_files(asset):
                        if not path.is_file():
                            continue
                        root = next((candidate for candidate in
                                     (AppConfig.HERO_WORKSPACE_ROOT, AppConfig.HERO_PUBLISH_ROOT)
                                     if path.is_relative_to(candidate)), None)
                        if root is None or (root == AppConfig.HERO_WORKSPACE_ROOT and not path.name.startswith(asset_id)):
                            raise ValueError(f"Refusing to move an unmanaged file: {path}")
                        relative = path.relative_to(root)
                        allowed = {"Needs Edit", "Thumbnails"} if root == AppConfig.HERO_WORKSPACE_ROOT else {"Events", "General School Life", "MASTER", "WEB", "_Metadata"}
                        if relative.parts[0] not in allowed:
                            raise ValueError(f"Refusing to move an unmanaged file: {path}")
                        destination = root / "_Removed" / asset_id / relative
                        if destination.exists():
                            raise ValueError(f"Removed file already exists: {destination}")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(path), str(destination))
                        moved.append({"original": str(path), "removed": str(destination)})
                    db.execute("UPDATE assets SET removed_at=?, removed_manifest=?, updated_at=? WHERE asset_id=?",
                               (_now(), _json(moved), _now(), asset_id))
                    db.commit()
                except Exception:
                    for item in reversed(moved):
                        shutil.move(item["removed"], item["original"])
                    raise
        self.write_manifest()
        return self.list_assets()

    def rename_published(self, dry_run: bool = False) -> dict:
        """Rename catalog-owned MASTER/WEB pairs without changing photo bytes."""
        root = AppConfig.HERO_PUBLISH_ROOT
        if root.name == "Photo_Library" or not root.is_dir():
            raise ValueError("Choose the Hero Shot Library Drive destination first.")
        with closing(self._connect()) as db, db:
            self._assign_event_photo_numbers(db)
            rows = db.execute("""SELECT * FROM assets WHERE edit_state='PUBLISHED'
                AND removed_at IS NULL ORDER BY id""").fetchall()
            plans: list[dict] = []
            reserved: set[str] = set()
            for row in rows:
                asset = self._record(row)
                if not asset["master_path"] or not asset["web_path"]:
                    raise ValueError(f"{asset['asset_id']} is missing a published file path.")
                old_master, old_web = Path(asset["master_path"]), Path(asset["web_path"])
                if not old_master.is_relative_to(root) or not old_web.is_relative_to(root):
                    raise ValueError(f"{asset['asset_id']} has a published file outside the Hero Library.")
                if not old_master.is_file() or not old_web.is_file():
                    raise FileNotFoundError(f"{asset['asset_id']} is missing a MASTER or WEB file.")
                stem = self._published_stem(asset)

                def targets(name: str) -> tuple[Path, Path]:
                    return (old_master.with_name(name + old_master.suffix),
                            old_web.with_name(name + old_web.suffix))

                new_master, new_web = targets(stem)
                if any((new != old and (new.exists() or str(new).casefold() in reserved))
                       for old, new in ((old_master, new_master), (old_web, new_web))):
                    new_master, new_web = targets(f"{stem} - {asset['asset_id']}")
                moves = [(old_master, new_master), (old_web, new_web)]
                for old, new in tuple(moves):
                    for sidecar in (_sidecar(old), old.with_suffix(old.suffix + ".xmp")):
                        if sidecar.is_file():
                            sidecar_name = _sidecar(new) if sidecar == _sidecar(old) else new.with_suffix(new.suffix + ".xmp")
                            moves.append((sidecar, sidecar_name))
                if all(old == new for old, new in moves):
                    continue
                for old, new in moves:
                    if old == new:
                        continue
                    key = str(new).casefold()
                    if key in reserved or new.exists():
                        raise FileExistsError(f"Target filename already exists: {new}")
                    reserved.add(key)
                plans.append({"asset_id": asset["asset_id"], "master": str(new_master),
                              "web": str(new_web), "moves": [(str(old), str(new)) for old, new in moves if old != new]})

            if dry_run:
                return {"planned": len(plans), "changes": plans}
            if not plans:
                return {"renamed": 0, "errors": [], "assets": self.list_assets()}

            journal_dir = AppConfig.HERO_WORKSPACE_ROOT / "Metadata Backups" / "Hero Filename Migrations"
            journal_dir.mkdir(parents=True, exist_ok=True)
            journal = journal_dir / f"hero-filenames-{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.json"
            journal.write_text(json.dumps({"schema_version": 1, "changes": plans}, indent=2) + "\n", encoding="utf-8")
            renamed = 0
            errors: list[str] = []
            for plan in plans:
                moved: list[tuple[str, str]] = []
                try:
                    for old, new in plan["moves"]:
                        if Path(new).exists():
                            raise FileExistsError(f"Target filename already exists: {new}")
                        shutil.move(old, new)
                        moved.append((old, new))
                    db.execute("UPDATE assets SET master_path=?, web_path=?, updated_at=? WHERE asset_id=?",
                               (plan["master"], plan["web"], _now(), plan["asset_id"]))
                    db.commit()
                    renamed += 1
                except Exception as exc:
                    db.rollback()
                    for old, new in reversed(moved):
                        shutil.move(new, old)
                    errors.append(f"{plan['asset_id']}: {exc}")
                    break
        self.write_manifest()
        return {"renamed": renamed, "errors": errors, "journal_path": str(journal),
                "assets": self.list_assets()}

    def restore(self, asset_ids: list[str]) -> list[dict]:
        if not asset_ids:
            raise ValueError("Select at least one removed Hero asset.")
        with closing(self._connect()) as db, db:
            for asset_id in asset_ids:
                row = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
                if row is None:
                    raise ValueError(f"Unknown asset: {asset_id}")
                asset = self._record(row)
                if not asset["removed_at"]:
                    continue
                restored: list[dict[str, str]] = []
                try:
                    for item in asset["removed_manifest"]:
                        original, removed = Path(item["original"]), Path(item["removed"])
                        if original.exists():
                            raise ValueError(f"Cannot restore over an existing file: {original}")
                        if removed.is_file():
                            original.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(removed), str(original))
                            restored.append(item)
                    db.execute("UPDATE assets SET removed_at=NULL, removed_manifest='[]', updated_at=? WHERE asset_id=?",
                               (_now(), asset_id))
                    db.commit()
                except Exception:
                    for item in reversed(restored):
                        shutil.move(item["original"], item["removed"])
                    raise
        self.write_manifest()
        return self.list_assets()

    @staticmethod
    def _list_of(values: object, allowed: set[str] | None = None) -> list[str]:
        if not isinstance(values, list):
            raise ValueError("Expected a list of tags.")
        result = sorted({str(value).strip() for value in values if str(value).strip()}, key=str.casefold)
        if allowed is not None and any(value not in allowed for value in result):
            raise ValueError("One or more values are outside the allowed taxonomy.")
        return result

    def update(self, asset_ids: list[str], changes: dict) -> list[dict]:
        """Save metadata while preserving the original list-returning API."""
        return self.update_with_summary(asset_ids, changes)["assets"]

    def update_with_summary(self, asset_ids: list[str], changes: dict) -> dict:
        """Save metadata, organize Drive additions, and update file metadata."""
        if not asset_ids:
            raise ValueError("Select at least one Hero asset.")
        allowed_fields = {"grades", "sections", "category", "browse_group", "subject", "setting", "extra_keywords", "featured", "edit_state"}
        if not changes or set(changes) - allowed_fields:
            raise ValueError("Unsupported Hero metadata field.")
        values: dict[str, object] = {}
        for key, value in changes.items():
            if key in {"grades", "sections", "extra_keywords"}:
                allowed = GRADES if key == "grades" else SECTIONS if key == "sections" else None
                parsed = self._list_of(value, allowed)
                values[key] = _json(KeywordVocabulary().canonicalize(parsed) if key == "extra_keywords" else parsed)
            elif key == "category":
                if value and value not in CATEGORIES:
                    raise ValueError("Choose a listed category.")
                values[key] = str(value)
            elif key == "browse_group":
                if value not in BROWSE_GROUPS:
                    raise ValueError("Choose a listed Hero Library folder.")
                values[key] = str(value)
            elif key == "edit_state":
                if value not in STATES or value == "PUBLISHED":
                    raise ValueError("Use Publish to mark an asset published.")
                values[key] = str(value)
            elif key == "featured":
                values[key] = int(bool(value))
            else:
                values[key] = str(value).strip()
        # Categories use automatic routing unless the staff member explicitly
        # selected a Library folder in the same edit.
        if "category" in values and "browse_group" not in values:
            values["browse_group"] = ""
        values["updated_at"] = _now()
        with closing(self._connect()) as db, db:
            for asset_id in asset_ids:
                row = db.execute("SELECT edit_state FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
                if row is None:
                    raise ValueError(f"Unknown asset: {asset_id}")
                if row["edit_state"] == "PUBLISHED" and "edit_state" in values:
                    raise ValueError("Published assets cannot be moved back to the inbox.")
                if values.get("edit_state") == "APPROVED_AS_IS":
                    source = db.execute("SELECT source_path FROM assets WHERE asset_id=?", (asset_id,)).fetchone()[0]
                    if Path(source).suffix.lower() not in PUBLISHABLE_SUFFIXES:
                        raise ValueError(f"{asset_id} is a raw file and needs an edited export.")
                if values.get("edit_state") == "READY_TO_PUBLISH":
                    exported = db.execute("SELECT export_path FROM assets WHERE asset_id=?", (asset_id,)).fetchone()[0]
                    if not exported:
                        raise ValueError(f"{asset_id} needs a matched Lightroom export first.")
                assignments = ", ".join(f"{key}=?" for key in values)
                db.execute(f"UPDATE assets SET {assignments} WHERE asset_id=?", (*values.values(), asset_id))
        metadata_fields = {"grades", "sections", "category", "browse_group", "subject", "setting", "extra_keywords"}
        routing_fields = {"grades", "sections", "category", "browse_group", "extra_keywords"}
        summary = {"organized": 0, "metadata_embedded": 0, "errors": []}

        if set(values) & routing_fields:
            result = self.reorganize_published(asset_ids)
            summary["organized"] += result["moved"]
            summary["errors"].extend(result["errors"])
        else:
            self.write_manifest()

        # A finished image adopted directly from Drive is already in the shared
        # library workflow. Once staff assign its metadata, make it a complete
        # MASTER/WEB library item in the matching browse folder.
        if set(values) & metadata_fields:
            drive_result = self.organize_drive_assets(asset_ids)
            summary["organized"] += drive_result["organized"]
            summary["errors"].extend(drive_result["errors"])

        for asset in self.list_assets():
            if asset["asset_id"] not in asset_ids or asset["removed_at"]:
                continue
            if asset["edit_state"] == "PUBLISHED":
                paths = [Path(asset[key]) for key in ("master_path", "web_path") if asset[key]]
            elif asset["source_kind"] == "STAFF_DRIVE":
                paths = [Path(asset["source_path"])]
            else:
                paths = []
            for path in paths:
                if not path.is_file():
                    summary["errors"].append(f"{asset['asset_id']}: file is unavailable for metadata.")
                    continue
                try:
                    if self._embed_metadata(path, asset):
                        summary["metadata_embedded"] += 1
                    else:
                        summary["errors"].append(
                            f"{asset['asset_id']}: this file type needs an edited export before its tags can be embedded."
                        )
                except (OSError, ValueError, subprocess.CalledProcessError) as exc:
                    summary["errors"].append(f"{asset['asset_id']}: could not write photo metadata: {exc}")
        self.write_manifest()
        summary["assets"] = self.list_assets()
        return summary

    def stage(self, asset_ids: list[str]) -> list[dict]:
        if not asset_ids:
            raise ValueError("Select at least one Hero asset.")
        self.ensure_catalog()
        with closing(self._connect()) as db, db:
            for asset_id in asset_ids:
                row = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
                if row is None or row["removed_at"] or row["edit_state"] == "PUBLISHED" or row["matched_library_path"]:
                    raise ValueError(f"Cannot stage {asset_id}.")
                source = Path(row["source_path"])
                if not source.is_file():
                    raise FileNotFoundError(f"Source unavailable: {source}")
                asset = self._record(row)
                local_copy = self._local_copy(asset)
                filename = self._needs_edit_destination(asset).name
                destination = Path(self.workspace_paths()["incoming_path"]) / filename
                destination.parent.mkdir(parents=True, exist_ok=True)
                if local_copy and local_copy.parent.name == "Queued":
                    if destination.exists():
                        raise ValueError(f"Lightroom Incoming already contains {filename}.")
                    shutil.move(str(local_copy), str(destination))
                elif local_copy:
                    destination = local_copy
                elif not destination.is_file():
                    size = source.stat().st_size
                    if shutil.disk_usage(AppConfig.HERO_WORKSPACE_ROOT).free < size * 2 + 768 * 1024 * 1024:
                        raise ValueError("Local disk space is too low to send this photo to Lightroom.")
                    shutil.copy2(source, destination)
                thumbnail = self._make_thumbnail(destination, asset_id)
                db.execute("""UPDATE assets SET needs_edit_path=?, thumbnail_path=?,
                    edit_state='IN_LIGHTROOM', updated_at=? WHERE asset_id=?""",
                    (str(destination), str(thumbnail) if thumbnail else None, _now(), asset_id))
        return self.list_assets()

    def match_exports(self) -> dict:
        export_root = Path(self.workspace_paths()["export_path"])
        matched = 0
        if not export_root.is_dir():
            return {"matched": matched, "assets": self.list_assets()}
        with closing(self._connect()) as db, db:
            for path in export_root.rglob("*"):
                if not path.is_file() or path.suffix.lower() not in PUBLISHABLE_SUFFIXES:
                    continue
                match = ASSET_RE.match(path.name)
                if not match:
                    continue
                row = db.execute("SELECT edit_state, export_path, removed_at, matched_library_path FROM assets WHERE asset_id=?", (match.group(1).upper(),)).fetchone()
                if row and not row["removed_at"] and row["edit_state"] in {"IN_LIGHTROOM", "NEEDS_EDIT", "READY_TO_PUBLISH"}:
                    if row["matched_library_path"]:
                        continue
                    db.execute("UPDATE assets SET export_path=?, edit_state='READY_TO_PUBLISH', updated_at=? WHERE asset_id=?",
                               (str(path), _now(), match.group(1).upper()))
                    if row["export_path"] != str(path):
                        matched += 1
        return {"matched": matched, "assets": self.list_assets()}

    @staticmethod
    def _hash(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _photo_digest(path: Path) -> str:
        """Compare selected photos independently of embedded metadata."""
        with Image.open(path) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            digest = hashlib.sha256(str(image.size).encode("ascii"))
            digest.update(image.tobytes())
            return digest.hexdigest()

    def _existing_published_pair(self, asset: dict, source: Path) -> tuple[Path, Path] | None:
        """Check matching published names before treating a collision as a new photo.

        Only candidates for this selected event/photo number are opened. Discovery
        continues to read metadata only, and renamed or moved library photos can
        be recovered even when the local catalog or shared manifest was reset.
        """
        root = AppConfig.HERO_PUBLISH_ROOT
        stem = self._published_stem(asset)
        candidates = sorted(
            (path for path in (root / "MASTER").rglob("*")
             if path.suffix.lower() in PUBLISHABLE_SUFFIXES
             and (path.stem == stem or re.fullmatch(re.escape(stem) + r" - EIS-H\d{6}", path.stem))),
            key=lambda path: (path.stem != stem, str(path)),
        )
        source_digest = None
        for master in candidates:
            if source_digest is None:
                source_digest = self._photo_digest(source)
            if self._photo_digest(master) != source_digest:
                continue
            web = root / "WEB" / master.relative_to(root / "MASTER").with_suffix(".jpg")
            if not web.is_file():
                alternatives = list((root / "WEB").rglob(master.stem + ".jpg"))
                if len(alternatives) != 1:
                    raise ValueError("This photo already has a MASTER on Drive, but its WEB copy is missing or ambiguous. Review the existing files before retrying.")
                web = alternatives[0]
            return master, web
        return None

    @staticmethod
    def _xmp(asset: dict) -> bytes:
        root = ET.Element("x:xmpmeta", {"xmlns:x": "adobe:ns:meta/"})
        rdf = ET.SubElement(root, "rdf:RDF", {"xmlns:rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#"})
        desc = ET.SubElement(rdf, "rdf:Description", {
            "xmlns:dc": "http://purl.org/dc/elements/1.1/",
            "xmlns:photoshop": "http://ns.adobe.com/photoshop/1.0/",
            "xmlns:ecc": "urn:ecc:hero:1.0",
            "ecc:AssetID": asset["asset_id"], "ecc:SourcePath": asset["source_path"],
            "ecc:SchoolYear": asset["school_year"], "ecc:EventID": asset["event_id"],
            "ecc:Featured": str(asset["featured"]).lower(),
            "ecc:BrowseGroup": HeroLibraryService._browse_group(asset),
        })
        title = ET.SubElement(desc, "dc:title")
        alt = ET.SubElement(title, "rdf:Alt")
        ET.SubElement(alt, "rdf:li", {"{http://www.w3.org/XML/1998/namespace}lang": "x-default"}).text = asset["event_name"] or asset["original_filename"]
        subject = ET.SubElement(desc, "dc:subject")
        bag = ET.SubElement(subject, "rdf:Bag")
        for term in HeroLibraryService._metadata_terms(asset):
            ET.SubElement(bag, "rdf:li").text = term
        ET.SubElement(desc, "photoshop:DateCreated").text = asset["event_date"].replace(".", "-")
        if asset["event_description"]:
            description = ET.SubElement(desc, "dc:description")
            alt = ET.SubElement(description, "rdf:Alt")
            ET.SubElement(alt, "rdf:li", {"{http://www.w3.org/XML/1998/namespace}lang": "x-default"}).text = asset["event_description"]
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _metadata_terms(asset: dict) -> list[str]:
        terms = [*asset["event_keywords"], *asset["extra_keywords"], *asset["event_grades"],
                 *asset["event_sections"], *asset["grades"], *asset["sections"],
                 asset["category"], asset["subject"], asset["setting"],
                 HeroLibraryService._browse_group(asset)]
        return list(dict.fromkeys(str(item).strip() for item in terms if str(item).strip()))

    @staticmethod
    def _metadata_description(asset: dict) -> str:
        title = str(asset.get("event_name") or asset.get("original_filename") or "Hero Library photo")
        date = str(asset.get("event_date") or "").replace(".", "-")
        tags = ", ".join(HeroLibraryService._metadata_terms(asset))
        parts = [title]
        if date:
            parts.append(date)
        if tags:
            parts.append(f"Tags: {tags}")
        return " | ".join(parts)

    @staticmethod
    def _embed_metadata(path: Path, asset: dict) -> bool:
        """Embed searchable tags without creating a separate metadata sidecar."""
        if path.suffix.lower() in {".jpg", ".jpeg"}:
            HeroLibraryService._embed_jpeg_xmp(path, HeroLibraryService._xmp(asset))
            return True
        keywords = HeroLibraryService._metadata_terms(asset)
        if shutil.which("exiftool"):
            command = ["exiftool", "-overwrite_original", f"-XMP-dc:Title={asset['event_name'] or asset['original_filename']}",
                       f"-XMP-dc:Description={HeroLibraryService._metadata_description(asset)}",
                       f"-XMP-photoshop:DateCreated={asset['event_date'].replace('.', '-')}",
                       f"-XMP-xmp:Identifier={asset['asset_id']}"]
            command.extend(f"-XMP-dc:Subject={word}" for word in keywords)
            command.append(str(path))
            subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            return True
        if path.suffix.lower() in PUBLISHABLE_SUFFIXES and shutil.which("sips"):
            try:
                subprocess.run(["sips", "--setProperty", "description",
                                HeroLibraryService._metadata_description(asset), str(path)],
                               check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                return True
            except subprocess.CalledProcessError:
                return False
        return False

    @staticmethod
    def _embed_jpeg_xmp(path: Path, xmp: bytes) -> None:
        """Replace standard XMP APP1 without decoding or recompressing a JPEG."""
        signature = b"http://ns.adobe.com/xap/1.0/\x00"
        payload = signature + xmp
        if len(payload) + 2 > 65535:
            raise ValueError("Hero metadata is too large to embed in JPEG.")
        segment = b"\xff\xe1" + (len(payload) + 2).to_bytes(2, "big") + payload
        fd, temp_name = tempfile.mkstemp(prefix=".hero-xmp-", dir=path.parent)
        try:
            with path.open("rb") as source, os.fdopen(fd, "wb") as target:
                if source.read(2) != b"\xff\xd8":
                    raise ValueError(f"Invalid JPEG: {path}")
                target.write(b"\xff\xd8")
                target.write(segment)
                while True:
                    marker = source.read(2)
                    if not marker:
                        break
                    if len(marker) != 2 or marker[0] != 0xff:
                        raise ValueError(f"Invalid JPEG segment: {path}")
                    if marker[1] in {0xd9, 0xda}:
                        target.write(marker)
                        shutil.copyfileobj(source, target)
                        break
                    if marker[1] in range(0xd0, 0xd8) or marker[1] == 0x01:
                        target.write(marker)
                        continue
                    length_bytes = source.read(2)
                    if len(length_bytes) != 2:
                        raise ValueError(f"Truncated JPEG segment: {path}")
                    length = int.from_bytes(length_bytes, "big")
                    data = source.read(length - 2)
                    if length < 2 or len(data) != length - 2:
                        raise ValueError(f"Truncated JPEG segment: {path}")
                    if marker != b"\xff\xe1" or not data.startswith(signature):
                        target.write(marker + length_bytes + data)
            shutil.copystat(path, temp_name)
            os.replace(temp_name, path)
        finally:
            Path(temp_name).unlink(missing_ok=True)

    def organize_drive_assets(self, asset_ids: list[str]) -> dict:
        """Turn tagged finished Drive photos into organized MASTER/WEB pairs."""
        root = AppConfig.HERO_PUBLISH_ROOT
        if root.name == "Photo_Library" or not root.is_dir():
            raise ValueError("Choose the new Hero_Shot_Library as the Drive destination.")
        organized = 0
        errors: list[str] = []
        with closing(self._connect()) as db, db:
            self._assign_event_photo_numbers(db)
            for asset_id in asset_ids:
                row = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
                if row is None or row["removed_at"] or row["edit_state"] == "PUBLISHED":
                    continue
                asset = self._record(row)
                staff_drive_source = asset["source_kind"] == "STAFF_DRIVE"
                matched_path = Path(asset["matched_library_path"]) if asset["matched_library_path"] else None
                if staff_drive_source:
                    drive_source = Path(asset["source_path"])
                elif matched_path and matched_path.is_relative_to(root):
                    drive_source = matched_path
                else:
                    continue
                try:
                    if not drive_source.is_relative_to(root) or not drive_source.is_file():
                        raise FileNotFoundError("The Drive photo is unavailable.")
                    if drive_source.suffix.lower() not in PUBLISHABLE_SUFFIXES:
                        raise ValueError("A raw file needs an edited export before it can enter MASTER and WEB.")
                    digest = self._hash(drive_source)
                    duplicate = db.execute("SELECT asset_id FROM assets WHERE sha256=? AND edit_state='PUBLISHED'", (digest,)).fetchone()
                    if duplicate:
                        raise ValueError(f"duplicates published asset {duplicate['asset_id']}")
                    browse_group = self._browse_group(asset)
                    asset["browse_group"] = browse_group
                    browse_path = self._browse_path(asset)
                    master_dir, web_dir = root / "MASTER" / browse_path, root / "WEB" / browse_path
                    stem = self._published_stem(asset)
                    master = master_dir / f"{stem}{drive_source.suffix.lower()}"
                    web = web_dir / f"{stem}.jpg"
                    if (master != drive_source and master.exists()) or web.exists():
                        stem = f"{stem} - {asset_id}"
                        master = master_dir / f"{stem}{drive_source.suffix.lower()}"
                        web = web_dir / f"{stem}.jpg"
                    if (master != drive_source and master.exists()) or web.exists():
                        raise FileExistsError("The destination already contains a photo with this name.")
                    moved_source = False
                    web_created = False
                    try:
                        master.parent.mkdir(parents=True, exist_ok=True)
                        web.parent.mkdir(parents=True, exist_ok=True)
                        if drive_source != master:
                            shutil.move(str(drive_source), str(master))
                            moved_source = True
                        with Image.open(master) as image:
                            exif = image.getexif()
                            capture_date = exif.get(36867) or exif.get(306) or datetime.fromtimestamp(master.stat().st_mtime).isoformat()
                            image = ImageOps.exif_transpose(image)
                            width, height = image.size
                            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                            image.convert("RGB").save(web, "JPEG", quality=82, optimize=True)
                            web_created = True
                        assignments = "edit_state='PUBLISHED', browse_group=?, sha256=?, capture_date=?, width=?, height=?, " \
                                      "orientation=?, master_path=?, web_path=?, matched_library_path=NULL, published_at=?, updated_at=?"
                        parameters: list[object] = [browse_group, digest, str(capture_date), width, height,
                                                    "Landscape" if width > height else "Portrait" if height > width else "Square",
                                                    str(master), str(web), _now(), _now()]
                        if staff_drive_source:
                            assignments = "source_path=?, source_size=?, " + assignments
                            parameters = [str(master), master.stat().st_size, *parameters]
                        db.execute(f"UPDATE assets SET {assignments} WHERE asset_id=?", (*parameters, asset_id))
                        db.commit()
                    except Exception:
                        db.rollback()
                        if web_created:
                            web.unlink(missing_ok=True)
                        if moved_source and master.is_file() and not drive_source.exists():
                            drive_source.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(master), str(drive_source))
                        raise
                    organized += 1
                except (OSError, ValueError, UnidentifiedImageError) as exc:
                    errors.append(f"{asset_id}: {exc}")
        return {"organized": organized, "errors": errors}

    def publish(self, asset_ids: list[str]) -> list[dict]:
        if not asset_ids:
            raise ValueError("Select at least one ready Hero asset.")
        root = AppConfig.HERO_PUBLISH_ROOT
        if root.name == "Photo_Library":
            raise ValueError("The existing Photo_Library is a read-only reference. Choose Hero_Shot_Library as the Drive destination.")
        if not root.is_dir():
            raise ValueError("Choose an existing shared-drive Hero Library folder in Hero settings.")
        with closing(self._connect()) as db, db:
            self._assign_event_photo_numbers(db)
            for asset_id in asset_ids:
                if not db.in_transaction:
                    db.execute("BEGIN IMMEDIATE")
                row = db.execute("SELECT * FROM assets WHERE asset_id=?", (asset_id,)).fetchone()
                if row is None or row["removed_at"] or row["matched_library_path"] or row["edit_state"] not in {"APPROVED_AS_IS", "READY_TO_PUBLISH"}:
                    raise ValueError(f"{asset_id} is not ready to publish.")
                asset = self._record(row)
                source = Path(asset["export_path"] if asset["edit_state"] == "READY_TO_PUBLISH" else asset["source_path"])
                if source.suffix.lower() not in PUBLISHABLE_SUFFIXES or not source.is_file():
                    raise ValueError(f"{asset_id} needs a finished JPEG, PNG, TIFF, or HEIC file.")
                digest = self._hash(source)
                duplicate = db.execute("SELECT asset_id FROM assets WHERE sha256=? AND edit_state='PUBLISHED'", (digest,)).fetchone()
                if duplicate:
                    raise ValueError(f"{asset_id} duplicates published asset {duplicate['asset_id']}.")
                browse_group = self._browse_group(asset)
                asset["browse_group"] = browse_group
                browse_path = self._browse_path(asset)
                master_dir, web_dir = root / "MASTER" / browse_path, root / "WEB" / browse_path
                existing_pair = self._existing_published_pair(asset, source)
                stem = self._published_stem(asset)
                master = master_dir / f"{stem}{source.suffix.lower()}"
                web = web_dir / f"{stem}.jpg"
                if existing_pair:
                    master, web = existing_pair
                    owner = db.execute("SELECT asset_id FROM assets WHERE master_path=? AND edit_state='PUBLISHED' AND removed_at IS NULL AND asset_id != ?",
                                       (str(master), asset_id)).fetchone()
                    if owner:
                        raise ValueError(f"{asset_id} duplicates published asset {owner['asset_id']}.")
                elif master.exists() or web.exists():
                    stem = f"{stem} - {asset_id}"
                    master = master_dir / f"{stem}{source.suffix.lower()}"
                    web = web_dir / f"{stem}.jpg"
                    if master.exists() or web.exists():
                        raise ValueError(f"Published file already exists for {asset_id}; review it before retrying.")
                try:
                    if not existing_pair:
                        master.parent.mkdir(parents=True, exist_ok=True)
                        web.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(source, master)
                    with Image.open(source) as image:
                        exif = image.getexif()
                        capture_date = exif.get(36867) or exif.get(306) or datetime.fromtimestamp(
                            Path(asset["source_path"]).stat().st_mtime
                        ).isoformat()
                        image = ImageOps.exif_transpose(image)
                        width, height = image.size
                        if not existing_pair:
                            image.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
                            image.convert("RGB").save(web, "JPEG", quality=82, optimize=True)
                    asset["sha256"] = digest
                    if not existing_pair:
                        self._embed_metadata(master, asset)
                        self._embed_metadata(web, asset)
                    db.execute("""UPDATE assets SET edit_state='PUBLISHED', browse_group=?, sha256=?, capture_date=?, width=?, height=?,
                        orientation=?, master_path=?, web_path=?, published_at=?, updated_at=? WHERE asset_id=?""",
                        (browse_group, digest, str(capture_date), width, height, "Landscape" if width > height else "Portrait" if height > width else "Square",
                         str(master), str(web), _now(), _now(), asset_id))
                    db.commit()
                except Exception:
                    if not existing_pair:
                        for path in (master, web):
                            path.unlink(missing_ok=True)
                    raise
                local_paths = [self._local_copy(asset)]
                local_paths.extend(Path(asset[key]) if asset[key] else None
                                   for key in ("thumbnail_path", "export_path"))
                for local_path in local_paths:
                    if local_path and local_path.is_relative_to(AppConfig.HERO_WORKSPACE_ROOT) and local_path.name.startswith(asset_id):
                        try:
                            local_path.unlink(missing_ok=True)
                        except OSError:
                            pass
                db.execute("UPDATE assets SET needs_edit_path=NULL, thumbnail_path=NULL, export_path=NULL WHERE asset_id=?", (asset_id,))
                db.commit()
        self.write_manifest()
        return self.list_assets()

    def write_manifest(self) -> dict:
        """Publish a generated, portable index without reading image content."""
        root = AppConfig.HERO_PUBLISH_ROOT
        if root.name == "Photo_Library" or not root.is_dir():
            return {"path": None, "count": 0}
        with closing(self._connect()) as db:
            rows = db.execute("SELECT * FROM assets WHERE edit_state='PUBLISHED' AND removed_at IS NULL ORDER BY asset_id").fetchall()
        entries = []
        for row in rows:
            asset = self._record(row)
            if not asset["master_path"] or not asset["web_path"]:
                continue
            master, web = Path(asset["master_path"]), Path(asset["web_path"])
            if not master.is_relative_to(root) or not web.is_relative_to(root):
                continue
            fields = ("asset_id", "source_kind", "original_filename", "source_size", "event_photo_number",
                      "event_name", "event_date", "school_year",
                      "event_id", "event_description", "event_grades", "event_sections", "event_keywords",
                      "grades", "sections", "category", "browse_group", "subject", "setting",
                      "extra_keywords", "featured", "sha256", "capture_date", "width", "height",
                      "orientation", "file_type", "published_at", "updated_at")
            entry = {key: asset[key] for key in fields}
            if entry["source_size"] is None:
                try:
                    entry["source_size"] = Path(asset["source_path"]).stat().st_size
                except OSError:
                    pass
            entry["master"] = str(master.relative_to(root))
            entry["web"] = str(web.relative_to(root))
            entries.append(entry)
        document = {"schema_version": 1, "generated_by": "Event Control Center",
                    "generated_at": _now(), "assets": entries}
        fd, temp_name = tempfile.mkstemp(prefix=".hero-catalog-", suffix=".json", dir=root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(document, output, ensure_ascii=False, indent=2)
                output.write("\n")
            os.replace(temp_name, root / "Hero_Catalog.json")
        finally:
            Path(temp_name).unlink(missing_ok=True)
        return {"path": str(root / "Hero_Catalog.json"), "count": len(entries)}

    def audit_drive(self) -> dict:
        """Find staff additions by path only; never open or hash Drive photos."""
        root = AppConfig.HERO_PUBLISH_ROOT
        if root.name == "Photo_Library" or not root.is_dir():
            raise ValueError("Choose the new Hero_Shot_Library as the Drive destination.")
        with closing(self._connect()) as db:
            rows = db.execute("SELECT source_path, source_kind, master_path, web_path FROM assets").fetchall()
        known = {str(Path(row[key])) for row in rows for key in ("master_path", "web_path") if row[key]}
        known.update(str(Path(row["source_path"])) for row in rows if row["source_kind"] == "STAFF_DRIVE")
        found = []
        for folder, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [name for name in dirs if name not in {"_Removed", "_Metadata"} and not name.startswith(".")]
            for name in names:
                path = Path(folder) / name
                if path.suffix.lower() in IMAGE_SUFFIXES and str(path) not in known:
                    found.append(str(path.relative_to(root)))
        return {"uncatalogued": sorted(found, key=str.casefold), "count": len(found)}

    def adopt_drive(self, relative_paths: list[str]) -> dict:
        """Register reviewed staff photos without opening or moving their bytes."""
        root = AppConfig.HERO_PUBLISH_ROOT
        if root.name == "Photo_Library" or not root.is_dir():
            raise ValueError("Choose the new Hero_Shot_Library as the Drive destination.")
        if not relative_paths:
            raise ValueError("Select at least one staff photo to add.")
        if len(relative_paths) > 10:
            raise ValueError("Add at most 10 staff photos at a time.")
        added: list[str] = []
        with closing(self._connect()) as db, db:
            known = {str(Path(row[key])) for row in db.execute(
                "SELECT source_path, master_path, web_path FROM assets")
                     for key in ("source_path", "master_path", "web_path") if row[key]}
            for raw in relative_paths:
                relative = Path(raw)
                if relative.is_absolute() or not relative.parts or ".." in relative.parts or "." in relative.parts:
                    raise ValueError("Choose a photo inside the Hero Shot Library.")
                if any(part.startswith(".") or part in {"_Removed", "_Metadata"} for part in relative.parts):
                    raise ValueError("Choose a visible staff photo in the Hero Shot Library.")
                source = root / relative
                if source.is_symlink() or not source.is_file() or not source.resolve().is_relative_to(root.resolve()):
                    raise ValueError(f"Staff photo unavailable: {relative}")
                if source.suffix.lower() not in IMAGE_SUFFIXES:
                    raise ValueError(f"Not a supported photo: {relative}")
                if str(source) in known:
                    raise ValueError(f"Already in the Hero catalog: {relative}")
                event_folder, event = self._event_metadata(source, root)
                event_grades = event.get("grades", []) if isinstance(event.get("grades", []), list) else []
                raw_sections = event.get("sections", []) if isinstance(event.get("sections", []), list) else []
                event_sections = sorted({str(value).upper() for value in [*event_grades, *raw_sections]
                                         if str(value).upper() in SECTIONS})
                timestamp = _now()
                cursor = db.execute("""INSERT INTO assets
                    (source_path, source_size, source_kind, original_filename, event_folder, event_name,
                     event_date, school_year, event_id, event_description,
                     event_grades, event_sections, event_keywords,
                     file_type, discovered_at, updated_at)
                    VALUES (?, ?, 'STAFF_DRIVE', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(source), source.stat().st_size, source.name, event_folder, str(event.get("event_name", "")),
                     str(event.get("date", "")), str(event.get("school_year", "")),
                     str(event.get("event_id") or ""), str(event.get("description") or ""),
                     _json([str(value) for value in event_grades]), _json(event_sections),
                     _json(KeywordVocabulary().canonicalize(event.get("keywords", []))),
                     source.suffix.lower().lstrip("."), timestamp, timestamp))
                asset_id = f"EIS-H{cursor.lastrowid:06d}"
                db.execute("UPDATE assets SET asset_id=? WHERE id=?", (asset_id, cursor.lastrowid))
                known.add(str(source))
                added.append(asset_id)
            self._assign_event_photo_numbers(db)
        return {"added": added, "assets": self.list_assets()}

    def consolidate_metadata(self, asset_ids: list[str] | None = None) -> dict:
        """Move old per-image sidecars to a reversible local backup after indexing."""
        root = AppConfig.HERO_PUBLISH_ROOT
        selected = set(asset_ids) if asset_ids is not None else None
        backup_root = AppConfig.HERO_WORKSPACE_ROOT / "Metadata Backups"
        manifest_path = root / "Hero_Catalog.json"
        manifest_ids = {item.get("asset_id") for item in json.loads(manifest_path.read_text(encoding="utf-8")).get("assets", [])} if manifest_path.is_file() else set()
        archived = 0
        errors = []
        for asset in self.list_assets():
            asset_id = asset["asset_id"]
            if asset["edit_state"] != "PUBLISHED" or asset["removed_at"] or (selected is not None and asset_id not in selected):
                continue
            paths = [Path(asset[key]) for key in ("master_path", "web_path") if asset[key]]
            candidates = [sidecar for path in paths for sidecar in (_sidecar(path), path.with_suffix(path.suffix + ".xmp"))]
            candidates.append(root / "_Metadata" / f"{asset_id}.xmp")
            if asset_id not in manifest_ids:
                errors.append(f"{asset_id}: generated catalog is missing this asset; sidecars retained.")
                continue
            web = Path(asset["web_path"]) if asset["web_path"] else None
            if web is None or not web.is_file() or asset_id.encode() not in web.read_bytes():
                errors.append(f"{asset_id}: WEB metadata could not be verified; sidecars retained.")
                continue
            for path in dict.fromkeys(candidates):
                if not path.is_file() or not path.is_relative_to(root):
                    continue
                try:
                    destination = backup_root / path.relative_to(root)
                    if destination.exists():
                        raise FileExistsError(f"Backup already exists: {destination}")
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(path), str(destination))
                    archived += 1
                except OSError as exc:
                    errors.append(f"{asset_id}: {exc}")
        return {"archived_sidecars": archived, "errors": errors}

    @staticmethod
    def _prune_legacy_folders(root: Path) -> None:
        for legacy in (root / "Events", root / "General School Life"):
            if not legacy.is_dir():
                continue
            directories = [path for path in legacy.rglob("*") if path.is_dir()]
            for folder in [*sorted(directories, key=lambda path: len(path.parts), reverse=True), legacy]:
                if not folder.is_dir():
                    continue
                contents = list(folder.iterdir())
                if all(item.name == ".DS_Store" and item.is_file() for item in contents):
                    for item in contents:
                        item.unlink()
                    folder.rmdir()

    def reorganize_published(self, asset_ids: list[str] | None = None) -> dict:
        """Move only catalog-owned published files into the shallow browse folders."""
        root = AppConfig.HERO_PUBLISH_ROOT
        if root.name == "Photo_Library" or not root.is_dir():
            raise ValueError("Choose the new Hero_Shot_Library as the Drive destination.")
        moved = 0
        errors: list[str] = []
        with closing(self._connect()) as db, db:
            if asset_ids is None:
                rows = db.execute("SELECT * FROM assets WHERE edit_state='PUBLISHED' AND removed_at IS NULL").fetchall()
            else:
                rows = [row for asset_id in asset_ids if (row := db.execute(
                    "SELECT * FROM assets WHERE asset_id=? AND edit_state='PUBLISHED' AND removed_at IS NULL",
                    (asset_id,)).fetchone()) is not None]
            for row in rows:
                asset = self._record(row)
                asset_id = asset["asset_id"]
                try:
                    if not asset["master_path"] or not asset["web_path"]:
                        raise ValueError("Published file paths are missing.")
                    old_master, old_web = Path(asset["master_path"]), Path(asset["web_path"])
                    if not old_master.is_relative_to(root) or not old_web.is_relative_to(root):
                        raise ValueError("Published files are outside the selected Hero Shot Library.")
                    if not old_master.is_file() or not old_web.is_file():
                        raise FileNotFoundError("A published MASTER or WEB file is missing.")
                    group = self._browse_group(asset)
                    browse_path = self._browse_path(asset)
                    new_master = root / "MASTER" / browse_path / old_master.name
                    new_web = root / "WEB" / browse_path / old_web.name
                    moves = [(old_master, new_master), (old_web, new_web)]
                    if all(old == new for old, new in moves):
                        if asset["browse_group"] != group:
                            db.execute("UPDATE assets SET browse_group=?, updated_at=? WHERE asset_id=?",
                                       (group, _now(), asset_id))
                        continue
                    for old, new in moves:
                        if old != new and new.exists():
                            raise FileExistsError(f"Destination already contains {new.name}.")
                    completed: list[tuple[Path, Path]] = []
                    try:
                        for old, new in moves:
                            if old == new:
                                continue
                            new.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(old), str(new))
                            completed.append((old, new))
                        db.execute("""UPDATE assets SET browse_group=?, master_path=?, web_path=?, updated_at=?
                            WHERE asset_id=?""", (group, str(new_master), str(new_web), _now(), asset_id))
                        db.commit()
                    except Exception:
                        for old, new in reversed(completed):
                            shutil.move(str(new), str(old))
                        raise
                    moved += 1
                except (OSError, ValueError) as exc:
                    errors.append(f"{asset_id}: {exc}")
        manifest = self.write_manifest()
        metadata = self.consolidate_metadata(asset_ids)
        errors.extend(metadata["errors"])
        self._prune_legacy_folders(root)
        return {"moved": moved, "catalogued": manifest["count"],
                "archived_sidecars": metadata["archived_sidecars"],
                "errors": errors, "assets": self.list_assets()}

    def push_batch(self, asset_ids: list[str]) -> dict:
        if not asset_ids:
            raise ValueError("No finished photos are ready to move to Google Drive.")
        pushed = 0
        errors: list[str] = []
        for asset_id in asset_ids:
            try:
                self.publish([asset_id])
                pushed += 1
            except (OSError, ValueError) as exc:
                errors.append(f"{asset_id}: {exc}")
        return {"pushed": pushed, "errors": errors, "assets": self.list_assets()}

    def push_originals(self, asset_ids: list[str]) -> dict:
        """Publish selected finished originals without a Lightroom export."""
        if not asset_ids:
            raise ValueError("Select at least one finished original photo.")
        pushed = 0
        errors: list[str] = []
        for asset_id in asset_ids:
            try:
                with closing(self._connect()) as db:
                    row = db.execute("SELECT edit_state, removed_at, matched_library_path FROM assets WHERE asset_id=?",
                                     (asset_id,)).fetchone()
                if row is None or row["removed_at"] or row["matched_library_path"] or row["edit_state"] not in {
                    "UNREVIEWED", "NEEDS_EDIT", "IN_LIGHTROOM", "APPROVED_AS_IS"
                }:
                    raise ValueError("This photo is already on Drive, removed, or being edited in Lightroom.")
                self.update([asset_id], {"edit_state": "APPROVED_AS_IS"})
                self.publish([asset_id])
                pushed += 1
            except (OSError, ValueError) as exc:
                errors.append(f"{asset_id}: {exc}")
        return {"pushed": pushed, "errors": errors, "assets": self.list_assets()}
