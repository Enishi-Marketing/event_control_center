# FilmCraft event preparation

ECC prepares FilmCraft projects after original media has been copied and verified,
Smaller Videos are available, browsing JPGs have been generated, and editing
project files have been created. This works for photo-only events and for adding
media to an existing event. Both project files live in the event’s Premiere
Project folder. Photo-only events get a FilmCraft project there without a
Premiere project file.

The native Import page shows preparation progress and the final video, photo,
proxy, problem, and timeline counts. **Utilities → FilmCraft assemblies →
Prepare / repair FilmCraft** repeats preparation from an existing event without
reimporting camera files. The backend commands are `prepare_filmcraft` and
`prepare_filmcraft_stream`, with an `event_folder` payload.

## Media and proxies

Originals come only from `Raw/Videos` and `Raw/Photos`. The media library has
Media/Videos, Media/Photos, and Timelines bins. Photos are available in
Media/Photos for manual editing. All three generated timelines share the same
video source assets. Proxies never appear as independent footage.

Video media references point at the originals. Proxies use the exact mapping
implemented by `SocialVideoService.destination_for`, including names such as
`Raw/Smaller Videos/Event clip 001.MOV.mp4`. No second video proxy directory or
generator is used.

FilmCraft's engine checks frame rate and duration (within one original frame)
before attaching a proxy. ECC additionally checks display aspect/orientation and
audio channel compatibility. Failed attachments keep the original reference,
use full-resolution footage, and appear in the completion report.

New Smaller Videos preserve frame timing with FFmpeg's `fps_mode=passthrough`,
retain the display rotation matrix without baking in rotation, and retain all
audio streams and channel layouts. They remain H.264/AAC MP4s in the same folder.
The AAC bitrate limit is per audio stream. FilmCraft also falls back to original
audio when an older proxy has fewer audio streams than its original.

`Data/smaller_video_manifest.json` binds each generated proxy to its source using
size and a fast content fingerprint of the first/last MiB. Legacy copies without
that record must pass two visual-content comparisons and an audio sample
comparison, as well as the engine's compatibility check. A verified legacy copy
gets a provenance record without re-encoding. A changed or wrong copy is rejected;
the existing Smaller Videos utility can rebuild it.

These fast fingerprints identify FilmCraft assets and proxies. They do **not**
replace original-import SHA-256 verification or the full source/archive hash
comparison required immediately before source cleanup.

## Photos requiring an intermediate

The tested FilmCraft 0.17.1 engine cannot decode HEIC directly. When its native
decoder cannot read a photo, ECC creates a lossless, full-resolution PNG under
`Data/FilmCraft/Photo Intermediates`. It respects EXIF orientation and retains the
ICC profile where available. On macOS, camera formats Pillow cannot decode are
tried through the system's full-resolution TIFF conversion first.

This uses neither the smaller browsing JPG nor its brightness adjustment. PNG
stores the decoder-rendered pixels losslessly, but this is not a bit-for-bit RAW
or HDR representation: the current HEIF/Pillow fallback renders 10/12-bit HDR
photos to 8-bit. Original high-bit-depth/HDR files remain unchanged in Raw/Photos.
The
project's editable photo record references the full-resolution intermediate;
the original filename and event-relative source path remain in the supported
FilmCraft metadata fields and ECC's asset mapping. The original stays in
`Raw/Photos`. The UI reports the number of intermediate photos.

A format neither FilmCraft nor the available photo decoders can read is reported
individually. Other readable media still gets a valid project. Full-resolution
PNG intermediates can require substantially more disk space than HEIC originals.
This does not add support for unsupported camera codecs to FilmCraft itself.

## Chronology, timing, and scaling

Video dates come from the original container's QuickTime recording/creation
metadata. Photos prefer EXIF DateTimeOriginal, then equivalent EXIF dates. Embedded
offsets are converted to UTC. If a timestamp has no offset, an optional
`capture_timezone` IANA timezone in `Data/metadata.json` is used, otherwise the Mac's
local timezone is assumed and reported. Invalid metadata falls back to ECC import
capture times, then the original's filesystem modification time. Proxy creation
times are never used. Equal times sort by original filename, relative path, and
persistent asset UUID.

The generated timelines are:

| Name | Canvas |
| --- | --- |
| YouTube - 16x9 | 1920 × 1080 |
| Vertical - 9x16 | 1080 × 1920 |
| Square - 1x1 | 1080 × 1080 |

They default to 30 fps; an optional `filmcraft_frame_rate` in event metadata can
select a supported rate between 1 and 240 fps. All three contain the readable
event videos in the same capture order, starting at zero. Photo-only events have
empty timelines. Video and linked audio use the original engine-probed duration
in exact 254,016,000,000-per-second ticks, including fractional sequence-frame durations.
Extra original audio streams get synchronized linked clips on additional tracks.

Scaling uses the original's oriented display dimensions and pixel aspect ratio:

```python
scale_percent = 100 * min(canvas_width / display_width,
                          canvas_height / display_height, 1.0)
```

ECC sets the real Motion scale, uniform scale, center position, and source-center
anchor. It disables scale-to-frame. FilmCraft's decoder already applies embedded
rotation; ECC does not rotate it a second time. There is no crop, stretch, upscale,
transition, music, or creative effect. Empty canvas space stays black.

## Repeat preparation and editor protection

Persistent UUIDs, source fingerprints, FilmCraft item IDs, capture times, and
representation/proxy locations live in `Data/FilmCraft/assembly.json`. Matching
content can keep its asset ID after a rename. Existing linked media can be adopted
with the engine's identity-checked relinking when ECC's state is absent.

Each generated timeline's complete content hash is recorded. An unchanged managed
timeline is reused when the ordered video inputs and sequence settings are
unchanged. When those inputs change, ECC rebuilds untouched managed timelines
and preserves edited ones alongside a new `… (ECC refreshed N)` timeline.
Separate user sequences and their references remain in the refreshed document.
Previously verified proxy links are reused when the source, proxy, provenance
record, and existing link still match.

Only a blank project created by the same import operation can be replaced, with
a recoverable copy under `Data/FilmCraft/Backups`. Later changes produce a new
`… - ECC refreshed NNN.fcproj` file, preserving the previous working project.
The UI opens the prepared file when the user chooses **Open prepared project**.
Unchanged runs reuse the current prepared file without rewriting it. Preparing
an event whose FilmCraft project is in the old separate folder saves a refreshed
copy in the Premiere Project folder and leaves the old file in place.

Preparation uses a per-event lock, a disposable draft, FilmCraft format validation,
atomic publication, and a final check that the source project did not change
during preparation. A busy or concurrently saved project is not overwritten.
The desktop editor does not share the CLI's save lock, which is why ECC creates
refreshed project files rather than externally saving over working edits.

Missing originals retain their existing media references and are reported.
Missing proxies never remove originals. Missing generated photo intermediates can
be rebuilt. Changed intermediates are preserved and a fresh representation is
used for the refreshed assembly. A newer/unknown project schema is refused safely.

Managed media paths and the asset mapping are event-relative, so moving the event
between local storage and another Drive mount does not require a staff username
or absolute home directory. User-added references outside the event are preserved;
those files still need FilmCraft's Link Media operation when unavailable elsewhere.

Preparation status is saved to `Data/FilmCraft/last_result.json` and appended to
`Data/import.log`. Import count reports include preparation failures and disable
source cleanup when the preparation needs attention.

## Runtime and validation

ECC uses the official FilmCraft **0.17.1** headless command engine. It never
connects to the running FilmCraft control server or edits the open desktop session.
Supported commands perform import, relinking, proxy attachment, sequence creation,
and clip placement. A small adapter applies exact durations, Motion transforms,
bins, portable paths, and persistent metadata using the inspected project schema.
The engine validates the final document before publication.

For source runs:

```sh
.venv/bin/python scripts/prepare_filmcraft_tool.py
.venv/bin/python -m unittest tests.test_filmcraft_service -v
```

The helper downloads the official release ZIP to prepare an ignored build tool,
verifies a pinned SHA-256 checksum, and includes the upstream MIT/Apache and font
license notices. `--archive /path/to/official.zip` supports an offline build.
`ECC_FILMCRAFT_CLI` can select an already available matching engine for development.
Staff build scripts prepare and bundle it automatically; staff do not need to
install or configure a separate CLI. No downloaded binary is committed to source.

Tests use disposable events and the real released engine to validate projects,
render fit/no-upscale and rotation cases, check original references and all audio
streams, reject mismatched proxies, test repeated/incremental preparation and
manual-edit protection, and open relocated event media through relative paths.
The integration tests skip explicitly when the engine has not been prepared.

Upstream references, pinned to the tested release's source commit:

- [Command engine and CLI](https://github.com/storytold/filmcraft/blob/2fe0d0460da86621fd8b193dcc0a61f790106200/docs/agents.md)
- [Project files, paths, and proxy rules](https://github.com/storytold/filmcraft/blob/2fe0d0460da86621fd8b193dcc0a61f790106200/docs/project-files.md)
- [Project model](https://github.com/storytold/filmcraft/tree/2fe0d0460da86621fd8b193dcc0a61f790106200/crates/project/src)

## Implementation files

- Assembly and native command adapter: `services/filmcraft_service.py`,
  `services/filmcraft_client.py`, `services/filmcraft_media.py`.
- Identity, proxy provenance, and compression: `services/media_identity.py`,
  `services/video_proxy_validation.py`, `services/social_video_service.py`.
- Import/project integration: `services/project_service.py`, `services/importer.py`,
  `services/import_check_service.py`, `backend_bridge.py`, `tabs/import_tab.py`.
- Native progress, results, and repair UI: `BackendClient.swift`, `Models.swift`,
  `EventControlCenterApp.swift`, `ContentView.swift`, `FilmcraftResultPanel.swift`.
- Tool preparation and packaging: `scripts/prepare_filmcraft_tool.py`,
  `scripts/build_staff_app.sh`, `scripts/build_macos_app.sh`,
  `EventControlBackend.spec`, `EventControlCenter.spec`.
- Tests: `tests/test_filmcraft_service.py`, `tests/test_backend_stream.py`, and
  `tests/test_bundled_project_templates.py`.

The accompanying format/count/cleanup safeguards are in `services/importer.py`,
`services/import_check_service.py`, `services/source_cleanup_service.py`,
`services/media_count_service.py`, `services/unedited_jpg_service.py`,
`tests/test_import_image_formats.py`, `tests/test_import_safety.py`, and
`tests/test_source_cleanup_service.py`.
