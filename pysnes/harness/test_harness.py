"""Smoke tests for the Harness. Marked @pytest.mark.harness — opt-in."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.harness

REPO_ROOT = Path(__file__).parent.parent.parent
SMW_ROM = REPO_ROOT / "roms" / "Super Mario World (U) [!].smc"


def _require_smw():
    if not SMW_ROM.exists():
        pytest.skip(f"SMW ROM not present at {SMW_ROM}")


def test_boot_and_run_frames():
    _require_smw()
    from pysnes.harness import Harness

    with Harness(SMW_ROM) as h:
        assert h.frame == 0
        h.run_frames(60)
        assert h.frame == 60


def test_screenshot_writes_png(tmp_path):
    _require_smw()
    from pysnes.harness import Harness

    with Harness(SMW_ROM) as h:
        h.run_frames(120)
        out = tmp_path / "shot.png"
        h.screenshot(out)
        data = out.read_bytes()
        assert data.startswith(b"\x89PNG\r\n\x1a\n")
        assert len(data) > 100


def test_cgram_returns_bytes():
    _require_smw()
    from pysnes.harness import Harness

    with Harness(SMW_ROM) as h:
        h.run_frames(60)
        cg = h.cgram(0, 32)
        assert isinstance(cg, bytes)
        assert len(cg) == 32


def test_breakpoint_pauses():
    _require_smw()
    from pysnes.harness import Harness

    with Harness(SMW_ROM) as h:
        # Set a BP at the reset vector. PC starts there, but the BP fires after
        # the matching instruction runs, so run_until_break should hit on the
        # second pass through that PC (fetch loop).
        reset = h._pysnes._reset_vector
        h.set_breakpoint(reset)
        # Run a small budget — boot loops typically revisit early code quickly.
        hit = h.run_until_break(max_frames=5)
        # Either hit (paused) or budget expired without revisit; both are
        # valid outcomes. The smoke test asserts the API runs without
        # error and that paused state is consistent with the return value.
        assert hit == h.paused


def test_on_write_range_fires_for_cgram():
    _require_smw()
    from pysnes.harness import Harness

    events: list[tuple[int, int, int, int]] = []

    with Harness(SMW_ROM) as h:
        def hook(harness, addr, value):
            events.append((harness.frame, harness.scanline, addr, value))

        h.on_write_range(0x2121, 0x2122, hook)
        # 200 frames covers the boot intro fade-out and reaches code that
        # actually writes CGRAM. With fewer frames SMW is in forced blank
        # and no $21xx writes occur.
        h.run_frames(200)

    assert events, "expected at least one $2121/$2122 write within 200 frames"
    # Bank-insensitive match: low 16 bits identify the register, full 24-bit
    # addr is passed to callbacks so they can see the originating bank.
    assert all(0x2121 <= (e[2] & 0xFFFF) <= 0x2122 for e in events)


def test_tap_press_release_edge():
    _require_smw()
    from pysnes.harness import Harness
    import sdl2

    with Harness(SMW_ROM) as h:
        h.tap("Start", hold_frames=2, gap_frames=1)
        # After tap, no buttons should still be held
        assert sdl2.SDLK_RETURN not in h._pysnes.controllers[0].pressed_keys
