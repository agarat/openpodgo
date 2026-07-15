# Feature: Drag & Drop with Filesystem (P-06)

**Current status:** ❌ Not implemented

Reference: _POD Go Edit Pilot's Guide v2.50_,
"IRs List" pp. 10–12 (IR drag & drop),
"Importing and Exporting Preset Files" pp. 9–10 (preset drag & drop),
"Additional Mouse Behaviors" p. 65.

---

## Overview

POD Go Edit supports drag & drop between the application and the OS
filesystem, in addition to internal drag & drop between panels.

## Drag & drop from the OS (import)

### Presets (`.pgp`)
- Drag `.pgp` from file manager → drop on a preset slot → imports and
  overwrites that slot
- Drag `.pgp` → drop on the currently loaded preset's slot → imports
  **and loads** the preset (not just import)
- Drag `.pgp` → drop on the Signal Flow → imports **and loads** the preset

### IRs (`.wav`, `.hir`)
- Drag one or more files from the OS → drop on the IR list → imports
  starting from the selected slot
- If multiple files, they are imported sequentially

## Drag & drop from the app (export)

### Presets
- Drag one or more presets from the list → drop on an OS folder →
  exports `.pgp` file(s)

### IRs
- Drag one or more IRs from the list → drop on an OS folder →
  exports `.hir` (Marketplace) or `.wav` (original WAV)

## Internal drag & drop

### Preset reorder
- Drag a preset within the same setlist → reorders (surrounding presets
  shift up/down)

### Preset copy
- `Alt/Option + click` (Mac) or `Ctrl + click` (PC) + drag → copies the
  preset(s) to another position (overwrites existing)
- Without modifier → moves (reorders)

### IRs
- Drag an IR within the IR list → **copies** (does not move). To
  reorder, manual Copy+Paste+Clear is needed.

### Between devices (multi-device)
- Drag presets between windows of different devices → copies
- Drag IRs between windows of different devices → copies
- Also works between POD Go Edit ↔ HX Edit ↔ Helix Native

### Blocks
- Drag a block between presets within POD Go Edit (and between windows
  of different devices) → copies the block with its settings

## Implementation considerations

### Qt Drag & Drop

PySide6 supports native drag & drop with:
- `QListWidget::setDragDropMode(QAbstractItemView::DragDrop)`
- `setAcceptDrops(True)` on destination widgets
- `dragEnterEvent`, `dropEvent` for handling MIME types

### MIME types

For OS drag & drop:
- Presets: `application/x-podgo-preset` + `text/uri-list` (for `.pgp`)
- IRs: `application/x-podgo-ir` + `text/uri-list` (for `.wav`, `.hir`)

### File detection

- `.pgp` → import preset
- `.hir` → import IR
- `.wav` → import IR (verify it's an IR, not just any WAV)
- `.pgs` → import setlist (possibly, though not explicitly documented)

### UI Feedback

- Show cursor with "+" when the drop is valid
- Highlight the destination slot on hover
- If the destination slot has content, show a warning that it will be
  overwritten

### Priority

**MEDIUM.** Not critical but very useful. Implement when the Librarian and
IR Library are working. Internal drag & drop (preset reorder) is already
partially implemented in `signal_flow.py` and `librarian.py`.
