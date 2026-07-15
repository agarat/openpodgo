# Spec 01 — Correct reading of the User setlist ✅ RESOLVED

> **Resolved (June 2026).** Two combined causes:
>
> 1. **The external index is a stable preset ID, not the slot.** The slot
>    (= PC number) is the entry's position in the stream. In Factory they
>    coincide because nobody reorders Factory; in User they diverge when
>    moving presets. The spurious "129" was juanitosSOLO (id 129) relocated
>    to slot 36 (10A) — verified against the pedal.
> 2. **The "missing" presets (ids 128-138) arrive in the User's
>    OPEN_STREAM response**, which is not a flat ack (as in Factory) but the
>    first packet of the data message: 24 B of header (total message length
>    in bytes 20-21 LE) + `DC 00 80` + the first ~9 entries. The code was
>    discarding it. Additionally the offset field of chunk-requests is
>    ignored: the device serves the stream sequentially (which is why no
>    base sweep ever found ids 128-138).
>
> Fix: `preset.stream_presets` prepends the OPEN_STREAM response window to
> the buffer; `parse_preset_list` assigns `slot` by stream position;
> the UI uses `PresetEntry.slot`. End-to-end validated: User with
> contiguous slots 0-127 and correct names, Factory without regression,
> stable repeated reads. Fixture: `captures/user_full.bin` +
> `test_parse_real_user_capture`. Details in `docs/protocol.md`.
>
> What follows is the historical description of the bug.

## Problem

The **Factory** setlist reads perfectly (contiguous indices 0-127, index = slot
= Program Change number). The **User** setlist does not read correctly with the
same offset scheme, which misaligns names and breaks recall from the UI.

## What is known (hard data)

Reading the User via `OPEN_STREAM` with byte 34 = 1, base offset 0x1000, step
0x100, 256 B window (see `preset.stream_presets`):

- The stream returns presets with indices **139-255 sequential and clean**.
- **Indices 128-138 are missing** (the first ~11 User presets, including the
  real 01A). They don't appear with any base offset tried (0x0800, 0x0C00,
  0x0E00, 0x0F00, 0x0FC0, 0x1000) — always `min=129`, `has128=False`.
- A spurious index **129** appears inserted mid-chunk (reassembly artifact),
  causing a real preset to be read with the wrong index.
- Each preset's internal map is `{109: name\0, 123: bool, 124: bool,
  125: int}`. **Key 125 is always 0**: it is NOT the slot. There is no slot
  field in the preset; the slot is the external index of the map.

### Relationship to hardware (verified by the user)

- Factory: index = slot (PC). Correct recall.
- User (presets that DO read cleanly): `pedal_slot = index - 129`.
  E.g.: Ilabaca (idx 139) → pedal 03C (PC 10); LerLalonde (idx 140) → 03D (PC 11).
- juanitosSOLO is on the pedal at 10A (PC 36) → its real index should be
  ~165 (36+129), but the current reading places it at the spurious 129.
  Confirms that reassembly corrupts the start of the User stream.

### Per-chunk dump (User, byte34=1, base 0x1000)

```
chunk 0 (0x1000): idx 139-147     (clean)
chunk 1 (0x1100): idx 148-157     (clean)
chunk 2 (0x1200): idx 158-164, 129(spurious), 165-166
chunk 3 (0x1300): idx 167-176     (clean)
...
```
Chunks are ~256 B and carry ~9-10 presets each, sequential, except for the
spurious index. Offset 0x1000 maps to preset 0 in Factory but to preset 139
in User: **the stream addressing differs per setlist**.

## Hypotheses to investigate (in order of likelihood)

1. **Different preamble/registration for User.** Just as Factory has the header
   `DC 00 80` + presets 0.. in its preamble, User might expose 128-138 in an
   initial block that the current `OPEN_STREAM` doesn't request. Check the raw
   response of `OPEN_STREAM` (byte34=1) and `OPEN_PRESETS` for pointers/lengths
   (fields `cd 03 ea`=1002, `65 02`, etc. in the packet).
2. **OPEN_STREAM needs more than byte 34.** The packet carries an id (`cd 03 ea`
   = 1002) and keys 100/101/107. For User perhaps the id or those keys need
   to change, not just the setlist. Compare the `OPEN_STREAM` that HX Edit sends
   for a non-Factory setlist (requires capturing the official editor — unavailable
   on Linux; see below).
3. **The correct User base offset is larger and the stream wraps.** The spurious
   "129" suggests wrap. Try base offsets above 0x1000 and/or read until the
   index set covers 128-255 without gaps.
4. **128-138 live after the end of the Factory stream.** Try: read Factory
   (byte34=0) and keep requesting chunks past preset 127 without stopping
   (remove the early-break) — already tried up to 80 chunks and Factory stops
   at 127 (empty payload), so this hypothesis is nearly ruled out, but
   reconfirm with higher offsets.

## How to investigate (tools ready)

- `tools/diag.py` — dumps handshake/OPEN_* responses in hex. Add the
  byte34=1 case and dump the full User OPEN_STREAM response.
- `tools/stream_explore.py --base 0xXXXX --chunks N` — sweep offsets and see
  what indices/names come out. (Has the reassembly and scan logic.)
- `tools/capture.py` — if a capture of the official editor is ever obtained.
- `captures/user_raw.bin` — a raw dump of the User stream for offline analysis.

## Success criterion

Read the User setlist and get **contiguous indices 128-255** (128 presets), with
`name[i]` = the preset the pedal shows at slot `i-128`. Validation: ask the
user for the first ~12 real User names (01A-03D) and confirm they match.

## Temporary workaround (if not resolved)

Since **positional** recall works, the User can be listed by slot number without
trusting the misread names, or presets whose index is suspicious can be hidden.
Implement in `ui/main_window._fill_presets` by detecting gaps.
Currently the code uses `position = index % 128` (correct for Factory;
approximate and shifted for User — see the comment in that function).
