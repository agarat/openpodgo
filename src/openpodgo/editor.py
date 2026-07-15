"""In-memory editing of the active preset and export to .pgp.

Mutations operate on the raw msgpack body (`Preset.body`) to avoid
losing any key on re-serialization; the decoded view is re-derived with
`l6helix.parse_body`. `to_pgp` is the inverse of the blob ↔ .pgp
mapping documented in docs/specs/02-lab-notes.md ("blob ↔ .pgp mapping"),
validated against real POD Go Edit exports in tests/test_editor.py.

Writing to the pedal (spec 03) will use this same body re-serialized to blob.
"""

from __future__ import annotations

import copy
import time

import msgpack

from . import catalog, l6helix

#: POD Go identity in official .pgp files (constant in both fixtures).
DEVICE_ID = 2162695
PGP_SCHEMA = "L6Preset"
PGP_VERSION = 6
#: POD Go Edit 2.x data.meta.appversion; emulated for maximum import
#: compatibility.
APP_NAME = "POD Go Edit"
APP_VERSION = 33554432

#: .pgp param names for input/output (positional order of the blob).
INPUT_PARAM_NAMES = ("noiseGate", "threshold", "decay")
OUTPUT_PARAM_NAMES = ("pan", "gain")
INPUT_MODEL = "P34_AppDSPFlowInput"
OUTPUT_MODEL = "P34_AppDSPFlowOutput"

#: Second params node of the block (key 12), empty in everything observed.
BLK_PARAMS_AUX = 12
#: On-wire category of amps (key 9 of the block).
CATEGORY_AMP = 17
#: Looper on-wire params (class 7): the preset stores only the first 4 of the
#: catalog param_order (Playback, Overdub, lowCut, highCut); the remaining 6
#: (Slow, Reverse, Once, Undo, …) are runtime toggles not saved in the blob.
#: RE'd from the pedal (HD2_LooperOneSwitchMono → params [0, 0, 20, 20000]).
LOOPER_STORED_PARAMS = 4

#: Chain entry classes that occupy a UI slot: normal blocks, loopers (class 7)
#: and empties. The looper is a distinct class, so every slot enumeration must
#: include it or indices desync on any preset that contains one.
_SLOT_CLASSES = (l6helix.CLASS_BLOCK, l6helix.CLASS_LOOPER, l6helix.CLASS_EMPTY)
#: Occupied slot classes (carry a model): everything but the empty slot.
_OCCUPIED_CLASSES = (l6helix.CLASS_BLOCK, l6helix.CLASS_LOOPER)


def _entry_model_id(entry: dict) -> int:
    """Model id of a chain entry, across block classes (6 and 7)."""
    payload = entry[l6helix.ENTRY_PAYLOAD]
    if entry[l6helix.ENTRY_CLASS] == l6helix.CLASS_LOOPER:
        return payload[l6helix.LOOPER_MODEL_ID]
    return payload[l6helix.BLK_MODEL][l6helix.MODEL_ID]


def _entry_params_node(entry: dict) -> dict:
    """Params node ({2,3,4}) of a chain entry: key 7 for loopers, 11 otherwise."""
    payload = entry[l6helix.ENTRY_PAYLOAD]
    key = (
        l6helix.IO_PARAMS
        if entry[l6helix.ENTRY_CLASS] == l6helix.CLASS_LOOPER
        else l6helix.BLK_PARAMS
    )
    return payload[key]

# Footswitch node keys (body[3], see lab-notes): 8 = groups per
# switch; each entry {10: order in group, 11: {5: label, 6: ledcolor auto,
# 7: enabled, 8: block 1-based}, 12: momentary (candidate), 15: custom
# color (bool), 16: palette color index}.
FS_GROUPS = 8
FS_ORDER = 10
FS_TARGET = 11
FS_MOMENTARY = 12
#: LED color CHOSEN by the user (RE spec 09, validated against the pedal):
#: entry key 16 is the index into FS_COLOR_NAMES and key 15 is the
#: "a palette color is chosen" flag (False = Auto). The internal key 6
#: (FST_LEDCOLOR) is the Auto color resolved by category, NOT the chosen one.
FS_COLOR_CUSTOM = 15
FS_COLOR_INDEX = 16
FST_LABEL = 5
FST_LEDCOLOR = 6
FST_ENABLED = 7
FST_BLOCK = 8

#: Fixed footswitch LED color palette (order = on-wire index of key 16;
#: matches res/strings/appStrings_eng.json and POD Go Edit).
FS_COLOR_NAMES = (
    "Auto", "White", "Red", "Dark Orange", "Light Orange", "Yellow",
    "Green", "Turquoise", "Blue", "Violet", "Pink", "Off",
)

# Controller keys. NOTE: this corrects the lab note (spec 02): the body[4]
# list is NOT indexed by block slot. Key 0 of the inner def is the @controller
# NUMBER (1=EXP wah, 2=EXP volume; validated against both .pgp); the target
# block is implicit by role (wah->1, volume->2) and the per-snapshot values
# align by number-1, not by list position. The inner key 5 is NOT the
# @controller (it differs between fixtures with the same @controller; meaning
# to be determined during harvesting).
CTL_DEF = 1
CTLD_NUM = 0
CTLD_MIN = 2
CTLD_MAX = 3
CTLD_PARAM = 4

# Snapshot keys (body[10][10][i]).
SNAP_CTL_VALUES = 2  # [ [fs_enabled, controller number - 1, value] ]
SNAP_LEDCOLOR = 12
SNAPS_PEDALSTATE = 8


class UnknownModelError(ValueError):
    """The preset uses models outside the catalog: cannot be exported."""


#: Undo stack cap (each step is a deepcopy of the body, ~tens of KB).
MAX_UNDO = 100

#: Footswitch group index (0-based) reserved for the expression pedal toe
#: switch (groups 0-7 are FS1-FS8).
FS_GROUP_EXP_TOE = 8

#: Bypass target labels by group index of body[3][8]:
#: groups 0-7 = FS1-FS8, group 8 = expression pedal toe switch.
BYPASS_TARGETS = [f"FS{i}" for i in range(1, 9)] + ["EXP Toe"]

#: Controller number → source. Only EXP1/EXP2 are observed in fixtures
#: (controllers are bound to the block by role, see the CTL_DEF note above and
#: docs/specs/09-bypass-control-assign.md); the rest of the controller number
#: scheme remains to be harvested against the pedal.
CTRL_SOURCE_LABELS = {1: "EXP 1", 2: "EXP 2"}
CTRL_SOURCE_NUMS = {v: k for k, v in CTRL_SOURCE_LABELS.items()}

#: Default LED color when creating a new bypass assignment ("auto").
DEFAULT_LED_COLOR = 0

#: Controller number - 1 that marks an EMPTY controller slot in the per-snapshot
#: values (body[10][10][i][2]); the real value is the number minus 1.
SNAP_CTL_NONE = 64


class ControllerAssignUnsupported(NotImplementedError):
    """Creating this controller requires RE against the pedal.

    The target block of a controller does NOT travel in body[4] (only the
    controller number, bound by role: 1=EXP1 on the wah, 2=EXP2 on the
    volume). Creating a controller on an arbitrary parameter requires knowing
    the controller number scheme for FS/EXP and the target binding, which is
    not in the fixtures. See docs/specs/09-bypass-control-assign.md.
    """


class PresetEditor:
    """Editor over the raw body of a decoded active preset."""

    def __init__(self, preset: l6helix.Preset) -> None:
        self.body = preset.body
        self._undo_stack: list[dict] = []
        self._redo_stack: list[dict] = []
        self._gesture_tag: tuple | None = None

    @property
    def preset(self) -> l6helix.Preset:
        """Decoded view of the current state (re-derived on each access)."""
        return l6helix.parse_body(self.body)

    # --- undo/redo ---

    def _checkpoint(self, tag: tuple | None = None) -> None:
        """Save the current state before mutating.

        Consecutive mutations with the same `tag` (slider drag) coalesce
        into a single step; `tag=None` always creates a new step.
        """
        if tag is not None and tag == self._gesture_tag:
            return
        self._undo_stack.append(copy.deepcopy(self.body))
        del self._undo_stack[:-MAX_UNDO]
        self._redo_stack.clear()
        self._gesture_tag = tag

    def end_gesture(self) -> None:
        """End the current gesture: the next set_param opens a new step."""
        self._gesture_tag = None

    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def can_redo(self) -> bool:
        return bool(self._redo_stack)

    def undo(self) -> bool:
        if not self._undo_stack:
            return False
        self._redo_stack.append(self.body)
        self.body = self._undo_stack.pop()
        self._gesture_tag = None
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._undo_stack.append(self.body)
        self.body = self._redo_stack.pop()
        self._gesture_tag = None
        return True

    # --- chain access ---

    def _chain_entries(self) -> list[dict]:
        """Chain entries that occupy a slot (blocks, loopers, empties), in order."""
        return [
            e
            for e in self.body[l6helix.BODY_DSP0][l6helix.DSP_CHAIN]
            if e[l6helix.ENTRY_CLASS] in _SLOT_CLASSES
        ]

    def _block_payload(self, slot: int) -> dict:
        entry = self._chain_entries()[slot]
        if entry[l6helix.ENTRY_CLASS] not in _OCCUPIED_CLASSES:
            raise ValueError(f"slot {slot} is empty")
        return entry[l6helix.ENTRY_PAYLOAD]

    def params_node(self, slot: int) -> dict:
        """Params node of the block: {2: n_total, 3: n_snapshot, 4: values}."""
        entry = self._chain_entries()[slot]
        if entry[l6helix.ENTRY_CLASS] not in _OCCUPIED_CLASSES:
            raise ValueError(f"slot {slot} is empty")
        return _entry_params_node(entry)

    # --- mutations ---

    def set_param(self, slot: int, idx: int, value) -> None:
        """Change a parameter, preserving the on-wire type of the current value."""
        self._checkpoint(tag=("param", slot, idx))
        values = self.params_node(slot)[l6helix.PARAMS_VALUES]
        old = values[idx]
        if isinstance(old, bool):
            values[idx] = bool(value)
        elif isinstance(old, int) and not isinstance(value, float):
            values[idx] = int(value)
        else:
            values[idx] = float(value)

    def set_bypass(self, slot: int, enabled: bool) -> None:
        self._checkpoint()
        self._block_payload(slot)[l6helix.BLK_ENABLED] = bool(enabled)

    def move_block(self, from_slot: int, to_slot: int) -> None:
        """Move the block from slot `from_slot` to position `to_slot`.

        Reorders DSP_CHAIN entries (input/output remain fixed) and
        **remaps by position** the references the pedal stores by slot:
        footswitch assignments (`FST_BLOCK`, 1-based) and per-snapshot
        bypass states (`SNAP_ENABLES`, indexed by chain position).
        Controllers bind by role/model, so they follow the block alone.

        This is the structural edit the pedal receives as a complete blob
        (op 21, see `device.write_chain_blob`).
        """
        full = self.body[l6helix.BODY_DSP0][l6helix.DSP_CHAIN]
        slot_idxs = [
            i for i, e in enumerate(full)
            if e[l6helix.ENTRY_CLASS] in _SLOT_CLASSES
        ]
        n = len(slot_idxs)
        if not (0 <= from_slot < n) or not (0 <= to_slot < n):
            raise ValueError(
                f"slots out of range (0-{n - 1}): from={from_slot} to={to_slot}"
            )
        if full[slot_idxs[from_slot]][l6helix.ENTRY_CLASS] not in _OCCUPIED_CLASSES:
            raise ValueError(f"slot {from_slot} is empty: no block to move")
        if from_slot == to_slot:
            return
        self._checkpoint()
        # Reorder the slotted entries, leaving input/output in place.
        slot_entries = [full[i] for i in slot_idxs]
        slot_entries.insert(to_slot, slot_entries.pop(from_slot))
        for pos, raw_idx in enumerate(slot_idxs):
            full[raw_idx] = slot_entries[pos]
        self._remap_slots_after_move(from_slot, to_slot, n)

    def _remap_slots_after_move(self, from_slot: int, to_slot: int, n: int) -> None:
        """Apply the old->new slot permutation to footswitch and snapshots."""
        order = list(range(n))
        order.insert(to_slot, order.pop(from_slot))
        old_to_new = {old: new for new, old in enumerate(order)}

        fs = self.body.get(l6helix.BODY_FOOTSWITCH) or {}
        for group in fs.get(FS_GROUPS) or []:
            for entry in group or []:
                target = entry[FS_TARGET]
                old = target[FST_BLOCK] - 1
                if old in old_to_new:
                    target[FST_BLOCK] = old_to_new[old] + 1

        snaps = self.body.get(l6helix.BODY_SNAPSHOTS) or {}
        for snap in snaps.get(l6helix.SNAPS_LIST) or []:
            enables = snap[l6helix.SNAP_ENABLES]
            # enables = [input, n blocks, output]; permute only the blocks.
            blocks = enables[1:1 + n]
            snap[l6helix.SNAP_ENABLES][1:1 + n] = [
                blocks[order[new]] for new in range(n)
            ]

    # --- input / output (#2) ---

    def _io_payload(self, io: str) -> dict:
        cls = l6helix.CLASS_INPUT if io == "input" else l6helix.CLASS_OUTPUT
        for e in self.body[l6helix.BODY_DSP0][l6helix.DSP_CHAIN]:
            if e[l6helix.ENTRY_CLASS] == cls:
                return e[l6helix.ENTRY_PAYLOAD]
        raise ValueError(f"no {io!r} entry in the chain")

    def io_values(self, io: str) -> list:
        """On-wire values of the Input/Output block (gate or pan/level)."""
        return list(self._io_payload(io)[l6helix.IO_PARAMS][l6helix.PARAMS_VALUES])

    def set_io_param(self, io: str, idx: int, value) -> None:
        """Change an Input/Output param, preserving its on-wire type."""
        self._checkpoint(tag=("io", io, idx))
        values = self._io_payload(io)[l6helix.IO_PARAMS][l6helix.PARAMS_VALUES]
        old = values[idx]
        if isinstance(old, bool):
            values[idx] = bool(value)
        elif isinstance(old, int) and not isinstance(value, float):
            values[idx] = int(value)
        else:
            values[idx] = float(value)

    def io_block_index(self, io: str) -> int:
        """Raw DSP_CHAIN index of the Input (0) / Output (last), for live
        writes with `device.set_param`."""
        cls = l6helix.CLASS_INPUT if io == "input" else l6helix.CLASS_OUTPUT
        full = self.body[l6helix.BODY_DSP0][l6helix.DSP_CHAIN]
        for i, e in enumerate(full):
            if e[l6helix.ENTRY_CLASS] == cls:
                return i
        raise ValueError(f"no {io!r} entry in the chain")

    def swap_model(self, slot: int, model_name: str) -> None:
        """Replace the slot block with `model_name` using its defaults."""
        info = catalog.model_info(model_name)
        if info is None:
            raise ValueError(f"unknown model: {model_name}")
        if info.wire_id is None or info.param_order is None:
            raise ValueError(
                f"{model_name}: no wire_id/param order in the catalog "
                "(pending harvest against the pedal)"
            )
        if info.wire_category is None:
            raise ValueError(f"{model_name}: no known on-wire category")
        self._check_swap_allowed(slot, model_name)
        self._checkpoint()
        if catalog.display_category(model_name) == "Looper":
            self._write_looper(slot, info)
            return
        values = [info.defaults[p] for p in info.param_order]
        n_extras = sum(1 for p in info.param_order if p.startswith("@"))
        entry = self._chain_entries()[slot]
        entry[l6helix.ENTRY_CLASS] = l6helix.CLASS_BLOCK
        entry[l6helix.ENTRY_PAYLOAD] = {
            l6helix.BLK_CATEGORY: info.wire_category,
            l6helix.BLK_ENABLED: True,
            l6helix.BLK_PARAMS: {
                l6helix.PARAMS_TOTAL: len(values),
                l6helix.PARAMS_SNAPSHOTTABLE: len(values) - n_extras,
                l6helix.PARAMS_VALUES: values,
            },
            l6helix.BLK_MODEL: {
                l6helix.MODEL_NO_SNAPSHOT_BYPASS: False,
                l6helix.MODEL_ID: info.wire_id,
                l6helix.MODEL_UNKNOWN_26: -1,
            },
            # Second params node, always empty in everything observed.
            BLK_PARAMS_AUX: {
                l6helix.PARAMS_TOTAL: 0,
                l6helix.PARAMS_SNAPSHOTTABLE: 0,
                l6helix.PARAMS_VALUES: [],
            },
        }

    def _write_looper(self, slot: int, info: catalog.ModelInfo) -> None:
        """Build the class-7 looper entry in the slot (spec03 follow-up).

        The looper is chain class 7 (see l6helix.CLASS_LOOPER): the model id
        lives directly at key 8 (no key-24 node), the params at key 7 (like
        input/output), and it stores only LOOPER_STORED_PARAMS values. Layout
        RE'd from the pedal. The live single-block write (device.set_model,
        op 40) only sends the wire_id and lets the pedal build the block; this
        keeps the in-memory body correct for saving the full preset.
        """
        values = [
            info.defaults[p]
            for p in info.param_order[:LOOPER_STORED_PARAMS]
        ]
        entry = self._chain_entries()[slot]
        entry[l6helix.ENTRY_CLASS] = l6helix.CLASS_LOOPER
        entry[l6helix.ENTRY_PAYLOAD] = {
            l6helix.LOOPER_MODEL_ID: info.wire_id,
            l6helix.BLK_CATEGORY: info.wire_category,
            l6helix.BLK_ENABLED: True,
            l6helix.IO_PARAMS: {
                l6helix.PARAMS_TOTAL: len(values),
                l6helix.PARAMS_SNAPSHOTTABLE: len(values),
                l6helix.PARAMS_VALUES: values,
            },
        }

    def slot_category(self, slot: int) -> str | None:
        """UI category of the block in the slot (None if empty)."""
        block = self.preset.chain[slot]
        if block is None:
            return None
        md = catalog.lookup(block.model_id)
        return catalog.display_category(md.name) if md else None

    def _check_swap_allowed(self, slot: int, model_name: str) -> None:
        """Restrict the model swap to the slot group (#5, see manual).

        An Amp only swaps for an Amp, a Cab for a Cab, etc.; Effects blocks
        swap among the pure effects. The slot category comes from the current
        block (or the effects group if empty). For EQ the group depends on the
        current model (Preset EQ vs Effects EQ, spec08).
        """
        block = self.preset.chain[slot]
        current = catalog.lookup(block.model_id) if block is not None else None
        current_name = current.name if current is not None else None
        allowed = catalog.swap_group(self.slot_category(slot), current_name)
        target = catalog.display_category(model_name)
        if target not in allowed:
            raise ValueError(
                f"{model_name} ({target}) is not compatible with this slot; "
                f"allowed: {sorted(allowed)}"
            )
        # spec08: within EQ, the block type (Preset vs Effects) must also
        # match — a dedicated Preset EQ does not host an Effects-EQ
        # (Acoustic Sim) or vice versa. Empty slot = Effects block.
        if target == "EQ":
            # Only the dedicated Preset EQ is "preset"; any other slot
            # (Effects block, holding an effect/Effects-EQ or empty) is "effects".
            slot_kind = (
                "preset"
                if current_name and catalog.eq_kind(current_name) == "preset"
                else "effects"
            )
            if catalog.eq_kind(model_name) != slot_kind:
                raise ValueError(
                    f"{model_name} is not a {slot_kind!r}-type EQ compatible "
                    "with this slot"
                )

    def clear_slot(self, slot: int) -> None:
        """Empty the slot and clear any controller/footswitch referencing it."""
        self._checkpoint()
        pedal_targets = self._controller_targets()
        entry = self._chain_entries()[slot]
        entry[l6helix.ENTRY_CLASS] = l6helix.CLASS_EMPTY
        entry[l6helix.ENTRY_PAYLOAD] = None
        nums = [n for n, s in pedal_targets.items() if s == slot]
        if nums:
            self._remove_controllers(nums)
        fs = self.body.get(l6helix.BODY_FOOTSWITCH) or {}
        groups = fs.get(FS_GROUPS)
        if isinstance(groups, list):
            for gi, group in enumerate(groups):
                if not group:
                    continue
                kept = [
                    e for e in group if e[FS_TARGET][FST_BLOCK] != slot + 1
                ]
                groups[gi] = kept or None

    def bypass_assignments(self) -> dict[int, str]:
        """slot -> label of the switch that toggles its bypass ("FS2", "EXP Toe").

        Read-only; feeds the labels over the Signal Flow blocks (groups 0-7 of
        body[3][8] are FS1-FS8, group 8 is the expression pedal toe switch).
        """
        out: dict[int, str] = {}
        fs = self.body.get(l6helix.BODY_FOOTSWITCH) or {}
        for gi, group in enumerate(fs.get(FS_GROUPS) or []):
            label = "EXP Toe" if gi == FS_GROUP_EXP_TOE else f"FS{gi + 1}"
            for entry in group or []:
                out[entry[FS_TARGET][FST_BLOCK] - 1] = label
        return out

    def _remove_controllers(self, nums: list[int]) -> None:
        """Remove from body[4] the controllers with those @controller numbers."""
        for entries in self.body.get(l6helix.BODY_CONTROLLER) or []:
            if entries:
                entries[:] = [
                    c for c in entries if c[CTL_DEF][CTLD_NUM] not in nums
                ]

    # --- bypass / controller assignments (spec 09) ---

    def _fs_groups(self) -> list:
        fs = self.body.get(l6helix.BODY_FOOTSWITCH) or {}
        return fs.get(FS_GROUPS) or []

    def _fs_entry(self, slot: int) -> dict | None:
        """body[3] bypass entry referencing the block, or None."""
        for group in self._fs_groups():
            for entry in group or []:
                if entry[FS_TARGET][FST_BLOCK] == slot + 1:
                    return entry
        return None

    def bypass_target(self, slot: int) -> str | None:
        """Label of the switch toggling the block bypass ("FS3"), or None."""
        for gi, group in enumerate(self._fs_groups()):
            for entry in group or []:
                if entry[FS_TARGET][FST_BLOCK] == slot + 1:
                    return BYPASS_TARGETS[gi]
        return None

    def bypass_blocks_on(self, target: str) -> list[int]:
        """Slots whose bypass hangs off the target, in order ('See All Assignments')."""
        gi = BYPASS_TARGETS.index(target)
        groups = self._fs_groups()
        group = groups[gi] if gi < len(groups) else None
        return [e[FS_TARGET][FST_BLOCK] - 1 for e in (group or [])]

    def footswitch_label(self, slot: int) -> str | None:
        """Customizable label of the FS assigned to the block (or None)."""
        e = self._fs_entry(slot)
        return l6helix.text(e[FS_TARGET][FST_LABEL]) if e else None

    def footswitch_color(self, slot: int) -> int | None:
        """Resolved Auto color (key 6, RGB-ish) of the block FS, or None.

        This is the per-category color; the color CHOSEN by the user is the
        palette index in `footswitch_color_index`.
        """
        e = self._fs_entry(slot)
        return e[FS_TARGET][FST_LEDCOLOR] if e else None

    def footswitch_color_index(self, slot: int) -> int | None:
        """FS palette color index (0=Auto … 11=Off), or None.

        Reads entry key 16 gated by key 15 ("custom"); see spec 09.
        """
        e = self._fs_entry(slot)
        if e is None:
            return None
        return e.get(FS_COLOR_INDEX, 0) if e.get(FS_COLOR_CUSTOM) else 0

    # per-FOOTSWITCH operations (not per-block): label/color/list of the whole
    # switch, for the context menu of each FS button on the panel (spec 09).

    def footswitch_label_for(self, target: str) -> str | None:
        """Label of footswitch `target` ("Multiple" if it differs per block)."""
        labels = {self.footswitch_label(s) for s in self.bypass_blocks_on(target)}
        if not labels:
            return None
        return next(iter(labels)) if len(labels) == 1 else "Multiple"

    def footswitch_color_index_for(self, target: str) -> int:
        """Color index of footswitch `target` (0=Auto if none/differs)."""
        idxs = {self.footswitch_color_index(s) for s in self.bypass_blocks_on(target)}
        return next(iter(idxs)) if len(idxs) == 1 else 0

    def set_fs_label_for(self, target: str, text: str) -> None:
        """Rename ALL blocks hanging off footswitch `target`."""
        slots = self.bypass_blocks_on(target)
        if not slots:
            raise ValueError(f"footswitch {target} has no assignments")
        self._checkpoint()
        for slot in slots:
            self._fs_entry(slot)[FS_TARGET][FST_LABEL] = text + "\x00"

    def reset_fs_label_for(self, target: str) -> None:
        """Reset footswitch `target` label to the model name."""
        slots = self.bypass_blocks_on(target)
        if not slots:
            return
        self._checkpoint()
        for slot in slots:
            self._fs_entry(slot)[FS_TARGET][FST_LABEL] = (
                self._model_display(slot) + "\x00"
            )

    def set_fs_color_index_for(self, target: str, index: int) -> None:
        """Set the LED color of ALL blocks on footswitch `target`."""
        if not 0 <= index < len(FS_COLOR_NAMES):
            raise ValueError(f"color index out of range: {index}")
        slots = self.bypass_blocks_on(target)
        if not slots:
            raise ValueError(f"footswitch {target} has no assignments")
        self._checkpoint()
        for slot in slots:
            e = self._fs_entry(slot)
            e[FS_COLOR_INDEX] = int(index)
            e[FS_COLOR_CUSTOM] = index != 0

    def controller_assignment(self, slot: int, param_idx: int) -> dict | None:
        """`{source, num, min, max}` of the parameter's controller, or None."""
        for s, pidx, ctl_def in self._controllers_in_order():
            if s == slot and pidx == param_idx:
                num = ctl_def[CTLD_NUM]
                return {
                    "source": CTRL_SOURCE_LABELS.get(num, f"#{num}"),
                    "num": num,
                    "min": ctl_def[CTLD_MIN],
                    "max": ctl_def[CTLD_MAX],
                }
        return None

    def _model_display(self, slot: int) -> str:
        """Display name of the model in the slot (default FS label)."""
        blk = self.preset.chain[slot]
        md = catalog.lookup(blk.model_id) if blk else None
        info = catalog.model_info(md.name) if md else None
        if info is not None and info.display_name:
            return info.display_name
        return f"Block {slot + 1}"

    # bypass mutations (body[3]) — known structure (spec 09)

    def _ensure_fs_groups(self) -> list:
        fs = self.body.get(l6helix.BODY_FOOTSWITCH)
        if not isinstance(fs, dict):
            fs = {7: 2, FS_GROUPS: [None] * (FS_GROUP_EXP_TOE + 1)}
            self.body[l6helix.BODY_FOOTSWITCH] = fs
        groups = fs.get(FS_GROUPS)
        if not isinstance(groups, list):
            groups = [None] * (FS_GROUP_EXP_TOE + 1)
            fs[FS_GROUPS] = groups
        while len(groups) <= FS_GROUP_EXP_TOE:
            groups.append(None)
        return groups

    def _detach_fs_entry(self, groups: list, slot: int) -> dict | None:
        """Removes the block's bypass entry from all groups; returns it."""
        found = None
        for gi, group in enumerate(groups):
            if not group:
                continue
            kept = []
            for e in group:
                if e[FS_TARGET][FST_BLOCK] == slot + 1:
                    found = e
                else:
                    kept.append(e)
            groups[gi] = kept or None
        return found

    def _new_fs_entry(self, slot: int) -> dict:
        """New bypass entry, cloning the skeleton observed in body[3]."""
        blk = self.preset.chain[slot]
        return {
            FS_ORDER: 0,
            FS_TARGET: {
                0: 1,
                FST_LABEL: self._model_display(slot) + "\x00",
                FST_LEDCOLOR: DEFAULT_LED_COLOR,
                FST_ENABLED: bool(blk.enabled) if blk else False,
                FST_BLOCK: slot + 1,
            },
            FS_MOMENTARY: False,
            13: False,
            14: "\x00",
            15: False,
            16: 0,
        }

    def set_bypass_assign(self, slot: int, target: str) -> None:
        """Assigns (or moves) the block's bypass to the footswitch/toe `target`.

        A block can only hang off one switch at a time (it is moved if it
        already had an assignment); multiple blocks can share the same switch.
        """
        if target not in BYPASS_TARGETS:
            raise ValueError(f"unknown bypass target: {target!r}")
        if self.preset.chain[slot] is None:
            raise ValueError(f"slot {slot} is empty")
        self._checkpoint()
        groups = self._ensure_fs_groups()
        entry = self._detach_fs_entry(groups, slot) or self._new_fs_entry(slot)
        gi = BYPASS_TARGETS.index(target)
        group = groups[gi] or []
        entry[FS_ORDER] = 0 if not group else max(e[FS_ORDER] for e in group) + 1
        entry[FS_TARGET][FST_BLOCK] = slot + 1
        groups[gi] = group + [entry]

    def clear_bypass_assign(self, slot: int) -> None:
        """Removes the block's bypass assignment (None button on the panel)."""
        self._checkpoint()
        self._detach_fs_entry(self._ensure_fs_groups(), slot)

    def set_fs_label(self, slot: int, text: str) -> None:
        """Renames the label of the FS assigned to the block."""
        e = self._fs_entry(slot)
        if e is None:
            raise ValueError(f"slot {slot} has no bypass assignment")
        self._checkpoint()
        e[FS_TARGET][FST_LABEL] = text + "\x00"

    def reset_fs_label(self, slot: int) -> None:
        """Resets the FS label to the model's display name."""
        self.set_fs_label(slot, self._model_display(slot))

    def set_fs_color_index(self, slot: int, index: int) -> None:
        """Sets the FS LED color by palette index (0=Auto … 11=Off).

        Writes key 16 (index) and key 15 (custom = index != Auto); see
        spec 09. Key 6 (resolved Auto) is left as-is, matching the pedal.
        """
        if not 0 <= index < len(FS_COLOR_NAMES):
            raise ValueError(f"color index out of range: {index}")
        e = self._fs_entry(slot)
        if e is None:
            raise ValueError(f"slot {slot} has no bypass assignment")
        self._checkpoint()
        e[FS_COLOR_INDEX] = int(index)
        e[FS_COLOR_CUSTOM] = index != 0

    # controller mutations (body[4]) — only what is verifiable offline (spec 09)

    def set_controller_min_max(
        self, slot: int, param_idx: int, lo: float, hi: float
    ) -> None:
        """Adjusts Min/Max of an EXISTING controller (known keys)."""
        for s, pidx, ctl_def in self._controllers_in_order():
            if s == slot and pidx == param_idx:
                self._checkpoint(tag=("ctl", slot, param_idx))
                ctl_def[CTLD_MIN] = float(lo)
                ctl_def[CTLD_MAX] = float(hi)
                return
        raise ValueError(f"slot {slot} param {param_idx} has no controller")

    def clear_controller_assign(self, slot: int, param_idx: int) -> None:
        """Removes the parameter's controller (None button) and cleans up snapshots."""
        num = None
        for s, pidx, ctl_def in self._controllers_in_order():
            if s == slot and pidx == param_idx:
                num = ctl_def[CTLD_NUM]
                break
        if num is None:
            raise ValueError(f"slot {slot} param {param_idx} no tiene controller")
        self._checkpoint()
        self._remove_controllers([num])
        self._reset_snapshot_controller(num)

    def _reset_snapshot_controller(self, num: int) -> None:
        """Resets to 'empty' the per-snapshot values of controller number `num`."""
        snaps = self.body.get(l6helix.BODY_SNAPSHOTS) or {}
        for snap in snaps.get(l6helix.SNAPS_LIST) or []:
            for entry in snap.get(SNAP_CTL_VALUES) or []:
                if entry[1] == num - 1:
                    entry[0], entry[1], entry[2] = False, SNAP_CTL_NONE, None

    def set_controller_assign(
        self, slot: int, param_idx: int, source: str, lo: float = 0.0, hi: float = 1.0
    ) -> None:
        """Creates a new controller. RE-blocked for arbitrary params.

        Only the target could be reconstructed for EXP1→wah / EXP2→volume
        (which already exist by default); any other case raises
        `ControllerAssignUnsupported` because the target block binding is
        not reverse-engineered. See docs/specs/09-bypass-control-assign.md.
        """
        raise ControllerAssignUnsupported(
            f"creating a controller ({source}) on slot {slot} param {param_idx} "
            "requires RE/harvesting against the pedal (see spec 09)"
        )

    def to_blob(self) -> bytes:
        """Re-serializes the edited body to the pedal's l6-helix container."""
        return l6helix.build_blob(self.body)

    def block_index(self, slot: int) -> int:
        """On-wire index (k101.98) of the block in the chain slot.

        This is the RAW INDEX of the entry within DSP_CHAIN, which includes
        INPUT at position 0 (and OUTPUT at the end). Since `slot` counts only
        slotted entries (blocks and empties, without input/output), the on-wire
        index is usually `slot + 1`. Verified against the pedal: set_param with
        k98 = raw index changes the correct block; using the non-empty block
        count pointed to the wrong block (the device ACKs and ignores).
        """
        entries = self._chain_entries()
        if slot < 0 or slot >= len(entries):
            raise ValueError(
                f"slot {slot} out of range (0-{len(entries) - 1})"
            )
        if entries[slot][l6helix.ENTRY_CLASS] not in _OCCUPIED_CLASSES:
            raise ValueError(f"slot {slot} is empty")
        full = self.body[l6helix.BODY_DSP0][l6helix.DSP_CHAIN]
        count = -1
        for raw_idx, entry in enumerate(full):
            if entry[l6helix.ENTRY_CLASS] in _SLOT_CLASSES:
                count += 1
                if count == slot:
                    return raw_idx
        raise ValueError(f"slot {slot} not found in DSP_CHAIN")

    def slot_from_block_index(self, raw_idx: int) -> int | None:
        """Inverse of `block_index`: chain slot from a raw DSP_CHAIN index.

        The pedal notifies changes with the on-wire index (k101.98 = raw index
        within DSP_CHAIN, with INPUT at 0). This translates it to the slot
        used by the UI (counting only blocks and empties). Returns None if the
        index does not fall on a slotted entry (e.g. input/output or out of range).
        """
        full = self.body[l6helix.BODY_DSP0][l6helix.DSP_CHAIN]
        if raw_idx < 0 or raw_idx >= len(full):
            return None
        count = -1
        for i, entry in enumerate(full):
            if entry[l6helix.ENTRY_CLASS] in _SLOT_CLASSES:
                count += 1
                if i == raw_idx:
                    return count
        return None

    # --- export .pgp ---

    def to_pgp(self, name: str) -> dict:
        """JSON L6Preset (.pgp format from POD Go Edit) of the current state."""
        body = self.body
        meta = body.get(l6helix.BODY_META) or {}
        tone = {
            "controller": {"dsp0": self._pgp_controllers()},
            "dsp0": self._pgp_dsp0(),
            "dsp1": {},
            "footswitch": {"dsp0": self._pgp_footswitch()},
            "global": self._pgp_global(),
        }
        tone.update(self._pgp_snapshots())
        return {
            "data": {
                "device": DEVICE_ID,
                "device_version": meta.get(35),
                "meta": {
                    "application": APP_NAME,
                    "appversion": APP_VERSION,
                    "build_sha": l6helix.text(meta.get(37, "")),
                    "modifieddate": int(time.time()),
                    "name": name,
                },
                "tone": tone,
            },
            "meta": {"original": 0, "pbn": 0, "premium": 0},
            "schema": PGP_SCHEMA,
            "version": PGP_VERSION,
        }

    def _pgp_dsp0(self) -> dict:
        out: dict = {}
        slot = 0
        for entry in self.body[l6helix.BODY_DSP0][l6helix.DSP_CHAIN]:
            cls = entry[l6helix.ENTRY_CLASS]
            payload = entry[l6helix.ENTRY_PAYLOAD]
            if cls == l6helix.CLASS_INPUT:
                values = payload[l6helix.IO_PARAMS][l6helix.PARAMS_VALUES]
                out["input"] = {
                    "@input": payload[l6helix.IO_INPUT_SETTING],
                    "@model": INPUT_MODEL,
                    **dict(zip(INPUT_PARAM_NAMES, values)),
                }
            elif cls == l6helix.CLASS_OUTPUT:
                values = payload[l6helix.IO_PARAMS][l6helix.PARAMS_VALUES]
                out["output"] = {
                    "@model": OUTPUT_MODEL,
                    "@output": payload[l6helix.IO_OUTPUT_SETTING],
                    **dict(zip(OUTPUT_PARAM_NAMES, values)),
                }
            elif cls == l6helix.CLASS_EMPTY:
                # The official .pgp emits the empty slot as a placeholder.
                out[f"block{slot}"] = {"@position": slot}
                slot += 1
            elif cls == l6helix.CLASS_BLOCK:
                out[f"block{slot}"] = self._pgp_block(payload, slot)
                slot += 1
            elif cls == l6helix.CLASS_LOOPER:
                # The .pgp representation of the looper is not reverse-engineered
                # yet; refuse rather than emit a malformed/misaligned export.
                raise UnknownModelError(
                    f"slot {slot}: .pgp export of the looper is not supported yet"
                )
        return out

    def _pgp_block(self, payload: dict, position: int) -> dict:
        model_id = payload[l6helix.BLK_MODEL][l6helix.MODEL_ID]
        md = catalog.lookup(model_id)
        info = catalog.model_info(md.name) if md else None
        if md is None or info is None:
            raise UnknownModelError(
                f"block in slot {position}: model {model_id} outside the "
                "catalog (run tools/harvest_catalog.py)"
            )
        values = payload[l6helix.BLK_PARAMS][l6helix.PARAMS_VALUES]
        if len(values) != len(md.params):
            raise UnknownModelError(
                f"{md.name}: {len(values)} values vs {len(md.params)} "
                "names (catalog outdated for this firmware)"
            )
        block = {
            "@enabled": payload[l6helix.BLK_ENABLED],
            "@model": md.name,
        }
        if payload[l6helix.BLK_CATEGORY] == CATEGORY_AMP:
            # Official editor attribute that does not travel in the blob; 1.0 is
            # the default (validated in both fixtures).
            block["@bypassvolume"] = 1.0
        block |= {
            "@no_snapshot_bypass": payload[l6helix.BLK_MODEL].get(
                l6helix.MODEL_NO_SNAPSHOT_BYPASS, False
            ),
            "@position": position,
            "@type": info.type,
        }
        block.update(zip(md.params, values))
        return block

    def _block_param_names(self, slot: int) -> tuple[str, ...]:
        model_id = _entry_model_id(self._chain_entries()[slot])
        md = catalog.lookup(model_id)
        return md.params if md else ()

    def _controller_targets(self) -> dict[int, int]:
        """@controller number → target block slot (role-based binding)."""
        targets: dict[int, int] = {}
        for slot, blk in enumerate(self.preset.chain):
            if blk is None:
                continue
            md = catalog.lookup(blk.model_id)
            if md is None:
                continue
            if md.name.startswith("HD2_Wah"):
                targets.setdefault(1, slot)
            elif md.name.startswith("HD2_Vol"):
                targets.setdefault(2, slot)
        return targets

    def _controllers_in_order(self):
        """(slot, param_idx, def) for each controller that can be bound."""
        targets = self._controller_targets()
        for entries in self.body.get(l6helix.BODY_CONTROLLER) or []:
            for ctl in entries or []:
                ctl_def = ctl[CTL_DEF]
                slot = targets.get(ctl_def[CTLD_NUM])
                if slot is not None:
                    yield slot, ctl_def[CTLD_PARAM], ctl_def

    def _pgp_controllers(self) -> dict:
        out: dict = {}
        for slot, param_idx, ctl_def in self._controllers_in_order():
            names = self._block_param_names(slot)
            pname = names[param_idx] if param_idx < len(names) else f"P{param_idx}"
            out.setdefault(f"block{slot}", {})[pname] = {
                "@controller": ctl_def[CTLD_NUM],
                "@max": ctl_def[CTLD_MAX],
                "@min": ctl_def[CTLD_MIN],
            }
        return out

    def _pgp_footswitch(self) -> dict:
        out: dict = {}
        fs = self.body.get(l6helix.BODY_FOOTSWITCH) or {}
        for gi, group in enumerate(fs.get(FS_GROUPS) or []):
            for entry in group or []:
                target = entry[FS_TARGET]
                item = {
                    "@fs_enabled": target[FST_ENABLED],
                    "@fs_index": gi + 1,
                    "@fs_label": l6helix.text(target[FST_LABEL]),
                    "@fs_ledcolor": target[FST_LEDCOLOR],
                    "@fs_momentary": bool(entry.get(FS_MOMENTARY, False)),
                }
                if entry.get(FS_ORDER, 0) == 0:
                    item["@fs_primary"] = True
                out[f"block{target[FST_BLOCK] - 1}"] = item
        return out

    def _pgp_global(self) -> dict:
        glob = self.body.get(l6helix.BODY_GLOBAL) or {}
        snaps = self.body.get(l6helix.BODY_SNAPSHOTS) or {}
        return {
            "@current_snapshot": snaps.get(l6helix.SNAPS_CURRENT, 0),
            # The official editor's cursor position does not travel in the blob.
            "@cursor_group": "block0",
            "@model": "@global_params",
            "@pedalstate": snaps.get(SNAPS_PEDALSTATE, 0),
            "@tempo": glob.get(l6helix.GLOBAL_TEMPO),
        }

    def _pgp_snapshots(self) -> dict:
        snaps = self.body.get(l6helix.BODY_SNAPSHOTS) or {}
        controllers = list(self._controllers_in_order())
        out: dict = {}
        for i, snap in enumerate(snaps.get(l6helix.SNAPS_LIST) or []):
            enables = snap[l6helix.SNAP_ENABLES]
            # Per-snapshot controller values, indexed by number-1.
            by_num = {
                entry[1]: entry
                for entry in snap[SNAP_CTL_VALUES]
                if entry[2] is not None
            }
            ctl_out: dict = {}
            for slot, param_idx, ctl_def in controllers:
                fs_enabled, _, value = by_num[ctl_def[CTLD_NUM] - 1][:3]
                names = self._block_param_names(slot)
                pname = (
                    names[param_idx] if param_idx < len(names) else f"P{param_idx}"
                )
                ctl_out.setdefault(f"block{slot}", {})[pname] = {
                    "@fs_enabled": fs_enabled,
                    "@value": value,
                }
            out[f"snapshot{i}"] = {
                "@ledcolor": snap.get(SNAP_LEDCOLOR, 0),
                "@name": l6helix.text(snap[l6helix.SNAP_NAME]),
                "@pedalstate": snap.get(11, 0),
                "@tempo": snap[l6helix.SNAP_TEMPO],
                "@valid": snap[l6helix.SNAP_VALID],
                "blocks": {
                    "dsp0": {
                        f"block{j}": enables[j + 1][1] for j in range(10)
                    }
                },
                "controllers": {"dsp0": ctl_out},
            }
        return out

    # --- import .pgp ---

    @classmethod
    def from_pgp(cls, pgp: dict) -> tuple[PresetEditor, list[str]]:
        tone = pgp.get("data", {}).get("tone", {})
        dsp0 = tone.get("dsp0", {})
        warnings: list[str] = []
        body: dict = {}
        body[0] = cls._pgp_to_dsp0(dsp0, warnings)
        body[1] = {}
        body[2] = {}
        body[3] = _pgp_to_footswitch(tone.get("footswitch", {}).get("dsp0", {}))
        body[4] = _pgp_to_controllers(
            tone.get("controller", {}).get("dsp0", {}), dsp0
        )
        body[5] = _pgp_to_global(tone.get("global", {}))
        body[7] = _pgp_to_meta(pgp.get("data", {}))
        body[10] = _pgp_to_snapshots(tone)
        dummy = l6helix.Preset(
            chain=[], input_params=[], output_params=[], tempo=None,
            current_snapshot=0, snapshots=[], product="", firmware="",
            body=body,
        )
        editor = cls(dummy)
        return editor, warnings

    @staticmethod
    def _pgp_to_dsp0(dsp0: dict, warnings: list[str]) -> dict:
        full: list[dict] = []
        # input first, then blocks in order, then output last
        keys = [k for k in ("input",) if k in dsp0]
        keys += sorted(k for k in dsp0 if k.startswith("block"))
        keys += [k for k in ("output",) if k in dsp0]
        for key in keys:
            value = dsp0[key]
            if key == "input":
                full.append(_pgp_to_input(value))
            elif key == "output":
                full.append(_pgp_to_output(value))
            elif isinstance(value, dict):
                model = value.get("@model")
                if model is None:
                    full.append({l6helix.ENTRY_CLASS: l6helix.CLASS_EMPTY,
                                 l6helix.ENTRY_PAYLOAD: None})
                else:
                    info = catalog.model_info(model)
                    if (info is not None and info.wire_id is not None
                            and info.param_order is not None
                            and info.wire_category is not None):
                        full.append(_pgp_to_block(value, info))
                    else:
                        warnings.append(model)
                        full.append({l6helix.ENTRY_CLASS: l6helix.CLASS_EMPTY,
                                     l6helix.ENTRY_PAYLOAD: None})
        return {21: 0, l6helix.DSP_CHAIN: full}


def _pgp_to_input(value: dict) -> dict:
    return {
        l6helix.ENTRY_CLASS: l6helix.CLASS_INPUT,
        l6helix.ENTRY_PAYLOAD: {
            l6helix.IO_INPUT_SETTING: value.get("@input", 0),
            l6helix.IO_PARAMS: {
                l6helix.PARAMS_TOTAL: 3,
                l6helix.PARAMS_SNAPSHOTTABLE: 3,
                l6helix.PARAMS_VALUES: [
                    bool(value.get("noiseGate", False)),
                    float(value.get("threshold", -96.0)),
                    float(value.get("decay", 0.1)),
                ],
            },
        },
    }


def _pgp_to_output(value: dict) -> dict:
    return {
        l6helix.ENTRY_CLASS: l6helix.CLASS_OUTPUT,
        l6helix.ENTRY_PAYLOAD: {
            l6helix.IO_OUTPUT_SETTING: value.get("@output", 0),
            l6helix.IO_PARAMS: {
                l6helix.PARAMS_TOTAL: 2,
                l6helix.PARAMS_SNAPSHOTTABLE: 2,
                l6helix.PARAMS_VALUES: [
                    float(value.get("pan", 0.5)),
                    float(value.get("gain", 0.0)),
                ],
            },
        },
    }


def _pgp_to_block(value: dict, info: catalog.ModelInfo) -> dict:
    order = info.param_order
    values = []
    for pname in order:
        if pname in value:
            v = value[pname]
        elif pname in info.defaults:
            v = info.defaults[pname]
        else:
            v = 0.0
        values.append(v)
    n_extras = sum(1 for p in order if p.startswith("@"))
    enabled = value.get("@enabled", True)
    if isinstance(enabled, (int, float)):
        enabled = bool(enabled)
    return {
        l6helix.ENTRY_CLASS: l6helix.CLASS_BLOCK,
        l6helix.ENTRY_PAYLOAD: {
            l6helix.BLK_CATEGORY: info.wire_category,
            l6helix.BLK_ENABLED: enabled,
            l6helix.BLK_PARAMS: {
                l6helix.PARAMS_TOTAL: len(values),
                l6helix.PARAMS_SNAPSHOTTABLE: len(values) - n_extras,
                l6helix.PARAMS_VALUES: values,
            },
            BLK_PARAMS_AUX: {
                l6helix.PARAMS_TOTAL: 0,
                l6helix.PARAMS_SNAPSHOTTABLE: 0,
                l6helix.PARAMS_VALUES: [],
            },
            l6helix.BLK_MODEL: {
                l6helix.MODEL_NO_SNAPSHOT_BYPASS: bool(
                    value.get("@no_snapshot_bypass", False)
                ),
                l6helix.MODEL_ID: info.wire_id,
                l6helix.MODEL_UNKNOWN_26: -1,
            },
        },
    }


def _block_key_to_slot(bk: str) -> int:
    return int(bk.replace("block", ""))


def _param_name_to_idx(bk: str, pname: str, dsp0: dict) -> int:
    block = dsp0.get(bk, {})
    model = block.get("@model", "")
    info = catalog.model_info(model)
    if info is not None and info.param_order is not None:
        if pname in info.param_order:
            return info.param_order.index(pname)
    return 0


def _pgp_to_footswitch(tone_fs: dict) -> dict:
    groups: list = [None] * 9
    for bk, entry in tone_fs.items():
        slot = _block_key_to_slot(bk)
        gi = entry.get("@fs_index", 1) - 1
        if gi >= len(groups):
            continue
        new_entry = {
            FS_ORDER: 0 if entry.get("@fs_primary") else 999,
            FS_TARGET: {
                0: 1,
                FST_LABEL: entry.get("@fs_label", "") + "\x00",
                FST_LEDCOLOR: entry.get("@fs_ledcolor", 0),
                FST_ENABLED: bool(entry.get("@fs_enabled", True)),
                FST_BLOCK: slot + 1,
            },
            FS_MOMENTARY: bool(entry.get("@fs_momentary", False)),
            13: False,
            14: "\x00",
            FS_COLOR_CUSTOM: False,
            FS_COLOR_INDEX: 0,
        }
        groups[gi] = (groups[gi] or []) + [new_entry]
    for gi, group in enumerate(groups):
        if not group:
            continue
        group.sort(key=lambda e: e[FS_ORDER])
        for idx, entry in enumerate(group):
            entry[FS_ORDER] = idx
    return {7: 2, FS_GROUPS: groups}


def _pgp_to_controllers(tone_ctl: dict, dsp0: dict) -> list:
    out: list = [None] * 12
    for bk, params in tone_ctl.items():
        slot = _block_key_to_slot(bk)
        for pname, ctl_info in params.items():
            num = ctl_info["@controller"]
            param_idx = _param_name_to_idx(bk, pname, dsp0)
            while len(out) <= num:
                out.append(None)
            entry = {
                0: num - 1,
                CTL_DEF: {
                    CTLD_NUM: num,
                    1: 4,
                    CTLD_MIN: ctl_info.get("@min", 0.0),
                    CTLD_MAX: ctl_info.get("@max", 1.0),
                    CTLD_PARAM: param_idx,
                    5: slot + 1,
                    6: {28: 0, 29: 0, 41: False},
                    7: 0,
                },
            }
            if out[num] is None:
                out[num] = []
            out[num].append(entry)
    return out


def _pgp_to_global(tone_global: dict) -> dict:
    return {l6helix.GLOBAL_TEMPO: tone_global.get("@tempo", 120.0)}


def _pgp_to_meta(data: dict) -> dict:
    dev_ver = data.get("device_version")
    meta = data.get("meta", {})
    sha = meta.get("build_sha", "")
    return {
        35: dev_ver,
        36: "P34\x00",
        37: (sha + "\x00") if sha else "",
    }


def _pgp_to_snapshots(tone: dict) -> dict:
    ctl_map: dict[tuple[str, str], int] = {}
    for bk, params in tone.get("controller", {}).get("dsp0", {}).items():
        for pname, ctl_info in params.items():
            ctl_map[(bk, pname)] = ctl_info["@controller"]

    global_info = tone.get("global", {})
    current_snapshot = global_info.get("@current_snapshot", 0)
    pedalstate = global_info.get("@pedalstate", 0)

    snap_list = []
    for i in range(4):
        sk = f"snapshot{i}"
        snap_data = tone.get(sk, {})
        blocks = snap_data.get("blocks", {}).get("dsp0", {})
        snap_controllers = snap_data.get("controllers", {}).get("dsp0", {})

        enables = [[False, True]]
        for j in range(10):
            enabled = bool(blocks.get(f"block{j}", True))
            enables.append([False, enabled])
        enables.append([False, True])

        ctl_values = []
        for ctl_num in range(1, 65):
            found = False
            for (bk, pname), ctl_n in ctl_map.items():
                if ctl_n == ctl_num and bk in snap_controllers:
                    if pname in snap_controllers[bk]:
                        sc = snap_controllers[bk][pname]
                        ctl_values.append([
                            bool(sc.get("@fs_enabled", False)),
                            ctl_num - 1,
                            sc.get("@value"),
                        ])
                        found = True
                        break
            if not found:
                ctl_values.append([False, 64, None])

        snap_list.append({
            l6helix.SNAP_VALID: bool(snap_data.get("@valid", False)),
            SNAP_CTL_VALUES: ctl_values,
            l6helix.SNAP_ENABLES: enables,
            l6helix.SNAP_NAME: (
                snap_data.get("@name", f"SNAPSHOT {i + 1}") + "\x00"
            ),
            l6helix.SNAP_TEMPO: snap_data.get("@tempo", 120.0),
            11: snap_data.get("@pedalstate", 0),
            SNAP_LEDCOLOR: snap_data.get("@ledcolor", 0),
        })

    return {
        l6helix.SNAPS_CURRENT: current_snapshot,
        SNAPS_PEDALSTATE: pedalstate,
        l6helix.SNAPS_LIST: snap_list,
    }
