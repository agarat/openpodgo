"""Offline write API tests: verifies packet construction
without needing a pedal."""

import pytest

from openpodgo import packets


def test_change_preset_builds_correct_packet():
    # Read channel: build_vendor_open(OPEN_PRESETS), cmd=1, slot key=101
    pkt = packets.build_vendor_open(
        packets.OPEN_PRESETS,
        {102: 1014, 100: 1, 101: {107: 1, 101: 7}},
        seq=0xab,
    )
    body = packets.decode_open_body(pkt)
    assert body is not None
    assert body[100] == 1
    assert body[101] == {107: 1, 101: 7}
    assert pkt[4] == 0x01 and pkt[5] == 0x10  # src=0x1001


def test_set_snapshot_builds_correct_packet():
    pkt = packets.build_vendor_write(
        {102: 1018, 100: 88, 101: {92: 2}},
        seq=0xe6, cmd=0x04,
    )
    body = packets.decode_open_body(pkt)
    assert body is not None
    assert body[100] == 88
    assert body[101][92] == 2


def test_set_param_builds_correct_packet():
    # param_idx travels in key 28 (verified against pedal); key 26
    # is constant 0. The capture only showed param 0 (both at 0), ambiguous.
    pkt = packets.build_vendor_write(
        {102: 1010, 100: 30, 101: {98: 3, 29: True, 26: 0, 28: 2, 119: 0.47}},
        seq=0x64, cmd=0x04,
    )
    body = packets.decode_open_body(pkt)
    assert body is not None
    assert body[100] == 30
    assert body[101][28] == 2
    assert body[101][119] == pytest.approx(0.47, abs=1e-6)


def test_save_preset_builds_correct_packet():
    pkt = packets.build_vendor_write(
        {102: 1013, 100: 71, 101: {107: 1, 108: 9, 109: "BassPreset\x00"}},
        seq=0x88, cmd=0x04,
    )
    body = packets.decode_open_body(pkt)
    assert body is not None
    assert body[100] == 71
    assert body[101][109] == "BassPreset\x00"


def test_set_model_builds_correct_packet():
    # RE of change-pedal-from-app.pcapng: op 40, payload {98: block_index,
    # 100: model node {23: no_snapshot_bypass, 25: wire_id, 26: -1}}.
    pkt = packets.build_vendor_write(
        {102: 1013, 100: 40, 101: {98: 5, 100: {23: False, 25: 433, 26: -1}}},
        seq=0x70, cmd=0x04,
    )
    body = packets.decode_open_body(pkt)
    assert body is not None
    assert body[100] == 40
    assert body[101][98] == 5
    assert body[101][100] == {23: False, 25: 433, 26: -1}


def test_write_tx_id_increments():
    from openpodgo.device import _write_tx_id
    a = _write_tx_id()
    b = _write_tx_id()
    assert b == a + 1


def test_send_write_chunked_emits_op21(monkeypatch):
    """send_write_chunked fragments an op 21 with the blob in key 110."""
    import msgpack
    from openpodgo.session import WriteSession
    from openpodgo.usb_transport import TransportError

    blob = b"l6-helix\x00" + bytes(range(256)) * 12  # ~3 KB → varios frames
    sent: list[bytes] = []

    class FakeTransport:
        def write(self, pkt):
            sent.append(pkt)

        def read(self, timeout_ms=None):
            raise TransportError("empty")  # no responses to drain

    ws = WriteSession(FakeTransport())
    ws._seq, ws._cursor, ws._open = 0x06, 0x2040, True
    ws.send_write_chunked({102: 1, 100: 21, 101: {110: blob}})

    assert len(sent) > 1  # it fragmented
    body = b""
    for i, f in enumerate(sent):
        body += f[24:] if i == 0 else f[16:]
    total = int.from_bytes(sent[0][20:24], "little")
    obj = msgpack.unpackb(body[:total], raw=True, strict_map_key=False)
    assert obj[100] == 21
    assert obj[101][110] == blob


def _framed_echo(body_dict: dict) -> bytes:
    """Framed response from the write channel with the given body."""
    import msgpack

    body = msgpack.packb(body_dict)
    pkt = bytearray(24)
    pkt[16:20] = bytes((0x00, 0x00, 0x06, 0x00))
    pkt[20:22] = len(body).to_bytes(2, "little")
    return bytes(pkt) + body


def test_write_chain_blob_fresh_handshake(monkeypatch):
    """Each blob dump (op 21) re-handshakes the write channel.

    The write session desyncs after a chunked write (its flow-control/cursor
    model is approximate), so reusing it causes the first attempt to fail and
    triggers reconnect+retry (~1 s lost per write). To succeed on the first
    attempt, write_chain_blob forces a fresh session.
    """
    from openpodgo.device import PodGo

    pod = PodGo()
    connects: list[bool] = []
    writes: list[int] = []

    class FakeWS:
        def send_write_chunked(self, payload, cmd=0x04):
            return _framed_echo({102: 1, 103: 1, 104: None})

        def send_write(self, payload, cmd=0x04):
            writes.append(payload[100])
            return b""

    def fake_write_connect():
        connects.append(True)
        pod._write_session = FakeWS()
        pod._read_since_write = False

    monkeypatch.setattr(pod, "write_connect", fake_write_connect)
    # Write session already open and NOT marked for reconnect: reusable.
    pod._write_session = FakeWS()
    pod._read_since_write = False

    assert pod.write_chain_blob(b"l6-helix\x00data") is True
    assert connects == [True]  # re-handshaked despite having "reusable" session
    # After the dump it sends the "apply/refresh" close (op 23 + op 22) so
    # the pedal refreshes without needing to toggle the footswitch.
    assert writes == [23, 22]


def test_chain_write_ok_accepts_103_one():
    """op 21 applied responds {103: 1} (≠ set_param, which is 103: 0).

    Validated against change-pedal-order-from-app.pcapng ({102:1017,103:1,104:None})
    and live: the reorder applies and the echo carries 103:1. Before, _write_ok
    required 103==0 → false failure → retry → double application (slowness).
    """
    from openpodgo.device import _chain_write_ok, _write_ok

    applied = _framed_echo({102: 1017, 103: 1, 104: None})
    assert _chain_write_ok(applied) is True       # op 21: 103:1 = applied
    assert _write_ok(applied) is False            # old check rejected it
    assert _chain_write_ok(_framed_echo({103: 0})) is True
    assert _chain_write_ok(_framed_echo({103: 7})) is False  # other value = failure
    assert _chain_write_ok(b"\x00" * 16) is False            # raw ack, no status
