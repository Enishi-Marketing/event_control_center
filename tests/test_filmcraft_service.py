"""Disposable projects validated/rendered by FilmCraft's released command engine."""

import copy
import fcntl
import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from imageio_ffmpeg import get_ffmpeg_exe
from PIL import Image, ImageChops
from pillow_heif import from_pillow

from services.filmcraft_client import FilmcraftClient, find_filmcraft_cli
from services.filmcraft_media import parse_capture_time, video_rotation
from services.filmcraft_service import FilmcraftService, PROFILES, TICKS, fit_scale
from services.project_service import ProjectService
from services.social_video_service import SocialVideoService


class FilmcraftMathTests(unittest.TestCase):
    def test_contain_scaling_never_crops_or_upscales(self):
        for source, target, expected in [
            ((3840, 2160), (1920, 1080), 50), ((3840, 2160), (1080, 1920), 28.125),
            ((2160, 3840), (1080, 1920), 50), ((3840, 2160), (1080, 1080), 28.125),
            ((800, 600), (1920, 1080), 100), ((720, 1280), (1080, 1920), 100),
        ]:
            with self.subTest(source=source, target=target):
                scale = fit_scale(*source, *target)
                self.assertAlmostEqual(scale, expected)
                self.assertLessEqual(scale, 100)
                self.assertLessEqual(source[0] * scale / 100, target[0])
                self.assertLessEqual(source[1] * scale / 100, target[1])

    def test_invalid_dimensions_are_refused(self):
        with self.assertRaises(ValueError):
            fit_scale(0, 600, 1080, 1920)

    def test_capture_time_offsets_and_corrupt_metadata(self):
        a = parse_capture_time("2026:11:05 10:00:00", timezone.utc, "+09:00")
        b = parse_capture_time("2026-11-05T01:00:00Z", timezone.utc)
        self.assertEqual(a, b)
        for value in ("bad", "0000:00:00 00:00:00", "1904-01-01T00:00:00Z", "2026-99-99"):
            self.assertIsNone(parse_capture_time(value, timezone.utc))


class FilmcraftIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.client = FilmcraftClient(find_filmcraft_cli())
        except RuntimeError as exc:
            raise unittest.SkipTest(str(exc))
        temporary = tempfile.TemporaryDirectory(prefix="ecc-filmcraft-fixtures-")
        cls.addClassCleanup(temporary.cleanup)
        cls.fixtures = Path(temporary.name)
        cls.video("landscape.mp4", 640, 360, "30000/1001")
        cls.video("portrait.mp4", 180, 320, "30")
        cls.video("4k.mp4", 3840, 2160, "30", duration="0.12")
        cls.video("wrong.mp4", 640, 360, "30000/1001", color="green")
        cls.video("two-audio.mp4", 320, 180, "30", audio=2)
        subprocess.run([get_ffmpeg_exe(), "-y", "-v", "error", "-display_rotation", "90", "-i",
                        str(cls.fixtures / "landscape.mp4"), "-c", "copy", str(cls.fixtures / "rotated.mp4")], check=True)
        cls.video("anamorphic.mp4", 1280, 720, "30", filters="setsar=4/3")
        image = Image.new("RGB", (800, 600), "red")
        exif = Image.Exif(); exif[36867] = "2026:11:05 10:02:30"; exif[36881] = "+09:00"
        image.save(cls.fixtures / "photo.jpg", exif=exif)
        image = Image.new("RGB", (120, 80), "green")
        exif = Image.Exif(); exif[274] = 6
        image.save(cls.fixtures / "oriented.jpg", exif=exif)
        from_pillow(Image.new("RGB", (160, 120), "yellow")).save(cls.fixtures / "photo.HEIC")

    @classmethod
    def video(cls, name, width, height, rate, duration="0.6", color="blue", audio=1, filters=None):
        command = [get_ffmpeg_exe(), "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c={color}:s={width}x{height}:r={rate}"]
        for index in range(audio):
            command += ["-f", "lavfi", "-i", f"sine=frequency={440 + index*440}:sample_rate=48000"]
        command += ["-map", "0:v:0"]
        for index in range(audio):
            command += ["-map", f"{index+1}:a:0"]
        if filters:
            command += ["-vf", filters]
        command += ["-t", duration, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                    "-metadata", "creation_time=2026-11-05T01:01:15Z", str(cls.fixtures / name)]
        subprocess.run(command, check=True, capture_output=True, timeout=30)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="ecc-filmcraft-test-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.event = self.root / "Test Event"
        for folder in ("Data", "Raw/Photos", "Raw/Videos"):
            (self.event / folder).mkdir(parents=True)
        (self.event / "Data" / "metadata.json").write_text(json.dumps({"event_name": "Test Event", "capture_timezone": "Asia/Tokyo"}))
        self.projects = ProjectService()
        self.project = self.projects.filmcraft_project_path(self.event, "Test Event")
        self.service = FilmcraftService(self.client)

    def media(self, name):
        category = "Videos" if name.endswith("mp4") else "Photos"
        path = self.event / "Raw" / category / name
        shutil.copy2(self.fixtures / name, path)
        return path

    def prepare(self, *, proxies=True, expected_proxy_failures=0):
        if proxies:
            result = SocialVideoService().generate_for_event(self.event)
            self.assertEqual(result.failed, expected_proxy_failures, result.failures)
        created, _ = self.projects.create_filmcraft_project(self.event, "Test Event")
        result = self.service.prepare(self.event, self.project, newly_created=created)
        self.assertTrue(Path(result.project_path).is_file())
        return result

    def document(self, result):
        return json.loads(Path(result.project_path).read_text())

    def render(self, result, sequence_id=None):
        path = Path(result.project_path)
        if sequence_id is not None:
            # Select a sequence in a disposable rendering copy, not the prepared
            # document and never the user's open FilmCraft session.
            doc = self.document(result)
            doc["view"]["active_sequence"] = sequence_id
            path = path.with_name("disposable-render.fcproj")
            path.write_text(json.dumps(doc))
        image = self.root / "frame.png"
        completed = subprocess.run([str(self.client.executable), "--project", str(path), "--data-dir", str(self.root / "cli-data"),
                                    "render", "--seconds", "0.1", "--out", str(image)], capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return Image.open(image)

    def test_mixed_event_has_native_media_proxies_and_three_video_only_timelines(self):
        for name in ("landscape.mp4", "portrait.mp4", "photo.jpg", "photo.HEIC"):
            self.media(name)
        originals = {p: hashlib.sha256(p.read_bytes()).digest() for p in (self.event / "Raw").rglob("*") if p.is_file()}
        result = self.prepare()
        self.assertEqual(result.failures, [])
        self.assertEqual(result.proxy_problems, [])
        self.assertEqual((result.videos, result.photos, result.proxies_linked, result.timelines_created), (2, 2, 2, 3))
        self.assertEqual(result.intermediate_photos, 1)
        doc = self.document(result)
        media = {int(k): v for k, v in doc["project"]["items"].items() if "Media" in v["kind"]}
        self.assertEqual(len(media), 4)
        sequences = {v["name"]: v["kind"]["Sequence"] for v in doc["project"]["items"].values() if "Sequence" in v["kind"]}
        self.assertEqual(set(sequences), {p[0] for p in PROFILES})
        videos = [key for key, item in media.items() if item["metadata"]["Original File"].startswith("Raw/Videos/")]
        expected_order = sorted(videos, key=lambda k: (media[k]["metadata"]["Capture Time"], media[k]["name"].casefold(), media[k]["metadata"]["Original File"]))
        for name, width, height in PROFILES:
            sequence = sequences[name]
            self.assertEqual((sequence["settings"]["width"], sequence["settings"]["height"]), (width, height))
            self.assertEqual(sequence["settings"]["frame_rate"], {"num": 30, "den": 1})
            clips = sequence["video_tracks"][0]["items"]
            self.assertEqual([c["item"] for c in clips], expected_order)
            cursor = 0
            for clip in clips:
                source = media[clip["item"]]["kind"]["Media"]
                duration = source["info"]["duration"]
                self.assertEqual((clip["start"], clip["duration"], clip["source_in"], clip["speed"]), (cursor, duration, 0, 1))
                cursor += duration
            for audio in sequence["audio_tracks"][0]["items"]:
                video = next(c for c in clips if c["item"] == audio["item"])
                self.assertEqual((audio["start"], audio["duration"], audio["link"]), (video["start"], video["duration"], video["link"]))
        for item in media.values():
            native = item["kind"]["Media"]
            self.assertNotIn("Smaller Videos", native["media"]["File"]["path"])
            self.assertFalse(Path(native["media"]["File"]["path"]).is_absolute())
        self.client.validate(Path(result.project_path), self.root / "cli-data")
        for path, digest in originals.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).digest(), digest)

    def test_photo_only_event_keeps_photo_in_library_and_timelines_empty(self):
        self.media("photo.jpg")
        result = self.prepare()
        self.assertEqual(result.failures, [])
        self.assertEqual((result.photos, result.videos, result.timelines_created), (1, 0, 3))
        items = self.document(result)["project"]["items"].values()
        self.assertTrue(any(item["name"] == "photo.jpg" and "Media" in item["kind"] for item in items))
        for sequence in (item["kind"]["Sequence"] for item in items if "Sequence" in item["kind"]):
            self.assertFalse(any(track["items"] for track in sequence["video_tracks"] + sequence["audio_tracks"]))

    def test_legacy_project_is_refreshed_alongside_premiere(self):
        self.media("landscape.mp4")
        self.media("photo.jpg")
        legacy = self.event / self.project.stem / self.project.name
        legacy.parent.mkdir()
        shutil.copy2(self.projects.filmcraft_template, legacy)
        original = self.service.prepare(self.event, legacy, newly_created=True)
        self.assertEqual(original.failures, [])
        before = legacy.read_bytes()

        self.assertEqual(self.projects.create_filmcraft_project(self.event, "Test Event"), (False, True))
        refreshed = self.service.prepare(self.event, self.project)
        self.assertEqual(refreshed.failures, [])
        project = Path(refreshed.project_path)
        self.assertEqual(project.parent, self.project.parent.resolve())
        self.assertEqual(legacy.read_bytes(), before)
        for item in self.document(refreshed)["project"]["items"].values():
            if "Media" in item["kind"]:
                ref = item["kind"]["Media"]["media"]["File"]["path"]
                self.assertTrue((project.parent / ref).is_file())
        self.assertTrue(self.service.prepare(self.event, self.project).unchanged)

    def test_four_k_video_uses_original_dimensions_for_fit(self):
        self.media("4k.mp4")
        result = self.prepare()
        self.assertEqual(result.proxy_problems, [])
        for item in self.document(result)["project"]["items"].values():
            if "Sequence" not in item["kind"]:
                continue
            clip = item["kind"]["Sequence"]["video_tracks"][0]["items"][0]
            motion = next(e for e in clip["effects"] if e["effect"] == "motion")
            expected = 50 if item["name"] == "YouTube - 16x9" else 28.125
            self.assertAlmostEqual(motion["params"]["scale"]["value"]["Float"], expected)

    def test_rotation_metadata_and_proxy_orientation_are_preserved(self):
        path = self.media("rotated.mp4")
        self.assertEqual(abs(video_rotation(path)), 90)
        result = self.prepare()
        self.assertEqual(result.proxy_problems, [])
        proxy = SocialVideoService.destination_for(path, self.event)
        self.assertEqual(video_rotation(path), video_rotation(proxy))
        doc = self.document(result)
        sequence = next(v for v in doc["project"]["items"].values() if v["name"] == "Vertical - 9x16")
        with self.render(result, sequence["id"]) as image:
            rgb = image.convert("RGB")
            bounds = ImageChops.difference(rgb, Image.new("RGB", rgb.size)).getbbox()
            self.assertAlmostEqual((bounds[2] - bounds[0]) / (bounds[3] - bounds[1]), 360/640, delta=0.01)

    def test_exif_orientation_and_anamorphic_display_aspect(self):
        self.media("oriented.jpg")
        self.media("anamorphic.mp4")
        result = self.prepare()
        self.assertEqual(result.failures, [])
        doc = self.document(result)
        photo = next(v for v in doc["project"]["items"].values() if v.get("name") == "oriented.jpg")
        self.assertEqual((photo["kind"]["Media"]["info"]["video"]["width"], photo["kind"]["Media"]["info"]["video"]["height"]), (80, 120))
        square = next(v["kind"]["Sequence"] for v in doc["project"]["items"].values() if v["name"] == "Square - 1x1")
        clip = next(c for c in square["video_tracks"][0]["items"] if c["name"] == "anamorphic.mp4")
        motion = next(e for e in clip["effects"] if e["effect"] == "motion")
        self.assertAlmostEqual(motion["params"]["scale"]["value"]["Float"], 1080/(1280*4/3)*100)

    def test_missing_proxy_preserves_original_and_assembles_all_timelines(self):
        self.media("landscape.mp4")
        result = self.prepare(proxies=False)
        self.assertEqual(result.failures, [])
        self.assertEqual((result.videos, result.proxies_linked, len(result.proxy_problems), result.timelines_created), (1, 0, 1, 3))
        native = next(v["kind"]["Media"] for v in self.document(result)["project"]["items"].values() if "Media" in v["kind"])
        self.assertIsNone(native["proxy"])
        self.assertIn("Raw/Videos", native["media"]["File"]["path"])

    def test_wrong_legacy_proxy_is_rejected_even_when_rate_and_duration_match(self):
        path = self.media("landscape.mp4")
        proxy = SocialVideoService.destination_for(path, self.event)
        proxy.parent.mkdir(parents=True)
        shutil.copy2(self.fixtures / "wrong.mp4", proxy)
        result = self.prepare(proxies=False)
        self.assertEqual(result.proxies_linked, 0)
        self.assertTrue(any("picture does not match" in problem for problem in result.proxy_problems), result.proxy_problems)

    def test_good_legacy_proxy_is_checked_and_backfilled_without_reencoding(self):
        path = self.media("landscape.mp4")
        SocialVideoService().generate_for_event(self.event)
        manifest = self.event / "Data" / "smaller_video_manifest.json"
        manifest.unlink()
        proxy = SocialVideoService.destination_for(path, self.event)
        before = hashlib.sha256(proxy.read_bytes()).digest()
        result = self.prepare(proxies=False)
        self.assertEqual(result.proxy_problems, [])
        self.assertEqual(result.proxies_linked, 1)
        self.assertTrue(manifest.exists())
        self.assertEqual(hashlib.sha256(proxy.read_bytes()).digest(), before)
        self.assertTrue(self.service.prepare(self.event, self.project).unchanged)

    def test_duration_mismatch_never_attaches_proxy(self):
        path = self.media("4k.mp4")
        proxy = SocialVideoService.destination_for(path, self.event)
        proxy.parent.mkdir(parents=True)
        shutil.copy2(self.fixtures / "portrait.mp4", proxy)
        result = self.prepare(proxies=False)
        self.assertEqual(result.proxies_linked, 0)
        self.assertTrue(any("duration" in problem for problem in result.proxy_problems))

    def test_repeated_preparation_does_not_write_or_duplicate_media(self):
        self.media("landscape.mp4"); self.media("photo.jpg")
        first = self.prepare()
        path = Path(first.project_path)
        before = path.read_bytes(), path.stat().st_mtime_ns
        again = self.service.prepare(self.event, self.project)
        self.assertTrue(again.unchanged)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual((again.timelines_created, again.timelines_updated), (0, 0))
        self.assertEqual(len([v for v in self.document(again)["project"]["items"].values() if "Media" in v["kind"]]), 2)

    def test_photo_only_refresh_reuses_proxy_and_timelines_in_a_recoverable_project(self):
        self.media("landscape.mp4")
        first = self.prepare()
        original_bytes = Path(first.project_path).read_bytes()
        self.media("photo.jpg")
        with patch.object(self.client, "run", wraps=self.client.run) as run:
            second = self.service.prepare(self.event, self.project)
        commands = {step["id"] for call in run.call_args_list for step in call.args[1]}
        self.assertTrue({"timeline.place", "media.attachProxies"}.isdisjoint(commands))
        self.assertEqual(second.failures + second.proxy_problems, [])
        self.assertEqual(second.proxies_linked, 1)
        self.assertNotEqual(second.project_path, first.project_path)
        self.assertEqual(Path(first.project_path).read_bytes(), original_bytes)
        self.assertEqual((second.timelines_created, second.timelines_updated), (0, 0))
        self.assertEqual(len([v for v in self.document(second)["project"]["items"].values() if "Media" in v["kind"]]), 2)
        self.assertTrue(self.service.prepare(self.event, self.project).unchanged)

    def test_manual_sequences_and_edited_generated_timeline_are_preserved(self):
        self.media("landscape.mp4")
        first = self.prepare()
        doc = self.document(first)
        edited = next(v for v in doc["project"]["items"].values() if v["name"] == "YouTube - 16x9")
        edited["kind"]["Sequence"]["video_tracks"][0]["items"][0]["duration"] -= TICKS//10
        Path(first.project_path).write_text(json.dumps(doc))
        rows = self.client.run(Path(first.project_path), [{"id": "file.newSequence", "params": {"name": "My manual edit", "width": 500, "height": 500}}], self.root / "cli-data")
        manual_id = rows[0]["result"]["sequence"]
        before = self.document(first)
        before_bytes = Path(first.project_path).read_bytes()
        self.media("portrait.mp4")
        refreshed = self.service.prepare(self.event, self.project)
        self.assertEqual(refreshed.failures, [])
        after = self.document(refreshed)
        self.assertEqual(after["project"]["items"][str(edited["id"])], before["project"]["items"][str(edited["id"])])
        self.assertEqual(after["project"]["items"][str(manual_id)], before["project"]["items"][str(manual_id)])
        self.assertEqual(Path(first.project_path).read_bytes(), before_bytes)
        self.assertTrue(any("ECC refreshed" in v["name"] for v in after["project"]["items"].values()))

    def test_relative_paths_work_after_moving_to_another_drive_mount(self):
        self.media("landscape.mp4"); self.media("photo.HEIC")
        first = self.prepare()
        moved = self.root / "Other Google Drive Mount" / "Moved Event"
        shutil.copytree(self.event, moved)
        state = json.loads((moved / "Data" / "FilmCraft" / "assembly.json").read_text())
        project = moved / state["project"]
        result = self.service.prepare(moved, project)
        self.assertTrue(result.unchanged)
        rows = self.client._call(["--project", str(project), "exec", "media.findMissing"], self.root / "cli-data")
        self.assertEqual(rows.returncode, 0, rows.stderr)
        self.assertEqual(json.loads(rows.stdout)["missing"], [])
        self.assertEqual(result.intermediate_photos, 1)

    def test_all_original_audio_streams_remain_synchronized(self):
        self.media("two-audio.mp4")
        result = self.prepare()
        self.assertEqual(result.failures + result.proxy_problems, [])
        for item in self.document(result)["project"]["items"].values():
            sequence = item["kind"].get("Sequence")
            if not sequence:
                continue
            video = sequence["video_tracks"][0]["items"][0]
            audio = [c for t in sequence["audio_tracks"] for c in t["items"]]
            self.assertEqual({c.get("audio_stream", 0) for c in audio}, {0, 1})
            self.assertTrue(all((c["start"], c["duration"], c["link"]) == (video["start"], video["duration"], video["link"]) for c in audio))

    def test_missing_original_reference_is_kept_in_refresh(self):
        path = self.media("landscape.mp4")
        self.prepare()
        path.unlink()
        result = self.service.prepare(self.event, self.project)
        self.assertTrue(any("Missing original" in problem for problem in result.failures))
        self.assertEqual(result.videos, 1)
        self.assertEqual(len([v for v in self.document(result)["project"]["items"].values() if "Media" in v["kind"]]), 1)

    def test_corrupt_file_does_not_stop_other_media_or_corrupt_project(self):
        self.media("landscape.mp4")
        bad = self.event / "Raw" / "Videos" / "bad.mp4"
        bad.write_bytes(b"damaged original")
        result = self.prepare(expected_proxy_failures=1)
        self.assertTrue(result.failures)
        self.assertEqual(result.videos, 1)
        self.client.validate(Path(result.project_path), self.root / "cli-data")
        self.assertEqual(bad.read_bytes(), b"damaged original")

    def test_lost_photo_intermediate_can_be_repaired(self):
        self.media("photo.HEIC")
        first = self.prepare()
        intermediate = next((self.event / "Data" / "FilmCraft" / "Photo Intermediates").glob("*.png"))
        intermediate.unlink()
        result = self.service.prepare(self.event, self.project)
        self.assertEqual(result.failures, [])
        self.assertTrue(intermediate.exists())
        self.assertEqual(len([v for v in self.document(result)["project"]["items"].values() if "Media" in v["kind"]]), 1)

    def test_renamed_original_keeps_stable_asset_id_without_duplicate(self):
        path = self.media("landscape.mp4")
        self.prepare()
        state_path = self.event / "Data" / "FilmCraft" / "assembly.json"
        original = next(iter(json.loads(state_path.read_text())["assets"].values()))
        path.rename(path.with_name("renamed.mp4"))
        result = self.service.prepare(self.event, self.project)
        self.assertEqual(result.failures, [])
        asset = next(iter(json.loads(state_path.read_text())["assets"].values()))
        self.assertEqual((asset["uuid"], asset["item"]), (original["uuid"], original["item"]))
        self.assertEqual(len([v for v in self.document(result)["project"]["items"].values() if "Media" in v["kind"]]), 1)

    def test_locked_event_is_not_modified(self):
        self.media("photo.jpg")
        first = self.prepare()
        before = Path(first.project_path).read_bytes()
        with (self.event / "Data" / "FilmCraft" / ".assembly.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.service.prepare(self.event, self.project)
        self.assertTrue(result.failures)
        self.assertEqual(Path(first.project_path).read_bytes(), before)

    def test_existing_media_is_adopted_when_ecc_state_is_missing(self):
        self.media("landscape.mp4"); self.media("photo.HEIC")
        first = self.prepare()
        (self.event / "Data" / "FilmCraft" / "assembly.json").unlink()
        result = self.service.prepare(self.event, self.project)
        self.assertEqual(result.failures, [])
        media = [v for v in self.document(result)["project"]["items"].values() if "Media" in v["kind"]]
        self.assertEqual(len(media), 2)

    def test_changed_photo_intermediate_is_preserved_and_repaired_in_new_version(self):
        self.media("photo.HEIC")
        first = self.prepare()
        intermediate = next((self.event / "Data" / "FilmCraft" / "Photo Intermediates").glob("*.png"))
        intermediate.write_bytes(b"changed representation")
        original_project = Path(first.project_path).read_bytes()
        result = self.service.prepare(self.event, self.project)
        self.assertEqual(result.failures, [])
        self.assertEqual(intermediate.read_bytes(), b"changed representation")
        self.assertEqual(Path(first.project_path).read_bytes(), original_project)
        self.assertTrue(result.warnings)
        self.assertEqual(result.intermediate_photos, 1)

    def test_project_saved_during_preparation_is_not_replaced_or_published_from_stale_snapshot(self):
        self.media("landscape.mp4")
        first = self.prepare()
        self.media("photo.jpg")
        state_path = self.event / "Data" / "FilmCraft" / "assembly.json"
        old_state = state_path.read_bytes()
        validate = self.client.validate

        def concurrent_save(project, data_dir):
            validate(project, data_dir)
            working = self.document(first)
            working["project"]["notes"] = "Editor's concurrent saved work"
            Path(first.project_path).write_text(json.dumps(working))

        with patch.object(self.client, "validate", side_effect=concurrent_save):
            result = self.service.prepare(self.event, self.project)
        self.assertTrue(any("changed during preparation" in problem for problem in result.failures))
        self.assertEqual(self.document(first)["project"]["notes"], "Editor's concurrent saved work")
        self.assertEqual(state_path.read_bytes(), old_state)
        self.assertEqual(list(Path(first.project_path).parent.glob("*ECC refreshed*.fcproj")), [])

    def test_existing_manually_imported_media_is_reused_and_organized(self):
        path = self.media("landscape.mp4")
        SocialVideoService().generate_for_event(self.event)
        self.project.parent.mkdir(parents=True)
        created = self.client._call(["--save-as", str(self.project), "import", str(path)], self.root / "cli-data")
        self.assertEqual(created.returncode, 0, created.stderr)
        original_project = self.project.read_bytes()
        result = self.service.prepare(self.event, self.project)
        self.assertEqual(result.failures, [])
        document = self.document(result)
        media_items = [item for item in document["project"]["items"].values() if "Media" in item["kind"]]
        self.assertEqual(len(media_items), 1)
        root = document["project"]["root"]
        media_bin = next(child["Bin"] for child in root["children"] if child.get("Bin", {}).get("name") == "Media")
        video_bin = next(child["Bin"] for child in media_bin["children"] if child.get("Bin", {}).get("name") == "Videos")
        self.assertIn({"Item": media_items[0]["id"]}, video_bin["children"])
        self.assertEqual(self.project.read_bytes(), original_project)


if __name__ == "__main__":
    unittest.main()
