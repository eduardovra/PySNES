"""
Sub-screen rendering and color math (minimal slice).

These tests pin down the behaviour the SMW title screen and Nintendo Presents
splash depend on:

  - A `sub_bgs` framebuffer parallel to `main_bgs`.
  - Backgrounds with `sub_screen_enable=True` render into `sub_bgs`.
  - Backgrounds with `main_screen_enable=False` no longer disappear; they go
    into `sub_bgs` if their sub-screen flag is set.
  - A composite pass at the end of the scanline applies color math controlled
    by `CGADSUB` ($2131) and `CGWSEL` ($2130).
  - For the cases SMW uses (CGADSUB selects backdrop only, ADD operation),
    pixels where the main-screen layer is the backdrop pick up the sub-screen
    pixel; pixels where any other main-screen layer drew are unchanged.

Coverage NOT in this slice (deliberately): subtract, half-add, color-math
windowing (CGWSEL bits 4-7), separate sub-screen backdrop via COLDATA,
direct-color mode.

Run:
    uv run --python pypy3.10 pytest pysnes/ppu/test_ppu_color_math.py -v
"""

import pytest

from pysnes.ppu.ppu import Ppu

SCREEN_W = 256
TILEDATA = 0x4000


# ---------------------------------------------------------------------------
# Helpers (mirror of test_ppu_scroll.py — kept private to avoid coupling)
# ---------------------------------------------------------------------------

def _make_ppu() -> Ppu:
    ppu = Ppu()
    ppu.inidisp_set(0x0F)  # full brightness so colors pass through unchanged
    ppu._bgmode = 1
    return ppu


def _write_2bpp_solid_tile(ppu: Ppu, tile_index: int, color_index: int) -> None:
    bp0 = 0xFF if (color_index & 1) else 0x00
    bp1 = 0xFF if (color_index & 2) else 0x00
    addr = TILEDATA + tile_index * 16
    for row in range(8):
        ppu.vram[addr + row * 2 + 0] = bp0
        ppu.vram[addr + row * 2 + 1] = bp1


def _write_4bpp_solid_tile(ppu: Ppu, tile_index: int, color_index: int) -> None:
    """4bpp tile = 32 bytes. Bytes 0-15 = bp0/bp1 interleaved, bytes 16-31 = bp2/bp3 interleaved."""
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


def _write_cgram(ppu: Ppu, index: int, r5: int, g5: int, b5: int) -> None:
    word = r5 | (g5 << 5) | (b5 << 10)
    ppu.cgram[index * 2 + 0] = word & 0xFF
    ppu.cgram[index * 2 + 1] = (word >> 8) & 0xFF


def _main_pixel(ppu: Ppu, x: int, y: int) -> tuple:
    u32 = ppu.main_bgs[y * SCREEN_W + x]
    return ((u32 >> 24) & 0xFF, (u32 >> 16) & 0xFF, (u32 >> 8) & 0xFF)


def _sub_pixel(ppu: Ppu, x: int, y: int) -> tuple:
    u32 = ppu.sub_bgs[y * SCREEN_W + x]
    return ((u32 >> 24) & 0xFF, (u32 >> 16) & 0xFF, (u32 >> 8) & 0xFF)


def _setup_solid_bg(
    ppu: Ppu,
    bg_index: int,
    color_index: int,
    rgb5: tuple,
    *,
    main: bool,
    sub: bool,
) -> None:
    """Configure BG{bg_index} to render a single solid colour everywhere."""
    bg = (None, ppu.bg1, ppu.bg2, ppu.bg3, ppu.bg4)[bg_index]

    # Always set CGRAM index 0 = black (backdrop), index = color_index = chosen colour.
    _write_cgram(ppu, 0, 0, 0, 0)
    _write_cgram(ppu, color_index, *rgb5)

    _write_2bpp_solid_tile(ppu, 0, color_index)

    # Tilemap row 0: all tile 0 (every column).
    base = bg.screen_addr if hasattr(bg, "screen_addr") else 0
    for col in range(32):
        addr = base + col * 2
        ppu.vram[addr] = 0
        ppu.vram[addr + 1] = 0

    bg.tiledata_addr = TILEDATA
    bg.screen_size = 0
    bg.tile_size = 0
    bg.hoffset = 0
    bg.voffset = 0
    bg.main_screen_enable = main
    bg.sub_screen_enable = sub


# ---------------------------------------------------------------------------
# Sub-screen buffer existence and sizing
# ---------------------------------------------------------------------------

class TestSubScreenBuffer:
    def test_sub_bgs_buffer_exists(self):
        ppu = _make_ppu()
        assert hasattr(ppu, "sub_bgs"), "Ppu must expose a sub_bgs framebuffer"

    def test_sub_bgs_same_size_as_main(self):
        ppu = _make_ppu()
        assert len(ppu.sub_bgs) == len(ppu.main_bgs), (
            "sub_bgs must be the same size as main_bgs"
        )


# ---------------------------------------------------------------------------
# Per-screen routing: backgrounds land in main, sub, or both
# ---------------------------------------------------------------------------

class TestPerScreenRouting:
    """Verify each background renders into the right buffer based on its enable flags."""

    def test_main_only_bg_does_not_touch_sub(self):
        """BG1 main=True/sub=False → main_bgs has the BG colour, sub_bgs stays at backdrop."""
        ppu = _make_ppu()
        ppu.bg1.screen_addr = 0
        _setup_solid_bg(ppu, 1, color_index=1, rgb5=(31, 0, 0), main=True, sub=False)

        ppu.v_counter = 1
        ppu.render_scanline()

        assert _main_pixel(ppu, 0, 0) == (255, 0, 0), "BG1 should appear in main"
        assert _sub_pixel(ppu, 0, 0) == (0, 0, 0), "sub_bgs should still hold backdrop"

    def test_sub_only_bg_does_not_touch_main(self):
        """BG2 main=False/sub=True → sub_bgs has the BG colour, main_bgs stays at backdrop."""
        ppu = _make_ppu()
        ppu.bg2.screen_addr = 0
        _setup_solid_bg(ppu, 2, color_index=2, rgb5=(0, 0, 31), main=False, sub=True)

        ppu.v_counter = 1
        ppu.render_scanline()

        assert _main_pixel(ppu, 0, 0) == (0, 0, 0), "main_bgs should still hold backdrop"
        assert _sub_pixel(ppu, 0, 0) == (0, 0, 255), "BG2 should appear in sub"

    def test_dual_screen_bg_renders_to_both(self):
        """A BG with main=True AND sub=True writes both buffers."""
        ppu = _make_ppu()
        ppu.bg1.screen_addr = 0
        _setup_solid_bg(ppu, 1, color_index=1, rgb5=(0, 31, 0), main=True, sub=True)

        ppu.v_counter = 1
        ppu.render_scanline()

        assert _main_pixel(ppu, 0, 0) == (0, 255, 0)
        assert _sub_pixel(ppu, 0, 0) == (0, 255, 0)


# ---------------------------------------------------------------------------
# Color math compositing (the SMW title-screen case)
# ---------------------------------------------------------------------------

class TestColorMathBackdropAdd:
    """CGADSUB=0x20 (backdrop participates, ADD) + CGWSEL=0x02 (sub layers enabled).

    This is what SMW's title screen sets: BG2 is on the sub-screen only, and where
    the main screen is just backdrop, the final pixel should be backdrop + sub.
    With backdrop = black, that simplifies to just the sub pixel."""

    def _setup_smw_title_like(self, ppu: Ppu) -> None:
        """BG1 on main only (the logo), BG2 on sub only (the sky)."""
        # BG1: solid red, but only on the LEFT half of the row (cols 0-15).
        # We do this by leaving the right half of the tilemap pointing at a transparent tile.
        ppu.bg1.screen_addr = 0
        ppu.bg2.screen_addr = 0x800  # word offset 0x800 → byte 0x1000 (different region)

        # Backdrop = black
        _write_cgram(ppu, 0, 0, 0, 0)
        # BG1 palette index 1 = red, index 2 (transparent placeholder) stays 0/0/0
        _write_cgram(ppu, 1, 31, 0, 0)
        # BG2 palette index 2 = blue (the "sky")
        _write_cgram(ppu, 2, 0, 0, 31)

        # BG1/BG2 are 4bpp in mode 1 → use 4bpp tiles. Different tile indices so they
        # don't share VRAM bytes (each 4bpp tile = 32 bytes).
        _write_4bpp_solid_tile(ppu, 0, 1)
        _write_4bpp_solid_tile(ppu, 1, 2)

        # BG1 tilemap (at byte 0): tile 0 in cols 0-15, transparent (use a tile we never wrote = bp0=bp1=0) in cols 16-31
        # CGRAM index 0 is "transparent" by SNES convention, so a tile with all-zero bitplanes renders nothing.
        for col in range(32):
            addr = 0 + col * 2
            ppu.vram[addr] = 0 if col < 16 else 0xFE  # tile FE we never wrote → bitplanes 0 → transparent
            ppu.vram[addr + 1] = 0

        # BG2 tilemap (at byte 0x1000 = word 0x800): tile 1 (blue) everywhere
        for col in range(32):
            addr = 0x1000 + col * 2
            ppu.vram[addr] = 1
            ppu.vram[addr + 1] = 0

        for bg, en_main, en_sub in ((ppu.bg1, True, False), (ppu.bg2, False, True)):
            bg.tiledata_addr = TILEDATA
            bg.screen_size = 0
            bg.tile_size = 0
            bg.hoffset = 0
            bg.voffset = 0
            bg.main_screen_enable = en_main
            bg.sub_screen_enable = en_sub

        # CGWSEL bit 1 = sub-screen layers (not just sub backdrop) participate in math
        ppu.cgwsel = 0b00000010
        # CGADSUB bit 5 = backdrop is the main-screen layer that takes part in math
        # bit 7 = 0 → ADD (not subtract); bit 6 = 0 → no half
        ppu.cgadsub = 0b00100000

    def test_main_backdrop_picks_up_sub_pixel(self):
        """Where main is backdrop, the composited pixel equals the sub-screen pixel."""
        ppu = _make_ppu()
        self._setup_smw_title_like(ppu)

        ppu.v_counter = 1
        ppu.render_scanline()

        # Right half (cols 16-31, pixels 128-255): main = backdrop (black), sub = blue (sky).
        # With CGADSUB=0x20 ADD: result = (0,0,0) + (0,0,255) = (0,0,255).
        assert _main_pixel(ppu, 200, 0) == (0, 0, 255), (
            "Backdrop + sub should equal the sub pixel where main is bare backdrop"
        )

    def test_main_bg_pixel_is_unchanged_by_color_math(self):
        """Where BG1 is on the main screen, color math leaves it alone (BG1 is not in CGADSUB)."""
        ppu = _make_ppu()
        self._setup_smw_title_like(ppu)

        ppu.v_counter = 1
        ppu.render_scanline()

        # Left half (cols 0-15, pixels 0-127): main = BG1 (red). BG1 bit (bit 0) is NOT
        # set in CGADSUB, so BG1 pixels pass through as-is.
        assert _main_pixel(ppu, 50, 0) == (255, 0, 0), (
            "BG1 pixel should not be modified by color math when its CGADSUB bit is clear"
        )

    def test_color_math_disabled_produces_main_only(self):
        """With CGADSUB=0 no math runs, so backdrop areas stay backdrop even if sub has content."""
        ppu = _make_ppu()
        self._setup_smw_title_like(ppu)
        ppu.cgadsub = 0  # disable all color math

        ppu.v_counter = 1
        ppu.render_scanline()

        # Right half: main = backdrop, sub = blue. With math off, result stays backdrop.
        assert _main_pixel(ppu, 200, 0) == (0, 0, 0), (
            "With color math disabled, the main backdrop should be visible (not the sub)"
        )
