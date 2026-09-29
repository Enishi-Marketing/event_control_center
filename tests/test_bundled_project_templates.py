import gzip
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
        self.assertTrue(catalog.is_file())
        self.assertTrue(premiere.is_file())
        self.assertNotIn(b"/Users/", catalog.read_bytes())
        self.assertNotIn(b"/Users/", gzip.decompress(premiere.read_bytes()))

        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary) / "Example Event"
            service = ProjectService(
                lightroom_template_dir=AppConfig.BUNDLED_LIGHTROOM_TEMPLATE_DIR,
                premiere_template=premiere,
            )
            result = service.create_projects(event, "Example Event", True, True)
            self.assertEqual(result.failures, [])
            self.assertTrue(result.lightroom_created)
            self.assertTrue(result.premiere_created)

            created_catalog = event / "Example Event Catalog" / "Example Event Catalog.lrcat"
            self.assertTrue(created_catalog.is_file())
            with closing(sqlite3.connect(created_catalog)) as db:
                self.assertEqual(db.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM Adobe_images").fetchone()[0], 0)
            self.assertTrue(
                (event / "Example Event Premiere Project" / "Example Event Premiere Project.prproj").is_file()
            )

    def test_old_default_paths_migrate_to_bundled_templates(self) -> None:
        legacy = Path.home() / "Documents" / "Blank_Lightroom"
        with patch.dict("os.environ", {"LIGHTROOM_TEMPLATE_DIR": str(legacy)}):
            self.assertEqual(_template_override("LIGHTROOM_TEMPLATE_DIR", legacy), "")
        with patch.dict("os.environ", {"LIGHTROOM_TEMPLATE_DIR": "/custom/catalog"}):
            self.assertEqual(_template_override("LIGHTROOM_TEMPLATE_DIR", legacy), "/custom/catalog")


if __name__ == "__main__":
    unittest.main()
