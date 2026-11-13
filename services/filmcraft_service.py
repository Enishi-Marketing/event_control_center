"""Prepare event assemblies through FilmCraft's official headless engine.

The small document adapter uses the released ProjectItem metadata, MediaRef,
Sequence and Motion fields (FilmCraft 0.17.1, project schema 17). The engine
imports/probes media, attaches compatible proxies, constructs clips and validates
the completed document. This module never connects to the running desktop app.
"""

import copy
import fcntl
import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from config.config import AppConfig
from services.filmcraft_client import FilmcraftClient
from services.filmcraft_media import capture_time, photo_intermediate
from services.importer import PHOTO_EXTENSIONS, VIDEO_EXTENSIONS, is_system_file
from services.media_identity import atomic_json, media_identity, same_content
from services.project_service import legacy_filmcraft_path
from services.social_video_service import SocialVideoService
from services.video_proxy_validation import verify_proxy_origin


TICKS = 254_016_000_000
PROFILES = (("YouTube - 16x9", 1920, 1080), ("Vertical - 9x16", 1080, 1920), ("Square - 1x1", 1080, 1080))


@dataclass
class FilmcraftProgress:
    message: str
    current: int = 0
    total: int = 0


@dataclass
class FilmcraftSummary:
    project_path: str = ""
    videos: int = 0
    photos: int = 0
    proxies_linked: int = 0
    proxy_problems: list[str] = field(default_factory=list)
    timelines_created: int = 0
    timelines_updated: int = 0
    intermediate_photos: int = 0
    failures: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    unchanged: bool = False


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _step(command: str, **params: Any) -> dict[str, Any]:
    return {"id": command, "params": params}


def _media(item: dict[str, Any]) -> dict[str, Any] | None:
    return item.get("kind", {}).get("Media")


def fit_scale(width: float, height: float, canvas_width: int, canvas_height: int) -> float:
    if width <= 0 or height <= 0:
        raise ValueError("Media display dimensions must be positive.")
    return min(canvas_width / width, canvas_height / height, 1.0) * 100.0


class FilmcraftService:
    def __init__(self, client: FilmcraftClient | None = None) -> None:
        self.client = client

    def prepare(
        self, event: Path, project_file: Path, *, newly_created: bool = False,
        progress_callback: Callable[[FilmcraftProgress], None] | None = None,
    ) -> FilmcraftSummary:
        summary = FilmcraftSummary(project_path=str(project_file))
        folder = event / "Data" / "FilmCraft"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            with (folder / ".assembly.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeError("Another FilmCraft preparation is using this event. Try again after it finishes.") from exc
                self._prepare(event.resolve(), project_file.resolve(), folder.resolve(), newly_created, summary, progress_callback)
        except Exception as exc:
            summary.failures.append(f"FilmCraft preparation: {exc}")
        atomic_json(folder / "last_result.json", asdict(summary))
        with (event / "Data" / "import.log").open("a", encoding="utf-8") as log:
            log.write("FilmCraft preparation:\n" + json.dumps(asdict(summary), indent=2) + "\n")
        return summary

    def _prepare(self, event: Path, canonical: Path, folder: Path, newly_created: bool,
                 summary: FilmcraftSummary, progress: Callable[[FilmcraftProgress], None] | None) -> None:
        def emit(message: str, current: int = 0, total: int = 0) -> None:
            if progress:
                progress(FilmcraftProgress(message, current, total))

        emit("Creating or opening FilmCraft project…")
        state_path = folder / "assembly.json"
        state = json.loads(state_path.read_text()) if state_path.exists() else {"version": 1, "assets": {}, "timelines": {}}
        if state.get("version") != 1:
            raise ValueError("The FilmCraft assembly record is from an unsupported version; it was left untouched.")
        source_project = event / state["project"] if state.get("project") else canonical
        if not state.get("project") and not canonical.exists():
            source_project = legacy_filmcraft_path(event, canonical)
        if not source_project.is_file():
            raise FileNotFoundError("The existing FilmCraft project is missing. Restore it before refreshing the assembly.")
        original_bytes = source_project.read_bytes()
        original_hash = hashlib.sha256(original_bytes).hexdigest()
        document = json.loads(original_bytes)
        if document.get("format") != "filmcraft.project" or not 15 <= document.get("schema_version", 0) <= 17:
            raise ValueError("This FilmCraft project schema is unsupported. The existing project was not changed.")
        project = document["project"]
        if original_bytes == AppConfig.BUNDLED_FILMCRAFT_TEMPLATE.read_bytes():
            for key in list(project["items"]):
                self._remove_reference(project["root"], int(key))
                del project["items"][key]
            project["root"]["children"] = []
            document["view"] = {"open_sequences": [], "active_sequence": None, "sequences": {}}
        project["settings"]["default_still_duration"] = 3 * TICKS
        records = state.get("assets", {})
        metadata_path = event / "Data" / "metadata.json"
        event_metadata = json.loads(metadata_path.read_text()) if metadata_path.exists() else {}
        fps = float(event_metadata.get("filmcraft_frame_rate", 30))
        if not 1 <= fps <= 240:
            raise ValueError("FilmCraft timeline frame rate must be between 1 and 240 fps.")
        hints = self._import_hints(event)
        assets = []
        claimed = set()
        inventory = {}
        files = sorted(p for name in ("Photos", "Videos") for p in (event / "Raw" / name).rglob("*")
                       if p.is_file() and not is_system_file(p) and p.suffix.casefold() in PHOTO_EXTENSIONS | VIDEO_EXTENSIONS)
        for index, source in enumerate(files, 1):
            relative = str(source.relative_to(event))
            kind = "video" if source.is_relative_to(event / "Raw" / "Videos") else "photo"
            emit("Inspecting original event media…", index, len(files))
            old = records.get(relative, {})
            try:
                identity = media_identity(source, old.get("signature"))
                proxy = SocialVideoService.destination_for(source, event) if kind == "video" else None
                proxy_signature = media_identity(proxy, old.get("proxy_signature")) if proxy and proxy.is_file() else None
                inventory[relative] = {"source": identity, "proxy": proxy_signature}
                if not old:
                    # A renamed original keeps its UUID when its previous path no
                    # longer exists. Identical files at two live paths stay distinct.
                    matches = [r for key, r in records.items() if r.get("uuid") not in claimed and not (event / key).exists() and same_content(identity, r.get("signature", {}))]
                    if len(matches) == 1:
                        old = matches[0]
                asset = copy.deepcopy(old) if old and same_content(identity, old.get("signature", {})) else {}
                asset.update({"relative": relative, "kind": kind, "signature": identity, "proxy_signature": proxy_signature})
                asset.pop("missing", None)
                if asset.get("representation"):
                    representation = event / asset["representation"]
                    previous_representation = asset.get("representation_signature")
                    current_representation = media_identity(representation, previous_representation) if representation.is_file() else None
                    asset["representation_signature"] = current_representation
                    if previous_representation and current_representation and not same_content(previous_representation, current_representation):
                        # Preserve a modified intermediate and every user sequence
                        # referencing it. The refreshed assembly gets a new version.
                        asset.pop("item", None)
                        asset.pop("representation", None)
                        asset.pop("representation_signature", None)
                        asset["uuid"] = uuid4().hex
                        asset["force_new"] = True
                        summary.warnings.append(f"Preserved a changed photo intermediate for {relative}; creating a fresh full-resolution representation.")
                asset.setdefault("uuid", uuid4().hex)
                if not asset.get("capture_time") or state.get("capture_timezone") != event_metadata.get("capture_timezone") or old.get("signature", {}).get("mtime_ns") != identity["mtime_ns"]:
                    hint = hints.get(relative, {})
                    when, method = capture_time(source, kind, hint.get("capture_time"), event_metadata.get("capture_timezone"))
                    asset.update(capture_time=when, capture_method=method, original_name=hint.get("original_name", source.name))
                assets.append(asset)
                claimed.add(asset["uuid"])
            except Exception as exc:
                summary.failures.append(f"{relative}: {exc}")
        for relative, old in records.items():
            if old.get("uuid") not in claimed and relative not in inventory and not (event / relative).exists() and str(old.get("item")) in project["items"]:
                missing = copy.deepcopy(old)
                missing["missing"] = True
                assets.append(missing)
                summary.failures.append(f"Missing original: {relative}; its project reference was preserved.")
        def input_signature() -> str:
            manifest = event / "Data" / "smaller_video_manifest.json"
            return _digest({"files": inventory, "fps": fps, "timezone": event_metadata.get("capture_timezone"),
                            "name": event_metadata.get("event_name"),
                            "representations": {a["relative"]: a.get("representation_signature") for a in assets if a.get("representation")},
                            "proxy_manifest": hashlib.sha256(manifest.read_bytes()).hexdigest() if manifest.exists() else None,
                            "assembly_version": 4})
        signature = input_signature()
        if (not summary.failures and source_project.parent == canonical.parent
            and state.get("input_signature") == signature and state.get("project_hash") == original_hash
            and all((event / a.get("representation", a["relative"])).is_file() for a in assets)):
            cached = state["summary"]
            for key, value in cached.items():
                setattr(summary, key, value)
            summary.project_path = str(source_project)
            summary.timelines_created = summary.timelines_updated = 0
            summary.unchanged = True
            emit("FilmCraft project already up to date.")
            return

        client = self.client or FilmcraftClient()
        self._absolute_references(document, source_project.parent)
        project = document["project"]
        media_bin = self._bin(project, "Media")
        video_bin = self._bin(project, "Videos", media_bin)
        photo_bin = self._bin(project, "Photos", media_bin)
        timeline_bin = self._bin(project, "Timelines")
        # A first import can replace only the blank file created by this same
        # import operation. Every later change is a fresh, recoverable project.
        target = canonical if newly_created and source_project == canonical and not state.get("project") else self._refreshed_path(canonical)
        target.parent.mkdir(parents=True, exist_ok=True)
        source_hash_before = original_hash
        with tempfile.TemporaryDirectory(prefix=".filmcraft-session-", dir=folder) as temporary:
            temporary = Path(temporary)
            draft = target.parent / f".ecc-filmcraft-{uuid4().hex}.fcproj"
            try:
                atomic_json(draft, document)
                pending = []
                for asset in assets:
                    item = project["items"].get(str(asset.get("item")))
                    if item is None and not asset.get("force_new"):
                        source_path = str((event / asset["relative"]).resolve())
                        candidates = [entry for entry in project["items"].values() if _media(entry) and (
                            _media(entry).get("media", {}).get("File", {}).get("path") == source_path
                            or (entry.get("metadata", {}).get("Original File") == asset["relative"]
                                and entry.get("metadata", {}).get("ECC Source Fingerprint") == asset["signature"]["fingerprint"])
                        )]
                        if len(candidates) == 1:
                            candidate = candidates[0]
                            linked = _media(candidate).get("media", {}).get("File", {}).get("path")
                            if linked:
                                atomic_json(draft, document)
                                rows = client.run(draft, [_step("media.relink", item=candidate["id"], path=linked,
                                                               relinkOthers=False, alignTimecode=False, force=False)], temporary)
                                if rows[0].get("ok"):
                                    document = json.loads(draft.read_text()); project = document["project"]
                                    asset["item"] = candidate["id"]
                                    asset["uuid"] = candidate.get("metadata", {}).get("ECC Asset ID") or asset["uuid"]
                                    if linked != source_path and Path(linked).is_relative_to(event):
                                        asset["representation"] = str(Path(linked).relative_to(event))
                                    item = project["items"][str(asset["item"])]
                    expected = str((event / asset.get("representation", asset["relative"])).resolve())
                    found = _media(item or {})
                    if found:
                        stored = found.get("media", {}).get("File", {}).get("path")
                        # A portable identity, not just a filename, established
                        # that this is a renamed original.
                        if stored and not Path(stored).exists() and not asset.get("missing") and not asset.get("representation"):
                            found["media"]["File"]["path"] = expected
                            stored = expected
                        if stored == expected:
                            if asset.get("representation") and not Path(expected).is_file() and not asset.get("missing"):
                                photo_intermediate(event / asset["relative"], Path(expected))
                            continue
                    if asset.get("missing"):
                        continue
                    source = event / asset["relative"]
                    emit("Importing original video media…" if asset["kind"] == "video" else "Importing photos…")
                    try:
                        if asset["kind"] == "photo":
                            try:
                                info = client.probe(source, temporary)
                                # Compare the engine's dimensions with oriented EXIF
                                # dimensions; do not leave a sideways still in an edit.
                                from PIL import Image
                                with Image.open(source) as image:
                                    w, h = image.size
                                    if image.getexif().get(274) in (5, 6, 7, 8):
                                        w, h = h, w
                                    if (info["video"]["width"], info["video"]["height"]) != (w, h):
                                        raise ValueError("Photo needs EXIF orientation normalization")
                            except Exception:
                                representation = folder / "Photo Intermediates" / f"{asset['uuid']}.png"
                                if not representation.is_file():
                                    photo_intermediate(source, representation)
                                asset["representation"] = str(representation.relative_to(event))
                                source = representation
                        pending.append((asset, source))
                    except Exception as exc:
                        summary.failures.append(f"{asset['relative']}: {exc}")
                for begin in range(0, len(pending), 20):
                    batch = pending[begin:begin + 20]
                    rows = client.run(draft, [_step("file.import", paths=[str(path)], bin=video_bin["id"] if a["kind"] == "video" else photo_bin["id"], imageSequence=False) for a, path in batch], temporary)
                    document = json.loads(draft.read_text()); project = document["project"]
                    for (asset, _), row in zip(batch, rows):
                        ids = row.get("result", {}).get("items", [])
                        if not row.get("ok") or not ids:
                            summary.failures.append(f"{asset['relative']}: {row.get('error') or row.get('result', {}).get('errors')}")
                        else:
                            asset["item"] = ids[0]
                    emit("Importing event media…", min(begin + 20, len(pending)), len(pending))
                active = []
                for asset in assets:
                    item = project["items"].get(str(asset.get("item")))
                    if not item or not _media(item):
                        continue
                    if not asset.get("project_name") or item["name"] == asset["project_name"]:
                        item["name"] = asset["original_name"]
                    asset["project_name"] = item["name"]
                    if asset.get("representation"):
                        asset["representation_signature"] = media_identity(event / asset["representation"])
                    asset.pop("force_new", None)
                    item.setdefault("metadata", {}).update({"ECC Asset ID": asset["uuid"], "Original Filename": asset["original_name"],
                                                           "Original File": asset["relative"], "Capture Time": asset["capture_time"],
                                                           "Capture Time Source": asset["capture_method"],
                                                           "ECC Source Fingerprint": asset["signature"]["fingerprint"]})
                    active.append(asset)
                active.sort(key=lambda a: (a["capture_time"], a["original_name"].casefold(), a["relative"], a["uuid"]))
                atomic_json(draft, document)
                organization = []
                for kind, destination_bin in (("video", video_bin), ("photo", photo_bin)):
                    identifiers = [asset["item"] for asset in active if asset["kind"] == kind]
                    if identifiers:
                        organization.append(_step("project.moveToBin", items=identifiers, bin=destination_bin["id"]))
                if organization:
                    rows = client.run(draft, organization, temporary)
                    if any(not row.get("ok") for row in rows):
                        raise ValueError("FilmCraft could not organize the original media bins.")
                    document = json.loads(draft.read_text())
                manifest_path = event / "Data" / "smaller_video_manifest.json"
                try:
                    proxy_records = json.loads(manifest_path.read_text()).get("videos", {})
                except (OSError, ValueError):
                    proxy_records = {}
                for index, asset in enumerate(active, 1):
                    if asset["kind"] != "video":
                        continue
                    emit("Linking compressed video proxies…", index, len(active))
                    original = event / asset["relative"]
                    proxy = SocialVideoService.destination_for(original, event)
                    media = _media(document["project"]["items"][str(asset["item"])])
                    proxy_record = proxy_records.get(asset["relative"])
                    verified_proxy = _digest([asset["signature"], asset["proxy_signature"], proxy_record, media["info"]])
                    previous_proxy = asset.pop("verified_proxy", None)
                    try:
                        if not original.is_file() or not proxy.is_file():
                            raise ValueError("Original or smaller video is missing")
                        linked = (media.get("proxy") or {}).get("File", {}).get("path")
                        if proxy_record and previous_proxy == verified_proxy and linked == str(proxy.resolve()):
                            asset["verified_proxy"] = verified_proxy
                            summary.proxies_linked += 1
                            continue
                        pi = client.probe(proxy, temporary)
                        vi = media["info"].get("video")
                        if not vi or not pi.get("video"):
                            raise ValueError("Original and proxy must both contain video")
                        rate = Fraction(vi["frame_rate"]["num"], vi["frame_rate"]["den"])
                        if Fraction(pi["video"]["frame_rate"]["num"], pi["video"]["frame_rate"]["den"]) != rate or abs(pi["duration"] - media["info"]["duration"]) > Fraction(TICKS, 1) / rate:
                            raise ValueError("Proxy frame rate or duration does not match the original")
                        original_aspect = vi["width"] / vi["height"] * float(Fraction(*vi["par"]))
                        proxy_aspect = pi["video"]["width"] / pi["video"]["height"] * float(Fraction(*pi["video"]["par"]))
                        if abs(proxy_aspect / original_aspect - 1) > 0.01:
                            raise ValueError("Proxy display aspect/orientation does not match this original")
                        original_audio = media["info"].get("audio_streams", [])
                        proxy_audio = pi.get("audio_streams", [])
                        if len(proxy_audio) >= len(original_audio) and any(
                            proxy_audio[i]["channels"] < stream["channels"] for i, stream in enumerate(original_audio)
                        ):
                            raise ValueError("Proxy loses original audio channels. Rebuild the smaller copy with ECC.")
                        checked_record = verify_proxy_origin(event, original, proxy, media["info"])
                        rows = client.run(draft, [_step("media.attachProxies", item=asset["item"], path=str(proxy), force=False)], temporary)
                        if not rows[0].get("ok"):
                            raise ValueError(rows[0].get("error", "FilmCraft refused this proxy"))
                        document = json.loads(draft.read_text())
                        if proxy_record and checked_record == proxy_record:
                            asset["verified_proxy"] = verified_proxy
                        summary.proxies_linked += 1
                    except Exception as exc:
                        summary.proxy_problems.append(f"{asset['relative']}: {exc}")
                        # Never remove the original. An invalid generated proxy is
                        # detached in the fresh assembly so editing uses full-res.
                        _media(document["project"]["items"][str(asset["item"])])["proxy"] = None
                        atomic_json(draft, document)

                document = json.loads(draft.read_text()); project = document["project"]
                videos = [asset for asset in active if asset["kind"] == "video"]
                timeline_signature = _digest([fps, PROFILES, [
                    [asset["item"], asset["signature"]["fingerprint"],
                     _media(project["items"][str(asset["item"])])["info"]]
                    for asset in videos
                ]])
                tracked = {}
                for name, width, height in PROFILES:
                    previous = state.get("timelines", {}).get(name, {})
                    item = project["items"].get(str(previous.get("item")))
                    if item and "Sequence" in item["kind"] and state.get("timeline_signature") == timeline_signature:
                        tracked[name] = previous
                        continue
                    emit(f"Preparing {name} timeline…")
                    if item and _digest(item) == previous.get("hash"):
                        sequence_id = item["id"]
                        sequence = item["kind"]["Sequence"]
                        sequence["video_tracks"] = sequence["video_tracks"][:1]
                        sequence["audio_tracks"] = sequence["audio_tracks"][:1]
                        for track in sequence["video_tracks"] + sequence["audio_tracks"]:
                            track["items"] = []; track["transitions"] = []
                        summary.timelines_updated += 1
                        atomic_json(draft, document)
                        changed = client.run(draft, [_step("sequence.open", item=sequence_id),
                                                     _step("sequence.settings", width=width, height=height, fps=fps)], temporary)
                        if any(not row.get("ok") for row in changed):
                            raise ValueError("FilmCraft could not update sequence settings.")
                    else:
                        display_name = name
                        existing_named = next((entry for entry in project["items"].values() if entry["name"] == name and "Sequence" in entry["kind"]), None)
                        if item or existing_named:
                            names = {p["name"] for p in project["items"].values()}
                            counter = 1
                            while f"{name} (ECC refreshed {counter})" in names:
                                counter += 1
                            display_name = f"{name} (ECC refreshed {counter})"
                            preserved = item or existing_named
                            summary.warnings.append(f"Preserved existing/edited timeline '{preserved['name']}' and created '{display_name}'.")
                        rows = client.run(draft, [_step("file.newSequence", name=display_name, width=width, height=height, fps=fps, video=1, audio=1)], temporary)
                        if not rows[0].get("ok"):
                            raise ValueError(rows[0].get("error", "Cannot create FilmCraft sequence"))
                        sequence_id = rows[0]["result"]["sequence"]
                        summary.timelines_created += 1
                    document = json.loads(draft.read_text()); project = document["project"]
                    item = project["items"][str(sequence_id)]
                    item.setdefault("metadata", {})["ECC Assembly"] = name
                    atomic_json(draft, document)
                    native_cursor = 0
                    steps = [_step("sequence.open", item=sequence_id)]
                    frame_rate = item["kind"]["Sequence"]["settings"]["frame_rate"]
                    frame_duration = Fraction(TICKS * frame_rate["den"], frame_rate["num"])
                    for asset in videos:
                        info = _media(project["items"][str(asset["item"])])["info"]
                        duration = int(info["duration"])
                        if duration <= 0:
                            raise ValueError(f"Invalid source duration: {asset['relative']}")
                        steps.append(_step("timeline.place", item=asset["item"], time=native_cursor, duration=duration, insert=False, matchSequence=False))
                        native_cursor += max(1, round(Fraction(duration, 1) / frame_duration)) * int(frame_duration)
                    rows = client.run(draft, steps, temporary)
                    problems = [r.get("error") for r in rows if not r.get("ok")]
                    if problems:
                        raise ValueError("; ".join(str(p) for p in problems))
                    document = json.loads(draft.read_text()); project = document["project"]
                    item = project["items"][str(sequence_id)]
                    self._finish_sequence(project, item["kind"]["Sequence"], videos, width, height)
                    # Move only this sequence's reference, leaving other user bins
                    # and sequences intact.
                    self._remove_reference(project["root"], sequence_id)
                    self._find_bin(project["root"], timeline_bin["id"])["children"].append({"Item": sequence_id})
                    tracked[name] = {"item": sequence_id, "hash": _digest(item)}
                    atomic_json(draft, document)
                if not active and files:
                    raise ValueError("FilmCraft could not import any event media. The existing project was preserved.")
                emit("Saving and validating FilmCraft project…")
                self._portable_references(document, event, target.parent)
                document.setdefault("view", {})["open_sequences"] = [tracked[name]["item"] for name, _, _ in PROFILES]
                document["view"]["active_sequence"] = tracked[PROFILES[0][0]]["item"]
                document["project"]["name"] = event_metadata.get("event_name") or canonical.stem
                document["project"]["root"]["name"] = document["project"]["name"]
                atomic_json(draft, document)
                client.validate(draft, temporary)
                if hashlib.sha256(source_project.read_bytes()).hexdigest() != source_hash_before:
                    raise RuntimeError("The working FilmCraft project changed during preparation. It was left untouched; try again.")
                if target == canonical:
                    backup = folder / "Backups" / f"{uuid4().hex}-{canonical.name}"
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(canonical, backup)
                    os.replace(draft, target)
                else:
                    os.link(draft, target)
                summary.project_path = str(target)
                summary.videos = sum(a["kind"] == "video" for a in active)
                summary.photos = sum(a["kind"] == "photo" for a in active)
                summary.intermediate_photos = sum("representation" in a for a in active)
                if any("assumed" in a["capture_method"] for a in active):
                    summary.warnings.append("Capture times without a timezone use metadata.json capture_timezone, or this Mac's local timezone when unset.")
                if any(a["capture_method"] == "Filesystem modification time" for a in active):
                    summary.warnings.append("Some media has no usable embedded capture time; original filesystem times were used.")
                atomic_json(state_path, {"version": 1, "project": str(target.relative_to(event)),
                                        "project_hash": hashlib.sha256(target.read_bytes()).hexdigest(),
                                        "input_signature": input_signature(), "capture_timezone": event_metadata.get("capture_timezone"),
                                        "assets": {a["relative"]: a for a in active},
                                        "timeline_signature": timeline_signature,
                                        "timelines": tracked, "summary": asdict(summary)})
                emit("FilmCraft preparation complete.")
            finally:
                draft.unlink(missing_ok=True)
                # The engine may leave its own migration backup / empty CLI
                # lock for the disposable draft. These are never user projects.
                for backup in draft.parent.glob(f"{draft.stem} (schema v* backup).fcproj"):
                    backup.unlink(missing_ok=True)
                cli_lock = draft.with_name(f".{draft.name}.lock")
                if cli_lock.is_file() and cli_lock.stat().st_size == 0:
                    cli_lock.unlink(missing_ok=True)

    @staticmethod
    def _finish_sequence(project: dict[str, Any], sequence: dict[str, Any], assets: list[dict[str, Any]], width: int, height: int) -> None:
        starts = {}; cursor = 0
        for asset in assets:
            info = _media(project["items"][str(asset["item"])])["info"]
            duration = int(info["duration"])
            starts[asset["item"]] = (cursor, duration)
            cursor += duration
        for track in sequence["video_tracks"] + sequence["audio_tracks"]:
            for clip in track["items"]:
                clip["start"], clip["duration"] = starts[clip["item"]]
                clip["source_in"] = 0
                clip["speed"] = 1.0
                if track["kind"] != "Video":
                    continue
                info = _media(project["items"][str(clip["item"])])["info"]["video"]
                numerator, denominator = info.get("par", [1, 1])
                par = Fraction(numerator, denominator) if numerator > 0 and denominator > 0 else Fraction(1)
                if not Fraction(1, 8) <= par <= 8:
                    par = Fraction(1)
                # Native probing reports oriented display dimensions; applying
                # the container rotation again would turn a portrait clip twice.
                display_width, display_height = info["width"] * float(par), info["height"]
                motion = next(effect for effect in clip["effects"] if effect["effect"] == "motion")
                for key, value in {
                    "scale": {"Float": fit_scale(display_width, display_height, width, height)},
                    "rotation": {"Float": 0.0},
                    "position": {"Vec2": {"x": width / 2, "y": height / 2}},
                    "anchor": {"Vec2": {"x": info["width"] / 2, "y": info["height"] / 2}},
                    "uniform_scale": {"Bool": True},
                }.items():
                    motion["params"][key] = {"value": value}
                clip["scale_to_frame"] = False
        # Retain every original audio stream. The engine's normal placement
        # creates the primary stream; add synchronized, linked clips for the
        # remaining streams without duplicating the source media record.
        primary_audio = [clip for track in sequence["audio_tracks"] for clip in track["items"]]
        extra_tracks = {}
        for clip in primary_audio:
            streams = _media(project["items"][str(clip["item"])])["info"].get("audio_streams", [])
            if streams and streams[0]["channels"] > 2:
                clip["source_channels"] = list(range(streams[0]["channels"]))
            for stream_index, stream in enumerate(streams[1:], 1):
                if stream_index not in extra_tracks:
                    track = copy.deepcopy(sequence["audio_tracks"][0])
                    track.update(id=project["next_id"], name=f"Audio stream {stream_index + 1}", items=[], transitions=[], channels="Adaptive")
                    project["next_id"] += 1
                    extra_tracks[stream_index] = track
                extra = copy.deepcopy(clip)
                extra.update(id=project["next_id"], audio_stream=stream_index, source_channels=list(range(stream["channels"])))
                project["next_id"] += 1
                extra_tracks[stream_index]["items"].append(extra)
        sequence["audio_tracks"].extend(extra_tracks.values())
        actual = [clip["item"] for track in sequence["video_tracks"] for clip in track["items"]]
        expected = [a["item"] for a in assets if _media(project["items"][str(a["item"])])["info"].get("video")]
        if actual != expected:
            raise ValueError("FilmCraft timeline is missing or duplicating event media.")

    @staticmethod
    def _bin(project: dict[str, Any], name: str, parent: dict[str, Any] | None = None) -> dict[str, Any]:
        parent = parent or project["root"]
        for entry in parent["children"]:
            if "Bin" in entry and entry["Bin"]["name"] == name:
                return entry["Bin"]
        identifier = project["next_id"]; project["next_id"] += 1
        child = {"id": identifier, "name": name, "children": []}
        parent["children"].append({"Bin": child})
        return child

    @classmethod
    def _find_bin(cls, root: dict[str, Any], identifier: int) -> dict[str, Any] | None:
        if root["id"] == identifier:
            return root
        for child in root["children"]:
            if "Bin" in child:
                result = cls._find_bin(child["Bin"], identifier)
                if result is not None:
                    return result
        return None

    @classmethod
    def _remove_reference(cls, root: dict[str, Any], identifier: int) -> None:
        root["children"] = [child for child in root["children"] if child.get("Item") != identifier]
        for child in root["children"]:
            if "Bin" in child:
                cls._remove_reference(child["Bin"], identifier)

    @staticmethod
    def _absolute_references(document: dict[str, Any], parent: Path) -> None:
        for item in document["project"]["items"].values():
            media = _media(item)
            if media:
                for ref in (media.get("media"), media.get("proxy")):
                    if ref and "File" in ref:
                        stored = ref["File"]["path"]
                        if "://" not in stored:
                            ref["File"]["path"] = str((parent / stored).resolve())

    @staticmethod
    def _portable_references(document: dict[str, Any], event: Path, parent: Path) -> None:
        for item in document["project"]["items"].values():
            media = _media(item)
            if media:
                for ref in (media.get("media"), media.get("proxy")):
                    if ref and "File" in ref:
                        path = Path(ref["File"]["path"])
                        if path.is_relative_to(event):
                            ref["File"]["path"] = os.path.relpath(path, parent)

    @staticmethod
    def _refreshed_path(canonical: Path) -> Path:
        counter = 1
        while True:
            candidate = canonical.with_name(f"{canonical.stem} - ECC refreshed {counter:03d}.fcproj")
            if not candidate.exists():
                return candidate
            counter += 1

    @staticmethod
    def _import_hints(event: Path) -> dict[str, dict[str, Any]]:
        result = {}
        for path in sorted((event / "Data" / "Import Checks").glob("*.json")):
            try:
                report = json.loads(path.read_text())
                old_root = Path(report["event_folder"])
                for record in report["records"]:
                    relative = str(Path(record["destination"]).relative_to(old_root))
                    result[relative] = {"original_name": Path(record["source"]).name, "capture_time": record.get("capture_time")}
            except (OSError, ValueError, KeyError, TypeError):
                continue
        return result
