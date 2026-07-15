# Spec 05 — Block reorder: state and UI feedback

Three visual editor bugs that share the block reorder path.
Implementation in a single session (the three interact with each other).

## TODO items covered

- **#2** — When moving blocks, the "preset edited" signal is lost in the app
  (white circle ●).
- **#3** — Block movement is odd when moving right: the insertion indicator
  (white line) shows a space but then the block ends up "shifted". Simple UI
  redesign to make it clear where the block will land.
- **#4** — When moving a block (especially *on the pedalboard*), the app
  subsequently shows another block's config instead of the moved one's. May be
  an edge case.

## Root cause

`#2` and `#4` share a cause: when the reorder happens **on the pedal**, it
arrives as a burst (op 49 `{75,76}`) that triggers `_chain_reread_timer` →
`_open_editor` → `_show_preset` → `EditorView.set_preset`. And `set_preset`:

- resets `self.modified = False` (`ui/editor.py:107`) → the ● is lost (#2);
- recalculates `self._selected` to the **first non-empty block** (`ui/editor.py:113`)
  → the app shows a different block, not the moved one (#4).

(Reorder done **from the app** already works: `move_block` sets
`_selected = to_slot` and `modified=True`, and `_suppress_chain_echo` prevents
the re-read. The bug is specific to reorder originating on the pedal.)

`#3` is independent, in `signal_flow.py`: the insertion caret is always drawn
at the left edge of the destination slot (`paintEvent`, `w.x() - 2`). When
dragging right, the insertion semantics don't match the final block position
(insert-before vs. insert-after).

## Required changes

### 1. Preserve selection and state on re-read (#2, #4)

`src/openpodgo/ui/editor.py` — `set_preset` must be able to preserve the
selected slot and the `modified` flag on a re-read. Recommended option: a
`keep_state: bool = False` parameter (or `preserve_selection` + `mark_modified`)
that, when `True`, keeps `self._selected` (clamped to the valid range of the
new chain) and `self.modified` instead of resetting them.

`src/openpodgo/ui/main_window.py` — distinguish a re-read triggered by
`chain_changed` (reorder on pedal) from a real preset change:

- In the `chain_changed` handler, when triggering the re-read, mark that it's
  a reorder (e.g. a flag `self._chain_reread_pending = True`).
- In `_show_preset`, if the flag is active, call `set_preset(...,
  keep_state=True)` and clear the flag. This way the ● survives (a reorder IS
  an unsaved edit) and the selection doesn't jump to the first block.

### 2. Select the moved block (#4, improvement — validate with pedal)

If op 49 `{75,76}` of the reorder carries the movement origin/destination,
parse it in `notifications.py::parse_notification` and propagate it as
`chain_changed` event data so that `_show_preset` selects the exact destination
slot instead of just preserving the previous one. **Pending RE:** confirm the
semantics of keys 75/76 with pedal captures. If not viable, the "preserve
selection" fallback from point 1 already prevents the arbitrary jump.

### 3. Redesign the insertion caret (#3)

`src/openpodgo/ui/signal_flow.py` — the drop indicator must reflect the
**final** block position:

- Calculate the insertion position accounting for the fact that the source
  block is removed before being reinserted (when moving right, the effective
  destination shifts by one).
- Draw the caret on the correct side of the slot based on drag direction
  (origin < destination → right edge of destination; origin > destination →
  left edge), or in the gap between slots with "insert between" semantics.
- Optional (if it helps clarity): preview the displacement of neighboring
  blocks during the drag.

The goal is that the white line shows exactly where the block will land when
dropped, without the current "shift".

## Tests

`tests/` (offline, no pedal):

- Reorder triggering re-read preserves `modified=True` (#2).
- Re-read with `keep_state=True` keeps `_selected` (clamped) (#4).
- `_slot_at` / insertion position calculation returns the correct final
  index when moving right and left (#3, pure logic).

The caret visual feedback (#3) and the moved block selection on pedal
(#4 improvement) are validated **manually with the pedal**.

## Pedal verification

1. Edit a param (● appears). Move a block **on the pedalboard** → the app must
   preserve the ● and show the moved block's config (not another's).
2. Drag a block right in the app → the insertion line must land where the
   block actually ends up when dropped.
3. Move blocks in both directions, from the app and from the pedal, without
   the selection or the edited indicator becoming inconsistent.
