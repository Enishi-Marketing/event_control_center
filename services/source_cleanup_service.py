import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


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
    ) -> SourceCleanupResult:
        result = SourceCleanupResult()
        unique_files = sorted({path for path in files}, key=lambda path: str(path))

        for path in unique_files:
            try:
                if not self._is_within(path, source):
                    result.delete_failures.append(f"{path}: not inside source")
                    continue
                if not path.exists():
                    result.delete_failures.append(f"{path}: already missing")
                    continue
                path.unlink()
                result.deleted += 1
            except OSError as exc:
                result.delete_failures.append(f"{path}: {exc}")

        mount_path = self.ejectable_mount(source)
        if mount_path is None:
            result.eject_message = "Source is not a recognized removable mount."
            return result

        result.ejected, result.eject_message = self._eject(mount_path)
        return result

    def ejectable_mount(self, source: Path) -> Path | None:
        source = source.resolve()
        roots = (Path("/Volumes"), Path("/media"), Path("/mnt"))

        for root in roots:
            try:
                relative = source.relative_to(root)
            except ValueError:
                continue

            parts = relative.parts
            if not parts:
                return None
            return root / parts[0]

        return None

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
