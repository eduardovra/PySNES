"""
Synthetic PPU sprite (OAM) unit tests.

These bypass ROM loading entirely — they write VRAM/CGRAM/OAM directly and
call draw_objects() to verify that sprite pixels land in main_bgs correctly.
No Mesen, no ROM files needed.

Setup:
  - 4BPP tile at VRAM[0x200..0x21F] (solid green, color index 1)
  - oam_tiledata_address = 0x100  →  tile_base_addr = 0x200
  - Sprite palette 8 (CGRAM[256..286]), color 1 = GREEN
  - Sprite 0 placed at screen (x=10, y=5), character=0, 8×8 pixels
  - v_counter = 6  →  sprite row 1 drawn, output at main_bgs row 5

Run:
    uv run --python pypy3.10 pytest pysnes/ppu/test_ppu_sprites.py -v
"""

import pytest

from pysnes.ppu.ppu import Ppu

SCREEN_W = 256

# 5-bit green: g5=31 → g8 = (31<<3)|(31>>2) = 248|7 = 255
GREEN = (0, 255, 0)
# Backdrop: all-zero CGRAM entry → black
BLACK = (0, 0, 0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ppu() -> Ppu:
    ppu = Ppu()
    ppu.inidisp_set(0x0F)  # max brightness
    ppu._bgmode = 1
    return ppu


def _write_cgram(ppu: Ppu, index: int, r5: int, g5: int, b5: int) -> None:
    """Write a 5-bit BGR color to CGRAM at palette color index."""
    word = r5 | (g5 << 5) | (b5 << 10)
    ppu.cgram[index * 2 + 0] = word & 0xFF
    ppu.cgram[index * 2 + 1] = (word >> 8) & 0xFF


def _write_4bpp_solid_tile(ppu: Ppu, vram_addr: int, color_index: int) -> None:
    """
    Write a solid-color 4BPP tile (32 bytes) at vram_addr.

    color_index is a 4-bit value. Bitplanes are interleaved:
      bytes  0..15: bp0/bp1 (row0: [bp0, bp1], row1: [bp0, bp1], ...)
      bytes 16..31: bp2/bp3
    """
    bp0 = 0xFF if (color_index & 1) else 0x00
    bp1 = 0xFF if (color_index & 2) else 0x00
    bp2 = 0xFF if (color_index & 4) else 0x00
    bp3 = 0xFF if (color_index & 8) else 0x00
    for row in range(8):
        ppu.vram[vram_addr + row * 2 + 0]  = bp0
        ppu.vram[vram_addr + row * 2 + 1]  = bp1
        ppu.vram[vram_addr + 16 + row * 2 + 0] = bp2
        ppu.vram[vram_addr + 16 + row * 2 + 1] = bp3


def _pixel(ppu: Ppu, x: int, y: int) -> tuple:
    """Return (R, G, B) from main_bgs at pixel (x, y)."""
    u32 = ppu.main_bgs[y * SCREEN_W + x]
    r = (u32 >> 24) & 0xFF
    g = (u32 >> 16) & 0xFF
    b = (u32 >>  8) & 0xFF
    return (r, g, b)


def _setup_sprite(ppu: Ppu) -> None:
    """
    Place one 8×8 sprite at screen (x=10, y=5) with a solid green tile.

    oam_tiledata_address = 0x100 → tile_base_addr = 0x200 bytes
    Tile 0 data lives at VRAM[0x200..0x21F].
    Sprite palette 8 (raw OAM palette field 0, +8 applied by OAM decoder).
    CGRAM color 8*16+1 = 129 → GREEN.
    """
    TILE_BASE = 0x200  # oam_tiledata_address * 2 = 0x100 * 2

    # Tile: solid color index 1 (green in palette 8)
    _write_4bpp_solid_tile(ppu, TILE_BASE, color_index=1)

    # CGRAM sprite palette 8, color 1 = GREEN
    # palette_index = 8 * 16 = 128; color_index = 129; CGRAM byte addr = 258
    _write_cgram(ppu, 0,   0,  0,  0)  # color 0 = transparent / backdrop (black)
    _write_cgram(ppu, 129, 0, 31,  0)  # sprite palette 8, color 1 = GREEN

    # Configure PPU OAM tile base
    ppu.oam_tiledata_address = 0x100

    # Hide all sprites (y=240 is the conventional hide value)
    for obj in ppu.oam.objects:
        obj.y = 240

    # Write sprite 0 directly to Object attributes (OAM decode path)
    obj = ppu.oam.objects[0]
    obj.x = 10
    obj.y = 5
    obj.character = 0
    obj.palette = 8   # +8 already applied (matches OAM decoder in update_low_table)
    obj.priority = 0
    obj.h_flip = False
    obj.v_flip = False
    obj.size = False   # 8×8 sprite (small size)
    obj.name_select = False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSpriteRendering:
    def test_sprite_pixels_written_to_framebuffer(self):
        """
        A sprite at (x=10, y=5) must produce green pixels in main_bgs at
        row 5 (= v_counter-1 = 6-1), columns 10..17.
        """
        ppu = _make_ppu()
        _setup_sprite(ppu)

        # Fill scanline 6 with backdrop first (painter's algorithm baseline)
        ppu.v_counter = 6
        ppu.draw_scanline_backdrop()

        # Draw objects for this scanline
        ppu.draw_objects()

        # Sprite tile row 1 (y=6 in tile coords) should be at main_bgs row 5
        for x in range(10, 18):
            assert _pixel(ppu, x, 5) == GREEN, f"Expected GREEN at ({x}, 5)"

    def test_sprite_pixels_do_not_bleed_outside_tile(self):
        """Pixels just outside the 8-wide sprite must not be overwritten."""
        ppu = _make_ppu()
        _setup_sprite(ppu)

        ppu.v_counter = 6
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        # Columns 9 and 18 are adjacent to the sprite — must be backdrop (black)
        assert _pixel(ppu, 9,  5) == BLACK, "Left neighbor should be backdrop"
        assert _pixel(ppu, 18, 5) == BLACK, "Right neighbor should be backdrop"

    def test_transparent_sprite_pixel_does_not_overwrite_backdrop(self):
        """
        A sprite with color index 0 (transparent) must leave main_bgs untouched.
        This verifies the 'color == 0 → skip write' guard in draw_point().
        """
        ppu = _make_ppu()
        _setup_sprite(ppu)

        # Overwrite tile with fully transparent (color_index=0) data
        _write_4bpp_solid_tile(ppu, 0x200, color_index=0)

        ppu.v_counter = 6
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        # All pixels on the sprite scanline should remain backdrop (black)
        for x in range(10, 18):
            assert _pixel(ppu, x, 5) == BLACK, (
                f"Transparent sprite must not overwrite backdrop at ({x}, 5)"
            )

    def test_sprite_off_screen_left_no_crash(self):
        """Sprite partially off-screen to the left must not crash or write OOB."""
        ppu = _make_ppu()
        _setup_sprite(ppu)

        ppu.oam.objects[0].x = -3  # 3 pixels off-screen left

        ppu.v_counter = 6
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()  # must not raise IndexError

        # Only the visible part (x=0..4) should be green
        for x in range(0, 5):
            assert _pixel(ppu, x, 5) == GREEN, f"Expected GREEN at ({x}, 5)"

    def test_sprite_scanline_not_rendered_above_or_below(self):
        """
        Sprite is at y=5 (rows 5..12). Scanline 5 (v_counter=5) corresponds
        to the sprite's first row. Scanline 4 (v_counter=4) should be backdrop.
        """
        ppu = _make_ppu()
        _setup_sprite(ppu)

        # Render scanline above the sprite
        ppu.v_counter = 4
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        for x in range(10, 18):
            assert _pixel(ppu, x, 3) == BLACK, (
                f"Row above sprite should be backdrop at ({x}, 3)"
            )

    def test_backdrop_fills_entire_scanline_before_sprites(self):
        """draw_scanline_backdrop() must write backdrop to all 256 pixels."""
        ppu = _make_ppu()
        # No sprites — just verify backdrop fills the row
        ppu.v_counter = 10
        ppu.draw_scanline_backdrop()

        for x in range(SCREEN_W):
            assert _pixel(ppu, x, 9) == BLACK, f"Expected backdrop at ({x}, 9)"


# ---------------------------------------------------------------------------
# 16x16 multi-tile sprite tests
# ---------------------------------------------------------------------------

# 5-bit red: r5=31 → r8 = 255
RED = (255, 0, 0)
BLUE = (0, 0, 255)


def _setup_16x16_sprite(ppu: Ppu) -> None:
    """Place one 16x16 sprite at (x=20, y=10) with distinct solid tiles.

    A 16x16 sprite is composed of 4 adjacent 8x8 tiles arranged:
      [char+0]  [char+1]      top-left   top-right
      [char+16] [char+17]     bot-left   bot-right

    SNES OBJ tile numbering: H offset +1, V offset +16.

    oam_base_size=0 → small=8x8, large=16x16.
    obj.size=True → use the large (16x16) size.
    """
    TILE_BASE = 0x200  # oam_tiledata_address = 0x100 → byte addr = 0x200
    TILE_SIZE_4BPP = 32

    # Tile 0 (top-left) = GREEN
    _write_4bpp_solid_tile(ppu, TILE_BASE + 0 * TILE_SIZE_4BPP, color_index=1)
    # Tile 1 (top-right) = RED
    _write_4bpp_solid_tile(ppu, TILE_BASE + 1 * TILE_SIZE_4BPP, color_index=2)
    # Tile 16 (bottom-left) = BLUE
    _write_4bpp_solid_tile(ppu, TILE_BASE + 16 * TILE_SIZE_4BPP, color_index=3)
    # Tile 17 (bottom-right) = GREEN again
    _write_4bpp_solid_tile(ppu, TILE_BASE + 17 * TILE_SIZE_4BPP, color_index=1)

    # CGRAM: sprite palette 8 (color indices 129-131)
    _write_cgram(ppu, 0,   0,  0,  0)   # backdrop = black
    _write_cgram(ppu, 129, 0, 31,  0)   # color 1 = GREEN
    _write_cgram(ppu, 130, 31, 0,  0)   # color 2 = RED
    _write_cgram(ppu, 131, 0,  0, 31)   # color 3 = BLUE

    ppu.oam_tiledata_address = 0x100
    ppu.oam_base_size = 0  # 8x8 and 16x16

    for obj in ppu.oam.objects:
        obj.y = 240

    obj = ppu.oam.objects[0]
    obj.x = 20
    obj.y = 10
    obj.character = 0
    obj.palette = 8
    obj.priority = 0
    obj.h_flip = False
    obj.v_flip = False
    obj.size = True  # large = 16x16


class TestMultiTileSprite:
    """16x16 sprites must render all four 8x8 sub-tiles, not just the top-left."""

    def test_16x16_top_left_tile(self):
        """Scanline through the top-left tile (y=10, pixels x=20..27) → GREEN."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 11  # output row = 10
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        for x in range(20, 28):
            assert _pixel(ppu, x, 10) == GREEN, f"top-left at ({x},10)"

    def test_16x16_top_right_tile(self):
        """Scanline through the top-right tile (y=10, pixels x=28..35) → RED."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 11
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        for x in range(28, 36):
            assert _pixel(ppu, x, 10) == RED, f"top-right at ({x},10)"

    def test_16x16_bottom_left_tile(self):
        """Scanline through the bottom-left tile (y=18, pixels x=20..27) → BLUE."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 19  # output row = 18
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        for x in range(20, 28):
            assert _pixel(ppu, x, 18) == BLUE, f"bottom-left at ({x},18)"

    def test_16x16_bottom_right_tile(self):
        """Scanline through the bottom-right tile (y=18, pixels x=28..35) → GREEN."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 19
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        for x in range(28, 36):
            assert _pixel(ppu, x, 18) == GREEN, f"bottom-right at ({x},18)"

    def test_16x16_no_bleed_right(self):
        """Pixel at x=36 (right of sprite) must be backdrop."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 11
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        assert _pixel(ppu, 36, 10) == BLACK, "right of 16x16 sprite"

    def test_16x16_no_bleed_below(self):
        """Row 26 (below bottom of sprite) must be backdrop."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 27  # output row = 26
        ppu.draw_scanline_backdrop()
        ppu.draw_objects()

        for x in range(20, 36):
            assert _pixel(ppu, x, 26) == BLACK, f"below sprite at ({x},26)"
