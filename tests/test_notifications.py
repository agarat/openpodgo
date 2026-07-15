"""Tests for the notification parser (event channel 0x03F0 → 0x1002)."""

import msgpack

from openpodgo.notifications import NOTIF_DST, NOTIF_SRC, parse_notification


def _notif(body_dict: dict, src: int = NOTIF_SRC, dst: int = NOTIF_DST) -> bytes:
    """Builds a framed vendor packet with the body at offset 24.

    Replicates the framing of `packets.build_vendor_*`: 16-byte header (byte 0 =
    16+len, src/dst LE at 4:8), subheader, len LE at 20:22 and the MessagePack
    at 24, with padding to a multiple of 4.
    """
    body = msgpack.packb(body_dict, use_single_float=True)
    pad = (-len(body)) % 4
    pkt = bytearray(16)
    pkt[0] = (16 + len(body)) & 0xFF
    pkt[3] = 0x18
    pkt[4:6] = src.to_bytes(2, "little")
    pkt[6:8] = dst.to_bytes(2, "little")
    pkt += bytes((0x00, 0x00, 0x06, 0x00))  # subheader (device packet)
    pkt += len(body).to_bytes(2, "little") + b"\x00\x00"
    pkt += body + b"\x00" * pad
    return bytes(pkt)


def test_set_param():
    raw = _notif({105: 30, 106: {82: 0, 68: 6, 121: 20,
                                 106: {98: 3, 29: True, 26: 5, 28: 0, 119: 0.5}}})
    ev = parse_notification(raw)
    assert ev["type"] == "set_param"
    assert ev["data"]["block"] == 3
    assert ev["data"]["param"] == 5
    assert abs(ev["data"]["value"] - 0.5) < 1e-6


def test_snapshot():
    raw = _notif({105: 42, 106: {92: 2}})
    assert parse_notification(raw) == {"type": "snapshot", "data": {"snapshot": 2}}


def test_snapshot_variant_b():
    raw = _notif({105: 46, 106: {92: 3}})
    assert parse_notification(raw) == {"type": "snapshot", "data": {"snapshot": 3}}


def test_chain_changed():
    # The pedal emits op 21 (body None) when reordering/altering the chain.
    raw = _notif({105: 21, 106: None})
    assert parse_notification(raw) == {"type": "chain_changed", "data": {}}


def test_fs_assign_changed():
    # Bypass assignment changed on the pedal (opcode 31).
    raw = _notif({105: 31, 106: {98: 8, 70: 2, 79: True}})
    ev = parse_notification(raw)
    assert ev["type"] == "assignment_changed"
    assert ev["data"]["block"] == 8
    assert ev["data"]["fs"] == 2


def test_controller_assign_changed():
    # Controller changed on the pedal (opcode 34).
    raw = _notif({105: 34, 106: {74: 1, 71: 4, 65: 0, 98: 2,
                                 72: 0.0, 73: 1.0, 59: False}})
    ev = parse_notification(raw)
    assert ev["type"] == "assignment_changed"
    assert ev["data"]["controller"] == 1
    assert ev["data"]["block"] == 2


def test_bypass():
    raw = _notif({105: 39, 106: {82: 1, 68: 3, 121: 19, 106: {98: 8, 26: 0}}})
    assert parse_notification(raw) == {
        "type": "bypass", "data": {"block": 8, "param": 0}}


def test_bypass_state_explicito():
    # op 49 carries the ABSOLUTE enabled state (key 59): this is how the wah
    # is reflected (#6) and it doesn't bounce when the change originated in the app.
    raw = _notif({105: 49, 106: {82: 0, 68: 5, 121: 17,
                                 106: {98: 3, 59: True}}})
    assert parse_notification(raw) == {
        "type": "bypass_state", "data": {"block": 3, "enabled": True}}
    raw_off = _notif({105: 49, 106: {82: 0, 68: 5, 121: 17,
                                     106: {98: 2, 59: False}}})
    assert parse_notification(raw_off) == {
        "type": "bypass_state", "data": {"block": 2, "enabled": False}}


def test_op49_sin_clave_59_se_ignora():
    # op 49 also accompanies a model change (without key 59): not a bypass.
    raw = _notif({105: 49, 106: {82: 0, 68: 5, 121: 17,
                                 106: {98: 5, 70: 4}}})
    assert parse_notification(raw) is None


def test_op49_reorden_en_pedal_es_chain_changed():
    # op 49 with {75: from, 76: to} = reorder done ON the pedal (does not send
    # op 21). Validated live: arrives in bursts of adjacent shifts.
    raw = _notif({105: 49, 106: {82: 0, 68: 5, 121: 13,
                                 106: {75: 2, 76: 3}}})
    assert parse_notification(raw) == {
        "type": "chain_changed", "data": {"from_slot": 2, "to_slot": 3}}


def test_preset_loaded():
    raw = _notif({105: 8, 106: {82: 1, 68: 1, 121: 5, 106: {107: 1, 108: 7}}})
    assert parse_notification(raw) == {
        "type": "preset_loaded", "data": {"setlist": 1, "slot": 7}}


def test_tempo():
    raw = _notif({105: 22, 106: {82: 0, 68: 9, 121: 25, 106: {118: 16, 119: 120.0}}})
    ev = parse_notification(raw)
    assert ev["type"] == "tempo"
    assert ev["data"]["param_id"] == 16
    assert abs(ev["data"]["value"] - 120.0) < 1e-3


def test_preset_name():
    raw = _notif({105: 6, 106: {106: {107: 0, 108: 2, 109: "Crunch\x00"}}})
    assert parse_notification(raw) == {
        "type": "preset_name",
        "data": {"setlist": 0, "slot": 2, "name": "Crunch"}}


def test_wrong_channel_is_ignored():
    # Packet from the read channel (0x03EF) — not an event notification.
    raw = _notif({105: 30, 106: {}}, src=0x03EF, dst=0x1001)
    assert parse_notification(raw) is None


def test_unknown_opcode_returns_none():
    raw = _notif({105: 99, 106: {}})
    assert parse_notification(raw) is None


def test_too_short_returns_none():
    assert parse_notification(b"\x00" * 8) is None


def test_garbage_body_returns_none():
    # Correct channel but non-MessagePack body: must not crash.
    pkt = bytearray(28)
    pkt[4:6] = NOTIF_SRC.to_bytes(2, "little")
    pkt[6:8] = NOTIF_DST.to_bytes(2, "little")
    pkt[24:28] = b"\xff\xff\xff\xff"
    assert parse_notification(bytes(pkt)) is None
