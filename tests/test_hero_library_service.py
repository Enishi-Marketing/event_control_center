import json
import plistlib
import shutil
import sqlite3
from contextlib import closing
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from config.config import AppConfig
from services.hero_library_service import HeroLibraryService


class HeroLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.archive = self.root / "Events"
        self.event = self.archive / "2026-27" / "2026.09.25 - Open Campus"
        (self.event / "Data").mkdir(parents=True)
        (self.event / "Raw").mkdir()
        (self.event / "Data" / "metadata.json").write_text(json.dumps({
            "event_name": "Open Campus", "date": "2026.09.25", "school_year": "2026-2027",
            "event_id": "event-open-campus", "description": "Families tour the school.",
            "grades": ["PYP", "Grade 1"], "sections": ["MYP"],
            "keywords": ["Admissions", "School Tour"]
        }))
        self.photo = self.event / "Raw" / "shot.jpg"
        Image.new("RGB", (120, 80), "blue").save(self.photo)
        self.workspace = self.root / "workspace"
        self.publish_root = self.root / "Hero_Shot_Library"
        self.publish_root.mkdir()
        self.service = HeroLibraryService(self.root / "catalog.sqlite3")
        p1 = patch.object(AppConfig, "HERO_SOURCE_ROOTS", [str(self.archive)])
        p2 = patch.object(AppConfig, "HERO_WORKSPACE_ROOT", self.workspace)
        p3 = patch.object(AppConfig, "HERO_PUBLISH_ROOT", self.publish_root)
        for item in (p1, p2, p3):
            item.start()
            self.addCleanup(item.stop)

    def test_scan_is_metadata_only_and_inherits_event(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]), \
             patch("PIL.Image.open", side_effect=AssertionError("image bytes opened during scan")):
            result = self.service.scan()
        self.assertEqual(result["added"], 1)
        asset = result["assets"][0]
        self.assertEqual(asset["asset_id"], "EIS-H000001")
        self.assertEqual(asset["event_name"], "Open Campus")
        self.assertEqual(asset["event_keywords"], ["Admissions", "School Tour"])
        self.assertEqual(asset["event_sections"], ["MYP", "PYP"])
        self.assertEqual(asset["event_grades"], ["PYP", "Grade 1"])
        self.assertEqual(asset["event_description"], "Families tour the school.")
        self.assertEqual(asset["event_id"], "event-open-campus")
        self.assertEqual(self.service.scan([str(self.root / "missing")])["added"], 0)

    def test_event_photo_numbers_follow_natural_order_and_stay_stable(self):
        for name in ("shot2.jpg", "shot10.jpg"):
            Image.new("RGB", (120, 80), "green").save(self.photo.with_name(name))
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            first = self.service.scan()["assets"]
            numbers = {item["original_filename"]: item["event_photo_number"] for item in first}
            self.assertEqual(numbers, {"shot.jpg": 1, "shot2.jpg": 2, "shot10.jpg": 3})
            Image.new("RGB", (120, 80), "red").save(self.photo.with_name("shot0.jpg"))
            second = self.service.scan()["assets"]
        numbers = {item["original_filename"]: item["event_photo_number"] for item in second}
        self.assertEqual(numbers["shot0.jpg"], 4)
        self.assertEqual(numbers["shot.jpg"], 1)

    def test_published_names_and_manifest_match_originals_on_another_catalog(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        published = next(item for item in self.service.push_originals([asset["asset_id"]])["assets"]
                         if item["asset_id"] == asset["asset_id"])
        expected = "Open Campus - 2026.09.25 - 001.jpg"
        self.assertEqual(Path(published["master_path"]).name, expected)
        self.assertEqual(Path(published["web_path"]).name, expected)
        self.assertTrue(self.photo.is_file())
        manifest = json.loads((self.publish_root / "Hero_Catalog.json").read_text())
        self.assertEqual(manifest["assets"][0]["event_photo_number"], 1)
        self.assertEqual(manifest["assets"][0]["source_size"], self.photo.stat().st_size)
        second_service = HeroLibraryService(self.root / "second-catalog.sqlite3")
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            second_asset = second_service.scan()["assets"][0]
        self.assertEqual(second_asset["matched_library_path"], published["master_path"])

    def test_existing_published_files_are_renamed_and_remain_removable(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        published = next(item for item in self.service.push_originals([asset["asset_id"]])["assets"]
                         if item["asset_id"] == asset["asset_id"])
        old_master = Path(published["master_path"]).with_name(f"{asset['asset_id']} - shot.jpg")
        old_web = Path(published["web_path"]).with_name(f"{asset['asset_id']} - shot.jpg")
        Path(published["master_path"]).rename(old_master)
        Path(published["web_path"]).rename(old_web)
        old_sidecar = old_master.with_suffix(old_master.suffix + ".xmp")
        old_sidecar.write_text("old metadata")
        with closing(sqlite3.connect(self.service.catalog_path)) as db, db:
            db.execute("UPDATE assets SET master_path=?, web_path=? WHERE asset_id=?",
                       (str(old_master), str(old_web), asset["asset_id"]))
        preview = self.service.rename_published(dry_run=True)
        self.assertEqual(preview["planned"], 1)
        self.assertTrue(old_master.is_file())
        result = self.service.rename_published()
        self.assertEqual(result["renamed"], 1)
        self.assertEqual(result["errors"], [])
        renamed = next(item for item in result["assets"] if item["asset_id"] == asset["asset_id"])
        self.assertEqual(Path(renamed["master_path"]).name, "Open Campus - 2026.09.25 - 001.jpg")
        self.assertTrue(Path(renamed["master_path"] + ".xmp").is_file())
        self.assertFalse(old_master.exists())
        self.assertTrue(Path(result["journal_path"]).is_file())
        self.assertEqual(self.service.rename_published()["renamed"], 0)
        removed = self.service.remove([asset["asset_id"]])[0]
        self.assertIsNotNone(removed["removed_at"])
        self.assertFalse(Path(renamed["master_path"]).exists())
        restored = self.service.restore([asset["asset_id"]])[0]
        self.assertTrue(Path(restored["master_path"]).is_file())

    def test_finder_tag_plist_is_read_without_photo_bytes(self):
        plist = plistlib.dumps(["Hero Shot\n6", "Review\n2"])
        subprocess.run(["xattr", "-wx", "com.apple.metadata:_kMDItemUserTags", plist.hex(), str(self.photo)], check=True)
        self.assertEqual(HeroLibraryService._finder_tags(self.photo), ["Hero Shot", "Review"])

    def test_legacy_event_folder_without_json_uses_folder_metadata(self):
        (self.event / "Data" / "metadata.json").unlink()
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        self.assertEqual(asset["event_name"], "Open Campus")
        self.assertEqual(asset["event_date"], "2026.09.25")
        self.assertEqual(asset["school_year"], "2026-2027")
        self.assertEqual(asset["event_keywords"], [])

    def test_refresh_copies_only_tagged_photos_and_removal_is_reversible(self):
        other = self.event / "Raw" / "untagged.jpg"
        Image.new("RGB", (120, 80), "green").save(other)
        with patch.object(HeroLibraryService, "_finder_tags", side_effect=lambda path: ["Hero Shot"] if path == self.photo else []):
            result = self.service.refresh()
            self.assertEqual(result["found"], 1)
            self.assertEqual(result["synced"], 1, result)
            asset = result["assets"][0]
            self.assertEqual(asset["source_path"], str(self.photo))
            copy = Path(asset["needs_edit_path"])
            self.assertTrue(copy.is_file())
            self.assertIn("Needs Edit/Queued", str(copy))
            self.assertTrue(Path(asset["thumbnail_path"]).is_file())
            self.assertTrue(Path(self.service.workspace_paths()["catalog_path"]).is_file())
            removed = self.service.remove([asset["asset_id"]])[0]
            self.assertIsNotNone(removed["removed_at"])
            self.assertFalse(copy.exists())
            self.assertEqual(self.service.refresh()["synced"], 0)
            restored = self.service.restore([asset["asset_id"]])[0]
            self.assertIsNone(restored["removed_at"])
            self.assertTrue(copy.is_file())
            self.assertTrue(self.photo.is_file())

    def test_stage_match_publish_and_dedupe(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        asset_id = asset["asset_id"]
        self.service.update([asset_id], {"grades": ["Grade 1"], "sections": ["PYP"],
                                         "category": "Learning", "featured": True})
        staged = self.service.stage([asset_id])[0]
        self.assertEqual(staged["edit_state"], "IN_LIGHTROOM")
        incoming = list((self.workspace / "Needs Edit" / "Incoming").iterdir())
        self.assertEqual(len(incoming), 1)
        self.assertTrue(incoming[0].name.startswith(asset_id))
        exports = self.workspace / "Needs Edit" / "Exports"
        Image.new("RGB", (120, 80), "red").save(exports / f"{asset_id} final.jpg")
        export_bytes = (exports / f"{asset_id} final.jpg").read_bytes()
        self.assertEqual(self.service.match_exports()["matched"], 1)
        published = self.service.publish([asset_id])[0]
        self.assertEqual(published["edit_state"], "PUBLISHED")
        self.assertTrue(Path(published["master_path"]).exists())
        self.assertTrue(Path(published["web_path"]).exists())
        manifest = json.loads((self.publish_root / "Hero_Catalog.json").read_text())
        self.assertEqual(manifest["assets"][0]["asset_id"], asset_id)
        self.assertEqual(manifest["assets"][0]["source_kind"], "FINDER_TAG")
        self.assertEqual(manifest["assets"][0]["event_keywords"], ["Admissions", "School Tour"])
        self.assertFalse(manifest["assets"][0]["master"].startswith("/"))
        self.assertFalse(Path(published["web_path"] + ".xmp").exists())
        self.assertFalse(Path(published["master_path"] + ".xmp").exists())
        self.assertFalse(incoming[0].exists())
        self.assertFalse((exports / f"{asset_id} final.jpg").exists())
        self.assertIn(b"EIS-H000001", Path(published["web_path"]).read_bytes())
        with Image.open(published["web_path"]) as web_image:
            self.assertEqual(web_image.size, (120, 80))
        self.assertIn("MASTER/Students/Primary School", published["master_path"])
        self.assertIn("WEB/Students/Primary School", published["web_path"])
        self.assertTrue(self.photo.exists())
        self.service.update([asset_id], {"extra_keywords": ["Library Test Keyword"]})
        web_bytes = Path(published["web_path"]).read_bytes()
        self.assertEqual(web_bytes.count(b"http://ns.adobe.com/xap/1.0/\x00"), 1)
        self.assertIn(b"Library Test Keyword", web_bytes)
        self.assertEqual(json.loads((self.publish_root / "Hero_Catalog.json").read_text())["assets"][0]["extra_keywords"],
                         ["Library Test Keyword"])

        other = self.event / "Raw" / "other.jpg"
        other.write_bytes(export_bytes)
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            other_id = self.service.scan()["assets"][0]["asset_id"]
        self.service.update([other_id], {"edit_state": "APPROVED_AS_IS"})
        with self.assertRaisesRegex(ValueError, "duplicates published asset"):
            self.service.publish([other_id])
        self.assertEqual(len([a for a in self.service.list_assets() if a["edit_state"] == "PUBLISHED"]), 1)

    def test_existing_shared_photo_is_not_staged(self):
        existing = self.root / "Photo_Library" / "PRINT (High Resolution)" / self.photo.name
        existing.parent.mkdir(parents=True)
        existing.write_bytes(self.photo.read_bytes())
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            result = self.service.refresh()
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["synced"], 0)
        self.assertEqual(result["assets"][0]["matched_library_path"], str(existing))
        self.assertFalse((self.workspace / "Needs Edit" / "Queued" / "EIS-H000001 - shot.jpg").exists())
        self.assertEqual(list(self.publish_root.iterdir()), [])

    def test_existing_photo_library_cannot_be_a_publish_destination(self):
        old_library = self.root / "Photo_Library"
        old_library.mkdir()
        with patch.object(AppConfig, "HERO_PUBLISH_ROOT", old_library), \
             patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
            self.service.update([asset["asset_id"]], {"edit_state": "APPROVED_AS_IS"})
            with self.assertRaisesRegex(ValueError, "read-only reference"):
                self.service.publish([asset["asset_id"]])
        self.assertEqual(list(old_library.iterdir()), [])

    def test_queued_batch_moves_into_empty_lightroom_watch_folder(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.refresh()["assets"][0]
        queued = Path(asset["needs_edit_path"])
        self.assertTrue(queued.is_file())
        staged = self.service.stage([asset["asset_id"]])[0]
        self.assertEqual(staged["edit_state"], "IN_LIGHTROOM")
        self.assertFalse(queued.exists())
        incoming = Path(staged["needs_edit_path"])
        self.assertEqual(incoming.parent.name, "Incoming")
        self.assertTrue(incoming.is_file())
        working = incoming.parent.parent / "Working Lightroom Edits" / incoming.name
        incoming.rename(working)  # Lightroom Classic moves watched photos here.
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            refreshed = self.service.refresh()["assets"][0]
        self.assertEqual(refreshed["needs_edit_path"], str(working))

    def test_exports_are_separate_and_legacy_exports_move_without_loss(self):
        legacy = self.workspace / "Needs Edit" / "Working Lightroom Edits" / "Exports"
        legacy.mkdir(parents=True)
        old_export = legacy / "EIS-H000001 finished.jpg"
        Image.new("RGB", (120, 80), "red").save(old_export)
        paths = self.service.ensure_catalog()
        self.assertFalse(legacy.exists())
        self.assertTrue((Path(paths["export_path"]) / old_export.name).is_file())
        self.assertEqual(list(Path(paths["working_path"]).iterdir()), [])

    def test_finished_original_can_publish_without_lightroom(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        result = self.service.push_originals([asset["asset_id"]])
        self.assertEqual(result["pushed"], 1, result["errors"])
        published = next(item for item in result["assets"] if item["asset_id"] == asset["asset_id"])
        self.assertEqual(published["edit_state"], "PUBLISHED")
        self.assertTrue(Path(published["master_path"]).is_file())
        self.assertTrue(Path(published["web_path"]).is_file())
        self.assertTrue(self.photo.is_file())

    def test_human_readable_section_folders_and_legacy_reorganization(self):
        for code, name in (("ELC", "Early Years"), ("PYP", "Primary School"),
                           ("MYP", "Middle School"), ("DP", "High School")):
            self.assertEqual(HeroLibraryService._browse_path({
                "browse_group": "Students", "sections": [code], "event_sections": []
            }), Path("Students") / name)
        self.assertEqual(HeroLibraryService._browse_path({
            "browse_group": "Students", "sections": [], "event_sections": []
        }), Path("Students") / "Section To Review")
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        self.service.update([asset["asset_id"]], {"sections": ["PYP"]})
        published = next(item for item in self.service.push_originals([asset["asset_id"]])["assets"]
                         if item["asset_id"] == asset["asset_id"])
        old_master = Path(published["master_path"])
        old_web = Path(published["web_path"])
        legacy_base = self.publish_root / "Events" / "2026-09-25 Open Campus"
        legacy_master = legacy_base / "MASTER" / old_master.name
        legacy_web = legacy_base / "WEB" / old_web.name
        for source, destination in ((old_master, legacy_master), (old_web, legacy_web)):
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(destination))
        with closing(self.service._connect()) as db, db:
            db.execute("UPDATE assets SET master_path=?, web_path=? WHERE asset_id=?",
                       (str(legacy_master), str(legacy_web), asset["asset_id"]))
        result = self.service.reorganize_published()
        self.assertEqual(result["moved"], 1, result["errors"])
        moved = next(item for item in result["assets"] if item["asset_id"] == asset["asset_id"])
        self.assertIn("MASTER/Students/Primary School", moved["master_path"])
        self.assertIn("WEB/Students/Primary School", moved["web_path"])
        self.assertFalse(Path(moved["master_path"] + ".xmp").exists())
        self.assertFalse((self.publish_root / "Events").exists())
        regrouped = next(item for item in self.service.update([asset["asset_id"]], {"browse_group": "Campus"})
                         if item["asset_id"] == asset["asset_id"])
        self.assertIn("MASTER/Campus", regrouped["master_path"])
        self.assertIn("WEB/Campus", regrouped["web_path"])

    def test_metadata_update_reorganizes_published_files_and_embeds_tags(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        self.service.push_originals([asset["asset_id"]])
        updated = next(item for item in self.service.update([asset["asset_id"]], {
            "category": "Campus", "extra_keywords": ["Open House"], "subject": "Admissions"
        }) if item["asset_id"] == asset["asset_id"])
        self.assertIn("MASTER/Campus", updated["master_path"])
        self.assertIn("WEB/Campus", updated["web_path"])
        for key in ("master_path", "web_path"):
            data = Path(updated[key]).read_bytes()
            self.assertIn(b"Open House", data)
            self.assertIn(b"Campus", data)

    def test_non_jpeg_master_uses_generated_catalog_without_drive_sidecar(self):
        png = self.event / "Raw" / "finished.png"
        Image.new("RGB", (120, 80), "green").save(png)
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            assets = self.service.scan()["assets"]
        asset = next(item for item in assets if item["source_path"] == str(png))
        result = self.service.push_originals([asset["asset_id"]])
        self.assertEqual(result["pushed"], 1, result["errors"])
        published = next(item for item in result["assets"] if item["asset_id"] == asset["asset_id"])
        self.assertFalse(Path(published["master_path"]).with_suffix(".xmp").exists())
        self.assertFalse(Path(published["master_path"] + ".xmp").exists())
        self.assertFalse(Path(published["web_path"] + ".xmp").exists())
        manifest = json.loads((self.publish_root / "Hero_Catalog.json").read_text())
        self.assertEqual(manifest["assets"][0]["asset_id"], asset["asset_id"])

    def test_drive_audit_finds_staff_additions_without_opening_photos(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        self.service.push_originals([asset["asset_id"]])
        staff = self.publish_root / "Staff Uploads" / "new.jpg"
        staff.parent.mkdir()
        staff.write_bytes(b"not downloaded")
        with patch("PIL.Image.open", side_effect=AssertionError("audit opened an image")):
            audit = self.service.audit_drive()
        self.assertEqual(audit["uncatalogued"], ["Staff Uploads/new.jpg"])

    def test_staff_photo_can_be_adopted_without_download_then_staged_in_batch(self):
        staff = self.publish_root / "Staff Uploads" / "new.jpg"
        staff.parent.mkdir()
        Image.new("RGB", (120, 80), "orange").save(staff)
        with patch("PIL.Image.open", side_effect=AssertionError("adoption opened an image")):
            result = self.service.adopt_drive(["Staff Uploads/new.jpg"])
        self.assertEqual(len(result["added"]), 1)
        asset = next(item for item in result["assets"] if item["asset_id"] == result["added"][0])
        self.assertEqual(asset["source_kind"], "STAFF_DRIVE")
        self.assertIsNone(asset["needs_edit_path"])
        self.assertTrue(staff.is_file())
        self.assertEqual(self.service.audit_drive()["uncatalogued"], [])
        with self.assertRaisesRegex(ValueError, "Already in the Hero catalog"):
            self.service.adopt_drive(["Staff Uploads/new.jpg"])
        with self.assertRaisesRegex(ValueError, "inside the Hero Shot Library"):
            self.service.adopt_drive(["../outside.jpg"])
        with patch.object(HeroLibraryService, "_finder_tags", return_value=[]):
            refreshed = self.service.refresh(limit=1)
        self.assertEqual(refreshed["synced"], 1, refreshed["errors"])
        staged = next(item for item in refreshed["assets"] if item["asset_id"] == asset["asset_id"])
        self.assertTrue(Path(staged["needs_edit_path"]).is_file())
        self.assertTrue(staff.is_file())
        self.service.update([asset["asset_id"]], {"edit_state": "APPROVED_AS_IS"})
        published = next(item for item in self.service.publish([asset["asset_id"]])
                         if item["asset_id"] == asset["asset_id"])
        self.assertEqual(published["edit_state"], "PUBLISHED")
        self.assertTrue(staff.is_file())
        self.assertEqual(self.service.audit_drive()["uncatalogued"], [])
        manifest = json.loads((self.publish_root / "Hero_Catalog.json").read_text())
        self.assertEqual(manifest["assets"][0]["source_kind"], "STAFF_DRIVE")

    def test_metadata_organizes_finished_staff_drive_photo_and_embeds_tags(self):
        staff = self.publish_root / "Staff Uploads" / "new.jpg"
        staff.parent.mkdir()
        Image.new("RGB", (120, 80), "orange").save(staff)
        adopted = self.service.adopt_drive(["Staff Uploads/new.jpg"])
        asset_id = adopted["added"][0]
        updated = next(item for item in self.service.update([asset_id], {
            "sections": ["PYP"], "category": "Sports", "extra_keywords": ["Tournament Day"],
            "subject": "Athletics"
        }) if item["asset_id"] == asset_id)
        self.assertEqual(updated["edit_state"], "PUBLISHED")
        self.assertEqual(updated["source_path"], updated["master_path"])
        self.assertIn("MASTER/Students/Primary School", updated["master_path"])
        self.assertIn("WEB/Students/Primary School", updated["web_path"])
        self.assertFalse(staff.exists())
        for key in ("master_path", "web_path"):
            data = Path(updated[key]).read_bytes()
            self.assertIn(b"Tournament Day", data)
            self.assertIn(b"Athletics", data)
        manifest = json.loads((self.publish_root / "Hero_Catalog.json").read_text())
        entry = next(item for item in manifest["assets"] if item["asset_id"] == asset_id)
        self.assertEqual(entry["extra_keywords"], ["Tournament Day"])

    def test_metadata_organizes_matching_hero_drive_photo_and_embeds_tags(self):
        existing = self.publish_root / "Unsorted" / self.photo.name
        existing.parent.mkdir()
        shutil.copy2(self.photo, existing)
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        self.assertEqual(asset["matched_library_path"], str(existing))
        updated = next(item for item in self.service.update([asset["asset_id"]], {
            "category": "Campus", "extra_keywords": ["Admissions"], "setting": "Main entrance"
        }) if item["asset_id"] == asset["asset_id"])
        self.assertEqual(updated["edit_state"], "PUBLISHED")
        self.assertEqual(updated["source_path"], str(self.photo))
        self.assertIsNone(updated["matched_library_path"])
        self.assertIn("MASTER/Campus", updated["master_path"])
        self.assertIn("WEB/Campus", updated["web_path"])
        self.assertFalse(existing.exists())
        self.assertTrue(self.photo.is_file())
        for key in ("master_path", "web_path"):
            self.assertIn(b"Main entrance", Path(updated[key]).read_bytes())

    def test_old_sidecars_move_to_local_backup(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.scan()["assets"][0]
        published = next(item for item in self.service.push_originals([asset["asset_id"]])["assets"]
                         if item["asset_id"] == asset["asset_id"])
        sidecar = Path(published["web_path"] + ".xmp")
        sidecar.write_text("old metadata")
        result = self.service.reorganize_published()
        self.assertEqual(result["archived_sidecars"], 1)
        self.assertFalse(sidecar.exists())
        self.assertTrue((self.workspace / "Metadata Backups" / sidecar.relative_to(self.publish_root)).is_file())

    def test_original_can_publish_after_being_sent_to_lightroom(self):
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            asset = self.service.refresh()["assets"][0]
        staged = self.service.stage([asset["asset_id"]])[0]
        local_copy = Path(staged["needs_edit_path"])
        self.assertTrue(local_copy.is_file())
        result = self.service.push_originals([asset["asset_id"]])
        self.assertEqual(result["pushed"], 1, result["errors"])
        self.assertFalse(local_copy.exists())
        self.assertTrue(self.photo.is_file())

    def test_push_batch_moves_ready_exports_and_reports_unready_item(self):
        other = self.event / "Raw" / "other.jpg"
        Image.new("RGB", (120, 80), "green").save(other)
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            assets = self.service.refresh()["assets"]
        ready = next(item for item in assets if item["source_path"] == str(self.photo))
        unready = next(item for item in assets if item["source_path"] == str(other))
        export = Path(self.service.workspace_paths()["export_path"]) / f"{ready['asset_id']} finished.jpg"
        Image.new("RGB", (120, 80), "red").save(export)
        self.service.match_exports()
        outcome = self.service.push_batch([ready["asset_id"], unready["asset_id"]])
        self.assertEqual(outcome["pushed"], 1)
        self.assertEqual(len(outcome["errors"]), 1)
        self.assertFalse(export.exists())
        self.assertTrue(Path(next(item for item in outcome["assets"] if item["asset_id"] == ready["asset_id"])["master_path"]).is_file())
        self.assertTrue(Path(next(item for item in outcome["assets"] if item["asset_id"] == unready["asset_id"])["needs_edit_path"]).is_file())

    def test_refresh_stages_only_requested_batch_size(self):
        other = self.event / "Raw" / "another.jpg"
        Image.new("RGB", (120, 80), "green").save(other)
        with patch.object(HeroLibraryService, "_finder_tags", return_value=["Hero Shot"]):
            first = self.service.refresh(limit=1)
            self.assertEqual(first["synced"], 1)
            self.assertEqual(first["pending"], 1)
            second = self.service.refresh(limit=1)
        self.assertEqual(second["synced"], 1)
        self.assertEqual(second["pending"], 0)


if __name__ == "__main__":
    unittest.main()
