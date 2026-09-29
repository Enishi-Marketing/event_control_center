import platform
import plistlib
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ImportSource:
    """A folder-like source that can be scanned for importable media."""

    name: str
    path: Path
    is_removable: bool = False


class DriveDetector:
    """Detects removable media and user-selectable import sources."""

    def available_sources(self) -> list[ImportSource]:
        sources: list[ImportSource] = []

        for root in self._candidate_roots():
            sources.extend(self._mounted_sources(root))

        return sources

    def removable_mount(self, source: Path) -> Path | None:
        """Return the actual removable volume containing a selected path."""
        source = source.resolve()
        for root in self._candidate_roots():
            try:
                relative = source.relative_to(root)
            except ValueError:
                continue
            if relative.parts:
                mount = root / relative.parts[0]
                if self._is_importable_mount(root, mount):
                    return mount
        return None

    def _candidate_roots(self) -> tuple[Path, ...]:
        return (Path("/Volumes"), Path("/media"), Path("/mnt"))

    def _mounted_sources(self, root: Path) -> list[ImportSource]:
        if not root.exists():
            return []

        sources: list[ImportSource] = []
        try:
            children = sorted(root.iterdir(), key=lambda path: path.name.casefold())
        except OSError:
            return []

        for child in children:
            if child.is_dir() and self._is_importable_mount(root, child):
                sources.append(
                    ImportSource(
                        name=child.name,
                        path=child,
                        is_removable=True,
                    )
                )

        return sources

    def _is_importable_mount(self, root: Path, child: Path) -> bool:
        if root == Path("/Volumes") and child.name == "Macintosh HD":
            return False
        if child.name.startswith("."):
            return False
        if root != Path("/Volumes") or platform.system() != "Darwin":
            return True
        try:
            result = subprocess.run(
                ["diskutil", "info", "-plist", str(child)],
                check=True,
                capture_output=True,
                timeout=5,
            )
            info = plistlib.loads(result.stdout)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError):
            return False
        return (
            bool(info.get("Ejectable"))
            and bool(info.get("WritableVolume"))
            and not bool(info.get("Internal"))
            and str(info.get("BusProtocol", "")).casefold() != "disk image"
        )
