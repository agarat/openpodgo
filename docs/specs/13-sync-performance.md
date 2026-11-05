# Spec 13 — Why USB sync was slow (and the fix)

Status: ✅ resolved (measured live, firmware 2.01).

## Symptom

The app felt sluggish compared with POD Go Edit: connecting, switching presets
and reacting to pedal changes took seconds, while the official editor is
snappy.

## Measurement (before)

Every read operation was timed on the pedal:

| operation | time |
|---|---|
| `list_setlists` | 1003 ms |
| `active_state` (object 23) | 1199 ms |
| `active_preset` (object 22, 3.7 KB) | 1202 ms |
| `list_presets` (128 names) | 1157 ms |
| `set_param` (one knob value) | 398 ms |

Instrumenting the handshake showed the pattern:

```
attempt 1: drain (>1 packet)  →  pkt0 HANDSHAKE  FAIL (300 ms timeout)
           backoff 300 ms
attempt 2: drain (0 packets)  →  pkt0 1 ms, pkt1 1 ms, pkt2 180 ms, pkt3 1 ms, pkt4 199 ms  → OK
```

So **every operation wasted one failed handshake attempt plus the 300 ms
backoff (~660 ms)**, on top of the ~400 ms the handshake itself needs.

## Root cause

The pedal answers the handshake magic only when it is "fresh". After a
completed handshake it **silently drops the next magic** — the retry 300 ms
later is answered in 1 ms. And the session cannot be reused for a second read
(a second `OPEN_PRESETS` on the same session times out), so every read *needs*
a handshake and therefore hit that penalty.

## Fix

`Session._prime()`: after the first handshake of a connection, send the magic
once more **without waiting for an answer** before running the real sequence.
The pedal is then back in the state where it answers, and the sequence succeeds
on its first attempt:

```
drain → prime magic (ignored, ~30 ms) → HANDSHAKE, OPEN_1, CHUNK_1, OPEN_2, CHUNK_2 → ~400 ms
```

Second, since each read costs a full session, the setlist names are now taken
from the `OPEN_PRESETS` response that already opens the preset stream
(`device.list_presets_and_setlists`): connecting needs **three** sessions
instead of four.

## Measurement (after)

| operation | before | after |
|---|---|---|
| `list_setlists` | 1003 ms | **403 ms** |
| `active_state` | 1199 ms | **597 ms** |
| `active_preset` | 1202 ms | **603 ms** |
| `list_presets` | 1157 ms | **554 ms** |
| `set_param` | 398 ms | **2 ms** (warm write channel) |
| `select_block` | 27 ms | 27 ms |
| retries logged per operation | 1 | **0** |
| app connect (device → presets in the UI) | ~4.5 s | **2.5 s** |
| preset switch (recall + re-read) | ~5–6 s | **1.6 s** |
| live-sync re-read (state + preset) | ~2.4 s | **1.3 s** |

## What still costs time (next steps, not done)

1. **A read is ~600 ms and cannot be batched**: one session per read operation
   is a device constraint. The ~400 ms handshake itself is dominated by two
   ~190 ms chunk packets (`SESSION_CHUNK_1/2`), which look like the device
   preparing the data window.
2. **Preset switch (~1.6 s)** = MIDI recall + `active_state` (verify) +
   `active_preset`. The verification could be skipped when the pedal's
   `preset_loaded` event (op 8, `{107: setlist, 108: slot}`) confirms the slot —
   that alone saves ~600 ms.
3. **Live-sync events re-read the whole preset (1.3 s)**: `preset_loaded` and
   `snapshot` both go through `_open_editor()` (state + preset). For
   `preset_loaded` the event already carries the slot, so `active_state` is
   redundant. A snapshot change could be applied **locally** (the blob carries
   the per-snapshot bypass states and controller values), making it instant like
   the official editor — that needs the per-snapshot controller logic decoded
   (`body[4]`, see spec 02 lab notes).
4. The live-sync poller (event channel, every ~30 ms) serializes with writes on
   the shared IN endpoint; it is bounded but shows up as occasional few-ms
   waits.
