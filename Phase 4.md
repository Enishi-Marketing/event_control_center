Event Control Center – Phase 4

Goal

Generate Unedited JPGs for imported photos.

After media has been successfully imported, the application should generate high-quality JPEG versions of all supported photo formats.

These JPEGs are intended for browsing, sharing, uploading, and general use without modifying the original media.

Original files must never be altered.

⸻

Destination

Store generated JPEGs inside the event folder.

Unedited JPGs/
    Photos/

Maintain the original filename whenever possible.

Examples:

IMG_1234.CR3
↓
IMG_1234.jpg
IMG_5678.NEF
↓
IMG_5678.jpg

If the source file is already a JPG or JPEG:

* Copy it into the Unedited JPGs/Photos folder.
* Do not recompress or resize it unless it exceeds the maximum size.

⸻

JPEG Generation

Generate JPEGs using the following rules:

* Maximum long edge: 2500 pixels
* Preserve aspect ratio.
* Never scale images up.
* JPEG quality approximately 90%.
* Preserve EXIF metadata where practical.
* Preserve image orientation.

If an image’s long edge is already 2500 pixels or smaller, retain its original dimensions.

⸻

Existing Files

If an Unedited JPG already exists:

* Skip generation.
* Never overwrite existing JPEGs.

This allows interrupted processing to resume safely.

⸻

Progress

After media importing completes, display:

Generating Unedited JPGs...
124 / 482

Show:

* Progress bar
* Current filename
* Remaining count
* Status bar updates

⸻

Metadata

Extend metadata.json.

Add:

{
    "unedited_jpg_count": 0
}

Update:

* unedited_jpg_count
* last_modified

Do not modify any other metadata fields.

⸻

Utilities

Add a Utilities function:

Regenerate Unedited JPGs

By default, generate only missing JPEGs.

Optionally allow the user to regenerate every JPEG after confirmation.

⸻

Goal

At the end of Phase 4, every event should contain a complete set of Unedited JPGs suitable for browsing, sharing, and uploading.

Each JPEG should have a maximum long edge of 2500 pixels, preserving aspect ratio and never enlarging smaller images.

Original media must never be modified.