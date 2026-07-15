#!/usr/bin/env python3
"""Diagnostic: reproduce the app's exact flow before a Save.

The app does: connect → write_connect → list_setlists → active_state →
list_presets → active_preset → (user edits) → set_param x N → save_preset.

This script checks at which step the write breaks.
"""
import logging, time
logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")

from openpodgo.device import PodGo
from openpodgo.editor import PresetEditor

pod = PodGo()
pod.connect()
pod.write_connect()

# Step 1: list_setlists (Session.handshake + OPEN_PRESETS)
print("\n=== 1. list_setlists ===")
setlists = pod.list_setlists()
print(f"Setlists: {setlists}")

# Step 2: active_state (Session.handshake + read object 23)
print("\n=== 2. active_state ===")
state = pod.active_state()
print(f"State: setlist={state.setlist} slot={state.slot}")

# Step 3: list_presets (Session.handshake + OPEN_STREAM + chunks)
print("\n=== 3. list_presets ===")
presets = pod.list_presets(state.setlist)
print(f"Presets: {len(presets)}")

# Step 4: active_preset (Session.handshake + read object 22)
print("\n=== 4. active_preset ===")
pre = pod.active_preset()
ed = PresetEditor(pre)

# Try writing after the reads
print("\n=== 5. set_param after reads ===")
for slot in range(min(3, len(pre.chain))):
    block = pre.chain[slot]
    if block is None:
        continue
    try:
        blk_idx = ed.block_index(slot)
    except ValueError:
        continue
    for i in range(min(2, len(block.params))):
        ok = pod.set_param(block_index=blk_idx, param_idx=i, value=float(block.params[i]))
        print(f"  slot={slot} idx={i} blk_idx={blk_idx} → {ok}")

# Check the WriteSession state
ws = pod._write_session
print(f"\n=== WriteSession state ===")
print(f"  is_open: {ws.is_open}")
print(f"  seq: {ws.seq}")
print(f"  cursor: {ws.cursor:#010x}")

# Try write_connect again
print("\n=== 6. write_connect again ===")
pod.write_connect()
ws2 = pod._write_session
print(f"  is_open: {ws2.is_open}")
print(f"  seq: {ws2.seq}")
print(f"  cursor: {ws2.cursor:#010x}")

for slot in range(min(2, len(pre.chain))):
    block = pre.chain[slot]
    if block is None:
        continue
    try:
        blk_idx = ed.block_index(slot)
    except ValueError:
        continue
    for i in range(min(1, len(block.params))):
        ok = pod.set_param(block_index=blk_idx, param_idx=i, value=float(block.params[i]))
        print(f"  slot={slot} idx={i} → {ok}")

pod.disconnect()
