# Event Control Center

Desktop application for an international school multimedia workflow.

## Run

### Native macOS interface (SwiftUI)

The new macOS interface is a native SwiftUI application. It uses the existing
Python services through `backend_bridge.py`; it does not duplicate the media,
metadata, or folder logic in Swift.

```bash
ECC_BACKEND_ROOT="$PWD" ECC_PYTHON="$PWD/.venv/bin/python" swift run --package-path swiftui
```

`ECC_PYTHON` must point to the Python environment that has the project's
requirements installed. The Swift package targets macOS 14 or later.

To build the native executable without launching it:

```bash
swift build --package-path swiftui
```

### Legacy Tkinter interface

```bash
python3 main.py
```

## Per-computer setup

Each computer keeps its own paths and credentials outside Git. Before using the
app, copy `config/local_settings.example.conf` to `config/local_settings.conf`
and replace the example paths, or set the shared-drive and local event folders
in the Settings tab. The app saves those locations locally.

Keep the Google service-account JSON file outside this repository and set its
path with `GOOGLE_SHEETS_CREDENTIALS_FILE` in `local_settings.conf`.

The staff-drive helper has no built-in paths; provide both folders when running
it:

```bash
python3 create_staff_drive_events.py /path/to/events/2025-26 /path/to/archive/2025-2026
```

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

To bump the version and build in one step:

```bash
scripts/release_macos_app.sh
```

By default this bumps the patch version, such as `0.1.0` to `0.1.1`.
You can also choose:

```bash
scripts/release_macos_app.sh minor
scripts/release_macos_app.sh major
scripts/release_macos_app.sh --version 1.2.0
```

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
- Automatic Unedited JPG generation for imported photos
- Lightroom catalog creation for photo imports
- Premiere project creation for video imports
- Event import destination choice: Google Drive or local Events folder

## Planned Areas

- Archive verification
- Metadata editing
- Google Drive and Google Sheets synchronization
- Archive search
- AI-assisted tagging
