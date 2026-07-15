# Spec 03 — Phase B: Write bug fixes

## Current status of the `spec03-fase-a` branch

The cherry-picked commits from opencode implemented the USB write infrastructure,
but with two specific bugs identified through analysis of real USB captures
(`change-param-from-app.pcapng`, `change-pedal-from-app.pcapng` in `captures/win-captures/`).

### What works today

- Block bypass toggle via MIDI footswitch (`_on_bypass_midi` in main_window.py)
- Save button enabled and connected to `_save_to_pedal`
- WriteSession handshake (2 packets) — confirmed correct against win_connect.pcapng
- `save_preset` (cmd=71, write channel) — protocol confirmed correct

### What doesn't work

**Bug 1 — `set_param` ignores the parameter index**

`device.set_param(block_index, value)` hardcodes `{26: 0}` in the msgpack.
Key 26 is the parameter index within the block.

- Immediate consequence: `_flush_editor_params` in `main_window.py` already calls
  `device.set_param(block_index=blk_idx, param_idx=i, value=...)` — crashes with
  `TypeError` because `set_param` doesn't accept `param_idx`.
- Functional consequence: even if it didn't crash, it would always modify parameter 0
  of the block instead of the correct parameter.

**Bug 2 — `change_preset` uses wrong channel and command**

The capture shows that `change_preset` goes through the **read channel** (src=0x1001→0x03EF),
not the write channel:

| Field        | Current code (incorrect) | Capture (correct)       |
|---|---|---|
| Channel      | write (0x1080→0x03ED)    | read (0x1001→0x03EF)    |
| Subheader    | `01 00 06 00`            | `01 00 02 00`           |
| cmd (key 100)| 20                       | **1**                   |
| slot key     | 108                      | **101**                 |
| Session      | WriteSession             | Session (read)          |

Correct payload: `{102: tx_id, 100: 1, 101: {107: setlist, 101: slot}}`

---

## Required changes

### 1. `src/openpodgo/device.py`

**a) `set_param` — add `param_idx`:**

```python
def set_param(self, block_index: int, param_idx: int, value: float) -> bool:
    ws = self._require_write_session()
    seq = ws.advance_seq()
    pkt = packets.build_vendor_write(
        {102: _write_tx_id(), 100: 30,
         101: {98: block_index, 29: True, 26: param_idx, 28: 0, 119: value}},
        seq=seq, cmd=0x04,
    )
    resp = ws.request(pkt)
    return _write_ok(resp)
```

**b) `change_preset` — use the read channel:**

Option A: extend `build_vendor_write` to accept optional `src`/`dst`/`subheader`
and call it with the read channel values.

Option B: use `build_vendor_open` with `OPEN_PRESETS` as template (already has
src=0x1001, dst=0x03EF, subheader `01 00 02 00`) and send with
`self._session.transport.request(pkt)`.

```python
def change_preset(self, setlist: int, slot: int) -> bool:
    session = self._require_session()
    seq = session.advance_seq()
    pkt = packets.build_vendor_open(
        packets.OPEN_PRESETS,
        {102: _write_tx_id(), 100: 1, 101: {107: setlist, 101: slot}},
        seq=seq,
    )
    try:
        session.transport.request(pkt)
    except Exception as exc:
        log.warning("change_preset: error (setlist=%d slot=%d): %s", setlist, slot, exc)
        return False
    return True
```

### 2. `tests/test_device_write.py`

- `test_change_preset_builds_correct_packet`: update to verify cmd=1,
  read channel (src=0x1001), slot key=101 in the payload.
- `test_write_session_integration`: change to `set_param(block_index=0, param_idx=0, value=0.5)`.

### 3. `tests/test_live_edit.py` (if it exists)

- Any call to `device.set_param` must include `param_idx`.

---

## Protocol confirmed by captures (reference)

### set_param (`change-param-from-app.pcapng`, packets [25], [27], [33])
```
OUT cmd=0x04  src=0x1080→0x03ed
{102: tx_id, 100: 30, 101: {98: block_idx, 29: True, 26: param_idx, 28: 0, 119: value}}
IN  cmd=0x04  {102: tx_id, 103: 0, 104: {...}}   ← 103:0 = OK
```

### save_preset (`change-param-from-app.pcapng`, packet [75])
```
OUT cmd=0x04  src=0x1080→0x03ed
{102: tx_id, 100: 71, 101: {107: setlist, 108: slot, 109: 'name\x00'}}
IN  cmd=0x04  {102: tx_id, 103: 0, 104: None}
```

### change_preset (`change-param-from-app.pcapng`, packet [81])
```
OUT cmd=0x04  src=0x1001→0x03ef  subheader: 01 00 02 00
{102: tx_id, 100: 1, 101: {107: setlist, 101: slot}}
```

### set_model — change block model (`change-pedal-from-app.pcapng`, packet [35]) — #3
```
OUT cmd=0x04  {102: tx_id, 100: 40,
              101: {98: block_index, 100: {23: no_snapshot_bypass, 25: wire_id, 26: -1}}}
IN  (event channel)  {105: 49, 106: {98: block_index, ...}}
IN  (event channel)  {105: 31, 106: {98: block_index, 70: 4, 79: True}}  ← 79:True = applied
```
- `98` = RAW index in DSP_CHAIN (input=0), same as `set_param` (`editor.block_index`).
- `100` = model node, same form as blob's `BLK_MODEL`: `25`=wire_id, `23`=no_snapshot_bypass, `26`=-1.
- In the capture: block 5 → wire_id 433 (`HD2_DistDeezOneVintageMono`). The pedal loads the model with its defaults and notifies them.
- Implemented in `device.set_model` and wired in `EditorView.apply_model` (`_write_model_to_device`).
- **Pending live validation:** confirm the pedal shows the new model and `save_preset` persists it; check whether params need to be re-read after the change (pedal defaults vs. catalog).

---

## Verification

1. Apply the two fixes and run `pytest tests/` (ignoring the 2 models.json failures).
2. Connect the pedal, load a preset, drag any slider → the parameter must
   change on the pedal in real time (not just parameter 0).
3. Click Save → the preset must be saved to the pedal's flash without crashing.
4. Change preset → the pedal must switch to the new preset.
