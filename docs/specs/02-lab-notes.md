# Spec 02 — Lab notes (preset dump discovery)

Pedal state during experiments: setlist ____, slot ____, preset "____".
(Pending confirmation with the user; probes E1-E4 are read-only.)

Each entry format: command executed, open response (ack/data and size),
number of chunks with payload, what `summarize` found (marker, entries),
and verdict (name-list / empty ack / error / CANDIDATE).

| # | Hypothesis | Command | Result | Verdict |
|---|-----------|---------|--------|---------|
| 0 | Base case (control): defaults = OPEN_STREAM Factory | `preset_explore.py` | open ack 16 B; 15 chunks with data; marker at 16; 128 entries | name-list (control OK) |
| E1 | k101.101 as field selector | `--k101 '{"107":0,"101":V}'` V=0,1,3,4,5,6,7,8,255 | **V=0: compact schema** `{idx: "name"}` direct, 2388 B, no internal map (capture `spec02_k101v0.bin`). V=1 and V>=2: standard 4-key schema, 3668 B, 128 entries | internal key 101 IS a schema selector, but only switches between compact(0) and standard(>=1); no "full mode" here |
| E2 | k100 as mode selector | `--k100 2` and `--k100 3` | open responds 36 B with `{102:1002, 103:255, 104:{111:-3}}` | **clean error**: response key 103 is a status code (0=OK, 255=error) and 104 the detail ({111:-3} ~ invalid argument). k100 only accepts 0/1 |
| E3 | k107 beyond setlist (edit buffer?) | `--k101 '{"107":2,"101":2}'` and `107:255` | same error `{103:255, 104:{111:-3}}` | 107 only accepts 0/1 (setlist); no "setlist 2 = edit buffer" |
| E4 | Sweep of resource ids in open 0x0C | `--sweep-resource 1003:1016` | all: ack 16 B and chunks serve the normal name list | device **ignores key 102** in stream open (or unknown ids fall to pending stream). The space to explore is open 0x04 (OPEN_PRESETS), not this |

| E5 | Variants of open 0x04 (k100=1,2,3) | `--open '{"102":1001,"100":V,"101":null}'` | error `{103:255,104:{111:-3}}` in all three; the subsequent 0x0C still serves the list | in 0x04, k100 only accepts 0 (setlist directory) and 254 (session) |
| E5b | Sweep of "resources" 1003-1012 in 0x04 | `--open '{"102":RID,...}'` | ALL status 0 with the SAME result (`[Factory, User]` directory), with rid echoed | **key 102 is a client TRANSACTION ID, not a resource** (1000/1001/1002 were sequential); the real object selector is key 100 |
| E6 | Object 0 via 0x0C; object 2 with other args | `--k100 0`; `--k100 2 --k101 null/{}/0` | obj 0: inline setlist directory (status 0); obj 2: error -3 with any arg | key 100 works the same in 0x04 and 0x0C; object 2 doesn't exist |
| E7 | **Sweep of key 100** (4-30) via 0x0C | `--k100 V --chunks 0` | 13, 14, 22, 23, 24 respond status 0; 19 and 29 error -45 (≠ -3: wrong args?); rest error -3 | **OBJECT MAP** (below) |

### Discovered object map (key 100, via open 0x0C)

| Object | Content | Capture |
|---|---|---|
| 0 | Setlist directory `[{0:"Factory"},{0:"User"}]` (inline) | — |
| 1 | Preset list of the setlist (k101 = `{107: setlist, 101: schema}`; schema 0=compact `{idx:name}`, ≥1=standard 4 keys) | `spec02_k101v0.bin` |
| 13 | Factory IR/cab directory: `[{104: md5, 109: name, 112: slot, 123/124/125}]` | `spec02_obj13.bin` |
| 14 | Per-slot checksums `[{slot: crc32}]`, 128 entries | `spec02_obj14.bin` |
| 19, 29 | Exist but reject the tested args (error -45) | — |
| **22** | **COMPLETE ACTIVE PRESET**: blob `l6-helix` + firmware version `v2.00-5-g665e64e` + product "P34" + u32 offset table + blocks with readable names ("Tube Drive", "Autofilter", "Growler", "Volume Pedal", "Mono FX Loop", "Parametric") + SNAPSHOT 1-4 + param floats. 3823 B inside key 104 | `spec02_obj22.bin` (message), `spec02_obj22_blob.bin` (blob) |
| 23 | **Active preset state** (inline): `{107: setlist, 108: slot, 109: name, 117: bool, 83: [...], ...}` — on capture: User/9/"BassPreset" | — |
| 24 | Flags `{118: 0, 119: true}` (meaning TBD) | — |

## Task 4 — Validation of object 22 as active preset

Candidate command: `python tools/preset_explore.py --k100 22 --save <file>`.
Pedal state at capture: **User, slot 9, "BassPreset"** (read from object 23,
not assumed).

- **Stability:** two consecutive dumps without touching anything → byte-identical
  (`spec02_a.bin` == `spec02_b.bin`, 3836 B).
- **Preset delta:** PC 10 via MIDI → object 23 starts reporting
  `{107:1, 108:10, 109:"Ilabaca"}` live; the dump (`spec02_otro_preset.bin`,
  3904 B) differs massively and its strings show OTHER blocks (Compulsive
  Drive, Triangle Fuzz, Script Phase, Fassel) with the same l6-helix
  container and SNAPSHOT 1-4. PC 9 back → dump byte-identical to `spec02_a.bin`
  (`spec02_vuelta.bin`). **Object 22 follows the active preset.**
- **Knob delta:** the user moved **Drive from ~43 to 47** (display) →
  `spec02_knob.bin` differs in EXACTLY 3 bytes (offsets 266-268 0-based):
  a msgpack float32 `ca 3e d7 0a 3c` (0.42) → `ca 3e f0 a3 d7` (0.47).
  **Parameters are normalized float32 0..1; the display shows ×100**
  (42 vs 43 is display rounding). Block context in the dump:
  `… 19 cd 01 6e … 0b 83 02 05 03 05 04 95 ca<float>×5 …` → key 25 = 366
  (block model id candidate), key 11 = map {2:5, 3:5, 4: array
  of 5 floats} with Drive as first element ([0.42, 0.66, 0.5, 0.5, 0.77]).
- **Reference `.pgp`:** ✅ exported (see "Windows loot" below) and
  cross-referenced against the blob — Task 4 complete, object 22 VALIDATED.

## Status at pause (11 Jun 2026) — how to resume

Branch `spec02-fase-a` (6 commits on `main`, 20 tests green, not merged).
Tasks 1-3 of the plan (`docs/superpowers/plans/2026-06-11-spec02-read-full-preset-fase-a.md`)
complete; Task 4 complete except for the `.pgp`. The user reboots to Windows to
export `captures/spec02_a.pgp` from POD Go Edit ("BassPreset", User slot 9;
note: Drive ended up at 47, was ~43 — doesn't matter for the export unless
you want the preset saved as-is, the dumps are already labeled).
Next step on return: with the `.pgp` in place, cross-reference numeric blob
keys against the JSON and write the **Phase B** plan using
superpowers:writing-plans (l6-helix container decoder, Preset/Block
dataclasses, offline tests with `spec02_*.bin`, model catalog).

### Blob structure (key 104 of the message, 3823 B in spec02_obj22_blob.bin)

`a9 "l6-helix\0"` + `da 0030` (str16 of 48 B: table of 12 ascending u32 LE
offsets: 0x3d, 0x5f, 0x2e5, 0x2e7, 0x413, 0x467, 0x621, 0x64b, 0x3e(?),
0x651, 0xeef, 0xeef) + MessagePack sections. Visible: firmware version
("v2.00-5-g665e64e"), product "P34", readable model names per block,
snapshots, `ca` param floats. Complete decoding = Phase B.

## Windows loot (11 Jun 2026) — Phase A closed

The entire checklist (`02-windows-checklist.md`) arrived at `captures/win-captures/`:
5 pcapng (connect/knob/save/preset_change/snapshot — input for specs 03/04),
both `.pgp` files and 3 `.pgb` backups. The BassPreset export came as
`spe02_a.pgp` (typo); canonical-name copies are at
`captures/spec02_a.pgp` and `captures/spec02_ilabaca.pgp`. The `build_sha` in
the JSON (`v2.00-5-g665e64e`) matches the blob. Note: the BassPreset `.pgp`
has Drive=0.47 (the user exported after moving the knob), so it matches
`spec02_knob.bin`, not `spec02_a.bin` (0.42).

### Blob ↔ .pgp mapping (validated with BOTH pairs)

The `.pgp` is JSON `schema: L6Preset` (Helix family format). The blob after the
offset table is a single msgpack map (the offsets point inside). Keys:

| Blob | .pgp JSON | Notes |
|---|---|---|
| `0` | `tone.dsp0` | `{21: dsp_idx, 22: [blocks]}` |
| `0.22[]` | blocks in chain order | `{19: class, 20: body}`; class 0=input, 1=output, 6=process block, 8=empty slot (body null) |
| block `20.24.25` | `@model` (as numeric id) | **stable across presets**: 224=HD2_VolPanVolStereo, 238=WahConductor, 366=DM4TubeDrive, 255=FilterAutoFilter, 119=FXLoopMono1, 3=AmpGCougar800, 60=Cab4x10Rhino, 472=EQ_STATIC_Parametric, 371=FM4Growler; (Ilabaca) 239=WahFassel, 88=CompulsiveDrive, 95=TriangleFuzz, 404=MM4ScriptPhase, 334=DL4DigDelay, 30=AmpMandarin80, 67=Cab4x12MandarinEM. Complete id→name catalog still missing (Phase B) |
| block `20.9` | — | model category: 1=FX, 8=delay, 9=fx loop, 15=cab, 17=amp, 23=static EQ |
| block `20.10` | `@enabled` | |
| block `20.11` | params | `{2: n_total, 3: n_snapshoteables, 4: [values]}` in **model definition order** (not alphabetical as in JSON); includes extras like `@trails`/`@mic` at the end |
| block `20.24.23` | `@no_snapshot_bypass` | (26: -1, TBD) |
| input `20.5` / output `20.6` | `@input` / `@output` | params: input `[noiseGate, threshold, decay]`, output `[pan, gain]` |
| `1` | `tone.dsp1` | null in POD Go (single DSP) |
| `3` | `tone.footswitch` | `{8: [groups per switch]}`; entry `{11: {5: name+'\0', 6: ledcolor, 7: state, 8: block_idx_1based}}` |
| `4` | `tone.controller` | **(corrected in editor-ui)** non-indexed-by-slot list; entry `{0: ordinal, 1: {0: @controller number, 2: @min, 3: @max, 4: param_idx}}`. Destination block is implicit by role (1=EXP wah, 2=EXP volume) and per-snapshot values (key 2 of the snapshot) align by number-1. Internal key 5 is NOT the @controller (differs between the two .pgp with the same @controller). See `editor.py` |
| `5` | `tone.global` | `16` = `@tempo` |
| `7` | `data.meta`/device | `{35: device_version (33619968 ✓), 36: "P34\0", 37: build_sha}` (duplicated inside `0.7`) |
| `10` | snapshots | `{6: @current_snapshot, 8: @pedalstate, 10: [4 × {0: @valid, 2: [controller values], 3: [12 × [?, enabled] per slot: input, 10 blocks, output], 4: name+'\0', 5: @tempo, 11: @pedalstate}]}` |
| `2`, `6` | — | TBD (all zeros / `{26:0, 98:3}`) |

Blob strings are NUL-terminated. The only thing missing for 100% decoding is
the **model catalog** (id → `HD2_*` name + param order/name): can be seeded
with the two `.pgp`↔blob pairs and grown with factory presets.

### Wire reads confirmed by E2/E3 (useful for everything that follows)

An open response is a map `{102: <echoed resource>, 103: <status>,
104: <result>}`: `103=0` OK (as the first data packet of the User arrives,
see protocol.md), `103=255` error with `104={111: <code>}` (seen -3).
This gives a binary accepted/rejected criterion for sweeping keys.

## Phase B — live validation (11 Jun 2026)

`tools/preset_show.py` against the real pedal, decoder + catalog green:

- **Surprise: firmware updated.** The pedal now reports
  `v2.01-19-g6e98447` (the Windows session with POD Go Edit updated it;
  captures were from `v2.00-5-g665e64e`). The container and key mapping
  didn't change: everything decodes the same.
- **Unknown preset ("RINDANSE", User slot 7):** complete readable chain;
  4 out-of-catalog models, expected: ids **135** (drive, 6 params),
  **363** (drive/fuzz, 5), **86** (delay, 11), **473** (EQ low/high cut, 5).
  Candidates for growing the catalog. Curious detail: the snapshot line
  came out without `*` (current_snapshot ≠ 0 with a single valid snapshot) —
  review key 6 of node 10 when snapshots are decoded thoroughly.
- **Known case (BassPreset, User slot 9, recall via MIDI `recall(1, 9)`):**
  chain and params identical to `spec02_a.bin` except `Drive=0.50` (the knob
  ended up in a different position from the capture, as the plan anticipated).
  The owner confirmed against the POD Go screen: name, active blocks
  (vol/amp/cab) and Drive ~50. **Object 22 + decoder + catalog
  validated live, even after the firmware change.**
