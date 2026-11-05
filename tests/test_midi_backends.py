"""Tests for the per-OS MIDI backends and the backend selection.

Nothing here talks to hardware: the ALSA backend is driven with a captured
`amidi -l` listing and a fake `subprocess.run`, and the CoreMIDI backend with a
fake API, so the file also runs on Linux and macOS CI alike.
"""

from __future__ import annotations

import struct
import subprocess

import pytest

import openpodgo.midi as midi
import openpodgo.midi_alsa as alsa
import openpodgo.midi_coremidi as coremidi
from openpodgo import platform_support

#: Real `amidi -l` output (alsa-utils) with the pedal on card 2.
AMIDI_LISTING = """\
Dir Device    Name
IO  hw:1,0,0  Built-in Audio Analog Stereo
IO  hw:2,0,0  POD Go MIDI 1
"""


class FakeRun:
    """Stand-in for subprocess.run that records command lines."""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.calls: list[list[str]] = []
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        return subprocess.CompletedProcess(
            cmd, self.returncode, self.stdout, self.stderr
        )


class FakeAPI:
    """Stand-in for CoreMidiAPI, usable on any OS."""

    def __init__(self, names: tuple[str, ...] = ()) -> None:
        self.names = list(names)
        self.sent: list[tuple[str, bytes]] = []
        self.closed = False

    def destinations(self):
        return [(index + 1, name) for index, name in enumerate(self.names)]

    def send(self, port: str, message: bytes) -> None:
        if port not in self.names:
            raise midi.MidiError(f"MIDI port {port!r} is gone")
        self.sent.append((port, message))

    def close(self) -> None:
        self.closed = True


# --- shared helpers ---


def test_port_matching_is_a_case_insensitive_substring():
    assert midi.port_matches("POD Go MIDI 1")
    assert midi.port_matches("pod go")
    assert not midi.port_matches("Built-in Audio Analog Stereo")
    assert midi.port_matches("My Pedal", hint="pedal")


# --- ALSA (Linux) ---


def test_parse_ports_reads_the_amidi_listing():
    assert alsa.parse_ports(AMIDI_LISTING) == "hw:2,0,0"
    assert alsa.parse_ports(AMIDI_LISTING, hint="pod go") == "hw:2,0,0"
    assert alsa.parse_ports("Dir Device Name\n") is None
    assert alsa.parse_ports(AMIDI_LISTING, hint="not there") is None


def test_alsa_requires_the_amidi_binary(monkeypatch):
    monkeypatch.setattr(alsa.shutil, "which", lambda name: None)
    with pytest.raises(midi.MidiError, match="alsa-utils"):
        alsa.AlsaBackend()


def test_alsa_find_port_and_send(monkeypatch):
    run = FakeRun(stdout=AMIDI_LISTING)
    monkeypatch.setattr(alsa.subprocess, "run", run)
    backend = alsa.AlsaBackend(amidi="/usr/bin/amidi")

    assert backend.find_port() == "hw:2,0,0"
    assert run.calls == [["/usr/bin/amidi", "-l"]]

    backend.send("hw:2,0,0", bytes([0xB0, 69, 2]))
    assert run.calls[-1] == ["/usr/bin/amidi", "-p", "hw:2,0,0", "-S", "B0 45 02"]


def test_alsa_send_failure_raises(monkeypatch):
    run = FakeRun(returncode=1, stderr="amidi: No such device")
    monkeypatch.setattr(alsa.subprocess, "run", run)
    backend = alsa.AlsaBackend(amidi="/usr/bin/amidi")
    with pytest.raises(midi.MidiError, match="No such device"):
        backend.send("hw:9,0,0", b"\xC0\x01")


# --- CoreMIDI (macOS) ---


def test_packet_list_layout_matches_the_coremidi_sdk():
    """The structures are not padded: numPackets@0, packet@4, data@14."""
    assert coremidi._MIDIPacketList.numPackets.offset == 0
    assert coremidi._MIDIPacketList.packet.offset == 4
    assert coremidi._MIDIPacket.timeStamp.offset == 0
    assert coremidi._MIDIPacket.length.offset == 8
    assert coremidi._MIDIPacket.data.offset == 10


def test_build_packet_list_packs_one_immediate_packet():
    message = bytes([0xB0, 69, 2])
    packets = coremidi.build_packet_list(message)

    assert packets.numPackets == 1
    packet = packets.packet[0]
    assert packet.timeStamp == 0  # "send now"
    assert packet.length == len(message)
    assert bytes(packet.data[: len(message)]) == message

    raw = bytes(packets)
    header = (
        struct.pack("<I", 1)  # numPackets
        + bytes(8)  # timeStamp
        + struct.pack("<H", 3)  # length
    )
    assert raw[: len(header) + len(message)] == header + message


def test_build_packet_list_rejects_bad_lengths():
    with pytest.raises(midi.MidiError):
        coremidi.build_packet_list(b"")
    with pytest.raises(midi.MidiError):
        coremidi.build_packet_list(bytes(coremidi.MAX_PACKET_DATA + 1))


def test_coremidi_backend_finds_the_pedal():
    api = FakeAPI(("IAC Driver Bus 1", "POD Go"))
    backend = coremidi.CoreMidiBackend(api)
    assert backend.name == "CoreMIDI"
    assert backend.find_port() == "POD Go"


def test_coremidi_backend_without_the_pedal():
    backend = coremidi.CoreMidiBackend(FakeAPI(("IAC Driver Bus 1",)))
    assert backend.find_port() is None


def test_coremidi_backend_sends_and_closes():
    api = FakeAPI(("POD Go",))
    backend = coremidi.CoreMidiBackend(api)
    backend.send("POD Go", bytes([0xC0, 5]))
    assert api.sent == [("POD Go", bytes([0xC0, 5]))]
    backend.close()
    assert api.closed


# --- backend selection ---


def test_default_backend_picks_the_os_stack(monkeypatch):
    monkeypatch.setattr(
        coremidi, "CoreMidiAPI", lambda: FakeAPI(("POD Go",))
    )
    monkeypatch.setattr(platform_support, "is_macos", lambda: True)
    monkeypatch.setattr(platform_support, "is_linux", lambda: False)
    assert isinstance(midi.default_backend(), coremidi.CoreMidiBackend)

    monkeypatch.setattr(platform_support, "is_macos", lambda: False)
    monkeypatch.setattr(platform_support, "is_linux", lambda: True)
    monkeypatch.setattr(alsa.shutil, "which", lambda name: "/usr/bin/amidi")
    assert isinstance(midi.default_backend(), alsa.AlsaBackend)


def test_default_backend_rejects_unsupported_os(monkeypatch):
    monkeypatch.setattr(platform_support, "is_macos", lambda: False)
    monkeypatch.setattr(platform_support, "is_linux", lambda: False)
    monkeypatch.setattr(platform_support, "os_name", lambda: "win32")
    with pytest.raises(midi.MidiError, match="win32"):
        midi.default_backend()


def test_midiout_uses_the_backend_port_and_sends_through_it():
    api = FakeAPI(("POD Go",))
    out = midi.MidiOut(backend=coremidi.CoreMidiBackend(api))
    assert out.port == "POD Go"
    out.recall(setlist=1, preset=3)
    assert api.sent == [("POD Go", bytes([0xB0, midi.CC_SETLIST, 1, 0xC0, 3]))]


def test_midiout_raises_without_a_port():
    with pytest.raises(midi.MidiError, match="not found"):
        midi.MidiOut(backend=coremidi.CoreMidiBackend(FakeAPI()))
