# SMW Title Screen Investigation — Remaining Visual Glitches

Branch: `smw-past-title`

## Status
SMW boots to the animated title screen. The sky-blue rendering is now
correct after the sub-screen backdrop fix (see Root Cause below). Two
visible glitches remain at frame 560:

1. Missing logo drop-shadow / 3D effect on "SUPER MARIO WORLD"
2. Missing bottom banner (grass + Mario + Nintendo copyright area) —
   the brick frame border bleeds through where the grass banner should
   be.

Frame 560 sky region pixel-diff vs Mesen:
- rows 28-39, cols 32-223: near-exact match (sky color `(156,231,231)`)
- rows 16-27 diffs are caused by missing logo drop-shadow layer

## Root Cause (Confirmed) — Sub-Screen Backdrop

`draw_scanline_backdrop` previously initialized `sub_bgs` to
`CGRAM[0]` (black). On the SMW title screen:

- `CGRAM[0]` is black
- `COLDATA ($2132)` fixed color = `0x7393` → `(156, 231, 231)` sky blue
- `CGADSUB = 0x20` → only backdrop participates in color math (ADD)
- `CGWSEL`, `TS`, `TM` are set up so that the sky pixels are
  backdrop-only on the main screen, with color math pulling the
  sub-screen fixed color onto the main.

SNES PPU behavior: the sub-screen backdrop is the **COLDATA fixed
color**, not `CGRAM[0]`. PySNES was writing `CGRAM[0] = 0` to
`sub_bgs`, so the ADD produced `black + black = black` at every sky
pixel. After the fix, `sub_bgs` is initialized to the COLDATA color,
and `backdrop + COLDATA = (156, 231, 231)` matches Mesen pixel-exact.

**Fix**: `pysnes/ppu/ppu.py` — `draw_scanline_backdrop` now uses
`get_u32_coldata_color()` for `sub_bgs`.

## Verified Not the Cause (pre-fix)
- **VRAM**: byte-identical between PySNES and Mesen in BG1/BG2/BG3
  tilemap/tiledata regions.
- **CGRAM**: only 2/512 bytes differ.
- **Multi-tile sprites**: fixed in `d0eb43b`.
- **Sub-screen buffer routing**: already routing BG2 to `sub_bgs`.
- **Window masking**: original hypothesis (BG3 showing through
  because of window-masking semantics) was wrong — the sky BG3 pixels
  were never there in Mesen; the sky was a color-math ADD of
  COLDATA onto the backdrop.

## Remaining Glitches

### 1. Bottom banner missing — two layers of bugs (one fixed, one open)

Where Mesen shows grass, Mario walking, a bird, a red apple, and the
"© 1990,1991 Nintendo" text, PySNES shows the brick frame-border
tiles repeating. BG1 is being window-masked out of the banner region:
with `--force-tmw 0` the grass banner renders nearly identically to
Mesen, so BG1 rendering is fine — the window mask is wrong.

HDMA ch7 targets `$2126/$2127` (WH0/WH1) and should update them per
scanline. Config (from Mesen state): `indirect=1, transferMode=1`
(2-byte transfer), `$00:$927C` table, `$00:$04A0` indirect data.

**Bug A (fixed)**: `pysnes/cpu/dma.py` had no indirect-addressing
support at all — the 2 bytes after the count byte were being read as
inline data, causing immediate termination. Rewrote `_load_next_entry`
and `hdma_scanline` for DMAPx bit 6. Added 3 new unit tests. After
this fix the pointer advances correctly (`$04A0 → $065E` over 224
scanlines) and the brick-border glitch is gone.

**Bug B (open — CPU/timing divergence)**: With indirect HDMA fixed,
WH0/WH1 now read fresh WRAM every scanline, but PySNES WRAM contents
are wrong. Tracked frame-by-frame dumps of `$04A0..$04AF`:

- Through frame 372, PySNES and Mesen match exactly
  (`FF 00 FF 00 FF 00 FF 00`).
- At frame 373 Mesen starts the curtain-rising animation and fills
  the table with varying window positions
  (`FF 00 6D 93 68 98 65 9B ...`).
- At frame 369 the same routine fires in PySNES but writes all
  `0x80` from byte 2 onward (`FF 00 80 80 80 80 80 80 ...`), and the
  table stays stuck at `0x80` forever.

Both 0x80 lo and 0x80 hi map to WH inverted-clip columns [128, 128],
i.e. BG1 fully masked. Same divergence pattern explains the frozen
`wh0=159, wh1=253` seen earlier (stale table from before the
animation routine ran).

Root cause is upstream of HDMA — the animation code computes wrong
bytes. Likely candidates: APU/CPU timing drift shifts which branch
the animation state machine takes, or a 16-bit arithmetic/flag bug
in an opcode SMW uses in this routine. `test_frame_divergence`
reports CPU drift by frame 1 (PC±2), consistent with this.

Next-step: instruction-level divergence trace around frames 368-373
to identify the specific opcode/branch going wrong.

### 2. Logo drop-shadow / 3D effect missing
In Mesen the "SUPER" letters have colorful gradient fills and the
"MARIO WORLD" letters have a 3D drop-shadow. In PySNES the letters
are flat.

Likely explanation: this is either a high-priority BG1 tile layer we
aren't compositing, or it involves color-math half/sub path (CGADSUB
bit 7 `subtract`, bit 6 `half`) — our `composite_scanline` bails out
on bit 7 (`if cgadsub & 0x80: return`).

## Diagnostic Scripts (committed)
- `scripts/pysnes_dump_vram.py` — headless dump of VRAM, CGRAM, PPU
  state, composite framebuffer
- `scripts/mesen_dump_state.lua` — Mesen-side equivalent dump
- `scripts/mesen_layers.lua` — per-layer capture with TM/TS
  overrides
