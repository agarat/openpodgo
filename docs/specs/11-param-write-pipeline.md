# Spec 11 — Parameter writes from the UI (knob → pedal)

Status: ✅ resolved (live-verified on macOS against a POD Go `0e41:4247`).

## Symptom

Turning a knob in the app did not change anything on the pedal, "even after
saving the preset". Nothing visible happened: no error, no status message.

## Root causes (both real, both silent)

1. **The value travelled with the wrong MessagePack type.** `device.set_param`
   was called with `float(value)` everywhere, and the pedal rejects (ACK
   `103: 255, 104: {111: -3}`) a type that does not match the parameter it
   stores: an int parameter (e.g. cab `Mic`) refuses `8.0` and accepts `8`, a
   float parameter does the opposite. Every *labeled discrete* knob (a combo in
   the UI) therefore never reached the pedal. Bool parameters (`@trails`, the
   volume-pedal taper…) answer 255 to every encoding tried, so they are simply
   not writable through op 30.
2. **Writes only happened on `sliderReleased`.** Wheel, arrow keys, typed
   values in the spinbox and keyboard-driven changes updated the editor but
   never the pedal, and there was no feedback when a write was refused.

The save button made it worse instead of better: op 71 stores the **pedal's**
edit buffer, so any value that never reached it was saved as the old value.

## Design

### Write on every change, coalesced (`ui/inspector.EditPanel`)

- Every parameter change (drag, wheel, arrows, typed, combo) queues the value
  in `_pending[(block_index, param_idx)]` — the newest value wins.
- A single-shot `QTimer` (`WRITE_INTERVAL_MS = 80`) flushes the queue, so a
  drag produces at most ~12 writes/s instead of one per pixel.
- The end of an interaction (slider release, `editingFinished`, combo change)
  flushes immediately, so the pedal updates as soon as the user stops.
- A rebuild of the panel (`clear()`) flushes what is pending; loading another
  preset (`EditorView.set_preset`) cancels it: those values belong to the
  previous preset and the pedal has already switched to the new one.
- Bools are skipped (see above) and stay in memory/`.pgp` only.

### Type-preserving writes

- `PresetEditor.set_param` / `set_io_param` keep the parameter's on-wire type
  (a float arriving for an int parameter is rounded).
- `device.set_param(value)` forwards the value untouched (its docstring spells
  out the type rule) and no longer coerces to `float`.
- `MainWindow._flush_editor_params` does the same and skips bools.

### The pedal's echo is not the source of truth for the index

The notification the pedal emits after our write carries the parameter index in
key 28 (`26` is 0). The parser read `26`, so every echo applied its value to the
block's **first** parameter: adjusting the second knob moved the first one in
the UI. `notifications._param_index()` now reads 28 (falling back to 26), which
matches what the pedal sends for its own physical knob events too, and
`_on_param_from_device` drops no-op echoes (same value) so they do not add undo
steps.

### Feedback instead of silence

`EditPanel.write_failed` → `InspectorPanel.write_failed` →
`EditorView.write_failed` → `MainWindow._on_write_failed` shows
`Not written to the pedal — the pedal rejected <param> = <value>` in the status
bar. A transport error says so instead.

### Save flushes first

`MainWindow._save_to_pedal` pushes the editor's parameters to the pedal (only
when the editor is modified) before op 71, so a save always stores what the app
shows — a lost or coalesced write can never be persisted as a stale value.

### Transport fixes this exposed (see spec 03)

- `WriteSession.send_write` stops draining at the command's own echo (matched by
  tx id `k102`); the trailing acks arrived 100–250 ms later and cost one
  timeout per write (~420 ms/write → ~20 ms/write, a 50-param save went from
  23 s to ~1 s).
- Writes hold `transport.lock` (now reentrant): the live-sync poller was
  reading the echo between write and drain, so the first attempt failed and
  only the reconnect+retry applied it.
- Reads no longer invalidate the write channel (`_read_since_write` is now a
  recovery flag), removing a ~1 s handshake from the first knob turn after
  loading a preset.

## Tests

- `tests/test_ui_inspector.py`: coalescing + typing (`writes are coalesced and
  typed`), int params travel as int, bools are skipped, rejections are reported.
- `tests/test_editor.py`: int/bool type preservation, IO params keep their type.
- `tests/test_integration_write.py`: `set_param` keeps `k119` typed; the drain
  stops at its own echo, skips a stale echo, and falls back to a full drain when
  there is none.

## Manual verification (live, macOS)

- Wheel-style change (no release) on a float knob: pedal follows.
- Combo (int) parameter: pedal follows (this was the silent failure).
- Save with a modified preset: flush + op 71, all values persisted.
- 50 parameters written with interleaved preset reads: all applied, all
  restored.
