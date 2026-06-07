from __future__ import annotations

from typing import Tuple, TYPE_CHECKING


from .constants import SCREEN_WIDTH, _PIXEL_SEQUENCE
from .data_structures import Object, Tilemap

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
                ((b0 >> shift) & 1) |
                (((b1 >> shift) & 1) << 1) |
                (((b2 >> shift) & 1) << 2) |
                (((b3 >> shift) & 1) << 3)
            )
    ppu._obj_tile_dirty[slot] = 0


def draw_tiles(
    ppu: Ppu,
    bpp: int,
    x_offset: int,
    y_offset: int,
    tile: Tilemap | Object,
    tile_base_addr: int,
    tile_width: int,
    tile_height: int,
    tile_character: int,
) -> None:
    h_tiles = tile_width // 8
    v_tiles = tile_height // 8
    vc = ppu.v_counter
    h_flip = tile.h_flip
    v_flip = tile.v_flip
    palette = tile.palette
    vram = ppu.vram
    main_bgs = ppu.main_bgs
    main_layer = ppu.main_layer
    if ppu._cgram_dirty:
        ppu._rebuild_cgram_cache()
    cgram_cache = ppu._cgram_cache
    tile_size = 8 * bpp
    palette_base = palette * (1 << bpp)
    y_idx = (vc - 1) * SCREEN_WIDTH

    for tile_pos_v in range(v_tiles):
        # Compute the screen-Y of the top of this tile row (before flip).
        if v_flip:
            tile_row_y = y_offset + (v_tiles - 1 - tile_pos_v) * 8
        else:
            tile_row_y = y_offset + tile_pos_v * 8
        # Skip the entire row if v_counter isn't within its 8-pixel span.
        if not (tile_row_y <= vc < tile_row_y + 8):
            continue

        # Which VRAM row within the 8×8 tile maps to vc.
        # v_flip reverses the tile's internal row order.
        row_in_tile = vc - tile_row_y
        i_base = ((7 - row_in_tile) if v_flip else row_in_tile) * 2

        for tile_pos_h in range(h_tiles):
            if h_flip:
                x = x_offset + (h_tiles - 1 - tile_pos_h) * 8
            else:
                x = x_offset + tile_pos_h * 8

            tile_addr = tile_character + tile_pos_h + tile_pos_v * 16

            if bpp == 4:
                # Fast path: use pre-decoded tile cache to avoid per-pixel VRAM reads.
                tile_vram_start = (tile_base_addr + tile_addr * tile_size) & 0xFFFF
                cache_slot = tile_vram_start >> 5
                if ppu._obj_tile_dirty[cache_slot]:
                    _decode_obj_tile(ppu, cache_slot, tile_vram_start)
                obj_cache = ppu._obj_tile_cache
                # i_base = vram_row * 2, so vram_row = i_base >> 1 (v_flip already folded in)
                cache_base = cache_slot * 64 + (i_base >> 1) * 8
                for col in range(8):
                    color = obj_cache[cache_base + col]
                    px = x + (7 - col if h_flip else col)
                    if color and 0 <= px < SCREEN_WIDTH:
                        u32_color = cgram_cache[palette_base + color]
                        idx = y_idx + px
                        main_bgs[idx] = u32_color
                        # OBJ palettes 4-7 (12-15 in global space) use color math (layer 5).
                        # Palettes 0-3 are immune (layer 6).
                        main_layer[idx] = 5 if palette >= 12 else 6
            else:
                # General path for bpp != 4.
                # VRAM is 64KB; mask to 16 bits to wrap correctly.
                i = (i_base + tile_base_addr + tile_addr * tile_size) & 0xFFFF

                if h_flip:
                    x_sequence = range(x + 7, x - 1, -1)
                else:
                    x_sequence = range(x, x + 8)

                for pixel, px in zip(_PIXEL_SEQUENCE, x_sequence):
                    mask = 1 << pixel
                    l = vram[i]
                    h = vram[(i + 1) & 0xFFFF]
                    color = (h & mask) >> pixel << 1 | (l & mask) >> pixel << 0
                    if bpp >= 4:
                        l = vram[(i + 16) & 0xFFFF]
                        h = vram[(i + 17) & 0xFFFF]
                        color |= (h & mask) >> pixel << 3 | (l & mask) >> pixel << 2
                    if color and 0 <= px < SCREEN_WIDTH:
                        u32_color = cgram_cache[palette_base + color]
                        idx = y_idx + px
                        main_bgs[idx] = u32_color
                        main_layer[idx] = 5 if palette >= 12 else 6


def draw_objects(ppu: Ppu, priority: int = -1) -> None:
    # objects are the building blocks for sprites
    # they can move independently from the background and always use 4bpp
    # they can be 8x8, 16x16, 32x32 or 64x64 pixels in size
    # oam is the memory region where the objects properties are stored. each obj uses 34 bits
    #
    # priority: when >= 0, only objects with obj.priority == priority are
    # drawn. This lets the mode dispatcher interleave sprite layers with
    # BG layers in the correct front-to-back order per SNES spec.

    if not ppu.oam_main_screen_enable:
        return

    vc = ppu.v_counter
    for obj in ppu.oam.objects:
        if priority >= 0 and obj.priority != priority:
            continue
        if obj.y == 240:  # TODO: replace with proper Y-bounds check; y=240 is the common hide convention but not the hardware rule
            continue

        tile_width, tile_height = get_obj_dimensions(ppu, obj.size)
        # Skip sprites whose Y range doesn't include the current scanline,
        # avoiding draw_tiles call overhead for the majority of objects.
        if not (obj.y <= vc < obj.y + tile_height):
            continue

        # OBJ X is 9-bit signed (Anomie/fullsnes): values 256..511 represent
        # -256..-1, letting sprites straddle the left edge.
        x_screen = obj.x - 512 if obj.x >= 256 else obj.x
        # Apply name_select: OAM byte 3 bit 0 selects the second sprite name
        # table, offset from the first by (oam_nameselect+1)*0x1000 VRAM words.
        tile_base_word = ppu.oam_tiledata_address
        if obj.name_select:
            tile_base_word = (tile_base_word + (ppu.oam_nameselect + 1) * 0x1000) & 0x7FFF

        draw_tiles(
            ppu,
            bpp=4,  # Always 4bpp for objects
            x_offset=x_screen,
            y_offset=obj.y,
            tile=obj,
            tile_base_addr=tile_base_word * 2,
            tile_width=tile_width,
            tile_height=tile_height,
            tile_character=obj.character,
        )


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
