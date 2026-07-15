# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this

Open-source editor for **Line 6 POD Go on Linux** — a clone of POD Go Edit.
It communicates with the pedal via the USB vendor protocol of the Helix/HX
family (bulk transfers + presets in MessagePack), reverse-engineered by the
community (openhx, helix_usb) and adapted to POD Go (`0e41:4247`).

## Commands

```bash
. .venv/bin/activate                   # activate the venv (always first)
python -m pytest                       # 261 tests, all OFFLINE (no pedal)
python -m pytest tests/test_editor.py  # a single file
python -m pytest tests/test_editor.py::test_nombre   # a single test
python -m openpodgo.app                 # launch the UI (or: openpodgo)
```

Installation: `pip install -e '.[dev,ui]'`. USB access without sudo: copy
`99-podgo.rules` to `/etc/udev/rules.d/` and reload udev (see README).

**Important about tests:** all tests run without the pedal (mocks/fixtures from
real captures). Hardware verification is manual and done by the pedal owner;
close the app before running `tools/*.py` with the pedal (only one process can
hold the vendor interface).

## Architecture

The library (`src/openpodgo/`) is a layered stack; each layer only knows the one
below it. From bottom to top:

1. **`usb_transport.py`** — opens the device, claims the vendor interface
   (iface 0, ep `0x01`/`0x81`), bulk write/read with the strict
   request→response pattern and "stale data drain". `DeviceInfo` describes the topology.
   Has a `_lock` for concurrent readers (NotificationReader).
2. **`packets.py`** — raw protocol templates (8 B transport header + MessagePack
   body). Ported from openhx (HX Stomp XL) and adjusted for POD Go. Only
   variable parts are parameterized (seq, cursor, offset). Helpers
   `decode_open_body` / `decode_*`.
3. **`session.py`** — 5-packet handshake and session recovery.
   Three classes: `Session` (preset operations), `WriteSession` (write channel,
   with its own cursor) and `EventSession` (notification channel).
4. **`device.py`** — `PodGo`, the high-level API used by the UI and scripts.
   `connect`, `list_setlists`, `list_presets`, `active_preset`, `set_param`,
   `set_model`, `write_chain_blob` (block reorder), `save_preset`,
   `change_preset`, snapshots, and the event channel (`open_event_channel` /
   `poll_event`). Encapsulates transport + the three sessions.

Preset decoding (orthogonal to the transport stack):

- **`preset.py`** — parsing the 128 presets from the stream (MessagePack,
  pattern scan). `PresetEntry`, `ActiveState`.
- **`l6helix.py`** — decodes the `l6-helix` container of the **active preset**
  (object 22): magic + offset table + a MessagePack map with the block chain,
  models, params and snapshots. The key mapping is validated against
  `.pgp` files (see `docs/specs/02-lab-notes.md`, "Blob ↔ .pgp mapping").
- **`catalog.py`** + `data/models.json` — on-wire id (block key 25) →
  name and param order. Generated from the official POD Go Edit resources
  (`l6res.py`, `pgb.py`, `tools/build_catalog.py`).
- **`editor.py`** — **in-memory** editing of the active preset: mutates the raw
  msgpack `body` (to avoid losing keys) and re-derives the view with `l6helix`.
  `to_pgp` is the inverse of the blob↔.pgp mapping. Writing to the pedal reuses
  this re-serialized body.

UI (`src/openpodgo/ui/`, PySide6, dark theme): `main_window.py` orchestrates;
`librarian.py` (preset browser), `editor.py`/`signal_flow.py`/
`inspector.py` (visual chain editor), `assets.py`/`theme.py`/`palette.py`
(resources). **`notifications.py`** — `NotificationReader`, a `QThread` that
reads the IN endpoint in the background for bidirectional live-sync (pedal
changes → UI). It pauses/resumes to avoid competing with writes.

- **`midi.py`** — MIDI commands via ALSA through `amidi -S` (PC, CC32 setlist,
  snapshots, footswitches, tap). No extra native dependencies.

## How the project grows

Work is organized in **numbered specs** under `docs/specs/` with a roadmap at
`docs/specs/00-roadmap.md`. "Let's continue with the plan" = the next pending
spec in the roadmap. The RE protocol lives in `docs/protocol.md` and
`https://github.com/allansomensi/openhx`; per-spec notes in `docs/specs/0N-lab-notes.md`.

`tools/` are validation/RE scripts against the real pedal (`probe.py`,
`diag.py`, `capture.py`, `preset_show.py`, `harvest_catalog.py`,
`build_catalog.py`). `captures/` and `res/` contain RE data and the official
POD Go Edit assets (these are **not published**).

## Write protocol (spec 03)

`set_param` works as follows: raw `block_index`, `param_idx` goes in key 28 of
the body, uses the **write channel** cursor, and `request()` filters by channel.
Chain writing (op 21, block reorder) responds `{102,103:1,104}` while
`set_param`/`save` echo `103: 0` (see `_chain_write_ok`).
`save_preset` has retry. Details in `docs/specs/03-write-to-device.md`.
