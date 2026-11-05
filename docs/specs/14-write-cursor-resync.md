# Spec 14 — Refused writes leave the cursor desynced (selection bursts)

Status: ✅ resolved.

## Symptom

Block selection worked most of the time but sometimes failed in bursts, with
warnings like:

```
WARNING openpodgo.ui.main_window: the pedal did not select block 6
WARNING openpodgo.ui.main_window: the pedal did not select block 7
WARNING openpodgo.ui.main_window: the pedal did not select block 6
```

## Cause

The write channel advances a **stream cursor** and the pedal validates it: a
command at the wrong position is refused (`103: 255`) and **not applied**. Our
`WriteSession.send_write` always advances the cursor by the command footprint —

```
self._cursor += 8 + body_len
```

— but a refused command does not advance the pedal's own position. So one
refused write (a transient refusal, or a command the pedal dropped while busy
streaming) shifts our cursor by one command and **every following write is
mispositioned and refused too**: the burst the user saw. Only an unrelated
write that reconnects the channel (`set_param`'s retry) cleared it, which is why
it "sometimes worked".

`select_block` had no retry at all, so it stayed broken until then.

## Fix

`PodGo._write_command(build, label)` — the single path for one-shot write
commands (`set_param`, `select_block`, `save_preset`, `set_snapshot`):

1. send the command;
2. if the pedal refuses it, **rewind the cursor** (`WriteSession.rewind_to`) and
   resend once — idempotent: same command, same position, so it is safe even
   when the refusal was a lost answer for a command that was actually applied;
3. if it is refused again, re-handshake the write channel (`write_connect`) and
   try once more;
4. log each refusal with the pedal's status (`103`/`104`, e.g. `{111: -3}`) so a
   real validation error is distinguishable from a desync.

`send_write` also stops draining at its own echo (matched by the tx id `k102`),
so a stale framed answer from a previous command cannot be mistaken for the
status of this one.

## Also: a read is one critical section

A read is several requests (handshake + `OPEN_PRESETS` + stream chunks), not
one. Without the transport lock around the whole sequence, a write from the UI
slipped in between two chunks — in the middle of the pedal's stream — and was
refused, exactly the burst above. `PodGo._exclusive()` now holds the lock for
the whole read (`list_setlists`, `list_presets`, `active_state`,
`active_preset`), and `MainWindow` postpones a block selection while a read is
in flight (newest selection wins) instead of blocking the UI thread for up to a
second.

Live stress test: 40 selections while a background thread streamed 41 full
preset reads → **0 failures, 0 read errors**.

## Tests

- `test_refused_write_is_resent_at_the_rewound_cursor`: the retry goes out with
  the **same** cursor bytes as the refused attempt.
- `test_write_gives_up_after_three_refusals`: no infinite retry, one cursor.
- `test_seleccion_durante_un_read_queda_pendiente`: a selection made while a
  read is in flight is postponed (and then sent), not lost.

## What would still show up in the logs

If a refusal keeps happening with the *same* `103/104` detail (e.g.
`104: {111: -3}` on a valid block that exists), it is a validation error, not a
desync: the block index would be wrong or the pedal would be in another mode.
The log line now carries that detail.
