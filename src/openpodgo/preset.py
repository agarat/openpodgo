"""Preset reading and decoding (device MessagePack stream).

Implements paginated streaming (presets/list.md) and parsing of the
128-preset array (presets/data-format.md), plus a bridge to .pgp files
(JSON) used by the official app / CustomTone.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

import msgpack

from . import l6helix
from . import packets
from .session import Session

log = logging.getLogger(__name__)


@dataclass
class PresetEntry:
    """A preset listing entry from the device.

    `slot` is the position within the setlist (= Program Change number,
    0-127); `index` is the stable preset ID on the device. In Factory both
    match, but in User they diverge when the user reorders presets: the real
    slot is the ENTRY POSITION in the stream, not its index.
    """

    index: int
    name: str
    slot: int = 0


@dataclass
class PresetStream:
    """Result of a raw preset stream dump, not yet decoded."""

    raw: bytes
    chunks: int
    #: Per-chunk individual buffers, useful for labeling captures.
    chunk_payloads: list[bytes] = field(default_factory=list)


def read_setlists(session: Session) -> list[str]:
    """Return the names of the pedal setlists (e.g. ["Factory","User"]).

    Re-executes the handshake to start from a clean session state.
    """
    session.handshake()
    resp = session.transport.request(packets.OPEN_PRESETS)
    return parse_setlists(resp)


def parse_setlists(open_presets_resp: bytes) -> list[str]:
    """Extract setlist names from the OPEN_PRESETS response.

    The response contains a fixmap with key 104 whose value is an array of
    maps {0: "name\\0"} (one per setlist).
    """
    start = open_presets_resp.find(b"\x83\x66")  # fixmap(3) with key 102
    if start < 0:
        return []
    try:
        unp = msgpack.Unpacker(raw=False, strict_map_key=False)
        unp.feed(open_presets_resp[start:])
        outer = unp.unpack()
    except Exception:
        return []
    arr = outer.get(104) if isinstance(outer, dict) else None
    names: list[str] = []
    if isinstance(arr, list):
        for el in arr:
            if isinstance(el, dict) and el:
                val = next(iter(el.values()))
                if isinstance(val, bytes):
                    val = val.decode("utf-8", "replace")
                if isinstance(val, str):
                    names.append(val.rstrip("\x00").strip())
    return names


def stream_presets(session: Session, setlist: int = 0) -> PresetStream:
    """Execute the preset stream for a setlist and return the raw buffer.

    Confirmed differences with HX Stomp XL (see docs/protocol.md):
    - OPEN_STREAM only returns an ack; data arrives in chunk-requests.
    - Byte 34 of OPEN_STREAM selects the setlist (0=Factory, 1=User).
    - Each 512 B chunk carries only `CHUNK_WINDOW` fresh bytes (the rest
      repeats the window); those are taken and concatenated in order.
    - The base offset is 0x1000 where the array header (DC 00 80) appears.

    Re-executes the handshake to guarantee a clean session state (reading
    a second setlist on a used session desyncs the device).
    """
    session.handshake()
    t = session.transport

    # Open the preset resource and start streaming the requested setlist.
    t.request(packets.OPEN_PRESETS)
    session.advance_seq()
    ack = t.request(packets.build_open_stream(setlist))
    session.advance_seq()

    # The OPEN_STREAM response may be the FIRST packet of the data message
    # (User case: 24 B header + first window with `DC 00 80` and the first
    # presets) or a plain 16 B ack (Factory case, where data starts in the
    # chunk-requests). If it carries data, it goes at the beginning of the
    # buffer: discarding it loses the first ~9 presets of the setlist.
    head = ack[packets.FIRST_DATA_HEADER_LEN:]

    # Reassembly by ABSOLUTE OFFSET with the complete payload: each 512 B
    # chunk brings ~CHUNK_WINDOW fresh bytes followed by a repetition; by
    # placing the full payload at its absolute position, the next chunk
    # (offset +CHUNK_OFFSET_STEP) overwrites the repetition with correct data.
    # This way no entries are lost at boundaries (truncating to 256 cut the
    # `81 cd` anchor of presets straddling the boundary) and there are no gaps
    # from short chunks.
    buf = bytearray(head)
    payloads: list[bytes] = []
    base = packets.CHUNK_FIRST_OFFSET
    seq = packets.CHUNK_FIRST_SEQ
    offset = base
    chunks = 0
    for _ in range(packets.MAX_CHUNKS):
        resp = t.request(packets.build_chunk_request(seq, offset))
        chunks += 1
        payload = resp[packets.RESPONSE_HEADER_LEN:]
        if not payload:
            break  # empty payload: stream exhausted (natural end)
        payloads.append(bytes(payload))
        pos = len(head) + (offset - base)
        end = pos + len(payload)
        if end > len(buf):
            buf.extend(b"\x00" * (end - len(buf)))
        buf[pos:end] = payload
        # Cut when we have the complete setlist; this avoids over-requesting
        # chunks (over-requesting leaves the device misaligned for the next
        # operation). The User setlist usually brings < PRESET_COUNT: ends
        # with an empty payload.
        if len(scan_preset_entries(buf)) >= packets.PRESET_COUNT:
            break
        new_offset = offset + packets.CHUNK_OFFSET_STEP
        if new_offset > 0xFFFFFFFF:
            raise OverflowError("stream offset overflows u32")
        offset = new_offset
        seq = packets.next_seq(seq)

    raw = bytes(buf)

    # Intentionally not drained here: the device may keep sending stream
    # chunks. The next operation's handshake drain clears pending data in a
    # synchronized way (draining halfway here desyncs).

    log.info("Preset stream: %d chunks, %d bytes", chunks, len(raw))
    return PresetStream(raw=bytes(raw), chunks=chunks, chunk_payloads=payloads)


#: Name key (109) encoded as uint16 MessagePack: cd 00 6d.
_NAME_KEY_BYTES = bytes((0xCD, 0x00, packets.PRESET_NAME_KEY))


def scan_preset_entries(raw: bytes) -> list[tuple[int, str]]:
    """Scan entries (index, name) by pattern, IN STREAM ORDER.

    Robust for both setlists: searches for the name key (109) in each entry
    `81 cd HI LO 8N cd 00 6d <name\\0>`, decodes the string that follows and
    obtains the index of the preceding `81 cd HI LO`. Order of appearance
    matters: it defines the slot (see `PresetEntry`).
    """
    out: list[tuple[int, str]] = []
    i = 0
    while True:
        j = raw.find(_NAME_KEY_BYTES, i)
        if j < 0:
            break
        i = j + 3
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
        # Index: pattern `81 cd HI LO 8N cd 00 6d` (outer map with uint16 key).
        if j >= 5 and raw[j - 5] == 0x81 and raw[j - 4] == 0xCD:
            index = (raw[j - 3] << 8) | raw[j - 2]
            out.append((index, name))
    return out


def parse_preset_list(raw: bytes) -> list[PresetEntry]:
    """Extract the preset list from the raw stream, with slot = position.

    Uses pattern scanning (`scan_preset_entries`), which works for both
    Factory and User setlists alike. The stream emits entries in slot order;
    each entry's index is a stable ID that in User may not match the slot
    (reordered presets).
    """
    entries = scan_preset_entries(raw)
    if not entries:
        raise ValueError("No preset entries found in the stream")
    return [
        PresetEntry(index=idx, name=name, slot=slot)
        for slot, (idx, name) in enumerate(entries)
    ]


# --- Active preset reading (objects 22 and 23, spec 02 Phase B) ---

#: Open vendor objects (key 100). Full map: docs/specs/02-lab-notes.md.
OBJ_SLOT_CHECKSUMS = 14
OBJ_ACTIVE_PRESET = 22
OBJ_ACTIVE_STATE = 23


@dataclass
class ActiveState:
    """Which preset is active on the pedal (object 23).

    `edited` is for future use: if a pedal capture revealed an explicit
    "edited" flag in object 23 it would be filled from there. Today it
    stays `None` — key 117, the only candidate, is RULED OUT (stays False
    after editing; see docs/specs/06-lab-notes.md). Edited detection goes
    through comparison in `device.PodGo.active_preset_is_edited`.
    """

    setlist: int
    slot: int
    name: str
    edited: bool | None = None


def read_object(session: Session, k100: int, k101: dict | None = None) -> bytes:
    """Reassembled dump of a vendor object (key 100) via open 0x0C.

    Reproduces the flow validated in Phase A (tools/preset_explore.py):
    fresh handshake, OPEN_PRESETS, open variant, and chunk-requests until
    empty payload. Returns the COMPLETE message {102, 103, 104}; decode
    with l6helix.extract_result / extract_blob.
    """
    if k101 is None:
        k101 = {107: 0, 101: 2}
    session.handshake()
    t = session.transport
    t.request(packets.OPEN_PRESETS)
    # Key 102 is a TRANSACTION ID that the device echoes, not a selector
    # (lab-notes E5b); 1002 is the historical value from captures.
    pkt = packets.build_vendor_open(
        packets.OPEN_STREAM, {102: 1002, 100: k100, 101: k101}, seq=0x07
    )
    resp = t.request(pkt)
    buf = bytearray(resp[packets.FIRST_DATA_HEADER_LEN:])
    seq = packets.CHUNK_FIRST_SEQ
    offset = packets.CHUNK_FIRST_OFFSET
    for _ in range(packets.MAX_CHUNKS):
        r = t.request(packets.build_chunk_request(seq, offset))
        payload = r[packets.RESPONSE_HEADER_LEN:]
        if not payload:
            break
        buf.extend(payload[: packets.CHUNK_WINDOW])
        offset += packets.CHUNK_OFFSET_STEP
        seq = packets.next_seq(seq)
    log.info("Object %d: %d bytes", k100, len(buf))
    return bytes(buf)


def read_active_preset(session: Session) -> l6helix.Preset:
    """Read and decode the full active preset (object 22)."""
    buf = read_object(session, OBJ_ACTIVE_PRESET)
    return l6helix.parse_blob(l6helix.extract_blob(buf))


def parse_slot_checksums(buf: bytes) -> dict[int, int | None]:
    """Decode the per-slot checksum table (object 14).

    Object 14 carries in key 104 an array of 128 maps ``{slot: crc32}``
    (one u32 per slot of the setlist). It is the content "seal" the pedal
    maintains per stored preset (probably the same u32 emitted by key 116
    of the save event; see docs/specs/06-lab-notes.md). Serves as a cheap
    comparator to detect edited without diffing the entire blob.

    Returns a dict ``{slot: crc32}``; empty slots arrive as ``None``
    (real captures have slots without presets). Tolerates malformed entries
    by skipping them.
    """
    result = l6helix.extract_result(buf)
    out: dict[int, int | None] = {}
    if isinstance(result, list):
        for el in result:
            if isinstance(el, dict) and len(el) == 1:
                (slot, crc), = el.items()
                if isinstance(slot, int) and (crc is None or isinstance(crc, int)):
                    out[slot] = crc
    return out


def read_slot_checksums(session: Session, setlist: int = 0) -> dict[int, int | None]:
    """Read the per-slot checksum table for the setlist (object 14)."""
    buf = read_object(session, OBJ_SLOT_CHECKSUMS, {107: setlist, 101: 2})
    return parse_slot_checksums(buf)


def parse_active_state(result: dict) -> ActiveState:
    """Decode the inline result of object 23."""
    return ActiveState(
        setlist=result.get(107, 0),
        slot=result.get(108, 0),
        name=l6helix.text(result.get(109, "")),
    )


def read_active_state(session: Session) -> ActiveState:
    """Read setlist/slot/name of the active preset (object 23)."""
    buf = read_object(session, OBJ_ACTIVE_STATE)
    return parse_active_state(l6helix.extract_result(buf))


# --- Bridge with .pgp files (JSON) ---

def load_pgp(path: str | Path) -> dict:
    """Load a .pgp preset (JSON) from disk."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_pgp(data: dict, path: str | Path) -> None:
    """Save a preset as .pgp (JSON) preserving stable formatting."""
    Path(path).write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
