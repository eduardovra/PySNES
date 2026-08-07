from array import array

# NTSC scanline timing (master clocks)
_MC_PER_SCANLINE: int = 1364
_HBLANK_START_MC: int = 1096
_VBLANK_START_LINE: int = 225
_TOTAL_SCANLINES: int = 262

SCREEN_WIDTH = 256
SCREEN_HEIGHT = 224
# TODO: overscan — PAL uses 239/240 visible lines; SETINI $2133 bit 2 enables
# NTSC pseudo-overscan to 239 lines

# Bit positions for each of the 8 pixels in a tile byte, right-to-left.
_PIXEL_SEQUENCE = [7, 6, 5, 4, 3, 2, 1, 0]

# 256-entry LUT: key = (plane0_nibble) | (plane1_nibble << 4). Value = 4
# per-pixel 2-bit color codes packed one per byte (byte p = h_shift p).
_colorcode_table = array("I", [0] * 256)
for _b in range(256):
    _b1n = _b & 0xF
    _b2n = (_b >> 4) & 0xF
    _v = 0
    for _p in range(4):
        _v |= (((_b1n >> _p) & 1) | (((_b2n >> _p) & 1) << 1)) << (_p * 8)
    _colorcode_table[_b] = _v
del _b, _b1n, _b2n, _v, _p
