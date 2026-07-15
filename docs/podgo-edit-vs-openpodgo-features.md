# POD Go Edit vs PodGo Lab — Feature Comparison Matrix

Based on the *POD Go Edit Pilot's Guide* (v2.50) compared against the current
PodGo Lab code (June 2026).

**Legend:**
- ✅ = implemented (and tested offline)
- 🟡 = partial / read-only / gated
- ❌ = not implemented
- 🔬 = requires live validation with the pedal

---

## CORE — USB Infrastructure and Protocol

| Code | Feature | Status | Notes |
|------|---------|--------|-------|
| C-01 | Bulk USB transport (5-packet handshake, session) | ✅ | `usb_transport.py`, `session.py` |
| C-02 | Streaming + preset parsing (MessagePack) | ✅ | `preset.py`, pattern scan |
| C-03 | PodGo API (connect, list_setlists, list_presets) | ✅ | `device.py` |
| C-04 | MIDI via ALSA (PC, CC32, snapshots, FS, tap) | ✅ | `midi.py`, via `amidi` |
| C-05 | 571-model catalog from official resources | ✅ 🔬 | `catalog.py` + `data/models.json`. Validate against pedal. |
| C-06 | Write to pedal (set_param, set_model, save, change_preset) | ✅ 🔬 | `device.py` + `session.py` (WriteSession). Pending visual verification. |
| C-07 | Bidirectional live sync (EventSession + NotificationReader) | ✅ 🔬 | `notifications.py` + dispatcher in `main_window.py`. 23 tests. |
| C-08 | Block reorder (write_chain_blob) | ✅ 🔬 | `device.write_chain_blob()`. Pending live caret verification. |
| C-09 | "Edited preset" indicator (spec 06) | 🟡 | Gated by `_OBJ14_CRC_CONFIRMED`. RE done offline, real checksum missing. |
| C-10 | Undo/Redo in in-memory editor | ✅ | `editor.EditorState.undo_stack` |

---

## LIBRARIAN — Preset Browser

| Code | Feature | Status | Notes |
|------|---------|--------|-------|
| L-01 | List setlists (Factory + User, 8 each) | ✅ | `librarian.py` |
| L-02 | List presets by setlist (slots 0-127) | ✅ | |
| L-03 | Recall preset by click | ✅ | `change_preset()` |
| L-04 | Preset search/filter by name | ✅ | QSortFilterProxyModel in `librarian.py` |
| L-05 | Drag presets between slots (reorder on pedal) | ✅ 🔬 | |
| L-06 | Import preset (.pgp) | ✅ | `editor.from_pgp()` |
| L-07 | Export preset (.pgp) | ✅ | `editor.to_pgp()`, round-trip validated |
| L-08 | **IR Library** (128 slots + import/export .wav/.hir) | ❌ | No code or spec yet. .hir format = header + IR data. |
| L-09 | **Backup/Restore** (.pgb) | 🟡 | `pgb.py` reads backups. Backup write + UI missing. |

---

## SIGNAL FLOW — Block Chain

| Code | Feature | Status | Notes |
|------|---------|--------|-------|
| S-01 | Block chain view | ✅ | `signal_flow.py` |
| S-02 | Drag & drop to reorder | ✅ | |
| S-03 | Bypass/engage blocks | ✅ | |
| S-04 | State indicators (● active, ⊕ bypass, etc.) | ✅ | |
| S-05 | Visual insertion caret | ✅ 🔬 | Spec 05. Pending live verification. |
| S-06 | Acoustic Sim (pickup selection) | ✅ 🔬 | Spec 08. Pending live verification. |
| S-07 | EQ effects vs Preset EQ (model subset) | ✅ 🔬 | Spec 08. Pending live verification. |
| S-08 | **Detailed Bypass/Control view** | ✅ 🔬 | Spec 09. `BypassControlPanel` (Ctrl+B toggle, parameter menu, selector grid, Min/Max, list). Pending live verification. |

---

## INSPECTOR — Edit Panel

| Code | Feature | Status | Notes |
|------|---------|--------|-------|
| I-01 | Parameter panel (knobs/sliders/combos) | ✅ | `inspector.py` |
| I-02 | Model selector (categories + search) | ✅ | `ModelSelectPanel` |
| I-03 | 2-value parameters as combobox | ✅ | Spec 07 |
| I-04 | **Controller Assignments** (view/assign mod matrix) | 🟡 🔬 | Spec 09. Display + edit Min/Max + clear existing. **Create** on arbitrary params remains RE-blocked (destination doesn't travel in `body[4]`): pending pedal harvest. |
| I-05 | **Bypass Assign** (alternative footswitch) | ✅ 🔬 | Spec 09. Full CRUD (create/move/clear + label + color), `.pgp` round-trip. Pending live verification. |

---

## SNAPSHOTS

| Code | Feature | Status | Notes |
|------|---------|--------|-------|
| N-01 | Snapshot recall by MIDI | ✅ | |
| N-02 | Set snapshot (write current state) | ✅ 🔬 | `device.set_snapshot()` |
| N-03 | **Copy/Paste snapshot** | ❌ | |
| N-04 | **Rename snapshot** | ❌ | |
| N-05 | **Customize snapshot/footswitch colors and labels** | ❌ | |

---

## GLOBAL EQ

| Code | Feature | Status | Notes |
|------|---------|--------|-------|
| G-01 | **Global EQ** (5-band parametric) | ❌ | No code. Probably lives in object 23. |
| G-02 | **Frequency response graph** | ❌ | |
| G-03 | **Bypass Global EQ** | ❌ | |

---

## PREFERENCES / SETTINGS

| Code | Feature | Status | Notes |
|------|---------|--------|-------|
| P-01 | **Preferences Window** | ❌ | |
| P-02 | **Account/Marketplace Window** | ❌ | |
| P-03 | **Firmware Updater** | ❌ | |
| P-04 | **Multi-device** (multiple connected POD Go units) | ❌ | |
| P-05 | **Complete keyboard shortcuts** | 🟡 | Some shortcuts (Ctrl+S, etc.). Most are missing. |
| P-06 | **Drag & drop with filesystem** | ❌ | Drag .pgp from the file manager. |

---

## Summary

| Status | Count |
|--------|-------|
| ✅ Implemented | ~25 items |
| 🟡 Partial / gated | ~6 items |
| ❌ Not implemented | ~16 items |
| 🔬 Requires live validation | ~6 items |
