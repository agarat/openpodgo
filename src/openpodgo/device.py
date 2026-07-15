"""High-level API for communicating with the POD Go.

Encapsulates transport + session + preset operations into a simple
interface for the UI and scripts. Designed to grow toward full preset
content reading and writing (Phases 3-4).
"""

from __future__ import annotations

import logging
import zlib

from . import l6helix
from . import packets
from . import preset
from .preset import PresetEntry
from .session import EventSession, Session, WriteSession
from .usb_transport import DeviceInfo, UsbTransport

log = logging.getLogger(__name__)

#: Is the object 14 checksum formula CONFIRMED live?
#:
#: Object 14 carries a u32 per slot (the stored content "seal"). To
#: detect edited we compare that seal with the active blob's (object 22).
#: The problem is that we DON'T know what algorithm/region the pedal uses
#: for that u32: offline, `zlib.crc32` over the object 22 blob (raw,
#: body-only, reconstructed with build_blob) does NOT match ANY of the 120
#: non-empty slots in `captures/spec02_obj14.bin` (Finding A of the
#: review). In other words, crc32-over-blob is RULED OUT as the object 14
#: formula.
#:
#: While this is False, `active_preset_is_edited` does NOT risk a false
#: positive: it returns False (never shows a spurious "●") and logs that
#: detection is pending RE on live. The day the pedal capture reveals the
#: real formula (algorithm/seed/region), `_blob_crc_for_obj14` is adjusted
#: and this constant is set to True to enable the comparison.
#:
#: See docs/specs/06-lab-notes.md ("Finding A" and "What remains to capture").
_OBJ14_CRC_CONFIRMED = False

_tx_counter = 1000


def _write_tx_id() -> int:
    global _tx_counter
    _tx_counter += 1
    return _tx_counter


def _write_ok(resp: bytes) -> bool:
    body = packets.decode_open_body(resp)
    if isinstance(body, dict):
        return body.get(103) == 0
    return False


def _blob_crc_for_obj14(active_blob: bytes) -> int:
    """Active blob seal in the object 14 format (HYPOTHESIS, not confirmed).

    Currently implements ``zlib.crc32`` over the raw object 22 blob.
    WARNING: this formula is RULED OUT offline (Finding A: does not match
    any slot in `captures/spec02_obj14.bin`); kept as the single point to
    fix when the live pedal capture reveals the real algorithm/seed/region.
    Only used when `_OBJ14_CRC_CONFIRMED` is True. See docs/specs/06-lab-notes.md.
    """
    return zlib.crc32(active_blob) & 0xFFFFFFFF


def _crc_says_edited(active_blob: bytes, stored_crc: int) -> bool:
    """PURE comparison helper: does the active blob seal differ from the stored one?

    Isolated from USB so it can be tested directly. Only reliable when
    `_OBJ14_CRC_CONFIRMED` is True (see `_blob_crc_for_obj14`).
    """
    return _blob_crc_for_obj14(active_blob) != stored_crc


def _chain_write_ok(resp: bytes) -> bool:
    """Chain write status (op 21).

    Unlike set_param/save (echo ``103: 0``), the chain dump the pedal
    applies responds ``{102: tx, 103: 1, 104: None}`` (validated against
    change-pedal-order-from-app.pcapng and live: the reorder applies and
    the echo carries ``103: 1``). We accept 0 or 1 as applied; anything
    else is a failure.
    """
    body = packets.decode_open_body(resp)
    if isinstance(body, dict):
        return body.get(103) in (0, 1)
    return False


class PodGo:
    """Connected POD Go device with application session open."""

    def __init__(self) -> None:
        self._transport = UsbTransport()
        self._session: Session | None = None
        self._write_session: WriteSession | None = None
        self._event_session: EventSession | None = None
        self._info: DeviceInfo | None = None
        self._read_since_write = False

    @property
    def info(self) -> DeviceInfo | None:
        return self._info

    @property
    def connected(self) -> bool:
        return self._session is not None and self._session.is_open

    def connect(self) -> DeviceInfo:
        """Open USB and execute the handshake. Returns the pedal identity."""
        self._info = self._transport.open()
        self._session = Session(self._transport)
        self._session.handshake()
        log.info("Connected to %s", self._info)
        return self._info

    def list_setlists(self) -> list[str]:
        """Names of the pedal setlists (e.g. ["Factory", "User"])."""
        self._require_session()
        self._read_since_write = True
        return preset.read_setlists(self._session)

    def list_presets(self, setlist: int = 0) -> list[PresetEntry]:
        """Read and return the 128 presets of the given setlist (0=Factory, 1=User)."""
        self._require_session()
        self._read_since_write = True
        stream = preset.stream_presets(self._session, setlist=setlist)
        return preset.parse_preset_list(stream.raw)

    def active_state(self) -> preset.ActiveState:
        """Setlist/slot/name of the active preset (object 23)."""
        self._require_session()
        self._read_since_write = True
        return preset.read_active_state(self._session)

    def active_preset(self) -> l6helix.Preset:
        """Full content of the active preset (object 22, l6-helix)."""
        self._require_session()
        self._read_since_write = True
        return preset.read_active_preset(self._session)

    def active_preset_is_edited(self) -> bool:
        """Is the active preset edited-unsaved (the pedal's "●")?

        DETECTION BY COMPARISON, encapsulated here to avoid leaking logic to
        the UI (spec 06, Task 1). The architecturally correct path is object
        14 (per-slot fingerprint): compare the stored seal of the active slot
        with the active blob's seal (object 22). We CANNOT compare blob vs
        stored blob because there is no vendor object that reads the complete
        blob of a STORED slot without recall (recall would reset the "●"
        state); see the object map in docs/specs/02-lab-notes.md. That's why
        object 14 is the comparison path, not `l6helix.blobs_equal_normalized`
        (that stays as a primitive prepared for the day a slot read exists).

        BEING HONEST — the object 14 formula is NOT confirmed:
        `zlib.crc32` over the object 22 blob does not match any slot in the
        captures (Finding A; see docs/specs/06-lab-notes.md). While
        `_OBJ14_CRC_CONFIRMED` is False this method does NOT risk a false
        positive: it always returns False (never shows a spurious "●") and
        logs a message. The crc-vs-object-14 comparison is implemented but
        GATED behind that constant; the day the live capture reveals the
        algorithm, `_blob_crc_for_obj14` is adjusted and the constant set
        to True.

        Does not change the pedal's active preset (does NOT call change_preset).
        Same pattern as specs 03/05: API ready, wiring marked pending.
        """
        session = self._require_session()
        self._read_since_write = True
        if not _OBJ14_CRC_CONFIRMED:
            # Without the confirmed object 14 formula, any crc comparison
            # would yield confidently wrong false positives (Finding A).
            # Conservative: treat as NOT edited (never a spurious "●") without
            # spending USB reads.
            log.info(
                "active_preset_is_edited: detection pending live RE of the "
                "object 14 formula (Finding A); returning conservative False"
            )
            return False
        state = preset.read_active_state(session)
        checksums = preset.read_slot_checksums(session, setlist=state.setlist)
        active_blob = l6helix.extract_blob(
            preset.read_object(session, preset.OBJ_ACTIVE_PRESET)
        )
        stored = checksums.get(state.slot)
        if stored is None:
            # Slot without seal in the table: cannot compare (and there is no
            # stored blob read without recall). Conservative: not edited.
            log.info(
                "active_preset_is_edited: slot %d has no seal in object 14; "
                "returning conservative False",
                state.slot,
            )
            return False
        return _crc_says_edited(active_blob, stored)

    def disconnect(self) -> None:
        self._write_session = None
        self._event_session = None
        self._transport.close()
        self._session = None

    def open_event_channel(self) -> None:
        """Open the pedal event channel (Spec 04 live sync).

        After this, `poll_event()` receives notifications the pedal emits
        when the user touches it. Best-effort: if it fails, live sync is
        disabled but the rest of the app keeps working.
        """
        self._require_session()
        session = EventSession(self._transport)
        session.handshake()
        self._event_session = session

    def poll_event(self) -> list[bytes]:
        """Poll the event channel once (used by NotificationReader).

        Acquires the transport lock non-blocking to avoid stepping on a
        Worker in progress; returns the raw frames of pending events
        (empty list if none, lock busy, or channel closed).
        """
        session = self._event_session
        if session is None:
            return []
        lock = self._transport.lock
        if not lock.acquire(blocking=False):
            return []
        try:
            return session.poll()
        finally:
            lock.release()

    def _require_session(self) -> Session:
        if not self.connected:
            raise RuntimeError("Not connected; call connect() first")
        return self._session  # type: ignore[return-value]

    def write_connect(self) -> None:
        """Open the write channel (src=0x1080, dst=0x03ED) with its handshake."""
        self._require_session()
        self._write_session = WriteSession(self._transport)
        self._write_session.handshake()
        self._read_since_write = False
        log.info("Write channel opened (src=0x1080, dst=0x03ED)")

    def change_preset(self, setlist: int, slot: int) -> bool:
        """Switch to another preset. Uses the read channel (src=0x1001→0x03EF)."""
        session = self._require_session()
        seq = session.advance_seq()
        pkt = packets.build_vendor_open(
            packets.OPEN_PRESETS,
            {102: _write_tx_id(), 100: 1, 101: {107: setlist, 101: slot}},
            seq=seq,
        )
        try:
            session.transport.request(pkt)
        except Exception as exc:
            log.warning("change_preset: error (setlist=%d slot=%d): %s", setlist, slot, exc)
            return False
        return True

    def set_snapshot(self, idx: int) -> bool:
        """Switch to snapshot idx (0-3)."""
        ws = self._require_write_session()
        resp = ws.send_write({102: _write_tx_id(), 100: 88, 101: {92: idx}})
        return _write_ok(resp)

    def set_param(self, block_index: int, param_idx: int, value: float) -> bool:
        """Set a continuous parameter.

        block_index is the on-wire index (k101.98) = RAW index in DSP_CHAIN
        (input=0); see editor.block_index. param_idx travels in key 28 (key 26
        is constant 0): verified against the pedal — putting param_idx in key 26
        makes the device ACK with status 255 and NOT apply anything except
        param 0 (where both keys are 0 and the error goes unnoticed).

        If it fails, reconnects the write session and retries once.
        """
        for attempt in range(2):
            ws = self._require_write_session()
            resp = ws.send_write(
                {102: _write_tx_id(), 100: 30,
                 101: {98: block_index, 29: True, 26: 0, 28: param_idx, 119: value}}
            )
            ok = _write_ok(resp)
            if ok:
                log.info("set_param(blk=%d, idx=%d, val=%.4f) → True", block_index, param_idx, value)
                return True
            log.warning("set_param(blk=%d, idx=%d, val=%.4f) → attempt %d failed",
                        block_index, param_idx, value, attempt + 1)
            self._read_since_write = True  # force reconnect on retry
        log.info("set_param(blk=%d, idx=%d, val=%.4f) → False (after retry)", block_index, param_idx, value)
        return False

    def set_model(
        self, block_index: int, wire_id: int, no_snapshot_bypass: bool = False
    ) -> bool:
        """Change the model of the block at `block_index` to `wire_id` (#3).

        Vendor packet (op 40), RE from change-pedal-from-app.pcapng:
        ``{100: 40, 101: {98: block_index, 100: {23: no_snapshot_bypass,
        25: wire_id, 26: -1}}}``. The pedal loads the model with its defaults
        and notifies the change (op 49/31 with 79=True) via the event channel.

        Retries once with forced reconnect if the ACK fails.
        """
        for attempt in range(2):
            ws = self._require_write_session()
            resp = ws.send_write(
                {102: _write_tx_id(), 100: 40,
                 101: {98: block_index,
                       100: {23: no_snapshot_bypass, 25: wire_id, 26: -1}}}
            )
            ok = _write_ok(resp)
            if ok:
                log.info("set_model(blk=%d, wire_id=%d) → True", block_index, wire_id)
                return True
            log.warning("set_model(blk=%d, wire_id=%d) → attempt %d failed",
                        block_index, wire_id, attempt + 1)
            self._read_since_write = True  # force reconnect on retry
        log.warning("set_model(blk=%d, wire_id=%d) → False (after retry)",
                    block_index, wire_id)
        return False

    def write_chain_blob(self, blob: bytes, block_index: int | None = None) -> bool:
        """Dump the full chain to the pedal (op 21) — structural editing.

        Used when moving/adding/removing blocks: re-serializes the entire
        preset (``editor.to_blob()``) and pushes it fragmented via the write
        channel, ``{102: tx, 100: 21, 101: {110: blob}}``. RE from
        change-pedal-order-from-app.pcapng. The pedal applies the blob and
        notifies the new state via the event channel.

        The write session CANNOT be reused between dumps: after a chunked
        write the cursor/flow-control is desynced and the device ignores
        the next one without a re-handshake (the first attempt fails and
        only the retry, which reconnects, applies it). That's why we force
        a fresh session before each dump and get it right on the first try.

        Retries once with forced reconnect if the ACK fails anyway.
        """
        self._read_since_write = True  # force fresh write-handshake (see above)
        for attempt in range(2):
            ws = self._require_write_session()
            resp = ws.send_write_chunked(
                {102: _write_tx_id(), 100: 21, 101: {110: blob}}
            )
            ok = _chain_write_ok(resp)
            if ok:
                self._apply_edit(ws, block_index)
                log.info("write_chain_blob(%d B) → True", len(blob))
                return True
            log.warning("write_chain_blob(%d B) → attempt %d failed", len(blob), attempt + 1)
            self._read_since_write = True  # force reconnect on retry
        log.warning("write_chain_blob(%d B) → False (after retry)", len(blob))
        return False

    def save_preset(self, setlist: int, slot: int, name: str) -> bool:
        """Save the edit buffer to the indicated slot.

        Retries once with forced reconnect on failure (the write channel
        cursor can desync after previous writes).
        """
        for attempt in range(2):
            ws = self._require_write_session()
            resp = ws.send_write(
                {102: _write_tx_id(), 100: 71,
                 101: {107: setlist, 108: slot, 109: name + "\x00"}}
            )
            ok = _write_ok(resp)
            if ok:
                log.info("save_preset(setlist=%d, slot=%d, name=%r) → True", setlist, slot, name)
                return True
            log.warning("save_preset(setlist=%d, slot=%d, name=%r) → attempt %d failed",
                        setlist, slot, name, attempt + 1)
            self._read_since_write = True  # force reconnect on retry
        log.warning("save_preset(setlist=%d, slot=%d, name=%r) → False (after retry)", setlist, slot, name)
        return False

    def _apply_edit(self, ws: WriteSession, block_index: int | None = None) -> None:
        """Post-edit "apply/refresh" that POD Go Edit sends after an edit.

        RE from change-pedal-from-app.pcapng: after set_model (op 40), the
        official app sends op 33 ``{101: {102: block}}`` (refresh the edited
        block), op 23 ``{101: None}`` and op 22 ``{101: None}`` (commit +
        refresh of the buffer). Without this the pedal applies the data but
        does NOT refresh the footswitch/LED until the switch is toggled.
        Best-effort: if these fail, the write is not aborted.
        """
        if block_index is not None:
            try:
                ws.send_write(
                    {102: _write_tx_id(), 100: 33, 101: {102: block_index}}
                )
            except (RuntimeError, OSError) as exc:
                log.warning("_apply_edit op 33 failed: %s", exc)
        for op in (23, 22):
            try:
                ws.send_write({102: _write_tx_id(), 100: op, 101: None})
            except (RuntimeError, OSError) as exc:
                log.warning("_apply_edit op %d failed: %s", op, exc)

    def _require_write_session(self) -> WriteSession:
        if self._write_session is None or self._read_since_write:
            self.write_connect()
        return self._write_session  # type: ignore[return-value]

    def __enter__(self) -> "PodGo":
        self.connect()
        return self

    def __exit__(self, *exc) -> None:
        self.disconnect()
