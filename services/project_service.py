import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from config.config import AppConfig
from services.lightcraft_service import prepare_lightcraft


def legacy_filmcraft_path(event_folder: Path, project_file: Path) -> Path:
    return event_folder / project_file.stem / project_file.name


@dataclass
class ProjectCreationSummary:
    """Outcome of creating editing project files for an event."""

    lightroom_created: bool = False
    lightroom_skipped: bool = False
    premiere_created: bool = False
    premiere_skipped: bool = False
    failures: list[str] = field(default_factory=list)
    filmcraft_created: bool = False
    filmcraft_skipped: bool = False
    lightcraft_path: str | None = None


class ProjectService:
    """Creates Lightroom, Premiere, and Filmcraft projects from blank templates."""

    def __init__(
        self,
        lightroom_template_dir: Path | None = None,
        premiere_template: Path | None = None,
        filmcraft_template: Path | None = None,
    ) -> None:
        self.lightroom_template_dir = (
            lightroom_template_dir or AppConfig.LIGHTROOM_TEMPLATE_DIR
        )
        self.premiere_template = premiere_template or AppConfig.PREMIERE_TEMPLATE
        self.filmcraft_template = filmcraft_template or AppConfig.FILMCRAFT_TEMPLATE

    def create_projects(
        self,
        event_folder: Path,
        event_name: str,
        has_photos: bool,
        has_videos: bool,
    ) -> ProjectCreationSummary:
        summary = ProjectCreationSummary()
        clean_name = self._safe_filename(event_name or self._event_name_from_folder(event_folder))

        if has_photos:
            try:
                summary.lightroom_created, summary.lightroom_skipped = (
                    self.create_lightroom_project(event_folder, clean_name)
                )
            except Exception as exc:
                summary.failures.append(f"Lightroom project: {exc}")
            try:
                path, failures = prepare_lightcraft(
                    event_folder, event_folder / f"{clean_name} Catalog", clean_name,
                )
                summary.lightcraft_path = str(path) if path else None
                summary.failures.extend(f"LightCraft: {failure}" for failure in failures)
            except Exception as exc:
                summary.failures.append(f"LightCraft: {exc}")

        if has_videos:
            try:
                summary.premiere_created, summary.premiere_skipped = (
                    self.create_premiere_project(event_folder, clean_name)
                )
            except Exception as exc:
                summary.failures.append(f"Premiere project: {exc}")
        if has_photos or has_videos:
            try:
                summary.filmcraft_created, summary.filmcraft_skipped = self.create_filmcraft_project(event_folder, clean_name)
            except Exception as exc:
                summary.failures.append(f"Filmcraft project: {exc}")

        return summary

    def create_lightroom_project(
        self,
        event_folder: Path,
        clean_name: str,
    ) -> tuple[bool, bool]:
        if not self.lightroom_template_dir.exists():
            raise FileNotFoundError(
                f"Lightroom template not found: {self.lightroom_template_dir}"
            )

        project_folder = event_folder / f"{clean_name} Catalog"
        if project_folder.exists():
            return False, True

        shutil.copytree(self.lightroom_template_dir, project_folder)
        original_catalog = project_folder / "Blank_Lightroom.lrcat"
        new_catalog = project_folder / f"{clean_name} Catalog.lrcat"
        if not original_catalog.exists():
            raise FileNotFoundError(f"Lightroom catalog missing: {original_catalog}")

        original_catalog.rename(new_catalog)
        return True, False

    def create_premiere_project(
        self,
        event_folder: Path,
        clean_name: str,
    ) -> tuple[bool, bool]:
        if not self.premiere_template.exists():
            raise FileNotFoundError(f"Premiere template not found: {self.premiere_template}")

        project_folder = self._video_project_folder(event_folder, clean_name)
        project_file = project_folder / f"{clean_name} Premiere Project.prproj"
        if project_file.exists():
            return False, True

        project_folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.premiere_template, project_file)
        return True, False

    def create_filmcraft_project(
        self,
        event_folder: Path,
        clean_name: str,
    ) -> tuple[bool, bool]:
        if not self.filmcraft_template.exists():
            raise FileNotFoundError(f"Filmcraft template not found: {self.filmcraft_template}")

        project_file = self.filmcraft_project_path(event_folder, clean_name)
        project_folder = project_file.parent
        if project_file.exists() or legacy_filmcraft_path(event_folder, project_file).is_file():
            return False, True

        project_folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.filmcraft_template, project_file)
        return True, False

    def filmcraft_project_path(self, event_folder: Path, event_name: str) -> Path:
        name = self._safe_filename(event_name or self._event_name_from_folder(event_folder))
        return self._video_project_folder(event_folder, name) / f"{name} Filmcraft Project.fcproj"

    @staticmethod
    def _video_project_folder(event_folder: Path, name: str) -> Path:
        return event_folder / f"{name} Premiere Project"

    def _event_name_from_folder(self, event_folder: Path) -> str:
        folder_name = event_folder.name
        if " - " in folder_name:
            return folder_name.split(" - ", 1)[1]
        return folder_name

    def _safe_filename(self, name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "-", name.strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" .") or "Event"
