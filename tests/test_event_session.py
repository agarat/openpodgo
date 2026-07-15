"""Tests for the event channel (Spec 04 live sync): builders + EventSession.poll.

The event channel is polled: the host sends a keepalive cmd=0x10 and the
device responds with cmd=0x10 (nothing) or cmd=0x04 (an event). These tests
use a transport with a fake device (IN packet queue) to verify the polling
state machine without hardware.
"""

from __future__ import annotations

from openpodgo import packets
from openpodgo.session import EventSession
from tests.test_usb_transport import _make_transport


def _event_data_frame(body: bytes, cursor: int = 0x1009) -> bytes:
    """Data frame cmd=0x04 from the event channel (src=0x03F0 → dst=0x1002)."""
    pkt = bytearray(16)
    pkt[0] = (16 + len(body)) & 0xFF
    pkt[3] = 0x18
    pkt[4:6] = (0x03F0).to_bytes(2, "little")  # src device
    pkt[6:8] = (0x1002).to_bytes(2, "little")  # dst host
    pkt[11] = 0x04
    pkt[12:16] = cursor.to_bytes(4, "little")
    pkt += bytes((0x00, 0x00, 0x04, 0x00))     # subheader del canal de eventos
    pkt += len(body).to_bytes(2, "little") + b"\x00\x00"
    pkt += body
    return bytes(pkt)


# Keepalive cmd=0x10 returned by the device when there are no events.
EVENT_KEEPALIVE = bytes.fromhex("08000018f00302100004001009020000")


def test_build_event_poll_structure():
    pkt = packets.build_event_poll(seq=0x04, cursor=0x1009)
    assert pkt[4:6] == (0x1002).to_bytes(2, "little")  # src host
    assert pkt[6:8] == (0x03F0).to_bytes(2, "little")  # dst device
    assert pkt[9] == 0x04          # seq
    assert pkt[11] == 0x10         # cmd keepalive
    assert int.from_bytes(pkt[12:16], "little") == 0x1009


def test_build_event_ack_is_cmd_08():
    assert packets.build_event_ack(seq=0x05, cursor=0x1015)[11] == 0x08


def test_event_cursor_advance():
    assert packets.event_cursor_advance(EVENT_KEEPALIVE) == 0       # <=16 B
    frame = _event_data_frame(b"\xaa\xbb\xcc\xdd")                  # body_len=4
    assert packets.event_cursor_advance(frame) == 12               # 8 + 4


def _open_session(incoming):
    t, dev = _make_transport(incoming)
    s = EventSession(t)
    s._open = True  # skip the handshake (we only test polling)
    return s, dev


def test_poll_keepalive_returns_empty_no_ack():
    s, dev = _open_session([EVENT_KEEPALIVE])
    assert s.poll() == []
    # Only the poll was written, no ack (there was no data).
    assert len(dev.written) == 1
    assert dev.written[0][11] == 0x10
    assert s.cursor == packets.EVENT_REST_CURSOR  # not advanced


def test_poll_data_frame_returns_data_acks_and_advances_cursor():
    frame = _event_data_frame(b"\x01\x02\x03\x04")  # body_len=4 → avance 12
    # After the data frame, the device responds with keepalive (end of burst).
    s, dev = _open_session([frame, EVENT_KEEPALIVE])
    out = s.poll()
    assert out == [frame]
    # Wrote poll (0x10) and then ack (0x08).
    assert [p[11] for p in dev.written] == [0x10, 0x08]
    assert s.cursor == packets.EVENT_REST_CURSOR + 12
    # The ack was sent at the advanced cursor.
    assert int.from_bytes(dev.written[1][12:16], "little") == s.cursor


def test_poll_drains_burst_of_events():
    # Two queued events (fast turn) + final keepalive: both are drained.
    f1 = _event_data_frame(b"\xaa\xaa\xaa\xaa")
    f2 = _event_data_frame(b"\xbb\xbb\xbb\xbb")
    s, dev = _open_session([f1, f2, EVENT_KEEPALIVE])
    out = s.poll()
    assert out == [f1, f2]
    # poll + ack(f1) + ack(f2) = 3 writes.
    assert [p[11] for p in dev.written] == [0x10, 0x08, 0x08]
    assert s.cursor == packets.EVENT_REST_CURSOR + 24  # 12 per frame


def test_poll_ignores_other_channel():
    # A frame from another channel (write keepalive) is not an event.
    other = bytes.fromhex("08000018ed038010000600101a020000")
    s, dev = _open_session([other])
    assert s.poll() == []
    assert s.cursor == packets.EVENT_REST_CURSOR


def test_poll_closed_session_returns_empty():
    t, _ = _make_transport([EVENT_KEEPALIVE])
    s = EventSession(t)  # _open = False
    assert s.poll() == []
