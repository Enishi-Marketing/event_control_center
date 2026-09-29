from pathlib import Path
from subprocess import CompletedProcess
import tempfile
import unittest
from unittest.mock import patch

from services.source_cleanup_service import SourceCleanupService


class SourceCleanupServiceTests(unittest.TestCase):
    def test_nonremovable_folder_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            photo = source / "photo.jpg"
            photo.write_bytes(b"media")
            service = SourceCleanupService()

            with patch.object(service, "ejectable_mount", return_value=None):
                result = service.cleanup_imported_files([photo], source)

            self.assertTrue(photo.exists())
            self.assertEqual(result.deleted, 0)
            self.assertFalse(result.ejected)
            self.assertIn("no files were deleted", result.eject_message)

    def test_cleanup_deletes_only_verified_files_and_ejects_their_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "card"
            source.mkdir()
            verified = source / "DCIM" / "IMG_0001.CR3"
            verified.parent.mkdir()
            verified.write_bytes(b"media")
            outside = root / "do-not-delete.CR3"
            outside.write_bytes(b"media")

            service = SourceCleanupService()
            with patch.object(service, "ejectable_mount", return_value=source), patch.object(
                service, "_eject", return_value=(True, "Ejected card")
            ):
                result = service.cleanup_imported_files([verified, outside], source)

            self.assertFalse(verified.exists())
            self.assertTrue(outside.exists())
            self.assertEqual(result.deleted, 1)
            self.assertTrue(result.ejected)
            self.assertEqual(result.delete_failures, [f"{outside}: not inside source"])

    def test_eject_uses_diskutil_on_macos(self):
        service = SourceCleanupService()
        with patch("services.source_cleanup_service.platform.system", return_value="Darwin"), patch(
            "services.source_cleanup_service.subprocess.run",
            return_value=CompletedProcess(
                ["diskutil", "eject", "/Volumes/Camera Card"],
                0,
                stdout="Disk ejected\n",
                stderr="",
            ),
        ) as run:
            ejected, message = service._eject(Path("/Volumes/Camera Card"))

        self.assertTrue(ejected)
        self.assertEqual(message, "Disk ejected")
        self.assertEqual(
            run.call_args.args[0], ["diskutil", "eject", "/Volumes/Camera Card"]
        )
