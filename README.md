# Event Control Center

Desktop application for an international school multimedia workflow.

## Hero Library

The photo list stays visible beneath a compact workflow toolbar. Each view shows
its relevant actions; selection, preview, and bulk metadata editing live in the
right-hand panel. Choose **Lightroom setup** for the Auto Import walkthrough,
**Locations** to change folders, or **More** for folder shortcuts and maintenance.

The native app has a **Hero Library** sidebar page. In Finder, tag chosen photos
`Hero Shot` in the configured event photo roots (including all subfolders).
Opening Hero Library or choosing **Scan Hero Shot tags** reads directory entries
and Finder tag metadata without opening image bytes. **Stage next batch** copies
three, five, or ten selected tagged originals per click into the **local**
`ECC Media Workspace/Needs Edit/Queued` folder. ECC makes
small local thumbnails for review as each batch completes. The original archive remains untouched.
An exact filename and file-size match already in `Hero_Shot_Library` or the
older `Photo_Library` is skipped; no whole-archive hashing is needed. The old
`Photo_Library` is read only and its existing folders are left in place.

ECC reads an event folder's `Data/metadata.json` when present and inherits its
event ID, name, date, school year, description, grades or sections, and
keywords. Older event folders without Data use their folder names for event
name and date. Photo-specific metadata can be added in bulk. The catalog is
stored locally, and **Remove from Library** moves ECC-managed copies into
local or shared `_Removed` folders; **Restore to Library** reverses that action. Removing
a Finder tag stops future refresh copies, while an existing catalog record
remains until explicitly removed in ECC.

Choose **Open Lightroom Catalog** to create and open a dedicated catalog from
ECC's included blank template. In Lightroom Classic, set Auto Import to watch
the empty `Needs Edit/Incoming` folder and move files into
`Needs Edit/Working Lightroom Edits` while keeping original filenames.
Then choose **Send to Lightroom** in ECC to move queued photos into Incoming.
Export full-quality finished files to the separate `Needs Edit/Exports` folder
with their ECC Asset ID at the
start of the filename; **Check Lightroom exports** matches them. **Use original**
marks an already acceptable non-raw photo ready without editing. **Push ready
to Drive** creates full-resolution `MASTER` and optimized `WEB` files under
shallow subject folders, records a hash
for duplicate detection, writes searchable metadata where supported, and clears
successfully pushed photos from the local Needs Edit workspace.
For a finished JPEG, PNG, TIFF, or HEIC that needs no Lightroom work, select it
and choose **Publish original (no edit)** to send it straight to the same
MASTER/WEB structure while preserving the source archive photo.
Published MASTER and WEB copies use matching names such as
`Open Campus - 2026.09.25 - 001.jpg`. The number is a stable position in the
catalogued Hero photo list for that event, ordered by camera filename; gaps are
possible when some photos have not been published. Lightroom working files keep
their ECC Asset ID prefix so exports can still be matched. The Library tab has
**Update existing filenames** for previously published copies; it updates the
catalog and keeps a local rename journal. Original event photos are not renamed.
Publishing checks existing copies with the same event/photo name before adding
an Asset ID suffix. If the image pixels match, ECC reconnects to the existing
MASTER and WEB files even when metadata or their school-section folder changed.
This recovery reads only matching candidates for the selected photo; scanning
the source archive remains metadata-only.
The shared library puts `MASTER` and `WEB` at the top level. Each contains
`Students`, `Teachers & Staff`, `Campus`, and `Community`. `Students` has
`Early Years`, `Primary School`, `Middle School`, and `High School` folders; mixed or
unknown sections go to `Mixed Sections` or `Section To Review`. One physical
folder is chosen per photo. Event names, dates, grades, activities, and other
facets remain in ECC and portable metadata rather than creating event folders.
**Refresh Drive folders** moves only ECC-catalogued published photos into this
layout, including files published by the earlier event-folder version.
The user can choose source, local Lightroom workspace, and shared Hero Shot Library
folders from the Hero Library **Locations** panel.

## Run

### Install on a staff Mac

The staff release is `Event Control Center vX.Y.Z.dmg` for macOS 14 or later.
Open the disk image, drag **Event Control Center** to **Applications**, then open
it from Applications. The app icon, Python backend, and dependencies are
included; staff do not need this repository, Python, Swift, or a terminal.

The no-fee release uses an ad hoc signature. On first launch, macOS may block
it because it is not notarized. After trying to open it, go to **System
Settings → Privacy & Security → Open Anyway**, enter the Mac login password,
and click **Open**. macOS saves that exception for future launches. The disk
image contains the same instructions in `Install Event Control Center.txt`.
The app checks for signed updates from GitHub Releases whenever it opens and
uses Sparkle to download and install them automatically. macOS may still ask
for authorization or first-open approval on a staff Mac. See [Apple's
first-open instructions](https://support.apple.com/guide/mac-help/open-a-mac-app-from-an-unidentified-developer-mh40617/mac).

On first launch, Settings opens so each person can choose their shared-drive
Events folder and local Events folder. The school-year folder is created below
those roots. Blank Lightroom and Premiere projects are included and used
automatically; the template fields in Settings are optional overrides. Google
Sheets requires a service-account JSON file and spreadsheet ID; obtain these
through the team's approved credential-sharing
process. No credentials or personal paths are included in the installer.

After scanning an SD card, use **Extra brightness** above the session previews
to see the lift before importing. New unedited JPG copies use that level; the
original photos are untouched. The same control is available under Utilities
for manual JPG generation. Choose **Regenerate all** there to apply a new
level to JPGs that already exist; a progress bar shows the current image and
the number completed. New installations start at **Auto + 50**; staff can
adjust the slider and their choice is saved on that Mac.

To add missing media to an event already on the shared drive, choose **Choose
existing event folder** on the Import page, then **Choose media folder** for
the original files. The existing event metadata is kept, and manually chosen
source folders are never offered for deletion or ejection. Detected writable
removable cards still offer optional cleanup after import. The app sends a
macOS notification when an import finishes; macOS may ask for notification
permission the first time.

Click a keyword chip to remove it from an event before saving.

This build targets the CPU architecture of the Mac on which it is built. Build
on Apple Silicon for Apple Silicon staff Macs; an Intel build needs an Intel
build machine and Python environment. Test the distributed disk image on a
second Mac before sending it to staff.

### Native macOS interface (SwiftUI)

The new macOS interface is a native SwiftUI application. It uses the existing
Python services through `backend_bridge.py`; it does not duplicate the media,
metadata, or folder logic in Swift.

```bash
ECC_BACKEND_ROOT="$PWD" swift run --package-path swiftui
```

The app automatically chooses a Python 3.10+ interpreter, preferring the
project's `.venv`. To use another interpreter, set `ECC_PYTHON` explicitly.
Install the project requirements before launching:

```bash
.venv/bin/python -m pip install --upgrade -r requirements.txt
```

The Swift package targets macOS 14 or later.

To build the native executable without launching it:

```bash
swift build --package-path swiftui
```

### Legacy Tkinter interface

```bash
python3 main.py
```

## Per-computer setup for source runs

Each computer keeps its own paths and credentials outside Git. Before using the
app, copy `config/local_settings.example.conf` to `config/local_settings.conf`
and replace the example paths, or set the shared-drive and local event folders
in the Settings tab. The app saves those locations locally.

Keep the Google service-account JSON file outside this repository and set its
path with `GOOGLE_SHEETS_CREDENTIALS_FILE` in `local_settings.conf`. Also set
`GOOGLE_SHEETS_SPREADSHEET_ID` and, if needed, `GOOGLE_SHEETS_WORKSHEET_NAME`.
Share the target spreadsheet with the service-account email from that JSON file.

The staff-drive helper has no built-in paths; provide both folders when running
it:

```bash
python3 create_staff_drive_events.py /path/to/events/2025-26 /path/to/archive/2025-2026
```

## Build a staff release without Apple membership

From this Mac, install the build dependencies and create the staff disk image:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-build.txt
scripts/package_staff_dmg.sh
```

This creates `dist/Event Control Center vX.Y.Z.dmg` and a SHA-256 checksum file.
Share the DMG with staff through the school's normal file-sharing channel. To
bump `VERSION` and build in one step, use `scripts/release_macos_app.sh`; it
accepts `patch`, `minor`, `major`, or `--version X.Y.Z`.

### Publish an automatic update

Sparkle checks a signed `appcast.xml` attached to the latest GitHub Release.
The release repository must be publicly readable so staff Macs can download
updates without a GitHub login. The source repository may remain private; use
a separate public repository for release assets if needed. Set the same
`RELEASE_REPOSITORY` when building the app and preparing each release:

```bash
export RELEASE_REPOSITORY='OWNER/PUBLIC_RELEASE_REPO'
scripts/package_staff_dmg.sh
scripts/prepare_github_release.sh
```

Create a GitHub Release tagged `vX.Y.Z` in that repository and attach the three
files from `build/github-release`: the DMG, its `.sha256`, and the signed
`appcast.xml`. The app's embedded feed points to that repository's latest
release. Use a higher `VERSION` for every new release. Sparkle signs the update
archive and feed with an EdDSA key stored in this build Mac's login Keychain;
back up that key securely using Sparkle's `generate_keys -x` before replacing
this Mac. Never commit or upload the private key.

Updates replace the `.app` bundle. Each Mac's paths and credentials stay in
`~/Library/Application Support/Event Control Center/local_settings.conf`, and
interface preferences stay in macOS user defaults, so an app replacement does
not reset them.

The free release cannot avoid macOS's first-open approval. Do not strip the
quarantine attribute or turn off Gatekeeper on staff Macs. Apple documents the
manual approval path above. If school IT manages staff Macs, ask whether its
device-management policy already supports internal apps.

## Optional notarized release

The release requires an Apple Developer Program **Developer ID Application**
certificate in the build Mac's keychain and a saved `notarytool` keychain
profile. Apple checks the signed disk image and staples a notarization ticket
to it. The release script stops if signing or notarization fails; only the
`.dmg` reported as ready by that script should be distributed.
Signing and notarization happen once per release, not every week. Installed
versions continue to run after the signing certificate expires; a new release
needs a valid certificate when it is built. See [Apple's Developer ID guidance](https://developer.apple.com/help/account/certificates/create-developer-id-certificates).

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-build.txt
export CODESIGN_IDENTITY='Developer ID Application: Your Organization (TEAMID)'
export NOTARYTOOL_PROFILE='your-saved-profile'
scripts/notarize_staff_app.sh
```

For a local `.app` build without a DMG, run `scripts/build_staff_app.sh`.

The notarized build signs the PyInstaller backend and SwiftUI executable with
the same Developer ID identity.

## Build the legacy Tkinter macOS App

From the project folder, install the app and build dependencies into the virtual
environment, then run the build script:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -r requirements-build.txt
chmod +x scripts/build_macos_app.sh
scripts/build_macos_app.sh
```

The build creates:

- `dist/Event Control Center.app` for double-click launching
- `dist/Event Control Center vX.Y.Z.zip` for sharing or moving to another Mac
- `dist/Event Control Center.zip` as the latest unversioned copy

The current app version lives in `VERSION`.

Packaged builds store saved settings in:

```text
~/Library/Application Support/Event Control Center/local_settings.conf
```

## macOS Tkinter Dependency

If `python3 main.py` fails with `ModuleNotFoundError: No module named '_tkinter'`,
install the Tkinter support package that matches your Homebrew Python version:

```bash
brew install python-tk@3.14
```

Then run the app again:

```bash
python3 main.py
```

## Current Features

- Native dark-mode SwiftUI desktop window with sidebar navigation
- Swift-to-Python JSON bridge that preserves the existing Python backend
- Import tab for event name, description, keywords, and grade selections
- Editable event date and school year fields
- Event folder creation under the configured event root
- Standard event subfolders for Data, Raw, and Finals
- metadata.json generation in the event Data folder
- Cleaned keyword output with whitespace removed, empty values removed, duplicates removed, and alphabetical sorting
- Pretty-printed JSON output to the terminal
- Removable media detection with manual source folder browsing
- Supported photo and video scanning without copying
- Automatic capture-session grouping with configurable gap threshold
- Session selection for simple cards and timeline selection for many sessions
- Verified media importing into Raw/Photos and Raw/Videos
- Photo and video folders are created only when that media type is imported
- Timestamp-preserving copies with duplicate filename protection
- SHA-256 verification, progress updates, cancellation, metadata count updates, and append-only import logs
- Automatic Unedited JPG generation with a gentle brightness lift for dark photos
- Lightroom catalog creation for photo imports
- Premiere project creation for video imports
- Event import destination choice: Google Drive or local Events folder

## Planned Areas

- Archive verification
- Metadata editing
- Google Drive and Google Sheets synchronization
- Archive search
- AI-assisted tagging
# Hero Library (native macOS app)

The SwiftUI sidebar includes **Hero Library** with Inbox, Library, and Featured views.
Configure source folders, a local Lightroom workspace, and the shared-drive
`Hero Library` folder from **Hero Library → Locations**. Finder-tag photos with
`Hero Shot`, then choose **Scan Hero Shot tags**. Discovery reads directory entries,
file types, and Finder tag extended attributes; it does not read or hash photo
contents. Event metadata comes from the closest ancestor `Data/metadata.json`.

The local SQLite catalog lives at
`~/Library/Application Support/Event Control Center/hero_library.sqlite3`.
Asset IDs are assigned at discovery so a Lightroom export can be matched by
starting its filename with that ID, for example `EIS-H000428 final.jpg`.
**Send to Lightroom** copies only selected originals into `Lightroom Incoming`.
Configure Lightroom Classic's watched folder to use that empty Incoming folder
and its destination to use `Lightroom Working`. Export finished images to
`Lightroom Exports`, keeping the Asset ID at the start of each filename, then
choose **Check Lightroom exports**. JPEG, PNG, TIFF, and HEIC can be published;
raw originals require an edited export. The export remains local until Publish.

Publish hashes only the selected finished file, checks for an already published
copy, and writes a full-resolution MASTER and a 2400-pixel WEB JPEG under
`MASTER/<subject>/` and `WEB/<subject>/`; Students has one additional
school-section folder. Original sources stay in the event archive.
JPEG MASTER and WEB files contain XMP metadata inside the image. One generated
`Hero_Catalog.json` at the Hero Shot Library root indexes every published asset,
including metadata for non-JPEG MASTER files. ECC remains the editable source
of truth. The **Review staff additions** action finds photos placed directly in
Drive by comparing paths without opening or hashing their image data. **Add to ECC**
registers a reviewed photo in the local inbox and assigns an Asset ID without
downloading or moving it. It can then be staged in a controlled batch, sent to
Lightroom, or published as-is. The staff-uploaded original remains at its Drive
location as the source after publication; ECC creates organized MASTER and WEB
copies. Existing per-image sidecars are moved to a local `Metadata Backups`
folder when Drive folders are refreshed. Files are copied through
the configured Google Drive filesystem location, so Drive synchronization is
handled by Google Drive for desktop. `Collections` is reserved for a later
release.
