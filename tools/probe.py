#!/usr/bin/env python3
"""Probe a connected POD Go: open USB, run the handshake and list presets.

This is the Phase 0/1 validation point: it confirms whether POD Go speaks the
same vendor protocol as the HX Stomp. Usage:

    python tools/probe.py            # open, handshake, list presets
    python tools/probe.py --raw out.bin   # also dump the raw stream
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpodgo import preset  # noqa: E402
from openpodgo.session import Session  # noqa: E402
from openpodgo.usb_transport import TransportError, UsbTransport  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="POD Go protocol probe")
    ap.add_argument("--raw", metavar="FILE", help="dump the raw stream to a file")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    transport = UsbTransport()
    try:
        info = transport.open()
    except TransportError as exc:
        print(f"[!] Could not open the device: {exc}")
        return 1

    print(f"[+] Device: {info}")

    try:
        session = Session(transport)
        print("[*] Running the 5-packet handshake...")
        session.handshake()
        print("[+] Handshake OK — POD Go responds to the HX-family protocol")

        print("[*] Streaming presets...")
        stream = preset.stream_presets(session)
        print(f"[+] Stream: {stream.chunks} chunks, {len(stream.raw)} bytes")

        if args.raw:
            Path(args.raw).write_bytes(stream.raw)
            print(f"[+] Raw stream saved to {args.raw}")

        entries = preset.parse_preset_list(stream.raw)
        print(f"[+] {len(entries)} presets decoded:")
        for e in entries:
            print(f"    {e.index:3d}: {e.name!r}")
    except Exception as exc:  # noqa: BLE001 - RE diagnostics
        print(f"[!] Probe failed: {exc!r}")
        logging.exception("detail")
        return 2
    finally:
        transport.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
