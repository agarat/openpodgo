# Feature: Multi-Device, Multi-Window Support (P-04)

**Current status:** ❌ Not implemented

Reference: _POD Go Edit Pilot's Guide v2.50_, "Multi-Device, Multi-Window Support" p. 3,
"Devices" menu p. 7.

---

## Overview

POD Go Edit supports multiple POD Go / POD Go Wireless devices connected
simultaneously. Each device has its own independent application window.

## Behavior

### Detection
- On launch, the app detects all connected devices
- Each device opens its own window, with the device name in the
  title bar
- If no device is detected, shows a "No device" indicator

### Devices Menu
- "Devices" menu in the menu bar
- Lists all connected devices
- Check mark indicates which window is in the foreground
- Click on a device → brings its window to front or hides it

### Independent windows
- Each window is independently resizable
- Can be positioned on different monitors
- On macOS, closing all windows doesn't close the app (Cmd+Q to quit)

### Drag & drop between devices
- Presets can be dragged between windows of different devices
- IRs can be dragged between windows (and also from/to HX Edit
  or Helix Native plugin)
- Blocks can be copied between windows of different devices

### Keyboard shortcuts
- `Alt + 0`, `Alt + 1`, etc. (Mac: `Option + 0`, etc.): select
  device N's window

## Implementation considerations

### Architecture

- Each `PodGo` (device) instance would have its own window
- The app main orchestrator manages the detected device list
- Each window shares the same UI code but with a different
  `PodGo` instance

### Device detection

- USB transport already supports finding the device by VID:PID
  (`0e41:4247`)
- Would need to be extended to enumerate multiple devices with the
  same VID:PID
- Each device needs its own vendor interface claim and
  its own sessions

### Priority

**LOW.** A single device is sufficient for 99% of users.
Implement when:
1. Single-device support is solid
2. Someone with two POD Go units can test
