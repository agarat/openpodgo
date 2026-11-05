"""Linux MIDI backend: ``amidi`` from alsa-utils.

ALSA exposes the pedal's class-compliant MIDI port as a rawmidi device
(``amidi -l`` prints e.g. ``IO  hw:2,0,0  POD Go MIDI 1``) and ``amidi -S``
writes raw bytes to it. Shelling out keeps the project free of native Python
MIDI dependencies, which is the whole point of this backend on Linux.
"""

from __future__ import annotations

import logging
import re
import shutil
import subprocess

from .midi import PORT_NAME_HINT, MidiBackend, MidiError, port_matches

log = logging.getLogger(__name__)

#: ALSA rawmidi device in an `amidi -l` line ("hw:2,0,0", "hw:2,0").
_DEVICE_RE = re.compile(r"(hw:\S+)")


def parse_ports(listing: str, hint: str = PORT_NAME_HINT) -> str | None:
    """ALSA device of the first `amidi -l` line matching `hint`, if any.

    Kept separate from the subprocess call so it can be tested with a plain
    string captured from a real machine.
    """
    for line in listing.splitlines():
        if not port_matches(line, hint):
            continue
        match = _DEVICE_RE.search(line)
        if match:
            return match.group(1)
    return None


class AlsaBackend(MidiBackend):
    """MIDI through the ALSA `amidi` utility (Linux only)."""

    name = "ALSA"

    def __init__(self, amidi: str | None = None) -> None:
        #: Path of the `amidi` binary; injectable for tests.
        self._amidi = amidi or shutil.which("amidi")
        if self._amidi is None:
            raise MidiError("'amidi' not found: install alsa-utils")

    def find_port(self, hint: str = PORT_NAME_HINT) -> str | None:
        listing = self._run("-l")
        port = parse_ports(listing, hint)
        log.debug("ALSA ports: %s -> %s", listing.strip() or "(none)", port)
        return port

    def send(self, port: str, message: bytes) -> None:
        hexstr = " ".join(f"{b & 0xFF:02X}" for b in message)
        try:
            self._run("-p", port, "-S", hexstr)
        except MidiError as exc:
            raise MidiError(f"amidi failed sending {hexstr!r}: {exc}") from exc

    def _run(self, *args: str) -> str:
        """Run `amidi` and return stdout, raising MidiError on failure."""
        try:
            result = subprocess.run(
                [self._amidi, *args], capture_output=True, text=True, check=False
            )
        except OSError as exc:  # amidi removed / not executable
            raise MidiError(f"could not run {self._amidi}: {exc}") from exc
        if result.returncode != 0:
            raise MidiError(
                result.stderr.strip() or f"amidi exited {result.returncode}"
            )
        return result.stdout
