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

from pysnes.ppu import bg_renderer, obj_renderer
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
        bg_renderer.draw_scanline_backdrop(ppu)

        # Draw objects for this scanline
        obj_renderer.draw_objects(ppu)

        # Sprite tile row 1 (y=6 in tile coords) should be at main_bgs row 5
        for x in range(10, 18):
            assert _pixel(ppu, x, 5) == GREEN, f"Expected GREEN at ({x}, 5)"

    def test_sprite_pixels_do_not_bleed_outside_tile(self):
        """Pixels just outside the 8-wide sprite must not be overwritten."""
        ppu = _make_ppu()
        _setup_sprite(ppu)

        ppu.v_counter = 6
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

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
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

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
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)  # must not raise IndexError

        # Only the visible part (x=0..4) should be green
        for x in range(0, 5):
            assert _pixel(ppu, x, 5) == GREEN, f"Expected GREEN at ({x}, 5)"

    def test_sprite_x_9bit_sign_extends_to_negative(self):
        """
        OBJ X is 9-bit signed on hardware. An obj.x of 509 (bit 8 set, low=0xFD)
        must be interpreted as -3, so an 8×8 sprite spans x=-3..4 and pixels
        0..4 on the visible row become GREEN. Without sign-extension the sprite
        is fully clipped (x≥256 never passes draw_point's 0 ≤ x < 256 guard).
        """
        ppu = _make_ppu()
        _setup_sprite(ppu)

        ppu.oam.objects[0].x = 509  # 9-bit raw; signed = -3

        ppu.v_counter = 6
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

        for x in range(0, 5):
            assert _pixel(ppu, x, 5) == GREEN, f"Expected GREEN at ({x}, 5)"
        # Pixel at x=5 is outside the sprite's right edge — must still be backdrop.
        assert _pixel(ppu, 5, 5) == BLACK

    def test_sprite_scanline_not_rendered_above_or_below(self):
        """
        Sprite is at y=5 (rows 5..12). Scanline 5 (v_counter=5) corresponds
        to the sprite's first row. Scanline 4 (v_counter=4) should be backdrop.
        """
        ppu = _make_ppu()
        _setup_sprite(ppu)

        # Render scanline above the sprite
        ppu.v_counter = 4
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

        for x in range(10, 18):
            assert _pixel(ppu, x, 3) == BLACK, (
                f"Row above sprite should be backdrop at ({x}, 3)"
            )

    def test_backdrop_fills_entire_scanline_before_sprites(self):
        """draw_scanline_backdrop() must write backdrop to all 256 pixels."""
        ppu = _make_ppu()
        # No sprites — just verify backdrop fills the row
        ppu.v_counter = 10
        bg_renderer.draw_scanline_backdrop(ppu)

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
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

        for x in range(20, 28):
            assert _pixel(ppu, x, 10) == GREEN, f"top-left at ({x},10)"

    def test_16x16_top_right_tile(self):
        """Scanline through the top-right tile (y=10, pixels x=28..35) → RED."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 11
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

        for x in range(28, 36):
            assert _pixel(ppu, x, 10) == RED, f"top-right at ({x},10)"

    def test_16x16_bottom_left_tile(self):
        """Scanline through the bottom-left tile (y=18, pixels x=20..27) → BLUE."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 19  # output row = 18
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

        for x in range(20, 28):
            assert _pixel(ppu, x, 18) == BLUE, f"bottom-left at ({x},18)"

    def test_16x16_bottom_right_tile(self):
        """Scanline through the bottom-right tile (y=18, pixels x=28..35) → GREEN."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 19
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

        for x in range(28, 36):
            assert _pixel(ppu, x, 18) == GREEN, f"bottom-right at ({x},18)"

    def test_16x16_no_bleed_right(self):
        """Pixel at x=36 (right of sprite) must be backdrop."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 11
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

        assert _pixel(ppu, 36, 10) == BLACK, "right of 16x16 sprite"

    def test_16x16_no_bleed_below(self):
        """Row 26 (below bottom of sprite) must be backdrop."""
        ppu = _make_ppu()
        _setup_16x16_sprite(ppu)

        ppu.v_counter = 27  # output row = 26
        bg_renderer.draw_scanline_backdrop(ppu)
        obj_renderer.draw_objects(ppu)

        for x in range(20, 36):
            assert _pixel(ppu, x, 26) == BLACK, f"below sprite at ({x},26)"


# ---------------------------------------------------------------------------
# Sprite priority ordering
#
# Mode 1 front→back order (from ppu.render_scanline):
#   BG3 pri 1 (if $2105 bit 3 set)
#   Sprite pri 3
#   BG1 pri 1
#   BG2 pri 1
#   Sprite pri 2
#   BG1 pri 0
#   BG2 pri 0
#   Sprite pri 1
#   BG3 pri 1 (if bit clear)
#   Sprite pri 0
#   BG3 pri 0
#   Backdrop
# ---------------------------------------------------------------------------

TILEDATA_BG = 0x4000  # BG1/2 tile data (bytes); different region from OBJ tiles
YELLOW = (255, 255, 0)


def _write_bg1_4bpp_solid_tile(ppu: Ppu, tile_index: int, color_index: int) -> None:
    bp0 = 0xFF if (color_index & 1) else 0x00
    bp1 = 0xFF if (color_index & 2) else 0x00
    bp2 = 0xFF if (color_index & 4) else 0x00
    bp3 = 0xFF if (color_index & 8) else 0x00
    addr = TILEDATA_BG + tile_index * 32
    for row in range(8):
        ppu.vram[addr + row * 2 + 0] = bp0
        ppu.vram[addr + row * 2 + 1] = bp1
        ppu.vram[addr + 16 + row * 2 + 0] = bp2
        ppu.vram[addr + 16 + row * 2 + 1] = bp3


def _setup_bg1_tile_over_sprite(ppu: Ppu, bg_priority_bit: int, sprite_priority: int) -> None:
    """Place a BG1 4bpp YELLOW tile and a GREEN sprite at the same pixel.

    BG1 tile's tilemap priority bit controls whether it's "priority 1" in SNES
    composition order. Both the BG1 tile and sprite render at screen (20, 10).
    """
    # BG1 palette 0, color 1 = YELLOW (5-bit: 31,31,0)
    _write_cgram(ppu, 0, 0, 0, 0)  # backdrop black
    _write_cgram(ppu, 1, 31, 31, 0)  # BG1 pal0 color1 = YELLOW

    _write_bg1_4bpp_solid_tile(ppu, 0, color_index=1)

    # Tilemap: one tile at tilemap row 1, col 2 → covers screen (16..23, 8..15).
    # Simpler: put the BG tile at col 2, row 1 so it covers the sprite at (20,10).
    # Tilemap entry: word 0 for (col 0, row 0). Each row = 32 words = 64 bytes.
    # For (col 2, row 1) → byte addr = 1*64 + 2*2 = 68.
    # Low byte = tile index 0; high byte bit 5 = priority bit.
    base = 0  # BG1 tilemap base at VRAM byte 0
    tilemap_addr = base + (1 * 32 + 2) * 2
    ppu.vram[tilemap_addr + 0] = 0  # tile 0
    # bit 5 of high byte is priority
    ppu.vram[tilemap_addr + 1] = 0x20 if bg_priority_bit else 0x00

    ppu.bg1.tiledata_addr = TILEDATA_BG
    ppu.bg1.screen_addr = base
    ppu.bg1.screen_size = 0
    ppu.bg1.tile_size = 0
    ppu.bg1.hoffset = 0
    ppu.bg1.voffset = 0
    ppu.bg1.main_screen_enable = True
    ppu.bg1.sub_screen_enable = False

    # Sprite at same pixel as BG1 tile — GREEN 8x8
    _setup_sprite(ppu)  # places sprite at (10, 5)
    ppu.oam.objects[0].x = 20
    ppu.oam.objects[0].y = 10
    ppu.oam.objects[0].priority = sprite_priority


class TestSpritePriorityOrdering:
    """Mode 1 BG/sprite compositing must respect OAM priority field."""

    def test_bg1_high_priority_covers_sprite_priority_2(self):
        """In Mode 1, BG1 pri-1 tile is in FRONT of sprite priority 2."""
        ppu = _make_ppu()
        _setup_bg1_tile_over_sprite(ppu, bg_priority_bit=1, sprite_priority=2)
        ppu.v_counter = 11  # draw at output row 10
        ppu.render_scanline()
        # Sprite and BG1 both at (20, 10). BG1 pri-1 wins → YELLOW.
        assert _pixel(ppu, 20, 10) == YELLOW, (
            f"BG1 pri-1 should be in front of sprite pri-2, got {_pixel(ppu, 20, 10)}"
        )

    def test_bg1_low_priority_behind_sprite_priority_2(self):
        """BG1 pri-0 tile is BEHIND sprite priority 2 → sprite wins."""
        ppu = _make_ppu()
        _setup_bg1_tile_over_sprite(ppu, bg_priority_bit=0, sprite_priority=2)
        ppu.v_counter = 11
        ppu.render_scanline()
        # BG1 pri-0 is behind sprite pri-2 → GREEN sprite visible.
        assert _pixel(ppu, 20, 10) == GREEN, (
            f"Sprite pri-2 should cover BG1 pri-0, got {_pixel(ppu, 20, 10)}"
        )

    def test_sprite_priority_3_covers_bg1_high_priority(self):
        """Sprite priority 3 is in front of EVERYTHING including BG1 pri-1."""
        ppu = _make_ppu()
        _setup_bg1_tile_over_sprite(ppu, bg_priority_bit=1, sprite_priority=3)
        ppu.v_counter = 11
        ppu.render_scanline()
        assert _pixel(ppu, 20, 10) == GREEN, (
            f"Sprite pri-3 should cover BG1 pri-1, got {_pixel(ppu, 20, 10)}"
        )

    def test_sprite_priority_0_behind_bg1_low_priority(self):
        """Sprite priority 0 is behind BG1 pri-0."""
        ppu = _make_ppu()
        _setup_bg1_tile_over_sprite(ppu, bg_priority_bit=0, sprite_priority=0)
        ppu.v_counter = 11
        ppu.render_scanline()
        # BG1 pri-0 is in front of sprite pri-0 → YELLOW wins.
        assert _pixel(ppu, 20, 10) == YELLOW, (
            f"BG1 pri-0 should cover sprite pri-0, got {_pixel(ppu, 20, 10)}"
        )


# 5-bit red: r5=31 → r8 = 255
RED = (255, 0, 0)


def _setup_two_overlapping_sprites(
    ppu: Ppu, a_priority: int, b_priority: int
) -> None:
    """Place two 8x8 sprites at the same pixel (20, 10).

    Sprite 0 (lower OAM index) uses palette 8 → GREEN.
    Sprite 1 (higher OAM index) uses palette 9 → RED.
    Both share the solid color-index-1 tile (character 0).
    """
    _setup_sprite(ppu)  # sprite 0: palette 8 (GREEN), all others hidden at y=240

    # Palette 9, color 1 = RED  →  CGRAM index 9*16 + 1 = 145
    _write_cgram(ppu, 145, 31, 0, 0)

    a = ppu.oam.objects[0]
    a.x = 20
    a.y = 10
    a.priority = a_priority

    b = ppu.oam.objects[1]
    b.x = 20
    b.y = 10
    b.character = 0
    b.palette = 9  # +8 already applied → RED
    b.priority = b_priority
    b.h_flip = False
    b.v_flip = False
    b.size = False
    b.name_select = False


class TestSpriteVsSpritePriority:
    """Sprite-vs-sprite priority is decided by OAM index — the lowest-numbered
    object wins each pixel — regardless of the OAM priority field. The priority
    field only chooses where that pixel sits relative to BG layers."""

    def test_lower_index_wins_same_priority(self):
        """Two overlapping sprites, equal priority: lowest OAM index on top."""
        ppu = _make_ppu()
        _setup_two_overlapping_sprites(ppu, a_priority=0, b_priority=0)
        ppu.v_counter = 11
        ppu.render_scanline()
        assert _pixel(ppu, 20, 10) == GREEN, (
            f"Sprite 0 (lowest index) should be on top, got {_pixel(ppu, 20, 10)}"
        )

    def test_lower_index_wins_despite_lower_priority_field(self):
        """Regression (Super Bomberman 5 menu cursor): sprite 0 has the LOWER
        priority field (2) than sprite 1 (3), yet still appears in front because
        sprite-vs-sprite ordering is purely by OAM index."""
        ppu = _make_ppu()
        _setup_two_overlapping_sprites(ppu, a_priority=2, b_priority=3)
        ppu.v_counter = 11
        ppu.render_scanline()
        assert _pixel(ppu, 20, 10) == GREEN, (
            "Sprite 0 (index 0, priority 2) must be in front of sprite 1 "
            f"(index 1, priority 3), got {_pixel(ppu, 20, 10)}"
        )

    def test_higher_index_higher_priority_still_loses(self):
        """Symmetric check: sprite 1 has the HIGHER priority field (3) and a
        higher index — it must still lose the pixel to sprite 0 (priority 0)."""
        ppu = _make_ppu()
        _setup_two_overlapping_sprites(ppu, a_priority=0, b_priority=3)
        ppu.v_counter = 11
        ppu.render_scanline()
        assert _pixel(ppu, 20, 10) == GREEN, (
            f"Sprite 0 (lowest index) must win the pixel, got {_pixel(ppu, 20, 10)}"
        )
