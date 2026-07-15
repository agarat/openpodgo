# Spec 03 — Lab notes (write commands)

Source: USBPcap captures of POD Go Edit (`captures/win-captures/`, 11 Jun 2026,
fw v2.01-19-g6e98447, POD Go Edit on Windows 11).

## Write channel (src=0x1080 → dst=0x03ED)

The official editor opens a **second channel** for writing, independent of the
read channel (0x1001→0x03EF). The write channel has its own 4-packet handshake:

| # | cmd | len | Description | Read equivalent |
|---|---|---|---|---|
| 1 | 0x02 | 20 | HANDSHAKE (magic 0x28) | HANDSHAKE with src/dst swapped |
| 2 | 0x04 | 28 | SESSION_OPEN | SESSION_OPEN_1 |
| 3 | 0x08 | 16 | SESSION_CHUNK | SESSION_CHUNK_1 |
| 4 | 0x04 | 36 | SESSION_OPEN with `{102:1000, 100:76, 101:{}}` | SESSION_OPEN_2 |

After the handshake, the first app seq is 0x06 (same convention).

## Control: win_connect

Full flow: read handshake → write handshake → reads of objects 23 (active state),
22 (active preset), 13 (IR list), 1 (presets) over both channels, plus UI flag
initialization (obj 24, `{118: 14}` → `{118: 73}`) and then cyclic cmd=0x10 polling.

## Parameter set (win_knob)

**Write packet (cmd=0x04):**

```hex
27 00 00 18 80 10 ed 03 00 64 00 04 84 2f 00 00
01 00 06 00 17 00 00 00
83 66 cd 03 f2 64 1e 65 85 62 03 1d c3 1a 00 1c 00 00 77 ca 3e f0 a3 d7 00
```

**Decoded msgpack body:**
`{102: 1010, 100: 30, 101: {98: 3, 29: True, 26: 0, 28: 0, 119: 0.47}}`

- `100=30`: "set param" object
- `101.98=3`: block index (pending live validation)
- `101.119=0.47`: normalized float32 0..1 value (Drive=47%)
- `101.29=True`: probably bypass enabled
- Only 3 writes in the entire capture, despite 17 cmd=0x10 polling packets
- cmd=0x10 packets are read POLLING (~1 Hz), NOT writes

## Snapshot change (win_snapshot)

`{102: 1018, 100: 88, 101: {92: 2}}` → cmd=0x04

- `100=88`: "set snapshot" object
- `101.92=2`: snapshot index (0-3)

## Preset change (win_preset_change)

`{102: 1014, 100: 20, 101: {107: 1, 108: 7}}` → cmd=0x04

- `100=20`: "change preset" object
- `101.107=1`: setlist (1=User)
- `101.108=7`: slot

Then reads obj 23 (state) and obj 22 (preset) to confirm: cmd=0x0c, `{100: 22, 101: None}`.

## Save to pedal (win_save)

`{102: 1013, 100: 71, 101: {107: 1, 108: 9, 109: 'BassPreset\x00'}}` → cmd=0x04

- `100=71`: "save preset" object
- name is NUL-terminated (0x00 at end)
- Then refresh of the setlist (read obj 1 on the read channel)

## Summary table

| Operation | k100 | k101 | cmd | Risk |
|---|---|---|---|---|
| Change preset | 20 | `{107: sl, 108: slot}` | 0x04 | Low |
| Set snapshot | 88 | `{92: idx}` | 0x04 | Low |
| Set param | 30 | `{98: block, 119: val, 29: bypass, 26:0, 28:0}` | 0x04/0x0c | Medium |
| Save preset | 71 | `{107: sl, 108: slot, 109: name}` | 0x04 | High |

## Open questions for live validation

1. `101.98` = which block index? 0-based like the chain or 1-based?
2. cmd=0x04 vs 0x0c: write vs commit, or interchangeable?
3. Is the write handshake necessary or can the read channel be reused?
