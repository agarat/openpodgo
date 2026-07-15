# Spec 03 — Writing to the pedal (Phase 3)

## Objective

Modify the pedal's state from the app via the **vendor protocol**: change a
block parameter, toggle bypass, switch preset/snapshot, and eventually upload
an entire preset. (Preset/snapshot switching via **MIDI** already works:
`midi.py` with CC32+PC, CC69 snapshot, CC49-56 FS.)

## Status and dependencies

- **Blocked by Spec 02**: to write a parameter you first need to know how
  it is addressed (block + parameter) in the preset representation. Do 02 first.
- No write packets identified yet. Everything captured so far is
  reading (device→host).

## RE plan

> **Update (Phase A, Jun 2026):** Write packets were identified in USBPcap
> captures of POD Go Edit (Windows), not by black-box RE.
> See [03-lab-notes.md](03-lab-notes.md) for the detailed analysis.
> Phase B implements the builders, API and live validation.

1. **Identify the "set parameter" packet.** Without a capture of the official
   editor (doesn't run on Linux), the path is black-box:
   - Change ONE parameter from the pedal and capture what it emits (`tools/capture.py`)
     — some physical changes generate device→host traffic that reveals the
     format of a parameter (block, param index, value).
   - Build by analogy a host→device packet with that format and send it;
     observe the pedal's screen (the user confirms). Start with something
     reversible and visible (e.g. a block's level).
2. **Safe read-modify-write.** Always: read the current value, change ONE
   parameter, write, verify on the pedal. Back up the preset (`.pgp`) first.
3. **Error recovery.** Apply `https://github.com/allansomensi/openhx`
   (drain + re-handshake with backoff) on timeouts.

## Suggested order (lowest to highest risk)

1. Switch preset/snapshot via vendor (alternative to MIDI; validates the write
   channel with something low-risk).
2. Toggle bypass on a block.
3. Set a continuous parameter (level/gain).
4. Upload a complete preset (high risk; last).

## Risks and mitigations

- Writing incorrectly can **corrupt a preset**: always back up `.pgp` first and
  change one parameter at a time with visual verification.
- Keep **a single USB operation at a time** and the strict
  request→response pattern (see `usb_transport.request`).

## Success criterion

Change a parameter from the app and see/hear it change on the pedal, without
corrupting the preset, with the app and pedal showing the same value.
