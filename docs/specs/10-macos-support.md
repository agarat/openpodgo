# Spec 10 — macOS support

Status: ✅ resolved (code + offline tests; verified live on macOS 26 / Apple
Silicon against a real POD Go `0e41:4247`).

## Goal

Run openpodgo natively on macOS: same protocol, same UI, but using the macOS
components underneath. Keep the platform code in one seam so the protocol,
preset and UI layers stay platform-agnostic and a future third OS only has to
add a backend.

## What is actually platform-specific

| Concern | Linux | macOS |
|---|---|---|
| libusb lookup (pyusb) | system install, found by `ctypes.util.find_library` | Homebrew (`/opt/homebrew`) or MacPorts, **not** on pyusb's search path; an old Intel copy under `/usr/local` can be picked and fail to load on arm64 |
| Kernel driver on the vendor interface | must be detached (`usb.core.Device.detach_kernel_driver`) | none; pyusb raises `NotImplementedError` |
| MIDI transport | ALSA rawmidi via `amidi -S` (alsa-utils) | CoreMIDI (no CLI equivalent exists) |
| Permission setup | udev rule (`99-podgo.rules`) | none; a USB device is granted to a single process |
| UI | X11/Wayland desktop | Cocoa; menu roles and app name come from the OS menu bar |

## Design

Two seams, no more:

1. **`src/openpodgo/platform_support.py`** — the only module that inspects
   `sys.platform`:
   - `os_name()` / `is_linux()` / `is_macos()` / `is_supported()`;
   - `has_kernel_driver()` — the transport only detaches on Linux;
   - `find_libusb()` — prefers the macOS install locations **and verifies the
     library dlopen's**, so a wrong-architecture copy is skipped instead of
     turning into a `NoBackendError`;
   - `usb_hint()` / `midi_install_hint()` — the advice shown in the status bar
     is the OS's (udev rule on Linux, `brew install libusb` + "close POD Go
     Edit" on macOS), not a hardcoded Linux message.

2. **MIDI backends** behind `midi.MidiBackend`
   (`find_port(hint)`, `send(port, message)`, `close()`):
   - `midi_alsa.py` (`AlsaBackend`, Linux): `amidi -l` parsing (pure
     `parse_ports()` helper) and `amidi -p <port> -S <hex>`.
   - `midi_coremidi.py` (`CoreMidiBackend`, macOS): CoreMIDI through `ctypes`
     — no new dependency, matching the project's "no extra native
     dependencies" rule.
     - `CoreMidiAPI` is the only class touching the framework: client +
       output port, enumerate destinations by display name, `MIDISend`.
     - `build_packet_list()` is a pure function; the `MIDIPacketList` layout
       was taken from the SDK (`numPackets` at 0, first packet at 4,
       `timeStamp` at 4, `length` at 12, `data` at 14 — **no padding**) and
       verified by sending through a virtual destination.
     - `CoreMidiBackend` wraps the API and is injectable (`api=`), so tests
       drive it with a fake and run on any OS.

`midi.default_backend()` picks the backend; `midi.MidiOut` (the API used by
the UI) keeps building the messages, so the callers never branch on the OS.

## Gotchas found on the way

- **CoreMIDI property keys are initialized lazily.** `kMIDIPropertyName` /
  `kMIDIPropertyDisplayName` / `kMIDIPropertyOffline` read as 0 until the
  first CoreMIDI call, so resolving them eagerly made every property lookup
  fail with `kMIDIUnknownProperty` (status -50). They are now resolved lazily
  and cached.
- **pyusb + Apple Silicon**: `ctypes.util.find_library('libusb-1.0')` returned
  `/usr/local/lib/libusb-1.0.dylib` (x86_64) and `ctypes.CDLL` failed, so
  pyusb reported no backend while libusb *was* installed in `/opt/homebrew`.
- **Exclusive USB access**: on macOS a second process gets "Access denied" on
  `claim_interface`; the message now names the usual culprits.
- **Roboto / assets**: `res/` is optional and the UI already degrades to the
  system font and placeholder icons, so no theme change was needed.

## UI changes

- Status bar: `MIDI <port> (<backend>)` — e.g. `MIDI POD Go (CoreMIDI)` vs
  `MIDI hw:2,0,0 (ALSA)`.
- "Not connected" advice comes from `platform_support.usb_hint()`.
- `QAction.QuitRole` on Quit (macOS application menu) and
  `QApplication.setApplicationName/DisplayName("openpodgo")`.
- `MainWindow.closeEvent` releases the MIDI backend (CoreMIDI client/port).

## Tests

- `tests/test_platform_support.py` — OS mapping, libusb resolution order
  (macOS paths first, unloadable libraries skipped), hint texts.
- `tests/test_midi_backends.py` — `parse_ports` on a captured `amidi -l`,
  `default_backend()` selection per OS, `AlsaBackend` subprocess calls,
  `CoreMidiBackend` with a fake API, but only where they do not need hardware;
  the `MIDIPacketList` layout/packing test runs everywhere.
- CI runs the same offline suite on `ubuntu-latest` (3.10–3.12) and one
  `macos-latest` job.

## Manual verification (done on macOS)

1. `python tools/probe.py` — open + handshake + stream 128 presets over USB.
2. `midi.find_port()` → `"POD Go"`; CoreMIDI send verified against a virtual
   destination (received `b0 45 02`, `c0 05` unchanged).
3. `python -m openpodgo.app` — UI connects, librarian fills, editor loads.

## Out of scope

Windows: pyusb would work with the WinUSB driver and the protocol layer is
already portable, but MIDI needs a third backend (WinMM). Tracked as future
work, not part of this spec.
