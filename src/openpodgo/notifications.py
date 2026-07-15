"""Notification receiver for the event channel 0x03F0 → 0x1002.

When the user interacts with the POD Go directly (knobs, footswitches,
snapshot, preset change) the device emits *unsolicited* notifications on the
`0x03F0 → 0x1002` channel. The body is MessagePack with the shape
`{105: opcode, 106: data}`. This module provides:

- `parse_notification(raw)` — decodes a raw packet to a structured event dict.
- `NotificationReader` — a QThread that reads the IN endpoint in the background
  and emits each parsed event via the `event` signal.

The framing (MessagePack offset within the vendor packet) is not fixed across
device responses: some come "framed" (subheader + len, the body starts at
offset 24) and others are raw windows (the body starts at 16). That is why
`parse_notification` tries several offsets and picks the one that produces a
dict with key 105. The opcodes/fields come from analysis of POD Go Edit
captures; unknown ones are logged as integers at INFO level so they can be
mapped against the real pedal.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable

import msgpack
from PySide6.QtCore import QThread, Signal

log = logging.getLogger(__name__)

#: Device event channel (src → dst, little-endian in the packet).
NOTIF_SRC = 0x03F0
NOTIF_DST = 0x1002

# Notification opcodes (body key 105).
OP_PRESET_SAVED = 4       # {107: setlist, 108: slot}
OP_PRESET_LOADED = 8      # {107: setlist, 108: slot}
OP_PRESET_NAME = 6        # {107: setlist, 108: slot, 109: name}
OP_TEMPO = 22             # {118: param_id, 119: value}
OP_SET_PARAM = 30         # {98: block, 26: param, 28: 0, 29: True, 119: value}
OP_BYPASS = 39            # {98: block, 26: param}  (toggle, sin valor)
OP_BLOCK_STATE = 49       # {98: block, 59: enabled}  (ABSOLUTE block state)
OP_SNAPSHOT_A = 42        # {92: idx}
OP_SNAPSHOT_B = 46        # {92: idx}  (segunda variante observada)
OP_CHAIN_CHANGED = 21     # chain reordered/altered (106: None). Same opcode
#: as write op 21 (dump chain): the pedal emits it as a notification when
#: the chain changes (validated in change-pedal-order-from-app.pcapng,
#: where the pedal echoes it after the write).
OP_FS_ASSIGN = 31         # bypass assignment changed: {98: block, 70: fs, 79: enabled}
OP_CTRL_ASSIGN = 34       # controller changed: {74: ctrl, 98: block, 72: min, 73: max, ...}
#: 31 and 34 are emitted by the pedal (also as an echo of our op 21) when a
#: footswitch/controller assignment changes; the consumer re-reads the preset.

#: Candidate offsets of the MessagePack body within the vendor packet.
_BODY_OFFSETS = (24, 16, 20)


def _decode_body(raw: bytes) -> dict | None:
    """Extracts the MessagePack dict from the packet, trying several offsets.

    Uses a streaming Unpacker to tolerate the 4-byte-aligned padding that
    follows the body (a direct `unpackb` would fail with ExtraData). Picks the
    first offset that yields a dict with key 105 (opcode).
    """
    for off in _BODY_OFFSETS:
        if off >= len(raw):
            continue
        try:
            unpacker = msgpack.Unpacker(strict_map_key=False, raw=False)
            unpacker.feed(raw[off:])
            obj = unpacker.unpack()
        except Exception:
            continue
        if isinstance(obj, dict) and 105 in obj:
            return obj
    return None


def parse_notification(raw: bytes) -> dict | None:
    """Decodes a packet from channel 0x03F0 to a structured event dict.

    Returns None if the packet is not a valid notification from the event
    channel or if the opcode is unknown. The event dict has the shape
    `{"type": str, "data": dict}`.
    """
    if len(raw) < 16:
        return None
    src = int.from_bytes(raw[4:6], "little")
    dst = int.from_bytes(raw[6:8], "little")
    if src != NOTIF_SRC or dst != NOTIF_DST:
        return None

    body = _decode_body(raw)
    if body is None:
        return None

    opcode = body.get(105)
    payload = body.get(106, {})
    if not isinstance(payload, dict):
        payload = {}
    # The outer payload carries metadata (82: source, 68, 121: len) and the
    # actual data nested under another key 106; if missing, the payload is
    # the data itself.
    inner = payload.get(106, payload)
    if not isinstance(inner, dict):
        inner = {}

    if opcode == OP_SET_PARAM:
        return {"type": "set_param", "data": {
            "block": inner.get(98),
            "param": inner.get(26),
            "value": inner.get(119),
        }}
    if opcode == OP_BYPASS:
        return {"type": "bypass", "data": {
            "block": inner.get(98),
            "param": inner.get(26),
        }}
    if opcode == OP_BLOCK_STATE and (75 in inner or 76 in inner):
        # op 49 OVERLOADED: with {75: from_slot, 76: to_slot} it is a
        # reorder done ON the pedal (it does not send op 21, that is only
        # the echo of OUR write). Arrives in bursts of adjacent shifts; the
        # consumer re-reads the chain (with debounce). Validated live.
        return {"type": "chain_changed", "data": {
            "from_slot": inner.get(75),
            "to_slot": inner.get(76),
        }}
    if opcode == OP_BLOCK_STATE and 59 in inner:
        # ABSOLUTE block state (key 59 = enabled). The pedal emits this when
        # toggling bypass from the hardware and, crucially, when stepping on
        # the wah toe (which does NOT send OP_BYPASS). This is the authoritative
        # source for enabled: it carries the explicit value, so no "toggle" is
        # needed and there is no bounce when the change originated in the app
        # (#6 + bypass flicker).
        return {"type": "bypass_state", "data": {
            "block": inner.get(98),
            "enabled": bool(inner.get(59)),
        }}
    if opcode in (OP_SNAPSHOT_A, OP_SNAPSHOT_B):
        return {"type": "snapshot", "data": {
            "snapshot": inner.get(92),
        }}
    if opcode == OP_CHAIN_CHANGED:
        # Structural chain change (reorder/add/remove block) done on the pedal.
        # The body is None: the consumer re-reads the active preset.
        return {"type": "chain_changed", "data": {}}
    if opcode in (OP_FS_ASSIGN, OP_CTRL_ASSIGN):
        # Bypass/controller assignment changed on the pedal (or echo of our
        # op 21). The consumer re-reads the active preset to reflect it.
        return {"type": "assignment_changed", "data": {
            "block": inner.get(98),
            "fs": inner.get(70),
            "controller": inner.get(74),
        }}
    if opcode == OP_PRESET_LOADED:
        return {"type": "preset_loaded", "data": {
            "setlist": inner.get(107),
            "slot": inner.get(108),
        }}
    if opcode == OP_PRESET_SAVED:
        return {"type": "preset_saved", "data": {
            "setlist": inner.get(107),
            "slot": inner.get(108),
        }}
    if opcode == OP_PRESET_NAME:
        name = inner.get(109, "")
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        return {"type": "preset_name", "data": {
            "setlist": inner.get(107),
            "slot": inner.get(108),
            "name": name.rstrip("\x00"),
        }}
    if opcode == OP_TEMPO:
        return {"type": "tempo", "data": {
            "param_id": inner.get(118),
            "value": inner.get(119),
        }}

    log.info("Notification with unknown opcode=%s body=%s", opcode, body)
    return None


class NotificationReader(QThread):
    """Polls the pedal's event channel and emits each notification via `event`.

    The vendor protocol is polled: this thread calls `poll_fn()` (which sends a
    keepalive cmd=0x10 to the event channel and reads the response, coordinating
    the transport lock with Workers) in a loop with a short pause between
    cycles. `poll_fn` returns the raw frame of an event or None. It is
    explicitly paused/resumed (`pause()`/`resume()`) to avoid polling during
    app operations.
    """

    event = Signal(dict)  # parsed notification → main thread

    #: Pause between polls when no event was received (ms). Keeps detection
    #: latency low without saturating the endpoint.
    POLL_INTERVAL_MS = 30

    def __init__(self, poll_fn: Callable[[], list[bytes]], parent=None) -> None:
        super().__init__(parent)
        self._poll_fn = poll_fn
        self._allowed = threading.Event()  # set = can poll; starts paused
        self._stopped = threading.Event()

    def run(self) -> None:
        while not self._stopped.is_set():
            self._allowed.wait()
            if self._stopped.is_set():
                break
            try:
                frames = self._poll_fn()
            except Exception:  # noqa: BLE001 — a poll failure must not kill the thread
                log.exception("event channel poll failed")
                frames = []
            if not frames:
                self.msleep(self.POLL_INTERVAL_MS)
                continue
            for data in frames:
                try:
                    ev = parse_notification(data)
                except Exception:  # noqa: BLE001 — a malformed packet must not kill the thread
                    log.exception("parse_notification failed on %s", data[:32].hex())
                    continue
                if ev:
                    self.event.emit(ev)

    def pause(self) -> None:
        """Stops polling until the next `resume()`."""
        self._allowed.clear()

    def resume(self) -> None:
        """Resumes polling."""
        self._allowed.set()

    def stop(self) -> None:
        """Terminates the thread permanently."""
        self._stopped.set()
        self._allowed.set()  # unblocks wait() so that run() can exit
