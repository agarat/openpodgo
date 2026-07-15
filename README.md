# openpodgo

**An open-source editor for the [Line 6 POD Go](https://line6.com/podgo/) on Linux** — a community clone of *POD Go Edit*.

openpodgo talks to the pedal over the Helix/HX family's USB **vendor protocol**
(bulk transfers + presets in MessagePack), reverse-engineered by the community
and adapted to the POD Go (`0e41:4247`). It runs where the official editor does
not: Linux.

> ⚠️ **Unofficial.** This project is not affiliated with, endorsed by, or
> supported by Yamaha Guitar Group / Line 6. Use at your own risk. See
> [Disclaimer](#disclaimer).

---

## What it does

- **USB protocol layer**, validated against a real POD Go (`0e41:4247`):
  device open, session handshake, streaming and parsing of all 128 presets
  (MessagePack), reading the active preset, and writing parameters / block
  reordering back to the pedal via the vendor protocol.
- **Preset librarian** — browse the Factory and User setlists; recall a preset
  with a click.
- **Visual chain editor** (PySide6, dark theme) — signal-flow view, block
  inspector, model swapping, parameter editing, bypass/controller assignment,
  snapshots, and bidirectional live-sync (changes on the pedal update the UI).
- **`.pgp` import/export** compatible with the POD Go Edit / CustomTone format.
- **MIDI** helpers over ALSA (`amidi`): program change, setlist select,
  snapshots, footswitches, tap.

## What it does **not** do (yet) / limits

- **It is unofficial and reverse-engineered.** A firmware update can change the
  protocol and break things. Development has tracked POD Go firmware up to
  **v2.01**; other versions are untested.
- **No proprietary assets are bundled.** Out of the box the UI uses neutral
  placeholder icons. To get the real artwork you copy it in yourself — see
  [Icons & artwork](#icons--artwork).
- **Linux-focused.** It may work on other platforms with `libusb`, but only
  Linux is tested.
- Some features are work-in-progress; see [`docs/specs/00-roadmap.md`](docs/specs/00-roadmap.md).
- **Back up your presets.** Writing to hardware always carries risk.

## Requirements

- Linux, Python **3.10+**
- A POD Go connected over USB
- For the UI: a Qt-capable desktop (PySide6 is installed via the `ui` extra)

## Install

```bash
git clone https://github.com/agarat/openpodgo.git
cd openpodgo
python3 -m venv .venv && . .venv/bin/activate
pip install -e '.[dev,ui]'     # library + tests + UI
```

### USB access without sudo

```bash
sudo cp 99-podgo.rules /etc/udev/rules.d/99-podgo.rules
sudo udevadm control --reload-rules && sudo udevadm trigger
# then reconnect the POD Go
```

## Run

```bash
python -m openpodgo.app        # or: openpodgo   (launches the UI)
```

## Icons & artwork

openpodgo ships **no** Line 6 / POD Go Edit artwork. Without it, the UI falls
back to neutral placeholder icons (fully usable). To get the real model
thumbnails, category icons and logos, copy the `res/` folder from an existing
**POD Go Edit** installation into the repository root:

| OS        | POD Go Edit resources folder |
|-----------|------------------------------|
| Windows   | `C:\Program Files (x86)\Line6\POD Go Edit\res` |
| macOS     | inside the `POD Go Edit.app` bundle (`.../Contents/.../res`) |

```bash
# from the repo root, with <SRC> = the res folder above
cp -r "<SRC>" ./res
```

The app picks it up automatically on the next launch — real icons replace the
placeholders. `res/` is git-ignored and is **never** redistributed by this
project; it stays on your machine.

## A note on the model catalog

The app ships `src/openpodgo/data/{models,controls,icon_map}.json`: factual
id → name → parameter-range mappings needed to interpret presets. These are
*derived* from the official POD Go Edit resources (they are data, not artwork or
code). They let openpodgo work out of the box; `tools/build_catalog.py` can
regenerate them from your own POD Go Edit installation.

## Development

```bash
python -m pytest                       # offline test suite (no pedal needed)
```

The suite runs entirely offline against small, sanitized fixtures under
`tests/fixtures/`. In a fresh clone (no proprietary resources present) it runs
**315 tests**; a further 28 are skipped because they need the official POD Go
Edit resources or your own USB captures locally.

RE / hardware tools live in `tools/` (they talk to a real pedal — close the app
first, since only one process can claim the vendor interface):

```bash
python tools/probe.py                  # open, handshake, list presets
python tools/capture.py --label "..."  # labeled capture for RE
```

## Project structure

- `src/openpodgo/` — the library: `usb_transport`, `session`, `packets`,
  `preset`, `l6helix`, `catalog`, `device`, `editor`, `midi`, and `ui/`.
- `tools/` — reverse-engineering / validation scripts (run against a real pedal).
- `docs/` — `protocol.md` and the numbered RE `specs/`.
- `tests/` — offline test suite and sanitized fixtures.

## Contributing

Issues and pull requests are welcome. The project is documented **in English**;
the reverse-engineering knowledge lives in `docs/`. If you own a POD Go, the
most valuable contributions are captures/validation against firmware versions
other than v2.01. Please don't commit proprietary Line 6 assets or personal
device backups.

## Acknowledgements

Built on the community's reverse-engineering of the Helix/HX USB protocol:

- [**openhx**](https://github.com/allansomensi/openhx) (MIT) — the protocol
  templates were ported from its HX Stomp XL documentation and adapted to POD Go.
- [**helix_usb**](https://github.com/kempline/helix_usb) (MIT) — early Helix/HX
  USB reverse-engineering.

See [`NOTICE`](NOTICE) for details. No code or docs from those projects are
redistributed here.

## Disclaimer

This is an independent, unofficial project. It is not affiliated with, endorsed
by, or supported by Yamaha Guitar Group / Line 6. "Line 6", "POD Go", "POD Go
Edit" and "Helix" are trademarks of their respective owners, used here only to
describe interoperability. No official assets, manuals, or fonts are
distributed. Interacting with your hardware is at your own risk.

## License

[MIT](LICENSE) © 2026 Arnaldo Garat
