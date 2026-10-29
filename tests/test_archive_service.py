import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.archive_service import ArchiveService


class ArchiveServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.local = self.root / 'local'
        self.drive = self.root / 'drive'
        self.event = self.drive / '2026-27' / '2026.10.08 - Event'
        self.event.mkdir(parents=True)
        (self.event / 'photo.jpg').write_bytes(b'photo')
        self.destination = self.local / '2026-27' / self.event.name
        self.destination.parent.mkdir(parents=True)
        self.service = ArchiveService()

    def test_download_and_rearchive(self):
        self.destination.symlink_to(self.event, target_is_directory=True)
        result = self.service.download_event(self.event, self.local, self.drive)
        self.assertEqual(result, self.destination)
        self.assertFalse(result.is_symlink())
        self.assertEqual((result / 'photo.jpg').read_bytes(), b'photo')
        (result / 'local-only').write_text('local')
        archived = self.service.archive_event(result, self.drive)
        self.assertEqual(archived.status, 'moved')
        self.assertTrue(result.is_symlink())
        self.assertFalse((self.event / 'local-only').exists())
        self.assertEqual((self.event / 'photo.jpg').read_bytes(), b'photo')

    def test_copy_failure_keeps_shortcut(self):
        self.destination.symlink_to(self.event, target_is_directory=True)
        with patch('services.archive_service.shutil.copytree', side_effect=OSError('offline')):
            with self.assertRaises(OSError):
                self.service.download_event(self.event, self.local, self.drive)
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual(self.destination.resolve(), self.event)

    def test_download_rejects_existing_local_folder(self):
        self.destination.mkdir()
        with self.assertRaises(FileExistsError):
            self.service.download_event(self.event, self.local, self.drive)

    def test_rearchive_link_failure_restores_local_copy(self):
        self.destination.mkdir()
        (self.destination / 'local-only').write_text('keep')
        with patch.object(Path, 'symlink_to', side_effect=OSError('failed')):
            with self.assertRaises(OSError):
                self.service.archive_event(self.destination, self.drive)
        self.assertEqual((self.destination / 'local-only').read_text(), 'keep')

    def test_first_archive_moves_and_links(self):
        self.destination.mkdir()
        (self.destination / 'new.jpg').write_bytes(b'new')
        other_drive = self.root / 'other-drive'
        result = self.service.archive_event(self.destination, other_drive)
        self.assertEqual(result.status, 'moved')
        self.assertTrue(self.destination.is_symlink())
        self.assertEqual((result.destination / 'new.jpg').read_bytes(), b'new')

    def test_download_outside_drive_rejected(self):
        self.destination.mkdir()
        with self.assertRaises(ValueError):
            self.service.download_event(self.destination, self.local, self.drive)
