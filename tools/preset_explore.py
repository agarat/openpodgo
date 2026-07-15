#!/usr/bin/env python3
"""Probe POD Go vendor resources (RE of the preset dump, spec 02).

Sends a variant of OPEN_STREAM (parameterized resource/k100/k101), shows the
response and continues with chunk-requests until the stream is exhausted. Lets
you sweep resource ids. Each probe starts with a fresh handshake.

Examples:
    python tools/preset_explore.py                       # same as the current OPEN_STREAM
    python tools/preset_explore.py --k101 '{"107": 0, "101": 0}'
    python tools/preset_explore.py --resource 1003 --save captures/spec02_r1003.bin
    python tools/preset_explore.py --sweep-resource 1003:1016
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpodgo import packets  # noqa: E402
from openpodgo.preset import scan_preset_entries  # noqa: E402
from openpodgo.session import Session  # noqa: E402
from openpodgo.usb_transport import TransportError, UsbTransport  # noqa: E402

HEX_PREVIEW = 96


def intkeys(val):
    """Recursively convert JSON map keys (strings) to int."""
    if isinstance(val, dict):
        return {int(k): intkeys(v) for k, v in val.items()}
    return val


def parse_k101(arg: str | None):
    """--k101 accepts JSON ('null', '2', '{"107": 0, "101": 2}'); keys to int."""
    if arg is None:
        return {107: 0, 101: 2}
    return intkeys(json.loads(arg))


def describe(label: str, data: bytes) -> None:
    kind = "plain ack" if len(data) <= packets.RESPONSE_HEADER_LEN else "WITH DATA"
    print(f"  <- {label}: {len(data)} B ({kind})")
    if data:
        print(f"     {data[:HEX_PREVIEW].hex(' ')}{' …' if len(data) > HEX_PREVIEW else ''}")


def probe(t: UsbTransport, resource: int, k100: int, k101, chunks: int,
          open04: dict | None = None) -> bytes:
    """A full probe: handshake, open 0x04, 0x0C variant, chunk loop.

    `open04` replaces the OPEN_PRESETS payload (cmd 0x04); None = template.
    Returns the reassembled buffer (response window + payloads).
    """
    Session(t).handshake()
    if open04 is None:
        t.request(packets.OPEN_PRESETS)
    else:
        pkt04 = packets.build_vendor_open(packets.OPEN_PRESETS, open04, seq=0x06)
        print(f"[>] open 0x04 variant: payload={open04!r}")
        describe("open 0x04 resp", t.request(pkt04))
    payload = {102: resource, 100: k100, 101: k101}
    pkt = packets.build_vendor_open(packets.OPEN_STREAM, payload, seq=0x07)
    print(f"[>] open variant: payload={payload!r}")
    resp = t.request(pkt)
    describe("open resp", resp)

    buf = bytearray(resp[packets.FIRST_DATA_HEADER_LEN:])
    seq = packets.CHUNK_FIRST_SEQ
    offset = packets.CHUNK_FIRST_OFFSET
    for i in range(chunks):
        r = t.request(packets.build_chunk_request(seq, offset))
        payload_bytes = r[packets.RESPONSE_HEADER_LEN:]
        if i < 3 or payload_bytes:
            describe(f"chunk {i} (seq={seq:#04x})", r)
        if not payload_bytes:
            print(f"  [end of stream at chunk {i}]")
            break
        buf.extend(payload_bytes[: packets.CHUNK_WINDOW])
        offset += packets.CHUNK_OFFSET_STEP
        seq = packets.next_seq(seq)
    return bytes(buf)


def summarize(buf: bytes) -> None:
    print(f"[*] total buffer: {len(buf)} B")
    marker = buf.find(packets.PRESET_ARRAY_MARKER)
    print(f"[*] DC 00 80 marker (list of 128): {'at ' + str(marker) if marker >= 0 else 'absent'}")
    entries = scan_preset_entries(buf)
    print(f"[*] name-list-style entries: {len(entries)}")
    if entries[:3]:
        print(f"    first: {entries[:3]!r}")
    if len(buf) > 0 and marker < 0 and len(entries) < 5:
        print("[!] does NOT look like the name list -> candidate for another resource. Save and label.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--resource", type=int, default=1002, help="value of key 102")
    ap.add_argument("--k100", type=int, default=1, help="value of key 100")
    ap.add_argument("--k101", help="value of key 101 in JSON (default: {'107':0,'101':2})")
    ap.add_argument("--chunks", type=int, default=packets.MAX_CHUNKS)
    ap.add_argument("--open", dest="open04", metavar="JSON",
                    help="open 0x04 payload in JSON, e.g. "
                         "'{\"102\": 1001, \"100\": 1, \"101\": null}' "
                         "(default: OPEN_PRESETS template)")
    ap.add_argument("--save", help="save the reassembled buffer to this file")
    ap.add_argument("--sweep-resource", metavar="A:B",
                    help="sweep key 102 over the range [A, B] (fresh handshake per id)")
    args = ap.parse_args()
    k101 = parse_k101(args.k101)
    open04 = intkeys(json.loads(args.open04)) if args.open04 else None

    t = UsbTransport()
    try:
        print(f"[+] {t.open()}")
    except TransportError as exc:
        print(f"[!] {exc}")
        return 1
    try:
        if args.sweep_resource:
            lo, hi = (int(x, 0) for x in args.sweep_resource.split(":"))
            for rid in range(lo, hi + 1):
                print(f"\n===== resource {rid} =====")
                buf = probe(t, rid, args.k100, k101, chunks=4, open04=open04)
                summarize(buf)
        else:
            buf = probe(t, args.resource, args.k100, k101, args.chunks,
                        open04=open04)
            summarize(buf)
            if args.save:
                Path(args.save).write_bytes(buf)
                print(f"[+] saved -> {args.save}")
    except Exception as exc:  # noqa: BLE001
        print(f"[!] {exc!r}")
        import traceback
        traceback.print_exc()
    finally:
        t.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
