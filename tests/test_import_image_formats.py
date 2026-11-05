import json
import shutil
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from PIL import Image
from pillow_heif import from_pillow

from services.importer import ImportService
from services.media_count_service import MediaCountService
from services.unedited_jpg_service import UneditedJpgService


class ImportImageFormatTests(unittest.TestCase):
    def test_scan_and_copy_new_formats_case_insensitively(self) -> None:
        extensions = ("heic", "heif", "png", "webp", "tif", "tiff", "gif", "bmp", "raw", "jpg", "cr3")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source" / "DCIM"
            source.mkdir(parents=True)
            originals: dict[str, bytes] = {}
            for extension in extensions:
                for index, suffix in enumerate((extension, extension.upper())):
                    name = f"photo-{index}.{suffix}"
                    originals[name] = f"original {name}".encode()
                    (source / name).write_bytes(originals[name])
            (source / "notes.txt").write_text("Not media", encoding="utf-8")
            service = ImportService()
            # This checks discovery and verified copying independently of decoding.
            with patch.object(service, "_with_session_thumbnails", side_effect=lambda sessions, failures: sessions):
                scan = service.scan_media(root / "source", 20)
            self.assertEqual(scan.photo_count, len(originals))
            self.assertEqual(scan.skipped_count, 1)
            self.assertEqual(scan.failures, ())
            self.assertEqual({item.path.name for item in scan.files}, set(originals))

            event = root / "event"
            result = service.import_media(list(scan.files), event, root / "source", Event())
            self.assertEqual(result.photos_imported, len(originals))
            self.assertEqual(result.failed, 0, result.failures)
            self.assertCountEqual(
                [path.read_bytes() for path in (event / "Raw" / "Photos").iterdir()],
                originals.values(),
            )
            self.assertEqual(len(UneditedJpgService().supported_photos(event / "Raw" / "Photos")), len(originals))
            for name, content in originals.items():
                self.assertEqual((source / name).read_bytes(), content)

    @unittest.skipUnless(shutil.which("sips"), "macOS sips is required")
    def test_real_images_have_previews_jpgs_and_media_counts(self) -> None:
        formats = {
            "heic": "HEIF", "heif": "HEIF", "png": "PNG", "webp": "WEBP",
            "tif": "TIFF", "tiff": "TIFF", "gif": "GIF", "bmp": "BMP",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for extension, image_format in formats.items():
                with self.subTest(extension=extension):
                    source = root / extension
                    source.mkdir()
                    photo = source / f"photo.{extension.upper()}"
                    image = Image.new("RGB", (120, 80), (70, 90, 110))
                    if image_format == "HEIF":
                        from_pillow(image).save(photo)
                    elif image_format in {"GIF", "TIFF"}:
                        image.save(photo, format=image_format, save_all=True,
                                   append_images=[Image.new("RGB", (120, 80), "red")])
                    else:
                        image.save(photo, format=image_format)
                    original = photo.read_bytes()
                    service = ImportService()
                    scan = service.scan_media(source, 20)
                    self.assertEqual(scan.photo_count, 1)
                    self.assertEqual(scan.skipped_count, 0)
                    self.assertIsNotNone(scan.sessions[0].start_thumbnail, scan.thumbnail_failures)
                    with Image.open(scan.sessions[0].start_thumbnail.path) as preview:
                        self.assertLessEqual(max(preview.size), 160)

                    event = root / f"event-{extension}"
                    metadata = event / "Data" / "metadata.json"
                    metadata.parent.mkdir(parents=True)
                    metadata.write_text(json.dumps({"photo_count": 0, "video_count": 0}), encoding="utf-8")
                    imported = service.import_media(list(scan.files), event, source, Event())
                    self.assertEqual(imported.photos_imported, 1)
                    self.assertEqual(imported.failed, 0, imported.failures)
                    copied = next((event / "Raw" / "Photos").iterdir())
                    self.assertEqual(copied.read_bytes(), original)
                    self.assertEqual(photo.read_bytes(), original)
                    jpgs = UneditedJpgService().generate_for_event(event)
                    self.assertEqual(jpgs.generated, 1, jpgs.failures)
                    with Image.open(event / "Unedited JPGs" / "Photos" / f"{copied.stem}.jpg") as jpg:
                        self.assertEqual(jpg.format, "JPEG")
                        self.assertLessEqual(max(jpg.size), 2500)
                        self.assertAlmostEqual(jpg.width / jpg.height, 1.5, places=2)
                    counts = MediaCountService().update_event_counts(event)
                    self.assertEqual(counts.photo_count, 1)
                    self.assertEqual(json.loads(metadata.read_text())["unedited_jpg_count"], 1)


if __name__ == "__main__":
    unittest.main()
