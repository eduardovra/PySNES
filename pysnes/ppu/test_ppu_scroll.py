"""
Synthetic PPU scroll unit tests.

These bypass ROM loading entirely — they write VRAM/CGRAM directly and call
draw_background_scanline() to verify pixel output.  No Mesen, no ROM files.

Layout used by all tests:
  - Tilemap at VRAM word 0 (byte 0), screen_addr = 0
  - Tiledata at VRAM byte 0x4000, tiledata_addr = 0x4000
  - 2BPP mode (4 colors per palette)
  - Tile 0: solid RED  (palette index 1)
  - Tile 1: solid BLUE (palette index 2)
  - Row 0 of tilemap: col0=tile0, col1=tile1, col2=tile0, … (alternating)
  - Row 1 of tilemap: all tile 1 (BLUE)

Run:
    uv run --python pypy3.10 pytest pysnes/ppu/test_ppu_scroll.py -v
"""

import pytest

from pysnes.ppu.ppu import Ppu

SCREEN_W = 256
TILEDATA = 0x4000  # tiledata byte address

# Fully-saturated 8-bit values for 5-bit (31, 0, 31):
#   expand: (v << 3) | (v >> 2)  →  (31<<3)|(31>>2) = 248|7 = 255
RED  = (255, 0, 0)
BLUE = (0, 0, 255)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ppu() -> Ppu:
    ppu = Ppu()
    ppu.inidisp_set(0x0F)   # max brightness so colors pass through unchanged
    ppu._bgmode = 1          # mode 1 — BG1 is 4BPP in real hardware, but we call
                             # draw_background_scanline with bpp=2 directly so the
                             # mode value only matters for color_offset_mode_0 logic
    return ppu


def _write_2bpp_solid_tile(ppu: Ppu, tile_index: int, color_index: int) -> None:
    """Write a solid-color 2BPP tile into VRAM at TILEDATA + tile_index*16.

    color_index is a 2-bit value (0=transparent, 1–3=opaque).
    Bitplane 0 carries bit 0, bitplane 1 carries bit 1.
    """
    bp0 = 0xFF if (color_index & 1) else 0x00
    bp1 = 0xFF if (color_index & 2) else 0x00
    addr = TILEDATA + tile_index * 16
    for row in range(8):
        ppu.vram[addr + row * 2 + 0] = bp0
        ppu.vram[addr + row * 2 + 1] = bp1


def _write_cgram(ppu: Ppu, index: int, r5: int, g5: int, b5: int) -> None:
    """Write a 5-bit BGR color to CGRAM at palette color index."""
    word = r5 | (g5 << 5) | (b5 << 10)
    ppu.cgram[index * 2 + 0] = word & 0xFF
    ppu.cgram[index * 2 + 1] = (word >> 8) & 0xFF


def _pixel(ppu: Ppu, x: int, y: int) -> tuple:
    """Return (R, G, B) from main_bgs at pixel (x, y)."""
    u32 = ppu.main_bgs[y * SCREEN_W + x]
    r = (u32 >> 24) & 0xFF
    g = (u32 >> 16) & 0xFF
    b = (u32 >>  8) & 0xFF
    return (r, g, b)


def _setup(ppu: Ppu, hoffset: int = 0, voffset: int = 0) -> None:
    """
    Populate VRAM/CGRAM with a two-tile checkerboard and apply scroll offsets.

    Tilemap layout (32x32 tiles, 8×8 px each):
      Row 0: tile0 tile1 tile0 tile1 …  (alternating RED / BLUE columns)
      Row 1: tile1 tile1 tile1 tile1 …  (all BLUE)
    """
    # CGRAM: index 0 = transparent, 1 = RED, 2 = BLUE
    _write_cgram(ppu, 0, 0,  0,  0)
    _write_cgram(ppu, 1, 31, 0,  0)   # RED
    _write_cgram(ppu, 2, 0,  0, 31)   # BLUE

    # Tile data
    _write_2bpp_solid_tile(ppu, 0, 1)  # tile 0 = solid RED
    _write_2bpp_solid_tile(ppu, 1, 2)  # tile 1 = solid BLUE

    # Tilemap row 0: alternating tile 0 / tile 1
    for col in range(32):
        addr = col * 2
        ppu.vram[addr]     = col & 1   # tile index
        ppu.vram[addr + 1] = 0x00      # palette 0, priority 0, no flip

    # Tilemap row 1 (starts at word offset 32 = byte 64): all tile 1
    for col in range(32):
        addr = 64 + col * 2
        ppu.vram[addr]     = 1
        ppu.vram[addr + 1] = 0x00

    ppu.bg1.screen_addr    = 0          # tilemap at VRAM byte 0
    ppu.bg1.tiledata_addr  = TILEDATA
    ppu.bg1.screen_size    = 0          # 32×32 tiles
    ppu.bg1.tile_size      = 0          # 8×8 px tiles
    ppu.bg1.hoffset        = hoffset
    ppu.bg1.voffset        = voffset
    ppu.bg1.main_screen_enable = True


def _draw_row(ppu: Ppu, scanline: int) -> None:
    """Draw one scanline.  Output lands in main_bgs at row (scanline-1)."""
    ppu.v_counter = scanline
    ppu.draw_background_scanline(ppu.bg1, bpp=2, priority_selector=0)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestHorizontalScroll:
    def test_no_scroll_alternating_columns(self):
        """hoffset=0: columns 0,2,4 are RED; columns 1,3,5 are BLUE."""
        ppu = _make_ppu()
        _setup(ppu, hoffset=0)
        _draw_row(ppu, scanline=1)   # output → row 0

        assert _pixel(ppu, 0,  0) == RED,  "col 0 tile 0 should be RED"
        assert _pixel(ppu, 8,  0) == BLUE, "col 1 tile 1 should be BLUE"
        assert _pixel(ppu, 16, 0) == RED,  "col 2 tile 0 should be RED"
        assert _pixel(ppu, 24, 0) == BLUE, "col 3 tile 1 should be BLUE"

    def test_full_tile_shift(self):
        """hoffset=8: shifts view right by one tile — colours invert."""
        ppu = _make_ppu()
        _setup(ppu, hoffset=8)
        _draw_row(ppu, scanline=1)

        assert _pixel(ppu, 0,  0) == BLUE, "shifted: col 0 should now be BLUE"
        assert _pixel(ppu, 8,  0) == RED,  "shifted: col 1 should now be RED"
        assert _pixel(ppu, 16, 0) == BLUE
        assert _pixel(ppu, 24, 0) == RED

    def test_sub_tile_shift_boundary(self):
        """hoffset=3: pixel (x=4) lands on tile 0, pixel (x=5) lands on tile 1."""
        ppu = _make_ppu()
        _setup(ppu, hoffset=3)
        _draw_row(ppu, scanline=1)

        # scrx = dot + 3.  Tile boundary is at dot+3 = 8, i.e. dot = 5.
        assert _pixel(ppu, 4, 0) == RED,  "dot 4: scrx=7, tile 0 (RED)"
        assert _pixel(ppu, 5, 0) == BLUE, "dot 5: scrx=8, tile 1 (BLUE)"

    def test_two_tile_shift(self):
        """hoffset=16: two full tiles — back to same pattern as hoffset=0."""
        ppu = _make_ppu()
        _setup(ppu, hoffset=16)
        _draw_row(ppu, scanline=1)

        assert _pixel(ppu, 0, 0) == RED,  "two-tile shift restores RED at col 0"
        assert _pixel(ppu, 8, 0) == BLUE

    def test_horizontal_wrap(self):
        """hoffset=248: last tile of row (tile 31=BLUE) wraps to screen left."""
        ppu = _make_ppu()
        _setup(ppu, hoffset=248)  # 248 = 31 * 8
        _draw_row(ppu, scanline=1)

        # dot 0: scrx = 248 → tile 31 (odd) → BLUE
        assert _pixel(ppu, 0, 0) == BLUE, "wrapping: tile 31 (BLUE) at left edge"
        # dot 8: scrx = (248+8)%256 = 0 → tile 0 (even) → RED
        assert _pixel(ppu, 8, 0) == RED,  "wrapping: tile 0 (RED) after wrap"


class TestVerticalScroll:
    def test_no_vscroll_row0(self):
        """voffset=0, scanline 1 → row 0 data (alternating RED/BLUE)."""
        ppu = _make_ppu()
        _setup(ppu, voffset=0)
        _draw_row(ppu, scanline=1)

        assert _pixel(ppu, 0, 0) == RED
        assert _pixel(ppu, 8, 0) == BLUE

    def test_vscroll_into_row1(self):
        """voffset=8: scanline 1 maps to tilemap row 1 (all BLUE)."""
        ppu = _make_ppu()
        _setup(ppu, voffset=8)
        _draw_row(ppu, scanline=1)

        # scry = (1 + 8) % 256 = 9 → tile row 1 (9 // 8 = 1) → all BLUE
        assert _pixel(ppu, 0, 0) == BLUE, "voffset=8 → tile row 1 → all BLUE"
        assert _pixel(ppu, 8, 0) == BLUE

    def test_sub_tile_vscroll_boundary(self):
        """voffset=7: scanline 1 → scry=8 → tile row 1 (BLUE)."""
        ppu = _make_ppu()
        _setup(ppu, voffset=7)
        _draw_row(ppu, scanline=1)

        # scry = 1 + 7 = 8 → tile row 1 → BLUE
        assert _pixel(ppu, 0, 0) == BLUE

    def test_sub_tile_vscroll_stays_row0(self):
        """voffset=6: scanline 1 → scry=7 → still tile row 0 (RED/BLUE alternating)."""
        ppu = _make_ppu()
        _setup(ppu, voffset=6)
        _draw_row(ppu, scanline=1)

        # scry = 1 + 6 = 7 → tile row 0 → alternating
        assert _pixel(ppu, 0, 0) == RED
        assert _pixel(ppu, 8, 0) == BLUE

    def test_vertical_wrap(self):
        """voffset=248: last tile row wraps — scanline 1 maps to tilemap row 31."""
        ppu = _make_ppu()
        _setup(ppu, voffset=248)  # 248 = 31 * 8

        # Tilemap row 31: fill with tile 0 (RED) so it's distinguishable
        for col in range(32):
            addr = (31 * 32 + col) * 2
            ppu.vram[addr]     = 0   # tile 0 (RED)
            ppu.vram[addr + 1] = 0x00
        _draw_row(ppu, scanline=1)

        # scry = (1 + 248) % 256 = 249 → tile row 31 (249 // 8 = 31) → all RED
        assert _pixel(ppu, 0, 0) == RED,  "vertical wrap → tile row 31 (RED)"
        assert _pixel(ppu, 8, 0) == RED
