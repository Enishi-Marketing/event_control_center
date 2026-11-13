import platform
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from services.drive_detector import DriveDetector
from services.hash_service import HashService
from services.importer import ImportService


@dataclass
class SourceCleanupResult:
    """Outcome of deleting imported source files and ejecting the source."""

    deleted: int = 0
    delete_failures: list[str] = field(default_factory=list)
    ejected: bool = False
    eject_message: str = ""


class SourceCleanupService:
    """Deletes verified imported files from a source and ejects removable media."""

    def cleanup_imported_files(
        self,
        files: list[Path],
        source: Path,
        import_receipt: Path | None = None,
    ) -> SourceCleanupResult:
        result = SourceCleanupResult()
        mount_path = self.ejectable_mount(source)
        if mount_path is None:
            result.eject_message = "Source is not a recognized removable mount; no files were deleted."
            return result

        try:
            records = self._validate_receipt(import_receipt, source, files)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.delete_failures.append(str(exc))
            result.eject_message = "Cleanup blocked; no files were deleted. Keep the source and review the import count check."
            return result

        # Validate the entire batch before deleting the first file. Both original
        # copies must still match; conversion success alone is never sufficient.
        for record in records:
            path, destination, conversion, fingerprints = record
            try:
                if [self._fingerprint(p) for p in (path, destination, conversion)] != fingerprints:
                    raise ValueError("files changed after verification")
                path.unlink()
                result.deleted += 1
            except (OSError, ValueError) as exc:
                result.delete_failures.append(f"{path}: {exc}")
                break

        if not result.delete_failures:
            result.ejected, result.eject_message = self._eject(mount_path)
        else:
            result.eject_message = "Cleanup stopped because files changed or could not be deleted. Keep the remaining source files."
        return result

    def _validate_receipt(
        self, receipt_path: Path | None, source: Path, files: list[Path],
    ) -> list[tuple[Path, Path, Path, list[tuple[int, int, int, int]]]]:
        if receipt_path is None:
            raise ValueError("A completed import count check is required for cleanup.")
        receipt_path = receipt_path.resolve(strict=True)
        if receipt_path.parent.name != "Import Checks" or receipt_path.parent.parent.name != "Data":
            raise ValueError("Invalid import count report location.")
        event = receipt_path.parents[2]
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if receipt["version"] != 2 or Path(receipt["source"]).resolve() != source.resolve():
            raise ValueError("The import count check belongs to a different source.")
        if Path(receipt["event_folder"]).resolve() != event or receipt["check"]["cleanup_allowed"] is not True:
            raise ValueError("Import count check has warnings; source cleanup is disabled.")
        entries = receipt["records"]
        requested = {p.resolve() for p in files}
        verified = {Path(entry["source"]) for entry in entries}
        if not entries or len(verified) != len(entries) or requested != verified:
            raise ValueError("Cleanup files do not match this import count check.")
        failures: list[str] = []
        scanner = ImportService()
        current = scanner._walk_source(source, failures, media_only=True)
        relative_paths = {str(p.relative_to(source)) for p in current}
        if failures or any(p.is_symlink() for p in current) or relative_paths != set(receipt["source_media"]):
            raise ValueError("Photos or videos on the source changed. Scan and check the source again.")
        if not verified.issubset({p.resolve() for p in current}):
            raise ValueError("Cleanup files do not match the photos and videos on the source.")
        validated = []
        hashes = HashService()
        for entry in entries:
            path = Path(entry["source"])
            destination = Path(entry["destination"])
            conversion = Path(entry["conversion"])
            media_type = scanner._media_type(path)
            if media_type is None or entry["media_type"] != media_type:
                raise ValueError(f"{path}: cleanup can only delete imported photos and videos")
            folder = "Photos" if media_type == "photo" else "Videos"
            conversion_folder = event / "Unedited JPGs" / "Photos" if folder == "Photos" else event / "Raw" / "Smaller Videos"
            if (not self._is_within(path, source)
                or not destination.resolve().is_relative_to(event / "Raw" / folder)
                or not conversion.resolve().is_relative_to(conversion_folder)):
                raise ValueError(f"{path}: invalid source or archive location")
            for candidate in (path, destination, conversion):
                if candidate.is_symlink() or not candidate.is_file():
                    raise ValueError(f"{candidate}: missing file or symbolic link")
            if conversion.stat().st_size == 0:
                raise ValueError(f"{conversion}: conversion is empty")
            fingerprints = [self._fingerprint(p) for p in (path, destination, conversion)]
            if not hashes.verify(path, destination):
                raise ValueError(f"{path}: source and archive hashes no longer match")
            if [self._fingerprint(p) for p in (path, destination, conversion)] != fingerprints:
                raise ValueError(f"{path}: files changed during verification")
            validated.append((path, destination, conversion, fingerprints))
        return validated

    @staticmethod
    def _fingerprint(path: Path) -> tuple[int, int, int, int]:
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns

    def ejectable_mount(self, source: Path) -> Path | None:
        return DriveDetector().removable_mount(source)

    def _is_within(self, path: Path, source: Path) -> bool:
        try:
            path.resolve().relative_to(source.resolve())
        except ValueError:
            return False
        return True

    def _eject(self, mount_path: Path) -> tuple[bool, str]:
        if platform.system() == "Darwin":
            command = ["diskutil", "eject", str(mount_path)]
        else:
            command = ["umount", str(mount_path)]

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)

        output = (completed.stdout or completed.stderr).strip()
        if completed.returncode == 0:
            return True, output or f"Ejected {mount_path}"
        return False, output or f"Eject failed for {mount_path}"
