import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from threading import Event
from unittest.mock import patch

from services.import_check_service import ImportCheckService
from services.importer import ImportService
from services.social_video_service import SocialVideoService
from services.source_cleanup_service import SourceCleanupService
from services.unedited_jpg_service import UneditedJpgService, UneditedJpgSummary


class ImportSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "card"
        self.source.mkdir()
        self.event = self.root / "2026.11.05 - Test"
        (self.event / "Data").mkdir(parents=True)
        self.metadata = self.event / "Data" / "metadata.json"
        self.metadata.write_text(json.dumps({"photo_count": 0, "video_count": 0, "description": "Keep this"}))

    def import_files(self, names: tuple[str, ...], selected: int | None = None):
        for name in names:
            (self.source / name).write_bytes(b"original " + name.encode())
        service = ImportService()
        with patch.object(service, "_with_session_thumbnails", side_effect=lambda sessions, failures: sessions):
            scan = service.scan_media(self.source, 20)
        files = list(scan.files) if selected is None else list(scan.files)[:selected]
        with patch.object(SocialVideoService, "create_copy", side_effect=RuntimeError("Unsupported codec")):
            summary = service.import_media(files, self.event, self.source, Event())
        return scan, summary

    def ready(self, names: tuple[str, ...] = ("one.HEIC", "two.PNG")):
        scan, summary = self.import_files(names)
        for record in summary.imported_files:
            output = self.event / "Unedited JPGs" / "Photos" / f"{record.destination.stem}.jpg"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"JPEG copy")
        check = ImportCheckService().finalize(scan, len(scan.files), summary, UneditedJpgSummary(), self.event)
        self.assertTrue(check["cleanup_allowed"], check["warnings"])
        return scan, summary, check

    def cleanup(self, summary, check):
        service = SourceCleanupService()
        with patch.object(service, "ejectable_mount", return_value=self.source), patch.object(
            service, "_eject", return_value=(True, "Ejected")
        ) as eject:
            result = service.cleanup_imported_files(summary.imported_sources, self.source, Path(check["report_path"]))
        return result, eject

    def test_success_counts_and_cleanup_reverify_originals(self):
        scan, summary, check = self.ready()
        self.assertEqual((check["source_file_count"], check["verified_original_count"], check["raw_photo_count"], check["jpg_count"]), (2, 2, 2, 2))
        report = json.loads(Path(check["report_path"]).read_text())
        self.assertEqual(len(report["records"]), 2)
        self.assertIn("Count check:", (self.event / "Data" / "import.log").read_text())
        result, eject = self.cleanup(summary, check)
        self.assertEqual(result.deleted, 2)
        self.assertTrue(result.ejected)
        eject.assert_called_once()
        self.assertTrue(all(not item.path.exists() for item in scan.files))
        self.assertTrue(all(item.destination.is_file() for item in summary.imported_files))
        self.assertEqual(json.loads(self.metadata.read_text())["description"], "Keep this")

    def test_unconvertible_photos_stay_in_raw_and_block_cleanup(self):
        scan, summary = self.import_files(("photo.PSD", "camera.RAW"))
        with patch.object(UneditedJpgService, "_create_jpeg", side_effect=RuntimeError("Unsupported image")):
            jpgs = UneditedJpgService().generate_for_event(self.event)
        check = ImportCheckService().finalize(scan, 2, summary, jpgs, self.event)
        self.assertEqual((check["raw_photo_count"], check["jpg_count"]), (2, 0))
        self.assertEqual(jpgs.failed, 2)
        report = json.loads(Path(check["report_path"]).read_text())
        self.assertEqual(len(report["missing_jpgs"]), 2)
        self.assertIn("Unsupported image", report["jpg_failures"][0])
        result, eject = self.cleanup(summary, check)
        self.assertEqual(result.deleted, 0)
        eject.assert_not_called()
        for item in summary.imported_files:
            self.assertEqual(item.source.read_bytes(), item.destination.read_bytes())

    def test_unconvertible_video_stays_in_raw_and_is_counted(self):
        scan, summary = self.import_files(("video.WEBM",))
        check = ImportCheckService().finalize(scan, 1, summary, UneditedJpgSummary(), self.event)
        self.assertEqual((check["raw_video_count"], check["smaller_video_count"]), (1, 0))
        self.assertFalse(check["cleanup_allowed"])
        self.assertEqual(summary.imported_files[0].destination.parent, self.event / "Raw" / "Videos")
        self.assertTrue(summary.imported_files[0].source.exists())

    def test_unrecognized_files_and_partial_session_selection_are_reported(self):
        scan, summary = self.import_files(("one.JPG", "two.JPG", "unknown.xyz"), selected=1)
        check = ImportCheckService().finalize(scan, 1, summary, UneditedJpgSummary(), self.event)
        self.assertEqual((check["source_file_count"], check["unimported_count"]), (3, 2))
        report = json.loads(Path(check["report_path"]).read_text())
        self.assertIn(str(self.source / "unknown.xyz"), report["unrecognized_files"])
        self.assertEqual(len(report["unimported_files"]), 2)
        self.assertFalse(check["cleanup_allowed"])

    def test_scan_read_failures_disable_cleanup_even_with_matching_counts(self):
        scan, summary, _ = self.ready()
        scan = replace(scan, failures=("Unreadable folder",))
        check = ImportCheckService().finalize(scan, 2, summary, UneditedJpgSummary(), self.event)
        self.assertFalse(check["cleanup_allowed"])
        self.assertTrue(any("read issue" in warning for warning in check["warnings"]))

    def test_changed_source_during_import_is_counted_and_warned(self):
        scan, summary, _ = self.ready()
        (self.source / "new.HEIC").write_bytes(b"new photo")
        check = ImportCheckService().finalize(scan, 2, summary, UneditedJpgSummary(), self.event)
        self.assertEqual((check["source_file_count"], check["unimported_count"]), (3, 1))
        self.assertFalse(check["cleanup_allowed"])

    def test_missing_original_warns_even_when_conversion_exists(self):
        scan, summary, _ = self.ready()
        summary.imported_files[0].destination.unlink()
        check = ImportCheckService().finalize(scan, 2, summary, UneditedJpgSummary(), self.event)
        self.assertEqual(check["verified_original_count"], 1)
        self.assertFalse(check["cleanup_allowed"])

    def test_archive_corruption_blocks_entire_cleanup_before_first_delete(self):
        _, summary, check = self.ready()
        damaged = summary.imported_files[-1].destination
        damaged.write_bytes(b"x" * damaged.stat().st_size)
        result, eject = self.cleanup(summary, check)
        self.assertEqual(result.deleted, 0)
        self.assertTrue(all(p.exists() for p in summary.imported_sources))
        self.assertIn("hashes", result.delete_failures[0])
        eject.assert_not_called()

    def test_source_changed_after_import_is_never_deleted(self):
        _, summary, check = self.ready()
        source = summary.imported_sources[-1]
        source.write_bytes(b"x" * source.stat().st_size)
        result, _ = self.cleanup(summary, check)
        self.assertEqual(result.deleted, 0)
        self.assertTrue(all(p.exists() for p in summary.imported_sources))

    def test_source_file_added_after_report_blocks_cleanup(self):
        _, summary, check = self.ready()
        (self.source / "unexpected.HEIC").write_bytes(b"do not lose")
        result, _ = self.cleanup(summary, check)
        self.assertEqual(result.deleted, 0)
        self.assertTrue(all(p.exists() for p in summary.imported_sources))

    def test_removed_conversion_blocks_cleanup(self):
        _, summary, check = self.ready()
        next((self.event / "Unedited JPGs" / "Photos").iterdir()).unlink()
        result, _ = self.cleanup(summary, check)
        self.assertEqual(result.deleted, 0)
        self.assertTrue(all(p.exists() for p in summary.imported_sources))

    def test_finder_bookkeeping_does_not_hide_real_files_or_block_cleanup(self):
        (self.source / ".DS_Store").write_bytes(b"Finder")
        (self.source / "._one.HEIC").write_bytes(b"Finder resource fork")
        _, summary, check = self.ready(("one.HEIC",))
        # AppleDouble resource forks have photo extensions but are not photos.
        self.assertEqual(check["source_file_count"], 1)
        self.assertEqual(check["verified_original_count"], 1)
        result, _ = self.cleanup(summary, check)
        self.assertEqual(result.deleted, 1)
        self.assertTrue((self.source / ".DS_Store").exists())

    def test_partial_failed_copy_is_removed_and_source_is_kept(self):
        source = self.source / "broken.HEIC"
        source.write_bytes(b"keep original")
        service = ImportService()
        files = [service._build_media_file(source, "photo", [])]

        def fail_copy(media, destination, *_args):
            destination.write_bytes(b"partial")
            raise OSError("Drive disconnected")

        with patch.object(service, "_copy_with_progress", side_effect=fail_copy):
            summary = service.import_media(files, self.event, self.source, Event())
        self.assertEqual(summary.failed, 1)
        self.assertEqual(list((self.event / "Raw" / "Photos").iterdir()), [])
        self.assertEqual(source.read_bytes(), b"keep original")

    def test_converter_timeout_is_reported_without_losing_raw(self):
        scan, summary = self.import_files(("photo.HEIC",))
        with patch("services.unedited_jpg_service.subprocess.run", side_effect=subprocess.TimeoutExpired("sips", 120)):
            jpgs = UneditedJpgService().generate_for_event(self.event)
        self.assertEqual(jpgs.failed, 1)
        check = ImportCheckService().finalize(scan, 1, summary, jpgs, self.event)
        self.assertFalse(check["cleanup_allowed"])
        self.assertTrue(summary.imported_files[0].destination.is_file())


if __name__ == "__main__":
    unittest.main()
