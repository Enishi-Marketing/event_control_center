import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from backend_bridge import _create_event
from config.config import AppConfig


class CreateEventTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        contexts = ExitStack()
        self.addCleanup(contexts.close)
        self.root = Path(temporary.name)
        self.payload = {
            "event_name": "Sports Day",
            "event_date": "2026.10.28",
            "destination": "Local Events Folder",
            "school_year": "2026-2027",
            "keywords": [" Sports ", "sports", "House   Competition", "STEM"],
            "description": "School sports event",
            "grades": ["PYP"],
        }
        contexts.enter_context(patch.object(AppConfig, "LOCAL_EVENT_ROOT", self.root / "local"))
        contexts.enter_context(patch.object(AppConfig, "EVENT_ROOT", self.root / "drive"))
        contexts.enter_context(patch.object(AppConfig, "SHARED_DRIVE_CONFIGURED", True))
        self.scan = contexts.enter_context(patch(
            "backend_bridge.MetadataSearchService.build_index",
            side_effect=TimeoutError("Unrelated archive is stalled"),
        ))

    def test_local_and_shared_creation_do_not_scan_archives(self) -> None:
        for destination, root_name in [("Local Events Folder", "local"), ("Google Drive", "drive")]:
            with self.subTest(destination=destination):
                result = _create_event({**self.payload, "destination": destination})
                folder = self.root / root_name / "2026.10.28 - Sports Day"
                self.assertEqual(result["event_folder"], str(folder))
                self.assertFalse(result["already_existed"])
                for subfolder in ["Data", "Raw", "Finals", "Raw/Smaller Videos"]:
                    self.assertTrue((folder / subfolder).is_dir())
                metadata = json.loads((folder / "Data/metadata.json").read_text())
                self.assertEqual(metadata["keywords"], ["House Competition", "Sports", "STEM"])
                self.assertEqual(metadata["description"], "School sports event")
                self.assertEqual(metadata["grades"], ["PYP"])
        self.scan.assert_not_called()

    def test_duplicate_keeps_metadata_until_overwrite_is_requested(self) -> None:
        result = _create_event(self.payload)
        metadata_path = Path(result["event_folder"]) / "Data/metadata.json"
        original = metadata_path.read_bytes()
        changed = {**self.payload, "description": "Updated"}
        with self.assertRaisesRegex(ValueError, "already exists"):
            _create_event(changed)
        self.assertEqual(metadata_path.read_bytes(), original)

        result = _create_event({**changed, "allow_overwrite": True})
        self.assertTrue(result["already_existed"])
        self.assertEqual(json.loads(metadata_path.read_text())["description"], "Updated")
        self.scan.assert_not_called()


if __name__ == "__main__":
    unittest.main()
