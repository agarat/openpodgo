# Spec 09 — Bypass / Controller Assignment (S-08, I-04, I-05)

POD Go Edit's **Bypass & Controller Assignment** window (manual v2.50,
pp. 27–34) brought to PodGo Lab: view, create, edit, rename and delete
footswitch / EXP pedal / snapshot assignments to blocks and their parameters.
Covers three items from the `docs/podgo-edit-vs-openpodgo-features.md` matrix:

- **I-05 Bypass Assign** — which FS/EXP toggles a block's bypass.
- **I-04 Controller Assignments** — which EXP/FS controls a parameter.
- **S-08 Detailed Bypass/Control view** — the window itself.

## Status

✅ Resolved (offline) for everything the RE supports; 🔬 pending live
verification with the pedal. Original feature doc:
`docs/features/03-bypass-control-assignment.md`.

## RE: assignment structure

Cross-referenced between the blob (`body[3]`/`body[4]`) and official `.pgp`
files (`captures/spec02_a.pgp`), confirming the mapping in `docs/specs/02-lab-notes.md`.

### Bypass — `body[3]` (footswitch). **Known structure.**

```
body[3] = {7: <int>, 8: [groups]}
```

- `body[3][8]` is a list of 9 groups: index `gi` 0–7 = **FS1–FS8**,
  `gi = 8` = **toe switch** of the expression pedal (`@fs_index = gi + 1`).
- Each group is a list of entries (multiple blocks can share a FS):

```
{10: order,                       # 0 = primary (@fs_primary), 1.. = secondary
 11: {0: 1,
      5: 'Tube Drive\0',          # customizable label (FST_LABEL)
      6: 525824,                  # LED color (FST_LEDCOLOR, integer on-wire)
      7: False,                   # state (FST_ENABLED)
      8: 3},                      # destination block, 1-based (FST_BLOCK = slot+1)
 12: False, 13: False, 14: '\0', 15: False, 16: 0}   # 0/13/14/15/16: cloned
```

The **destination block DOES travel** in the blob (`[11][8]`), so creating/moving/
clearing/renaming/recoloring is reconstructible by cloning the observed
skeleton. Validated by `.pgp` round-trip (`@fs_index`, `@fs_label`, `@fs_ledcolor`,
`@fs_primary`) in `tests/test_editor.py`.

### Controller — `body[4]`. **Binding NOT yet reconstructible.**

```
body[4] = [None, [ctl], [ctl], None, ...]   # list of 12
ctl = {0: ordinal,
       1: {0: @controller number,   # 1 = EXP1 (wah), 2 = EXP2 (volume)
           1: 4,                   # type/curve (?), 5/6/7: uncertain
           2: @min, 3: @max, 4: param_idx}}
```

The **destination block does NOT travel** in `body[4]`: only the `@controller`
number, which is currently linked to the block **by role** (1 → wah, 2 → volume;
see `editor.py`, `_controller_targets`). The `@controller` numbers for FS1–8 /
EXP Toe / Tap and the binding to non-wah/volume blocks **do not appear** in the
fixtures (which only carry the EXP1/EXP2 defaults). Per-snapshot values are
indexed by `number-1` in `body[10][10][i][2]` (placeholder `[False, 64, None]`).

**Consequence:** editing Min/Max and clearing an existing controller is safe;
**creating** a controller (or a snapshot-assign, which shares the same
controller number) on an arbitrary parameter requires RE/harvest with the pedal.

## Data layer — `src/openpodgo/editor.py`

Read: `bypass_target`, `bypass_blocks_on`, `footswitch_label`,
`footswitch_color`, `controller_assignment`.

Bypass mutations (solid): `set_bypass_assign`, `clear_bypass_assign`,
`set_fs_label`, `reset_fs_label`, `set_fs_ledcolor`. All go through the
undo/redo checkpoint and re-derive the view with `l6helix.parse_body`.

Controller mutations: `set_controller_min_max`, `clear_controller_assign`
(resets per-snapshot values). `set_controller_assign` raises
`ControllerAssignUnsupported` (RE-blocked, see above).

New constants: `BYPASS_TARGETS`, `CTRL_SOURCE_LABELS`, `DEFAULT_LED_COLOR`,
`SNAP_CTL_NONE`.

## UI

- **`src/openpodgo/ui/bypass_control.py`** — `BypassControlPanel`: Parameter menu
  (block params + "Bypass", with `[FS4]` indicators), selector grid
  (None, FS1–8, EXP Toe, EXP 1/2, Snapshots; Mode/Tap disabled) with
  official icons (`btn-ctrl-assign`, `icon-fs-*`, `icon-exp1/2`,
  `icon-snapshot-assign`) and category color ring, Min/Max sliders for
  controllers, FS bar (Rename / Color / View assignments) and
  `AssignmentsListDialog`. A status bar reports when an action is
  RE-blocked rather than writing something the pedal wouldn't honor.
- **`src/openpodgo/ui/inspector.py`** — `InspectorHeader.bypass_btn` (panel toggle,
  `btn-ctrl-assign` icon).
- **`src/openpodgo/ui/editor.py`** — the panel is inserted below the Signal Flow
  (hidden by default), toggled via the header button or **Ctrl+B**, and the
  block context menu gains the **Bypass Assign** submenu (FS1–8, toe, None).

## Live sync (op 21)

Clearing a slot and any assignment change are synced with the **full blob dump**
(`device.write_chain_blob`, op 21), same as block reorder: there's no known
vendor op for assignments. `EditorView` emits `chain_write_requested` from
`clear_slot`, `assign_bypass` and `_on_assignment_changed`.

**Apply/refresh after write:** the pedal applies the op 21 data but does NOT
refresh the footswitch/LED live until the switch is toggled. RE from
change-pedal-from-app.pcapng: POD Go Edit closes every edit with op 33 (block)
+ **op 23 (None) + op 22 (None)** (commit + buffer refresh). `write_chain_blob`
now sends op 23 + op 22 after the dump (`_apply_edit`) so the change is
reflected without touching the pedal. 🔬 Pending live confirmation.

**Performance:** the write session **cannot be reused** between dumps
(cursor/flow-control gets out of sync after a chunked write; the device
ignores the next one without re-handshake). `write_chain_blob` now forces a
fresh session before each dump, so it succeeds on the first attempt instead of
fail+reconnect+retry (~2× faster, without the "attempt 1 failed" WARNING).
Confirmed by live logs: every successful write was preceded by a
write-handshake; every failed attempt-1 reused a session.

## LED color (RESOLVED with pedal)

The footswitch LED color is a **fixed palette** (not free RGB). RE
confirmed live with `tools/harvest_fs_color.py` (diagnostic mode, dumping
the raw body[3] entry while changing color on the pedal):

- **key 16** of the entry = index in `FS_COLOR_NAMES`
  (`0=Auto, 1=White, 2=Red, 3=Dark Orange, 4=Light Orange, 5=Yellow, 6=Green,
  7=Turquoise, 8=Blue, 9=Violet, 10=Pink, 11=Off`; same order as
  `res/strings/appStrings_eng.json`).
- **key 15** = "custom color" flag (`True` except Auto).
- Internal **key 6** (FST_LEDCOLOR) is NOT the chosen color: it's the Auto
  color resolved by category (RGB-ish), and the pedal leaves it unchanged
  when customizing.

Data layer: `footswitch_color_index` / `set_fs_color_index` (writes 16 + 15).
UI: the **Color** button opens a menu with the palette (`icon-fs-*` swatches).
The change lands in the blob without needing Save (verified: the preset
fingerprint changes when varying the color).

## Pending with pedal (🔬)

1. Verify against the POD Go screen that read assignments match, and that
   create/move/clear/rename/recolor of a bypass is reflected;
   export a `.pgp` and import it into POD Go Edit as a final test.
2. **Resolve controller / snapshot-assign creation:** harvest with
   `tools/harvest_catalog.py` (or a dedicated capture) the `@controller`
   number scheme for FS/EXP and how the destination block travels when it's
   not the default wah/volume. That unlocks `set_controller_assign` and the
   manual's Alt+Click snapshot-assign (p. 32).

## Tests

`tests/test_editor.py` (read + bypass/controller mutations, `.pgp`
round-trip), `tests/test_ui_bypass_control.py` (panel), `tests/test_ui_editor.py`
(Ctrl+B toggle + Bypass Assign submenu). All offline.
