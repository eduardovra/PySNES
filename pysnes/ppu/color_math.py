from __future__ import annotations

from typing import TYPE_CHECKING


from .constants import SCREEN_WIDTH

if TYPE_CHECKING:
    from .ppu import Ppu

# CGADSUB ($2131) bit masks
_CGADSUB_SUBTRACT = 0x80  # 0=add, 1=subtract
_CGADSUB_HALF     = 0x40  # 0=full intensity, 1=half intensity
_CGADSUB_BACK     = 0x20  # backdrop participates
_CGADSUB_OBJ      = 0x10  # OBJ palettes 4-7 participate
_CGADSUB_BG4      = 0x08
_CGADSUB_BG3      = 0x04
_CGADSUB_BG2      = 0x02
_CGADSUB_BG1      = 0x01


def draw_scanline_forced_blank(ppu: Ppu) -> None:
    y = ppu.v_counter - 1
    row = y * SCREEN_WIDTH
    black_u32 = 0x000000FF
    for x in range(SCREEN_WIDTH):
        ppu.main_bgs[row + x] = black_u32
        ppu.sub_bgs[row + x] = black_u32
        ppu.main_layer[row + x] = 0


def apply_brightness_scanline(ppu: Ppu) -> None:
    """Scale the rendered scanline by the master brightness (0–15).

    Brightness 15 = full; brightness 0 = black.  Called only when
    display_brightness < 15 to avoid the overhead on the common case.
    """
    brightness = ppu.display_brightness
    y = ppu.v_counter - 1
    row = y * SCREEN_WIDTH
    if brightness == 0:
        black = 0x000000FF
        for x in range(SCREEN_WIDTH):
            ppu.main_bgs[row + x] = black
        return
    for x in range(SCREEN_WIDTH):
        idx = row + x
        p = ppu.main_bgs[idx]
        r = ((p >> 24) & 0xFF) * brightness // 15
        g = ((p >> 16) & 0xFF) * brightness // 15
        b = ((p >> 8) & 0xFF) * brightness // 15
        ppu.main_bgs[idx] = (r << 24) | (g << 16) | (b << 8) | (p & 0xFF)


def composite_scanline(ppu: Ppu) -> None:
    """Apply CGADSUB color math, blending sub_bgs into main_bgs.

    CGADSUB ($2131) layout:
      bit 7: 0 = add, 1 = subtract (main minus sub)
      bit 6: 0 = full,  1 = half-intensity (divide result by 2)
      bit 5: backdrop participates
      bit 4: OBJ palettes 4-7 participate
      bit 3..0: BG4..BG1 participate

    CGWSEL ($2130) bits 5-4 gate WHEN color math applies per pixel:
      00 = always, 01 = inside color window, 10 = outside, 11 = never.
    The color window uses W1/W2 with WOBJSEL bits 4-7 for enable/invert
    and WOBJLOG bits 2-3 for combining W1+W2 (OR/AND/XOR/XNOR).

    Not yet implemented: CGWSEL bits 7-6 clip-to-black, bit 1 sub-source
    select (we always use sub_bgs, which already holds COLDATA where no
    sub layer covered the pixel).
    """
    cgadsub = ppu.cgadsub
    cgwsel = ppu.cgwsel
    cmath_mode = (cgwsel >> 4) & 0x3  # 00..11
    if cgadsub == 0 or cmath_mode == 0x3:
        return
    subtract = cgadsub & _CGADSUB_SUBTRACT
    half = cgadsub & _CGADSUB_HALF
    enable_bg1 = cgadsub & _CGADSUB_BG1
    enable_bg2 = cgadsub & _CGADSUB_BG2
    enable_bg3 = cgadsub & _CGADSUB_BG3
    enable_bg4 = cgadsub & _CGADSUB_BG4
    enable_obj = cgadsub & _CGADSUB_OBJ
    enable_back = cgadsub & _CGADSUB_BACK

    # Color-window (math window) setup: WOBJSEL bits 4-7, WOBJLOG bits 2-3.
    # Per $2125 spec (matching $2123 W12SEL convention): bit 0=invert, bit 1=enable.
    # Pairs: bits 0-1 OBJ W1, 2-3 OBJ W2, 4-5 MATH W1, 6-7 MATH W2.
    math_w1_invert = (ppu.wobjsel >> 4) & 1
    math_w1_enable = (ppu.wobjsel >> 5) & 1
    math_w2_invert = (ppu.wobjsel >> 6) & 1
    math_w2_enable = (ppu.wobjsel >> 7) & 1
    math_logic = (ppu.wobjlog >> 2) & 0x3  # 0=OR,1=AND,2=XOR,3=XNOR

    # Pre-compute color-math window mask for the scanline before the pixel loop.
    cmath_mask = None
    if cmath_mode != 0 and (math_w1_enable or math_w2_enable):
        cmath_mask = ppu._window_mask_buf
        ppu._build_window_mask(
            cmath_mask,
            math_w1_enable, math_w1_invert,
            math_w2_enable, math_w2_invert,
            math_logic,
        )

    y = ppu.v_counter - 1
    row = y * SCREEN_WIDTH
    for x in range(SCREEN_WIDTH):
        idx = row + x
        layer = ppu.main_layer[idx]
        participate = False
        if layer == 0:
            participate = enable_back
        elif layer == 1:
            participate = enable_bg1
        elif layer == 2:
            participate = enable_bg2
        elif layer == 3:
            participate = enable_bg3
        elif layer == 4:
            participate = enable_bg4
        elif layer == 5:
            participate = enable_obj
        if not participate:
            continue

        # Color-window gating (CGWSEL bits 5-4).
        if cmath_mode != 0:
            if cmath_mask is not None:
                in_window = cmath_mask[x]
            else:
                # No windows enabled → treat as always inside. Matches Mesen
                # semantic where a disabled window acts as full-screen inside.
                in_window = True
            if cmath_mode == 1 and not in_window:
                continue  # inside only → skip outside
            if cmath_mode == 2 and in_window:
                continue  # outside only → skip inside
        m = ppu.main_bgs[idx]
        s = ppu.sub_bgs[idx]
        mr = (m >> 24) & 0xFF
        mg = (m >> 16) & 0xFF
        mb = (m >> 8) & 0xFF
        sr = (s >> 24) & 0xFF
        sg = (s >> 16) & 0xFF
        sb = (s >> 8) & 0xFF
        if subtract:
            r = mr - sr
            g = mg - sg
            b = mb - sb
            if r < 0:
                r = 0
            if g < 0:
                g = 0
            if b < 0:
                b = 0
            if half:
                r >>= 1
                g >>= 1
                b >>= 1
        else:
            r = mr + sr
            g = mg + sg
            b = mb + sb
            # Half applies before saturation: the 9-bit adder's overflow
            # bit becomes the high bit of the halved result.
            if half:
                r >>= 1
                g >>= 1
                b >>= 1
            if r > 255:
                r = 255
            if g > 255:
                g = 255
            if b > 255:
                b = 255
        ppu.main_bgs[idx] = (r << 24) | (g << 16) | (b << 8) | (m & 0xFF)


def get_u32_color(ppu: Ppu, bpp: int, palette: int, color: int, color_offset: int = 0) -> int:
    if ppu._cgram_dirty:
        ppu._rebuild_cgram_cache()
    if bpp == 8:
        color_index = color
    else:
        color_index = palette * (1 << bpp) + color + color_offset
    return ppu._cgram_cache[color_index]


def get_u32_backdrop_color(ppu: Ppu) -> int:
    data = ppu.cgram[0] | ppu.cgram[1] << 8
    r_5bit = data >> 0 & 0x1F
    g_5bit = data >> 5 & 0x1F
    b_5bit = data >> 10 & 0x1F

    r_8bit = (r_5bit << 3) | (r_5bit >> 2)
    g_8bit = (g_5bit << 3) | (g_5bit >> 2)
    b_8bit = (b_5bit << 3) | (b_5bit >> 2)
    a_8bit = 255

    return (r_8bit << 24) | (g_8bit << 16) | (b_8bit << 8) | a_8bit


def get_u32_coldata_color(ppu: Ppu) -> int:
    r_8bit = (ppu.coldata_r << 3) | (ppu.coldata_r >> 2)
    g_8bit = (ppu.coldata_g << 3) | (ppu.coldata_g >> 2)
    b_8bit = (ppu.coldata_b << 3) | (ppu.coldata_b >> 2)
    return (r_8bit << 24) | (g_8bit << 16) | (b_8bit << 8) | 255
