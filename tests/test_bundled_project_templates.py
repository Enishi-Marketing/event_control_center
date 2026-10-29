import gzip
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from config.config import AppConfig, _template_override
from services.project_service import ProjectService


class BundledProjectTemplateTests(unittest.TestCase):
    def test_templates_are_blank_and_create_event_projects(self) -> None:
        catalog = AppConfig.BUNDLED_LIGHTROOM_TEMPLATE_DIR / "Blank_Lightroom.lrcat"
        premiere = AppConfig.BUNDLED_PREMIERE_TEMPLATE
        filmcraft = AppConfig.BUNDLED_FILMCRAFT_TEMPLATE
        self.assertTrue(catalog.is_file())
        self.assertTrue(premiere.is_file())
        self.assertTrue(filmcraft.is_file())
        self.assertNotIn(b"/Users/", catalog.read_bytes())
        self.assertNotIn(b"/Users/", gzip.decompress(premiere.read_bytes()))
        self.assertNotIn(b"/Users/", filmcraft.read_bytes())
        self.assertEqual(json.loads(filmcraft.read_bytes())["format"], "filmcraft.project")

        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary) / "Example Event"
            service = ProjectService(
                lightroom_template_dir=AppConfig.BUNDLED_LIGHTROOM_TEMPLATE_DIR,
                premiere_template=premiere,
                filmcraft_template=filmcraft,
            )
            result = service.create_projects(event, "Example Event", True, True)
            self.assertEqual(result.failures, [])
            self.assertTrue(result.lightroom_created)
            self.assertTrue(result.premiere_created)
            self.assertTrue(result.filmcraft_created)

            created_catalog = event / "Example Event Catalog" / "Example Event Catalog.lrcat"
            self.assertTrue(created_catalog.is_file())
            with closing(sqlite3.connect(created_catalog)) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM Adobe_images").fetchone()[0], 0)
            self.assertTrue(
                (event / "Example Event Premiere Project" / "Example Event Premiere Project.prproj").is_file()
            )
            created_filmcraft = event / "Example Event Filmcraft Project" / "Example Event Filmcraft Project.fcproj"
            self.assertEqual(created_filmcraft.read_bytes(), filmcraft.read_bytes())

    def test_repeat_video_import_keeps_edited_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary) / "event"
            service = ProjectService(
                premiere_template=AppConfig.BUNDLED_PREMIERE_TEMPLATE,
                filmcraft_template=AppConfig.BUNDLED_FILMCRAFT_TEMPLATE,
            )
            first = service.create_projects(event, '  Sports: Day / Finals?  ', False, True)
            self.assertEqual(first.failures, [])
            for editor, extension in [("Premiere", "prproj"), ("Filmcraft", "fcproj")]:
                project = event / f"Sports- Day - Finals- {editor} Project" / f"Sports- Day - Finals- {editor} Project.{extension}"
                project.write_bytes(b"edited project")

            repeated = service.create_projects(event, '  Sports: Day / Finals?  ', False, True)
            self.assertEqual(repeated.failures, [])
            self.assertTrue(repeated.premiere_skipped)
            self.assertTrue(repeated.filmcraft_skipped)
            self.assertFalse(repeated.filmcraft_created)
            for project in event.glob("*/*"):
                self.assertEqual(project.read_bytes(), b"edited project")

    def test_video_projects_fail_independently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for missing in ["Premiere", "Filmcraft"]:
                with self.subTest(missing=missing):
                    service = ProjectService(
                        premiere_template=root / "missing.prproj" if missing == "Premiere" else AppConfig.BUNDLED_PREMIERE_TEMPLATE,
                        filmcraft_template=root / "missing.fcproj" if missing == "Filmcraft" else AppConfig.BUNDLED_FILMCRAFT_TEMPLATE,
                    )
                    result = service.create_projects(root / missing, "Event", False, True)
                    self.assertEqual(len(result.failures), 1)
                    self.assertTrue(result.failures[0].startswith(f"{missing} project:"))
                    self.assertEqual(result.premiere_created, missing != "Premiere")
                    self.assertEqual(result.filmcraft_created, missing != "Filmcraft")

    def test_photo_only_import_does_not_create_video_projects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary) / "event"
            result = ProjectService(
                lightroom_template_dir=AppConfig.BUNDLED_LIGHTROOM_TEMPLATE_DIR,
            ).create_projects(event, "Event", True, False)
            self.assertEqual(result.failures, [])
            self.assertTrue(result.lightroom_created)
            self.assertFalse(result.premiere_created)
            self.assertFalse(result.filmcraft_created)
            self.assertFalse(result.filmcraft_skipped)
            self.assertEqual([folder.name for folder in event.iterdir()], ["Event Catalog"])

    def test_old_default_paths_migrate_to_bundled_templates(self) -> None:
        legacy = Path.home() / "Documents" / "Blank_Lightroom"
        with patch.dict("os.environ", {"LIGHTROOM_TEMPLATE_DIR": str(legacy)}):
            self.assertEqual(_template_override("LIGHTROOM_TEMPLATE_DIR", legacy), "")
        with patch.dict("os.environ", {"LIGHTROOM_TEMPLATE_DIR": "/custom/catalog"}):
            self.assertEqual(_template_override("LIGHTROOM_TEMPLATE_DIR", legacy), "/custom/catalog")


if __name__ == "__main__":
    unittest.main()
