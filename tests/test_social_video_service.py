import json
import subprocess
import tempfile
import unittest
import sys
from datetime import datetime
from pathlib import Path
from threading import Event
from unittest.mock import patch

import cv2
from imageio_ffmpeg import get_ffmpeg_exe

from services.folder_service import FolderService
from services.importer import ImportService, MediaFile
from services.social_video_service import SocialVideoService


class SocialVideoTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.event = FolderService(self.root / "events").create_event_folders("2026.10.27", "Sports Day").event_folder
        self.source = self.root / "camera.mov"
        self.source.write_bytes(b"original video")
        self.service = SocialVideoService()

    def test_success_publishes_complete_copy_and_preserves_original(self) -> None:
        def encode(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
            output = Path(command[-1])
            output.write_bytes(b"encoded MP4")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        with patch("services.social_video_service.subprocess.run", side_effect=encode):
            self.assertTrue(self.service.create_copy(self.source, self.event))

        output = self.service.destination_for(self.source, self.event)
        self.assertEqual(output.read_bytes(), b"encoded MP4")
        self.assertEqual(output.stat().st_mtime_ns, self.source.stat().st_mtime_ns)
        self.assertEqual(self.source.read_bytes(), b"original video")
        self.assertEqual(list(output.parent.iterdir()), [output])

    def test_existing_copy_is_not_overwritten(self) -> None:
        output = self.service.destination_for(self.source, self.event)
        output.write_bytes(b"keep existing")
        with patch("services.social_video_service.subprocess.run") as run:
            self.assertFalse(self.service.create_copy(self.source, self.event))
            run.assert_not_called()
        self.assertEqual(output.read_bytes(), b"keep existing")

    def test_failed_conversion_leaves_no_partial_output(self) -> None:
        def fail(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
            Path(command[-1]).write_bytes(b"partial")
            return subprocess.CompletedProcess(command, 1, stdout="", stderr="Unsupported codec")

        with patch("services.social_video_service.subprocess.run", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "Unsupported codec"):
                self.service.create_copy(self.source, self.event)
        self.assertEqual(list((self.event / "Raw" / "Smaller Videos").iterdir()), [])
        self.assertEqual(self.source.read_bytes(), b"original video")

    def test_success_without_output_is_reported_as_failure(self) -> None:
        with patch("services.social_video_service.subprocess.run", return_value=subprocess.CompletedProcess([], 0)):
            with self.assertRaisesRegex(RuntimeError, "complete MP4"):
                self.service.create_copy(self.source, self.event)

    def test_import_conversion_failure_preserves_verified_video_and_counts(self) -> None:
        metadata = self.event / "Data" / "metadata.json"
        metadata.write_text(json.dumps({"photo_count": 0, "video_count": 0}), encoding="utf-8")
        media = MediaFile(self.source, "video", datetime.now(), self.source.stat().st_size)
        progress = []
        with patch.object(SocialVideoService, "create_copy", side_effect=RuntimeError("Unsupported codec")):
            summary = ImportService().import_media(
                [media], self.event, self.root, Event(), progress_callback=progress.append,
                event_name="Sports Day",
            )

        self.assertEqual(summary.videos_imported, 1)
        self.assertEqual(summary.failed, 0)
        self.assertEqual(summary.social_videos_failed, 1)
        self.assertEqual(summary.imported_sources, [self.source])
        self.assertEqual((self.event / "Raw" / "Videos" / "Sports Day clip 001.mov").read_bytes(), self.source.read_bytes())
        self.assertEqual(json.loads(metadata.read_text())["video_count"], 1)
        self.assertIn("Unsupported codec", (self.event / "Data" / "import.log").read_text())
        self.assertIn("Creating smaller video", [item.phase for item in progress])

    def test_import_only_converts_verified_videos(self) -> None:
        media = MediaFile(self.source, "video", datetime.now(), self.source.stat().st_size)
        importer = ImportService()
        with patch.object(importer.hash_service, "verify", return_value=False), patch.object(
            SocialVideoService, "create_copy"
        ) as convert:
            summary = importer.import_media([media], self.event, self.root, Event())
            convert.assert_not_called()
        self.assertEqual(summary.failed, 1)
        self.assertEqual(summary.videos_imported, 0)
        self.assertEqual(summary.imported_sources, [])

    def test_failed_rebuild_preserves_existing_staff_copy(self) -> None:
        output = self.service.destination_for(self.source, self.event)
        output.write_bytes(b"keep existing")
        with patch("services.social_video_service.subprocess.run", return_value=subprocess.CompletedProcess([], 1, stderr="Failed")):
            with self.assertRaisesRegex(RuntimeError, "Failed"):
                self.service.create_copy(self.source, self.event, replace_existing=True)
        self.assertEqual(output.read_bytes(), b"keep existing")

    def test_existing_event_regeneration_reports_sizes_and_skips_completed_copies(self) -> None:
        source = self.event / "Raw" / "Videos" / "camera.mov"
        source.parent.mkdir(parents=True)
        source.write_bytes(b"original large video")

        def encode(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess:
            Path(command[-1]).write_bytes(b"smaller")
            return subprocess.CompletedProcess(command, 0)

        with patch("services.social_video_service.subprocess.run", side_effect=encode):
            result = self.service.generate_for_event(self.event)
            self.assertEqual((result.generated, result.source_bytes, result.output_bytes), (1, 20, 7))
            self.assertEqual(self.service.generate_for_event(self.event).skipped, 1)
            self.assertEqual(self.service.generate_for_event(self.event, regenerate_all=True).generated, 1)
        self.assertEqual(source.read_bytes(), b"original large video")

    def test_same_stems_and_nested_sources_get_distinct_copies(self) -> None:
        raw = self.event / "Raw" / "Videos"
        destinations = {
            self.service.destination_for(raw / name, self.event)
            for name in ("camera.mov", "camera.mp4", "camera.mxf", "other/camera.mov")
        }
        self.assertEqual(len(destinations), 4)

    def test_stream_rebuilds_an_existing_event_and_returns_sizes(self) -> None:
        source = self.event / "Raw" / "Videos" / "camera.mp4"
        source.parent.mkdir(parents=True)
        subprocess.run(
            [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-f", "lavfi",
             "-i", "testsrc2=size=320x180:rate=24", "-t", "0.5", "-c:v", "libx264",
             "-preset", "ultrafast", "-crf", "0", str(source)],
            capture_output=True, check=True,
        )
        output = self.service.destination_for(source, self.event)
        output.write_bytes(b"old copy")
        request = {"command": "generate_social_videos_stream", "payload": {
            "event_folder": str(self.event), "regenerate_all": True,
        }}
        completed = subprocess.run(
            [sys.executable, "backend_bridge.py"], input=json.dumps(request), capture_output=True,
            text=True, check=True, cwd=Path(__file__).resolve().parents[1],
        )
        events = [json.loads(line) for line in completed.stdout.splitlines()]
        self.assertEqual(events[-1]["type"], "completed")
        result = events[-1]["result"]
        self.assertEqual(result["generated"], 1)
        self.assertEqual(result["source_bytes"], source.stat().st_size)
        self.assertEqual(result["output_bytes"], output.stat().st_size)
        self.assertLess(result["output_bytes"], result["source_bytes"])
        self.assertTrue(any(event.get("current_file") for event in events))

    def test_real_encoder_preserves_1080p_and_720p_compresses_and_keeps_audio(self) -> None:
        encoder = get_ffmpeg_exe()
        for width, height in [(1920, 1080), (1080, 1920), (1280, 720), (2160, 3840)]:
            with self.subTest(dimensions=(width, height)):
                source = self.root / f"sample-{width}x{height}.mp4"
                subprocess.run(
                    [encoder, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                     f"testsrc2=size={width}x{height}:rate=24", "-f", "lavfi", "-i",
                     "sine=frequency=440:sample_rate=48000", "-t", "0.5", "-c:v", "libx264",
                     "-preset", "ultrafast", "-crf", "0", "-c:a", "aac", str(source)],
                    capture_output=True, check=True,
                )
                original = source.read_bytes()
                self.assertTrue(self.service.create_copy(source, self.event))
                output = self.service.destination_for(source, self.event)
                capture = cv2.VideoCapture(str(output))
                dimensions = (int(capture.get(cv2.CAP_PROP_FRAME_WIDTH)), int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
                self.assertTrue(capture.read()[0])
                capture.release()
                self.assertEqual(dimensions, (1080, 1920) if height == 3840 else (width, height))
                self.assertLess(output.stat().st_size, source.stat().st_size / 2)
                self.assertEqual(source.read_bytes(), original)
                probe = subprocess.run([encoder, "-hide_banner", "-i", str(output)], capture_output=True, text=True)
                self.assertIn("Audio: aac", probe.stderr)
                self.assertIn("Video: h264", probe.stderr)


if __name__ == "__main__":
    unittest.main()
