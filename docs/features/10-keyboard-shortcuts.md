# Feature: Keyboard Shortcuts (P-05)

**Current status:** 🟡 Some shortcuts (Ctrl+S, etc.). Most are missing.

Reference: _POD Go Edit Pilot's Guide v2.50_, "Keyboard Shortcuts" pp. 56–64.

---

## Summary

The PDF's complete shortcut table has ~100 combinations organized by
context (Librarian focus, Signal Flow focus, Inspector focus). Many shortcuts
only work when the correct panel has focus.

## Focus system

There are 3 main panels. `Tab` cycles between them; `Shift+Tab` in reverse.
Focus is indicated by a blue triangle in the top-left corner of the active
panel.

- **Librarian**: Factory setlist, User setlist, IRs list
- **Signal Flow**: the block chain
- **Inspector**: Edit panel / Model Select panel / Bypass/Control window

## Global shortcuts

| Action | Mac | PC | Notes |
|--------|-----|----|-------|
| Window Focus (forward) | Tab | Tab | Cycles Librarian → Signal Flow → Inspector |
| Window Focus (reverse) | Shift+Tab | Shift+Tab | |
| Tap Tempo | T | T | Rhythmic tapping |
| Tap Tempo Mode | Cmd+T | Ctrl+T | Cycles Per Snapshot / Per Preset / Global |
| Tap Tempo value edit | Cmd+Alt+T | Ctrl+Alt+T | Selects the numeric field |
| POD Go Pilot's Guide | F1 | F1 | Opens the PDF |
| About Box | Cmd+? | Ctrl+? | App version |
| Preferences | Cmd+, | Ctrl+, | |
| Quit | Cmd+Q | Ctrl+Q | |

## File Menu

| Action | Mac | PC | Context |
|--------|-----|----|---------|
| Save Preset | Cmd+S | Ctrl+S | Any |
| Save Preset As | Cmd+Shift+S | Ctrl+Shift+S | Any |
| Import Preset/IR | Cmd+I | Ctrl+I | Librarian |
| Export Preset/IR | Cmd+E | Ctrl+E | Librarian |
| Import Setlist | Cmd+Alt+I | Ctrl+Alt+I | Setlist focus |
| Export Setlist | Cmd+Shift+E | Ctrl+Shift+E | Setlist focus |

## Edit Menu

| Action | Mac | PC | Librarian | Signal Flow | Inspector |
|--------|-----|----|-----------|-------------|-----------|
| Undo | Cmd+Z | Ctrl+Z | — | ✓ | ✓ |
| Redo | Cmd+Shift+Z | Ctrl+Shift+Z | — | ✓ | ✓ |
| Cut | Cmd+X | Ctrl+X | — | ✓ (Effects blocks) | — |
| Copy | Cmd+C | Ctrl+C | Preset/IR | Block | — |
| Paste | Cmd+V | Ctrl+V | Preset/IR | Block | — |
| Clear | Cmd+Delete | Ctrl+Delete | IR | Block (Effects) | — |
| Select All | Cmd+A | Ctrl+A | ✓ | — | — |
| Rename | Cmd+R | Ctrl+R | Preset/IR | — | — |

## Snapshots Menu

| Action | Mac | PC |
|--------|-----|----|
| Copy Snapshot | Cmd+Shift+C | Ctrl+Shift+C |
| Paste Snapshot | Cmd+Shift+V | Ctrl+Shift+V |
| Snapshot 1 | Cmd+1 | Ctrl+1 |
| Snapshot 2 | Cmd+2 | Ctrl+2 |
| Snapshot 3 | Cmd+3 | Ctrl+3 |
| Snapshot 4 | Cmd+4 | Ctrl+4 |

## Window Menu

| Action | Mac | PC | Notes |
|--------|-----|----|-------|
| Show/Hide Bypass/Control | Cmd+B | Ctrl+B | Inspector focus, Edit panel |
| Open Global EQ | Cmd+G | Ctrl+G | Opens Global EQ window |

## Devices Menu

| Action | Mac | PC |
|--------|-----|----|
| Select Device N window | Option+0,1,... | Alt+0,1,... |

## Librarian Shortcuts

| Action | Mac/PC | Context |
|--------|--------|---------|
| F | — | Factory setlist |
| U | — | User setlist |
| I | — | IRs library |
| Enter/Return | — | Load selected preset |
| Shift+Arrow | — | Contiguous multi-select |
| Cmd+Click (Mac) / Ctrl+Click (PC) | — | Non-contiguous multi-select |
| Delay click | — | Rename preset/IR (click, wait, click again) |

## Signal Flow Shortcuts

| Action | Key | Notes |
|--------|-----|-------|
| Select next/prev block | ← → | |
| Block context menu | Shift+Enter | |
| Bypass toggle | Spacebar | |
| Select Amp block | A | |
| Select Cab/IR block | C | |
| Select Volume block | V | |
| Select Wah block | W | |
| Select FX Loop block | F | |
| Select Preset EQ block | E | |
| Select Effects 1–4 | 1 2 3 4 | |
| Select Input block | I | |
| Select Output block | O | |
| Display Edit panel | Enter/Return or double-click | |
| Display Model Selector | M | |

## Edit Panel Shortcuts

| Action | Mac | PC |
|--------|-----|----|
| Display Model Selector | M | M |
| Show/Hide Bypass/Control | Cmd+B | Ctrl+B |
| Focus between Edit/Bypass | Cmd+Shift+B | Ctrl+Shift+B |
| Select prev/next parameter | ← → | ← → |
| Snapshot assign/remove | Alt+Click or S | Alt+Click or S |
| Reset parameter to default | D | D |
| Fine adjust | ↑ ↓ | ↑ ↓ |
| Coarse adjust | Shift+↑↓ | Shift+↑↓ |
| Edit numerical value | Enter/Return or double-click | Enter/Return or double-click |
| Open controller panel | Shift+Enter or right-click | Shift+Enter or right-click |
| Note Sync toggle | N | N |

## Bypass/Control Window Shortcuts

| Action | Key |
|--------|-----|
| Focus between Parameter menu / Controllers / Sliders | Shift (cycles) |
| Shift+← | Returns focus to Edit panel |
| Open Parameter menu | Enter |
| Navigate menu | ↑ ↓ |
| Open Assignments List (with FS/EXP selector focused) | A |

## Implementation

### Qt

PySide6 supports `QShortcut` and `QAction` with shortcuts. The focus
system is managed with `QWidget::setFocus()` and `focusWidget()`.

### Approach

Shortcuts can be grouped into 4 classes:

1. **Global**: registered on `MainWindow`, always active
2. **Librarian**: registered on `LibrarianPanel`, active when Librarian
   has focus
3. **Signal Flow**: registered on `SignalFlowPanel`, active when Signal
   Flow has focus
4. **Inspector**: registered on `InspectorPanel` (and sub-panels Edit and
   Bypass/Control), active when Inspector has focus

### Current status

Already implemented:
- `Ctrl+S` (Save Preset)
- Possibly a few more (to be verified)

~90 combinations remain.

### Priority

**MEDIUM.** Not blocking but significantly improves UX. Suggestion:
implement in order of usage frequency:
1. Global (Tab, Spacebar, T, Ctrl+S)
2. Signal Flow (A, C, V, W, E, F, 1-4, Spacebar, ← →)
3. Inspector (M, D, N, S, ↑↓)
4. Librarian (F, U, I, Enter, Ctrl+C/V)
5. Snapshots (Cmd+1-4, Cmd+Shift+C/V)
6. Window (Cmd+B, Cmd+G)
7. Bypass/Control (Shift, A)
