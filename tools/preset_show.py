#!/usr/bin/env python3
"""Shows the block chain of a preset (.bin dump or live pedal).

Offline:   python tools/preset_show.py --file captures/spec02_a.bin
With pedal: python tools/preset_show.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpodgo import catalog, l6helix  # noqa: E402


def fmt_val(v) -> str:
    return f"{v:.3f}" if isinstance(v, float) else str(v)


def show(pre: l6helix.Preset, header: str) -> None:
    print(f"== {header} — fw {pre.firmware} ({pre.product}), tempo {pre.tempo} ==")
    for pos, b in enumerate(pre.chain):
        if b is None:
            print(f"  [{pos}] (empty)")
            continue
        md = catalog.lookup(b.model_id)
        name = md.name if md else f"model {b.model_id} (out of catalog)"
        print(
            f"  [{pos}] {'ON ' if b.enabled else 'off'} "
            f"cat={b.category:>2} id={b.model_id:>3} {name}"
        )
        named = catalog.named_params(b.model_id, b.params)
        if named:
            print("        " + "  ".join(f"{k}={fmt_val(v)}" for k, v in named.items()))
        else:
            print("        " + "  ".join(fmt_val(v) for v in b.params))
    snaps = ", ".join(
        f"{s.name}{'*' if i == pre.current_snapshot else ''}"
        for i, s in enumerate(pre.snapshots)
        if s.valid
    )
    print(f"  valid snapshots: {snaps or '-'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--file",
        help="decode a .bin dump (message or blob) instead of reading the pedal",
    )
    ap.add_argument(
        "--save",
        help="save the raw object 22 message as a .bin fixture (with pedal)",
    )
    args = ap.parse_args()

    if args.file:
        raw = Path(args.file).read_bytes()
        blob = raw if raw[1:10] == l6helix.MAGIC else l6helix.extract_blob(raw)
        show(l6helix.parse_blob(blob), args.file)
        return 0

    from openpodgo import preset  # noqa: E402
    from openpodgo.session import Session  # noqa: E402
    from openpodgo.usb_transport import TransportError, UsbTransport  # noqa: E402

    t = UsbTransport()
    try:
        print(f"[+] {t.open()}")
    except TransportError as exc:
        print(f"[!] {exc}")
        return 1
    try:
        session = Session(t)
        state = preset.read_active_state(session)
        buf = preset.read_object(session, preset.OBJ_ACTIVE_PRESET)
        if args.save:
            Path(args.save).write_bytes(buf)
            print(f"[+] raw object 22 saved to {args.save} ({len(buf)} bytes)")
        pre = l6helix.parse_blob(l6helix.extract_blob(buf))
        show(pre, f"{state.name!r} (setlist {state.setlist}, slot {state.slot})")
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
