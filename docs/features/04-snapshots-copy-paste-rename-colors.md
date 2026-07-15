# Feature: Snapshots — Copy/Paste, Rename, Custom Colors (N-03, N-04, N-05)

**Current status:** ❌ Not implemented

Reference: _POD Go Edit Pilot's Guide v2.50_,
"Configuring & Managing Snapshots" pp. 14–16,
"Customizing Snapshot Names & Footswitch LED Colors" pp. 16–17.

---

## Overview

Snapshots in POD Go allow saving and recalling partial preset
configurations. There are 4 snapshots per preset. They store:

- Bypass state of any block (all by default)
- Up to 64 manually assigned parameters
- Tempo (if in "Per Snapshot" mode)

## Current Snapshots Menu UI

The current PodGo Lab UI already has a Snapshots menu with 4 entries
and all 4 snapshots can be selected. What's missing:

### 1. Copy/Paste Snapshot (N-03)

**Access:**
- `Snapshots > Copy Snapshot` (menu bar)
- `Snapshots > Paste Snapshot` (menu bar)
- Right-click on the Snapshots menu (camera icon) → Copy/Paste

**Behavior:**
1. Select and load the source snapshot
2. `Copy Snapshot` → saves all settings of the current snapshot to clipboard
3. Select and load the destination snapshot
4. `Paste Snapshot` → overwrites the destination snapshot with the copied settings

> **NOTE:** Paste Snapshot is NOT undoable. It doesn't appear in the Undo/Redo
> history.

**Keyboard shortcuts:**
- Mac: `Shift+Cmd+C` (Copy), `Shift+Cmd+V` (Paste)
- PC: `Shift+Ctrl+C` (Copy), `Shift+Ctrl+V` (Paste)

### 2. Rename Snapshot (N-04)

**Access:**
1. Click the toolbar Snapshots menu → expands the menu showing 4 snapshots
2. Hover over a snapshot → menu button (ⓘ) appears in the top-right corner
3. Click → "Rename"
4. Alternatively: direct double-click on the name in the expanded menu

**Behavior:**
- Edit the name text
- Enter to accept / ESC to cancel
- The new name is reflected on the pedal's snapshot footswitch mode

### 3. Customize Snapshot Footswitch LED Color (N-05)

**Access:**
1. Click the toolbar Snapshots menu → expand
2. Hover over a snapshot → menu button → select color

**Color options:**
- Auto (default = white for snapshots)
- Specific colors (red, blue, green, yellow, etc.)
- Off (no LED)

**Behavior:**
- The new color appears on the pedal's footswitch LED
- In Snapshot Footswitch Mode, the active snapshot's LED uses this color
- Also reflected in the expanded UI menu

### 4. Customize Footswitch Label & LED Color in Stomp Mode (N-05)

This is covered in detail in the Bypass/Control Assignment doc
(`docs/features/03-bypass-control-assignment.md#customizar-footswitch-label--led-color`),
but also applies to snapshots when creating controller assignments.
Custom label and color are configured from the Bypass/Control window.

## Implementation considerations

### Data layer

- Snapshot names and colors are in the active preset's blob
  (object 22, MessagePack map). See keys:
  - Snapshot names: probably an array of 4 strings
  - Snapshot LED colors: probably an array of 4 enum values
- Snapshot rename/color writing must be a `set_param` operation
  or similar on object 22
- Snapshot Copy/Paste requires reading the entire current snapshot state
  and writing it to the destination. In the blob, each snapshot has its own
  sub-map or value array

### UI

- [ ] Expand the current Snapshots menu so hovering shows a menu button
  (ⓘ) on each snapshot
- [ ] Menu options: Rename, Copy, Paste, colors
- [ ] Keyboard shortcut for Copy/Paste Snapshot
- [ ] On copy snapshot, serialize relevant data to clipboard
- [ ] On paste snapshot, mutate the blob and write to device
- [ ] Inline name editing (double-click or Rename → text field)
- [ ] Color selector (~8–12 color palette + Auto + Off)
