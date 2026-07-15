# Feature: IR Library (L-08)

**Current status:** ❌ Not implemented

Reference: _POD Go Edit Pilot's Guide v2.50_, "IRs List" pp. 10–12,
"IR File Reference" pp. 12–13, "Cab/IR Block Speaker Cabinet Models" p. 50.

---

## Overview

The pedal has 128 IR (Impulse Response) slots numbered 1–128,
initially empty. The user imports `.wav` (mono or stereo) or `.hir`
(Helix IR, Line 6 proprietary format) files into these slots. Once loaded,
they can be referenced from the Cab/IR block in any preset.

## UI in POD Go Edit

The UI has an "IRs folder" button at the top of the Librarian panel
(just beside the Factory/User folders). Clicking it replaces the preset
list with the IR list, showing:

- **Left column:** numeric index (1–128)
- **Right column:** IR file name (if the slot is occupied)
- **Gold guitar pick icon** for Marketplace-purchased IRs
- **Loaded IR:** visual indicator of which IR is currently in use in
  the active preset (if applicable)
- **Selected IR:** gray highlight, same as presets

## Import

1. Select destination slot in the IR list
2. `File > Import IR` (or contextual menu > Import, or drag & drop from the OS)
3. Multiple files can be selected and imported in sequence
   starting from the selected slot
4. When importing a stereo `.wav`, it's converted to mono according to the
   preference set in `Preferences > Presets/IRs > Stereo IR Import`
   (Left / Right / Sum)

### Supported formats

| Extension | Description |
|-----------|-------------|
| `.hir` | Line 6 Helix IR proprietary format. Used for Marketplace IRs |
| `.wav` | Standard WAV, mono or stereo, any bit depth, sample rate and duration |

### Marketplace

Premium Marketplace IRs require:
- Being signed in to a Line 6 account
- An authorized computer
- Once imported, no Internet connection is needed to use them

When exporting, a Marketplace IR exports as `.hir`; a `.wav` IR
exports as `.wav`.

## Export

1. Select slot(s) in the IR list
2. `File > Export IR` (or contextual menu > Export, or drag & drop to the OS)
3. Saves as `.hir` (Marketplace) or `.wav` (imported as WAV)

## Copy/Paste/Clear

- **Copy IR** (Edit menu or contextual): copies the IR and its settings to the clipboard
- **Paste IR**: pastes into the selected slot, overwriting
- **Clear IR**: deletes the IR from the slot
- **Rename IR**: renames the IR (slow double-click or `Edit > Rename`)
- **Drag & drop** within the list copies the IR to the new position
  (no direct "move"; done via Copy+Paste+Clear)
- **Multi-select**: Shift+click (contiguous), Cmd/Ctrl+click (non-contiguous)

## Use in a preset

Once imported, the IR is loaded into the Cab/IR block in 3 ways:

1. **Double-click** an IR in the list — automatically switches the
   Cab/IR block to IR category and loads that IR
2. **IR Select parameter** in the Edit panel — numeric slider 1–128
3. **IR category** in the Model Select panel of the Cab/IR block

### Additional IR block parameters

- Low Cut
- High Cut
- Level
- (others depending on the model)

### Filename reference

When a preset is saved with an IR, the preset stores a "reference
signature" of the filename. This means that if IRs are later reordered
in the library, the preset still finds the correct IR even if it's at a
different index. Behaviors:

- If the referenced slot is **empty**, alert "IR not found"
- If the referenced slot has a **different IR**, alert "associated IR cannot
  be found, using new IR in this slot"
- If the original IR is re-imported into another slot, the preset finds it

## DSP limitations

Using an IR consumes more DSP than a standard Cabinet model. If the
preset is at the DSP limit, an IR cannot be loaded. The UI shows
an error message in that case.

## What needs to be implemented in PodGo Lab

### Data layer

1. **`.hir` format**: determine whether it needs parsing or can be
   handled as an opaque blob. The `.hir` files have a header
   + IR data (see `docs/specs/02-lab-notes.md`)
2. **USB messages**: figure out which USB operations are needed to
   read/write IRs from the device. Probably similar to the preset
   stream but with a different object/ID
3. **Persistent 1–128 index**: the device has 128 fixed slots;
   the complete table must be read on connection

### UI

Based on the existing Librarian pattern (`librarian.py`):

- Toggle between preset view and IR view with an "IRs folder" button
- QListView + QSortFilterProxyModel (search by name)
- Drag & drop from/to the filesystem
- Contextual menu with Import, Export, Copy, Paste, Clear, Rename
- Indicator of the IR currently loaded in the active preset
- Double-click to load into the Cab/IR block

### Integration with preset editor

- When selecting a Cab/IR block with IR category, show the IR Select
  parameter (1–128) and the Low Cut, High Cut, Level sliders
- Double-clicking an IR in the list should switch the current Cab/IR block
  to IR category if it isn't already, and select that index
