#!/usr/bin/env python3
"""End-to-end check with the real API (device.set_param + editor.block_index).

Uses exactly the app's code path: PresetEditor.block_index(slot) →
device.set_param(...). Changes TubeDrive (slot 2) Drive to 1.0 and re-reads.
"""
import logging, time
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

from openpodgo.device import PodGo
from openpodgo.editor import PresetEditor

pod = PodGo()
pod.connect()
pod.write_connect()

pre = pod.active_preset()
ed = PresetEditor(pre)
SLOT = 2  # TubeDrive in BassPreset (chain excludes input)
blk_idx = ed.block_index(SLOT)
before = pre.chain[SLOT].params[0]
print(f"\nTubeDrive slot={SLOT} → block_index(k98)={blk_idx}  param[0] BEFORE={before}")

ok = pod.set_param(block_index=blk_idx, param_idx=0, value=1.0)
print(f"device.set_param → {ok}")

time.sleep(0.3)
pod._transport.drain()
pre2 = pod.active_preset()
after = pre2.chain[SLOT].params[0]
print(f"param[0] AFTER={after}")
print("→ " + ("✓ APPLIED via real API" if abs(after - 1.0) < 0.01 else "✗ not applied"))
pod.disconnect()
