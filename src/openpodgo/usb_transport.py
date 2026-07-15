"""USB bulk transport layer for the POD Go vendor interface.

Implements device opening, vendor-specific interface claim, and the bulk
write/read helpers with the strict request->response pattern and the
"stale data drain" described in https://github.com/allansomensi/openhx
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

import usb.core
import usb.util

log = logging.getLogger(__name__)

#: Line 6 Vendor ID.
VENDOR_ID = 0x0E41

#: Known PIDs of the Helix/HX family (reference). The POD Go PID is
#: autodetected: any device with VENDOR_ID that exposes a vendor-specific
#: interface with a pair of bulk endpoints is considered a candidate.
KNOWN_PRODUCT_IDS = {
    0x4247: "POD Go",
    0x4246: "HX Stomp",
    0x4253: "HX Stomp XL",
    0x5055: "HX Stomp (alt)",
}

USB_CLASS_VENDOR_SPECIFIC = 0xFF
EP_OUT = 0x01
EP_IN = 0x81

READ_BUFFER = 512
OP_TIMEOUT_MS = 2000
DRAIN_TIMEOUT_MS = 50


class TransportError(Exception):
    """Failure in the USB transport layer."""


@dataclass
class DeviceInfo:
    """USB identity and topology of the found device."""

    vendor_id: int
    product_id: int
    product_name: str
    interface: int
    ep_out: int
    ep_in: int

    def __str__(self) -> str:
        return (
            f"{self.product_name} ({self.vendor_id:04x}:{self.product_id:04x}) "
            f"iface={self.interface} out={self.ep_out:#04x} in={self.ep_in:#04x}"
        )


def _find_vendor_interface(dev) -> tuple[int, int, int] | None:
    """Returns (interface, ep_out, ep_in) of the first vendor-specific interface
    with a bulk OUT and a bulk IN endpoint, or None if none found."""
    for cfg in dev:
        for intf in cfg:
            if intf.bInterfaceClass != USB_CLASS_VENDOR_SPECIFIC:
                continue
            ep_out = ep_in = None
            for ep in intf:
                is_bulk = usb.util.endpoint_type(ep.bmAttributes) == usb.util.ENDPOINT_TYPE_BULK
                if not is_bulk:
                    continue
                if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_OUT:
                    ep_out = ep.bEndpointAddress
                else:
                    ep_in = ep.bEndpointAddress
            if ep_out is not None and ep_in is not None:
                return intf.bInterfaceNumber, ep_out, ep_in
    return None


class UsbTransport:
    """Bulk connection to a POD Go / Helix device via its vendor interface."""

    def __init__(self) -> None:
        self._dev = None
        self._info: DeviceInfo | None = None
        self._detached_kernel = False
        self._lock = threading.Lock()

    @property
    def info(self) -> DeviceInfo | None:
        return self._info

    def open(self) -> DeviceInfo:
        """Locates, opens and claims the device. Returns its DeviceInfo."""
        dev = self._locate()
        if dev is None:
            raise TransportError(
                "No Line 6 device with a vendor interface found "
                f"(VID {VENDOR_ID:#06x}). Is the POD Go connected and powered on?"
            )

        found = _find_vendor_interface(dev)
        if found is None:
            raise TransportError(
                "Line 6 device found but without a vendor interface with "
                "bulk endpoints; not editable via this protocol."
            )
        interface, ep_out, ep_in = found
        pid = dev.idProduct

        # Detach the kernel driver if it claimed the vendor interface.
        try:
            if dev.is_kernel_driver_active(interface):
                log.info("Detaching kernel driver from interface %d", interface)
                dev.detach_kernel_driver(interface)
                self._detached_kernel = True
        except (NotImplementedError, usb.core.USBError) as exc:
            log.debug("detach_kernel_driver no aplicable: %s", exc)

        try:
            dev.set_configuration(1)
        except usb.core.USBError as exc:
            # Already configured by the kernel: continue.
            log.debug("set_configuration(1): %s", exc)

        usb.util.claim_interface(dev, interface)

        # Clear endpoints that may be in a halt state.
        for ep in (ep_out, ep_in):
            try:
                dev.clear_halt(ep)
            except usb.core.USBError as exc:
                log.debug("clear_halt(%#x): %s", ep, exc)

        self._dev = dev
        self._info = DeviceInfo(
            vendor_id=VENDOR_ID,
            product_id=pid,
            product_name=KNOWN_PRODUCT_IDS.get(pid, "POD Go / Helix (unknown)"),
            interface=interface,
            ep_out=ep_out,
            ep_in=ep_in,
        )
        log.info("Device opened: %s", self._info)
        return self._info

    def _locate(self):
        # Prefer known PIDs; otherwise, any Line 6 with a vendor interface.
        for dev in usb.core.find(find_all=True, idVendor=VENDOR_ID):
            if _find_vendor_interface(dev) is not None:
                if dev.idProduct in KNOWN_PRODUCT_IDS:
                    return dev
        for dev in usb.core.find(find_all=True, idVendor=VENDOR_ID):
            if _find_vendor_interface(dev) is not None:
                return dev
        return None

    def drain(self, timeout_ms: int = DRAIN_TIMEOUT_MS) -> int:
        """Drains residual IN data from a previous improperly closed session.

        Reads with a short timeout until the read fails with a timeout. Returns
        the number of drained packets.
        """
        drained = 0
        while True:
            try:
                self._dev.read(self._info.ep_in, READ_BUFFER, timeout=timeout_ms)
                drained += 1
            except usb.core.USBError:
                break
        if drained:
            log.debug("drained %d residual packets", drained)
        return drained

    def write(self, data: bytes, timeout_ms: int = OP_TIMEOUT_MS) -> int:
        """Writes a packet to the bulk OUT endpoint."""
        try:
            return self._dev.write(self._info.ep_out, data, timeout=timeout_ms)
        except usb.core.USBError as exc:
            raise TransportError(f"bulk write failure: {exc}") from exc

    def read(self, timeout_ms: int = OP_TIMEOUT_MS) -> bytes:
        """Reads a packet from the bulk IN endpoint."""
        try:
            arr = self._dev.read(self._info.ep_in, READ_BUFFER, timeout=timeout_ms)
            return bytes(arr)
        except usb.core.USBError as exc:
            raise TransportError(f"bulk read failure: {exc}") from exc

    def request(self, data: bytes, timeout_ms: int = OP_TIMEOUT_MS) -> bytes:
        """CHANNEL-FILTERED request->response pattern.

        The IN EP is shared by the three logical channels (read 0x03EF,
        write 0x03ED, keepalive 0x03F0) and the device pushes unsolicited
        packets (e.g. keepalives from the write channel once opened). The
        legitimate response mirrors the request's src/dst:
        IN[4:8] == OUT[6:8] + OUT[4:6]. Packets from other channels are
        discarded until it is found or the timeout expires.
        """
        expected = data[6:8] + data[4:6] if len(data) >= 8 else b""
        with self._lock:
            self.write(data, timeout_ms)
            deadline = time.monotonic() + timeout_ms / 1000.0
            while True:
                remaining_ms = max(1, int((deadline - time.monotonic()) * 1000))
                resp = self.read(remaining_ms)
                if not expected or len(resp) < 8 or resp[4:8] == expected:
                    return resp
                log.debug(
                    "request: descartado paquete de canal %s (esperaba %s)",
                    resp[4:8].hex(), expected.hex(),
                )
                if time.monotonic() >= deadline:
                    raise TransportError(
                        f"no response from channel {expected.hex()} within {timeout_ms} ms "
                        "(solo llegaron paquetes de otros canales)"
                    )

    def close(self) -> None:
        if self._dev is None:
            return
        try:
            usb.util.release_interface(self._dev, self._info.interface)
        except usb.core.USBError as exc:
            log.debug("release_interface: %s", exc)
        if self._detached_kernel:
            try:
                self._dev.attach_kernel_driver(self._info.interface)
            except (NotImplementedError, usb.core.USBError) as exc:
                log.debug("attach_kernel_driver: %s", exc)
        usb.util.dispose_resources(self._dev)
        self._dev = None
        log.info("Device closed")

    @property
    def lock(self) -> threading.Lock:
        return self._lock

    def try_read_notification(self, timeout_ms: int = 50) -> bytes | None:
        """Non-blocking read from IN endpoint.

        Returns raw packet data if the lock could be acquired (no Worker
        in progress) and data was available. Returns None if the lock is
        held or no data arrived within timeout_ms.
        """
        if self._dev is None:
            return None
        if not self._lock.acquire(blocking=False):
            return None
        try:
            arr = self._dev.read(self._info.ep_in, READ_BUFFER, timeout=timeout_ms)
            return bytes(arr)
        except usb.core.USBError as exc:
            if "timeout" not in str(exc).lower():
                log.warning("try_read_notification: %s", exc)
            return None
        finally:
            self._lock.release()

    def __enter__(self) -> "UsbTransport":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()
