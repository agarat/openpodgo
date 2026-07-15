# Feature: Firmware Updater (P-03)

**Current status:** ❌ Not implemented

Reference: _POD Go Edit Pilot's Guide v2.50_,
"Updater & Additional Resources" pp. 66–71.

---

## Overview

POD Go Edit includes a built-in Updater that can update:

1. **POD Go Edit** (the application itself)
2. **POD Go / POD Go Wireless firmware** (device firmware)
3. **Relay G10T / G10TII firmware** (wireless transmitter firmware)

Requires Internet connection and being signed in to the Line 6 account.

## Auto-update flow

1. On POD Go Edit launch, automatically checks for updates
2. If available, shows "Update Available" pop-up with:
   - List of available updates (app, device firmware, Relay)
   - Release Notes link
   - "Update Now" / "Later" buttons
3. Update indicator also appears at the bottom of the main window
   (clickable)

## Manual flow

Can also be checked manually from:
- `Preferences > General > Check for Updates`
- `Help > Check for Updates` (Mac)

## Update process

### 1. POD Go Edit (app)

1. Update Available prompt → "Update Now"
2. Downloads the installer (.dmg/.exe)
3. Prompt to back up (recommended)
4. Optional: customize backup name/description/location
5. Runs the downloaded installer

### 2. POD Go / POD Go Wireless firmware

1. Must be signed in
2. Update Now → EULA → Accept
3. "Update Device" → progress bar
4. Do not interrupt during the update
5. "Update Complete" → "Back to POD Go Edit"
6. Automatic reconnect

### 3. Relay G10T/G10TII firmware

- Similar to device firmware
- The transmitter must be connected to the POD Go Wireless Guitar In jack
- It's recommended to update POD Go Wireless firmware first

## Line 6 Central (offline alternative)

For firmware rollback or offline installation:
- Separate app: Line 6 Central (available at line6.com/software/)
- Supports "Update from File" with `.hxf` or `.wuf` files

## Implementation considerations

### Network layer

- Requires integration with the Line 6 API for version checking and
  firmware download
- POD Go firmware files are probably `.hxf` (Helix firmware format)
- App updates are handled by downloading and running an installer

### Safety

- Do not interrupt during firmware update (may brick the device)
- Verify firmware integrity (checksum/signature)
- Back up before updating

### Priority

**VERY LOW.** This feature:
- Requires integration with Line 6 servers
- Risk of bricking the device if implemented incorrectly
- Depends on the firmware format (`.hxf`) which hasn't been RE'd
- Not needed for PodGo Lab's offline operation

**Recommendation:** Do not implement. If any user needs to update
firmware, they can use the official POD Go Edit or Line 6 Central. Document
this decision in the README.
