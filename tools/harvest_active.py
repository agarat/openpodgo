#!/usr/bin/env python3
"""Fills wire_category from the ACTIVE preset on the pedal (read-only).

Complements tools/harvest_catalog.py: that one only reaches models that
appear in a backup preset; this one grabs the on-wire category (block key 9)
of whatever blocks are in the CURRENTLY ACTIVE preset, straight from the blob
— no backup and no save needed. Build a scratch preset with the blocks you
want to harvest (up to 4 effect blocks; one looper at a time), make it active,
and run this. Repeat until nothing is missing.

It writes NOTHING to the pedal: a single vendor read of object 22. Close the
app before running it (only one USB process).

Usage: python tools/harvest_active.py [--models PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from openpodgo import l6helix, preset  # noqa: E402
from openpodgo.session import Session  # noqa: E402
from openpodgo.usb_transport import TransportError, UsbTransport  # noqa: E402

MODELS_JSON = ROOT / "src" / "openpodgo" / "data" / "models.json"
#: Categories whose wire_category is populated only by harvest (spec03).
_HARVEST_CATEGORIES = ("Dyn", "Pitch", "Looper")


def _chain_blocks(blob: bytes) -> list[tuple[int, int, int]]:
    """(position, model_id, on-wire category) of each block in the chain.

    Walks the raw chain so it survives block classes the core decoder does
    not model yet: normal effects are class 6 (model id at 24→25); the looper
    is class 7 (model id directly at key 8). Both carry the on-wire category
    at key 9. Input/output/empty (0/1/8) are skipped.
    """
    import msgpack

    _, body_bytes = l6helix.split_container(blob)
    body = msgpack.unpackb(body_bytes, raw=False, strict_map_key=False)
    out: list[tuple[int, int, int]] = []
    for pos, entry in enumerate(body[l6helix.BODY_DSP0][l6helix.DSP_CHAIN]):
        cls = entry[l6helix.ENTRY_CLASS]
        payload = entry[l6helix.ENTRY_PAYLOAD]
        if cls == l6helix.CLASS_BLOCK:  # 6: normal effect
            model_id = payload[l6helix.BLK_MODEL][l6helix.MODEL_ID]
        elif cls == 7:  # looper: model id lives directly at key 8
            model_id = payload[8]
        else:  # input / output / empty
            continue
        out.append((pos, model_id, payload[l6helix.BLK_CATEGORY]))
    return out


def _name_by_wire_id(doc: dict) -> dict[int, str]:
    return {
        m["wire_id"]: name
        for name, m in doc["models"].items()
        if m.get("wire_id") is not None
    }


def _remaining(doc: dict) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {c: [] for c in _HARVEST_CATEGORIES}
    for name, m in doc["models"].items():
        cat = m.get("category")
        if cat in out and m.get("wire_category") is None:
            out[cat].append(name)
    return {c: sorted(v) for c, v in out.items()}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--models", type=Path, default=MODELS_JSON)
    ap.add_argument(
        "--dry-run", action="store_true",
        help="show what would be filled without writing models.json",
    )
    args = ap.parse_args()

    doc = json.loads(args.models.read_text(encoding="utf-8"))
    by_id = _name_by_wire_id(doc)

    transport = UsbTransport()
    try:
        print(f"[+] {transport.open()}")
    except TransportError as exc:
        print(f"[!] {exc}")
        return 1
    try:
        session = Session(transport)
        state = preset.read_active_state(session)
        buf = preset.read_object(session, preset.OBJ_ACTIVE_PRESET)
        blocks = _chain_blocks(l6helix.extract_blob(buf))
    finally:
        transport.close()

    print(f"[+] active preset: {state.name!r} "
          f"(setlist {state.setlist}, slot {state.slot})")

    filled = 0
    for pos, model_id, category in blocks:
        name = by_id.get(model_id)
        if name is None:
            print(f"    [{pos}] id={model_id}: not in models.json, skipping")
            continue
        entry = doc["models"][name]
        old = entry.get("wire_category")
        if old is None:
            entry["wire_category"] = category
            filled += 1
            print(f"    [{pos}] {name}: wire_category = {category}  (NEW)")
        elif old != category:
            print(f"    [!] {name}: models.json={old} but pedal={category} "
                  "— NOT overwriting (check RE)")
        else:
            print(f"    [{pos}] {name}: already {old}, ok")

    if filled and not args.dry_run:
        args.models.write_text(
            json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        print(f"[+] merged {filled} new categories into {args.models.name}")
    elif filled:
        print(f"[i] dry-run: {filled} would be filled (nothing written)")
    else:
        print("[i] nothing new in this preset")

    rem = _remaining(doc)
    total = sum(len(v) for v in rem.values())
    print(f"\n[i] still without wire_category ({total}):")
    for cat, names in rem.items():
        if names:
            print(f"    {cat} ({len(names)}): {', '.join(names)}")
    if total == 0:
        print("    — none! Dyn/Pitch/Looper fully harvested.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
