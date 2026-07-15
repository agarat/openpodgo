# Feature: Preferences Window (P-01)

**Current status:** ❌ Not implemented

Reference: _POD Go Edit Pilot's Guide v2.50_, "Preferences and About Box" pp. 36–37.

---

## Overview

The Preferences window has 3 tabs: General, Presets/IRs, Device Settings.

**Access:**
- `POD Go Edit > Preferences` (Mac) / `Help > Preferences` (Windows)
- Click the gear icon (⚙️) in the bottom-left corner of the main window
- Click the "POD Go" logo in the top-left corner

## Tab: General

```
┌──────────────────────────────────────────────┐
│  [General] [Presets/IRs] [Device Settings]  │
├──────────────────────────────────────────────┤
│                                              │
│  Check for Updates                           │
│  [Check for Updates] button                  │
│                                              │
│  (Opens the Updater to search for and install│
│   software/firmware updates)                 │
│                                              │
└──────────────────────────────────────────────┘
```

## Tab: Presets/IRs

```
┌──────────────────────────────────────────────┐
│  [General] [Presets/IRs] [Device Settings]  │
├──────────────────────────────────────────────┤
│                                              │
│  Stereo IR Import                            │
│  When a stereo IR .wav file is imported, it  │
│  must be converted to mono.                  │
│                                              │
│  ○ Left (factory default)                    │
│  ○ Right                                     │
│  ○ Sum (sum both channels to mono)           │
│                                              │
└──────────────────────────────────────────────┘
```

## Tab: Device Settings

```
┌──────────────────────────────────────────────┐
│  [General] [Presets/IRs] [Device Settings]  │
├──────────────────────────────────────────────┤
│                                              │
│  EXP 2 - FS7/8                               │
│  Toggle the jack's functionality between:    │
│                                              │
│  ○ EXP 2 (external expression pedal)         │
│  ○ FS7/8 (single or dual footswitch)         │
│                                              │
│  FS7/8 Function (only if FS7/8 is active):   │
│  ○ Stomp 7/8                                 │
│  ○ Bank Up/Down                              │
│  ○ Preset Up/Down                            │
│  ○ Snapshot Up/Down                          │
│                                              │
└──────────────────────────────────────────────┘
```

## Restore Factory Settings

Button in the bottom-left of the Preferences window:
- Resets only Presets/IRs and Device Settings options to factory values
- Does NOT affect the device's Global Settings or other adjustments

## Implementation considerations

### Data layer

- App preferences can be saved in a local file (JSON/YAML)
  or use Qt's QSettings
- Device Settings (EXP2/FS7/8) probably communicate with the device
  via USB Global Settings messages (object not yet identified)
- Stereo IR Import is a local app preference

### UI

- [ ] Window with QTabWidget (3 tabs)
- [ ] General tab: Check for Updates button that invokes the Updater
- [ ] Presets/IRs tab: radio buttons for stereo IR import
- [ ] Device Settings tab: radio buttons for EXP2 vs FS7/8 and combo for
  FS7/8 Function (contextual based on selection)
- [ ] Restore Factory Settings button
- [ ] Done / OK / Cancel button
- [ ] Persistence with QSettings
