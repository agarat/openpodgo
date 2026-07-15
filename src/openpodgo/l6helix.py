"""Decoding the l6-helix container (active preset, spec 02 Phase B).

Object 22 of the open vendor returns the full active preset as a
message `{102: txn, 103: status, 104: blob}`. The blob is the
`l6-helix` container: magic + offset table + ONE MessagePack map with
the chain of blocks, snapshots and metadata. The key mapping is validated
against POD Go Edit `.pgp` files: docs/specs/02-lab-notes.md,
"blob ↔ .pgp mapping".
"""

from __future__ import annotations

import io
import struct
from dataclasses import dataclass, field

import msgpack

#: Container magic, NUL included (fixstr of 9 on the wire).
MAGIC = b"l6-helix\x00"

# Keys of the open response message (lab-notes E2/E5b).
KEY_STATUS = 103
KEY_RESULT = 104
KEY_ERROR_CODE = 111


class DeviceStatusError(RuntimeError):
    """The device rejected the operation (status != 0 in the response)."""


def text(value) -> str:
    """Normalize device strings: NUL-terminated, sometimes bytes."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    return value.rstrip("\x00").strip()


def unpack_message(buf: bytes) -> dict:
    """Decode the `{102, 103, 104}` message, tolerating trailing padding.

    `raw=True` because the key 104 blob is not valid UTF-8.
    """
    unp = msgpack.Unpacker(io.BytesIO(buf), raw=True, strict_map_key=False)
    msg = unp.unpack()
    if not isinstance(msg, dict):
        raise ValueError(f"message is not a map: {type(msg).__name__}")
    return msg


def extract_result(buf: bytes):
    """Validate the message status and return the result (key 104)."""
    msg = unpack_message(buf)
    status = msg.get(KEY_STATUS)
    if status != 0:
        detail = msg.get(KEY_RESULT)
        code = detail.get(KEY_ERROR_CODE) if isinstance(detail, dict) else None
        raise DeviceStatusError(f"open rejected: status={status} code={code}")
    return msg.get(KEY_RESULT)


def extract_blob(buf: bytes) -> bytes:
    """Extract the l6-helix blob from a dump message (object 22)."""
    result = extract_result(buf)
    if not isinstance(result, bytes):
        raise ValueError(f"result is not a blob: {type(result).__name__}")
    return result


def split_container(blob: bytes) -> tuple[list[int], bytes]:
    """Separate the container: validate the magic and return (offsets, body).

    The offsets (u32 LE) point to positions within the blob; the body
    following the table is a single MessagePack map, so for decoding the
    body and offsets suffice (offsets remain informational).
    """
    unp = msgpack.Unpacker(io.BytesIO(blob), raw=True)
    magic = unp.unpack()
    if magic != MAGIC:
        raise ValueError(f"not an l6-helix container: {magic!r}")
    table = unp.unpack()
    if not isinstance(table, bytes) or len(table) % 4:
        raise ValueError(f"invalid offset table: {table!r}")
    offsets = list(struct.unpack(f"<{len(table) // 4}I", table))
    return offsets, blob[unp.tell():]


#: Offset table schema for the container (validated against real pedal
#: blobs, see split_container). The table is 12 u32 LE:
#:   [body_start, off(k) per key of _BLOB_TABLE_KEYS, blob_end, blob_end]
#: where off(k) points to the byte of that top-level key entry in the body.
#: The order is NOT the wire key order; it is the fixed order POD Go Edit
#: emits. For a missing key, blob_end is used.
_BLOB_TABLE_KEYS = (0, 1, 3, 4, 2, 5, 6, 7, 10)
#: Fixed table size: body_start + keys + two end markers.
_BLOB_TABLE_LEN = len(_BLOB_TABLE_KEYS) + 3


def _toplevel_key_offsets(body: dict) -> dict:
    """Byte offset (body-relative) of each top-level key in the packed body.

    Walks the map packing key+value in insertion order (msgpack preserves
    order), with the same encoder as `build_blob` (single-float).
    """
    if len(body) > 15:
        raise ValueError("body with >15 keys: map header is not 1 byte")
    pos = 1  # after fixmap header (1 byte for <=15 keys)
    out: dict = {}
    for key, value in body.items():
        out[key] = pos
        pos += len(msgpack.packb(key, use_single_float=True))
        pos += len(msgpack.packb(value, use_single_float=True))
    return out


def build_blob(body: dict) -> bytes:
    """Serialize a `body` to an l6-helix container ready for the pedal.

    Inverse of `split_container`: magic (fixstr9) + offset table (str16) +
    MessagePack body. Floats go as float32 (all wire data is f32, zero f64)
    and strings as str (body decoded with raw=False). The table is
    recalculated from the actual layout of the re-packed body.

    Does not reproduce the original blob byte-for-byte (POD Go Edit uses
    non-minimal encodings for some integers), but it is a semantically
    equivalent, well-formed container.
    """
    body_packed = msgpack.packb(body, use_single_float=True)
    magic_packed = bytes((0xA0 | len(MAGIC),)) + MAGIC  # fixstr, len(MAGIC)=9
    table_bytes = _BLOB_TABLE_LEN * 4
    # body_start = magic + (str16 header: 0xda + 2B len) + table
    body_start = len(magic_packed) + 3 + table_bytes
    blob_end = body_start + len(body_packed)
    keypos = _toplevel_key_offsets(body)
    table = [body_start]
    for key in _BLOB_TABLE_KEYS:
        table.append(body_start + keypos[key] if key in keypos else blob_end)
    table += [blob_end, blob_end]
    raw_table = struct.pack(f"<{len(table)}I", *table)
    table_packed = bytes((0xDA,)) + struct.pack(">H", len(raw_table)) + raw_table
    return magic_packed + table_packed + body_packed


# --- Blob body keys (table "blob ↔ .pgp mapping" in lab-notes) ---

BODY_DSP0 = 0          # {21: idx_dsp, 22: [chain entries]}
BODY_FOOTSWITCH = 3    # footswitch assignments (not yet decoded)
BODY_CONTROLLER = 4    # controller assignments (not yet decoded)
BODY_GLOBAL = 5        # {16: tempo, ...}
BODY_META = 7          # {35: device_version, 36: product, 37: firmware}
BODY_SNAPSHOTS = 10    # {6: current, 10: [4 snapshots], ...}

DSP_CHAIN = 22
GLOBAL_TEMPO = 16
META_PRODUCT = 36
META_FIRMWARE = 37

# Chain entries: {19: class, 20: payload}.
ENTRY_CLASS = 19
ENTRY_PAYLOAD = 20
CLASS_INPUT = 0
CLASS_OUTPUT = 1
CLASS_BLOCK = 6
CLASS_EMPTY = 8

# Processing block body.
BLK_CATEGORY = 9       # 1=FX, 8=delay, 9=fx loop, 15=cab, 17=amp, 23=static EQ
BLK_ENABLED = 10
BLK_PARAMS = 11        # {2: n_total, 3: n_snapshoteables, 4: [valores]}
BLK_MODEL = 24         # {23: no_snapshot_bypass, 25: model id, 26: -1}
MODEL_NO_SNAPSHOT_BYPASS = 23
MODEL_ID = 25
MODEL_UNKNOWN_26 = 26  # always -1 in observed data
PARAMS_TOTAL = 2
PARAMS_SNAPSHOTTABLE = 3
PARAMS_VALUES = 4
IO_PARAMS = 7          # input/output carry their params in key 7
IO_INPUT_SETTING = 5   # ↔ `@input` in the .pgp
IO_OUTPUT_SETTING = 6  # ↔ `@output` in the .pgp

# Snapshots.
SNAP_VALID = 0
SNAP_ENABLES = 3       # 12 × [?, enabled] per slot: [input, 10 blocks, output]
SNAP_NAME = 4
SNAP_TEMPO = 5
SNAPS_CURRENT = 6
SNAPS_LIST = 10


@dataclass
class Block:
    """A processing block in the chain (params in model order)."""

    model_id: int
    category: int
    enabled: bool
    params: list
    no_snapshot_bypass: bool = False


@dataclass
class Snapshot:
    name: str
    valid: bool
    tempo: float
    #: Per-chain-slot state: [input, 10 blocks, output] (12 bools).
    enables: list[bool] = field(default_factory=list)


@dataclass
class Preset:
    """Decoded active preset from the l6-helix container.

    `chain` is the 10 processing slots in order (= `@position` of the
    .pgp); `None` is an empty slot. `body` preserves the complete
    MessagePack map (keys 2/3/4/6 and footswitch/controller remain
    undecoded).
    """

    chain: list[Block | None]
    input_params: list
    output_params: list
    tempo: float | None
    current_snapshot: int
    snapshots: list[Snapshot]
    product: str
    firmware: str
    body: dict


def parse_blob(blob: bytes) -> Preset:
    """Decode a complete l6-helix blob into a `Preset`."""
    _, body_bytes = split_container(blob)
    body = msgpack.unpackb(body_bytes, raw=False, strict_map_key=False)
    return parse_body(body)


def _normalize(value):
    """Canonical form of a body value for comparing two blobs.

    Stabilizes map key order and collapses float representation to float32
    precision (all wire data is f32; on re-serialization, the same value
    may appear with different repr). This way comparison does not flag
    "edited" from ordering/encoding noise, only from real content changes.
    """
    if isinstance(value, dict):
        return {k: _normalize(value[k]) for k in sorted(value, key=repr)}
    if isinstance(value, (list, tuple)):
        return [_normalize(v) for v in value]
    if isinstance(value, float):
        return struct.unpack("<f", struct.pack("<f", value))[0]
    if isinstance(value, bytes):
        return value.rstrip(b"\x00")
    return value


def blobs_equal_normalized(a: bytes, b: bytes) -> bool:
    """Do two l6-helix blobs represent the SAME preset, after normalization?

    Compares decoded MessagePack bodies with stable key order and float
    precision f32 (see `_normalize`); ignores the container's offset table
    (it is derived from the body) and string padding. Falls back to raw
    byte equality on unreadable blobs.

    STATUS (spec 06, Task 1) — PRIMITIVE PREPARED, not yet connected. It
    is the fallback of the "compare active blob vs stored blob" path in
    edited detection (`device.PodGo.active_preset_is_edited`). Not
    connectable today because there is no vendor object that reads the
    complete blob of a STORED slot without recall (recall would reset the
    "●"); so that detection goes through the object 14 seal, not blobs.
    Will be connected when the RE item "read stored blob of a slot without
    recall" is closed. See docs/specs/06-lab-notes.md.

    NOTE: which blob fields are volatile at runtime (timestamps? seals?)
    can only be confirmed with the pedal — see docs/specs/06-lab-notes.md.
    """
    if a == b:
        return True
    try:
        _, body_a = split_container(a)
        _, body_b = split_container(b)
        da = msgpack.unpackb(body_a, raw=False, strict_map_key=False)
        db = msgpack.unpackb(body_b, raw=False, strict_map_key=False)
    except Exception:
        return a == b
    return _normalize(da) == _normalize(db)


def parse_body(body: dict) -> Preset:
    """Build a `Preset` from the already-decoded body (mutable)."""
    chain: list[Block | None] = []
    input_params: list = []
    output_params: list = []
    for entry in body[BODY_DSP0][DSP_CHAIN]:
        cls = entry[ENTRY_CLASS]
        payload = entry[ENTRY_PAYLOAD]  # None for CLASS_EMPTY; not used in that branch
        if cls == CLASS_INPUT:
            input_params = list(payload[IO_PARAMS][PARAMS_VALUES])
        elif cls == CLASS_OUTPUT:
            output_params = list(payload[IO_PARAMS][PARAMS_VALUES])
        elif cls == CLASS_EMPTY:
            chain.append(None)
        elif cls == CLASS_BLOCK:
            model = payload[BLK_MODEL]
            chain.append(
                Block(
                    model_id=model[MODEL_ID],
                    category=payload[BLK_CATEGORY],
                    enabled=bool(payload[BLK_ENABLED]),
                    params=list(payload[BLK_PARAMS][PARAMS_VALUES]),
                    no_snapshot_bypass=bool(
                        model.get(MODEL_NO_SNAPSHOT_BYPASS, False)
                    ),
                )
            )
        else:
            raise ValueError(f"chain entry with unknown class: {cls!r}")

    snaps_node = body.get(BODY_SNAPSHOTS) or {}
    snapshots = [
        Snapshot(
            name=text(s[SNAP_NAME]),
            valid=bool(s[SNAP_VALID]),
            tempo=s[SNAP_TEMPO],
            enables=[bool(pair[1]) for pair in s[SNAP_ENABLES]],
        )
        for s in snaps_node.get(SNAPS_LIST, [])
    ]

    meta = body.get(BODY_META) or {}
    glob = body.get(BODY_GLOBAL) or {}
    return Preset(
        chain=chain,
        input_params=input_params,
        output_params=output_params,
        tempo=glob.get(GLOBAL_TEMPO),
        current_snapshot=snaps_node.get(SNAPS_CURRENT, 0),
        snapshots=snapshots,
        product=text(meta.get(META_PRODUCT, "")),
        firmware=text(meta.get(META_FIRMWARE, "")),
        body=body,
    )
