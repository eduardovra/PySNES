"""
BG mode dispatch + VRAM-wrap unit tests.

- Mode-2 dispatch test: exercises _render_layers() with _bgmode=2 to verify
  BG1 and BG2 are rendered as 4bpp (no NotImplementedError, pixels land).
- VRAM wrap tests: verify the `& 0xFFFF` masks in draw_background_scanline()
  (2bpp/4bpp/8bpp) and the `% tlen` wrap in draw_point() correctly handle
  tile data placed near the top of VRAM. Real games frequently put tile
  data at addresses where the computed fetch offset spills past 0xFFFF.
"""

import pytest

from pysnes.ppu.ppu import Ppu

SCREEN_W = 256

RED   = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE  = (0, 0, 255)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ppu(bgmode: int = 1) -> Ppu:
    ppu = Ppu()
    ppu.inidisp_set(0x0F)
    ppu._bgmode = bgmode
    ppu.v_counter = 1
    return ppu


def _write_cgram(ppu: Ppu, index: int, r5: int, g5: int, b5: int) -> None:
    word = r5 | (g5 << 5) | (b5 << 10)
    ppu.cgram[index * 2 + 0] = word & 0xFF
    ppu.cgram[index * 2 + 1] = (word >> 8) & 0xFF


def _pixel(ppu: Ppu, x: int, y: int) -> tuple:
    u32 = ppu.main_bgs[y * SCREEN_W + x]
    return ((u32 >> 24) & 0xFF, (u32 >> 16) & 0xFF, (u32 >> 8) & 0xFF)


def _write_2bpp_solid_tile_at(ppu: Ppu, addr: int, color_index: int) -> None:
    """Write a solid 2bpp tile (16 bytes) at VRAM byte address `addr`,
    wrapping each byte write at 0xFFFF."""
    bp0 = 0xFF if (color_index & 1) else 0x00
    bp1 = 0xFF if (color_index & 2) else 0x00
    for row in range(8):
        ppu.vram[(addr + row * 2 + 0) & 0xFFFF] = bp0
        ppu.vram[(addr + row * 2 + 1) & 0xFFFF] = bp1


def _write_4bpp_solid_tile_at(ppu: Ppu, addr: int, color_index: int) -> None:
    """Write a solid 4bpp tile (32 bytes: 2 planes × 8 rows, then 2 more × 8)
    at VRAM byte address `addr`, wrapping per byte."""
    bp0 = 0xFF if (color_index & 1) else 0x00
    bp1 = 0xFF if (color_index & 2) else 0x00
    bp2 = 0xFF if (color_index & 4) else 0x00
    bp3 = 0xFF if (color_index & 8) else 0x00
    for row in range(8):
        ppu.vram[(addr + row * 2 + 0) & 0xFFFF] = bp0
        ppu.vram[(addr + row * 2 + 1) & 0xFFFF] = bp1
        ppu.vram[(addr + 16 + row * 2 + 0) & 0xFFFF] = bp2
        ppu.vram[(addr + 16 + row * 2 + 1) & 0xFFFF] = bp3


def _write_8bpp_solid_tile_at(ppu: Ppu, addr: int, color_index: int) -> None:
    """Write a solid 8bpp tile (64 bytes: 4 pairs × 8 rows) at VRAM byte
    address `addr`, wrapping per byte."""
    planes = [0xFF if (color_index >> i) & 1 else 0x00 for i in range(8)]
    for row in range(8):
        ppu.vram[(addr + row * 2 + 0) & 0xFFFF] = planes[0]
        ppu.vram[(addr + row * 2 + 1) & 0xFFFF] = planes[1]
        ppu.vram[(addr + 16 + row * 2 + 0) & 0xFFFF] = planes[2]
        ppu.vram[(addr + 16 + row * 2 + 1) & 0xFFFF] = planes[3]
        ppu.vram[(addr + 32 + row * 2 + 0) & 0xFFFF] = planes[4]
        ppu.vram[(addr + 32 + row * 2 + 1) & 0xFFFF] = planes[5]
        ppu.vram[(addr + 48 + row * 2 + 0) & 0xFFFF] = planes[6]
        ppu.vram[(addr + 48 + row * 2 + 1) & 0xFFFF] = planes[7]


def _write_tilemap_entry(ppu: Ppu, screen_addr: int, col: int, row: int,
                         tile_index: int, palette: int = 0) -> None:
    """Write a single tilemap word at (col, row) in a 32×32 tilemap."""
    word_off = (row * 32 + col) * 2
    ppu.vram[(screen_addr + word_off + 0) & 0xFFFF] = tile_index & 0xFF
    ppu.vram[(screen_addr + word_off + 1) & 0xFFFF] = (palette & 7) << 2


# ---------------------------------------------------------------------------
# BG Mode 2 dispatch
# ---------------------------------------------------------------------------


class TestBgMode2Dispatch:
    """_render_layers() with _bgmode=2 must render BG1 and BG2 as 4bpp."""

    def test_mode2_does_not_raise_not_implemented(self):
        ppu = _make_ppu(bgmode=2)
        # No BGs enabled — just verify dispatch path runs.
        ppu.render_scanline()        # should not raise

    def test_mode2_renders_bg1_as_4bpp(self):
        """BG1 in Mode 2 renders at 4bpp (palette index 1 → color 1)."""
        ppu = _make_ppu(bgmode=2)

        # Palette 0, color 1 = RED  (4bpp uses 16-color palettes)
        _write_cgram(ppu, 0, 0,  0,  0)
        _write_cgram(ppu, 1, 31, 0,  0)

        # Tile 0 = solid color-1 pixels
        _write_4bpp_solid_tile_at(ppu, 0x4000, color_index=1)
        # Tilemap[0, 0] = tile 0, palette 0
        _write_tilemap_entry(ppu, screen_addr=0x0000, col=0, row=0,
                             tile_index=0, palette=0)

        ppu.bg1.screen_addr    = 0x0000
        ppu.bg1.tiledata_addr  = 0x4000
        ppu.bg1.main_screen_enable = True

        ppu.render_scanline()
        assert _pixel(ppu, 0, 0) == RED

    def test_mode2_renders_bg2_as_4bpp(self):
        """BG2 in Mode 2 renders at 4bpp (behind BG1)."""
        ppu = _make_ppu(bgmode=2)

        _write_cgram(ppu, 0, 0,  0,  0)
        _write_cgram(ppu, 1, 0,  0, 31)   # color 1 = BLUE

        _write_4bpp_solid_tile_at(ppu, 0x5000, color_index=1)
        _write_tilemap_entry(ppu, screen_addr=0x0800, col=0, row=0,
                             tile_index=0, palette=0)

        ppu.bg2.screen_addr    = 0x0800
        ppu.bg2.tiledata_addr  = 0x5000
        ppu.bg2.main_screen_enable = True

        ppu.render_scanline()
        assert _pixel(ppu, 0, 0) == BLUE


# ---------------------------------------------------------------------------
# VRAM wrap (& 0xFFFF)
# ---------------------------------------------------------------------------


class TestVramWrap:
    """draw_background_scanline reads VRAM with `& 0xFFFF` masks so tile
    fetches near the top of VRAM wrap back to the bottom (real PPU behavior).
    """

    def test_2bpp_tile_fetch_wraps_at_0xffff(self):
        """2bpp tile at tiledata_addr=0xFFF0 with v_shift=8 would be at byte
        0x10000 = 0x0000 after wrap. Place the tile there and verify the
        pixel decodes correctly."""
        ppu = _make_ppu(bgmode=1)

        _write_cgram(ppu, 0, 0,  0,  0)
        _write_cgram(ppu, 1, 31, 0,  0)   # RED

        # Place 2bpp tile 0 starting at 0xFFF0. Each tile = 16 bytes → tile
        # occupies 0xFFF0..0xFFFF then wraps to 0x0000..0x000F? No — tile 0
        # is fully within [0xFFF0, 0xFFFF]. To force a wrap, put tile 0 at
        # 0xFFFE: row 0 at 0xFFFE/0xFFFF, row 1 at 0x0000/0x0001 (wrapped).
        _write_2bpp_solid_tile_at(ppu, addr=0xFFFE, color_index=1)

        _write_tilemap_entry(ppu, screen_addr=0x0100, col=0, row=0,
                             tile_index=0, palette=0)

        ppu.bg1.screen_addr    = 0x0100
        ppu.bg1.tiledata_addr  = 0xFFFE
        ppu.bg1.main_screen_enable = True

        # Scanline 2 → v_shift=1 → fetches row 1 = bytes at wrapped 0x0000/0x0001.
        ppu.v_counter = 2
        ppu.draw_background_scanline(ppu.bg1, bpp=2, priority_selector=0)
        assert _pixel(ppu, 0, 1) == RED

    def test_4bpp_tile_fetch_wraps_at_0xffff(self):
        """4bpp needs 32 bytes per tile; plane 2/3 at +16 off the base must
        also wrap."""
        ppu = _make_ppu(bgmode=1)

        _write_cgram(ppu, 0, 0,  0,  0)
        _write_cgram(ppu, 1, 0,  31, 0)   # GREEN

        # Place tile at 0xFFF0: row 0 plane 0/1 at 0xFFF0/0xFFF1 (in range),
        # plane 2/3 at 0xFFF0+16=0x10000 → wraps to 0x0000.
        _write_4bpp_solid_tile_at(ppu, addr=0xFFF0, color_index=1)

        _write_tilemap_entry(ppu, screen_addr=0x0100, col=0, row=0,
                             tile_index=0, palette=0)

        ppu.bg1.screen_addr    = 0x0100
        ppu.bg1.tiledata_addr  = 0xFFF0
        ppu.bg1.main_screen_enable = True

        ppu.v_counter = 1
        ppu.draw_background_scanline(ppu.bg1, bpp=4, priority_selector=0)
        assert _pixel(ppu, 0, 0) == GREEN

    def test_8bpp_tile_fetch_wraps_at_0xffff(self):
        """8bpp needs 64 bytes; the +32 and +48 plane pairs must wrap too."""
        ppu = _make_ppu(bgmode=1)

        _write_cgram(ppu, 0, 0,  0,  0)
        _write_cgram(ppu, 1, 0,  0, 31)   # BLUE (palette idx 1)

        # Place tile at 0xFFE0: row 0 plane 0/1 in range, planes 2/3 at +16
        # (0xFFF0), planes 4/5 at +32 (0x10000 → 0x0000), planes 6/7 at +48.
        _write_8bpp_solid_tile_at(ppu, addr=0xFFE0, color_index=1)

        _write_tilemap_entry(ppu, screen_addr=0x0100, col=0, row=0,
                             tile_index=0, palette=0)

        ppu.bg1.screen_addr    = 0x0100
        ppu.bg1.tiledata_addr  = 0xFFE0
        ppu.bg1.main_screen_enable = True

        ppu.v_counter = 1
        ppu.draw_background_scanline(ppu.bg1, bpp=8, priority_selector=0)
        assert _pixel(ppu, 0, 0) == BLUE


class TestSpriteDrawPointWrap:
    """draw_point() accesses tile_data with `% tlen` so sprite tile fetches
    that cross the 0xFFFF VRAM boundary wrap instead of IndexError."""

    def test_draw_point_wraps_tile_data_index_near_vram_top(self):
        """With tile_data_index=0xFFFE and i=1, the effective index is
        0xFFFF; fetches at +0/+1/+16/+17 land at 0xFFFF, 0x0000, 0x000F,
        0x0010 after `% tlen`. Without the wrap, +1/+16/+17 would overflow."""
        ppu = _make_ppu(bgmode=1)

        # All four bitplane bytes have bit 7 set → pixel 7 resolves to color 15.
        ppu.vram[0xFFFF] = 0x80   # plane 0
        ppu.vram[0x0000] = 0x80   # plane 1 (wrapped)
        ppu.vram[0x000F] = 0x80   # plane 2 (wrapped)
        ppu.vram[0x0010] = 0x80   # plane 3 (wrapped)
        _write_cgram(ppu, 15, 31, 0, 0)   # palette 0, color 15 = RED

        # Snapshot vram into a bytes object to pass as tile_data. tlen=65536
        # so the `% tlen` wrap matches how VRAM indexing works in real fetches.
        tile_data = bytes(ppu.vram)

        ppu.v_counter = 1
        ppu.draw_point(
            i=1,
            tile_data=tile_data,
            tile_data_index=0xFFFE,
            bpp=4,
            palette=0,
            pixel=7,
            x=10,
            y=1,
        )
        assert _pixel(ppu, 10, 0) == RED
