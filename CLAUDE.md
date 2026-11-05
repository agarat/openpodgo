# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is this

Open-source editor for **Line 6 POD Go on Linux and macOS** — a clone of POD Go Edit.
It communicates with the pedal via the USB vendor protocol of the Helix/HX
family (bulk transfers + presets in MessagePack), reverse-engineered by the
community (openhx, helix_usb) and adapted to POD Go (`0e41:4247`).

Platform-specific code is deliberately confined to two seams: `platform_support.py`
(OS detection, libusb lookup, user-facing hints) and the MIDI backends
(`midi_alsa.py` for Linux, `midi_coremidi.py` for macOS). The protocol,
presets and UI are platform-agnostic.

## Commands

```bash
. .venv/bin/activate                   # activate the venv (always first)
python -m pytest                       # 357 tests, all OFFLINE (no pedal)
python -m pytest tests/test_editor.py  # a single file
python -m pytest tests/test_editor.py::test_nombre   # a single test
python -m openpodgo.app                 # launch the UI (or: openpodgo)
```

Installation: `pip install -e '.[dev,ui]'`. Linux needs `libusb-1.0-0`, `alsa-utils`
(`amidi`) and the udev rule (`99-podgo.rules` → `/etc/udev/rules.d/`, see README);
macOS needs `libusb` (`brew install libusb`) and nothing else — MIDI goes through
CoreMIDI and there are no udev rules.

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

- **`midi.py`** — MIDI commands (PC, CC32 setlist, snapshots, footswitches,
  tap) on top of a `MidiBackend` selected per OS by `default_backend()`:
  `midi_alsa.py` shells out to `amidi -S` (Linux), `midi_coremidi.py` talks to
  CoreMIDI through `ctypes` (macOS). Neither adds a native dependency, and
  `MidiOut` (the public API used by the UI) stays platform-agnostic.
- **`platform_support.py`** — the only place that inspects `sys.platform`:
  OS name, `has_kernel_driver()` (udev detach on Linux), `find_libusb()` (with
  the macOS Homebrew/MacPorts paths) and the hints shown in the status bar.

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

Verified live rules that decide whether a write is applied (all bit us — see
`docs/specs/11-param-write-pipeline.md`):

- **`k119` must carry the parameter's on-wire MessagePack type.** An int
  parameter rejects `8.0` (`103: 255, 104: {111: -3}`) and a float one rejects
  `1`. Never `float(value)` a value on its way to the pedal: the editor keeps
  the type (`PresetEditor.set_param`) and the UI forwards it.
- **Bool parameters are not writable via op 30** (255 for `true/false`,
  `1/0`, `1.0/0.0`): keep them in memory/`.pgp` and skip them when writing.
- **The status arrives first**: the framed echo (echoes our tx id `k102`) comes
  in ~2 ms; the 16 B acks 100–250 ms later and carry no status. `send_write`
  stops at its own echo (~20 ms/write) instead of draining to a timeout.
- **Writes hold `transport.lock`** (reentrant): the IN endpoint is shared with
  the read and event channels, and the live-sync poller otherwise steals the
  echo (symptom: first attempt fails with "no response from channel …").
- Reads do **not** invalidate the write channel (`_read_since_write` is only a
  recovery flag); a full chain dump (op 21) is the exception and forces a fresh
  write handshake.
- The UI writes on **every** change (coalesced ~80 ms, flushed on release), and
  `_save_to_pedal` flushes the editor's parameters before op 71.
- In the pedal's `set_param` **notifications** (op 30: a physical knob turn and
  the echo of our own write) the parameter index is **key 28**; key 26 is 0.
  Read it with `notifications._param_index()` — reading 26 made every event look
  like parameter 0 (a knob change moved the block's first parameter).
