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

### 1. Bottom banner missing — HDMA ch7 early termination
Where Mesen shows grass, Mario walking, a bird, a red apple, and the
"© 1990,1991 Nintendo" text, PySNES shows the brick frame-border
tiles repeating.

**Cause (confirmed)**: BG1 is being window-masked out of every
scanline in the banner region. With `--force-tmw 0` (all window
masking disabled), PySNES renders the grass banner nearly
identically to Mesen. So BG1 rendering itself is fine — the window
mask is wrong.

**Root cause (confirmed)**: HDMA channel 7 targets `$2126/$2127`
(WH0/WH1) and should update them per scanline. Per-scanline logging
of `wh0/wh1` shows values changing through scanline 112, then
**freezing at `(wh0=159, wh1=253)` for scanlines 113-223**. On those
scanlines the BG1 W1-inverted mask clips BG1 everywhere except
cols 159-253 (visible as a small grass bush on the right side of
the rendered frame).

HDMA ch7 config (from Mesen state):
`hdmaIndirectAddressing: true, transferMode: 1` (2-byte transfer).

Likely bug in `pysnes/cpu/dma.py::hdma_scanline` — either the repeat
counter runs out prematurely, indirect-address pointer reads
garbage, or the "done" flag is set early. Reproducer:
`scripts/pysnes_dump_vram.py --force-tmw 0` vs default.

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
