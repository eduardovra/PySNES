"""
Synthetic BG window-masking unit tests for $2123 W12SEL + $2126-$2129 WH0-3 +
$212A WBGLOG + $212E TMW.

These bypass ROM loading — write VRAM/CGRAM directly, call draw_background_scanline(),
and assert pixel output. No Mesen, no ROM files.

Setup:
  - BG1 tilemap row 0: all tile 0 (solid RED)
  - CGRAM backdrop (index 0) = BLACK (so masked pixels read as black)
  - Brightness = 15 (colours pass through unmodified)

Run:
    uv run --python pypy3.10 pytest pysnes/ppu/test_ppu_bg_window.py -v
"""

import pytest

from pysnes.ppu import bg_renderer
from pysnes.ppu.ppu import Ppu

SCREEN_W = 256
TILEDATA = 0x4000

RED = (255, 0, 0)
BLACK = (0, 0, 0)


def _make_ppu() -> Ppu:
    ppu = Ppu()
    ppu.inidisp_set(0x0F)
    ppu._bgmode = 1
    return ppu


def _write_cgram(ppu: Ppu, index: int, r5: int, g5: int, b5: int) -> None:
    word = r5 | (g5 << 5) | (b5 << 10)
    ppu.cgram[index * 2 + 0] = word & 0xFF
    ppu.cgram[index * 2 + 1] = (word >> 8) & 0xFF


def _write_2bpp_solid_tile(ppu: Ppu, tile_index: int, color_index: int) -> None:
    bp0 = 0xFF if (color_index & 1) else 0x00
    bp1 = 0xFF if (color_index & 2) else 0x00
    addr = TILEDATA + tile_index * 16
    for row in range(8):
        ppu.vram[addr + row * 2 + 0] = bp0
        ppu.vram[addr + row * 2 + 1] = bp1


def _pixel(ppu: Ppu, x: int, y: int) -> tuple:
    u32 = ppu.main_bgs[y * SCREEN_W + x]
    return ((u32 >> 24) & 0xFF, (u32 >> 16) & 0xFF, (u32 >> 8) & 0xFF)


def _setup_bg1_solid_red(ppu: Ppu) -> None:
    _write_cgram(ppu, 0, 0, 0, 0)  # backdrop = BLACK
    _write_cgram(ppu, 1, 31, 0, 0)  # palette 1 = RED
    _write_2bpp_solid_tile(ppu, 0, 1)  # tile 0 = solid RED
    # Row 0 of tilemap: all tile 0
    for col in range(32):
        ppu.vram[col * 2 + 0] = 0
        ppu.vram[col * 2 + 1] = 0x00

    ppu.bg1.screen_addr = 0
    ppu.bg1.tiledata_addr = TILEDATA
    ppu.bg1.screen_size = 0
    ppu.bg1.tile_size = 0
    ppu.bg1.hoffset = 0
    ppu.bg1.voffset = 0
    ppu.bg1.main_screen_enable = True

    # Enable window masking for BG1 on main screen
    ppu.tmw = 0x01


def _draw_row_with_backdrop(ppu: Ppu, scanline: int) -> None:
    """Fill backdrop, then draw BG1 — matches real render_scanline ordering."""
    ppu.v_counter = scanline
    bg_renderer.draw_scanline_backdrop(ppu)
    bg_renderer.draw_background_scanline(
        ppu, ppu.bg1, bpp=2, priority_selector=0
    )


# ---------------------------------------------------------------------------
# W1 only (baseline — previously worked)
# ---------------------------------------------------------------------------


class TestW1Only:
    def test_w1_invert0_masks_inside(self):
        """W1 enabled, invert=0 → pixels INSIDE [wh0,wh1] are masked (BLACK)."""
        ppu = _make_ppu()
        _setup_bg1_solid_red(ppu)
        ppu.w12sel = 0b00000010  # BG1 W1 enable, invert=0
        ppu.wh0 = 64
        ppu.wh1 = 128
        _draw_row_with_backdrop(ppu, scanline=1)

        assert _pixel(ppu, 60, 0) == RED
        assert _pixel(ppu, 64, 0) == BLACK
        assert _pixel(ppu, 96, 0) == BLACK
        assert _pixel(ppu, 128, 0) == BLACK
        assert _pixel(ppu, 132, 0) == RED

    def test_w1_invert1_masks_outside(self):
        """W1 enabled, invert=1 → pixels OUTSIDE [wh0,wh1] are masked (BLACK)."""
        ppu = _make_ppu()
        _setup_bg1_solid_red(ppu)
        ppu.w12sel = 0b00000011  # BG1 W1 enable + invert
        ppu.wh0 = 64
        ppu.wh1 = 128
        _draw_row_with_backdrop(ppu, scanline=1)

        assert _pixel(ppu, 0, 0) == BLACK
        assert _pixel(ppu, 60, 0) == BLACK
        assert _pixel(ppu, 64, 0) == RED
        assert _pixel(ppu, 128, 0) == RED
        assert _pixel(ppu, 130, 0) == BLACK


# ---------------------------------------------------------------------------
# W1 + W2 with all four WBGLOG combine modes (regression for WindowMultiHDMA)
# ---------------------------------------------------------------------------


class TestW1W2Combine:
    """BG1 W1=[16,112] invert=1; BG1 W2=[144,240] invert=1.

    With invert=1, each window's "mask value" is TRUE when X lies OUTSIDE its range.
    WBGLOG per BG1 (bits 1:0): 0=OR, 1=AND, 2=XOR, 3=XNOR.

    AND case (matches the WindowMultiHDMA ROM): pixel masked iff it's outside
    both windows — i.e. BG1 is drawn inside at least one of W1 or W2.
    """

    W12SEL_BG1_BOTH_INVERT = 0b00001111  # W2 enable+invert, W1 enable+invert

    def _setup_two_windows(self, ppu: Ppu, logic: int) -> None:
        _setup_bg1_solid_red(ppu)
        ppu.w12sel = self.W12SEL_BG1_BOTH_INVERT
        ppu.wh0, ppu.wh1 = 16, 112
        ppu.wh2, ppu.wh3 = 144, 240
        ppu.wbglog = logic & 0x03  # BG1 logic goes into bits 1:0

    def test_and_logic_shows_bg_in_either_window(self):
        """WBGLOG=AND + invert=1 both → BG1 drawn inside W1∪W2."""
        ppu = _make_ppu()
        self._setup_two_windows(ppu, logic=1)  # AND
        _draw_row_with_backdrop(ppu, scanline=1)

        # Outside both windows → masked (black)
        assert _pixel(ppu, 0, 0) == BLACK, "left strip before W1"
        assert _pixel(ppu, 15, 0) == BLACK
        assert _pixel(ppu, 113, 0) == BLACK, "gap between W1 and W2"
        assert _pixel(ppu, 143, 0) == BLACK
        assert _pixel(ppu, 241, 0) == BLACK
        assert _pixel(ppu, 255, 0) == BLACK
        # Inside W1 → visible
        assert _pixel(ppu, 16, 0) == RED
        assert _pixel(ppu, 64, 0) == RED
        assert _pixel(ppu, 112, 0) == RED
        # Inside W2 → visible
        assert _pixel(ppu, 144, 0) == RED
        assert _pixel(ppu, 200, 0) == RED
        assert _pixel(ppu, 240, 0) == RED

    def test_or_logic_masks_whole_row(self):
        """WBGLOG=OR + invert=1 both → masked whenever outside either — entire row masked."""
        ppu = _make_ppu()
        self._setup_two_windows(ppu, logic=0)  # OR
        _draw_row_with_backdrop(ppu, scanline=1)

        for x in (0, 16, 64, 112, 113, 143, 144, 200, 240, 255):
            assert _pixel(ppu, x, 0) == BLACK, f"x={x} should be masked"

    def test_xor_logic_masks_symmetric_strips(self):
        """XOR: masked only where W1_val XOR W2_val is true.

        With invert=1 and disjoint ranges:
          - X in W1 [16..112]: W1_val=0, W2_val=1 → XOR=1 → masked
          - X in W2 [144..240]: W1_val=1, W2_val=0 → XOR=1 → masked
          - X outside both: W1_val=1, W2_val=1 → XOR=0 → visible
        """
        ppu = _make_ppu()
        self._setup_two_windows(ppu, logic=2)  # XOR
        _draw_row_with_backdrop(ppu, scanline=1)

        assert _pixel(ppu, 0, 0) == RED, "outside both → visible"
        assert _pixel(ppu, 15, 0) == RED
        assert _pixel(ppu, 16, 0) == BLACK, "inside W1 only → masked"
        assert _pixel(ppu, 112, 0) == BLACK
        assert _pixel(ppu, 113, 0) == RED, "gap → visible"
        assert _pixel(ppu, 144, 0) == BLACK, "inside W2 only → masked"
        assert _pixel(ppu, 240, 0) == BLACK
        assert _pixel(ppu, 255, 0) == RED


# ---------------------------------------------------------------------------
# W2-only regression (old code ignored W2 entirely)
# ---------------------------------------------------------------------------


class TestW2Only:
    def test_w2_invert0_masks_inside(self):
        """Only W2 enabled — masks pixels inside [wh2, wh3]."""
        ppu = _make_ppu()
        _setup_bg1_solid_red(ppu)
        ppu.w12sel = 0b00001000  # BG1: only W2 enable, invert=0
        ppu.wh2, ppu.wh3 = 144, 240
        _draw_row_with_backdrop(ppu, scanline=1)

        assert _pixel(ppu, 64, 0) == RED
        assert _pixel(ppu, 143, 0) == RED
        assert _pixel(ppu, 144, 0) == BLACK
        assert _pixel(ppu, 200, 0) == BLACK
        assert _pixel(ppu, 240, 0) == BLACK
        assert _pixel(ppu, 241, 0) == RED


# ---------------------------------------------------------------------------
# TMW bit gates masking entirely
# ---------------------------------------------------------------------------


class TestTmwGate:
    def test_tmw_disabled_draws_everywhere(self):
        """With TMW bit 0 clear, even an enabled W1 does nothing for BG1."""
        ppu = _make_ppu()
        _setup_bg1_solid_red(ppu)
        ppu.tmw = 0x00  # <- disable BG1 window masking
        ppu.w12sel = 0b00000010  # BG1 W1 enable (would normally mask)
        ppu.wh0, ppu.wh1 = 64, 128
        _draw_row_with_backdrop(ppu, scanline=1)

        for x in (0, 64, 96, 128, 200, 255):
            assert _pixel(ppu, x, 0) == RED, f"x={x} should be unmasked"
