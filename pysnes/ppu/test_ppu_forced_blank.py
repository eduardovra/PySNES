from pysnes.ppu.ppu import Ppu, SCREEN_WIDTH


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


def test_forced_blank_mid_frame_does_not_clear_earlier_snapshots():
    """With deferred rendering, asserting forced blank mid-frame affects only
    scanlines whose HBlank snapshot is captured after the assertion.  Scanlines
    snapshotted before display_disable=True are rendered normally at VBlank;
    no retroactive clearing of the framebuffer occurs (that matched the old
    immediate-render model, not real hardware behaviour)."""
    ppu = Ppu()

    # Seed 4 rows with red so we can tell whether they were cleared.
    for row in range(4):
        base = row * SCREEN_WIDTH
        for x in range(SCREEN_WIDTH):
            ppu.main_bgs[base + x] = 0xFF0000FF
            ppu.sub_bgs[base + x] = 0xFF0000FF
            ppu.main_layer[base + x] = 5

    # v_counter=4 — HBlank snapshots for scanlines 1-4 would have been taken
    # with display_disable=False (already).  Asserting forced blank now only
    # affects subsequent snapshots, not the existing framebuffer data.
    ppu.v_counter = 4
    ppu.inidisp_set(0x80)  # forced blank, brightness 0

    # Framebuffer is written only at VBlank; inidisp_set alone must not touch it.
    for row in range(4):
        base = row * SCREEN_WIDTH
        for x in (0, 64, 128, 255):
            assert _rgb(ppu.main_bgs[base + x]) == (255, 0, 0), \
                f"row {row} x={x} framebuffer must be untouched by inidisp_set alone"
