# Feature: Global EQ (G-01, G-02, G-03)

**Current status:** ❌ Not implemented

Reference: _POD Go Edit Pilot's Guide v2.50_, "Global EQ Window" pp. 35–36,
"Keyboard Shortcuts" pp. 56+.

---

## Overview

The Global EQ is a 5-band parametric equalizer applied **after** all signal
chain processing, just before the Main 1/4" and Headphone outputs. It is
**global**: not saved per preset or per snapshot — applies to the entire
device at all times.

## Window layout

```
┌──────────────────────────────────────────────────────┐
│  ┌──────────────────────────────────────────────────┐│
│  │                                                  ││
│  │         FREQUENCY RESPONSE GRAPH                 ││
│  │                                                  ││
│  │   +12 ┤                                          ││
│  │      ┤   ● Band 2             ● Band 4          ││
│  │      ┤  ● Band 1    ● Band 3       ● Band 5    ││
│  │      ┤                                           ││
│  │   -12 ┤                                          ││
│  │      └──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──┬──    ││
│  │        20 50 100 200 500 1k 2k 5k 10k           ││
│  └──────────────────────────────────────────────────┘│
│  [Bypass: ● Active]           [Reset]  [Done]       │
├──────────────────────────────────────────────────────┤
│  INSPECTOR PANE                                       │
│                                                       │
│  Band 1: Low Cut (shelving)                           │
│    [Freq: ═══●═══════════]  [Gain: ═══●═══════════] │
│                                                       │
│  Band 2: Parametric                                   │
│    [Freq: ═══●═══════════]  [Gain: ═══●═══════════] │
│    [Q: ═══●══════════════]                           │
│                                                       │
│  Band 3: Parametric                                   │
│    [Freq: ═══●═══════════]  [Gain: ═══●═══════════] │
│    [Q: ═══●══════════════]                           │
│                                                       │
│  Band 4: Parametric                                   │
│    [Freq: ═══●═══════════]  [Gain: ═══●═══════════] │
│    [Q: ═══●══════════════]                           │
│                                                       │
│  Band 5: High Cut (shelving)                          │
│    [Freq: ═══●═══════════]  [Gain: ═══●═══════════] │
└──────────────────────────────────────────────────────┘
```

## Interaction

### Response graph (G-02)

- Each band has a **draggable edit node** (circle) on the graph
- Drag vertically = adjust Gain
- Drag horizontally = adjust Frequency
- Moving a node updates the corresponding sliders in the Inspector pane
  in real time

### Inspector Pane

Each band has adjustable sliders in the following ways:
- Click + drag on the slider
- Click in an empty range of the slider → jumps to that value
- Mouse wheel over slider
- Up/Down buttons to the right of the slider
- Right-click → precise numeric entry
- Double-click on slider → individual reset to flat value (0 dB)

### Bypass (G-03)

- "Bypass" toggle button: enables/disables the Global EQ
- Default: enabled (active), all parameters flat
- Keyboard shortcut `Ctrl/Cmd + Shift + E` toggles bypass
- The bypass state persists across app close/open (saved on the device,
  not in the preset)

### Reset

- "Reset" button: returns all parameters to flat (+0 dB) and bypass to enabled

### Done

- "Done" button (or ESC) → closes the window

## The 5 bands

| Band | Type | Parameters |
|------|------|------------|
| Band 1 | Low Cut (shelving) | Frequency, Gain |
| Band 2 | Parametric | Frequency, Gain (±12 dB), Q |
| Band 3 | Parametric | Frequency, Gain (±12 dB), Q |
| Band 4 | Parametric | Frequency, Gain (±12 dB), Q |
| Band 5 | High Cut (shelving) | Frequency, Gain |

## Implementation considerations

### Data layer

- The Global EQ probably lives in **object 23** of the USB protocol
  (not currently implemented)
- Alternatively it could be part of Global Settings, accessible via
  specific GET/SET messages
- Review captures to identify the object and offsets of each band
- The bypass state is a global flag, not associated with any preset

### UI

- [ ] Independent window (modal or non-modal) opened from
  `Window > Global EQ` or shortcut `Ctrl/Cmd + G`
- [ ] Frequency response graph with 5 draggable edit nodes
- [ ] Inspector pane with 5 slider sections (3 sliders for parametric
  bands, 2 for shelving)
- [ ] Bypass button with state indicator
- [ ] Reset button
- [ ] Done button
- [ ] Bidirectional binding: move node on graph → updates sliders,
  move slider → updates node on graph
- [ ] Keyboard shortcuts to navigate and adjust parameters within the
  window (see keyboard shortcuts p. 56)

### Graphics library

For the frequency response graph:
- QPainter + custom widget (since it's PySide6)
- Logarithmic frequency axis (20 Hz – 20 kHz)
- Linear gain axis (±12 dB)
- Draw the combined curve of all bands
- Draggable nodes per band
- Tooltip on hover showing exact frequency and gain
