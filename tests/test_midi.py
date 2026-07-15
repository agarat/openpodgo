import openpodgo.midi as midi


class FakeMidi(midi.MidiOut):
    """MidiOut that captures bytes instead of calling amidi."""

    def __init__(self):
        self.port = "hw:test"
        self.sent = []

    def _send(self, *data):
        self.sent.append(tuple(b & 0xFF for b in data))


def test_program_change_message():
    m = FakeMidi()
    m.program_change(5)
    assert m.sent == [(0xC0, 5)]


def test_program_change_range():
    m = FakeMidi()
    for bad in (-1, 128):
        try:
            m.program_change(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("should have rejected out of 0-127")


def test_snapshot_and_footswitch():
    m = FakeMidi()
    m.snapshot(2)
    m.footswitch(3, on=True)
    m.footswitch(3, on=False)
    assert m.sent == [
        (0xB0, midi.CC_SNAPSHOT, 2),
        (0xB0, midi.CC_FS_BASE + 2, 127),
        (0xB0, midi.CC_FS_BASE + 2, 0),
    ]
