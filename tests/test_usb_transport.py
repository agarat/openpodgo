"""Tests for the channel-filtered request→response pattern of UsbTransport.

Against the real pedal, after opening the write channel, the device pushes
unsolicited packets (keepalives cmd=0x10 from src=0x03ED→0x1080) over the
same EP IN. Without channel filtering, request() returns the first packet that
arrives and misaligns all subsequent operations (seen live: object
23 read the response to OPEN_PRESETS and crashed with 'list' has no 'get').

The legitimate response always mirrors the request's src/dst:
    IN[4:8] == OUT[6:8] + OUT[4:6]
"""

from __future__ import annotations

import usb.core

from openpodgo.usb_transport import DeviceInfo, TransportError, UsbTransport

# Read channel request: src=0x1001 (01 10), dst=0x03EF (ef 03).
READ_REQ = bytes.fromhex("080000180110ef030003000809100000")
# Its mirrored response: src=0x03EF (ef 03), dst=0x1001 (01 10).
READ_RESP = bytes.fromhex("08000018ef0301100003000809020000")
# Unsolicited keepalive from the write channel (device→host), captured live.
WRITE_KEEPALIVE = bytes.fromhex("08000018ed038010000600101a020000")


class FakeDev:
    """Fake usb.core.Device: queue of IN packets, records writes."""

    def __init__(self, incoming: list[bytes]) -> None:
        self.incoming = list(incoming)
        self.written: list[bytes] = []

    def write(self, ep, data, timeout=None) -> int:
        self.written.append(bytes(data))
        return len(data)

    def read(self, ep, size, timeout=None):
        if not self.incoming:
            raise usb.core.USBError("Operation timed out")
        return bytearray(self.incoming.pop(0))


def _make_transport(incoming: list[bytes]) -> tuple[UsbTransport, FakeDev]:
    t = UsbTransport()
    dev = FakeDev(incoming)
    t._dev = dev
    t._info = DeviceInfo(
        vendor_id=0x0E41, product_id=0x4247, product_name="POD Go",
        interface=0, ep_out=0x01, ep_in=0x81,
    )
    return t, dev


def test_request_discards_packets_from_other_channel():
    """request() must skip write channel keepalives and return the
    response of the request's channel (mirrored src/dst)."""
    t, dev = _make_transport([WRITE_KEEPALIVE, WRITE_KEEPALIVE, READ_RESP])
    resp = t.request(READ_REQ, timeout_ms=500)
    assert resp == READ_RESP
    assert dev.written == [READ_REQ]


def test_request_without_channel_response_raises_transport_error():
    """If only packets from other channels arrive and then timeout, request()
    must fail as a normal timeout (not return another channel's packet)."""
    t, _ = _make_transport([WRITE_KEEPALIVE])
    try:
        t.request(READ_REQ, timeout_ms=200)
    except TransportError:
        pass
    else:
        raise AssertionError("request() returned a packet from another channel")


def test_request_direct_response_still_works():
    """Normal case without interference: first response is the correct one."""
    t, _ = _make_transport([READ_RESP])
    assert t.request(READ_REQ, timeout_ms=500) == READ_RESP
