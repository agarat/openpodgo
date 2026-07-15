"""Human-readable short name of a model (POD Go Edit style)."""

from __future__ import annotations

import re

#: Category words stripped from the front of the short name.
_STRIP_WORDS = (
    "Compressor", "Preamp", "Delay", "Reverb", "Chorus", "Flanger",
    "Phaser", "Rotary", "Tremolo", "Filter", "Pitch", "Synth", "Dist",
    "Amp", "Cab", "Wah", "Vol", "EQ",
)
_CAMEL = re.compile(
    r"(?<=[A-Z])(?=[A-Z][a-z])"      # G|Cougar
    r"|(?<=[a-z])(?=[A-Z])"          # Tube|Drive
    r"|(?<=[0-9])(?=[A-Z])"          # DM4|Tube
    r"|(?<=(?<![0-9])[a-z])(?=[0-9])"  # Cougar|800 (but not 4x|12)
)


def short_name(model_name: str) -> str:
    """Human-readable short name of a model (POD Go Edit style)."""
    name = re.sub(r"^(HD2|VIC|P34)_", "", model_name)
    for word in _STRIP_WORDS:
        if name.startswith(word) and len(name) > len(word):
            name = name[len(word):].lstrip("_")
            break
    for suffix in ("Stereo", "Mono"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return _CAMEL.sub(" ", name).replace("_", " ").strip()
