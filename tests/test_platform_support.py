"""Tests for the platform seam: OS detection, libusb lookup and hints.

These run on any OS: the platform is simulated by monkeypatching
`platform_support.sys.platform` (and the helpers it consults).
"""

from __future__ import annotations

import pytest

from openpodgo import platform_support


@pytest.fixture
def fake_platform(monkeypatch):
    """Set sys.platform to an arbitrary value, undoing nothing else."""

    def _set(value: str) -> None:
        monkeypatch.setattr(platform_support.sys, "platform", value)

    return _set


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("linux", platform_support.LINUX),
        ("linux2", platform_support.LINUX),
        ("darwin", platform_support.MACOS),
        ("win32", "win32"),  # not supported, reported verbatim
        ("freebsd13", "freebsd13"),
    ],
)
def test_os_name_mapping(fake_platform, raw, expected):
    fake_platform(raw)
    assert platform_support.os_name() == expected


def test_supported_platforms(fake_platform):
    fake_platform("linux")
    assert platform_support.is_linux()
    assert platform_support.is_supported()
    assert platform_support.has_kernel_driver()

    fake_platform("darwin")
    assert platform_support.is_macos()
    assert platform_support.is_supported()
    # macOS has no kernel driver to detach from the vendor interface.
    assert not platform_support.has_kernel_driver()

    fake_platform("win32")
    assert not platform_support.is_linux()
    assert not platform_support.is_macos()
    assert not platform_support.is_supported()


def test_hints_name_the_platform_tooling(fake_platform):
    fake_platform("linux")
    assert "udev" in platform_support.usb_hint()
    assert "alsa-utils" in platform_support.midi_install_hint()

    fake_platform("darwin")
    assert "libusb" in platform_support.usb_hint()
    assert "POD Go Edit" in platform_support.usb_hint()
    assert "CoreMIDI" in platform_support.midi_install_hint()

    fake_platform("win32")
    hint = platform_support.usb_hint()
    assert "linux" not in hint and "darwin" not in hint


def test_find_libusb_prefers_a_loadable_macos_path(fake_platform, monkeypatch):
    """An Intel copy under /usr/local must not shadow the arm64 one."""
    fake_platform("darwin")
    tried: list[str] = []

    def fake_loads(path: str) -> bool:
        tried.append(path)
        return path == "/opt/homebrew/lib/libusb-1.0.dylib"

    monkeypatch.setattr(platform_support, "_loads", fake_loads)
    monkeypatch.setattr(
        platform_support.os.path, "isfile", lambda path: "libusb" in path
    )
    assert platform_support.find_libusb() == "/opt/homebrew/lib/libusb-1.0.dylib"
    # It stopped at the first library that loads.
    assert tried == ["/opt/homebrew/lib/libusb-1.0.dylib"]


def test_find_libusb_falls_back_to_the_system_lookup(fake_platform, monkeypatch):
    fake_platform("linux")
    monkeypatch.setattr(
        platform_support.ctypes.util, "find_library", lambda name: f"lib{name}.so"
    )
    assert platform_support.find_libusb() == "liblibusb-1.0.so"


def test_find_libusb_returns_none_when_missing(fake_platform, monkeypatch):
    fake_platform("linux")
    monkeypatch.setattr(
        platform_support.ctypes.util, "find_library", lambda name: None
    )
    assert platform_support.find_libusb() is None
