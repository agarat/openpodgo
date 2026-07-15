# Spec 06 — "Edited preset" indicator on startup

## TODO item covered

- **#1** — If the pedalboard is on an **unsaved** preset at startup
  (the "E" indicator on the POD Go screen), the app doesn't reflect it:
  shows the preset as clean (white circle ○) instead of edited (●).

## Cause

On connect, the app reads the active preset (`active_state()` + `active_preset()`)
and `EditorView.set_preset` always starts with `self.modified = False`
(`ui/editor.py:107`). There is no reading of the "edited-unsaved" state from
the pedal, so a preset marked with "E" on the pedal arrives at the app as if
it were freshly loaded.

## RE work (first, with the pedal)

Discover how the POD Go exposes the "edited" state. Two hypotheses to verify
with captures (`tools/capture.py`, compare with POD Go Edit on Windows if
needed):

1. **Explicit flag** in `active_state()` / in some handshake packet or in an
   initial notification. Look for a new boolean key in the active state object
   (`preset.py::ActiveState`, decoded in `l6helix.py` /
   `device.active_state`). This is the clean path if it exists.
2. **Blob comparison** (fallback): if no flag exists, compare the active
   preset's blob (object 22) against the preset stored in that slot
   (re-read it from the stream). If they differ → edited. More expensive
   (an extra read) and sensitive to blob normalization; use only if (1)
   doesn't appear.

Document the finding in `docs/specs/06-lab-notes.md`.

## Required changes

### 1. Expose the flag in the API (based on RE findings)

- If it's an explicit flag: add it to `ActiveState` (`src/openpodgo/preset.py`)
  and to its decoding (`device.active_state` / `l6helix.py`), e.g.
  `ActiveState.edited: bool`.
- If it's blob comparison: encapsulate it in `device.py` (e.g.
  `PodGo.active_preset_is_edited()`), without leaking the logic to the UI.

### 2. Propagate to the UI

`src/openpodgo/ui/editor.py` — `set_preset` accepts an initial
`modified: bool = False` (or reuses the `keep_state` from spec 05 if it
already exists) to start with ● when the pedal reports the preset as edited.

`src/openpodgo/ui/main_window.py` — `_show_preset` passes the flag read from
the pedal to `set_preset`. Applies both on initial connection (`_on_connected`
→ first `_open_editor`) and on every re-read of the active preset.

## Tests

`tests/` (offline):

- If the flag is decodable from a capture: `ActiveState` fixture with
  `edited=True` → `set_preset` starts with `modified=True` (●).
- `edited=False` case → starts clean (○).

(If the final path is blob comparison, test the comparison with two
blob fixtures: same → not edited, different → edited.)

## Pedal verification

1. On the POD Go, edit a param **without saving** ("E" appears on screen).
2. Open the app (or reconnect) → the active preset must show ● from the start,
   without touching anything.
3. Save on the pedal ("E" disappears) and reconnect → the app must show it
   clean (○).

## Notes

- Depends on the pedal for RE; it's the spec with the most uncertainty in the batch.
- Shares the "start with modified" mechanism with spec 05 (#2); if 05 is
  already implemented, reuse that parameter in `set_preset`.
