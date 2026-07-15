# POD Go Protocol — reverse engineering notes

Starting point: the HX Stomp XL editor spec published by **openhx**
(copy at `https://github.com/allansomensi/openhx`). POD Go belongs to the same
Helix/HX family; this document records what has been confirmed/adjusted against
the real pedal.

## Transport summary (inherited from HX Stomp XL)

- Line 6 Vendor ID: `0x0E41`. POD Go PID: **to be confirmed** (`lsusb`).
- **Vendor-specific** interface (class `0xFF`) with a bulk OUT endpoint (`0x01`)
  and a bulk IN endpoint (`0x81`). Implemented in `usb_transport.py` auto-detecting
  the interface via descriptors instead of hardcoding numbers.
- `set_configuration(1)`, `claim_interface`, `clear_halt` on both endpoints,
  and **drain** of residual IN data before the first packet.
- Strict **request → response** pattern: never two writes without a read in
  between. Operation timeout 2000 ms, drain 50 ms, buffer 512 B, LE.

## Handshake (5 packets)

`session.py` sends `packets.HANDSHAKE_SEQUENCE` and discards each response.
HANDSHAKE uses magic `0x28`; the rest `0x18`. Application seq starts at `0x06`.

## Preset listing

Phases 1-3 in `preset.stream_presets`: OPEN_PRESETS (seq 0x06), OPEN_STREAM
(seq 0x07, brings chunk #0), loop of 16 B chunks (seq 0x08+, offset 0x1138
+0x100) until short read (< 272 B). Reassemble → search for `DC 00 80`
(array16 of 128) → MessagePack → key 109 = name (strip `\0`).

## Validation status against real POD Go

| Aspect | Status |
|---|---|
| Device PID | ✅ `0x4247` (Line6, Inc. POD Go) |
| Vendor interface/endpoints | ✅ iface 0 (class 0xFF), bulk OUT `0x01` / IN `0x81` |
| 5-packet handshake | ✅ identical to HX; accepted on first attempt |
| Setlist listing | ✅ OPEN_PRESETS returns `["Factory", "User"]` |
| 128-preset listing (Factory) | ✅ indices 0..127 with names; MessagePack decoded |
| 128-preset listing (User) | ✅ slots 0..127 by stream position; stable ids |
| Preset map schema | ✅ `{idx: {109: name\0, 123: bool, 124: bool, 125: int}}` |
| Complete preset content (blocks/params) | ⏳ next |
| Writing to pedal | ⏳ Phase 3 |

## Setlists (CC32 + vendor read)

- `OPEN_PRESETS` returns the setlists (key 104 = array of `{0: name}`):
  `["Factory", "User"]` (setlist 0 and 1).
- `OPEN_STREAM` byte **34** selects the setlist to stream (0=Factory, 1=User).
- MIDI **CC32** (channel 1) selects the active setlist on the pedal; then **PC**
  recalls the preset. Confirmed: Factory recalls and lists correctly.

### RESOLVED: User setlist reading (slot = position, index = ID)

Two discoveries close the User reading bug (validated against the pedal,
June 2026):

1. **The preset's external index is a stable ID, NOT the slot.** The slot
   (= PC number) is the **entry's position in the stream**. In Factory
   id == slot by coincidence (it's never reordered); in User they diverge
   when the user moves presets (e.g. id 129 'juanitosSOLO' lives at
   slot 36/10A — the spurious "129" was a real preset relocated). Internal
   key 125 is not the slot (always 0); there is no slot field: the order
   defines it. Implemented in `preset.parse_preset_list` (`PresetEntry.slot`).
2. **The User's OPEN_STREAM response carries the first data window.**
   It's the first packet of the message: 24 B of header (16 transport + 8
   sub-header with the **total message length** in bytes 20-21 LE,
   e.g. 0x0D04 = 3332) followed by `83 66 cd 03 ea 67 00 68` and the array
   `DC 00 80` with the first ~9 presets. Discarding it as an "ack" lost ids
   128-138. For Factory the response IS a flat 16 B ack and data starts in
   the chunk-responses. `stream_presets` prepends that window to the buffer
   (`packets.FIRST_DATA_HEADER_LEN`).

Additionally, **the offset field of chunk-requests appears to be ignored**: the
device serves the stream sequentially (reading with base 0x0F00 produces a
byte-for-byte identical buffer to base 0x1000). "Offset addressing" only works
because requests advance by `0x100` and reassembly places each payload in order.

End-to-end validation: complete User (slots 0-127 contiguous, first 12 names
confirmed against the pedal's screen), Factory re-read afterwards without
desynchronizing, second User read identical. Real fixture at
`captures/user_full.bin` + test `test_parse_real_user_capture`.

## POD Go vs HX Stomp XL differences (confirmed)

| Aspect | HX Stomp XL | POD Go |
|---|---|---|
| PID | `0x4253` | `0x4247` |
| OPEN_STREAM | returns chunk #0 with data | Factory: flat 16 B ack; User: first data packet (272 B, 24-byte header) |
| Stream base offset | `0x1138` | **`0x1000`** (that's where the DC 00 80 header and preset 0 are) |
| IN transfer size | 272 B (256 useful) | 512 B, but only the first 256 (`CHUNK_WINDOW`) are new; the rest repeats the window |
| Stream end | short read < 272 | empty payload, or already-decodable 128-element array |
| Handshake / magic | same | same (`0x28` only in HANDSHAKE) |

### Detail of each preset's internal map

`81 cd HI LO  8N  cd 00 6d <str:name\0>  7b c2  7c c2  7d 00`

- `81` fixmap(1) outer; key = preset index (`cd` uint16).
- `8N` inner map (seen `0x84` = 4 entries).
- key `109` (`cd 00 6d`) → **name**, string with trailing `\0` (strip).
- keys `123`/`124` → bool (`c2`=false); key `125` → int. Meaning
  TBD (probably slot/usage flags). Setlists: 0=Factory, 1=User.

## Complete active preset (object 22) and l6-helix container

The vendor open (cmd 0x0C, payload `{102: txn, 100: object, 101: args}`)
selects the OBJECT with key 100 (102 is a transaction id that the device
echoes). Discovered objects and response `{102, 103: status,
104: result}`: see `docs/specs/02-lab-notes.md` (object map and
"Blob ↔ .pgp mapping" table).

- **Object 22** = complete active preset. The result (key 104) is the
  `l6-helix` container: fixstr `"l6-helix\0"` + 48 B str16 (12 informative
  u32 LE offsets) + a single MessagePack map with the block chain
  (stable model ids, float32 0..1 params in model definition order),
  snapshots, footswitch/controller and metadata (product, firmware).
  The dump follows the active preset (changes with PC) and reflects the
  live edit buffer (moving a knob changes the corresponding float).
  Validated on firmware v2.00 and v2.01 (format unchanged).
- **Object 23** = `{107: setlist, 108: slot, 109: name}` of the active
  preset (inline).

Code: `src/openpodgo/l6helix.py` (container → dataclasses),
`src/openpodgo/catalog.py` (model id → name + param order, validated
against `.pgp`), `preset.read_active_preset()` / `read_active_state()`.
Pending decode: body keys 2 and 6, footswitch (3) and controller (4)
assignments already roughly mapped, and `@bypassvolume` of the amp
(key 12 of the block?).
