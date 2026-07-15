# Checklist for the Windows session with POD Go Edit

Loot to bring back (copy everything to `~/openpodgo/captures/` on return).

## 1. USB captures with Wireshark (most valuable)

Install Wireshark checking the **USBPcap** option in the installer (may require
a reboot). Capture on the "USBPcap" interface that shows pedal traffic.
One capture per scenario, short, and note exactly what was done:

| File | Scenario |
|---|---|
| `win_connect.pcapng` | Start capture → open POD Go Edit → wait for everything to load → stop. (Official handshake + how it reads presets/active preset/globals.) |
| `win_knob.pcapng` | Editor already open → start capture → move ONE knob (Drive) → stop. (Live sync, spec 04.) |
| `win_save.pcapng` | Start capture → save the preset to the pedal (Ctrl+S) → stop. (First WRITE operation, spec 03!) |
| `win_preset_change.pcapng` | Start capture → click on another preset → stop. |
| `win_snapshot.pcapng` | Start capture → change snapshot → stop. |

Tips: close other noisy USB apps; if there are multiple USBPcap interfaces, pick
the one that shows packets when touching the pedal; no need to filter, raw is fine.

## 2. .pgp exports (the two presets already dumped via vendor)

- `spec02_a.pgp` ← **"BassPreset"** (User setlist, slot 9). Ideally with
  Drive returned to ~43 (it was left at 47 unsaved).
- `spec02_ilabaca.pgp` ← **"Ilabaca"** (User setlist, slot 10).

Two dump-vendor/.pgp pairs make the key mapping much more robust than one.

## 3. Versions (note down, e.g. in a txt)

- POD Go Edit version (Help/About) and firmware reported by the pedal.
  The vendor blob says `v2.00-5-g665e64e` — confirm if it matches.

## 4. Optional (cheap since you're there)

- A complete backup from POD Go Edit (`.pgb` or whatever they call it) — another
  container of the same format to cross-reference.
