"""Generates src/openpodgo/data/models.json (offline).

Primary source: the official POD Go Edit resources (captures/podgo-edit-res):
PodGo.sym gives the wire_id (array index) and the positional order of params;
*.models give display name, defaults and ranges; PGModelCatalog.json the
categories. Cross-validated against:

- the hand-seeded catalog (`catalog.MODELS`, 16 models verified against the
  pedal) — any discrepancy aborts;
- the post-v2.01 .pgb backup (observed param sets and @type);
- the local vendor dumps (on-wire category, block key 9).

The on-wire category of models never seen in a blob is inferred from the
official category ONLY where there is at least one validated data point; the
rest stays null until the harvest (tools/harvest_catalog.py). Models with
attributes lacking on-wire evidence (@stereo, Pan, Lock) keep param_order null.

Usage: python tools/build_catalog.py
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from openpodgo import catalog, l6helix, l6res, pgb  # noqa: E402

DEFAULT_RES = ROOT / "captures" / "podgo-edit-res"
DEFAULT_BACKUP = (
    ROOT / "captures" / "win-captures" / "POD Go Backup 2026-Jun-11(2).pgb"
)
DEFAULT_OUT = ROOT / "src" / "openpodgo" / "data" / "models.json"
#: Local vendor dumps (object 22): on-wire category of their models.
DEFAULT_BLOBS = (
    ROOT / "captures" / "spec02_knob.bin",
    ROOT / "captures" / "spec02_otro_preset.bin",
    # spec08: carries an Effects-EQ (Acoustic Sim, cat=1) and the dedicated
    # Preset EQ (cat=23) — confirms the on-wire category of EQs vs the pedal.
    ROOT / "captures" / "eq_acoustic_sim_obj22.bin",
)

#: Official category → on-wire category (block key 9). Only entries with at
#: least one model validated against a real dump; re-verified against the
#: dumps on every build. EQ is split by prefix (EQ_STATIC_* are blob 23; the
#: "effect" EQs have no data).
WIRE_CATEGORY = {
    "Dist": 1,
    "Wah": 1,
    "Vol": 1,
    "Filter": 1,
    "Mod": 1,
    "Delay": 8,
    "Reverb": 1,
    "Send/Return": 9,
    "Cab": 15,
    "Amp": 17,
}
#: Display-name fixes for resource typos. The `.models` file names this model
#: "Warble Eater", but the pedal screen and PGModelCatalog.json say "Warble
#: Matic" (confirmed against the pedal). Keyed by .sym symbol.
DISPLAY_NAME_OVERRIDES = {
    "Warble_Matic": "Warble Matic",
}
EQ_STATIC_PREFIX = "HD2_EQ_STATIC_"
EQ_STATIC_WIRE_CATEGORY = 23
#: Non-STATIC EQs (Cali Q … Acoustic Sim) live in an Effects block, so they
#: report on-wire category 1 like any effect — confirmed against the pedal
#: (captures/eq_acoustic_sim_obj22.bin, spec08). The official source has no
#: on-wire category for the "effect" EQs; this is an RE override.
EQ_EFFECTS_WIRE_CATEGORY = 1

#: Input/Output are not chain blocks and their official definition is the
#: POD Go Wireless superset (8 params vs 3 on-wire): the editor handles them
#: separately (editor.INPUT_PARAM_NAMES); they stay out of models.json.
_EXCLUDED_CATEGORIES = ("Input", "Output")


def _wire_categories(blob_paths) -> dict[int, int]:
    """model_id -> category (key 9) from the local vendor dumps."""
    cats: dict[int, int] = {}
    for path in blob_paths:
        pre = l6helix.parse_blob(l6helix.extract_blob(path.read_bytes()))
        for block in pre.chain:
            if block is not None:
                cats[block.model_id] = block.category
    return cats


def _infer_wire_category(model: l6res.ResModel) -> int | None:
    if model.symbol.startswith(EQ_STATIC_PREFIX):
        return EQ_STATIC_WIRE_CATEGORY
    if model.category == "EQ":
        return EQ_EFFECTS_WIRE_CATEGORY
    return WIRE_CATEGORY.get(model.category)


def _validate(
    resources, backup_models, observed_cats
) -> tuple[dict[str, int], dict[str, list[str]]]:
    """Hard checks across sources.

    Returns (name -> @type from the backup, name -> resource params the .pgp
    does not serialize, e.g. IrData of the HX cabs: with no on-wire evidence
    they make the model uncertain).
    """
    for mid, md in catalog.MODELS.items():
        rm = resources.get(md.name)
        if rm is None or rm.wire_id != mid or rm.param_order != md.params:
            raise SystemExit(
                f"{md.name}: seeded (id {mid}, {md.params}) != resources "
                f"({rm.wire_id if rm else '-'}, "
                f"{rm.param_order if rm else '-'})"
            )
    types: dict[str, int] = {}
    extra_attrs: dict[str, list[str]] = {}
    for name, bm in backup_models.items():
        rm = resources.get(name)
        if rm is None:
            raise SystemExit(f"{name}: in the backup but not in the resources")
        if rm.category in _EXCLUDED_CATEGORIES:
            continue
        missing = set(bm.params) - set(rm.param_order)
        if missing:
            raise SystemExit(
                f"{name}: the backup uses params the resources do not list: "
                f"{sorted(missing)}"
            )
        extra = sorted(set(rm.param_order) - set(bm.params))
        if extra:
            extra_attrs[name] = extra
        if bm.type is not None:
            types[name] = bm.type
    by_id = {rm.wire_id: rm for rm in resources.values()}
    for mid, cat in observed_cats.items():
        inferred = _infer_wire_category(by_id[mid])
        if inferred is not None and inferred != cat:
            raise SystemExit(
                f"{by_id[mid].symbol}: observed on-wire category {cat} "
                f"!= inferred {inferred}"
            )
    return types, extra_attrs


def _infer_types(resources, types: dict[str, int]) -> dict[str, int]:
    """Fills @type by official category where the backup is unanimous."""
    by_cat: dict[tuple, set[int]] = defaultdict(set)
    for name, t in types.items():
        rm = resources[name]
        by_cat[(rm.category, rm.subcategory)].add(t)
    inferred = dict(types)
    for rm in resources.values():
        if rm.symbol in inferred:
            continue
        candidates = by_cat.get((rm.category, rm.subcategory))
        if candidates and len(candidates) == 1:
            inferred[rm.symbol] = next(iter(candidates))
    return inferred


def build(
    backup_path: Path,
    out_path: Path,
    res_dir: Path = DEFAULT_RES,
    blob_paths=DEFAULT_BLOBS,
) -> dict:
    resources = l6res.load_resources(res_dir)
    backup_models = pgb.extract_models(pgb.read_backup(backup_path))
    observed_cats = _wire_categories(blob_paths)
    types, extra_attrs = _validate(resources, backup_models, observed_cats)
    types = _infer_types(resources, types)

    doc: dict = {
        "source": {"res": res_dir.name, "backup": backup_path.name},
        "models": {},
    }
    for name in sorted(resources):
        rm = resources[name]
        if rm.category in _EXCLUDED_CATEGORIES:
            continue
        bm = backup_models.get(name)
        params = {}
        defaults = {}
        for pname in rm.param_order:
            rp = rm.params.get(pname)
            brange = bm.params.get(pname) if bm else None
            if rp is None:
                # In .sym but with no metadata in .models (IrData of some
                # HX cabs): only whatever the backup says.
                params[pname] = {
                    "min": brange.vmin if brange else None,
                    "max": brange.vmax if brange else None,
                    "bool": brange.is_bool if brange else False,
                    "value_type": None,
                    "display_type": None,
                }
                defaults[pname] = bm.defaults.get(pname) if bm else None
                continue
            params[pname] = {
                "min": rp.vmin if rp.vmin is not None else
                       (brange.vmin if brange else None),
                "max": rp.vmax if rp.vmax is not None else
                       (brange.vmax if brange else None),
                "bool": rp.is_bool,
                "value_type": rp.value_type,
                "display_type": rp.display_type,
            }
            defaults[pname] = (
                rp.default if rp.default is not None
                else (bm.defaults.get(pname) if bm else None)
            )
        no_default = [p for p, v in defaults.items() if v is None]
        for p in no_default:
            defaults[p] = 0 if params[p]["bool"] else 0.0
        uncertain = sorted(
            {*rm.uncertain, *extra_attrs.get(name, ())}
        )
        doc["models"][name] = {
            "display_name": DISPLAY_NAME_OVERRIDES.get(name, rm.display_name),
            "category": rm.category,
            "subcategory": rm.subcategory,
            "type": types.get(name),
            "wire_id": rm.wire_id,
            "wire_category": observed_cats.get(rm.wire_id)
            if rm.wire_id in observed_cats
            else _infer_wire_category(rm),
            "param_order": list(rm.param_order) if rm.param_order else None,
            "uncertain": uncertain,
            "params": params,
            "defaults": defaults,
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return doc


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    ap.add_argument("--res", type=Path, default=DEFAULT_RES)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    doc = build(args.backup, args.out, args.res)
    models = doc["models"].values()
    swappable = sum(
        1 for e in models
        if e["param_order"] and e["wire_category"] is not None
    )
    uncertain = sum(1 for e in models if e["uncertain"])
    print(
        f"{args.out}: {len(doc['models'])} models, {swappable} swappable "
        f"(wire_id+order+category), {uncertain} with uncertain attributes"
    )


if __name__ == "__main__":
    main()
