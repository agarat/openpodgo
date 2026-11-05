"""Sending MIDI messages to the POD Go.

The pedal exposes a class-compliant MIDI device (it shows up as "POD Go"),
which is enough to recall presets/snapshots and to emulate footswitches
independently of the USB vendor session.

The messages are the same on every OS; only the transport differs, so it is
pluggable behind :class:`MidiBackend`:

- **Linux** → :class:`midi_alsa.AlsaBackend`, shells out to ``amidi``
  (alsa-utils), no Python dependency.
- **macOS** → :class:`midi_coremidi.CoreMidiBackend`, talks to CoreMIDI
  through ``ctypes``, no dependency either.

:class:`MidiOut` stays platform-agnostic: it builds the messages and asks the
backend to find the port and write the bytes. Official POD Go MIDI table
(Owner's Manual):
- Program Change (channel 1): preset recall 0-127 of the active setlist.
- CC 69: snapshot (0-3).
- CC 49-56: footswitches FS1-FS8.
- CC 68: tap tempo.  CC 1/2: expression pedals.
"""

from __future__ import annotations

import logging

from . import platform_support

log = logging.getLogger(__name__)

#: Substring of the pedal's MIDI port name on every OS ("POD Go MIDI 1").
PORT_NAME_HINT = "POD Go"

# Channel 1 (status nibble 0). Program Change = 0xC0.
PROGRAM_CHANGE = 0xC0
CONTROL_CHANGE = 0xB0

CC_SETLIST = 32  # Bank Select LSB: selects the setlist (0=Factory, 1=User)
CC_SNAPSHOT = 69
CC_TAP_TEMPO = 68
CC_FS_BASE = 49  # FS1=49 ... FS8=56
CC_EXP1 = 1
CC_EXP2 = 2


class MidiError(Exception):
    """Failed to talk MIDI to the POD Go."""


def port_matches(name: str, hint: str = PORT_NAME_HINT) -> bool:
    """True if `name` looks like the pedal's port.

    Case-insensitive substring: OSes decorate the name differently ("POD Go
    MIDI 1" on ALSA, "POD Go" on CoreMIDI) and the user may rename the port.
    """
    return hint.lower() in name.lower()


class MidiBackend:
    """OS-specific MIDI transport: find the pedal's port and write messages.

    Subclasses only implement the two OS calls; `name` is shown in the status
    bar so it is obvious which stack is live (e.g. "ALSA", "CoreMIDI").
    """

    #: Short label of the OS stack, for logs and the status bar.
    name = "MIDI"

    def find_port(self, hint: str = PORT_NAME_HINT) -> str | None:
        """Identifier of the first matching port, or None if there is none."""
        raise NotImplementedError

    def send(self, port: str, message: bytes) -> None:
        """Write one complete MIDI message to `port`."""
        raise NotImplementedError

    def close(self) -> None:
        """Release any OS resource held (no-op by default)."""


def default_backend() -> MidiBackend:
    """The MIDI backend for this OS.

    The backends are imported here (not at module level) so that a session
    only ever loads the OS stack it can actually use.
    """
    if platform_support.is_macos():
        from .midi_coremidi import CoreMidiBackend

        return CoreMidiBackend()
    if platform_support.is_linux():
        from .midi_alsa import AlsaBackend

        return AlsaBackend()
    raise MidiError(
        f"MIDI is not implemented for {platform_support.os_name()!r} "
        f"({platform_support.midi_install_hint()})"
    )


def find_port(hint: str = PORT_NAME_HINT) -> str | None:
    """Identifier of the POD Go MIDI port on this OS, or None if absent."""
    backend = default_backend()
    try:
        return backend.find_port(hint)
    finally:
        backend.close()


class MidiOut:
    """MIDI output to the POD Go through the platform backend."""

    def __init__(
        self, port: str | None = None, backend: MidiBackend | None = None
    ) -> None:
        self.backend = backend if backend is not None else default_backend()
        self.port = port or self.backend.find_port()
        if self.port is None:
            raise MidiError(
                f"POD Go MIDI port not found ({self.backend.name}). "
                f"Is the pedal connected? {platform_support.midi_install_hint()}"
            )

    def _send(self, *data: int) -> None:
        message = bytes(b & 0xFF for b in data)
        self.backend.send(self.port, message)
        log.debug(
            "MIDI -> %s [%s]: %s",
            self.port,
            self.backend.name,
            message.hex(" ").upper(),
        )

    def program_change(self, preset: int) -> None:
        """Recall preset 0-127 of the active setlist."""
        if not 0 <= preset <= 127:
            raise ValueError(f"preset out of range 0-127: {preset}")
        self._send(PROGRAM_CHANGE, preset)

    def select_setlist(self, setlist: int) -> None:
        """Select the setlist (CC32): 0=Factory, 1=User."""
        if not 0 <= setlist <= 127:
            raise ValueError(f"setlist out of range: {setlist}")
        self.control_change(CC_SETLIST, setlist)

    def recall(self, setlist: int, preset: int) -> None:
        """Recall a preset from a specific setlist: CC32 (setlist) + PC,
        in a single message to guarantee ordering on the pedal."""
        if not 0 <= setlist <= 127:
            raise ValueError(f"setlist out of range: {setlist}")
        if not 0 <= preset <= 127:
            raise ValueError(f"preset out of range 0-127: {preset}")
        self._send(CONTROL_CHANGE, CC_SETLIST, setlist, PROGRAM_CHANGE, preset)

    def control_change(self, cc: int, value: int) -> None:
        self._send(CONTROL_CHANGE, cc, value)

    def snapshot(self, n: int) -> None:
        """Select snapshot 0-3 (CC 69)."""
        if not 0 <= n <= 3:
            raise ValueError(f"snapshot out of range 0-3: {n}")
        self.control_change(CC_SNAPSHOT, n)

    def footswitch(self, fs: int, on: bool = True) -> None:
        """Emulate FS1-FS8 (CC 49-56)."""
        if not 1 <= fs <= 8:
            raise ValueError(f"footswitch out of range 1-8: {fs}")
        self.control_change(CC_FS_BASE + (fs - 1), 127 if on else 0)

    def tap_tempo(self) -> None:
        self.control_change(CC_TAP_TEMPO, 127)

    def close(self) -> None:
        """Release the OS resources held by the backend."""
        self.backend.close()
