#!/usr/bin/env python3
"""Harvests wire_id/category/param order by traversing the pedal (read-only).

For each setlist slot: recall via MIDI → read object 23 (verify that the
recall succeeded and the name matches the backup) → read object 22 → cross-reference
each block of the blob with the homonymous preset of the backup (openpodgo.harvest).
At the end, it merges the result into src/openpodgo/data/models.json and returns
the pedal to the preset it was initially on.

It writes NOTHING to the pedal: only MIDI Program Changes (active preset changes)
and vendor reads. Close the app before running it (only one USB process).

Usage: python tools/harvest_catalog.py [--setlists 0,1] [--slots 0:128]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from openpodgo import harvest, pgb, preset  # noqa: E402
from openpodgo.midi import MidiOut  # noqa: E402
from openpodgo.session import Session  # noqa: E402
from openpodgo.usb_transport import TransportError, UsbTransport  # noqa: E402

DEFAULT_BACKUP = (
    ROOT / "captures" / "win-captures" / "POD Go Backup 2026-Jun-11(2).pgb"
)
MODELS_JSON = ROOT / "src" / "openpodgo" / "data" / "models.json"
SETLIST_NAMES = {0: "Factory", 1: "User"}


def wait_for_slot(session, setlist: int, slot: int, tries: int = 6):
    """Waits for object 23 to confirm the recall; returns the state."""
    for _ in range(tries):
        state = preset.read_active_state(session)
        if state.setlist == setlist and state.slot == slot:
            return state
        time.sleep(0.25)
    return None


def merge_into_models_json(results: dict, path: Path) -> tuple[int, int]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    merged = with_order = 0
    for name, r in sorted(results.items()):
        entry = doc["models"].get(name)
        if entry is None:
            print(f"[!] {name}: not in models.json (is the backup outdated?)")
            continue
        if entry["wire_id"] is not None and entry["wire_id"] != r.wire_id:
            raise SystemExit(
                f"CONFLICT {name}: models.json says wire_id "
                f"{entry['wire_id']}, harvest says {r.wire_id}"
            )
        entry["wire_id"] = r.wire_id
        entry["wire_category"] = r.category
        if entry["param_order"] is None and r.param_order is not None:
            entry["param_order"] = r.param_order
        merged += 1
        if entry["param_order"] is not None:
            with_order += 1
    path.write_text(
        json.dumps(doc, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return merged, with_order


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    ap.add_argument("--models", type=Path, default=MODELS_JSON)
    ap.add_argument(
        "--setlists", default="0,1",
        help="setlist indices to scan (0=Factory, 1=User)",
    )
    ap.add_argument(
        "--slots", default="0:128", help="slot range `start:end` (excl.)"
    )
    ap.add_argument(
        "--settle", type=float, default=0.3,
        help="wait seconds after each Program Change",
    )
    args = ap.parse_args()

    backup = pgb.read_backup(args.backup)
    setlists = [int(s) for s in args.setlists.split(",")]
    lo, hi = (int(x) for x in args.slots.split(":"))

    midi = MidiOut()
    transport = UsbTransport()
    try:
        print(f"[+] {transport.open()}")
    except TransportError as exc:
        print(f"[!] {exc}")
        return 1

    acc = harvest.Accumulator()
    scanned = skipped = 0
    try:
        session = Session(transport)
        initial = preset.read_active_state(session)
        print(f"[+] initial preset: {initial.name!r} "
              f"(setlist {initial.setlist}, slot {initial.slot})")
        for setlist in setlists:
            sl_name = SETLIST_NAMES.get(setlist, str(setlist))
            entries = backup.setlists.get(sl_name)
            if entries is None:
                print(f"[!] setlist {sl_name} is not in the backup")
                continue
            for slot in range(lo, min(hi, len(entries))):
                expected = entries[slot]
                if not expected:
                    continue
                midi.recall(setlist, slot)
                time.sleep(args.settle)
                state = wait_for_slot(session, setlist, slot)
                if state is None:
                    print(f"[!] {sl_name} {slot}: recall not confirmed, skipping")
                    skipped += 1
                    continue
                expected_name = expected["meta"]["name"]
                if state.name != expected_name:
                    print(
                        f"[!] {sl_name} {slot}: pedal says {state.name!r}, "
                        f"backup says {expected_name!r} — skipping (old backup?)"
                    )
                    skipped += 1
                    continue
                pre = preset.read_active_preset(session)
                warnings = acc.add_preset(pre, expected["tone"])
                scanned += 1
                for w in warnings:
                    print(f"[!] {sl_name} {slot} ({expected_name}): {w}")
                print(f"    {sl_name} {slot:3d} {expected_name:<18} ok")
        print("[+] returning the pedal to the initial preset...")
        midi.recall(initial.setlist, initial.slot)
    finally:
        transport.close()

    results = acc.resolved()
    merged, with_order = merge_into_models_json(results, args.models)
    unresolved = sorted(r.name for r in results.values() if r.param_order is None)
    print(
        f"\n[+] cross-referenced presets: {scanned} (skipped {skipped}) — "
        f"harvested models: {len(results)}, merged: {merged}, "
        f"with parameter order: {with_order}"
    )
    if unresolved:
        print(f"[i] without complete order yet ({len(unresolved)}): "
              + ", ".join(unresolved))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
