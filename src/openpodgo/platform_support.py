"""Host-platform facts shared by the USB transport, the MIDI layer and the UI.

openpodgo reaches the pedal through two OS-specific paths:

- **USB** — pyusb on top of libusb-1.0. Same code everywhere, but the library
  is installed in different places (a Homebrew libusb on Apple Silicon is not
  on pyusb's search path, and an Intel copy under ``/usr/local`` can shadow it
  and refuse to load on an arm64 Mac), and only Linux has a kernel driver to
  detach from the vendor interface.
- **MIDI** — ALSA (``amidi``) on Linux, CoreMIDI on macOS. The transports live
  in :mod:`openpodgo.midi_alsa` / :mod:`openpodgo.midi_coremidi`; this module
  only answers which one applies.

Keeping the answers here means ``sys.platform`` is inspected in exactly one
place and every layer (transport, MIDI, UI) can ask the same questions.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys

LINUX = "linux"
MACOS = "macos"

#: Operating systems with a tested MIDI backend (see `midi.default_backend`).
SUPPORTED = (LINUX, MACOS)

#: Usual libusb-1.0 install locations on macOS, most specific first. An Apple
#: Silicon Homebrew prefix is preferred over `/usr/local`, where an old Intel
#: copy may live: pyusb's own lookup picks whatever `ctypes.util.find_library`
#: returns and then fails to dlopen a wrong-architecture library.
_MACOS_LIBUSB_PATHS = (
    "/opt/homebrew/lib/libusb-1.0.dylib",  # Homebrew (Apple Silicon)
    "/usr/local/lib/libusb-1.0.dylib",  # Homebrew (Intel) / manual install
    "/opt/local/lib/libusb-1.0.dylib",  # MacPorts
)


def os_name() -> str:
    """``"linux"`` / ``"macos"`` on the supported systems, else ``sys.platform``."""
    if sys.platform.startswith("linux"):
        return LINUX
    if sys.platform == "darwin":
        return MACOS
    return sys.platform


def is_linux() -> bool:
    return os_name() == LINUX


def is_macos() -> bool:
    return os_name() == MACOS


def is_supported() -> bool:
    """True if this OS has both a USB path and a MIDI backend."""
    return os_name() in SUPPORTED


def has_kernel_driver() -> bool:
    """True where a kernel driver may hold the vendor USB interface.

    Only Linux has one: pyusb raises ``NotImplementedError`` from
    `is_kernel_driver_active` on macOS, so the transport asks first.
    """
    return is_linux()


def find_libusb() -> str | None:
    """Path or soname of libusb-1.0, or None if it cannot be found.

    On macOS the known install locations are tried first and only a library
    that actually loads is accepted (see `_MACOS_LIBUSB_PATHS`); elsewhere the
    system lookup is enough.
    """
    if is_macos():
        for path in _MACOS_LIBUSB_PATHS:
            if os.path.isfile(path) and _loads(path):
                return path
    return ctypes.util.find_library("libusb-1.0") or ctypes.util.find_library(
        "usb-1.0"
    )


def _loads(path: str) -> bool:
    """True if `path` can be dlopen'ed (right architecture and dependencies)."""
    try:
        ctypes.CDLL(path)
    except OSError:
        return False
    return True


def usb_hint() -> str:
    """What to check when the pedal cannot be opened, phrased for this OS."""
    if is_macos():
        return (
            "check libusb is installed (brew install libusb) and that no other "
            "app (POD Go Edit, a DAW) is holding the pedal"
        )
    if is_linux():
        return "check the udev rule is applied (see README) and reconnect the pedal"
    return "check the USB cable and the libusb installation of your platform"


def midi_install_hint() -> str:
    """What to install when no MIDI backend is available on this OS."""
    if is_linux():
        return "install alsa-utils ('amidi' is used to send MIDI)"
    if is_macos():
        return (
            "CoreMIDI should be available; check the pedal appears in "
            "Audio MIDI Setup"
        )
    return "MIDI is only implemented for Linux (ALSA) and macOS (CoreMIDI)"
