# SMW Title Screen Investigation — Remaining Visual Glitches

Branch: `smw-past-title`

## Status
SMW boots to the animated title screen, but at frame 560 the rendered image diverges from Mesen by ~37% of pixels (16,163 large diffs). Most visible issue: sky area renders as a brownish BG3 striped pattern in PySNES, but shows blue sky in Mesen.

## Symptoms

| Pixel region | PySNES | Mesen |
|---|---|---|
| Top 0–40 rows, center | BG3 pattern `(222,156,99)` tan | Sky blue `(156,231,231)` |
| Row 0, layer tag | `layer=3` (BG3) everywhere | BG3 only on left/right edges |
| Sub screen (BG2) | BG2 mountains + 1 cloud; top rows all black | Same shape, composed into main |

Screenshots saved to `/tmp/pysnes_frame560.png`, `/tmp/pysnes_sub560.png`, `/tmp/mesen_frame560.png`.

## Verified Not the Cause
- **VRAM**: matches Mesen byte-for-byte in the visible tilemap regions (Q0 = BG1/BG2/BG3 tilemaps and tiledata).
- **CGRAM**: only 1/256 entries differ — backdrop is `CGRAM[0] = 0x0000` (black) in both.
- **Multi-tile sprites**: previously fixed in `d0eb43b` — confirmed rendering correctly.
- **Sub-screen buffer / color math composite**: implemented in `3a2b812` — confirmed routing BG2 to `sub_bgs`.

## Root Cause Hypothesis: Window Masking Semantics

At frame 560, SMW has these register values:

```
CGADSUB = 0x20  → only backdrop participates in color math (ADD)
CGWSEL  = 0x12  → prevent color math outside color window; source = sub-screen
TMW     = 0x15  → BG1, BG3, OBJ masked on main screen by window
TSW     = 0x02  → BG2 masked on sub screen by window
W12SEL  = 0x33  → BG1/BG2 Window 1 enabled + inverted
W34SEL  = 0x00  → BG3/BG4 Windows 1 & 2 DISABLED
WOBJSEL = 0x23  → OBJ W1 enabled+inverted; Color W1 enabled
HDMA ch7 → writes $2126/$2127 (WH0/WH1) per scanline — W1 varies by row
```

### The Bug
`draw_background_scanline` (pysnes/ppu/ppu.py:674-679) only applies window masking when **both** `TMW` bit is set **and** `W1_enable` is true. For BG3, `TMW` bit 2 = 1 but `W34SEL` W1 enable = 0 — so no masking is applied and BG3 draws over the entire scanline.

Per SNES hardware (anomie/fullsnes):
- If neither W1 nor W2 is enabled for a layer, the window mask is `0` everywhere (no pixels "inside").
- When TMW enables masking: pixels where mask=1 are clipped.
- So BG3 with `TMW=on, W34SEL=off`: no clipping → BG3 draws normally.

**But that matches our current behavior.** Mesen, however, clips BG3 in the center of the screen. Something else must be controlling this.

### Open Questions
1. Does SMW rely on W12SEL inverted-W1 for BG1 to draw the sky area through BG1 (not BG3)? BG1's current render at row 0 is transparent (tile 0x0F8 or similar), so BG1 doesn't overwrite BG3. Why does Mesen not render BG3 there?
2. Is the BG3 tile at (x=128, y=0) genuinely non-transparent in the tilemap? If yes, Mesen must be applying *some* clipping we're missing.
3. Could this be a **color math** issue where Mesen composites backdrop through color math to produce the sky blue, and our composite shortcuts when the main-screen layer ≠ backdrop?

### Key Observation
`CGWSEL bits 5-4 = 01` means "prevent color math outside color window." The color window for SMW is defined by WH0/WH1 set via HDMA ch7 per scanline. Our `composite_scanline` does **not** implement this gating.

The sky blue `(156,231,231)` is likely the result of **main + sub** color math. But `CGADSUB=0x20` only enables color math on *backdrop pixels*, not BG3. So if Mesen shows backdrop (not BG3) at those pixels, color math would add the sub-screen backdrop ≈ fixed color and produce sky blue.

This points back to: **why is BG3 transparent in those pixels in Mesen but opaque in PySNES?**

## Next Steps
1. Dump Mesen's per-pixel layer output at row 0 (if possible via Mesen Lua).
2. Trace BG3 tile 0x??? at the problem pixels to confirm whether the tile data has a color_idx=0 pixel there.
3. Implement color math windowing (CGWSEL bits 5-4 + color window from WOBJSEL/WH0-WH1) in `composite_scanline`.
4. Consider that BG3 in SMW title may use the **"mode 1 BG3 priority"** bit (`$2105` bit 3) differently than we handle it.

## Diagnostic Scripts (local, not committed)
- `tmp_row0_trace.py` — decode BG2 tilemap/tile at row 0
- `tmp_cgram_compare.py` — compare CGRAM PySNES vs Mesen
- `tmp_vram_compare.py` — compare VRAM PySNES vs Mesen
- `tmp_hdma_diag.py` — dump HDMA channel state
- `tmp_cloud_trace.py` — trace known-cloud pixels through all BG layers
