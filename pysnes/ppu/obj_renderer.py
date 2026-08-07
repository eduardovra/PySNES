from __future__ import annotations

from array import array
from typing import Tuple, TYPE_CHECKING


from .constants import SCREEN_WIDTH
from .data_structures import Object

if TYPE_CHECKING:
    from .ppu import Ppu


def _decode_obj_tile(ppu: Ppu, slot: int, vram_addr: int) -> None:
    """Decode one 4bpp 8×8 tile from VRAM into the object tile cache."""
    vram = ppu.vram
    cache = ppu._obj_tile_cache
    base = slot * 64
    for row in range(8):
        row_addr = (vram_addr + row * 2) & 0xFFFF
        b0 = vram[row_addr]
        b1 = vram[(row_addr + 1) & 0xFFFF]
        b2 = vram[(row_addr + 16) & 0xFFFF]
        b3 = vram[(row_addr + 17) & 0xFFFF]
        dst = base + row * 8
        for col in range(8):
            shift = 7 - col
            cache[dst + col] = (
                ((b0 >> shift) & 1)
                | (((b1 >> shift) & 1) << 1)
                | (((b2 >> shift) & 1) << 2)
                | (((b3 >> shift) & 1) << 3)
            )
    ppu._obj_tile_dirty[slot] = 0


def _plot_obj(
    ppu: Ppu,
    obj: Object,
    x_offset: int,
    tile_base_addr: int,
    tile_width: int,
    tile_height: int,
    cgram_cache: array,
) -> None:
    """Plot one object's pixels for the current scanline into the OBJ line
    buffers, writing only where no lower-index sprite has already claimed the
    pixel (color_line == 0). Objects are always 4bpp."""
    vc = ppu.v_counter
    h_tiles = tile_width // 8
    v_tiles = tile_height // 8
    h_flip = obj.h_flip
    v_flip = obj.v_flip
    palette_base = obj.palette * 16  # 4bpp: 16 colors per palette
    pri = obj.priority
    # OBJ palettes 4-7 (12-15 in global space) use color math (layer 5);
    # palettes 0-3 are immune (layer 6).
    layer = 5 if obj.palette >= 12 else 6
    tile_character = obj.character
    y_offset = obj.y
    color_line = ppu._obj_line_color
    pri_line = ppu._obj_line_pri
    layer_line = ppu._obj_line_layer
    obj_cache = ppu._obj_tile_cache

    for tile_pos_v in range(v_tiles):
        if v_flip:
            tile_row_y = y_offset + (v_tiles - 1 - tile_pos_v) * 8
        else:
            tile_row_y = y_offset + tile_pos_v * 8
        if not (tile_row_y <= vc < tile_row_y + 8):
            continue

        row_in_tile = vc - tile_row_y
        i_base = ((7 - row_in_tile) if v_flip else row_in_tile) * 2

        for tile_pos_h in range(h_tiles):
            if h_flip:
                x = x_offset + (h_tiles - 1 - tile_pos_h) * 8
            else:
                x = x_offset + tile_pos_h * 8

            tile_addr = tile_character + tile_pos_h + tile_pos_v * 16
            tile_vram_start = (tile_base_addr + tile_addr * 32) & 0xFFFF
            cache_slot = tile_vram_start >> 5
            if ppu._obj_tile_dirty[cache_slot]:
                _decode_obj_tile(ppu, cache_slot, tile_vram_start)
            cache_base = cache_slot * 64 + (i_base >> 1) * 8
            for col in range(8):
                color = obj_cache[cache_base + col]
                if not color:
                    continue
                px = x + (7 - col if h_flip else col)
                if 0 <= px < SCREEN_WIDTH and color_line[px] == 0:
                    color_line[px] = cgram_cache[palette_base + color]
                    pri_line[px] = pri
                    layer_line[px] = layer


def _render_obj_line(ppu: Ppu) -> None:
    """Resolve the full OBJ layer for the current scanline into the line
    buffers. Sprite-vs-sprite priority is by OAM index — the lowest-numbered
    object wins each pixel regardless of priority field — so iterate index
    0→127 and let the first writer keep the pixel."""
    vc = ppu.v_counter
    color_line = ppu._obj_line_color
    for i in range(SCREEN_WIDTH):
        color_line[i] = 0
    ppu._obj_line_vc = vc

    if not ppu.oam_main_screen_enable:
        return

    if ppu._cgram_dirty:
        ppu._rebuild_cgram_cache()
    cgram_cache = ppu._cgram_cache

    for obj in ppu.oam.objects:
        if (
            obj.y == 240
        ):  # TODO: replace with proper Y-bounds check; y=240 is the common hide convention but not the hardware rule
            continue

        tile_width, tile_height = get_obj_dimensions(ppu, obj.size)
        # Skip sprites whose Y range doesn't include the current scanline.
        if not (obj.y <= vc < obj.y + tile_height):
            continue

        # OBJ X is 9-bit signed (Anomie/fullsnes): values 256..511 represent
        # -256..-1, letting sprites straddle the left edge.
        x_screen = obj.x - 512 if obj.x >= 256 else obj.x
        # Apply name_select: OAM byte 3 bit 0 selects the second sprite name
        # table, offset from the first by (oam_nameselect+1)*0x1000 VRAM words.
        tile_base_word = ppu.oam_tiledata_address
        if obj.name_select:
            tile_base_word = (
                tile_base_word + (ppu.oam_nameselect + 1) * 0x1000
            ) & 0x7FFF

        _plot_obj(
            ppu,
            obj,
            x_screen,
            tile_base_word * 2,
            tile_width,
            tile_height,
            cgram_cache,
        )


def copy_obj_pixels_for_priority(ppu: Ppu, priority: int = -1) -> None:
    # objects are the building blocks for sprites
    # they can move independently from the background and always use 4bpp
    # they can be 8x8, 16x16, 32x32 or 64x64 pixels in size
    #
    # The OBJ layer is resolved once per scanline (by OAM index) into the line
    # buffers; this call blits the pixels whose owning sprite has the requested
    # priority into the main screen. The mode dispatcher interleaves these
    # per-priority blits with BG layers in the correct front-to-back order.
    #
    # priority: when >= 0, only pixels with that priority are drawn; -1 draws
    # all priorities (used by tests).

    if not ppu.oam_main_screen_enable:
        return

    vc = ppu.v_counter
    if ppu._obj_line_vc != vc:
        _render_obj_line(ppu)

    color_line = ppu._obj_line_color
    pri_line = ppu._obj_line_pri
    layer_line = ppu._obj_line_layer
    main_bgs = ppu.main_bgs
    main_layer = ppu.main_layer
    y_idx = (vc - 1) * SCREEN_WIDTH

    for px in range(SCREEN_WIDTH):
        c = color_line[px]
        if c and (priority < 0 or pri_line[px] == priority):
            idx = y_idx + px
            main_bgs[idx] = c
            main_layer[idx] = layer_line[px]


def get_obj_dimensions(ppu: Ppu, obj_size: bool) -> Tuple[int, int]:
    """
    000 =  8x8  and 16x16 sprites
    001 =  8x8  and 32x32 sprites
    010 =  8x8  and 64x64 sprites
    011 = 16x16 and 32x32 sprites
    100 = 16x16 and 64x64 sprites
    101 = 32x32 and 64x64 sprites
    110 = 16x32 and 32x64 sprites (Not officially supported)
    111 = 16x32 and 32x32 sprites (Not officially supported)
    """
    return ppu._OBJ_DIM_TABLE[ppu.oam_base_size][obj_size]


def draw_point(
    ppu: Ppu,
    i: int,
    tile_data: bytes,
    tile_data_index: int,
    bpp: int,
    palette: int,
    pixel: int,
    x: int,
    y: int,
) -> None:
    """Draw a single pixel from bitplane data at tile_data_index+i, wrapping at len(tile_data).

    Used by tests to verify VRAM-boundary wrapping in tile fetches.
    """
    tlen = len(tile_data)
    mask = 1 << pixel
    addr = (tile_data_index + i) % tlen
    lo = tile_data[addr]
    hi = tile_data[(addr + 1) % tlen]
    color = (hi & mask) >> pixel << 1 | (lo & mask) >> pixel
    if bpp >= 4:
        lo = tile_data[(addr + 16) % tlen]
        hi = tile_data[(addr + 17) % tlen]
        color |= (hi & mask) >> pixel << 3 | (lo & mask) >> pixel << 2
    if color and 0 <= x < SCREEN_WIDTH:
        if ppu._cgram_dirty:
            ppu._rebuild_cgram_cache()
        palette_base = palette * (1 << bpp)
        u32_color = ppu._cgram_cache[palette_base + color]
        row = (y - 1) * SCREEN_WIDTH
        ppu.main_bgs[row + x] = u32_color
