# Spec 04 — Live sync

Bidirectional app ↔ pedal sync status and pending items.

## Implemented (commit d692925 + spec03)

- `NotificationReader` polls the event channel (0x03F0→0x1002) and emits each
  notification. `MainWindow._on_device_event` dispatches by type.
- Handled types: `set_param` (op 30), `bypass_state` (op 49, absolute state),
  `bypass` (op 39, legacy), `snapshot` (op 42/46), `preset_loaded` (op 8),
  `tempo` (op 22). See `src/openpodgo/notifications.py`.
- App→pedal writes: `set_param`, `set_snapshot`, `change_preset`,
  `save_preset` and now `set_model` (op 40, #3).

## #6 — Wah doesn't activate in the UI (RESOLVED)

Original symptom: pressing the toe switch of the wah didn't reflect the block
state change in the UI.

**Cause (confirmed with pedal captures, fw v2.01):** the wah toe does NOT emit
`OP_BYPASS` (op 39). It emits **op 49** with the *absolute* block state:

```
op 49  body={105:49, 106:{82:0, 68:5, 121:17, 106:{98:<block>, 59:<enabled>}}}
```

- `98` = RAW block index in DSP_CHAIN (same as set_param).
- `59` = EXPLICIT `enabled` (bool). It's not a toggle: it carries the final value.
- Pressing the wah sends two op 49 (blocks 2 and 3): the wah occupies two
  on-wire positions; `slot_from_block_index` maps each to its slot (or None).
- op 49 also accompanies other changes (e.g. set_model) WITHOUT key 59; that's
  why the parser only treats it as bypass when `59` is present.

**Fix:** `parse_notification` decodes op 49 (with key 59) as a new
`bypass_state` event `{block, enabled}`. `_on_bypass_state_from_device` applies
the absolute `enabled` to the slot (with guard `block.enabled == enabled` → no-op).
The old `bypass` dispatch (op 39, toggle) was removed.

### Resolved side effect: bypass flicker from the app

Previously, toggling a block from the app enabled it on the pedal, the pedal
returned the echo (op 39) and `_on_bypass_from_device` **toggled again** → ended
up reversed. Now the echo arrives as op 49 with the absolute state already
applied, and the guard makes it a no-op: no flicker and no spurious modified mark.
