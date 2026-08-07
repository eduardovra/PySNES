"""
PPU mosaic ($2106) unit tests.

Mosaic takes every NxN block of pixels and replaces them all with the color
of the top-left pixel of that block. Bits 0-3 of $2106 enable per-BG; bits
4-7 encode block size (0=1x1 no effect, 1=2x2, 2=3x3, ..., 0xF=16x16).

Our bus handler stores block_size = (high_nibble + 1) so PPU state holds
the pixel-block side length directly (1..16).

These tests set up a single BG with tiles that have distinct pixel colors
across the first 8 pixels of row 0, then assert that enabling mosaic causes
pixels inside each NxN block to share the top-left pixel's color.

Run:
    uv run --python pypy3.10 pytest pysnes/ppu/test_ppu_mosaic.py -v
"""

import pytest
from pysnes.ppu.ppu import Ppu

SCREEN_W = 256
TILEDATA = 0x4000


def _make_ppu() -> Ppu:
    ppu = Ppu()
    ppu.inidisp_set(0x0F)  # max brightness
    ppu._bgmode = 1
    return ppu


def _write_cgram(ppu: Ppu, index: int, r5: int, g5: int, b5: int) -> None:
    word = r5 | (g5 << 5) | (b5 << 10)
    ppu.cgram[index * 2 + 0] = word & 0xFF
    ppu.cgram[index * 2 + 1] = (word >> 8) & 0xFF


def _write_4bpp_tile_horizontal_gradient(
    ppu: Ppu, tile_index: int, row_colors: list
) -> None:
    """Write a 4bpp tile where ALL 8 rows share the same horizontal gradient."""
    addr = TILEDATA + tile_index * 32
    bp0 = bp1 = bp2 = bp3 = 0
    for col, c in enumerate(row_colors):
        bit = 7 - col
        bp0 |= ((c >> 0) & 1) << bit
        bp1 |= ((c >> 1) & 1) << bit
        bp2 |= ((c >> 2) & 1) << bit
        bp3 |= ((c >> 3) & 1) << bit
    for row in range(8):
        ppu.vram[addr + row * 2 + 0] = bp0
        ppu.vram[addr + row * 2 + 1] = bp1
        ppu.vram[addr + 16 + row * 2 + 0] = bp2
        ppu.vram[addr + 16 + row * 2 + 1] = bp3


def _setup_gradient_bg1(ppu: Ppu) -> None:
    """BG1 tile 0 row 0 has 8 distinct color indices (1..8), rest transparent."""
    # CGRAM colors 1..8: pure reds of increasing brightness
    for i in range(1, 9):
        _write_cgram(ppu, i, i * 3, 0, 0)

    _write_4bpp_tile_horizontal_gradient(ppu, 0, [1, 2, 3, 4, 5, 6, 7, 8])

    # Tilemap at VRAM 0: row 0 col 0 = tile 0 (covers dots 0-7)
    ppu.vram[0] = 0
    ppu.vram[1] = 0

    ppu.bg1.tiledata_addr = TILEDATA
    ppu.bg1.screen_addr = 0
    ppu.bg1.screen_size = 0
    ppu.bg1.tile_size = 0
    ppu.bg1.hoffset = 0
    ppu.bg1.voffset = 0
    ppu.bg1.main_screen_enable = True
    ppu.bg1.sub_screen_enable = False


def _pixel(ppu: Ppu, x: int, y: int) -> tuple:
    u32 = ppu.main_bgs[y * SCREEN_W + x]
    return ((u32 >> 24) & 0xFF, (u32 >> 16) & 0xFF, (u32 >> 8) & 0xFF)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestMosaicHorizontal:
    def test_mosaic_disabled_renders_each_pixel(self):
        """Without mosaic, each of dots 0..7 shows its own gradient color."""
        ppu = _make_ppu()
        _setup_gradient_bg1(ppu)
        ppu.mosaic_enabled = [False, False, False, False]
        ppu.mosaic_size = 1

        ppu.v_counter = 1
        ppu.render_scanline()

        colors = [_pixel(ppu, x, 0) for x in range(8)]
        assert len(set(colors)) == 8, (
            f"Expected 8 distinct pixel colors without mosaic, got: {colors}"
        )

    def test_mosaic_size_2_blocks_pairs(self):
        """With size=2 mosaic on BG1: dot 1 matches dot 0; dot 3 matches dot 2; etc."""
        ppu = _make_ppu()
        _setup_gradient_bg1(ppu)
        ppu.mosaic_enabled = [True, False, False, False]
        ppu.mosaic_size = 2

        ppu.v_counter = 1
        ppu.render_scanline()

        for anchor in range(0, 8, 2):
            expected = _pixel(ppu, anchor, 0)
            got = _pixel(ppu, anchor + 1, 0)
            assert got == expected, (
                f"dot {anchor + 1} should match anchor dot {anchor}: got {got} vs {expected}"
            )

    def test_mosaic_size_4_blocks_groups_of_four(self):
        """With size=4: dots 0-3 all match dot 0; dots 4-7 all match dot 4."""
        ppu = _make_ppu()
        _setup_gradient_bg1(ppu)
        ppu.mosaic_enabled = [True, False, False, False]
        ppu.mosaic_size = 4

        ppu.v_counter = 1
        ppu.render_scanline()

        for anchor in (0, 4):
            expected = _pixel(ppu, anchor, 0)
            for offset in range(4):
                got = _pixel(ppu, anchor + offset, 0)
                assert got == expected, (
                    f"dot {anchor + offset} in block@{anchor}: got {got} vs anchor {expected}"
                )

    def test_mosaic_disable_bit_gated_per_bg(self):
        """Size is 4 but BG1 enable bit is off → BG1 unaffected, renders full gradient."""
        ppu = _make_ppu()
        _setup_gradient_bg1(ppu)
        ppu.mosaic_enabled = [False, True, True, True]  # BG1 disabled
        ppu.mosaic_size = 4

        ppu.v_counter = 1
        ppu.render_scanline()

        colors = [_pixel(ppu, x, 0) for x in range(8)]
        assert len(set(colors)) == 8, (
            f"BG1 mosaic disabled → full gradient expected, got: {colors}"
        )


class TestMosaicVertical:
    def test_mosaic_size_2_pairs_rows(self):
        """With size=2 mosaic: row 1 pixel matches row 0 pixel (same column)."""
        ppu = _make_ppu()
        _setup_gradient_bg1(ppu)
        ppu.mosaic_enabled = [True, False, False, False]
        ppu.mosaic_size = 2

        # Render rows 0 and 1 (v_counter 1 and 2)
        ppu.v_counter = 1
        ppu.render_scanline()
        ppu.v_counter = 2
        ppu.render_scanline()

        for x in range(8):
            r0 = _pixel(ppu, x, 0)
            r1 = _pixel(ppu, x, 1)
            assert r0 == r1, (
                f"col {x}: row 1 {r1} should match row 0 anchor {r0}"
            )
