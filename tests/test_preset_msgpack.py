"""Tests for parsing presets with device-style bytes.

POD Go encodes map keys as MessagePack uint16 (e.g. key 109 as `cd 00 6d`),
not with the minimal fixint. That's why the parser scans by pattern instead
of relying on a standard decode.
"""

from pathlib import Path

from openpodgo import preset


def _entry(index: int, name: str) -> bytes:
    """Builds a preset entry as emitted by the device:
    `81 cd HI LO 84 cd 00 6d <fixstr name\\0> 7b c2 7c c2 7d 00`."""
    raw_name = (name + "\x00").encode("utf-8")
    assert len(raw_name) < 32, "use short names in tests"
    strhdr = bytes((0xA0 | len(raw_name),))  # fixstr
    return (
        bytes((0x81, 0xCD, (index >> 8) & 0xFF, index & 0xFF))  # outer map {index:
        + bytes((0x84, 0xCD, 0x00, 0x6D))                        # inner map, key 109
        + strhdr + raw_name                                      # name\0
        + bytes((0x7B, 0xC2, 0x7C, 0xC2, 0x7D, 0x00))            # keys 123/124/125
    )


def _factory_stream(names):
    preamble = bytes.fromhex("00112233445566") + b"\xdc\x00\x80"
    return preamble + b"".join(_entry(i, n) for i, n in enumerate(names))


def _user_stream(names):
    # The User setlist does not include the DC 00 80 marker and its indices are 128+.
    return b"\x99\x88\x77" + b"".join(_entry(128 + i, n) for i, n in enumerate(names))


def test_scan_factory_indices_and_names():
    names = [f"Preset {i:02d}" for i in range(10)]
    entries = preset.scan_preset_entries(_factory_stream(names))
    assert len(entries) == 10
    assert entries[0] == (0, "Preset 00")  # no \0 or spaces
    assert entries[9] == (9, "Preset 09")


def test_parse_preset_list_assigns_slots_in_stream_order():
    names = ["Bravo", "Alpha", "Charlie"]
    raw = _factory_stream(names)
    out = preset.parse_preset_list(raw)
    assert [e.slot for e in out] == [0, 1, 2]
    assert [e.index for e in out] == [0, 1, 2]
    assert [e.name for e in out] == ["Bravo", "Alpha", "Charlie"]


def test_parse_user_stream_without_marker():
    # Must work even when there is NO DC 00 80 marker (User setlist case).
    out = preset.parse_preset_list(_user_stream(["miTono", "otro"]))
    assert [e.index for e in out] == [128, 129]
    assert [e.slot for e in out] == [0, 1]
    assert out[0].name == "miTono"


def test_slot_is_stream_position_not_index():
    # In the User setlist the index is a stable ID that does NOT match the
    # slot when the user reorders presets: the slot is the position in the
    # stream. Real case: id 129 relocated between 164 and 165.
    raw = b"\x00" + _entry(139, "Preset Two") + _entry(129, "movido") + _entry(140, "otro")
    out = preset.parse_preset_list(raw)
    assert [(e.slot, e.index, e.name) for e in out] == [
        (0, 139, "Preset Two"),
        (1, 129, "movido"),
        (2, 140, "otro"),
    ]


def test_parse_empty_raises():
    try:
        preset.parse_preset_list(b"\x00\x01\x02 no entries")
    except ValueError as exc:
        assert "entries" in str(exc)
    else:
        raise AssertionError("should have failed with no entries")


def test_parse_real_user_capture():
    """Regression against a real User-setlist dump (POD Go 0e41:4247).

    The dump is a captured User setlist with every preset name replaced by a
    neutral placeholder (see tools that build tests/fixtures). The structure is
    intact: the first presets (ids 128-138) arrive in the OPEN_STREAM response,
    and id 129 is reordered to slot 36 (10A) — the slot/index divergence is the
    property under test, independent of the (sanitized) names.
    """
    fixture = Path(__file__).parent / "fixtures" / "user_setlist.bin"
    out = preset.parse_preset_list(fixture.read_bytes())
    assert len(out) == 128
    assert [e.slot for e in out] == list(range(128))
    assert (out[0].index, out[0].name) == (128, "Preset 000")
    assert (out[9].index, out[9].name) == (138, "Preset 008")
    assert out[10].index == 139
    assert (out[36].index, out[36].name) == (129, "Preset 033")


def test_pgp_roundtrip(tmp_path):
    data = {"data": {"meta": {"name": "Mi Tono"}}, "schema": "L6Preset"}
    p = tmp_path / "tono.pgp"
    preset.save_pgp(data, p)
    assert preset.load_pgp(p) == data


def test_parse_active_state():
    # Real shape of the object 23 result (lab-notes Task 4): with raw=True
    # strings arrive as NUL-terminated bytes.
    result = {107: 1, 108: 9, 109: b"BassPreset\x00", 117: True}
    state = preset.parse_active_state(result)
    assert (state.setlist, state.slot, state.name) == (1, 9, "BassPreset")
    # `edited` is for the future: currently stays None (key 117 is discarded, spec 06).
    assert state.edited is None


def test_parse_slot_checksums_real_capture():
    """Object 14 decodes to 128 slot→crc32 entries (spec 06).

    Real capture from POD Go (captures/spec02_obj14.bin): key 104 = array of
    maps {slot: u32}. This is the cheap comparand for edited detection.
    """
    buf = (Path(__file__).parent / "fixtures" / "spec02_obj14.bin").read_bytes()
    sums = preset.parse_slot_checksums(buf)
    assert len(sums) == 128
    assert set(sums) == set(range(128))
    # slots with a preset carry a u32; empty ones arrive as None.
    assert all(v is None or 0 <= v <= 0xFFFFFFFF for v in sums.values())
    assert sums[0] == 2580378960  # first slot in the capture
    assert sums[119] is None      # empty slot in the capture


def test_parse_slot_checksums_tolera_basura():
    import msgpack

    buf = msgpack.packb({102: 1, 103: 0, 104: [{0: 111}, "x", {1: 2, 3: 4}, {5: 6}]})
    assert preset.parse_slot_checksums(buf) == {0: 111, 5: 6}
