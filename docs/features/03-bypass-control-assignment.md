# Feature: Bypass/Control Assignment Window (S-08, I-04, I-05)

**Current status:** ❌ Not implemented (S-08: full window; I-04: Controller
Assignments; I-05: Bypass Assign)

Reference: _POD Go Edit Pilot's Guide v2.50_,
"Bypass & Controller Assignment" pp. 27–34,
"Bypass Assignment Indicators" p. 22, "Controller Assignment Indicators" p. 24.

---

## Overview

The Bypass/Control panel is a sub-panel of the Inspector (Edit panel) that
allows creating, editing, and deleting assignments for:

1. **Bypass Assign**: which footswitch or EXP pedal controls a block's bypass
2. **Controller Assign**: which footswitch or EXP pedal controls a specific parameter
3. **Snapshot Assign**: which parameters are stored per snapshot

Each preset can have up to **64 total assignments**. Each footswitch or EXP
pedal can have up to **8 assignments**.

## Bypass/Control Window Layout

The panel is shown/hidden with a toggle button inside the Edit panel
(or `Window > Show/Hide Bypass/Control`, or `Ctrl/Cmd + B`).

```
┌─────────────────────────────────────────────────┐
│  [Parameter Menu ▼]  (lists all params of the  │
│   selected block)                               │
├─────────────────────────────────────────────────┤
│  [FS1] [FS2] [FS3] [FS4] [FS5] [FS6]           │
│  [FS7] [FS8] [EXP Toe] [EXP 1] [EXP 2]         │
│  [Snapshots] [None]                             │
├─────────────────────────────────────────────────┤
│  Controller selectors with indicators:          │
│  - Customizable label (text + LED color)        │
│  - Category color ring                          │
│  - Italic if existing assignments present        │
│  - Menu button (ⓘ) on hover for Rename/Color   │
├─────────────────────────────────────────────────┤
│  (Only for controller assignments)              │
│  Min: [====●=========] Max: [====●=========]    │
│  (For bypass with EXP pedal: Position + Wait)   │
└─────────────────────────────────────────────────┘
```

### Parameter Menu

Lists all parameters of the selected block. To the right of each
parameter, in brackets, it shows existing assignments:
`[Bypass: FS1]`, `[Position: EXP 1]`, `[Drive: Snapshot]`, etc.

### Controller Selectors

- FS1–FS8: footswitches 1–8
- EXP Toe: pedal toe switch
- EXP 1 / EXP 2: expression pedals
- Snapshots: button that appears only when the parameter is NOT Bypass
  (bypass is already controlled by snapshot by default)
- None: clears the assignment

Each FS1–FS6 selector has:

- Label: customizable text (appears on the pedal's screen in Stomp Mode)
- Color ring: footswitch LED color on the pedal
- If there are multiple assignments, label reads "Multiple (N)"
- On hover a menu button appears with options: Rename, Reset Name, Footswitch Color

## Assignment types

### Bypass Assignment

Assigns a block's on/off toggle to a footswitch or EXP pedal.

- Can be done from:
  1. Signal Flow: click the assignment indicator above the block → "Bypass Assign panel"
  2. Bypass/Control Window: Parameter > "Bypass" → click selector
  3. Right-click on block > Bypass Assign > footswitch
- **EXP pedal bypass**: configured with Position sliders (pedal position where
  it triggers, e.g.: 5%) and Wait (ms delay before triggering, e.g.: 300ms)
- **Multi-bypass**: multiple blocks can share a footswitch for simultaneous
  toggle. The logic can be inverted so one block turns off while another
  turns on at the same time

### Controller Assignment

Assigns a parameter's value to an EXP pedal or footswitch.

- With EXP pedal: the parameter varies continuously between Min and Max based
  on pedal position
- With footswitch: the parameter has two fixed values (Min = Off state,
  Max = On state of the footswitch)
- The behavior can be "inverted": Min=100%, Max=0%

### Snapshot Assignment

Assigns a parameter to have its value saved per snapshot.

- Block bypass is automatically saved per snapshot
- For other parameters, a snapshot assignment must be created explicitly
- Shortcut: `Alt+Click` on any slider in the Edit panel to create/remove
  snapshot assignment

### Auto Assign Feature

By default, when a model is added to an empty Effects block, POD Go
auto-assigns its bypass to the first free FS1–FS6. This is configurable from
the device: `Global Settings > Switches/Pedals > FS Auto Assign On/Off`.

- Wah and Volume come pre-assigned to the Toe Switch
- Preset EQ → FS1, FX Loop → FS2 in New Presets
- If a Clear is done on an auto-assignment, Auto Assign may re-assign
  when the model is changed

## Existing assignments in New Presets

| Block | Bypass | Controller |
|-------|--------|------------|
| Wah | EXP Toe | Position → EXP 1 |
| Volume/Pan | EXP Toe | Position → EXP 2 |
| Preset EQ | FS1 | — |
| FX Loop | FS2 | — |

## The Assignments List Window

When hovering over a FS with multiple assignments, a menu button appears.
Click → "See All Assignments" → popup window listing all assignments for
that controller, with an X button to delete individually and "Clear All" to
delete everything.

## Customizing Footswitch Label & LED Color

Inside the Bypass/Control window:

1. **Rename label**: hover over FS1–FS6 → menu button → Rename (or
   direct double-click on the text)
2. **LED Color**: menu button → Footswitch Color → color selector
   (Auto = category color, or specific color, or None)
3. **Reset Name**: menu button → Reset Name to return to default

Custom label and color persist even when the assigned model is changed.

## What needs to be implemented in PodGo Lab

### Data layer

1. Controller assignments are already read from the blob (mapping in
   `l6helix.py`). Writing is missing: when the user assigns a parameter to
   a FS/EXP/Snapshot, the MessagePack body must be mutated and serialized
2. Understand the assignment structure in the blob (keys ~43–50).
   See `docs/specs/02-lab-notes.md`
3. Bypass Assigns use a different mechanism than Controller Assigns
   in the protocol. Review capture data

### UI

- [ ] Toggle button in the Edit panel to show/hide Bypass/Control window
- [ ] Parameter menu with all parameters of the selected block
- [ ] Grid of FS1–FS8, EXP Toe, EXP 1/2, Snapshots, None buttons
- [ ] Existing assignment indicators (italic label, color ring)
- [ ] For EXP pedal: show Min/Max sliders (controller) or Position/Wait (bypass)
- [ ] For footswitch controller: show Min/Max sliders for Off/On value
- [ ] Assignments List window for controllers with multiple assignments
- [ ] Right-click on Signal Flow blocks → "Bypass Assign" submenu
- [ ] Click assignment indicator above block → Bypass Assign pop-up panel
- [ ] Alt+Click shortcut on slider for snapshot assign
- [ ] Footswitch label and color customization in Bypass/Control window
- [ ] Assignment icons (camera, pedal, footswitch) next to the slider
