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
    uv run --python pypy pytest pysnes/ppu/test_ppu_scroll.py -v
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


class TestTilemapWordBits:
    """Verify tilemap high-byte bit extraction: palette (bits 12:10) and priority (bit 13).

    SNES tilemap word layout (16-bit):
      bit 15     : V-flip
      bit 14     : H-flip
      bit 13     : priority        → high byte bit 5     → (high >> 5) & 1
      bits 12:10 : palette index  → high byte bits 4:2  → (high >> 2) & 7
      bits 9:0   : tile char index
    """

    def _setup_palette_test(self, ppu: "Ppu", palette: int) -> None:
        """Single solid tile at col 0, using the given 2BPP palette index."""
        # CGRAM palette 0, color 1 = RED
        _write_cgram(ppu, 0, 0, 0, 0)   # transparent
        _write_cgram(ppu, 1, 31, 0, 0)  # palette 0 color 1 = RED
        # CGRAM palette 1, color 1 = GREEN  (index = 1*4+1 = 5)
        _write_cgram(ppu, 5, 0, 31, 0)  # palette 1 color 1 = GREEN

        _write_2bpp_solid_tile(ppu, 0, 1)  # tile 0: solid color-index 1

        # Tilemap col 0: tile 0, given palette, priority 0
        # high byte: vflip=0, hflip=0, palette in bits 4:2, priority=0, tile_hi=0
        high = (palette & 7) << 2
        ppu.vram[0] = 0       # tile index low
        ppu.vram[1] = high

        ppu.bg1.screen_addr   = 0
        ppu.bg1.tiledata_addr = TILEDATA
        ppu.bg1.screen_size   = 0
        ppu.bg1.tile_size     = 0
        ppu.bg1.hoffset       = 0
        ppu.bg1.voffset       = 0
        ppu.bg1.main_screen_enable = True

    def test_palette0_renders_red(self):
        """Tilemap high=0x00 → palette 0 → color 1 = RED."""
        ppu = _make_ppu()
        self._setup_palette_test(ppu, palette=0)
        _draw_row(ppu, scanline=1)
        assert _pixel(ppu, 0, 0) == (255, 0, 0), "palette 0 color 1 should be RED"

    def test_palette1_renders_green(self):
        """Tilemap high=0x04 → palette 1 → color 1 = GREEN.

        SNES: palette bits are 12:10, i.e. bits 4:2 of the high byte.
        palette=1 → high = 0x04 → (0x04 >> 2) & 7 = 1.
        """
        ppu = _make_ppu()
        self._setup_palette_test(ppu, palette=1)
        _draw_row(ppu, scanline=1)
        assert _pixel(ppu, 0, 0) == (0, 255, 0), "palette 1 color 1 should be GREEN"

    def test_priority0_renders_on_low_pass(self):
        """priority=0 tile renders when priority_selector=False (low-priority pass)."""
        ppu = _make_ppu()
        _write_cgram(ppu, 0, 0, 0, 0)
        _write_cgram(ppu, 1, 31, 0, 0)  # RED
        _write_2bpp_solid_tile(ppu, 0, 1)
        # high byte: priority=0 → bit 5 = 0 → high = 0x00
        ppu.vram[0] = 0
        ppu.vram[1] = 0x00
        ppu.bg1.screen_addr = 0
        ppu.bg1.tiledata_addr = TILEDATA
        ppu.bg1.screen_size = 0
        ppu.bg1.tile_size = 0
        ppu.bg1.main_screen_enable = True

        _draw_row(ppu, scanline=1)
        assert _pixel(ppu, 0, 0) == (255, 0, 0), "priority=0 tile should render on low pass"

    def test_priority1_renders_on_high_pass(self):
        """priority=1 tile renders only when priority_selector=True (high-priority pass).

        SNES: priority is bit 13, i.e. bit 5 of the high byte.
        priority=1 → high = 0x20 → (0x20 >> 5) & 1 = 1.
        """
        ppu = _make_ppu()
        _write_cgram(ppu, 0, 0, 0, 0)
        _write_cgram(ppu, 1, 31, 0, 0)  # RED
        _write_2bpp_solid_tile(ppu, 0, 1)
        # high byte: priority=1 → bit 5 = 1 → high = 0x20
        ppu.vram[0] = 0
        ppu.vram[1] = 0x20
        ppu.bg1.screen_addr = 0
        ppu.bg1.tiledata_addr = TILEDATA
        ppu.bg1.screen_size = 0
        ppu.bg1.tile_size = 0
        ppu.bg1.main_screen_enable = True

        # Low-priority pass: should NOT render
        _draw_row(ppu, scanline=1)
        assert _pixel(ppu, 0, 0) == (0, 0, 0), "priority=1 tile must not render on low pass"

        # High-priority pass: SHOULD render
        ppu.draw_background_scanline(ppu.bg1, bpp=2, priority_selector=1)
        assert _pixel(ppu, 0, 0) == (255, 0, 0), "priority=1 tile should render on high pass"


class TestWindowMasking:
    """Verify BG1 window masking via W12SEL, TMW, WH0, WH1.

    SNES $2123 W12SEL layout (for BG1):
      bit 1: Window 1 enable for BG1
      bit 0: Window 1 invert for BG1
           0 = pixels INSIDE [WH0,WH1] are masked (not drawn)
           1 = pixels OUTSIDE [WH0,WH1] are masked (not drawn)

    $212E TMW: window masking on main screen
      bit 0: BG1 window masking enable
    """

    def _solid_red_bg1(self, ppu):
        """Set up a full-screen solid RED BG1 (all tiles = RED, no scroll)."""
        _write_cgram(ppu, 0, 0, 0, 0)
        _write_cgram(ppu, 1, 31, 0, 0)  # RED
        _write_2bpp_solid_tile(ppu, 0, 1)
        for col in range(32):
            ppu.vram[col * 2]     = 0
            ppu.vram[col * 2 + 1] = 0x00
        ppu.bg1.screen_addr    = 0
        ppu.bg1.tiledata_addr  = TILEDATA
        ppu.bg1.screen_size    = 0
        ppu.bg1.tile_size      = 0
        ppu.bg1.hoffset        = 0
        ppu.bg1.voffset        = 0
        ppu.bg1.main_screen_enable = True

    def test_no_window_all_pixels_drawn(self):
        """TMW=0 (window masking disabled): all BG1 pixels drawn regardless of WH0/WH1."""
        ppu = _make_ppu()
        self._solid_red_bg1(ppu)
        ppu.tmw   = 0x00  # window masking disabled
        ppu.w12sel = 0x03  # would be active if tmw enabled
        ppu.wh0   = 50
        ppu.wh1   = 100
        _draw_row(ppu, scanline=1)

        assert _pixel(ppu, 40,  0) == RED, "left of window: RED (no masking)"
        assert _pixel(ppu, 75,  0) == RED, "inside window: RED (no masking)"
        assert _pixel(ppu, 150, 0) == RED, "right of window: RED (no masking)"

    def test_window_masks_inside_region(self):
        """W12SEL=0x02 (enable, no invert): pixels INSIDE [WH0,WH1] are masked (not drawn)."""
        ppu = _make_ppu()
        self._solid_red_bg1(ppu)
        ppu.tmw    = 0x01   # BG1 window masking on main screen
        ppu.w12sel = 0x02   # BG1 Window 1 enabled, invert=0 (inside masked)
        ppu.wh0    = 50
        ppu.wh1    = 100
        _draw_row(ppu, scanline=1)

        # pixels [50..100] are inside the window → masked → not drawn (stay 0)
        assert _pixel(ppu, 49,  0) == RED, "just left of window: drawn"
        assert _pixel(ppu, 50,  0) == (0, 0, 0), "window left edge: masked"
        assert _pixel(ppu, 75,  0) == (0, 0, 0), "inside window: masked"
        assert _pixel(ppu, 100, 0) == (0, 0, 0), "window right edge: masked"
        assert _pixel(ppu, 101, 0) == RED, "just right of window: drawn"

    def test_window_masks_outside_region(self):
        """W12SEL=0x03 (enable + invert): pixels OUTSIDE [WH0,WH1] are masked."""
        ppu = _make_ppu()
        self._solid_red_bg1(ppu)
        ppu.tmw    = 0x01   # BG1 window masking on main screen
        ppu.w12sel = 0x03   # BG1 Window 1 enabled, invert=1 (outside masked)
        ppu.wh0    = 50
        ppu.wh1    = 100
        _draw_row(ppu, scanline=1)

        # pixels outside [50..100] are masked → not drawn
        assert _pixel(ppu, 49,  0) == (0, 0, 0), "left of window: masked"
        assert _pixel(ppu, 50,  0) == RED, "window left edge: drawn"
        assert _pixel(ppu, 75,  0) == RED, "inside window: drawn"
        assert _pixel(ppu, 100, 0) == RED, "window right edge: drawn"
        assert _pixel(ppu, 101, 0) == (0, 0, 0), "right of window: masked"

    def test_window_boundary_wh0_equals_wh1(self):
        """Single-pixel window: only pixel at wh0=wh1 is inside."""
        ppu = _make_ppu()
        self._solid_red_bg1(ppu)
        ppu.tmw    = 0x01
        ppu.w12sel = 0x02   # inside masked
        ppu.wh0    = 80
        ppu.wh1    = 80
        _draw_row(ppu, scanline=1)

        assert _pixel(ppu, 79,  0) == RED,       "pixel before: drawn"
        assert _pixel(ppu, 80,  0) == (0, 0, 0), "single-pixel window: masked"
        assert _pixel(ppu, 81,  0) == RED,       "pixel after: drawn"
