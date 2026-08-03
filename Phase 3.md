Event Control Center – Phase 3

Goal

Implement reliable media importing.

The application should now import photos and videos from a camera SD card or selected folder into an event created during Phase 2.

This phase should prioritize data integrity, reliability, and a smooth user experience over raw import speed.

Do not generate preview JPEGs yet.

Do not delete media from the source device.

⸻

Existing Functionality

Preserve all functionality from Phases 1 and 2.

Do not redesign the existing interface except where necessary to support media importing.

⸻

Import Source

Add an Import Source section to the Import tab.

The application should automatically detect mounted removable media.

Example:

Import Source
Camera SD Card
EOS_DIGITAL

If no removable media is available, allow the user to browse for a folder manually.

Example:

Browse...

The selected source should remain editable before importing.

⸻

Supported File Types

Photos

* CR3
* CR2
* DNG
* NEF
* ARW
* RAF
* ORF
* RW2
* JPG
* JPEG

Videos

* MP4
* MOV
* MXF
* AVI
* MTS
* M2TS

Ignore unsupported file types.

⸻

Media Scan

Before importing, scan the selected source.

Display:

* Total photos
* Total videos
* Capture time information

The scan should classify supported media without copying files.

⸻

Automatic Session Detection

After scanning, automatically group files into capture sessions.

A session is a collection of files captured close together in time.

Use gaps between capture timestamps to detect session boundaries.

The exact threshold should be configurable within the application (default approximately 15–20 minutes).

⸻

Session Selection

The application should assume the user’s normal workflow is:

One SD card = One Event

Accordingly:

If six or fewer sessions are detected, present each session as a selectable card.

Example:

☑ Session 1
08:15–09:42
512 Photos
18 Videos
☑ Session 2
10:10–10:38
96 Photos
☑ Session 3
13:05–13:20
42 Photos

Provide:

* Select All Sessions
* Select None
* Individual session selection

By default, Select All Sessions should be enabled.

Users may import one, several, or all detected sessions as a single event.

⸻

Timeline Mode

If more than six sessions are detected, replace the session cards with Timeline Mode.

Display:

* Start Time
* End Time

using a timeline or two adjustable time controls.

As the user adjusts the time range, update:

* Photo count
* Video count

in real time.

This mode provides finer control when many small sessions are detected.

⸻

Destination

Import selected media into the event folder created during Phase 2.

Copy files into:

Raw/
    Photos/
Raw/
    Videos/

Create folders if required.

⸻

Copy Behaviour

Copy files while preserving timestamps.

Never overwrite existing files.

If a filename already exists, append:

_001
_002
_003

until a unique filename is available.

⸻

File Verification

Every copied file must be verified.

After copying:

* Calculate SHA-256 hashes for the source file.
* Calculate SHA-256 hashes for the destination file.

If the hashes differ:

* Delete the copied file.
* Record the failure.
* Continue importing remaining files.

Never stop importing because a single file failed verification.

⸻

Progress

Display:

Scanning Media...

followed by:

Found:
482 Photos
14 Videos

During import display:

Importing
248 / 496 Files

Include:

* Progress bar
* Current file
* Status bar updates

The interface must remain responsive throughout the import.

⸻

Import Summary

After completion display:

Import Complete
Photos Imported:
482
Videos Imported:
14
Skipped:
2
Failed:
0

⸻

Update Metadata

After a successful import, update:

* photo_count
* video_count
* last_modified

Do not overwrite:

* event_name
* keywords
* grades
* description
* school_year
* date

⸻

Import Log

Create:

Data/import.log

Append every import.

Example:

==================================
2026-07-03 14:52
Source:
/Volumes/EOS_DIGITAL
Destination:
2026.07.03 - Summer School Day 1
Photos Imported:
482
Videos Imported:
14
Skipped:
2
Failures:
0
Cancelled:
False

Never overwrite previous log entries.

⸻

Cancellation

Provide a Cancel button.

If Cancel is pressed:

* Finish copying the current file.
* Stop importing.
* Leave copied files intact.
* Update metadata counts.
* Record the cancellation in import.log.

⸻

Error Handling

Gracefully handle:

* Missing SD card
* Missing source folder
* Permission errors
* Read failures
* Disk full
* Hash verification failures

Individual file failures should never crash the application.

⸻

Services

Create:

DriveDetector

Responsible for:

* Detecting removable media
* Providing available import sources

⸻

ImportService

Responsible for:

* Scanning media
* Detecting sessions
* Filtering selected media
* Copying files
* Verifying hashes
* Updating metadata
* Writing import logs

⸻

HashService

Responsible for:

* SHA-256 generation
* File verification

⸻

The user interface should never perform file operations directly.

⸻

Threading

Use a worker thread for importing.

The Tkinter main thread must remain responsive.

Communicate progress to the interface using a thread-safe queue.

The worker thread must never update Tkinter widgets directly.

⸻

Code Quality

Use:

* pathlib
* shutil
* hashlib
* threading
* queue
* dataclasses
* type hints
* docstrings

Keep methods focused and avoid duplicated code.

⸻

Goal

At the end of Phase 3, Event Control Center should fully replace the existing Bash-based media import workflow while providing a significantly better user experience.

The application should support importing an entire SD card by default while also making it quick and intuitive to split a card containing multiple events into separate imports when necessary.

Do not generate preview JPEGs.

Do not delete media from the SD card.

Protecting user data is more important than convenience.