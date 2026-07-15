# Spec 06 — Lab notes: RE of the "edited preset" indicator ("E")

**Offline** research into how the POD Go exposes the "edited-unsaved" state
(the "E" on the pedal's screen). Only captures from
`captures/win-captures/` of POD Go Edit (Windows) — no pedal.

## TL;DR — conclusion

- **Hypothesis 1 (explicit flag): DISCARDED with the available evidence.**
  The only "extra" boolean in object 23 (active preset state) is
  **key 117**, and it appears as `False` in all THREE object 23 reads from
  the captures, **including one read made immediately after editing
  the pedal** (model change). 117 doesn't change with edited/clean ⇒ it's not
  the "E". There is no other boolean candidate in object 23, nor in the
  object 22 wrapper, nor in the handshake.
- **The official app does NOT read any "edited" flag from the pedal.** It tracks
  the edited state **locally** (it makes the changes itself). That's why it
  never re-reads object 23 looking for the flag after an edit.
- **Hypothesis 2 (compare blobs): is the viable path**, but it **cannot be
  CONFIRMED offline** that it distinguishes edited from clean, because no capture
  contains the pair "stored slot blob" vs "edited active preset blob" for the
  same slot. What IS clear is **what** would need to be compared and that the
  pedal maintains a content "seal" (key 116) that could serve as a shortcut.
- **A capture with the pedal is missing** (see "What's missing to capture") to
  close the RE.

## Channel map (the captures use three logical channels in parallel)

| Channel | src→dst | Role |
|---|---|---|
| Main/read | `0x1001→0x03EF` | preset listing/stream, stray commands |
| Write | `0x1080→0x03ED` | `set_param`, `set_model`, **save (op 71)**, reads of objects 22/23 |
| Events | `0x1002→0x03F0` | notifications pushed by the pedal (spec 04) |

All three channels poll with keepalives `cmd=0x10`.

## Clue from the prompt: the `cmd 0x10` poll (`04 2f 00 00` / `43 02 00 00`)

**It's not an edited indicator.** It's the generic channel keepalive. Bytes
12-15 are a **read cursor** that advances based on how much data was read on
that channel; they don't encode preset state. Evidence: in `win_save.pcapng` the
main channel's IN cursor advances from `04 2f 00 00` to `10 3c 00 00` only because
a preset stream was read in between (the cursor advanced), not because of the save.
The same cursor pattern appears identically in captures without any editing
(`win_connect`, `win_knob`). Discarded.

## Object 23 (active preset state) — full decoding

Request (write channel, `cmd=0x0c`): `{102: <txid>, 100: 23, 101: None}`.
Inline response `{102, 103:0, 104: {...}}`. The `104` carries:

```
{107: setlist, 108: slot, 109: name\0, 117: bool, 83: [u16, u16], 92: int}
```

The three object 23 reads from the captures:

| Capture | idx | 107 | 108 | 109 | **117** | 83 | 92 |
|---|---|---|---|---|---|---|---|
| `win_connect.pcapng` | 27 | 1 | 7 | RINDANSE | **False** | [7711, 0] | 0 |
| `change-pedal-from-app.pcapng` | 48 | 1 | 35 | marca | **False** | [7911, 0] | 0 |
| `win_preset_change.pcapng` | 31 | 1 | 7 | RINDANSE | **False** | [7711, 0] | 0 |

### Why 117 is NOT the "E"

In `change-pedal-from-app.pcapng` the temporal order is decisive:

```
[35] 5.5s OUT write     op 40 (set_model): changes model of block 5  → EDITS the preset
[44] 5.9s OUT write     op 33 (reads the chain after the swap)
[47] 5.9s OUT write     requests object 23
[48] 5.9s IN  write     obj23 → {…, 117: False, …}   ← edited, but 117 still False
```

In other words: even with the preset already modified (model just changed,
unsaved), object 23 reports `117: False`. The app reads object 23 there only
to refresh the name/slot in the bar (they don't change with a model swap), not
to know if it's edited. `117` seems like something else ("preset exists / slot
occupied"? to be confirmed), but **not** the editing indicator.

`83` changes between different presets (RINDANSE→marca), not with editing;
`92` is 0 in all cases. None moves with the clean↔edited transition observed.

## The pedal does NOT push an "edited" flag on the event channel

When a parameter is edited, the pedal pushes the **specific edit** on the
event channel, not a boolean "now I'm edited":

`change-param-from-app.pcapng`:
```
[30] event {121: 20, 106: {98:5, 29:True, 26:0, 28:0, 119: 0.47}}   ← "param changed" (value echo)
```
`change-pedal-from-app.pcapng`:
```
[40] event {121: 47, 106: None}
[41] event {121: 31?...}  (several {98, 70, 79:True} = topology/blocks)
```

After a **save** (op 71), the pedal pushes two confirmation events
(identical in `win_save` and in `change-param`'s save):
```
{121: 3, 106: {107: setlist, 108: slot, 116: <u32>}}   ← "preset saved", with a CONTENT SEAL (116)
{121: 8, 106: {107: setlist, 108: slot, 109: name}}  ← name of the saved slot
```

Examples of key 116 (seal): `2591025121` (BassPreset), `2436289391`
(marca). It's a 32-bit integer that changes per preset/content — looks like
a hash/version of the saved preset, **not** an edited flag. `121` is the
event type discriminator (3=saved, 8=name, 20=param, 47/31=chain).

Conclusion: the event channel is useful for knowing **that** something changed
(useful for the spec 04 live-sync) and **when it was saved**, but **does not
expose the "E" state as a boolean**.

## Hypothesis 2 (compare blobs) — viable, but not confirmable offline

Object 22 (`OBJ_ACTIVE_PRESET`) is the `l6-helix` blob of the **active**
preset (the pedal's live edit buffer). The preset stream (object 1) delivers
the **stored** presets by slot. The idea:

> active (obj 22) ≠ stored in its slot ⇒ edited.

What the offline evidence DOES make clear:

- **What to compare:** blob of object 22 vs the preset in slot
  `(setlist=107, slot=108)` from object 23. We already know how to read both
  (`preset.read_active_preset` / `stream_presets`).
- **A possible shortcut:** the "seal" (key 116) that the pedal emits on save.
  If that same u32 were available both in object 23 (or in the stream's slot
  entry) and derivable from the active preset, comparing two integers would be
  cheaper than diffing the blob. BUT there's no capture showing 116
  outside the save event, so it can't be confirmed where to read it live.

What CANNOT be confirmed offline:

- That the object 22 blob **edited** differs, byte by byte or after
  normalization, from the preset stored in that slot. No capture has the
  labeled pair (active-edited vs stored-from-same-slot). The editing captures
  (`change-param`, `win_knob`, `change-pedal*`) edit but do NOT
  re-read object 22 after editing and before saving, so there's no
  "dirty obj 22" to diff against the stream.
- Known risk (already noted in the spec): the blob may carry volatile fields
  (key ordering, floats, possible timestamps/seals) that differ without the
  user having edited anything ⇒ false positives. Would need normalization.

## Finding A — `zlib.crc32` on the blob is NOT the object 14 formula

**Offline** result on real captures (`captures/spec02_obj22_blob.bin`
= object 22 blob; `captures/spec02_obj14.bin` = per-slot seal table,
`parse_slot_checksums` gives 120 non-empty slots):

```
crc32(raw blob)            = 3153828841 (0xbbfb9be9)  in object 14? No
crc32(body w/o table)      = 2712857884 (0xa1b2ed1c)  in object 14? No
crc32(rebuilt build_blob)  = 2501166100 (0x9514c414)  in object 14? No
crc32(full obj22 message)  = 3384956662 (0xc9c256f6)  in object 14? No
```

None of the four variants matches ANY of the 120 non-empty seals.
Conclusion: **`zlib.crc32` on the object 22 blob is DISCARDED as the
object 14 seal formula.** If the code compared `crc32(active)` against the
stored seal on a pedal with a populated table, it would give `!=` (and thus
"edited") even for a CLEAN preset ⇒ confident false positive.

**Constraint for live capture:** the capture must reveal the actual
object 14 seal algorithm — algorithm (different CRC variant?, sum?,
custom hash?), seed/polynomial, and above all the **input region** (raw blob?,
just the body?, a subset of keys?, with/without the offset table?). Without
that, the active seal can't be matched to the stored one.

That's why in `device.py`, the constant `_OBJ14_CRC_CONFIRMED = False` gates the
comparison: while it's False, `active_preset_is_edited` returns conservative
`False` (never a spurious "●") and logs it; the only point to fix when the
formula is confirmed is `_blob_crc_for_obj14` (+ set the constant to True).

## Constraint — no reading of the stored blob without recall

Reviewed the object map in `docs/specs/02-lab-notes.md`: **there is no vendor
object that reads the complete `l6-helix` blob of a STORED slot** without
recall (loading the slot to make it active — which would reset the "●" state).
Object 22 is always the **active** one; the stream (object 1) only carries
per-slot metadata, not the complete editable blob. Therefore the comparison
"active blob vs normalized stored blob" **has no source for its comparison
operand today** (neither offline nor live) without a new RE step.

Implication: **object 14** (per-slot fingerprint/seal) is the architecturally
correct comparison direction. `l6helix.blobs_equal_normalized` remains as a
prepared primitive for the blob-vs-blob path, pending the RE item
**"read the stored blob of a slot without recall"**; it doesn't connect until
that item exists.

## What's missing to capture with the pedal (to close the RE)

A single capture resolves both hypotheses. With the pedal and `tools/capture.py`
(app closed), in this order, **without saving**:

1. Load a clean preset. Read object 23, object 22 and object 14 → CLEAN snapshot.
2. Edit **one** parameter on the pedal ("E" appears). Do NOT save.
3. Re-read object 23, object 22 and object 14 → EDITED snapshot of the **same** slot.
4. Save on the pedal ("E" disappears). Read objects 23, 22 and 14 → CLEAN snapshot.

With that:
- **Hypothesis 1** is confirmed/discarded by checking whether **any** key of
  object 23 (especially 117, but review all) changes `False→True` between
  steps 1/2 and returns in step 4. If it appears, THAT is the flag.
- If no key changes, **Hypothesis 2** applies: diffing obj 22 (step 1 vs
  step 2) confirms whether the blob works to detect edited, and comparing
  key 116 / 83 between steps tells whether there's a cheap seal that
  replaces the diff.
- **Object 14 formula (Finding A):** with the object 14 capture in each
  step, find what transformation of the object 22 blob (step 1, clean)
  reproduces the slot seal in the object 14 table — try region (raw blob /
  body only / key subset) and algorithm (standard crc32 already ruled out,
  try other variants/seeds or the save event's 116 seal).
  Once the formula is confirmed: adjust `_blob_crc_for_obj14` and set
  `_OBJ14_CRC_CONFIRMED = True` in `device.py`.

(Optional, even cleaner: replicate the step 2 flow with POD Go Edit on
Windows and capture; if the official app DOES read some flag after editing —
something these captures don't show — it would surface there.)

## Recommendation for Task 1 (API change)

Current evidence status: **no confirmed explicit flag**; the most likely
path is blob comparison (Hypothesis 2). Therefore:

1. **Do not yet add** `ActiveState.edited` as a bool read from a specific
   object 23 key: no key supports it (117 is discarded).
2. Design the API around the **comparison** and keep it behind
   `device.py`, e.g. `PodGo.active_preset_is_edited() -> bool` that:
   - reads object 23 (active setlist/slot),
   - reads object 22 (active blob) and the stored preset for that slot,
   - compares after **normalizing** the blob (stabilize key ordering; tolerate
     floats; ignore volatile fields if any).
   Encapsulating it there prevents leaking the logic to the UI.
3. Keep `ActiveState` with an optional `edited: bool | None` field, in case the
   capture with pedal reveals an explicit flag (then it would be populated from
   object 23 and `active_preset_is_edited` becomes trivial). Today it would be
   `None` / unset.
4. **Blocker:** run the pedal capture from above first. Until the labeled
   clean-vs-edited pair exists, the blob diff can't be validated (nor can a
   choice be made between full diff and the 116 seal shortcut).

## Evidence (transfer indices)

- Flag 117 = False post-edit: `change-pedal-from-app.pcapng`,
  set_model at idx 35, object 23 read at idx 47-48.
- Decoded object 23: `win_connect.pcapng` idx 26-27,
  `win_preset_change.pcapng` idx 31, `change-pedal-from-app.pcapng` idx 48.
- Save (op 71) + event 116 seals: `win_save.pcapng` idx 41 (save), 45/48
  (`121:3`/`121:8` events); `change-param-from-app.pcapng` idx 75 (save),
  77/82 (events).
- Param edit event (`121:20`): `change-param-from-app.pcapng` idx 30.
- `cmd 0x10` poll = keepalive with cursor (not flag): `win_save.pcapng` main
  channel, cursors `04 2f 00 00` → `10 3c 00 00`.
