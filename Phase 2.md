Event Control Center - Phase 2

Goal

Expand the Import tab so that it can create the event folder structure and generate a fully populated metadata.json file.

This phase does not import photos or videos yet.

The objective is to establish the folder structure and metadata workflow that later import functionality will build upon.

⸻

Existing Functionality

Preserve all functionality from Phase 1.

Do not redesign the UI unless required.

⸻

Root Event Folder

Add a configurable Event Root Folder.

For now, define it inside config.py.

Example:

EVENT_ROOT = "/Users/marketing/Library/CloudStorage/GoogleDrive-austin.witt@enishi.ac.jp/Shared drives/Enishi - Multimedia/04_Events/2025-26"

Future versions will expose this in Settings.

⸻

Import Tab Additions

Add two new fields.

Event Date

Default to today’s date.

Display format:

YYYY.MM.DD

Allow editing.

⸻

School Year

Default:

2025-2026

Allow editing.

⸻

Folder Creation

When the user presses:

Create Event

Create the folder:

YYYY.MM.DD - Event Name

inside the Event Root Folder.

Example:

2026.07.01 - Summer School Day 1

⸻

Inside that folder automatically create:

Data/
Raw/
    Photos/
    Videos/
Unedited JPGs/
    Photos/
Finals/
    Photos/
    Videos/
Lightroom/
Premiere/

Use pathlib instead of string concatenation.

If folders already exist, do not overwrite them.

⸻

metadata.json

Inside

Data/

generate

metadata.json

Populate it with:

{
    "version": 1,
    "event_name": "",
    "date": "",
    "school_year": "",
    "grades": [],
    "keywords": [],
    "description": "",
    "photo_count": 0,
    "video_count": 0,
    "created": "",
    "last_modified": ""
}

Populate:

* event_name
* date
* school_year
* grades
* keywords
* description

using the UI.

created and last_modified should be ISO 8601 timestamps.

Example:

2026-07-01T14:32:05+09:00

⸻

Duplicate Events

If the destination folder already exists:

Display a confirmation dialog.

Example:

This event already exists.
Do you want to overwrite the metadata?
[Cancel] [Overwrite]

Do not overwrite automatically.

⸻

Validation

Before creating anything:

Validate:

* Event name is not empty.
* Event date is valid.
* School year is not empty.

Display user-friendly errors.

⸻

Status Bar

Display progress messages.

Examples:

Creating folders...
Writing metadata...
Done.

⸻

Success Dialog

After completion:

Display:

Event created successfully.
Folder:
2026.07.01 - Summer School Day 1

⸻

Services

Move all folder creation into a service class.

Example:

FolderService

Move JSON creation into

MetadataService

The UI should only collect information and call these services.

⸻

Code Quality

Use:

* pathlib
* dataclasses where appropriate
* type hints
* docstrings

Avoid duplicated code.

Keep methods under roughly 40 lines where practical.

⸻

Goal

At the end of Phase 2, Event Control Center should be capable of creating a brand-new event folder with the complete directory structure and a valid metadata.json file using only the GUI.

No media import functionality should be added yet.
