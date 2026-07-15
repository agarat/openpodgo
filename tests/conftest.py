"""Shared fixtures for the editor tests."""

from pathlib import Path

import pytest

from openpodgo import l6helix
from openpodgo.editor import PresetEditor

CAPS = Path(__file__).parent / "fixtures"


@pytest.fixture
def preset_a():
    return CAPS / "spec02_a.pgp"


@pytest.fixture
def editor_a():
    blob = l6helix.extract_blob((CAPS / "spec02_knob.bin").read_bytes())
    return PresetEditor(l6helix.parse_blob(blob))


@pytest.fixture
def preset_two():
    return CAPS / "spec02_preset2.pgp"
