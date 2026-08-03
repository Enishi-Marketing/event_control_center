{\rtf1\ansi\ansicpg1252\cocoartf2822
\cocoatextscaling0\cocoaplatform0{\fonttbl\f0\fswiss\fcharset0 Helvetica;}
{\colortbl;\red255\green255\blue255;}
{\*\expandedcolortbl;;}
\paperw11900\paperh16840\margl1440\margr1440\vieww11520\viewh8400\viewkind0
\pard\tx720\tx1440\tx2160\tx2880\tx3600\tx4320\tx5040\tx5760\tx6480\tx7200\tx7920\tx8640\pardirnatural\partightenfactor0

\f0\fs24 \cf0 # Event Control Center - Phase 1\
\
## Overview\
\
Create a new desktop application called **Event Control Center**.\
\
This application will become the central tool used by the multimedia department at an international school to manage photography and video events.\
\
The existing workflow is implemented in Bash. That workflow is proven and will be migrated gradually into this application.\
\
The goal is **not** to recreate the Bash script immediately.\
\
Instead, build a clean, modular application that can grow over time.\
\
---\
\
# Technology\
\
Use:\
\
- Python 3.12+\
- Tkinter (standard library only)\
- ttk widgets where appropriate\
- Object-oriented design\
- Standard library only (no third-party packages)\
\
---\
\
# Design Philosophy\
\
This application is expected to grow substantially.\
\
Future features will include:\
\
- Camera / SD card detection\
- Importing photos and videos\
- Archive verification\
- Unedited JPG generation\
- Lightroom project creation\
- Premiere project creation\
- Metadata editing\
- Google Drive synchronization\
- Google Sheets synchronization\
- Archive searching\
- AI-assisted tagging\
\
The architecture should make these additions straightforward.\
\
Separate the application into logical modules rather than placing everything in one file.\
\
Avoid tightly coupling the user interface to business logic.\
\
---\
\
# Project Structure\
\
Create the following structure:\
\
```text\
event-control-center/\
\uc0\u9474 \
\uc0\u9500 \u9472 \u9472  main.py\
\uc0\u9474 \
\uc0\u9500 \u9472 \u9472  app/\
\uc0\u9474    \u9500 \u9472 \u9472  app.py\
\uc0\u9474    \u9492 \u9472 \u9472  ui.py\
\uc0\u9474 \
\uc0\u9500 \u9472 \u9472  tabs/\
\uc0\u9474    \u9500 \u9472 \u9472  import_tab.py\
\uc0\u9474    \u9500 \u9472 \u9472  search_tab.py\
\uc0\u9474    \u9500 \u9472 \u9472  metadata_tab.py\
\uc0\u9474    \u9500 \u9472 \u9472  utilities_tab.py\
\uc0\u9474    \u9492 \u9472 \u9472  settings_tab.py\
\uc0\u9474 \
\uc0\u9500 \u9472 \u9472  services/\
\uc0\u9474    \u9500 \u9472 \u9472  metadata_service.py\
\uc0\u9474    \u9492 \u9472 \u9472  importer.py\
\uc0\u9474 \
\uc0\u9500 \u9472 \u9472  models/\
\uc0\u9474    \u9500 \u9472 \u9472  event.py\
\uc0\u9474    \u9492 \u9472 \u9472  metadata.py\
\uc0\u9474 \
\uc0\u9500 \u9472 \u9472  config/\
\uc0\u9474    \u9492 \u9472 \u9472  config.py\
\uc0\u9474 \
\uc0\u9500 \u9472 \u9472  templates/\
\uc0\u9474 \
\uc0\u9500 \u9472 \u9472  assets/\
\uc0\u9474 \
\uc0\u9492 \u9472 \u9472  README.md\
```\
\
Each file should contain an appropriate class or placeholder implementation so the structure is immediately understandable.\
\
---\
\
# Main Window\
\
Title:\
\
Event Control Center\
\
Minimum size:\
\
900 \'d7 700\
\
Resizable.\
\
Use ttk widgets.\
\
---\
\
# Tabs\
\
Create a Notebook with the following tabs:\
\
- Import\
- Search\
- Metadata\
- Utilities\
- Settings\
\
Only the Import tab should contain functionality.\
\
The remaining tabs should simply display:\
\
"Coming Soon"\
\
---\
\
# Import Tab\
\
The Import tab should contain:\
\
## Event Name\
\
Single-line text field.\
\
---\
\
## Description\
\
Multi-line text field.\
\
---\
\
## Keywords\
\
Single-line text field.\
\
The user enters comma-separated keywords.\
\
Before metadata is generated:\
\
- Trim whitespace.\
- Remove duplicates.\
- Remove empty values.\
- Sort alphabetically.\
\
---\
\
## Grades\
\
Use checkboxes.\
\
Group them visually.\
\
### School-wide\
\
- All\
- Staff\
- Parents\
\
### School Sections\
\
- ELC\
- PYP\
- MYP\
- DP\
\
### Early Years\
\
- Foundation\
- Preschool\
- PreK\
- Kindergarten\
\
### Year Levels\
\
Grade 1\
\
through\
\
Grade 12\
\
Store only selected values.\
\
Example:\
\
```json\
[\
    "PYP",\
    "Grade 1",\
    "Grade 2"\
]\
```\
\
Do not store boolean values.\
\
---\
\
# Button\
\
Add a button:\
\
Create Metadata\
\
When clicked:\
\
Generate the following Python dictionary:\
\
```python\
\{\
    "version": 1,\
    "event_name": "",\
    "date": "",\
    "school_year": "",\
    "grades": [],\
    "keywords": [],\
    "description": "",\
    "photo_count": 0,\
    "video_count": 0,\
    "created": "",\
    "last_modified": ""\
\}\
```\
\
Populate it using the information entered in the interface.\
\
Pretty-print the JSON to the terminal.\
\
Do not write any files yet.\
\
---\
\
# Status Bar\
\
Add a status bar along the bottom.\
\
Initially display:\
\
Ready\
\
This will later be used for import progress and status messages.\
\
---\
\
# Code Quality\
\
Use classes.\
\
Use type hints.\
\
Use docstrings.\
\
Separate UI code from business logic.\
\
Keep methods short.\
\
Avoid global variables.\
\
---\
\
# README\
\
Generate a README describing:\
\
- Project purpose\
- Folder structure\
- Current functionality\
- Planned future modules\
\
---\
\
# Goal\
\
The result should feel like the foundation of a professional desktop application rather than a simple script with a GUI.\
\
Focus on clean architecture, maintainability, and extensibility over implementing many features.}
