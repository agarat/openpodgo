"""Tests for the USBPcap reader: minimal synthetic captures and invalid files."""

import struct
from pathlib import Path

import pytest

from openpodgo import packets
from openpodgo.usbpcap import parse_bulk_transfers


def _block(btype: int, body: bytes) -> bytes:
    """pcapng block: type, total length, 4-byte-aligned body, length."""
    pad = (-len(body)) % 4
    total = 12 + len(body) + pad
    return (
        struct.pack("<II", btype, total)
        + body + b"\x00" * pad
        + struct.pack("<I", total)
    )


def _shb() -> bytes:
    # magic LE, version 1.0, unknown section length (-1)
    return _block(0x0A0D0D0A, struct.pack("<IHHq", 0x1A2B3C4D, 1, 0, -1))


def _idb() -> bytes:
    # linktype 249 (USBPcap), reservado, snaplen 65535
    return _block(0x00000001, struct.pack("<HHI", 249, 0, 0xFFFF))


def _usbpcap_record(endpoint: int, transfer: int, payload: bytes,
                    info: int = 0) -> bytes:
    header = struct.pack(
        "<HQIHBHHBBI",
        27,             # headerLen
        1,              # irpId
        0,              # status
        9,              # function (BULK_OR_INTERRUPT_TRANSFER)
        info, 1, 1,     # info, bus, device
        endpoint, transfer, len(payload),
    )
    return header + payload


def _epb(record: bytes) -> bytes:
    body = struct.pack("<IIIII", 0, 0, 0, len(record), len(record)) + record
    return _block(0x00000006, body)


def _capture(*records: bytes) -> bytes:
    return _shb() + _idb() + b"".join(_epb(r) for r in records)


def test_parse_synthetic_bulk_out(tmp_path):
    f = tmp_path / "c.pcapng"
    f.write_bytes(_capture(_usbpcap_record(0x01, 3, packets.HANDSHAKE)))
    transfers = parse_bulk_transfers(f)
    assert len(transfers) == 1
    t = transfers[0]
    assert t.endpoint == 0x01
    assert not t.is_in
    assert t.payload == packets.HANDSHAKE


def test_distinguishes_in_from_out(tmp_path):
    f = tmp_path / "c.pcapng"
    f.write_bytes(_capture(
        _usbpcap_record(0x01, 3, b"\x01\x02"),
        _usbpcap_record(0x81, 3, b"\x03\x04", info=1),
    ))
    transfers = parse_bulk_transfers(f)
    assert [t.is_in for t in transfers] == [False, True]
    assert transfers[1].endpoint == 0x81


def test_ignores_non_bulk_and_bulk_without_payload(tmp_path):
    f = tmp_path / "c.pcapng"
    f.write_bytes(_capture(
        _usbpcap_record(0x80, 2, b"\x09\x02"),  # control
        _usbpcap_record(0x01, 3, b""),          # bulk without data (empty OUT submit)
        _usbpcap_record(0x01, 3, b"\xaa"),
    ))
    transfers = parse_bulk_transfers(f)
    assert len(transfers) == 1
    assert transfers[0].payload == b"\xaa"


def test_rejects_non_pcapng_file(tmp_path):
    f = tmp_path / "basura.bin"
    f.write_bytes(b"\x00" * 64)
    with pytest.raises(ValueError):
        parse_bulk_transfers(f)


# --- Capturas reales de POD Go Edit (docs/specs/02-windows-checklist.md) ---

WIN_CAPTURES = Path(__file__).resolve().parent.parent / "captures" / "win-captures"

#: Host->device signature of the Line 6 header: magic 0x18 + src 0x1001 + dst 0x03EF.
L6_OUT_SIG = bytes((0x18, 0x01, 0x10, 0xEF, 0x03))


def _vendor_out(path):
    return [
        t.payload
        for t in parse_bulk_transfers(path)
        if not t.is_in and len(t.payload) >= 16 and t.payload[3:8] == L6_OUT_SIG
    ]


@pytest.mark.parametrize("name", [
    "win_connect", "win_knob", "win_save", "win_preset_change", "win_snapshot",
])
def test_real_captures_contain_vendor_out_commands(name):
    pcap = WIN_CAPTURES / f"{name}.pcapng"
    if not pcap.exists():
        pytest.skip("Windows capture not present in this checkout")
    assert len(_vendor_out(pcap)) > 0


def test_connect_contains_official_handshake():
    pcap = WIN_CAPTURES / "win_connect.pcapng"
    if not pcap.exists():
        pytest.skip("Windows capture not present in this checkout")
    transfers = parse_bulk_transfers(pcap)
    outs = [t.payload for t in transfers if not t.is_in and len(t.payload) >= 4]
    # The HANDSHAKE packet is the only one with magic 0x28.
    assert any(p[3] == 0x28 for p in outs)
