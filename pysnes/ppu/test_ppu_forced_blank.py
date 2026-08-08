from pysnes.ppu.ppu import SCREEN_WIDTH, Ppu


def _rgb(u32: int) -> tuple[int, int, int]:
    return ((u32 >> 24) & 0xFF, (u32 >> 16) & 0xFF, (u32 >> 8) & 0xFF)


def test_forced_blank_overwrites_stale_scanline_with_black():
    ppu = Ppu()

    # Seed the scanline with stale visible data to mirror the intro bug.
    for x in range(SCREEN_WIDTH):
        ppu.main_bgs[x] = 0xFF0000FF
        ppu.sub_bgs[x] = 0x00FF00FF
        ppu.main_layer[x] = 3

    ppu.v_counter = 1
    ppu.inidisp_set(0x80)  # forced blank, brightness 0
    ppu.render_scanline()

    for x in (0, 64, 128, 255):
        assert _rgb(ppu.main_bgs[x]) == (0, 0, 0)
        assert _rgb(ppu.sub_bgs[x]) == (0, 0, 0)
        assert ppu.main_layer[x] == 0


def test_forced_blank_mid_frame_clears_already_rendered_rows():
    """When forced blank is asserted after a few scanlines have rendered,
    inidisp_set must retroactively clear those rows so stale content
    (e.g. old sprites from a previous scene) doesn't flash at the top."""
    ppu = Ppu()

    # Simulate 4 scanlines already rendered with visible data (rows 0..3).
    for row in range(4):
        base = row * SCREEN_WIDTH
        for x in range(SCREEN_WIDTH):
            ppu.main_bgs[base + x] = 0xFF0000FF  # red
            ppu.sub_bgs[base + x] = 0xFF0000FF
            ppu.main_layer[base + x] = 5  # OBJ layer

    # v_counter=4 means scanlines 1..4 have already been rendered (rows 0..3).
    ppu.v_counter = 4

    # Game writes $80 to $2100 mid-frame (e.g. from main loop, not NMI).
    ppu.inidisp_set(0x80)

    # All 4 rendered rows must now be black, not the stale red pixels.
    for row in range(4):
        base = row * SCREEN_WIDTH
        for x in (0, 64, 128, 255):
            assert _rgb(ppu.main_bgs[base + x]) == (0, 0, 0), (
                f"row {row} x={x} should be black after mid-frame forced blank"
            )
            assert _rgb(ppu.sub_bgs[base + x]) == (0, 0, 0)
            assert ppu.main_layer[base + x] == 0

    # Rows beyond v_counter should be untouched (not yet rendered).
    assert ppu.main_bgs[4 * SCREEN_WIDTH] == 0, "row 4 should be untouched"
