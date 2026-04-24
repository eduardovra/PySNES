"""
PPU screenshot regression tests.

Each test loads a pre-built ROM from submodules/SNES/PPU/ (PeterLemon collection),
runs both PySNES and Mesen headlessly for N frames, and compares the 256×224
framebuffers pixel-by-pixel.  No static reference PNGs are required; Mesen is
the live oracle.

Marks: @pytest.mark.ppu  — excluded from the default suite with -m "not ppu"

Run:
    uv run pytest pysnes/ppu/test_ppu.py -m ppu -v
"""

import os
import struct
import tempfile
import time
import zlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.ppu

REPO_ROOT    = Path(__file__).parent.parent.parent
PPU_ROMS     = REPO_ROOT / "submodules" / "SNES" / "PPU"
ACTUALS_DIR  = REPO_ROOT / "tests" / "ppu_references"
MC_PER_FRAME = 262 * 1364
SCREEN_W     = 256
SCREEN_H     = 224

# Mesen getScreenBuffer() returns 256x239; visible 224 lines start at row 7.
MESEN_BUF_H      = 239
MESEN_ROW_OFFSET = 7


# ---------------------------------------------------------------------------
# PNG helpers (no Pillow dependency)
# ---------------------------------------------------------------------------

def _write_png(path: Path, pixels: list, width: int, height: int) -> None:
    """Write a flat list of (R, G, B) tuples as an RGB PNG."""
    raw = bytearray()
    for row in range(height):
        raw.append(0)  # filter type None
        for col in range(width):
            r, g, b = pixels[row * width + col]
            raw += bytes([r, g, b])

    def chunk(tag: bytes, body: bytes) -> bytes:
        c = struct.pack(">I", len(body)) + tag + body
        return c + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw))
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


# ---------------------------------------------------------------------------
# PySNES framebuffer capture
# ---------------------------------------------------------------------------

def _run_pysnes(rom_path: Path, n_frames: int) -> list:
    """Run PySNES headlessly for n_frames and return SCREEN_H×SCREEN_W (R,G,B) tuples."""
    from pysnes.pysnes import PySNES  # noqa: PLC0415

    pysnes = PySNES(str(rom_path), settings={"headless": True})
    pysnes.cpu.start(pysnes.scheduler)
    pysnes.ppu.start()

    for _ in range(n_frames):
        frame_end = pysnes.scheduler.master_clock + MC_PER_FRAME
        pysnes.scheduler.run_to(frame_end)

    # Apply INIDISP brightness (0-15) post-VBlank, matching Mesen's getScreenBuffer() behavior.
    # main_bgs stores unbrightened 8-bit values; brightness is applied here at read time.
    brightness = pysnes.ppu.display_brightness
    pixels = []
    for y in range(SCREEN_H):
        for x in range(SCREEN_W):
            u32 = pysnes.ppu.main_bgs[y * SCREEN_W + x]
            r5 = (u32 >> 27) & 0x1F
            g5 = (u32 >> 19) & 0x1F
            b5 = (u32 >> 11) & 0x1F
            r5 = (r5 * brightness) // 15
            g5 = (g5 * brightness) // 15
            b5 = (b5 * brightness) // 15
            r = (r5 << 3) | (r5 >> 2)
            g = (g5 << 3) | (g5 >> 2)
            b = (b5 << 3) | (b5 >> 2)
            pixels.append((r, g, b))
    return pixels


# ---------------------------------------------------------------------------
# Mesen oracle
# ---------------------------------------------------------------------------

def _mesen_bin(config) -> str:
    """Return path to Mesen binary, or pytest.skip() if not found."""
    from pysnes import settings as s  # noqa: PLC0415
    cfg = s.load()
    candidates = [
        os.environ.get("MESEN_BIN"),
        cfg.get("mesen_bin"),
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path
    pytest.skip(
        "Mesen binary not found. Set MESEN_BIN env var or 'mesen_bin' in settings.json"
    )


def _run_mesen(mesen: str, rom_path: Path, n_frames: int) -> list:
    """Run Mesen headlessly for n_frames; return SCREEN_H×SCREEN_W (R,G,B) tuples."""
    import subprocess  # noqa: PLC0415

    lua_script = REPO_ROOT / "scripts" / "mesen_screenshot.lua"
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False, dir="/tmp") as tf:
        out_bin = tf.name

    try:
        env = os.environ.copy()
        env["MESEN_FRAMES"] = str(n_frames)
        env["MESEN_OUTPUT_BIN"] = out_bin

        proc = subprocess.Popen(
            [mesen, "--testrunner", str(lua_script), str(rom_path)],
            env=env,
        )
        expected_size = SCREEN_W * MESEN_BUF_H * 4
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if Path(out_bin).stat().st_size >= expected_size:
                break
            time.sleep(0.1)
        proc.kill()
        proc.wait()

        raw = Path(out_bin).read_bytes()
        count = len(raw) // 4
        assert count == SCREEN_W * MESEN_BUF_H, (
            f"Expected {SCREEN_W * MESEN_BUF_H} pixels, got {count}"
        )
        pixels_u32 = struct.unpack(f"<{count}I", raw)

        pixels = []
        for row in range(SCREEN_H):
            for col in range(SCREEN_W):
                v = pixels_u32[(MESEN_ROW_OFFSET + row) * SCREEN_W + col]
                r = (v >> 16) & 0xFF
                g = (v >>  8) & 0xFF
                b =  v        & 0xFF
                pixels.append((r, g, b))
        return pixels
    finally:
        Path(out_bin).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test cases
# Each entry: (test_id, rom_rel, n_frames)
# Paths are relative to PPU_ROMS (submodules/SNES/PPU/).
#
# NOTE ON FRAME COUNTS
# DMA timing is approximated: PySNES charges 8 MC/byte via a direct
# master_clock advance after the transfer (see dma.py do_transfer).  This
# brings PySNES within ~1-2 frames of Mesen's fade-in timing: PySNES reaches
# brightness=15 around frame 18-19, Mesen around frame 20.  n_frames=20 (and
# n_frames=25 for window/mosaic ROMs) ensures both emulators have completed
# the INIDISP fade-in and are rendering a stable, fully-lit frame.
# ---------------------------------------------------------------------------

PPU_TEST_ROMS = [
    (
        "bg1_2bpp",
        "BGMAP/8x8/2BPP/8x8BG1Map2BPP32x328PAL/8x8BG1Map2BPP32x328PAL.sfc",
        20,
    ),
    (
        "bg2_2bpp",
        "BGMAP/8x8/2BPP/8x8BG2Map2BPP32x328PAL/8x8BG2Map2BPP32x328PAL.sfc",
        20,
    ),
    (
        "bg3_2bpp",
        "BGMAP/8x8/2BPP/8x8BG3Map2BPP32x328PAL/8x8BG3Map2BPP32x328PAL.sfc",
        20,
    ),
    (
        "bg4_2bpp",
        "BGMAP/8x8/2BPP/8x8BG4Map2BPP32x328PAL/8x8BG4Map2BPP32x328PAL.sfc",
        20,
    ),
    (
        "bg_4bpp",
        "BGMAP/8x8/4BPP/8x8BGMap4BPP32x328PAL/8x8BGMap4BPP32x328PAL.sfc",
        20,
    ),
    (
        "tile_flip",
        "BGMAP/8x8/8BPP/TileFlip/8x8BGMapTileFlip.sfc",
        20,
    ),
    pytest.param(
        "mode7_rotzoom",
        "Mode7/RotZoom/RotZoom.sfc",
        20,
        marks=pytest.mark.xfail(reason="Mode 7 not implemented", raises=NotImplementedError, strict=True),
        id="mode7_rotzoom",
    ),
    (
        "window_hdma",
        "Window/WindowHDMA/WindowHDMA.sfc",
        25,
    ),
    (
        "mosaic_mode3",
        "Mosaic/Mode3/MosaicMode3.sfc",
        25,
    ),
]


@pytest.mark.parametrize(
    "test_id,rom_rel,n_frames",
    PPU_TEST_ROMS,
    ids=[t[0] if not hasattr(t, 'id') or t.id is None else t.id for t in PPU_TEST_ROMS],
)
def test_ppu_screenshot(request, test_id, rom_rel, n_frames):
    """Compare PySNES framebuffer against Mesen oracle at the same frame count."""
    rom_path = PPU_ROMS / rom_rel

    if not rom_path.exists():
        pytest.skip(f"ROM not found: {rom_path}")

    mesen = _mesen_bin(request.config)
    ref_pixels = _run_mesen(mesen, rom_path, n_frames)
    got_pixels = _run_pysnes(rom_path, n_frames)

    assert len(ref_pixels) == len(got_pixels) == SCREEN_W * SCREEN_H

    mismatches = [
        (i, ref_pixels[i], got_pixels[i])
        for i in range(len(ref_pixels))
        if ref_pixels[i] != got_pixels[i]
    ]

    if mismatches:
        out_path = ACTUALS_DIR / f"{test_id}_actual.png"
        ref_path = ACTUALS_DIR / f"{test_id}_ref.png"
        _write_png(out_path, got_pixels, SCREEN_W, SCREEN_H)
        _write_png(ref_path, ref_pixels, SCREEN_W, SCREEN_H)
        pct = 100 * len(mismatches) / len(ref_pixels)
        first = mismatches[:5]
        pytest.fail(
            f"{len(mismatches)} pixels differ ({pct:.1f}%) for '{test_id}'.\n"
            f"First mismatches (pixel_idx, expected_rgb, got_rgb): {first}\n"
            f"Actual saved to: {out_path}\n"
            f"Reference saved to: {ref_path}"
        )
