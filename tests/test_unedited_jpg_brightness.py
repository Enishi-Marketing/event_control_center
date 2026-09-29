import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageStat

from services.importer import ImportService
from services.unedited_jpg_service import UneditedJpgService


@unittest.skipUnless(shutil.which("sips"), "macOS sips is required")
class UneditedJpgBrightnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.event = Path(self.temporary.name)
        self.photos = self.event / "Raw" / "Photos"
        self.photos.mkdir(parents=True)
        self.service = UneditedJpgService()

    def _jpeg(self, name: str, value: int, size: tuple[int, int] = (120, 80)) -> Path:
        path = self.photos / name
        image = Image.new("RGB", size, (value, value, value))
        exif = Image.Exif()
        exif[274] = 6
        image.save(path, quality=95, exif=exif)
        return path

    def _mean(self, path: Path) -> float:
        with Image.open(path) as image:
            return ImageStat.Stat(image.convert("L")).mean[0]

    def test_dark_jpg_is_brightened_without_changing_original(self) -> None:
        source = self._jpeg("dark.jpg", 85)
        original = hashlib.sha256(source.read_bytes()).digest()

        result = self.service.generate_for_event(self.event)
        output = self.event / "Unedited JPGs" / "Photos" / "dark.jpg"

        self.assertEqual(result.generated, 1, result.failures)
        self.assertGreater(self._mean(output), self._mean(source) + 10)
        self.assertEqual(hashlib.sha256(source.read_bytes()).digest(), original)
        with Image.open(output) as image:
            self.assertEqual(image.size, (120, 80))
            self.assertEqual(image.getexif()[274], 6)

        unchanged = output.read_bytes()
        again = self.service.generate_for_event(self.event)
        self.assertEqual(again.skipped, 1)
        self.assertEqual(output.read_bytes(), unchanged)

    def test_bright_jpg_stays_byte_identical(self) -> None:
        source = self._jpeg("bright.jpg", 205)
        result = self.service.generate_for_event(self.event)
        output = self.event / "Unedited JPGs" / "Photos" / "bright.jpg"
        self.assertEqual(result.generated, 1, result.failures)
        self.assertEqual(output.read_bytes(), source.read_bytes())

    def test_regenerate_all_brightens_existing_jpg(self) -> None:
        source = self._jpeg("old.jpg", 80)
        output = self.event / "Unedited JPGs" / "Photos" / "old.jpg"
        output.parent.mkdir(parents=True)
        shutil.copy2(source, output)

        self.assertEqual(self.service.generate_for_event(self.event).skipped, 1)
        self.assertEqual(output.read_bytes(), source.read_bytes())

        result = self.service.generate_for_event(self.event, regenerate_all=True)
        self.assertEqual(result.generated, 1, result.failures)
        self.assertGreater(self._mean(output), self._mean(source) + 10)

    def test_extra_brightness_changes_regenerated_jpg_without_changing_source(self) -> None:
        source = self._jpeg("adjust.jpg", 85)
        original = source.read_bytes()
        output = self.event / "Unedited JPGs" / "Photos" / "adjust.jpg"

        self.service.generate_for_event(self.event)
        automatic_mean = self._mean(output)
        result = self.service.generate_for_event(
            self.event, regenerate_all=True, brightness=100
        )

        self.assertEqual(result.generated, 1, result.failures)
        self.assertGreater(self._mean(output), automatic_mean + 40)
        self.assertEqual(source.read_bytes(), original)

    def test_sd_card_thumbnail_includes_automatic_lift(self) -> None:
        source = self._jpeg("preview.jpg", 85)
        scan = ImportService().scan_media(self.photos, 20)
        thumbnail = scan.sessions[0].start_thumbnail

        self.assertIsNotNone(thumbnail, scan.thumbnail_failures)
        self.assertGreater(self._mean(thumbnail.path), self._mean(source) + 10)

    def test_regeneration_stream_reports_each_image_and_completion(self) -> None:
        self._jpeg("one.jpg", 85)
        self._jpeg("two.jpg", 90)
        request = {
            "command": "generate_jpgs_stream",
            "payload": {
                "event_folder": str(self.event),
                "regenerate_all": True,
                "brightness": 50,
            },
        }
        process = subprocess.run(
            [sys.executable, "backend_bridge.py"],
            input=json.dumps(request),
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[1],
        )
        events = [json.loads(line) for line in process.stdout.splitlines()]

        self.assertEqual(events[-1]["type"], "completed")
        self.assertEqual(events[-1]["result"]["generated"], 2)
        self.assertEqual(
            [Path(event["current_file"]).name for event in events if event.get("current_file")],
            ["one.jpg", "two.jpg"],
        )
        self.assertEqual(events[-2]["current"], 2)
        self.assertEqual(events[-2]["total"], 2)

    def test_large_jpg_is_resized_and_brightened(self) -> None:
        source = self._jpeg("large.jpg", 85, (2600, 100))
        result = self.service.generate_for_event(self.event)
        output = self.event / "Unedited JPGs" / "Photos" / "large.jpg"
        self.assertEqual(result.generated, 1, result.failures)
        with Image.open(output) as image:
            self.assertLessEqual(max(image.size), 2500)
        self.assertGreater(self._mean(output), self._mean(source) + 10)


if __name__ == "__main__":
    unittest.main()
