<img height="200" alt="splash-v2" src="https://github.com/user-attachments/assets/f2816f78-98a1-4816-a964-494d71e29e67" />

# CC Project Transfer

A portable Windows (10 & 11) utility for packaging local CapCut projects into ZIP files and restoring them on another computer.
Built with Python and Tkinter for project handoffs between teammates.

- Ease your way to copy / transfer project between pc / teams
- Export capcut project to zip file (with or without media sources)
- Export/Export Capcut project to FTP server (like cloud, but less secure)

V2.0 Changelog
- Added FTP support
- Added Jianying Support
- Added batch export option
- Removed capcut is closed sldier/checkbox

## Overview

CapCut stores local drafts in project folders. This app helps users find those folders, package a selected project, and restore a shared package into their own drafts directory. Source media can be included or transferred separately.

## Quick start

1. Run `CC Project Transfer v1.0.exe` No Python installation is required.
2. Be sure to save your work and close CapCut before exporting or importing.
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

## Portable settings

The EXE saves its folder preference beside itself:

```text
CC Project Transfer v1.0.exe
CapCutProjectTransfer.settings.json
```

## Development

Build on Windows using Python with Tcl/Tk installed:

The current release was built with Python 3.12 and PyInstaller for 64-bit Windows.

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

