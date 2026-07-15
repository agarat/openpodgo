import pytest

from openpodgo import packets


def test_handshake_templates_have_documented_lengths():
    assert len(packets.HANDSHAKE) == 20
    assert len(packets.SESSION_OPEN_1) == 28
    assert len(packets.SESSION_CHUNK_1) == 16
    assert len(packets.SESSION_OPEN_2) == 36
    assert len(packets.SESSION_CHUNK_2) == 16


def test_handshake_magic_bytes():
    # Only HANDSHAKE uses magic 0x28; the rest use the standard 0x18.
    assert packets.HANDSHAKE[3] == 0x28
    for pkt in packets.HANDSHAKE_SEQUENCE[1:]:
        assert pkt[3] == 0x18


def test_preset_packets_lengths():
    assert len(packets.OPEN_PRESETS) == 36
    assert len(packets.OPEN_STREAM) == 40


def test_build_chunk_request_layout():
    req = packets.build_chunk_request(0x08, 0x00001138)
    assert len(req) == 16
    assert req[:12] == bytes((0x08, 0x00, 0x00, 0x18, 0x01, 0x10, 0xEF, 0x03,
                              0x00, 0x08, 0x00, 0x08))
    # offset 0x1138 little-endian in bytes 12-15.
    assert req[12:] == (0x00001138).to_bytes(4, "little")


def test_build_chunk_request_offset_le():
    req = packets.build_chunk_request(0x09, 0x00001238)
    assert req[9] == 0x09
    assert int.from_bytes(req[12:], "little") == 0x00001238


def test_next_seq_wraps():
    assert packets.next_seq(0x08) == 0x09
    assert packets.next_seq(0xFF) == 0x00


def test_build_vendor_open_reproduce_open_presets():
    pkt = packets.build_vendor_open(
        packets.OPEN_PRESETS, {102: 1001, 100: 0, 101: None}, seq=0x06
    )
    assert pkt == packets.OPEN_PRESETS


def test_build_vendor_open_reproduce_open_stream():
    pkt = packets.build_vendor_open(
        packets.OPEN_STREAM, {102: 1002, 100: 1, 101: {107: 0, 101: 2}}, seq=0x07
    )
    assert pkt == packets.OPEN_STREAM


def test_build_vendor_open_reproduce_session_open_2():
    pkt = packets.build_vendor_open(
        packets.SESSION_OPEN_2, {102: 1000, 100: 254, 101: {}}, seq=0x04
    )
    assert pkt == packets.SESSION_OPEN_2


def test_build_vendor_open_large_payload_rejected():
    with pytest.raises(ValueError):
        packets.build_vendor_open(
            packets.OPEN_STREAM, {102: 1002, 101: b"x" * 300}, seq=0x07
        )


def test_identify_command_recognizes_templates_ignoring_seq():
    assert packets.identify_command(packets.HANDSHAKE) == "HANDSHAKE"
    with_other_seq = bytearray(packets.OPEN_PRESETS)
    with_other_seq[9] = 0x42
    assert packets.identify_command(bytes(with_other_seq)) == "OPEN_PRESETS"
    assert packets.identify_command(packets.build_open_stream(1)) == "OPEN_STREAM"


def test_identify_command_chunk_and_unknown():
    chunk = packets.build_chunk_request(seq=0x08, offset=0x1100)
    assert packets.identify_command(chunk) == "CHUNK_REQUEST(offset=0x1100)"
    weird = bytearray(packets.OPEN_PRESETS)
    weird[11] = 0x55  # nonexistent cmd
    assert "cmd=0x55" in packets.identify_command(bytes(weird))


def test_decode_open_body_roundtrip():
    payload = {102: 1001, 100: 1, 101: {107: 0, 101: 1}}
    pkt = packets.build_vendor_open(packets.OPEN_PRESETS, payload, seq=0x06)
    assert packets.decode_open_body(pkt) == payload


def test_decode_open_body_no_subheader():
    assert packets.decode_open_body(packets.HANDSHAKE) is None
    assert packets.decode_open_body(b"\x00" * 8) is None


def test_build_write_param_match_win_knob():
    pkt = packets.build_vendor_write(
        {102: 1010, 100: 30, 101: {98: 3, 29: True, 26: 0, 28: 0, 119: 0.47}},
        seq=0x64, cmd=0x04,
    )
    expected = bytes.fromhex(
        "270000188010ed030064000 43f200000010006001700000 0"
        "8366cd03f2641e658562031dc31a001c0077ca3ef0a3d700"
        .replace(" ", "")
    )
    assert pkt == expected


def test_build_write_uses_different_subheader():
    pkt = packets.build_vendor_write({102: 1000, 100: 76, 101: {}}, seq=0x04)
    assert pkt[16:20] == bytes((0x01, 0x00, 0x06, 0x00))


def test_build_change_preset_match_win_preset_change():
    # Capture shows read channel (OPEN_PRESETS template), cmd=1, slot key=101
    pkt = packets.build_vendor_open(
        packets.OPEN_PRESETS,
        {102: 1014, 100: 1, 101: {107: 1, 101: 7}},
        seq=0xab,
    )
    body = packets.decode_open_body(pkt)
    assert body == {102: 1014, 100: 1, 101: {107: 1, 101: 7}}
    assert pkt[4] == 0x01 and pkt[5] == 0x10  # src=0x1001


def test_build_set_snapshot_match_win_snapshot():
    pkt = packets.build_vendor_write(
        {102: 1018, 100: 88, 101: {92: 2}},
        seq=0xe6, cmd=0x04,
    )
    assert packets.decode_open_body(pkt) == {102: 1018, 100: 88, 101: {92: 2}}


def test_build_save_preset_match_win_save():
    pkt = packets.build_vendor_write(
        {102: 1013, 100: 71, 101: {107: 1, 108: 9, 109: "BassPreset\x00"}},
        seq=0x88, cmd=0x04,
    )
    assert packets.decode_open_body(pkt) == {102: 1013, 100: 71, 101: {107: 1, 108: 9, 109: "BassPreset\x00"}}


def test_build_write_rejects_invalid_seq():
    with pytest.raises(ValueError):
        packets.build_vendor_write({}, seq=256)


def test_build_vendor_write_cursor_param():
    """The write stream cursor is parameterizable (LE u32 at 12:16)."""
    pkt = packets.build_vendor_write(
        {102: 1, 100: 30, 101: {}}, seq=0x05, cmd=0x04, cursor=0x105B
    )
    assert pkt[12:16] == (0x105B).to_bytes(4, "little")


def test_build_vendor_write_cursor_default_is_steady_state():
    """Without explicit cursor keeps 0x203F (compat with warm captures)."""
    pkt = packets.build_vendor_write({102: 1, 100: 30, 101: {}}, seq=0x05)
    assert pkt[12:16] == (0x203F).to_bytes(4, "little")


def test_build_write_chunk_layout():
    """Chunk-read on the write channel: 16 B, cmd=0x08, src=0x1080→0x03ED."""
    pkt = packets.build_write_chunk(seq=0x09, cursor=0x105B)
    assert len(pkt) == 16
    assert pkt[4:8] == bytes((0x80, 0x10, 0xED, 0x03))  # src=0x1080 dst=0x03ED
    assert pkt[9] == 0x09 and pkt[11] == 0x08
    assert pkt[12:16] == (0x105B).to_bytes(4, "little")


def test_write_cursor_advance_framed_response():
    """Framed open response (subheader 00 00 06 00): advances 8 + body_len."""
    resp = bytearray(16 + 8 + 74)
    resp[16:20] = bytes((0x00, 0x00, 0x06, 0x00))
    resp[20:22] = (74).to_bytes(2, "little")
    assert packets.write_cursor_advance(bytes(resp)) == 8 + 74


def test_write_cursor_advance_raw_window():
    """Raw data window (no subheader): advances len - 16."""
    resp = bytes(16 + 256)  # starts with zeros (not a known subheader)
    # force 16:20 to not be a framed subheader
    resp = bytes([0]*16 + [0x83, 0x66] + [0]*254)
    assert packets.write_cursor_advance(resp) == len(resp) - 16


def test_write_cursor_advance_bare_ack():
    """Ack of 16 B or less: no advance."""
    assert packets.write_cursor_advance(b"\x00" * 16) == 0
    assert packets.write_cursor_advance(b"ok") == 0


# --- fragmented write (op 21, move block) ---

import msgpack  # noqa: E402
from pathlib import Path  # noqa: E402

CAPS = Path(__file__).parent.parent / "captures"


def _reassemble(frames):
    """Inverse of build_vendor_write_chunked: concatenates frame data."""
    body = b""
    for i, f in enumerate(frames):
        if i == 0:
            assert f[16:20] == packets.WRITE_SUBHEADER
            total = int.from_bytes(f[20:24], "little")
            body += f[24:]
        else:
            body += f[16:]
    return body[:total]


def test_chunked_round_trip():
    payload = {102: 1234, 100: 21, 101: {110: bytes(range(256)) * 10}}
    frames = packets.build_vendor_write_chunked(payload, seq=0x20, cursor=0x30B3)
    assert len(frames) > 1  # a large payload is fragmented
    rebuilt = _reassemble(frames)
    assert rebuilt == msgpack.packb(payload, use_single_float=True, use_bin_type=False)


def test_chunked_frame_layout():
    payload = {102: 1, 100: 21, 101: {110: b"x" * 2000}}
    frames = packets.build_vendor_write_chunked(payload, seq=0x20, cursor=0x30B3)
    for i, f in enumerate(frames):
        assert len(f) <= packets.WRITE_FRAME_MAX
        assert len(f) % 4 == 0  # aligned to 4 B
        assert f[3] == 0x18
        assert f[4:8] == bytes((0x80, 0x10, 0xED, 0x03))  # WRITE_SRC→WRITE_DST
        assert f[9] == (0x20 + i) & 0xFF  # incremental seq
        assert f[11] == 0x04
        assert int.from_bytes(f[12:16], "little") == 0x30B3  # shared cursor
        assert int.from_bytes(f[0:2], "little") == len(f) - 8  # lenf field


def _capture_op21_payload():
    """Reassemble the op 21 payload written in change-pedal-order-from-app.pcapng."""
    from openpodgo.usbpcap import parse_bulk_transfers
    ts = parse_bulk_transfers(str(CAPS / "win-captures" / "change-pedal-order-from-app.pcapng"))
    frags = []
    for t in ts:
        p = t.payload
        if t.is_in or p[4:8] != bytes((0x80, 0x10, 0xED, 0x03)) or p[11] != 0x04:
            continue
        frags.append((p[9], p))
    frags.sort()
    body, total = b"", None
    for n, (_seq, p) in enumerate(frags):
        if n == 0:
            total = int.from_bytes(p[20:24], "little")
            body += p[24:]
        else:
            body += p[16:]
    return body[:total]


def test_chunked_reproduces_capture_payload():
    """Oracle: our fragmenter rebuilds the same payload as the real one."""
    cap = CAPS / "win-captures" / "change-pedal-order-from-app.pcapng"
    if not cap.exists():
        pytest.skip("USB capture (.pcapng) not present")
    cap_body = _capture_op21_payload()
    obj = msgpack.unpackb(cap_body, raw=True, strict_map_key=False)
    assert obj[100] == 21  # chain dump op
    assert 110 in obj[101]  # l6-helix blob
    # re-fragmenting the same payload and reassembling must yield the same bytes
    frames = packets.build_vendor_write_chunked(obj, seq=0x20, cursor=0x30B3)
    assert _reassemble(frames) == cap_body
