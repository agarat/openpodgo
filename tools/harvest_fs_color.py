#!/usr/bin/env python3
"""INTERACTIVE harvest of footswitch LED color (spec 09).

Steps through the fixed palette of the POD Go (Auto, White, Red, ...): for each color
it asks you to set it on the pedal, press Enter, and the script reads the on-wire
integer only. Finally it prints the name→integer table ready to copy. You write nothing down.

The palette↔integer mapping is not in the resources (factory presets use
"Auto" = color by category), which is why it must be harvested from the pedal.

Usage (close the app before running; only one process claims the vendor interface):

    python tools/harvest_fs_color.py
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import msgpack

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpodgo.device import PodGo  # noqa: E402
from openpodgo.editor import PresetEditor  # noqa: E402

#: Fixed palette of POD Go Edit (order of res/strings/appStrings_eng.json).
PALETTE = [
    "Auto", "White", "Red", "Dark Orange", "Light Orange", "Yellow",
    "Green", "Turquoise", "Blue", "Violet", "Pink", "Off",
]


def _read_fs_colors(pod: PodGo) -> dict[int, tuple[str, str, int]]:
    """slot → (footswitch, label, ledcolor) of blocks with bypass assign.

    Re-handshake BEFORE reading: reusing the session without re-synchronizing
    returns the old buffer (see docs/specs/00-roadmap.md, "Method notes"), which
    is exactly what caused the color to read identical on each read.
    """
    pod._session.handshake()  # type: ignore[union-attr]
    ed = PresetEditor(pod.active_preset())
    out: dict[int, tuple[str, str, int]] = {}
    for slot, blk in enumerate(ed.preset.chain):
        if blk is None:
            continue
        target = ed.bypass_target(slot)
        if target is None:
            continue
        out[slot] = (target, ed.footswitch_label(slot) or "", ed.footswitch_color(slot))
    return out


def _read_diag(pod: PodGo, slot: int):
    """(color, raw_fs_entry, body_hash) after fresh reread.

    Diagnosis: if customizing the color on the pedal changes neither the
    footswitch entry nor the preset hash, the change does not land in the active
    preset blob (object 22) — it probably needs a Save on the pedal or
    lives in another structure (global / stomp display).
    """
    for _ in range(3):
        try:
            pod._session.handshake()  # type: ignore[union-attr]
            ed = PresetEditor(pod.active_preset())
            entry = ed._fs_entry(slot)
            body_hash = hashlib.sha1(
                msgpack.packb(ed.body, use_single_float=True)
            ).hexdigest()[:10]
            color = ed.footswitch_color(slot)
            return color, entry, body_hash
        except Exception as exc:  # noqa: BLE001 - RE diagnosis
            print(f"    (reread retry: {exc!r})")
    return None, None, None


def main() -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    print("=== Footswitch LED color harvest (spec 09) ===\n")
    try:
        pod = PodGo()
        pod.connect()
    except Exception as exc:  # noqa: BLE001 - RE diagnosis
        print(f"[!] Could not connect to the pedal: {exc!r}")
        print("    (is the app open? close it: only one process can claim USB)")
        return 1

    try:
        fs = _read_fs_colors(pod)
        if not fs:
            print("[!] The active preset has no bypass assignments.")
            print("    Assign a block to a footswitch first (in the app or the pedal).")
            return 1

        print("Footswitches with assignment in the active preset:")
        for slot, (target, label, color) in sorted(fs.items()):
            print(f"   slot {slot:>2}  {target:<8}  {label!r:<16}  color={color}")
        default_slot = sorted(fs)[0]
        raw = input(f"\nWhich slot will you use for the test? [{default_slot}]: ").strip()
        slot = int(raw) if raw else default_slot
        if slot not in fs:
            print(f"[!] Slot {slot} has no bypass assignment.")
            return 1

        target = fs[slot][0]
        print(
            f"\nWe will use footswitch {target} (slot {slot}).\n"
            "For each color: set it on the pedal\n"
            "  (Stomp: press Action on the FS > Customize > Footswitch Color)\n"
            "and press Enter. Commands: [Enter]=read  s=skip  q=quit.\n"
        )

        results: dict[str, int] = {}
        for i, name in enumerate(PALETTE, 1):
            cmd = input(f"[{i:>2}/{len(PALETTE)}] Set {target} to >>> {name} <<< and press Enter: ").strip().lower()
            if cmd == "q":
                break
            if cmd == "s":
                print("    (skipped)")
                continue
            color, entry, body_hash = _read_diag(pod, slot)
            if color is None:
                print("    [!] could not read color, continuing")
                continue
            results[name] = color
            print(f"    → {name:<12} = {color}  (0x{color & 0xFFFFFF:06X})")
            print(f"      [diag] body={body_hash}  fs_entry={entry}")
    finally:
        pod.disconnect()

    print("\n=== Summary (copy me this) ===")
    for name in PALETTE:
        if name in results:
            c = results[name]
            print(f"  {name:<12} = {c:<10}  0x{c & 0xFFFFFF:06X}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
