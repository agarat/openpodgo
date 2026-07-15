"""Packet templates for the Helix/HX family vendor protocol.

The templates come from the reverse engineering published by the openhx
project (HX Stomp XL, PID 0x4253). POD Go belongs to the same family;
these templates are the starting point, and `tools/probe.py` confirms or
adjusts values against the real pedal. All multibyte integers are little-endian.

Every packet shares an 8-byte transport header:

    byte 0     body length after the fixed offset
    byte 1-2   0x00 0x00
    byte 3     "magic": 0x18 standard Line 6, 0x28 only in HANDSHAKE
    byte 4-5   source   (0x1001  -> 01 10)
    byte 6-7   dest     (0x03EF  -> EF 03)
    byte 9     sequence number (seq)
    byte 11    command code (cmd)

We do not interpret every field: we carry the exact templates and only
parameterize the fields known to vary (seq and stream offset).
"""

from __future__ import annotations

import msgpack

# Primary channel used during the handshake and preset operations.
SRC = 0x1001
DST = 0x03EF

# --- Session handshake (5 packets, see the openhx spec:
#     https://github.com/allansomensi/openhx) ---

HANDSHAKE = bytes.fromhex(
    "0c 00 00 28 01 10 ef 03 00 00 00 02 00 01 00 21 00 10 00 00".replace(" ", "")
)
SESSION_OPEN_1 = bytes.fromhex(
    "11 00 00 18 01 10 ef 03 00 02 00 04 00 10 00 00"
    "01 00 02 00 01 00 00 00 02 00 00 00".replace(" ", "")
)
SESSION_CHUNK_1 = bytes.fromhex(
    "08 00 00 18 01 10 ef 03 00 03 00 08 09 10 00 00".replace(" ", "")
)
SESSION_OPEN_2 = bytes.fromhex(
    "1a 00 00 18 01 10 ef 03 00 04 00 04 09 10 00 00"
    "01 00 02 00 0a 00 00 00 83 66 cd 03 e8 64 cc fe 65 80 00 00".replace(" ", "")
)
SESSION_CHUNK_2 = bytes.fromhex(
    "08 00 00 18 01 10 ef 03 00 05 00 08 1a 10 00 00".replace(" ", "")
)

#: The 5 init packets in order. After each one a bulk read is performed and
#: discarded (keeps the device state machine synchronized).
HANDSHAKE_SEQUENCE = (
    HANDSHAKE,
    SESSION_OPEN_1,
    SESSION_CHUNK_1,
    SESSION_OPEN_2,
    SESSION_CHUNK_2,
)

#: First seq available for application commands after the handshake.
FIRST_APP_SEQ = 0x06

# --- Preset listing / streaming ---

OPEN_PRESETS = bytes.fromhex(
    "19 00 00 18 01 10 ef 03 00 06 00 04 1a 10 00 00"
    "01 00 02 00 09 00 00 00 83 66 cd 03 e9 64 00 65 c0 00 00 00".replace(" ", "")
)
OPEN_STREAM = bytes.fromhex(
    "1d 00 00 18 01 10 ef 03 00 07 00 0c 38 10 00 00"
    "01 00 02 00 0d 00 00 00 83 66 cd 03 ea 64 01 65 82 6b 00 65 02 00 00 00".replace(" ", "")
)
#: Byte of OPEN_STREAM that selects the setlist (confirmed: 0=Factory, 1=User).
OPEN_STREAM_SETLIST_BYTE = 34


def build_open_stream(setlist: int = 0) -> bytes:
    """OPEN_STREAM pointing to a specific setlist (0=Factory, 1=User)."""
    if not 0 <= setlist <= 0xFF:
        raise ValueError(f"setlist out of range: {setlist}")
    pkt = bytearray(OPEN_STREAM)
    pkt[OPEN_STREAM_SETLIST_BYTE] = setlist
    return bytes(pkt)

#: Initial values for the chunk loop.
CHUNK_FIRST_SEQ = 0x08
#: Base offset of the preset stream.
#: HX Stomp XL uses 0x1138; POD Go (confirmed by capture) starts at 0x1000,
#: where the array header (DC 00 80) and preset 0 appear.
CHUNK_FIRST_OFFSET = 0x00001000
CHUNK_OFFSET_STEP = 0x0100
#: Bytes of "fresh window" per chunk. POD Go responds with 512 B transfers
#: (496 payload) but only the first `CHUNK_OFFSET_STEP` are new data;
#: the rest repeats the window. Only these are taken and concatenated.
CHUNK_WINDOW = CHUNK_OFFSET_STEP
#: Expected number of preset slots per setlist (array16 of 128).
PRESET_COUNT = 128
#: Maximum chunks to request as a safeguard.
MAX_CHUNKS = 64
#: Header of data responses; the payload starts at this byte.
RESPONSE_HEADER_LEN = 16
#: Header of the FIRST packet in a data message (16 transport +
#: 8 sub-header with the total message length in bytes 20-21 LE).
#: The OPEN_STREAM response for the User setlist is of this type and carries
#: the first data window (header DC 00 80 + first presets); the Factory
#: response is a plain 16 B ack.
FIRST_DATA_HEADER_LEN = 24
#: MessagePack array16 marker for 128 elements (DC 00 80) in the stream.
PRESET_ARRAY_MARKER = bytes((0xDC, 0x00, 0x80))
#: Key of the internal map of each preset that contains the name.
PRESET_NAME_KEY = 109


def build_chunk_request(seq: int, offset: int) -> bytes:
    """Build a 16-byte chunk request packet (Phase 3).

    `seq` is the sequence number (increments by +1, wraps at 0xFF) and
    `offset` is the 4-byte little-endian stream offset.
    """
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"seq out of range: {seq}")
    if not 0 <= offset <= 0xFFFFFFFF:
        raise ValueError(f"offset overflows u32: {offset:#x}")
    o = offset.to_bytes(4, "little")
    return bytes(
        (0x08, 0x00, 0x00, 0x18, 0x01, 0x10, 0xEF, 0x03,
         0x00, seq, 0x00, 0x08, o[0], o[1], o[2], o[3])
    )


def next_seq(seq: int) -> int:
    """Next sequence number, wrapping 0xFF -> 0x00."""
    return (seq + 1) & 0xFF


# --- Generic builder for "open" packets (RE of new resources) ---

#: Constant sub-header of open packets: 01 00 02 00 + len LE u16 + 00 00.
VENDOR_OPEN_SUBHEADER = bytes((0x01, 0x00, 0x02, 0x00))


def build_vendor_open(template: bytes, payload: dict, seq: int) -> bytes:
    """OPEN_*-style packet (cmd 0x04/0x0C) with a different MessagePack payload.

    Preserves from `template` the cmd (byte 11) and the cursor (bytes 12-15,
    whose calculation is not yet deciphered); recalculates byte 0 (= 16 +
    MessagePack payload length), the seq (byte 9), the sub-header length
    (bytes 20-21 LE) and the zero-padding to a multiple of 4. The dict
    insertion order is preserved on the wire: use the same key order as the
    templates ({102, 100, 101}).
    """
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"seq out of range: {seq}")
    body = msgpack.packb(payload)
    if 16 + len(body) > 0xFF:
        raise ValueError(f"payload too long for byte 0: {len(body)} B")
    pad = (-len(body)) % 4
    pkt = bytearray(template[:16])
    pkt[0] = 16 + len(body)
    pkt[9] = seq
    pkt += VENDOR_OPEN_SUBHEADER
    pkt += len(body).to_bytes(2, "little") + b"\x00\x00"
    pkt += body + b"\x00" * pad
    return bytes(pkt)


# --- Captured packet classification (RE of new commands) ---

#: Known OUT templates, for labeling captures.
KNOWN_TEMPLATES = {
    "HANDSHAKE": HANDSHAKE,
    "SESSION_OPEN_1": SESSION_OPEN_1,
    "SESSION_CHUNK_1": SESSION_CHUNK_1,
    "SESSION_OPEN_2": SESSION_OPEN_2,
    "SESSION_CHUNK_2": SESSION_CHUNK_2,
    "OPEN_PRESETS": OPEN_PRESETS,
    "OPEN_STREAM": OPEN_STREAM,
}


def _mask_variable_bytes(pkt: bytes, name: str | None = None) -> bytes:
    """Copy with seq (byte 9) zeroed; for OPEN_STREAM also the setlist."""
    b = bytearray(pkt)
    if len(b) > 9:
        b[9] = 0
    if name == "OPEN_STREAM" and len(b) > OPEN_STREAM_SETLIST_BYTE:
        b[OPEN_STREAM_SETLIST_BYTE] = 0
    return bytes(b)


def identify_command(payload: bytes) -> str:
    """Label a captured OUT packet: known template or description."""
    for name, tpl in KNOWN_TEMPLATES.items():
        if _mask_variable_bytes(payload, name) == _mask_variable_bytes(tpl, name):
            return name
    if len(payload) == 16 and payload[11] == 0x08:
        offset = int.from_bytes(payload[12:16], "little")
        return f"CHUNK_REQUEST(offset={offset:#x})"
    if len(payload) > 11:
        return f"UNKNOWN(cmd={payload[11]:#04x}, len={len(payload)})"
    return f"SHORT(len={len(payload)})"


def decode_open_body(payload: bytes):
    """MessagePack body of an open-style packet, or None if not applicable.

    Accepts subheader 01 00 (read/write channel requests) and
    00 00 (write channel responses from the real device).
    """
    if len(payload) < 24 or payload[16:18] not in (bytes((0x01, 0x00)), bytes((0x00, 0x00))):
        return None
    body_len = int.from_bytes(payload[20:22], "little")
    body = payload[24 : 24 + body_len]
    if len(body) != body_len:
        return None
    try:
        return msgpack.unpackb(body, strict_map_key=False)
    except Exception:
        return None


# --- Device write (Spec 03, channel 0x1080 → 0x03ED) ---

WRITE_SRC = 0x1080
WRITE_DST = 0x03ED
WRITE_SUBHEADER = bytes((0x01, 0x00, 0x06, 0x00))
WRITE_FIRST_APP_SEQ = 0x06

#: Default "warm" write stream cursor (from captured sessions). In a real
#: session it is TRACKED: WriteSession initializes it after the handshake and
#: advances it per command. See `write_cursor_advance`.
WRITE_DEFAULT_CURSOR = 0x0000203F

#: Sub-headers that mark a framed response (with body_len in 20:22). Other
#: data responses are raw windows starting at msgpack.
WRITE_FRAMED_SUBHEADERS = (
    bytes((0x00, 0x00, 0x06, 0x00)),
    bytes((0x01, 0x00, 0x06, 0x00)),
)


def build_vendor_write(
    payload: dict, seq: int, cmd: int = 0x04, cursor: int = WRITE_DEFAULT_CURSOR
) -> bytes:
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"seq out of range: {seq}")
    if not 0 <= cursor <= 0xFFFFFFFF:
        raise ValueError(f"cursor overflows u32: {cursor:#x}")
    body = msgpack.packb(payload, use_single_float=True)
    if 16 + len(body) > 0xFF:
        raise ValueError(f"payload too long: {len(body)} B")
    pad = (-len(body)) % 4
    pkt = bytearray(16)
    pkt[0] = 16 + len(body)
    pkt[3] = 0x18
    pkt[4] = WRITE_SRC & 0xFF
    pkt[5] = (WRITE_SRC >> 8) & 0xFF
    pkt[6] = WRITE_DST & 0xFF
    pkt[7] = (WRITE_DST >> 8) & 0xFF
    pkt[9] = seq
    pkt[11] = cmd
    pkt[12:16] = cursor.to_bytes(4, "little")
    pkt += WRITE_SUBHEADER
    pkt += len(body).to_bytes(2, "little") + b"\x00\x00"
    pkt += body + b"\x00" * pad
    return bytes(pkt)


#: Max bytes per fragmented write frame (512 B transfers in the
#: change-pedal-order-from-app.pcapng capture).
WRITE_FRAME_MAX = 512


def _write_frame_header(seq: int, cursor: int, data_len: int, cmd: int) -> bytearray:
    """16 B header for a write channel frame (u16 length in [0:2])."""
    pkt = bytearray(16)
    frame_len = 16 + data_len  # bytes after the header counted in data_len
    pkt[0:2] = (8 + data_len).to_bytes(2, "little")  # lenf field = total - 8
    pkt[3] = 0x18
    pkt[4] = WRITE_SRC & 0xFF
    pkt[5] = (WRITE_SRC >> 8) & 0xFF
    pkt[6] = WRITE_DST & 0xFF
    pkt[7] = (WRITE_DST >> 8) & 0xFF
    pkt[9] = seq
    pkt[11] = cmd
    pkt[12:16] = cursor.to_bytes(4, "little")
    return pkt


def build_vendor_write_chunked(
    payload: dict, seq: int, cursor: int = WRITE_DEFAULT_CURSOR, cmd: int = 0x04
) -> list[bytes]:
    """Fragment a large msgpack payload into write channel frames.

    Used by op 21 (dump the full chain blob, #move-block). The first frame
    carries header(16) + subheader `01 00 06 00` + `total_len` (u32 LE) +
    data; continuation frames carry only header + data. All share the same
    `cursor` (the message start) with incremental `seq`, and are padded to
    a multiple of 4 (USB alignment). The device reassembles by `total_len`,
    so the exact size of each chunk is not critical.

    Inverse: concatenating the data of each frame (without the first frame's
    subheader) reproduces the packed `payload`.

    `use_bin_type=False`: the pedal packs bytes (the key 110 blob) with
    str/raw header (`da`), not bin (`c5`) — classic msgpack "raw" format.
    """
    body = msgpack.packb(payload, use_single_float=True, use_bin_type=False)
    total = len(body)
    frames: list[bytes] = []
    pos = 0
    first = True
    while first or pos < total:
        prefix = WRITE_SUBHEADER + total.to_bytes(4, "little") if first else b""
        room = WRITE_FRAME_MAX - 16 - len(prefix)
        chunk = body[pos:pos + room]
        data = prefix + chunk
        pad = (-len(data)) % 4
        data += b"\x00" * pad
        frames.append(bytes(_write_frame_header(seq, cursor, len(data), cmd)) + data)
        pos += len(chunk)
        seq = (seq + 1) & 0xFF
        first = False
    return frames


def build_write_chunk(seq: int, cursor: int) -> bytes:
    """16 B chunk-read on the write channel (cmd=0x08).

    Consumes the device response to a previous command, same as on the read
    channel but with src=0x1080 → dst=0x03ED.
    """
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"seq out of range: {seq}")
    if not 0 <= cursor <= 0xFFFFFFFF:
        raise ValueError(f"cursor overflows u32: {cursor:#x}")
    o = cursor.to_bytes(4, "little")
    return bytes(
        (0x08, 0x00, 0x00, 0x18, WRITE_SRC & 0xFF, (WRITE_SRC >> 8) & 0xFF,
         WRITE_DST & 0xFF, (WRITE_DST >> 8) & 0xFF,
         0x00, seq, 0x00, 0x08, o[0], o[1], o[2], o[3])
    )


def write_cursor_advance(resp: bytes) -> int:
    """How much the write stream cursor advances after a response.

    - Bare ack (<=16 B): 0.
    - Framed response (subheader 00/01 00 06 00 at 16:20): 8 + body_len[20:22].
    - Raw data window (starts at msgpack): len(resp) - 16.
    """
    if len(resp) <= 16:
        return 0
    if resp[16:20] in WRITE_FRAMED_SUBHEADERS:
        return 8 + int.from_bytes(resp[20:22], "little")
    return len(resp) - 16


# --- Event channel (Spec 04, src=0x1002 → dst=0x03F0) -------------------
#
# POD Go Edit opens a third logical channel to receive notifications that
# the pedal emits when the user touches it (knobs, footswitches, snapshot,
# preset). The protocol is 100% polled: the host sends cmd=0x10 keepalives
# and the device responds cmd=0x10 (nothing new) or cmd=0x04 (data = event).
# The open templates come verbatim from captures/win-captures/win_connect.

EVENT_SRC = 0x1002
EVENT_DST = 0x03F0

#: Event channel open (3 packets, copied from the write channel
#: but with session type 0x04 instead of 0x06). The read cursor settles
#: at 0x1009 after opening and stays fixed while no events arrive.
EVENT_HANDSHAKE = bytes.fromhex("0c0000280210f003000000020001002100100000")
EVENT_OPEN = bytes.fromhex(
    "110000180210f0030002000400100000010004000100000004000000"
)
EVENT_CHUNK = bytes.fromhex("080000180210f0030003000809100000")
#: Rest cursor after opening (cursor field of EVENT_CHUNK).
EVENT_REST_CURSOR = int.from_bytes(EVENT_CHUNK[12:16], "little")


def build_event_poll(seq: int, cursor: int) -> bytes:
    """cmd=0x10 keepalive for the event channel (host → device)."""
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"seq out of range: {seq}")
    o = cursor.to_bytes(4, "little")
    return bytes(
        (0x08, 0x00, 0x00, 0x18, EVENT_SRC & 0xFF, (EVENT_SRC >> 8) & 0xFF,
         EVENT_DST & 0xFF, (EVENT_DST >> 8) & 0xFF,
         0x00, seq, 0x00, 0x10, o[0], o[1], o[2], o[3])
    )


def build_event_ack(seq: int, cursor: int) -> bytes:
    """cmd=0x08 ack/chunk-read that advances the cursor after receiving an event."""
    if not 0 <= seq <= 0xFF:
        raise ValueError(f"seq out of range: {seq}")
    o = cursor.to_bytes(4, "little")
    return bytes(
        (0x08, 0x00, 0x00, 0x18, EVENT_SRC & 0xFF, (EVENT_SRC >> 8) & 0xFF,
         EVENT_DST & 0xFF, (EVENT_DST >> 8) & 0xFF,
         0x00, seq, 0x00, 0x08, o[0], o[1], o[2], o[3])
    )


def event_cursor_advance(resp: bytes) -> int:
    """Event channel cursor advance after a received frame.

    Bare keepalive (<=16 B) → 0. Framed data frame → 8 + body_len. The
    event channel sub-header is 00 00 04 00 (not the 00 00 06 00 of the
    write channel), so `write_cursor_advance` is not reused here.
    """
    if len(resp) <= 16:
        return 0
    return 8 + int.from_bytes(resp[20:22], "little")
