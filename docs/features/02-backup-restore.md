# Feature: Backup/Restore (L-09)

**Current status:** 🟡 `pgb.py` reads backups. Backup write + UI still missing.

Reference: _POD Go Edit Pilot's Guide v2.50_, "Creating & Restoring Complete
Device Backups" pp. 18–19.

---

## Overview

POD Go Edit allows creating a `.pgb` (POD Go Backup) file containing a
complete copy of the device state. It can be restored fully or partially
at any time.

## Backup contents

The backup includes 4 individually selectable categories when restoring:

| Item | Description |
|------|-------------|
| **Global Settings** | Device global configuration |
| **IRs** | The 128 IR slots |
| **User Model Defaults** | User-saved default values for models |
| **Presets** | Factory + User setlists (256 presets) |

## Creating a backup

1. `File > Create Backup`
2. "Create a POD Go Backup" window with:
   - **Name**: auto-generated "POD Go Backup YYYY-MM-DD", editable
   - **Description**: optional field for descriptive notes
   - **Where**: default directory:
     - Mac: `~/Documents/Line 6/POD Go/Backups/`
     - Windows: `~\My Documents\Line 6\POD Go\Backups\`
   - Folder button to choose a different location
3. Click "Create Backup" → progress bar → success or error message

Marketplace IRs require an authorized computer to include them
in the backup.

## Restoring a backup

1. `File > Restore From Backup`
2. "Restore From Backup" window with:
   - **Backup Folder**: directory (default or last used)
   - **Backup File**: combo with available `.pgb` files. Selecting one shows:
     - Date
     - Device (POD Go / POD Go Wireless)
     - Version (firmware)
     - Description
   - **Items to Restore**: checkboxes with:
     - Global Settings
     - IRs (if it includes Marketplace IRs, requires being signed in)
     - User Model Defaults
     - Presets (expandable to choose Factory and/or User individually)
3. Click "Restore Backup" → progress bar → success message

> Post-restore recommendation: power cycle the device.

## .pgb format

There is already partial implementation in `pgb.py` that reads the format. The
file appears to be a MessagePack or similar container with the same objects
transmitted over USB. See `docs/specs/02-lab-notes.md` for details.

## What needs to be implemented in PodGo Lab

### Data layer

1. **Serialization to `.pgb`**: if `pgb.py` already reads, the write
   (symmetric) must be implemented. Requires understanding the complete
   file structure
2. **Reading Global Settings and User Model Defaults**: these data
   probably live in USB objects not yet implemented
3. **IRs included in backup**: read the 128 IR slots from the device
   and embed them in the `.pgb`

### UI

"Create Backup" dialog:
- Name field (with default)
- Description field (optional)
- Directory selector
- Create / Cancel button
- Progress bar

"Restore From Backup" dialog:
- `.pgb` file selector
- Preview with metadata (date, device, version, description)
- Checkboxes for items to restore
- Restore / Cancel button
- Progress bar

### Considerations

- Marketplace: detect premium IRs to require authorization
- POD Go ↔ POD Go Wireless compatibility (mentioned in the manual)
- Backup is made from the "last-saved" state of presets; warn
  the user if the current preset has unsaved changes
- Recommend backup before firmware update
