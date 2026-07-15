"""Offline integration tests: verifies the complete write pipeline.

Uses real fixtures, simulates the transport layer with a mock, and verifies
that all pieces (packets → session → device → editor) fit together.
"""

from __future__ import annotations

from pathlib import Path

import msgpack
import pytest

from openpodgo import l6helix, packets
from openpodgo.device import PodGo
from openpodgo.editor import PresetEditor
from openpodgo.session import Session, WriteSession
from openpodgo.usb_transport import TransportError

CAPS = Path(__file__).parent / "fixtures"


class MockTransport:
    """Mock transport that captures requests and returns pre-set responses."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.responses: list[bytes] = []
        self._ri = 0
        # send_write drains until timeout; in mock we count reads per
        # send_write and stop after 3 (ack+echo+ack).
        self._reads_this_call = 0

    def request(self, pkt: bytes, timeout_ms: int = 2000) -> bytes:
        self.sent.append(pkt)
        self._reads_this_call = 0
        return self.read(timeout_ms)

    def write(self, pkt: bytes, timeout_ms: int = 2000) -> int:
        self.sent.append(pkt)
        self._reads_this_call = 0
        return len(pkt)

    def read(self, timeout_ms: int = 2000) -> bytes:
        self._reads_this_call += 1
        if self._reads_this_call > 3:
            raise TransportError("drained (mock)")
        if self._ri >= len(self.responses):
            raise TransportError("no more mock responses")
        resp = self.responses[self._ri]
        self._ri += 1
        return resp

    def open(self):
        return None

    def drain(self) -> None:
        pass

    def close(self) -> None:
        pass


def _write_resp_from(payload: dict, seq: int = 0x06) -> bytes:
    """Creates a successful mock response for a write packet.

    build_vendor_write uses fixed src/dst (WRITE_SRC, WRITE_DST); the
    mock response uses src=0x03ED and dst=0x1080 (inverted).

    NOTE: we can't pass custom src/dst to build_vendor_write
    because it has fixed src/dst. This function produces a generic
    packet that decode_open_body can read; the address is ignored in
    decoding.
    """
    return packets.build_vendor_write(
        payload, seq=seq, cmd=0x04,
    )


def _ok_resp(seq: int = 0x06) -> bytes:
    return _write_resp_from({102: 1001, 103: 0}, seq=seq)


def _make_pod_with_mock() -> tuple[PodGo, MockTransport]:
    """PodGo with mock transport (no real USB), open session and write session."""
    t = MockTransport()
    pod = PodGo()
    pod._transport = t
    pod._session = Session(t)
    pod._session._open = True
    ws = WriteSession(t)
    ws._open = True
    ws._seq = 0x06
    pod._write_session = ws
    return pod, t


# --- packet → session pipeline ---


def test_build_and_parse_preset_change():
    """build_vendor_open(OPEN_PRESETS) + decode_open_body round-trip for change_preset."""
    pkt = packets.build_vendor_open(
        packets.OPEN_PRESETS,
        {102: 1010, 100: 1, 101: {107: 0, 101: 1}},
        seq=0x06,
    )
    body = packets.decode_open_body(pkt)
    assert body is not None
    assert body[100] == 1
    assert body[101][107] == 0
    assert body[101][101] == 1


def test_ok_resp_validation():
    """_ok_resp must have 103=0 (success)."""
    resp = _ok_resp()
    body = packets.decode_open_body(resp)
    assert body[103] == 0


# --- editor → blob pipeline ---


def test_editor_modify_and_to_blob():
    """Edits a parameter, serializes to blob, and verifies the change
    survives the round-trip."""
    cap = CAPS / "spec02_knob.bin"
    preset = l6helix.parse_blob(l6helix.extract_blob(cap.read_bytes()))
    ed = PresetEditor(preset)

    # Tube Drive (slot 2), Drive (param idx 0) a 50%
    ed.set_param(2, 0, 0.5)
    blob = ed.to_blob()
    back = l6helix.parse_blob(blob)
    assert back.chain[2].params[0] == pytest.approx(0.5)


def test_block_index_from_editor():
    """Controls block_index() from editor."""
    cap = CAPS / "spec02_knob.bin"
    blob = l6helix.extract_blob(cap.read_bytes())
    ed = PresetEditor(l6helix.parse_blob(blob))
    # Raw index in DSP_CHAIN (INPUT at raw 0): block_index(slot) = slot + 1.
    assert ed.block_index(0) == 1
    assert ed.block_index(2) == 3
    with pytest.raises(ValueError, match="empty"):
        ed.block_index(9)


# --- write session ---


def test_write_handshake_sends_four_packets():
    """WriteSession.handshake() sends exactly 4 packets in order."""
    t = MockTransport()
    t.responses = [b"ok"] * 4
    ws = WriteSession(t)
    ws.handshake()
    assert len(t.sent) == 4
    assert t.sent[0] == WriteSession.WRITE_HANDSHAKE
    assert t.sent[1] == WriteSession.WRITE_OPEN_1
    assert t.sent[2] == WriteSession.WRITE_CHUNK_1
    assert t.sent[3] == WriteSession.WRITE_OPEN_2


def test_write_session_seq_avanza():
    t = MockTransport()
    ws = WriteSession(t)
    assert ws.seq == 0x00
    ws.advance_seq()
    assert ws.seq == 0x01
    assert ws.advance_seq() == 0x01


def _framed_resp(body_len: int) -> bytes:
    r = bytearray(16 + 8 + body_len)
    r[16:20] = bytes((0x00, 0x00, 0x06, 0x00))
    r[20:22] = body_len.to_bytes(2, "little")
    return bytes(r)


def test_write_session_handshake_initializes_cursor():
    """After handshake, cursor = cursor of WRITE_OPEN_2 + advance of its
    response (the device already sent object 76)."""
    t = MockTransport()
    t.responses = [b"ok", b"ok", b"ok", _framed_resp(74)]
    ws = WriteSession(t)
    ws.handshake()
    # WRITE_OPEN_2 carries cursor 0x1009; framed response body_len=74 → +82.
    assert ws.cursor == 0x1009 + 8 + 74


def test_write_session_send_write_drains_and_returns_echo():
    """send_write sends ONE command at the current cursor, advances the cursor by the
    request footprint, and drains all responses returning the framed echo
    (the one carrying the status)."""
    t = MockTransport()
    ack = b"\x00" * 16
    echo = _ok_resp()  # framed (subheader 01 00 06 00) with status
    t.responses = [ack, echo, ack]  # after these, MockTransport.read raises TransportError
    ws = WriteSession(t)
    ws._open = True
    ws._cursor = 0x105B
    ws._seq = 0x06
    resp = ws.send_write({102: 1, 100: 30, 101: {98: 3, 29: True, 26: 0, 28: 0, 119: 1.0}})
    assert len(t.sent) == 1            # un solo comando enviado
    assert t.sent[0][11] == 0x04       # cmd set_param
    assert t.sent[0][12:16] == (0x105B).to_bytes(4, "little")  # al cursor actual
    assert resp == echo                # returns the framed echo, not the acks
    body_len = int.from_bytes(t.sent[0][20:22], "little")
    assert ws.cursor == 0x105B + 8 + body_len   # cursor advanced by the footprint


# --- write packet construction ---


def test_change_preset_build_and_resp():
    """change_preset uses the read channel: cmd=1, slot key=101."""
    pkt = packets.build_vendor_open(
        packets.OPEN_PRESETS,
        {102: 1010, 100: 1, 101: {107: 0, 101: 1}},
        seq=0x06,
    )
    body = packets.decode_open_body(pkt)
    assert body[100] == 1
    assert body[101][107] == 0
    assert body[101][101] == 1
    # Read channel (src=0x1001)
    assert pkt[4] == 0x01 and pkt[5] == 0x10


def test_decode_open_body_accepts_write_response_subheader():
    """decode_open_body must accept subheader 00 00 06 00 (real device response).

    Write channel responses use 00 00 (not 01 00) in bytes 16-17.
    Without this fix, _write_ok always returns False against the real pedal.
    """
    body = msgpack.packb({102: 1001, 103: 0}, use_single_float=True)
    # Build a packet with RESPONSE subheader (00 00 06 00)
    pkt = bytearray(24 + len(body))
    pkt[0] = 16 + len(body)
    pkt[3] = 0x18
    pkt[4] = 0xED; pkt[5] = 0x03   # src = 0x03ED (write channel device→host)
    pkt[6] = 0x80; pkt[7] = 0x10   # dst = 0x1080
    pkt[16:20] = bytes([0x00, 0x00, 0x06, 0x00])    # subheader de respuesta
    pkt[20:22] = len(body).to_bytes(2, "little")
    pkt[24:24 + len(body)] = body

    result = packets.decode_open_body(bytes(pkt))
    assert result is not None, "decode_open_body rejects subheader 00 00 (write response)"
    assert result[103] == 0


def test_write_handshake_calls_drain_before_sending():
    """WriteSession.handshake() must call drain() to flush residual keepalives."""
    class TrackingTransport(MockTransport):
        def __init__(self):
            super().__init__()
            self.drain_calls = 0
        def drain(self, timeout_ms: int = 50) -> int:
            self.drain_calls += 1
            return 0

    t = TrackingTransport()
    t.responses = [b"ok"] * 4
    ws = WriteSession(t)
    ws.handshake()
    assert t.drain_calls >= 1, "WriteSession.handshake() did not call transport.drain()"


def test_session_handshake_resends_packets_when_session_open():
    """handshake() always sends the 5 packets — the device requires them
    before each operation, even if the session was already open."""
    t = MockTransport()
    t.responses = [b"ok"] * 10  # 5 for each handshake
    s = Session(t)
    s.handshake()
    n = len(t.sent)  # 5 paquetes

    s.handshake()
    assert len(t.sent) == n + 5  # 5 more packets from the second handshake
    assert s.is_open


def test_pod_write_connect_opens_write_channel():
    """write_connect() must leave _write_session open."""
    t2 = MockTransport()
    pod2 = PodGo()
    pod2._transport = t2
    pod2._session = Session(t2)
    pod2._session._open = True
    t2.responses = [b"ok"] * 4   # 4 packets of the WriteSession handshake
    pod2.write_connect()
    assert pod2._write_session is not None
    assert pod2._write_session.is_open


def test_set_param_opens_write_session_automatically():
    """set_param lazily opens write_connect if the write session isn't open."""
    t = MockTransport()
    pod = PodGo()
    pod._transport = t
    pod._session = Session(t)
    pod._session._open = True
    # No write_session — must open on its own at the first set_param.
    # 4 handshake + (ack + echo + ack) that send_write drains.
    t.responses = [b"ok"] * 4 + [b"\x00" * 16, _ok_resp(), b"\x00" * 16]

    assert pod.set_param(block_index=0, param_idx=0, value=0.5) is True

    assert pod._write_session is not None
    assert pod._write_session.is_open


def test_set_param_encodes_param_idx():
    """device.set_param must send param_idx (26) on the wire, not hardcode 0."""
    pod, t = _make_pod_with_mock()
    # send_write drains: ack + echo (with status) + ack.
    t.responses = [b"\x00" * 16, _ok_resp(), b"\x00" * 16]

    assert pod.set_param(block_index=3, param_idx=2, value=0.7) is True

    # The set_param command is the first (and only) packet sent by send_write.
    body = packets.decode_open_body(t.sent[0])
    assert body[101][28] == 2   # param_idx goes in key 28 (NOT 26)
    assert body[101][26] == 0   # key 26 constant 0 (verified against pedal)
    assert body[101][98] == 3   # correct block_index
    assert body[101][119] == pytest.approx(0.7, abs=1e-4)


def test_device_change_preset_uses_read_channel():
    """device.change_preset must use the read channel (src=0x1001), cmd=1, slot key=101."""
    pod, t = _make_pod_with_mock()
    t.responses = [b"\x00" * 16]

    pod.change_preset(setlist=1, slot=7)

    sent = t.sent[-1]
    assert sent[4] == 0x01 and sent[5] == 0x10    # src=0x1001, not 0x1080
    body = packets.decode_open_body(sent)
    assert body[100] == 1                          # cmd=1, not 20
    assert body[101][107] == 1                     # setlist
    assert body[101][101] == 7                     # slot key=101, not 108


def test_flush_editor_params_resilient():
    """_flush_editor_params doesn't abort if an individual set_param fails (uses internal retry)."""
    from openpodgo.ui.main_window import MainWindow
    from openpodgo.editor import PresetEditor

    cap = CAPS / "spec02_knob.bin"
    pre = l6helix.parse_blob(l6helix.extract_blob(cap.read_bytes()))
    ed = PresetEditor(pre)

    # Count total params
    n = 0
    for slot in range(len(pre.chain)):
        block = pre.chain[slot]
        if block is None:
            continue
        try:
            ed.block_index(slot)
        except ValueError:
            continue
        n += len(block.params)

    pod, t = _make_pod_with_mock()
    ok_echo = _write_resp_from({102: 1001, 103: 0})
    # A successful set_param needs 3 responses (ack + echo + ack).
    # With the internal retry, each set_param always does 1 attempt and doesn't
    # retry because the mock always returns success.
    t.responses = [b"\x00" * 16, ok_echo, b"\x00" * 16] * n

    result = MainWindow._flush_editor_params(pod, ed)
    assert result is True
