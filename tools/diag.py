#!/usr/bin/env python3
"""RE Diagnosis: dumps in hex each response of the POD Go.

Performs the handshake showing responses, then sends OPEN_PRESETS and
OPEN_STREAM showing what the pedal returns, and tests a few chunk requests.
Useful for adjusting the preset listing protocol for the POD Go.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpodgo import packets  # noqa: E402
from openpodgo.usb_transport import TransportError, UsbTransport  # noqa: E402


def show(label: str, data: bytes) -> None:
    print(f"  <- {label}: {len(data)} bytes")
    if data:
        print(f"     {data.hex(' ')}")


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    t = UsbTransport()
    try:
        info = t.open()
    except TransportError as exc:
        print(f"[!] {exc}")
        return 1
    print(f"[+] {info}")

    try:
        n = t.drain()
        print(f"[*] initial drain: {n} packets")

        names = ["HANDSHAKE", "SESSION_OPEN_1", "SESSION_CHUNK_1",
                 "SESSION_OPEN_2", "SESSION_CHUNK_2"]
        for name, pkt in zip(names, packets.HANDSHAKE_SEQUENCE):
            print(f"[>] {name} ({len(pkt)} B)")
            show(name + " resp", t.request(pkt))

        print("[>] OPEN_PRESETS")
        show("OPEN_PRESETS resp", t.request(packets.OPEN_PRESETS))

        print("[>] OPEN_STREAM")
        show("OPEN_STREAM resp", t.request(packets.OPEN_STREAM))

        # Test various chunk-requests with the HX offset to see response.
        seq = packets.CHUNK_FIRST_SEQ
        offset = packets.CHUNK_FIRST_OFFSET
        for i in range(4):
            req = packets.build_chunk_request(seq, offset)
            print(f"[>] CHUNK seq={seq:#04x} offset={offset:#06x}")
            show("CHUNK resp", t.request(req))
            offset += packets.CHUNK_OFFSET_STEP
            seq = packets.next_seq(seq)
    except Exception as exc:  # noqa: BLE001
        print(f"[!] {exc!r}")
        logging.exception("detail")
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
