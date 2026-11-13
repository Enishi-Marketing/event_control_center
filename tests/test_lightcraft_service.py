import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image, TiffImagePlugin

from config.config import AppConfig
from services.lightcraft_service import _find_cli
from services.project_service import ProjectService


class LightcraftIntegrationTests(unittest.TestCase):
    def test_project_import_links_raws_and_keeps_existing_edits(self):
        try:
            cli = _find_cli()
        except RuntimeError as exc:
            self.skipTest(str(exc))

        def write_dng(path: Path, value: int) -> None:
            tags = TiffImagePlugin.ImageFileDirectory_v2()
            for tag, data in {
                262: 32803, 50706: bytes((1, 4, 0, 0)), 50707: bytes((1, 1, 0, 0)),
                33421: (2, 2), 33422: bytes((0, 1, 1, 2)), 50714: 0, 50717: 4095,
                50708: "ECC Synthetic CFA",
            }.items():
                tags[tag] = data
            Image.new("I;16", (64, 64), value).save(path, format="TIFF", tiffinfo=tags)

        with tempfile.TemporaryDirectory() as temporary:
            event = Path(temporary).resolve() / "Example Event"
            photos = event / "Raw" / "Photos"
            photos.mkdir(parents=True)
            first, second = photos / "first.dng", photos / "second.DNG"
            write_dng(first, 1400)
            Image.new("RGB", (64, 64)).save(photos / "camera.jpg")
            service = ProjectService(lightroom_template_dir=AppConfig.BUNDLED_LIGHTROOM_TEMPLATE_DIR)

            result = service.create_projects(event, event.name, True, False)
            self.assertEqual(result.failures, [])
            catalog = Path(result.lightcraft_path)
            self.assertEqual(catalog.parent.parent, event / "Example Event Catalog")
            self.assertTrue((catalog.parent.parent / "Example Event Catalog.lrcat").is_file())
            before = first.read_bytes()
            edit = subprocess.run(
                [str(cli), "run", "--library", str(catalog), "--script", "-"],
                input='{"command":"library.select","params":{"ids":[1],"active":1}}\n'
                      '{"command":"photo.rate","params":{"rating":4}}\n',
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(edit.returncode, 0, edit.stdout + edit.stderr)

            write_dng(second, 2400)
            result = service.create_projects(event, event.name, True, False)
            self.assertEqual(result.failures, [])
            self.assertEqual(Path(result.lightcraft_path), catalog)
            records = json.loads(catalog.read_text())["catalog"]["photos"]
            self.assertEqual({p["source"]["path"] for p in records.values()}, {str(first), str(second)})
            self.assertEqual(records["1"]["rating"], 4)
            self.assertEqual(first.read_bytes(), before)
