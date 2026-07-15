# PodGo Lab — Roadmap and pending specs

At-a-glance status (June 2026). The project is a clone of POD Go Edit for
Linux that speaks the USB vendor protocol of the Helix/HX family. What already
works and what's missing, with actionable specs to pick up.

## ✅ Done and validated against real POD Go (0e41:4247)

- USB bulk transport (iface 0, ep 0x01/0x81), 5-packet handshake,
  session recovery. Code: `src/openpodgo/{usb_transport,session,packets}.py`.
- Streaming + preset parsing (MessagePack, pattern scan). Code:
  `src/openpodgo/preset.py`.
- High-level `PodGo` API (`connect`, `list_setlists`, `list_presets`).
  Code: `src/openpodgo/device.py`.
- MIDI via ALSA/`amidi` (PC, CC32 setlist, snapshots, FS, tap).
  Code: `src/openpodgo/midi.py`.
- PySide6 UI (preset browser, dark theme). Code: `src/openpodgo/ui/`.
- **Factory and User setlists: complete listing (slots 0-127) + recall by click,
  correct.** The slot is the position in the stream; the index is a stable ID
  (see spec 01, resolved).
- **Complete active preset decoded** (object 22, l6-helix container):
  block chain + models + params + snapshots, validated against `.pgp`
  and live. Code: `src/openpodgo/{l6helix,catalog}.py`, `tools/preset_show.py`.
- 36 offline tests passing (`tests/`). RE tools: `tools/{probe,diag,
  stream_explore,capture,preset_explore,preset_show}.py`.
- Base protocol spec: `docs/protocol.md` and `https://github.com/allansomensi/openhx`.

## 🚧 In progress: visual editor (`editor-ui` branch, June 2026)

Clone of POD Go Edit's editing view, **in-memory editing** (writing to
the pedal is still spec 03). Done and tested offline (76 tests):

- **Complete catalog (571 models, 436 interchangeable)** from official
  POD Go Edit resources (`captures/podgo-edit-res`: the index of
  `PodGo.sym` IS the wire_id, validated 16/16; `*.models` = display names,
  defaults, ranges; `PGModelCatalog.json` = categories), validated against
  the `.pgb` backup (which contains complete Factory+User in .pgp format)
  and vendor dumps. `src/openpodgo/{l6res,pgb,catalog}.py`, `data/models.json`,
  `tools/build_catalog.py`.
- **In-memory editor + .pgp export** validated against official exports
  (complete round-trip: blocks, footswitch, controllers, snapshots).
  `src/openpodgo/editor.py`. New RE: actual semantics of body[4]
  (controllers by @controller number, not by slot) — lab notes corrected.
- **UI**: chain strip + param panel + model switching + snapshots via
  MIDI + export. `src/openpodgo/ui/editor.py`, integrated in `main_window.py`
  ("Edit active preset").
- **Wire ID harvesting** (`src/openpodgo/harvest.py`, validated offline).

Pending **with pedal connected** (close the app first):

1. `python tools/harvest_catalog.py` — traverses Factory+User via MIDI (read
   only). No longer needed for the bulk of the catalog (official resources
   cover it): useful for VALIDATING inferences and resolving the ~70 uncertain
   models (are `@stereo`/`IrData` blob values?) and the on-wire categories
   without data (reverbs, dynamics, pitch, looper).
2. `python -m openpodgo.app` → "Edit active preset" → verify chain and
   values against the POD Go screen; export a `.pgp` and import it into
   POD Go Edit (Windows) as a final test.

## ⏳ Pending (each with its own spec)

| # | Topic | Spec | Status |
|---|-------|------|--------|
| 1 | **User** setlist reading | [01-user-setlist-stream.md](01-user-setlist-stream.md) | ✅ resolved |
| 2 | Read full preset content (blocks/params) | [02-read-full-preset.md](02-read-full-preset.md) | ✅ resolved (reading): object 22 decoded to dataclasses with model catalog, validated against `.pgp` and pedal. See [02-lab-notes.md](02-lab-notes.md) |
| 3 | Writing to pedal (params, snapshots, presets via vendor) | [03-write-to-device.md](03-write-to-device.md) | ✅ resolved (Phase A + B): write channel, packets, API, editor. Pending live validation. |
| 4 | Bidirectional live sync | [04-live-sync.md](04-live-sync.md) | ✅ resolved: EventSession + NotificationReader (QThread) + dispatcher in main_window, 23 tests |
| 5 | Block reorder: state and UI feedback (TODO #2, #3, #4) | [05-block-reorder-ux.md](05-block-reorder-ux.md) | ✅ resolved (offline): `set_preset(keep_state)` preserves the ● and selection on a re-read triggered by a reorder-on-pedal, which also selects the moved block (`to_slot`); the insertion caret is drawn on the real side of the drop. Pending live verification: caret visual feedback (#3) and exact selection of the moved block on pedal (#4). |
| 6 | "Edited preset" indicator on startup (TODO #1) | [06-edited-indicator.md](06-edited-indicator.md) | 🟡 RE offline + plumbing done, **gated pending pedal**: RE discarded an explicit flag (key 117) and showed that the official app tracks "edited" locally; slot fingerprint detection (object 14) was implemented in `PodGo.active_preset_is_edited()` and propagated to the UI (`set_preset(modified=…)`), but remains **inert** behind the `_OBJ14_CRC_CONFIRMED` gate because `crc32` of the blob does NOT reproduce the object 14 checksum. A capture with the pedal is needed to find the real formula and open the gate. See [06-lab-notes.md](06-lab-notes.md). |
| 7 | 2-value params as combobox (TODO #5) | [07-two-value-params-combobox.md](07-two-value-params-combobox.md) | ✅ resolved: ParamRow with QComboBox for bools/discrete + QCheckBox fallback, 5 tests |
| 8 | Effects EQ vs Preset EQ (model subset + icons, Acoustic Sim) | [2026-06-14-spec08-effects-eq-vs-preset-eq-design.md](../superpowers/specs/2026-06-14-spec08-effects-eq-vs-preset-eq-design.md) | ✅ resolved (code + offline tests). Pending live verification. |
| 9 | Bypass/Controller Assignment (window + assignments; S-08/I-04/I-05) | [09-bypass-control-assign.md](09-bypass-control-assign.md) | ✅ resolved (offline): bypass with full CRUD (create/move/clear + label/color, `.pgp` round-trip), controllers with display + Min/Max + clear; `BypassControlPanel` + Ctrl+B toggle + Bypass Assign submenu. **Creating controllers/snapshot-assign on arbitrary params remains RE-blocked** (destination block does not travel in `body[4]`): pending harvest with pedal. |

## How to pick up (quick setup)

```bash
cd ~/openpodgo && source .venv/bin/activate
python -m pytest                 # offline tests (no pedal)
python tools/probe.py            # with pedal: handshake + Factory list
python -m openpodgo.app           # the UI
```

Hardware requirements: POD Go connected via USB and udev rule installed
(`99-podgo.rules` in `/etc/udev/rules.d/`, already done). Only one process can
hold the USB interface at a time (close the app before running tools).

## Method notes (important for RE)

- **One USB operation at a time.** Two reads/threads on the device will collide.
- **Fresh handshake per operation** leaves state clean (`session.handshake()`
  drains + restarts). Reading a second setlist without re-handshake desynchronizes.
- Useful raw captures stored in `captures/` (e.g. `user_raw.bin`).
- The user (pedal owner) can verify against the POD Go screen and
  provide the real preset list: use it to validate mappings.
