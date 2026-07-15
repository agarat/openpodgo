# Spec 02 — Read the full content of a preset (blocks/params)

## Objective

Currently only the **name** of each preset (key 109) is read. For a real editor
the complete active preset must be dumped: the block chain (amp, cab, drives,
mods, delays, reverb, EQ, wah/vol), each block's model and its parameters,
plus routing and snapshots. This is the foundation of `ui/chain_view` and
`ui/param_panel`.

## What is known

- The **preset list** stream (`OPEN_PRESETS` → `OPEN_STREAM` → chunks)
  returns a per-preset map with only lightweight metadata
  (`{109: name, 123: bool, 124: bool, 125: int}`). It does NOT carry the blocks.
- Therefore the full content is obtained with **another vendor operation**
  (another resource/stream), still unidentified.
- Reference: `https://github.com/allansomensi/openhx` documents listing presets
  in HX Stomp XL; the dump of an individual preset is not documented there (was
  "planned" in openhx). Check the openhx repo for updates.
- The `.pgp` files (exported by POD Go Edit) are **JSON** and describe the
  complete preset (blocks + params). They serve as a reference schema for the
  data model even though the on-wire representation is MessagePack.

## RE plan

1. **Capture the active preset via vendor.** With the pedal on a known preset,
   try variants of the stream flow targeting the "current preset" resource
   instead of "name list". Hints in packets: the keys of the
   `OPEN_PRESETS`/`OPEN_STREAM` map (102=1001/1002 seems to be a resource id;
   100, 101, 107 parameters). Change the id/resource and observe responses with
   `tools/diag.py`.
2. **Change the preset on the pedal and dump again** to see which bytes change
   (diff) → locate where model and parameters live. `tools/capture.py` helps
   label (the user moves a knob; the delta is captured).
3. **Decode the MessagePack** of the preset: identify block keys,
   the `@model` (Line 6 model id) and parameter values. Cross-reference with
   a `.pgp` exported from the same preset (ask the user for one) to map numeric
   keys → readable names.
4. **Model catalog** (`src/openpodgo/catalog.py`, currently a stub): populate id→name
   and parameters from the official POD Go manual (public PDF) and from observed
   `.pgp` files. The `vesco-helixnamer` repo has internal-id→real-name pairs.

## Suggested data model

Extend `preset.py` with a `Preset` dataclass: metadata, list of
`Block(model_id, category, bypassed, params: dict)` and routing. Keep the bridge
to `.pgp` (`load_pgp`/`save_pgp` already exist) for import/export and
interoperability with the official app and CustomTone.

## Success criterion

Dump the active preset and reconstruct its block chain with models and
parameters, validated against the `.pgp` exported from the same preset (same
blocks, same values).

## Status (June 2026): RESOLVED (reading)

Phase A discovered the dump (object 22; `docs/specs/02-lab-notes.md`) and
Phase B decoded it: `l6helix.py` (container → `Preset`/`Block`/`Snapshot`),
`catalog.py` (16 models seeded, validated against two `.pgp`),
`preset.read_active_preset()`, CLI `tools/preset_show.py`. The success
criterion was met: chain + models + parameters reconstructed and validated
against `.pgp` (tests `tests/test_catalog.py`) and against the pedal live
(even after the update to firmware v2.01). Next: grow the catalog with
more presets (ids 86, 135, 363, 473 were seen out of catalog live) and
decode footswitch/controller when the UI needs it.
