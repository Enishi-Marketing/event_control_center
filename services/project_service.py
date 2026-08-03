import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from config.config import AppConfig


@dataclass
class ProjectCreationSummary:
    """Outcome of creating editing project files for an event."""

    lightroom_created: bool = False
    lightroom_skipped: bool = False
    premiere_created: bool = False
    premiere_skipped: bool = False
    failures: list[str] = field(default_factory=list)


class ProjectService:
    """Creates Lightroom and Premiere projects from local blank templates."""

    def __init__(
        self,
        lightroom_template_dir: Path | None = None,
        premiere_template: Path | None = None,
    ) -> None:
        self.lightroom_template_dir = (
            lightroom_template_dir or AppConfig.LIGHTROOM_TEMPLATE_DIR
        )
        self.premiere_template = premiere_template or AppConfig.PREMIERE_TEMPLATE

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

        if has_videos:
            try:
                summary.premiere_created, summary.premiere_skipped = (
                    self.create_premiere_project(event_folder, clean_name)
                )
            except Exception as exc:
                summary.failures.append(f"Premiere project: {exc}")

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

        project_folder = event_folder / f"{clean_name} Premiere Project"
        project_file = project_folder / f"{clean_name} Premiere Project.prproj"
        if project_file.exists():
            return False, True

        project_folder.mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.premiere_template, project_file)
        return True, False

    def _event_name_from_folder(self, event_folder: Path) -> str:
        folder_name = event_folder.name
        if " - " in folder_name:
            return folder_name.split(" - ", 1)[1]
        return folder_name

    def _safe_filename(self, name: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "-", name.strip())
        cleaned = re.sub(r"\s+", " ", cleaned)
        return cleaned.strip(" .") or "Event"
