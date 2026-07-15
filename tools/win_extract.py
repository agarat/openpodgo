#!/usr/bin/env python3
"""Dump and classify the vendor traffic of a POD Go Edit USBPcap capture.

Each line: index, relative t, direction, length, seq, cmd, label (known
template or UNKNOWN) and the MessagePack body if it could be decoded.

Usage:
    python tools/win_extract.py captures/win-captures/win_knob.pcapng
    python tools/win_extract.py <pcapng> --dir out --hex-full
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import msgpack  # noqa: E402

from openpodgo import packets  # noqa: E402
from openpodgo.usbpcap import parse_bulk_transfers  # noqa: E402

#: Line 6 header signatures after the length byte (bytes 3-7).
OUT_SIG = bytes((0x18, 0x01, 0x10, 0xEF, 0x03))
IN_SIG = bytes((0x18, 0xEF, 0x03, 0x01, 0x10))


def is_l6(payload: bytes) -> bool:
    return len(payload) >= 16 and (
        payload[3:8] in (OUT_SIG, IN_SIG) or payload[3] == 0x28
    )


def decode_body(payload: bytes):
    """Best effort: open OUT body, or msgpack after a 16/24 B header (IN)."""
    decoded = packets.decode_open_body(payload)
    if decoded is not None:
        return decoded
    for offset in (packets.FIRST_DATA_HEADER_LEN, packets.RESPONSE_HEADER_LEN):
        try:
            unpacker = msgpack.Unpacker(strict_map_key=False)
            unpacker.feed(payload[offset:])
            return unpacker.unpack()
        except Exception:
            continue
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("pcapng", type=Path)
    ap.add_argument("--dir", choices=("out", "in", "both"), default="both")
    ap.add_argument("--all", action="store_true",
                    help="include bulk that does not look like Line 6 traffic")
    ap.add_argument("--hex-full", action="store_true",
                    help="full hex instead of the first 48 bytes")
    args = ap.parse_args()

    transfers = parse_bulk_transfers(args.pcapng)
    t0 = transfers[0].ts if transfers else 0
    shown = 0
    for i, t in enumerate(transfers):
        if args.dir == "out" and t.is_in or args.dir == "in" and not t.is_in:
            continue
        if not args.all and not is_l6(t.payload):
            continue
        p = t.payload
        direction = "IN " if t.is_in else "OUT"
        seq = f"{p[9]:#04x}" if len(p) > 9 else "  — "
        cmd = f"{p[11]:#04x}" if len(p) > 11 else "  — "
        label = packets.identify_command(p) if not t.is_in else "response"
        line = (f"[{i:3d}] +{(t.ts - t0) / 1000:9.1f}ms {direction} "
                f"{len(p):4d}B seq={seq} cmd={cmd}  {label}")
        body = decode_body(p)
        if body is not None:
            line += f"  {body!r}"
        print(line)
        cut = None if args.hex_full else 48
        print(f"      {p[:cut].hex(' ')}{'…' if cut and len(p) > cut else ''}")
        shown += 1
    print(f"-- {shown} transfers shown out of {len(transfers)} bulk")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
