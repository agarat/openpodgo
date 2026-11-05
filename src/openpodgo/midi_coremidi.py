"""macOS MIDI backend: CoreMIDI through ``ctypes`` (no extra dependency).

macOS exposes the pedal's class-compliant MIDI interface automatically — the
"POD Go" device appears in Audio MIDI Setup — so there is nothing to install
and no ``amidi`` equivalent to shell out to. This backend creates a CoreMIDI
client with an output port, finds the pedal by its display name and sends each
message as a single-packet ``MIDIPacketList``.

Only :class:`CoreMidiAPI` touches the framework; :class:`CoreMidiBackend` is a
thin adapter over it, which keeps the OS code replaceable (the tests drive it
with a fake API, so they also run on non-Mac CI).
"""

from __future__ import annotations

import ctypes
import logging

from .midi import PORT_NAME_HINT, MidiBackend, MidiError, port_matches

log = logging.getLogger(__name__)

_COREMIDI = "/System/Library/Frameworks/CoreMIDI.framework/CoreMIDI"
_COREFOUNDATION = "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"

#: kCFStringEncodingUTF8.
_UTF8 = 0x08000100

#: MIDIPacketList holds a variable-length packet: `data` is `length` bytes,
#: the 256 below is only the declared maximum. Layout verified against the
#: macOS SDK (CoreMIDI/MIDIServices.h): numPackets at 0, the first packet at 4,
#: its timeStamp at 4, length at 12 and data at 14 — the structures are not
#: padded, so ctypes must not pad them either.
MAX_PACKET_DATA = 256


class _MIDIPacket(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("timeStamp", ctypes.c_uint64),
        ("length", ctypes.c_uint16),
        ("data", ctypes.c_ubyte * MAX_PACKET_DATA),
    ]


class _MIDIPacketList(ctypes.Structure):
    _pack_ = 1
    _fields_ = [
        ("numPackets", ctypes.c_uint32),
        ("packet", _MIDIPacket * 1),
    ]


def build_packet_list(message: bytes) -> _MIDIPacketList:
    """A one-packet MIDIPacketList that sends `message` immediately.

    A timeStamp of 0 means "now", which is what a UI-driven send wants.
    """
    if not message:
        raise MidiError("empty MIDI message")
    if len(message) > MAX_PACKET_DATA:
        raise MidiError(
            f"MIDI message too long ({len(message)} > {MAX_PACKET_DATA} bytes)"
        )
    packets = _MIDIPacketList()
    packets.numPackets = 1
    packet = packets.packet[0]
    packet.timeStamp = 0
    packet.length = len(message)
    packet.data[: len(message)] = message
    return packets


class CoreMidiAPI:
    """The bits of CoreMIDI this project uses, bound with ctypes.

    Everything is created eagerly in `__init__` (client + output port) so a
    missing MIDI server or a sandbox denial fails at construction time, where
    the UI can fall back to "MIDI not available".
    """

    def __init__(
        self, coremidi_path: str = _COREMIDI, corefoundation_path: str = _COREFOUNDATION
    ) -> None:
        try:
            self._midi = ctypes.CDLL(coremidi_path)
            self._cf = ctypes.CDLL(corefoundation_path)
        except OSError as exc:  # pragma: no cover - CoreMIDI ships with macOS
            raise MidiError(f"CoreMIDI unavailable: {exc}") from exc
        self._bind()
        self._props: dict[str, int] = {}
        self._client = ctypes.c_uint32()
        self._port = ctypes.c_uint32()
        self._closed = False
        # CoreMIDI copies/references the names; the CFStrings are kept alive
        # here anyway (two tiny objects) to avoid depending on that.
        self._client_name = self._cf_string("openpodgo")
        self._port_name = self._cf_string("openpodgo out")
        self._check(
            self._midi.MIDIClientCreate(
                self._client_name, None, None, ctypes.byref(self._client)
            ),
            "MIDIClientCreate",
        )
        self._check(
            self._midi.MIDIOutputPortCreate(
                self._client, self._port_name, ctypes.byref(self._port)
            ),
            "MIDIOutputPortCreate",
        )
        log.debug("CoreMIDI client ready (port %d)", self._port.value)

    # --- framework binding ---

    def _bind(self) -> None:
        midi, cf = self._midi, self._cf
        ref = ctypes.c_uint32
        cstr = ctypes.c_void_p

        midi.MIDIGetNumberOfDestinations.restype = ctypes.c_ulong
        midi.MIDIGetDestination.argtypes = [ctypes.c_ulong]
        midi.MIDIGetDestination.restype = ref
        midi.MIDIObjectGetStringProperty.argtypes = [
            ref,
            cstr,
            ctypes.POINTER(cstr),
        ]
        midi.MIDIObjectGetStringProperty.restype = ctypes.c_int32
        midi.MIDIObjectGetIntegerProperty.argtypes = [
            ref,
            cstr,
            ctypes.POINTER(ctypes.c_int32),
        ]
        midi.MIDIObjectGetIntegerProperty.restype = ctypes.c_int32
        midi.MIDIClientCreate.argtypes = [
            cstr,
            cstr,  # notify proc: NULL, we never listen to topology changes
            cstr,
            ctypes.POINTER(ref),
        ]
        midi.MIDIClientCreate.restype = ctypes.c_int32
        midi.MIDIOutputPortCreate.argtypes = [ref, cstr, ctypes.POINTER(ref)]
        midi.MIDIOutputPortCreate.restype = ctypes.c_int32
        midi.MIDISend.argtypes = [ref, ref, ctypes.POINTER(_MIDIPacketList)]
        midi.MIDISend.restype = ctypes.c_int32
        midi.MIDIPortDispose.argtypes = [ref]
        midi.MIDIPortDispose.restype = ctypes.c_int32
        midi.MIDIClientDispose.argtypes = [ref]
        midi.MIDIClientDispose.restype = ctypes.c_int32

        cf.CFStringCreateWithCString.argtypes = [cstr, ctypes.c_char_p, ctypes.c_uint32]
        cf.CFStringCreateWithCString.restype = cstr
        cf.CFStringGetLength.argtypes = [cstr]
        cf.CFStringGetLength.restype = ctypes.c_long
        cf.CFStringGetMaximumSizeForEncoding.argtypes = [
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        cf.CFStringGetMaximumSizeForEncoding.restype = ctypes.c_long
        cf.CFStringGetCString.argtypes = [
            cstr,
            ctypes.c_char_p,
            ctypes.c_long,
            ctypes.c_uint32,
        ]
        cf.CFStringGetCString.restype = ctypes.c_bool
        cf.CFRelease.argtypes = [cstr]
        cf.CFRelease.restype = None

    def _property(self, symbol: str) -> int | None:
        """Value of an exported `const CFStringRef` property key (cached).

        Resolved lazily on first use: CoreMIDI fills these globals during its
        first API call, so reading them before that returns 0, which would
        make every property lookup fail with kMIDIUnknownProperty.
        """
        if symbol in self._props:
            return self._props[symbol]
        try:
            value = ctypes.c_void_p.in_dll(self._midi, symbol).value
        except ValueError:  # pragma: no cover - symbol missing on very old macOS
            log.debug("CoreMIDI symbol %s not found", symbol)
            value = None
        if value:
            self._props[symbol] = value
        return value

    def _check(self, status: int, what: str) -> None:
        if status != 0:
            raise MidiError(f"CoreMIDI {what} failed (OSStatus {status})")

    # --- CoreFoundation strings ---

    def _cf_string(self, text: str):
        handle = self._cf.CFStringCreateWithCString(
            None, text.encode("utf-8"), _UTF8
        )
        if not handle:
            raise MidiError(f"could not create the CFString {text!r}")
        return handle

    def _read_cf_string(self, handle) -> str:
        """Convert an owned CFStringRef to Python text and release it."""
        try:
            count = self._cf.CFStringGetLength(handle) + 1
            size = self._cf.CFStringGetMaximumSizeForEncoding(count, _UTF8) or count * 4
            buffer = ctypes.create_string_buffer(max(size, 1))
            if not self._cf.CFStringGetCString(handle, buffer, size, _UTF8):
                return ""
            return buffer.value.decode("utf-8", "replace")
        finally:
            self._cf.CFRelease(handle)

    # --- objects ---

    def _string_property(self, obj: int, symbol: str) -> str | None:
        key = self._property(symbol)
        if key is None:
            return None
        handle = ctypes.c_void_p()
        status = self._midi.MIDIObjectGetStringProperty(
            obj, key, ctypes.byref(handle)
        )
        if status != 0 or not handle.value:
            return None
        return self._read_cf_string(handle)

    def _is_offline(self, obj: int) -> bool:
        key = self._property("kMIDIPropertyOffline")
        if key is None:
            return False
        value = ctypes.c_int32()
        status = self._midi.MIDIObjectGetIntegerProperty(
            obj, key, ctypes.byref(value)
        )
        return status == 0 and value.value != 0

    def _display_name(self, obj: int) -> str | None:
        """User-visible endpoint name ("POD Go"), falling back to its ID name."""
        name = self._string_property(obj, "kMIDIPropertyDisplayName")
        return name or self._string_property(obj, "kMIDIPropertyName")

    def destinations(self) -> list[tuple[int, str]]:
        """Live (endpoint, display name) pairs, skipping offline endpoints."""
        found: list[tuple[int, str]] = []
        for index in range(self._midi.MIDIGetNumberOfDestinations()):
            endpoint = self._midi.MIDIGetDestination(index)
            if not endpoint:
                continue
            if self._is_offline(endpoint):
                continue
            name = self._display_name(endpoint)
            if name:
                found.append((int(endpoint), name))
        return found

    def destination(self, port: str) -> int | None:
        """Endpoint for `port`: its exact name, else any name containing it."""
        endpoints = self.destinations()
        for endpoint, name in endpoints:
            if name == port:
                return endpoint
        for endpoint, name in endpoints:
            if port_matches(name, port):
                return endpoint
        return None

    def send(self, port: str, message: bytes) -> None:
        endpoint = self.destination(port)
        if endpoint is None:
            raise MidiError(
                f"MIDI port {port!r} is gone (was the pedal disconnected?)"
            )
        packets = build_packet_list(message)
        self._check(
            self._midi.MIDISend(self._port, endpoint, ctypes.byref(packets)),
            "MIDISend",
        )

    def close(self) -> None:
        """Dispose the output port and the client (idempotent)."""
        if self._closed:
            return
        self._closed = True
        if self._port.value:
            self._midi.MIDIPortDispose(self._port)
        if self._client.value:
            self._midi.MIDIClientDispose(self._client)


class CoreMidiBackend(MidiBackend):
    """MIDI through CoreMIDI (macOS only)."""

    name = "CoreMIDI"

    def __init__(self, api: CoreMidiAPI | None = None) -> None:
        #: CoreMIDI binding; injectable for tests.
        self._api = api if api is not None else CoreMidiAPI()

    def find_port(self, hint: str = PORT_NAME_HINT) -> str | None:
        names = [name for _endpoint, name in self._api.destinations()]
        port = next((name for name in names if port_matches(name, hint)), None)
        log.debug("CoreMIDI destinations %s -> %s", names, port)
        return port

    def send(self, port: str, message: bytes) -> None:
        self._api.send(port, message)

    def close(self) -> None:
        self._api.close()
