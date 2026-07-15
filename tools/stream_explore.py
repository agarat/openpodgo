#!/usr/bin/env python3
"""POD Go preset-stream explorer (reverse-engineering).

Reassembles the chunks by ABSOLUTE OFFSET (not by concatenation) and scans
preset entries {index: {109: name}} without relying on the array header.
Lets you sweep the base offset and the number of chunks.

    python tools/stream_explore.py --setlist 1 --base 0x0f00 --chunks 32 --raw out.bin
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import msgpack

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpodgo import packets  # noqa: E402
from openpodgo.session import Session  # noqa: E402
from openpodgo.usb_transport import TransportError, UsbTransport  # noqa: E402

HDR = packets.RESPONSE_HEADER_LEN
NAME_KEY = b"\xcd\x00\x6d"  # uint16 109 (name key in the inner map)


def scan_entries(raw: bytes) -> dict[int, str]:
    """Scan (index -> name) by finding the name key 109 and reading the
    MessagePack string that follows it; the index comes from the preceding
    `81 cd HI LO 8N`."""
    out: dict[int, str] = {}
    i = 0
    while True:
        j = raw.find(NAME_KEY, i)
        if j < 0:
            break
        i = j + 3
        # name: a MessagePack object right after the key
        try:
            unp = msgpack.Unpacker(raw=False, strict_map_key=False)
            unp.feed(raw[j + 3 : j + 3 + 80])
            name = unp.unpack()
        except Exception:
            continue
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        if not isinstance(name, str):
            continue
        name = name.rstrip("\x00").strip()
        # index: pattern `81 cd HI LO 8N cd 00 6d`
        idx = None
        if j >= 5 and raw[j - 5] == 0x81 and raw[j - 4] == 0xCD:
            idx = (raw[j - 3] << 8) | raw[j - 2]
        if idx is None:
            idx = -len(out) - 1  # negative placeholder so the datum isn't lost
        out.setdefault(idx, name)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--setlist", type=int, default=0, help="0=Factory, 1=User")
    ap.add_argument("--base", default="0x1138", help="start offset (hex or dec)")
    ap.add_argument("--chunks", type=int, default=32)
    ap.add_argument("--step", default="0x100", help="offset increment per chunk")
    ap.add_argument("--raw", help="save the reassembled buffer")
    args = ap.parse_args()

    base = int(args.base, 0)
    step = int(args.step, 0)

    t = UsbTransport()
    try:
        print(f"[+] {t.open()}")
    except TransportError as exc:
        print(f"[!] {exc}")
        return 1

    try:
        Session(t).handshake()
        print("[+] handshake OK")

        setlists_resp = t.request(packets.OPEN_PRESETS)
        print(f"[*] OPEN_PRESETS resp {len(setlists_resp)}B")
        t.request(packets.build_open_stream(args.setlist))

        # Each payload carries ~`step` bytes of a fresh window and then
        # repeats; take only the first `step` bytes and concatenate in order.
        buf = bytearray()
        seq = packets.CHUNK_FIRST_SEQ
        offset = base
        for _ in range(args.chunks):
            resp = t.request(packets.build_chunk_request(seq, offset))
            payload = resp[HDR:]
            buf.extend(payload[:step])
            offset += step
            seq = packets.next_seq(seq)

        raw = bytes(buf)
        if args.raw:
            Path(args.raw).write_bytes(raw)
            print(f"[+] reassembled buffer ({len(raw)}B) -> {args.raw}")

        marker = raw.find(packets.PRESET_ARRAY_MARKER)
        print(f"[*] DC 00 80 marker at: {marker}")

        entries = scan_entries(raw)
        named = {k: v for k, v in entries.items() if k >= 0}
        print(f"[+] {len(named)} presets with index; range "
              f"{min(named) if named else '-'}..{max(named) if named else '-'}")
        for idx in sorted(named):
            print(f"    {idx:3d}: {named[idx]!r}")
    except Exception as exc:  # noqa: BLE001
        print(f"[!] {exc!r}")
        import traceback
        traceback.print_exc()
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
