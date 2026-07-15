#!/usr/bin/env python3
"""Labeled capture of bulk-IN traffic while the user operates the pedal.

After the handshake, it listens to the bulk IN endpoint and logs everything the
POD Go emits. The user describes what action they performed (change preset, move a
knob, toggle a block) and each capture is associated with that label, generating
a dataset to map the MessagePack schema of the POD Go.

Interactive use:

    python tools/capture.py --label "change to preset 02B"
    # move something on the pedal; Ctrl-C stops and saves the log

Output: captures/<timestamp>_<label>.json with the packets in hex.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpodgo.session import Session  # noqa: E402
from openpodgo.usb_transport import TransportError, UsbTransport  # noqa: E402

CAPTURES_DIR = Path(__file__).resolve().parent.parent / "captures"


def main() -> int:
    ap = argparse.ArgumentParser(description="Labeled capture of bulk-IN from POD Go")
    ap.add_argument("--label", required=True, help="what action you are going to perform on the pedal")
    ap.add_argument("--seconds", type=float, default=0, help="0 = until Ctrl-C")
    ap.add_argument("--no-handshake", action="store_true",
                    help="do not perform handshake (only listen to raw IN)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    CAPTURES_DIR.mkdir(exist_ok=True)

    transport = UsbTransport()
    try:
        info = transport.open()
    except TransportError as exc:
        print(f"[!] Could not open device: {exc}")
        return 1
    print(f"[+] {info}")

    captured: list[dict] = []
    try:
        if not args.no_handshake:
            Session(transport).handshake()
            print("[+] Handshake OK")
        print(f"[*] Capturing IN for: {args.label!r}. Operate the pedal. Ctrl-C to stop.")
        start = dt.datetime.now()
        while True:
            if args.seconds and (dt.datetime.now() - start).total_seconds() >= args.seconds:
                break
            try:
                data = transport.read(timeout_ms=1000)
            except TransportError:
                continue  # timeout: nothing to read right now
            if data:
                ts = (dt.datetime.now() - start).total_seconds()
                captured.append({"t": round(ts, 4), "len": len(data), "hex": data.hex()})
                print(f"    +{ts:7.3f}s  {len(data):4d} bytes  {data[:32].hex()}")
    except KeyboardInterrupt:
        print("\n[*] Capture stopped")
    finally:
        transport.close()

    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = "".join(c if c.isalnum() else "_" for c in args.label)[:40]
    out = CAPTURES_DIR / f"{stamp}_{safe}.json"
    out.write_text(json.dumps(
        {"label": args.label, "device": str(info), "packets": captured},
        indent=2, ensure_ascii=False,
    ), encoding="utf-8")
    print(f"[+] {len(captured)} packets saved in {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
