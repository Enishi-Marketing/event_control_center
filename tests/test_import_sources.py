import json
import plistlib
import tempfile
import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch

from backend_bridge import _inspect_existing_event, _validate_import_paths
from services.drive_detector import DriveDetector


class ImportSourceTests(unittest.TestCase):
    def test_existing_event_can_be_selected_without_changing_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "2026.09.29 - Arts Day"
            metadata_path = event / "Data" / "metadata.json"
            metadata_path.parent.mkdir(parents=True)
            metadata = {"event_name": "Arts Day", "date": "2026.09.29", "description": "Keep me"}
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            result = _inspect_existing_event({"event_folder": str(event)})

            self.assertEqual(result["event_folder"], str(event.resolve()))
            self.assertEqual(result["event_name"], "Arts Day")
            self.assertEqual(result["event_date"], "2026.09.29")
            self.assertEqual(json.loads(metadata_path.read_text(encoding="utf-8")), metadata)

    def test_import_rejects_scanning_its_own_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            event = Path(directory) / "2026.09.29 - Arts Day"
            photos = event / "Raw" / "Photos"
            photos.mkdir(parents=True)

            with self.assertRaisesRegex(ValueError, "original media"):
                _validate_import_paths(event, event)
            with self.assertRaisesRegex(ValueError, "output folder"):
                _validate_import_paths(photos, event)

            unimported = event / "To Import"
            unimported.mkdir()
            _validate_import_paths(unimported, event)

    def test_disk_images_are_not_detected_as_cards(self) -> None:
        detector = DriveDetector()

        def disk_info(bus: str, writable: bool) -> CompletedProcess[bytes]:
            data = plistlib.dumps({
                "Ejectable": True,
                "WritableVolume": writable,
                "Internal": False,
                "BusProtocol": bus,
            })
            return CompletedProcess(["diskutil"], 0, stdout=data)

        with patch("services.drive_detector.platform.system", return_value="Darwin"), patch(
            "services.drive_detector.subprocess.run", return_value=disk_info("Disk Image", False)
        ):
            self.assertFalse(detector._is_importable_mount(Path("/Volumes"), Path("/Volumes/Installer")))

        with patch("services.drive_detector.platform.system", return_value="Darwin"), patch(
            "services.drive_detector.subprocess.run", return_value=disk_info("USB", True)
        ):
            self.assertTrue(detector._is_importable_mount(Path("/Volumes"), Path("/Volumes/Camera Card")))


if __name__ == "__main__":
    unittest.main()
