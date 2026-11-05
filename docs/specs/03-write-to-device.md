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

## Resolved: on-wire rules for `set_param` (op 30, key 119)

Verified live against the pedal (firmware 2.01). These rules decide whether a
write is applied or silently discarded — each one bit us in the UI:

1. **The value's MessagePack type must match the parameter's stored type.**
   An int parameter (cab `Mic`) applies `119: 8` and answers `103: 255,
   104: {111: -3}` for `119: 8.0`; a float parameter (`Distance`) is the exact
   opposite. So the editor keeps the on-wire type (`PresetEditor.set_param`)
   and the UI passes that value through instead of `float(value)`.
2. **Bool parameters are not writable through op 30.** `true`/`false`, `1`/`0`
   and `1.0`/`0.0` all answer 255. They stay in-memory/exported (`.pgp`) only;
   the UI skips them instead of reporting a failure.
3. **The response is the framed echo, and it echoes the command's tx id
   (`k102`).** It arrives in ~2 ms; the 16 B acks arrive 100–250 ms later and
   carry no status. Draining until timeout cost ~420 ms per write (a 50-param
   save took 23 s); `WriteSession.send_write` now stops at its own echo and
   leaves the acks for the next drain.
4. **Reads do not invalidate the write channel.** A write right after a read,
   or right after a preset change, applies with the current cursor (verified
   with 50 interleaved writes). `_read_since_write` is now only a recovery
   flag, set when a write fails. The exception is a full chain dump (op 21):
   it does force a fresh write handshake because the flow control desyncs.
5. **The write must hold the transport lock.** The IN endpoint is shared with
   the read and event channels: the live-sync poller was reading our echo
   between write and drain, so the first attempt failed with "no response from
   channel …" and only the retry (which reconnects) applied it. `send_write`
   and `send_write_chunked` now hold `transport.lock` (reentrant) for the whole
   write→drain sequence.

Result: ~20 ms per parameter write, and the whole editor's 50 parameters are
flushed before a save in ~1 s.

