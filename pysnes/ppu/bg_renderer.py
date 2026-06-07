from __future__ import annotations

from typing import TYPE_CHECKING


from . import color_math
from .constants import SCREEN_WIDTH, _colorcode_table
from .data_structures import Background

if TYPE_CHECKING:
    from .ppu import Ppu


def draw_scanline_backdrop(ppu: Ppu) -> None:
    """Draw the backdrop color for the current scanline.

    Main-screen backdrop = CGRAM[0]. Sub-screen backdrop = COLDATA fixed
    color ($2132), per SNES PPU behavior — sub-screen doesn't use CGRAM[0]."""
    main_u32 = color_math.get_u32_backdrop_color(ppu)
    sub_u32 = color_math.get_u32_coldata_color(ppu)
    y = ppu.v_counter - 1
    row = y * SCREEN_WIDTH
    for x in range(SCREEN_WIDTH):
        ppu.main_bgs[row + x] = main_u32
        ppu.sub_bgs[row + x] = sub_u32
        ppu.main_layer[row + x] = 0


def draw_mode7_scanline(ppu: Ppu) -> None:
    """Render BG1 (and EXTBG BG2) for Mode 7 using affine transformation.

    VRAM layout: each word at address N has low byte = tilemap tile number
    (128×128 grid) and high byte = 8bpp pixel data for tile/pixel lookups.

    TODO: EXTBG — M7SEL bit 6 enables a second BG layer from the high byte of
    the VRAM word; priority split between BG1 and BG2(EXTBG) not yet wired.
    TODO: repeat/wrap — M7SEL bits 0-1 control out-of-bounds behavior
    (0=wrap, 1=transparent, 2=fill with tile 0); currently always wraps.
    TODO: border fill — M7SEL bit 7 selects between transparent and tile-0
    fill for pixels that map outside the 1024×1024 mode-7 plane.
    """
    # v_counter is the hardware scanline (1 = first visible line).
    # The affine transform uses the hardware scanline directly; the output
    # row is 0-indexed so we subtract 1 only for the buffer write.
    scan_y = ppu.v_counter       # hardware scanline (1-based) for transform
    row_y = ppu.v_counter - 1    # 0-based index into main_bgs / sub_bgs

    # Sign-extend 16-bit matrix coefficients (m7_write stores them unsigned)
    a = ppu.m7a if ppu.m7a < 0x8000 else ppu.m7a - 0x10000
    b = ppu.m7b if ppu.m7b < 0x8000 else ppu.m7b - 0x10000
    c = ppu.m7c if ppu.m7c < 0x8000 else ppu.m7c - 0x10000
    d = ppu.m7d if ppu.m7d < 0x8000 else ppu.m7d - 0x10000

    # Center of rotation (already 13-bit signed from m7_write)
    cx = ppu.m7x
    cy = ppu.m7y

    # Scroll offsets: BG1HOFS/VOFS are reused as M7HOFS/VOFS; sign-extend 13-bit
    hofs = ppu.bg1.hoffset & 0x1FFF
    if hofs >= 0x1000:
        hofs -= 0x2000
    vofs = ppu.bg1.voffset & 0x1FFF
    if vofs >= 0x1000:
        vofs -= 0x2000

    # M7SEL flags
    h_flip = (ppu.m7sel >> 0) & 1
    v_flip = (ppu.m7sel >> 1) & 1
    # bits 7-6: 0/1=wrap, 2=transparent outside 1024×1024, 3=fill with tile 0
    screen_over = (ppu.m7sel >> 6) & 3

    # Apply V-flip to scanline (Mode 7 "screen" height = 256)
    fy = (255 - scan_y) if v_flip else scan_y
    dy = fy + vofs - cy

    # Precompute y-column of the matrix (constant for this scanline)
    b_dy = b * dy
    d_dy = d * dy

    row = row_y * SCREEN_WIDTH
    write_main_bg1 = ppu.bg1.main_screen_enable
    write_sub_bg1 = ppu.bg1.sub_screen_enable
    write_main_bg2 = ppu.bg2.main_screen_enable
    write_sub_bg2 = ppu.bg2.sub_screen_enable
    extbg = ppu.m7_extbg

    # Window masking for BG1 (same logic as draw_background_scanline, bg_idx=0)
    window_active = bool(ppu.tmw & 0x01)
    w1_enable = bool((ppu.w12sel >> 1) & 1)
    w1_invert = bool(ppu.w12sel & 1)
    w2_enable = bool((ppu.w12sel >> 3) & 1)
    w2_invert = bool((ppu.w12sel >> 2) & 1)
    combine_logic = ppu.wbglog & 0x3

    window_masked = None
    if window_active and (w1_enable or w2_enable):
        window_masked = ppu._window_mask_buf
        ppu._build_window_mask(
            window_masked,
            w1_enable, w1_invert,
            w2_enable, w2_invert,
            combine_logic,
        )

    for px in range(SCREEN_WIDTH):
        if window_masked is not None and window_masked[px]:
            continue

        fx = (255 - px) if h_flip else px
        dx = fx + hofs - cx

        # Affine transform → VRAM coordinate (fixed-point 8.8 → integer)
        vx = ((a * dx + b_dy) >> 8) + cx
        vy = ((c * dx + d_dy) >> 8) + cy

        outside = vx < 0 or vx >= 1024 or vy < 0 or vy >= 1024
        if outside:
            if screen_over == 2:
                continue  # transparent
            elif screen_over != 3:
                vx &= 0x3FF  # wrap to 1024×1024
                vy &= 0x3FF
                outside = False

        # Tilemap: low byte of VRAM word at (ty*128+tx) = tile number
        if outside:  # screen_over == 3: force tile 0
            tile_num = 0
        else:
            tile_num = ppu.vram[2 * ((vy >> 3) * 128 + (vx >> 3))]

        # Pixel: high byte of VRAM word at tile data offset (8bpp)
        tile_px = vx & 7
        tile_py = vy & 7
        pixel = ppu.vram[2 * (tile_num * 64 + tile_py * 8 + tile_px) + 1]

        if pixel == 0:
            continue  # transparent

        idx = row + px

        if extbg and pixel & 0x80:
            # EXTBG: high bit selects BG2 layer
            if not (write_main_bg2 or write_sub_bg2):
                continue
            color = color_math.get_u32_color(ppu, 8, 0, pixel)
            if write_main_bg2:
                ppu.main_bgs[idx] = color
                ppu.main_layer[idx] = 2  # BG2
            if write_sub_bg2:
                ppu.sub_bgs[idx] = color
        else:
            if not (write_main_bg1 or write_sub_bg1):
                continue
            color = color_math.get_u32_color(ppu, 8, 0, pixel)
            if write_main_bg1:
                ppu.main_bgs[idx] = color
                ppu.main_layer[idx] = 1  # BG1
            if write_sub_bg1:
                ppu.sub_bgs[idx] = color


def draw_background_scanline(ppu: Ppu, bg: Background, bpp, priority_selector) -> None:
    # If neither main nor sub is enabled, nothing to do at all.
    if not bg.main_screen_enable and not bg.sub_screen_enable:
        return

    write_main = bg.main_screen_enable
    write_sub = bg.sub_screen_enable
    layer_tag = bg.number

    # Window masking setup for this BG.
    # $212E TMW bit (bg.number-1): window masking enabled for this BG on main screen.
    # $2123 W12SEL (for BG1/BG2) / $2124 W34SEL (for BG3/BG4):
    #   bit pairs per BG: (W1 invert, W1 enable, W2 invert, W2 enable).
    # For BG1: W12SEL bits 3:2:1:0 = (W2_enable, W2_invert, W1_enable, W1_invert).
    # invert=0: pixels INSIDE [WHx_L,WHx_R] are in the mask zone.
    # invert=1: pixels OUTSIDE [WHx_L,WHx_R] are in the mask zone.
    # $212A WBGLOG combines the two window outputs per BG:
    #   bits 2n..2n+1 for BGn: 0=OR, 1=AND, 2=XOR, 3=XNOR.
    bg_idx = bg.number - 1
    window_active = ppu.tmw & (1 << bg_idx)
    w1_enable = False
    w1_invert = False
    w2_enable = False
    w2_invert = False
    combine_logic = 0
    if window_active:
        if bg_idx == 0:
            w1_enable = (ppu.w12sel >> 1) & 1
            w1_invert = ppu.w12sel & 1
            w2_enable = (ppu.w12sel >> 3) & 1
            w2_invert = (ppu.w12sel >> 2) & 1
        elif bg_idx == 1:
            w1_enable = (ppu.w12sel >> 5) & 1
            w1_invert = (ppu.w12sel >> 4) & 1
            w2_enable = (ppu.w12sel >> 7) & 1
            w2_invert = (ppu.w12sel >> 6) & 1
        elif bg_idx == 2:
            w1_enable = (ppu.w34sel >> 1) & 1
            w1_invert = ppu.w34sel & 1
            w2_enable = (ppu.w34sel >> 3) & 1
            w2_invert = (ppu.w34sel >> 2) & 1
        elif bg_idx == 3:
            w1_enable = (ppu.w34sel >> 5) & 1
            w1_invert = (ppu.w34sel >> 4) & 1
            w2_enable = (ppu.w34sel >> 7) & 1
            w2_invert = (ppu.w34sel >> 6) & 1
        combine_logic = (ppu.wbglog >> (bg_idx * 2)) & 0x3

    # Mosaic: when enabled for this BG with size > 1, every S×S block of
    # screen pixels shows the color sampled from the block's top-left
    # pixel. We apply mosaic by rounding the effective scrx/scry down to
    # the nearest S multiple (in screen-space) before doing the tilemap/
    # tile fetch. The OUTPUT position (orgx, orgy) is unchanged.
    mosaic_on = ppu.mosaic_enabled[bg_idx]
    mosaic_size = ppu.mosaic_size

    # Hoist scanline-invariant values out of the 256-pixel loop.
    screen_size = bg.screen_size
    bg_size_w = 32 << (screen_size & 1)
    bg_size_h = 32 << (screen_size >> 1)
    scroll_x = bg.hoffset
    scroll_y = bg.voffset
    tiledata_addr = bg.tiledata_addr
    screen_addr = bg.screen_addr & 0xFFFF
    color_offset = bg.color_offset_mode_0 if ppu._bgmode == 0 else 0
    bpp_mult = 1 << bpp
    if ppu._cgram_dirty:
        ppu._rebuild_cgram_cache()
    cgram_cache = ppu._cgram_cache
    orgy = ppu.v_counter - 1
    scry_base = ppu.v_counter
    row_base = orgy * SCREEN_WIDTH
    vram = ppu.vram
    main_bgs = ppu.main_bgs
    main_layer = ppu.main_layer
    sub_bgs = ppu.sub_bgs
    ct = _colorcode_table

    # Precompute per-dot window mask once for the scanline (constant window boundaries).
    window_masked = None
    if window_active and (w1_enable or w2_enable):
        window_masked = ppu._window_mask_buf
        ppu._build_window_mask(
            window_masked,
            w1_enable, w1_invert,
            w2_enable, w2_invert,
            combine_logic,
        )

    if mosaic_on and mosaic_size > 1:
        # Slow path: mosaic snaps scry per pixel — cannot batch by tile column.
        for dot in range(256):
            if window_masked is not None and window_masked[dot]:
                continue
            scrx = dot - (dot % mosaic_size)
            anchor_orgy = orgy - (orgy % mosaic_size)
            scry = (anchor_orgy + 1 + scroll_y) % (8 * bg_size_h)
            scrx = (scrx + scroll_x) % (8 * bg_size_w)

            offset = ((scry % 256 if bg_size_w == 64 else scry) // 8) * 32
            offset += ((scrx % 256) // 8)
            offset += (scrx // 256) * 0x400
            offset += (bg_size_w // 64) * ((scry // 256) * 0x800)
            tilemap_word_addr = (screen_addr + offset) * 2 & 0xFFFF

            low = vram[tilemap_word_addr]
            high = vram[tilemap_word_addr + 1]
            tile_num = (high & 3) << 8 | low
            tilemap_palette = (high >> 2) & 7
            tilemap_priority = (high >> 5) & 1
            tilemap_h_flip = (high >> 6) & 1
            tilemap_v_flip = (high >> 7) & 1

            if tilemap_priority == priority_selector:
                i = scry & 7
                j = scrx & 7
                v_shift = i if not tilemap_v_flip else (7 - i)
                h_shift = (7 - j) if not tilemap_h_flip else j
                if bpp == 2:
                    tile_address = (tiledata_addr + tile_num * 16 + v_shift * 2) & 0xFFFF
                    b_lo = vram[tile_address]
                    b_hi = vram[(tile_address + 1) & 0xFFFF]
                    v = ((b_lo >> h_shift) & 1) | (((b_hi >> h_shift) & 1) << 1)
                elif bpp == 4:
                    tile_address = (tiledata_addr + tile_num * 32 + v_shift * 2) & 0xFFFF
                    b_1 = vram[tile_address]
                    b_2 = vram[(tile_address + 1) & 0xFFFF]
                    b_3 = vram[(tile_address + 16) & 0xFFFF]
                    b_4 = vram[(tile_address + 17) & 0xFFFF]
                    v = ((b_1 >> h_shift) & 1) | (((b_2 >> h_shift) & 1) << 1) | \
                        (((b_3 >> h_shift) & 1) << 2) | (((b_4 >> h_shift) & 1) << 3)
                elif bpp == 8:
                    tile_address = (tiledata_addr + tile_num * 64 + v_shift * 2) & 0xFFFF
                    b_1 = vram[tile_address]
                    b_2 = vram[(tile_address + 1) & 0xFFFF]
                    b_3 = vram[(tile_address + 16) & 0xFFFF]
                    b_4 = vram[(tile_address + 17) & 0xFFFF]
                    b_5 = vram[(tile_address + 32) & 0xFFFF]
                    b_6 = vram[(tile_address + 33) & 0xFFFF]
                    b_7 = vram[(tile_address + 48) & 0xFFFF]
                    b_8 = vram[(tile_address + 49) & 0xFFFF]
                    v = ((b_1 >> h_shift) & 1) | (((b_2 >> h_shift) & 1) << 1) | \
                        (((b_3 >> h_shift) & 1) << 2) | (((b_4 >> h_shift) & 1) << 3) | \
                        (((b_5 >> h_shift) & 1) << 4) | (((b_6 >> h_shift) & 1) << 5) | \
                        (((b_7 >> h_shift) & 1) << 6) | (((b_8 >> h_shift) & 1) << 7)
                else:
                    raise NotImplementedError(f"Invalid bpp {bpp}")
                if v:
                    u32_color = cgram_cache[tilemap_palette * bpp_mult + v + color_offset]
                    pix_idx = row_base + dot
                    if write_main:
                        main_bgs[pix_idx] = u32_color
                        main_layer[pix_idx] = layer_tag
                    if write_sub:
                        sub_bgs[pix_idx] = u32_color
    else:
        # Fast path: scry is constant for the whole scanline.
        # Process pixels in tile-column batches (up to 8 pixels at a time) so
        # each tilemap fetch and tile-data read is amortised across 8 pixels
        # instead of being repeated once per pixel.
        eff_scry = (scry_base + scroll_y) % (8 * bg_size_h)
        i = eff_scry & 7
        # Precompute the scry-dependent part of the tilemap word offset.
        # (bg_size_w >> 6) == bg_size_w // 64: 0 for 32-tile-wide, 1 for 64-tile-wide.
        scry_for_row = eff_scry % 256 if bg_size_w == 64 else eff_scry
        scry_page = eff_scry >> 8
        scry_offset = (scry_for_row >> 3) * 32 + (bg_size_w >> 6) * (scry_page * 0x800)

        eff_scrx = scroll_x % (8 * bg_size_w)
        scrx_wrap = 8 * bg_size_w
        dot = 0
        while dot < 256:
            pixel_in_tile = eff_scrx & 7
            n_pixels = 8 - pixel_in_tile
            if dot + n_pixels > 256:
                n_pixels = 256 - dot

            # Tilemap fetch — once per tile column.
            scrx_page = eff_scrx >> 8
            col_offset = ((eff_scrx & 0xFF) >> 3) + scrx_page * 0x400
            tilemap_word_addr = (screen_addr + scry_offset + col_offset) * 2 & 0xFFFF
            low = vram[tilemap_word_addr]
            high = vram[tilemap_word_addr + 1]
            tile_num = (high & 3) << 8 | low
            tilemap_palette = (high >> 2) & 7
            tilemap_priority = (high >> 5) & 1
            tilemap_h_flip = (high >> 6) & 1
            tilemap_v_flip = (high >> 7) & 1

            if tilemap_priority == priority_selector:
                v_shift = i if not tilemap_v_flip else (7 - i)

                # Tile-data fetch — once per tile column, shared across all 8 pixels.
                if bpp == 2:
                    tile_address = (tiledata_addr + tile_num * 16 + v_shift * 2) & 0xFFFF
                    b_lo = vram[tile_address]
                    b_hi = vram[(tile_address + 1) & 0xFFFF]
                    row_code = ct[(b_lo & 0xF) | ((b_hi & 0xF) << 4)] | (ct[((b_lo >> 4) & 0xF) | (b_hi & 0xF0)] << 32)
                    for k in range(n_pixels):
                        current_dot = dot + k
                        if window_masked is not None and window_masked[current_dot]:
                            continue
                        jj = pixel_in_tile + k
                        h_shift = (7 - jj) if not tilemap_h_flip else jj
                        v = (row_code >> (h_shift * 8)) & 0x3
                        if v:
                            u32_color = cgram_cache[tilemap_palette * bpp_mult + v + color_offset]
                            pix_idx = row_base + current_dot
                            if write_main:
                                main_bgs[pix_idx] = u32_color
                                main_layer[pix_idx] = layer_tag
                            if write_sub:
                                sub_bgs[pix_idx] = u32_color
                elif bpp == 4:
                    tile_address = (tiledata_addr + tile_num * 32 + v_shift * 2) & 0xFFFF
                    b_1 = vram[tile_address]
                    b_2 = vram[(tile_address + 1) & 0xFFFF]
                    b_3 = vram[(tile_address + 16) & 0xFFFF]
                    b_4 = vram[(tile_address + 17) & 0xFFFF]
                    code12 = ct[(b_1 & 0xF) | ((b_2 & 0xF) << 4)] | (ct[((b_1 >> 4) & 0xF) | (b_2 & 0xF0)] << 32)
                    code34 = ct[(b_3 & 0xF) | ((b_4 & 0xF) << 4)] | (ct[((b_3 >> 4) & 0xF) | (b_4 & 0xF0)] << 32)
                    for k in range(n_pixels):
                        current_dot = dot + k
                        if window_masked is not None and window_masked[current_dot]:
                            continue
                        jj = pixel_in_tile + k
                        h_shift = (7 - jj) if not tilemap_h_flip else jj
                        sh = h_shift * 8
                        v = ((code12 >> sh) & 0x3) | (((code34 >> sh) & 0x3) << 2)
                        if v:
                            u32_color = cgram_cache[tilemap_palette * bpp_mult + v + color_offset]
                            pix_idx = row_base + current_dot
                            if write_main:
                                main_bgs[pix_idx] = u32_color
                                main_layer[pix_idx] = layer_tag
                            if write_sub:
                                sub_bgs[pix_idx] = u32_color
                elif bpp == 8:
                    tile_address = (tiledata_addr + tile_num * 64 + v_shift * 2) & 0xFFFF
                    b_1 = vram[tile_address]
                    b_2 = vram[(tile_address + 1) & 0xFFFF]
                    b_3 = vram[(tile_address + 16) & 0xFFFF]
                    b_4 = vram[(tile_address + 17) & 0xFFFF]
                    b_5 = vram[(tile_address + 32) & 0xFFFF]
                    b_6 = vram[(tile_address + 33) & 0xFFFF]
                    b_7 = vram[(tile_address + 48) & 0xFFFF]
                    b_8 = vram[(tile_address + 49) & 0xFFFF]
                    code12 = ct[(b_1 & 0xF) | ((b_2 & 0xF) << 4)] | (ct[((b_1 >> 4) & 0xF) | (b_2 & 0xF0)] << 32)
                    code34 = ct[(b_3 & 0xF) | ((b_4 & 0xF) << 4)] | (ct[((b_3 >> 4) & 0xF) | (b_4 & 0xF0)] << 32)
                    code56 = ct[(b_5 & 0xF) | ((b_6 & 0xF) << 4)] | (ct[((b_5 >> 4) & 0xF) | (b_6 & 0xF0)] << 32)
                    code78 = ct[(b_7 & 0xF) | ((b_8 & 0xF) << 4)] | (ct[((b_7 >> 4) & 0xF) | (b_8 & 0xF0)] << 32)
                    for k in range(n_pixels):
                        current_dot = dot + k
                        if window_masked is not None and window_masked[current_dot]:
                            continue
                        jj = pixel_in_tile + k
                        h_shift = (7 - jj) if not tilemap_h_flip else jj
                        sh = h_shift * 8
                        v = ((code12 >> sh) & 0x3) | (((code34 >> sh) & 0x3) << 2) | \
                            (((code56 >> sh) & 0x3) << 4) | (((code78 >> sh) & 0x3) << 6)
                        if v:
                            u32_color = cgram_cache[tilemap_palette * bpp_mult + v + color_offset]
                            pix_idx = row_base + current_dot
                            if write_main:
                                main_bgs[pix_idx] = u32_color
                                main_layer[pix_idx] = layer_tag
                            if write_sub:
                                sub_bgs[pix_idx] = u32_color
                else:
                    raise NotImplementedError(f"Invalid bpp {bpp}")

            dot += n_pixels
            eff_scrx += n_pixels
            if eff_scrx >= scrx_wrap:
                eff_scrx -= scrx_wrap
