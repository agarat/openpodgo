# Spec 12 — Block focus on the pedal (app → pedal)

Status: ✅ **resolved** — the select command was found in a USBPcap capture of
POD Go Edit (op **78**) and is implemented.

## Symptom

Selecting another block in the app changed the app's panel, but the pedal kept
its own selection: its screen showed the previous block and its physical knobs
kept editing it. When it did change, it went back to the previous block a
moment later.

## The command (found in a USBPcap capture of POD Go Edit)

Clicking a block in POD Go Edit's chain sends this on the **write channel**
(0x1080 → 0x03ED, cmd 0x04), decoded from the `win_block_select` capture:

```
{102: <tx_id>, 100: 78, 101: {98: <raw block index>}}
```

- Cab click      → `{102: 1010, 100: 78, 101: {98: 7}}`   (cab = raw block 7)
- Screamer click → `{102: 1011, 100: 78, 101: {98: 3}}`   (raw block 3)
- Block delete   → `{102: 1016, 100: 78, 101: {98: 3}}`

The pedal answers `{103: 0, 104: nil}` and then emits an event
`{105: 39, 106: {…, 106: {98: <block>, 26: 0, …}}}`. `98` is the same raw
`DSP_CHAIN` index `set_param` uses (input = 0), i.e. `PresetEditor.block_index`.

`device.select_block(block_index)` builds exactly that packet;
`MainWindow._on_block_selected` (wired to `EditorView.block_selected`, emitted
by `select_slot` / `select_io`) sends it, so the pedal's screen and physical
knobs follow the block selected in the app.

## Earlier (wrong) hypotheses, kept for the record

Before the capture, these were measured live with a knob-turn probe on the event
channel (op 30 notifications carry `98: block`, so the pedal itself reports which
block it is editing):

| action | pedal focus afterwards |
|---|---|
| `op 33 {101: {102: <block>}}` (what POD Go Edit sends after every edit) | **unchanged** |
| `op 33` + `op 23 {None}` + `op 22 {None}` (the "apply/refresh" triple) | **unchanged** |
| `set_param` on a block (op 30) | **moves to that block** |
| ~2.5 s after that write | **reverts** to the pedal's own selection |

`op 33` turned out to be a **read** of the block descriptor — it answers
`{102: <slot>, 65: False, 109: None, 66: None, 67: [<assignments>]}` and rejects
raw index 0 with `{111: -3}` — not a selection. A temporary workaround (poke a
parameter of the block) was used until the capture arrived; it is gone.

## Opcode sweep attempt (what NOT to repeat)

A brute-force sweep over the opcode space was tried with a block-index payload
`{102: <block>}` (each op given a fresh write handshake every 16 commands):

- **`op 87`** answered `103: 1`; **`op 90`, `91`, `92`** answered `103: 0` with
  `104: None`. None of them echoed the block index, so none looks like a
  "select": a real selection should at least report which block it took.
- **`op ≥ 93` is dangerous**: `93`, `94` and `95` answered nothing and `op 96`
  left the pedal's vendor endpoint refusing bulk writes (writes time out, the
  USB `dev.reset()` does not clear it). Recovery requires a physical
  **power cycle** of the pedal.

So: only sweep with (a) a per-op sanity check (e.g. `op 33` must still answer),
(b) results written to disk as you go, and (c) an immediate stop on the first
silent op. Better still, don't sweep: capture POD Go Edit clicking a block (see
above) — one packet, no risk to the pedal.
