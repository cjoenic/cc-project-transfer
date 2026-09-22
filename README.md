# CC Project Transfer v1.0

A portable Windows utility for packaging local CapCut projects into ZIP files and restoring them on another computer. Built with Python and Tkinter for project handoffs between teammates.

**CC Project Transfer v1.0 - made by charles**

## Overview

CapCut stores local drafts in project folders. This app helps users find those folders, package a selected project, and restore a shared package into their own drafts directory. Source media can be included or transferred separately.

The app works locally. Share the resulting ZIP through your preferred file-sharing service. It does not provide cloud sync, simultaneous editing, or project merging.

## Features

- Detects the default Windows drafts location, with manual folder selection and a saved folder preference.
- Lists projects by name and last-modified date.
- Suggests the project name as the export ZIP filename, replacing invalid Windows filename characters.
- Offers an **Include source media files** toggle.
- Displays recognized media references, missing-file counts, and estimated uncompressed size.
- Includes optional handoff notes and a media checklist in the package.
- Verifies packaged files using SHA-256 checksums during restoration.
- Checks archive paths and available disk space before extraction.
- Restores into a new folder without overwriting existing projects.
- Provides a compact interface with scrollable settings, progress feedback, and a fixed export button.
- Runs as a single portable Windows EXE with Python and Tkinter bundled.

## Quick start

1. Run `dist\CC Project Transfer v1.0.exe` from a writable folder. No Python installation is required.
2. Save your work and close CapCut before exporting or importing.
3. Confirm the drafts folder, or use **Browse** to select it. Select the folder containing individual project folders.
4. Choose a project and export it, or select **Import package** to restore a ZIP created by this app.

The default draft-location candidate is:

```text
%LOCALAPPDATA%\CapCut\User Data\Projects\com.lveditor.draft
```

Custom locations require manual selection. The app does not use the Windows registry or scan all drives.

## Export a project

1. Select the project in the library.
2. Set **Include source media files** as needed.
3. Add optional handoff notes.
4. Confirm that your work is saved and CapCut is closed.
5. Click **Export project** and choose a new ZIP filename outside the project folder.
6. Send the ZIP to your teammate.

| Media toggle | Export behavior |
| --- | --- |
| On | Packages draft data and available recognized source media. Missing references or unreadable draft JSON block this mode. |
| Off | Packages draft data and omits files with recognized media extensions, including those inside the draft folder. Transfer source media separately and relink it afterward. |

Project-only mode cannot identify every possible embedded asset or unknown file extension. ZIP compression may provide limited size reduction for already compressed video.

## Import and restore location

1. Select the receiving computer's CapCut drafts folder in the app.
2. Save your work, close CapCut, and enable the confirmation toggle.
3. Click **Import package** and select a ZIP created by this app.
4. Review the project details, media inclusion status, size, and handoff notes.
5. Confirm the import.

The app restores into a new folder beneath the selected drafts directory:

```text
<Selected drafts folder>\Transferred-<unique ID>\
```

It does **not** restore the project to the sender's original absolute location.

- **Media included:** External media is placed in a uniquely named `_transfer_media_<ID>` subfolder inside the restored project. Media originally inside the draft remains in the copied project structure. Recognized paths in readable JSON are updated to the new absolute locations.
- **Media excluded:** External media paths remain unchanged. Copy the media separately and relink it in CapCut. References to locations inside the original draft directory are updated to the restored directory, even if the media was omitted.
- **Unreadable JSON:** Files are preserved, but references inside them cannot be rewritten.

Files are staged and checked before the new project folder is finalized. Existing projects and CapCut indexes are not overwritten.

**A successful file restoration does not guarantee the project appears in CapCut's project list.** This version does not register projects in CapCut's index or regenerate internal project IDs.

## Package contents

```text
Project name.zip
├── manifest.json          # Format version, source paths, notes, sizes and checksums
├── MEDIA_CHECKLIST.txt    # Recognized media paths, sizes and availability
├── project/               # Packaged draft files
└── media/                 # Collected external media, when included
```

The manifest and checklist contain original absolute paths, which may include the sender's Windows username or folder names. Checksums detect corruption; they do not authenticate the sender.

## Portable settings

The EXE saves its folder preference beside itself:

```text
CC Project Transfer v1.0.exe
CapCutProjectTransfer.settings.json
```

Keep the executable in a writable location, such as a personal folder or USB drive. If settings cannot be saved, the app can still list projects, but the folder preference will not persist. Single-file packaging temporarily extracts runtime files when the app starts.

When running from Python source, settings are saved to:

```text
%LOCALAPPDATA%\CapCutProjectTransfer\settings.json
```

## Development

### Run from source

Use Windows with Python 3.10 or newer, including Tcl/Tk support. The app itself uses only the Python standard library.

```powershell
py -3 app.py
```

Alternatively, double-click `launch.bat`. The launcher checks for an installed Python runtime and supports the bundled development runtime on the original build machine.

### Build the portable EXE

Build on Windows using Python with Tcl/Tk installed:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
powershell -ExecutionPolicy Bypass -File build.ps1
```

Output:

```text
dist\CC Project Transfer v1.0.exe
```

The current release was built with Python 3.12 and PyInstaller for 64-bit Windows.

### Verify

Run the transfer tests:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

Run the packaged GUI startup check:

```powershell
Start-Process -FilePath '.\dist\CC Project Transfer v1.0.exe' -ArgumentList '--smoke-test' -Wait
```

Nine automated transfer tests passed, covering media transfer, project-only export, missing media, unreadable drafts, archive safety, corruption rollback, overwrite prevention, and re-exporting a restored project. GUI layout was checked at 960 × 620 and 860 × 480, and the packaged startup check passed.

### Source layout

| File | Purpose |
| --- | --- |
| `app.py` | Desktop UI, settings, filename suggestions, and background jobs |
| `transfer.py` | Draft discovery, media scanning, packaging, validation, and restoration |
| `launch.bat` / `launch.ps1` | Source-code launch helpers |
| `build.ps1` | Single-file Windows EXE build |
| `requirements-build.txt` | Pinned build dependencies |
| `tests/test_transfer.py` | Automated transfer tests |

## Current limitations

This is an experimental utility, not an official CapCut integration. A full transfer has **not yet been validated by opening and exporting the restored project in CapCut on a second computer**.

- CapCut's draft format varies by version; compatibility is not guaranteed merely because CapCut is installed.
- Project registration and internal ID regeneration are not implemented. A restored project may not appear automatically, and its internal IDs may still match the original.
- Media collection scans readable JSON for absolute paths with recognized extensions. Relative paths and unknown dependencies may be missed.
- Encrypted or unreadable draft JSON supports project-only packaging; automatic relinking is unavailable for those files.
- Fonts outside the project, effects, cloud assets, asset URLs, and account entitlements are not automatically resolved.
- Missing recognized media references block media-inclusive exports, including stale references in metadata.
- Only this app's package format is accepted; arbitrary project ZIP files are not supported.
- Transfers are intended for Windows-to-Windows use, preferably with matching CapCut versions.

The next validation step is a real two-computer transfer using external video, audio, and images, followed by checking project visibility, playback, editing, and video export. Test both media-inclusive and project-only handoffs before relying on the app for production collaboration.
