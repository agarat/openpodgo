"""Application-level session: 5-packet handshake and recovery.

Follows https://github.com/allansomensi/openhx and error-recovery.md.
"""

from __future__ import annotations

import logging
import time

from . import packets
from .usb_transport import TransportError, UsbTransport

log = logging.getLogger(__name__)

MAX_INIT_ATTEMPTS = 5
BACKOFF_BASE_MS = 300


def _frame_desc(p: bytes) -> str:
    """Summary of a write channel frame for debug logs.

    Decodes the 16 B header fields: cmd (p[11]), seq (p[9]), cursor
    (p[12:16] u32 LE) and src/dst (p[4:8]). Used for comparing our
    exchange against change-pedal-order-from-app.pcapng (#flow-control op 21).
    """
    if len(p) < 16:
        return f"len={len(p)} <16B {p.hex(' ')}"
    cmd = p[11]
    seq = p[9]
    cursor = int.from_bytes(p[12:16], "little")
    return (
        f"len={len(p):4} cmd={cmd:#04x} seq={seq:3} cursor={cursor:#08x} "
        f"src={p[4:6].hex()}->{p[6:8].hex()} sub={p[16:20].hex(' ') if len(p) >= 20 else ''}"
    )


class SessionError(Exception):
    """Could not establish application session with the device."""


class Session:
    """Manages session state on an already-opened UsbTransport."""

    def __init__(self, transport: UsbTransport) -> None:
        self.transport = transport
        self._seq = packets.FIRST_APP_SEQ
        self._open = False

    @property
    def seq(self) -> int:
        return self._seq

    def advance_seq(self) -> int:
        """Return the current seq and advance the counter (wraps 0xFF->0x00)."""
        current = self._seq
        self._seq = packets.next_seq(self._seq)
        return current

    #: Short timeout for handshake packets: the device ignores the first
    #: post-connection attempt (~50 ms to be ready), so we fail fast and
    #: retry instead of waiting 2 s per packet.
    HANDSHAKE_TIMEOUT_MS = 300

    def handshake(self) -> None:
        """Execute the 5-packet init with drain + exponential backoff.

        The device requires this handshake before each major operation
        (list_setlists, stream_presets, read_object). The first attempt
        usually fails because the device is still processing the previous
        response; drain + 300 ms backoff + second attempt always works.
        """
        last_exc: Exception | None = None
        for attempt in range(MAX_INIT_ATTEMPTS):
            try:
                self.transport.drain()
                for pkt in packets.HANDSHAKE_SEQUENCE:
                    self.transport.request(pkt, timeout_ms=self.HANDSHAKE_TIMEOUT_MS)
                self._seq = packets.FIRST_APP_SEQ
                self._open = True
                log.info("Handshake completed (attempt %d)", attempt + 1)
                return
            except TransportError as exc:
                last_exc = exc
                wait = BACKOFF_BASE_MS * (2 ** attempt)
                log.warning(
                    "Handshake attempt %d failed (%s); retrying in %d ms",
                    attempt + 1, exc, wait,
                )
                time.sleep(wait / 1000.0)
        raise SessionError(
            f"Handshake failed after {MAX_INIT_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    @property
    def is_open(self) -> bool:
        return self._open


class WriteSession:
    """Write session on the same UsbTransport.

    POD Go Edit opens a separate channel (src=0x1080, dst=0x03ED) for
    writing, with its own handshake and seq. Shares the USB transport
    with the read session.
    """

    WRITE_HANDSHAKE = bytes.fromhex(
        "0c 00 00 28 80 10 ed 03 00 00 00 02 00 01 00 21 00 10 00 00"
    )
    # byte[18]=0x06 (not 0x05): POD Go session type; byte[24]=0x06: msgpack body
    WRITE_OPEN_1 = bytes.fromhex(
        "11 00 00 18 80 10 ed 03 00 02 00 04 00 10 00 00 "
        "01 00 06 00 01 00 00 00 06 00 00 00"
    )
    # byte[11]=0x08 (not 0x02): cmd; bytes[12-13]=09 10 (not 34 10): cursor
    WRITE_CHUNK_1 = bytes.fromhex(
        "08 00 00 18 80 10 ed 03 00 03 00 08 09 10 00 00"
    )
    # byte[0]=0x19, bytes[12-13]=09 10, byte[20]=0x09 (body_len=9, pad=3)
    WRITE_OPEN_2 = bytes.fromhex(
        "19 00 00 18 80 10 ed 03 00 04 00 04 09 10 00 00 "
        "01 00 06 00 09 00 00 00 83 66 cd 03 e8 64 4c 65 80 00 00 00"
    )

    def __init__(self, transport: UsbTransport) -> None:
        self.transport = transport
        self._seq = 0x00
        self._open = False
        #: Position in the write stream. Initialized in handshake() and
        #: advanced per command; the device validates the cursor against its
        #: own position and discards (ACKing) mispositioned commands.
        self._cursor = 0x00

    @property
    def seq(self) -> int:
        return self._seq

    @property
    def cursor(self) -> int:
        return self._cursor

    def advance_seq(self) -> int:
        current = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return current

    def handshake(self) -> None:
        """4-packet handshake for the write channel.

        The stream cursor settles at the post-handshake rest position: the
        WRITE_OPEN_2 cursor plus its response advance (the device responds
        with object 76). After that set_param works without having to dump
        the full preset via the write channel.
        """
        open2_cursor = int.from_bytes(self.WRITE_OPEN_2[12:16], "little")
        last_exc: Exception | None = None
        for attempt in range(MAX_INIT_ATTEMPTS):
            try:
                self.transport.drain()  # clear residual keepalives from the read channel
                resp = b""
                for pkt in (self.WRITE_HANDSHAKE, self.WRITE_OPEN_1,
                            self.WRITE_CHUNK_1, self.WRITE_OPEN_2):
                    resp = self.transport.request(pkt)
                self._seq = 0x05
                self._cursor = open2_cursor + packets.write_cursor_advance(resp)
                self._open = True
                log.info(
                    "Write handshake completed (attempt %d); cursor=%#06x",
                    attempt + 1, self._cursor,
                )
                return
            except TransportError as exc:
                last_exc = exc
                wait = BACKOFF_BASE_MS * (2 ** attempt)
                log.warning(
                    "Write handshake attempt %d failed (%s); retrying in %d ms",
                    attempt + 1, exc, wait,
                )
                time.sleep(wait / 1000.0)
        raise SessionError(
            f"Write handshake failed after {MAX_INIT_ATTEMPTS} attempts: {last_exc}"
        ) from last_exc

    #: Per-read timeout when draining write command responses.
    WRITE_DRAIN_MS = 250

    #: Shorter timeout between fragmented send frames (op 21): the pedal
    #: grants credits (cmd=0x08) in a few ms, so a 250 ms drain per frame
    #: adds ~2 s of dead wait. 80 ms is enough to read the grants.
    WRITE_CHUNK_DRAIN_MS = 80

    def send_write(self, payload: dict, cmd: int = 0x04) -> bytes:
        """Send a write command at the current cursor and return its echoed status.

        The device autonomously responds with several frames: 16 B acks
        (cmd=0x10/0x08, no status) and a framed echo of ~48 B with
        `{102, 103, 104}` that carries the status. ALL must be drained:
        leaving one unread desynchronizes the next command (it reads the old
        response). Advances the cursor by the request footprint (8 + body_len);
        keeping it synchronized is what makes the device apply the change
        instead of just ACKing it.
        """
        seq = self.advance_seq()
        pkt = packets.build_vendor_write(payload, seq=seq, cmd=cmd, cursor=self._cursor)
        self.transport.write(pkt)
        self._cursor += 8 + int.from_bytes(pkt[20:22], "little")
        echo = b""
        while True:
            try:
                resp = self.transport.read(self.WRITE_DRAIN_MS)
            except TransportError:
                break
            if len(resp) > 24 and resp[16:20] in packets.WRITE_FRAMED_SUBHEADERS:
                echo = resp  # the framed frame carries the status
        return echo

    def send_write_chunked(self, payload: dict, cmd: int = 0x04) -> bytes:
        """Send a large fragmented payload (op 21, dump the chain).

        Sends all frames at the current cursor with incremental `seq` (same as
        in the change-pedal-order-from-app.pcapng capture, where frames of the
        same message share cursor), draining between frames the device's flow
        control responses (cmd=0x08) and keeping the framed echo that carries
        the status. Advances the cursor by the message footprint (subheader 8 +
        body), same as `send_write`.

        Note: fine-grained flow control (when the device requests each window)
        is pending live validation; this loop is the best model of the capture.
        """
        import msgpack

        body = msgpack.packb(payload, use_single_float=True, use_bin_type=False)
        frames = packets.build_vendor_write_chunked(
            payload, seq=self._seq, cursor=self._cursor, cmd=cmd
        )
        self._seq = (self._seq + len(frames)) & 0xFF
        log.debug("send_write_chunked: %d frames, %d B body, cursor=%#08x",
                  len(frames), len(body), self._cursor)
        echo = b""
        for i, frame in enumerate(frames):
            log.debug("  OUT[%d] %s", i, _frame_desc(frame))
            self.transport.write(frame)
            while True:
                try:
                    resp = self.transport.read(self.WRITE_CHUNK_DRAIN_MS)
                except TransportError:
                    break
                log.debug("  IN      %s", _frame_desc(resp))
                if len(resp) > 24 and resp[16:20] in packets.WRITE_FRAMED_SUBHEADERS:
                    echo = resp
        self._cursor += 8 + len(body)
        log.debug("send_write_chunked: fin, echo len=%d", len(echo))
        return echo

    def request(self, pkt: bytes) -> bytes:
        return self.transport.request(pkt)

    @property
    def is_open(self) -> bool:
        return self._open


class EventSession:
    """Pedal event channel (src=0x1002, dst=0x03F0) — Spec 04 live sync.

    POD Go Edit opens this third channel to receive notifications when the
    user touches the pedal. The protocol is polled: `poll()` sends a cmd=0x10
    keepalive and reads the response; if the device has an event it responds
    with a cmd=0x04 data frame (returned raw for parsing) and is then
    ACKed with cmd=0x08 to advance the cursor. Without this polling the
    device pushes nothing to the IN endpoint (a bare read times out).
    """

    #: Poll response read timeout (device responds quickly).
    POLL_TIMEOUT_MS = 200

    def __init__(self, transport: UsbTransport) -> None:
        self.transport = transport
        self._seq = 0x00
        self._cursor = packets.EVENT_REST_CURSOR
        self._open = False

    @property
    def cursor(self) -> int:
        return self._cursor

    @property
    def is_open(self) -> bool:
        return self._open

    def _advance_seq(self) -> int:
        current = self._seq
        self._seq = (self._seq + 1) & 0xFF
        return current

    def handshake(self) -> None:
        """Open the event channel (3 packets) and leave the cursor at rest."""
        last_exc: Exception | None = None
        for attempt in range(MAX_INIT_ATTEMPTS):
            try:
                self.transport.drain()
                for pkt in (packets.EVENT_HANDSHAKE, packets.EVENT_OPEN,
                            packets.EVENT_CHUNK):
                    self.transport.request(pkt)
                self._seq = 0x04
                self._cursor = packets.EVENT_REST_CURSOR
                self._open = True
                log.info(
                    "Event channel opened (src=0x1002, dst=0x03F0); "
                    "cursor=%#06x", self._cursor,
                )
                return
            except TransportError as exc:
                last_exc = exc
                wait = BACKOFF_BASE_MS * (2 ** attempt)
                log.warning(
                    "Event channel open attempt %d failed (%s); retrying in %d ms",
                    attempt + 1, exc, wait,
                )
                time.sleep(wait / 1000.0)
        raise SessionError(
            f"Could not open event channel after {MAX_INIT_ATTEMPTS} "
            f"attempts: {last_exc}"
        ) from last_exc

    def poll(self) -> list[bytes]:
        """Poll the event channel and drain the burst of pending events.

        Sends a cmd=0x10 keepalive and reads the response; while data frames
        arrive (cmd=0x04 from channel 0x03F0) it accumulates them, advances
        the cursor, and ACKs (cmd=0x08), reading the next response — so a
        knob turn that queues multiple events is fully drained without loss.
        Returns the list of raw frames (empty if only a keepalive was
        received). The caller coordinates exclusive access to the endpoint
        (transport lock).
        """
        if not self._open:
            return []
        poll = packets.build_event_poll(self._advance_seq(), self._cursor)
        self.transport.write(poll)
        frames: list[bytes] = []
        while True:
            try:
                resp = self.transport.read(self.POLL_TIMEOUT_MS)
            except TransportError:
                break  # no response: end of burst
            # Only data frames from the event channel (src=0x03F0, cmd=0x04).
            if len(resp) < 12 or resp[4:6] != b"\xf0\x03" or resp[11] != 0x04:
                break  # keepalive or something else: no (more) events
            frames.append(resp)
            self._cursor += packets.event_cursor_advance(resp)
            ack = packets.build_event_ack(self._advance_seq(), self._cursor)
            self.transport.write(ack)  # we read its response in the next iteration
        return frames
