"""Sending MIDI messages to the POD Go via ALSA (`amidi`).

The POD Go exposes a class-compliant MIDI port (interface 4) that ALSA
detects as "POD Go MIDI 1". Standard MIDI is sufficient for changing
preset/snapshot and emulating footswitches, independently of the vendor
session (interface 0).

`amidi -S` is used to avoid adding extra native dependencies. Official
POD Go MIDI table (Owner's Manual):
- Program Change (channel 1): preset recall 0-127 of the active setlist.
- CC 69: snapshot (0-3).
- CC 49-56: footswitches FS1-FS8.
- CC 68: tap tempo.  CC 1/2: expression pedals.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess

log = logging.getLogger(__name__)

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
    """Failed to send MIDI to the POD Go."""


def find_port(hint: str = PORT_NAME_HINT) -> str | None:
    """Return the ALSA port (e.g. 'hw:2,0,0') of the POD Go, or None."""
    if shutil.which("amidi") is None:
        raise MidiError("'amidi' not found (install alsa-utils)")
    out = subprocess.run(
        ["amidi", "-l"], capture_output=True, text=True, check=False
    ).stdout
    for line in out.splitlines():
        if hint.lower() in line.lower():
            m = re.search(r"(hw:\S+)", line)
            if m:
                return m.group(1)
    return None


class MidiOut:
    """MIDI output to the POD Go via an ALSA port."""

    def __init__(self, port: str | None = None) -> None:
        self.port = port or find_port()
        if self.port is None:
            raise MidiError(
                "POD Go MIDI port not found. Is it connected?"
            )

    def _send(self, *data: int) -> None:
        hexstr = " ".join(f"{b & 0xFF:02X}" for b in data)
        res = subprocess.run(
            ["amidi", "-p", self.port, "-S", hexstr],
            capture_output=True, text=True, check=False,
        )
        if res.returncode != 0:
            raise MidiError(f"amidi failed sending {hexstr!r}: {res.stderr.strip()}")
        log.debug("MIDI -> %s: %s", self.port, hexstr)

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
