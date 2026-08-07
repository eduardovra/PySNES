"""
Color-math windowing ($2130 CGWSEL bits 5-4, $2125 WOBJSEL bits 4-7, $212C
WOBJLOG bits 2-3).

CGWSEL bits 5-4 gate WHEN color math is applied:
  00 = Always
  01 = Inside color window only
  10 = Outside color window only
  11 = Never

The color window is built from W1 and/or W2 per WOBJSEL bits 4-7, combined by
WOBJLOG bits 2-3 (OR/AND/XOR/XNOR).

These tests mirror test_ppu_color_math.py's SMW-title-like setup: BG1 on
main, BG2 on sub, CGADSUB=0x20 (backdrop ADD). They assert that the color
math gating controls whether the backdrop picks up the sub-screen pixel.

Run:
    uv run --python pypy3.10 pytest pysnes/ppu/test_ppu_color_math_window.py -v
"""

from pysnes.ppu.ppu import Ppu

SCREEN_W = 256
TILEDATA = 0x4000


def _make_ppu() -> Ppu:
    ppu = Ppu()
    ppu.inidisp_set(0x0F)
    ppu._bgmode = 1
    for i in range(128):
        ppu.oam.write(i * 4 + 1, 0xF0)  # y=240: move all sprites off-screen
    return ppu


def _write_cgram(ppu: Ppu, index: int, r5: int, g5: int, b5: int) -> None:
    word = r5 | (g5 << 5) | (b5 << 10)
    ppu.cgram[index * 2 + 0] = word & 0xFF
    ppu.cgram[index * 2 + 1] = (word >> 8) & 0xFF


def _write_4bpp_solid_tile(ppu: Ppu, tile_index: int, color_index: int) -> None:
    bp0 = 0xFF if (color_index & 1) else 0x00
    bp1 = 0xFF if (color_index & 2) else 0x00
    bp2 = 0xFF if (color_index & 4) else 0x00
    bp3 = 0xFF if (color_index & 8) else 0x00
    addr = TILEDATA + tile_index * 32
    for row in range(8):
        ppu.vram[addr + row * 2 + 0] = bp0
        ppu.vram[addr + row * 2 + 1] = bp1
        ppu.vram[addr + 16 + row * 2 + 0] = bp2
        ppu.vram[addr + 16 + row * 2 + 1] = bp3


def _main_pixel(ppu: Ppu, x: int, y: int) -> tuple:
    u32 = ppu.main_bgs[y * SCREEN_W + x]
    return ((u32 >> 24) & 0xFF, (u32 >> 16) & 0xFF, (u32 >> 8) & 0xFF)


def _setup_backdrop_add_bg2(ppu: Ppu) -> None:
    """Mirror SMW title: BG1 main (sparse), BG2 sub (blue), CGADSUB=0x20
    (backdrop ADD).

    BG1 has no opaque tiles so the whole main scanline is backdrop. BG2 fills
    sub-screen with blue. Where color math fires, main = backdrop + blue = blue.
    Where color math is gated off, main stays backdrop (black).
    """
    # Backdrop = black
    _write_cgram(ppu, 0, 0, 0, 0)
    # BG2 palette 2 (4bpp → base 2*16=32) color 1 = blue
    _write_cgram(ppu, 33, 0, 0, 31)

    # BG2 solid blue tile
    _write_4bpp_solid_tile(
        ppu, 0, 1
    )  # tile 0 → color_index=1 → palette color 33 for BG2 pal 2

    # Wait — for BG2 we need palette 2. Let's instead put color at palette-0
    # color-1.
    _write_cgram(ppu, 1, 0, 0, 31)  # BG2 pal 0 color 1 = blue

    # BG1 tilemap: transparent (tile with bitplanes = 0 never gets drawn)
    ppu.bg1.screen_addr = 0
    ppu.bg1.tiledata_addr = TILEDATA
    ppu.bg1.screen_size = 0
    ppu.bg1.tile_size = 0
    ppu.bg1.hoffset = 0
    ppu.bg1.voffset = 0
    ppu.bg1.main_screen_enable = True  # on main but all-transparent tiles
    ppu.bg1.sub_screen_enable = False
    # Write tilemap entries pointing at a never-written tile index 0xFE
    for col in range(32):
        ppu.vram[col * 2 + 0] = 0xFE
        ppu.vram[col * 2 + 1] = 0

    # BG2 tilemap at word 0x1000: all tile 0 (the blue tile we wrote)
    ppu.bg2.screen_addr = 0x800  # word → byte 0x1000
    ppu.bg2.tiledata_addr = TILEDATA
    ppu.bg2.screen_size = 0
    ppu.bg2.tile_size = 0
    ppu.bg2.hoffset = 0
    ppu.bg2.voffset = 0
    ppu.bg2.main_screen_enable = False
    ppu.bg2.sub_screen_enable = True
    for col in range(32):
        ppu.vram[0x1000 + col * 2 + 0] = 0
        ppu.vram[0x1000 + col * 2 + 1] = 0

    # CGWSEL bit 1 = sub-screen layers participate
    ppu.cgwsel = 0b00000010
    # CGADSUB: backdrop participates, ADD (bit 5 set, bits 7/6 clear)
    ppu.cgadsub = 0b00100000


class TestColorMathWindowMode00_Always:
    """CGWSEL bits 5:4 = 00 → color math always applied regardless of window."""

    def test_backdrop_picks_up_sub(self):
        ppu = _make_ppu()
        _setup_backdrop_add_bg2(ppu)
        # mode 00 (always) — ensure bits 5:4 are 0
        ppu.cgwsel = (ppu.cgwsel & ~0x30) | 0x00
        ppu.v_counter = 1
        ppu.render_scanline()
        # Every backdrop pixel should be blue (backdrop + BG2 via ADD).
        assert _main_pixel(ppu, 0, 0) == (0, 0, 255)
        assert _main_pixel(ppu, 128, 0) == (0, 0, 255)
        assert _main_pixel(ppu, 255, 0) == (0, 0, 255)


class TestColorMathWindowMode11_Never:
    """CGWSEL bits 5:4 = 11 → color math never applied."""

    def test_backdrop_stays_backdrop(self):
        ppu = _make_ppu()
        _setup_backdrop_add_bg2(ppu)
        # mode 11 (never)
        ppu.cgwsel = (ppu.cgwsel & ~0x30) | 0x30
        ppu.v_counter = 1
        ppu.render_scanline()
        # Color math fires nowhere → all backdrop pixels stay black.
        for x in (0, 64, 128, 192, 255):
            assert _main_pixel(ppu, x, 0) == (0, 0, 0), (
                f"never mode: pixel ({x},0) should stay backdrop, got "
                f"{_main_pixel(ppu, x, 0)}"
            )


class TestColorMathWindowMode01_Inside:
    """CGWSEL bits 5:4 = 01 → color math only inside color window."""

    def test_empty_math_window_blocks_color_math_everywhere(self):
        """Match SMW f310 config: CGWSEL inside + WH0=255/WH1=0 (empty) + math
        W1 enabled."""
        ppu = _make_ppu()
        _setup_backdrop_add_bg2(ppu)
        ppu.cgwsel = (ppu.cgwsel & ~0x30) | 0x10  # inside window only
        # $2125 WOBJSEL bit 4 = color math W1 enable
        ppu.wobjsel = 0x20  # MATH W1 enable bit 5 set, invert bit 4 clear
        ppu.wh0 = 255
        ppu.wh1 = 0
        ppu.v_counter = 1
        ppu.render_scanline()
        # Empty window, "inside only" → color math fires nowhere.
        for x in (0, 64, 128, 192, 255):
            assert _main_pixel(ppu, x, 0) == (0, 0, 0), (
                f"empty inside-window: ({x},0) should stay backdrop, got "
                f"{_main_pixel(ppu, x, 0)}"
            )

    def test_narrow_math_window_limits_color_math_region(self):
        ppu = _make_ppu()
        _setup_backdrop_add_bg2(ppu)
        ppu.cgwsel = (ppu.cgwsel & ~0x30) | 0x10
        ppu.wobjsel = 0x20  # MATH W1 enable bit 5 set, invert bit 4 clear
        ppu.wh0 = 100
        ppu.wh1 = 150
        ppu.v_counter = 1
        ppu.render_scanline()
        # Inside [100..150]: color math fires → blue.
        assert _main_pixel(ppu, 100, 0) == (0, 0, 255)
        assert _main_pixel(ppu, 125, 0) == (0, 0, 255)
        assert _main_pixel(ppu, 150, 0) == (0, 0, 255)
        # Outside: stays backdrop.
        assert _main_pixel(ppu, 0, 0) == (0, 0, 0)
        assert _main_pixel(ppu, 99, 0) == (0, 0, 0)
        assert _main_pixel(ppu, 151, 0) == (0, 0, 0)
        assert _main_pixel(ppu, 255, 0) == (0, 0, 0)


class TestColorMathWindowMode10_Outside:
    """CGWSEL bits 5:4 = 10 → color math only outside color window."""

    def test_outside_mode(self):
        ppu = _make_ppu()
        _setup_backdrop_add_bg2(ppu)
        ppu.cgwsel = (ppu.cgwsel & ~0x30) | 0x20  # outside window only
        ppu.wobjsel = 0x20  # MATH W1 enable bit 5 set, invert bit 4 clear
        ppu.wh0 = 100
        ppu.wh1 = 150
        ppu.v_counter = 1
        ppu.render_scanline()
        # Inside [100..150]: color math blocked → backdrop.
        assert _main_pixel(ppu, 125, 0) == (0, 0, 0)
        # Outside: color math fires → blue.
        assert _main_pixel(ppu, 0, 0) == (0, 0, 255)
        assert _main_pixel(ppu, 255, 0) == (0, 0, 255)
