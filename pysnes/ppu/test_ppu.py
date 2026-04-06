"""
PPU screenshot regression tests.

Each test loads a pre-built ROM from submodules/SNES/PPU/ (PeterLemon collection),
runs PySNES headlessly for N frames, and compares the 256×224 framebuffer against
the reference PNG that ships alongside each ROM.

On failure the actual framebuffer is saved to tests/ppu_references/<id>_actual.png
for visual inspection.

Marks: @pytest.mark.ppu  — excluded from the default suite with -m "not ppu"

Run:
    uv run --python pypy3.10 pytest pysnes/ppu/test_ppu.py -m ppu -v
"""

import os
import struct
import subprocess
import tempfile
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
MESEN_BUF_H     = 239
MESEN_ROW_OFFSET = 7


# ---------------------------------------------------------------------------
# PNG helpers (no Pillow dependency)
# ---------------------------------------------------------------------------

def _read_png_pixels(path: Path) -> list:
    """Return a flat list of (R, G, B) tuples from an RGB PNG."""
    with open(path, "rb") as f:
        data = f.read()

    assert data[:8] == b"\x89PNG\r\n\x1a\n", f"Not a PNG: {path}"

    idat_chunks = []
    i = 8
    width = height = None
    while i < len(data):
        length = struct.unpack(">I", data[i:i+4])[0]
        chunk_type = data[i+4:i+8]
        chunk_data = data[i+8:i+8+length]
        i += 12 + length
        if chunk_type == b"IHDR":
            width, height = struct.unpack(">II", chunk_data[:8])
            bit_depth   = chunk_data[8]
            color_type  = chunk_data[9]
            assert bit_depth == 8 and color_type == 2, (
                f"Only 8-bit RGB PNGs supported, got bit_depth={bit_depth} color_type={color_type}"
            )
        elif chunk_type == b"IDAT":
            idat_chunks.append(chunk_data)

    raw = zlib.decompress(b"".join(idat_chunks))
    stride = 1 + width * 3  # filter byte + RGB bytes per row
    pixels = []
    for row in range(height):
        base = row * stride + 1  # skip filter byte
        for col in range(width):
            o = base + col * 3
            pixels.append((raw[o], raw[o+1], raw[o+2]))
    return pixels, width, height


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
# Mesen reference generation
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


def _generate_ref_png(mesen: str, rom_path: Path, ref_path: Path, n_frames: int) -> None:
    """Run Mesen headlessly, capture framebuffer, save as reference PNG."""
    lua_script = REPO_ROOT / "scripts" / "mesen_screenshot.lua"
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tf:
        out_bin = tf.name

    try:
        env = os.environ.copy()
        env["MESEN_FRAMES"] = str(n_frames)
        env["MESEN_OUTPUT_BIN"] = out_bin

        import time  # noqa: PLC0415
        proc = subprocess.Popen(
            [mesen, str(rom_path), "--headless", "--lua", str(lua_script)],
            env=env,
        )
        # Wait for Mesen to finish writing the output file (it hangs after emu.stop())
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

        # Extract visible 224 rows starting at MESEN_ROW_OFFSET
        pixels = []
        for row in range(SCREEN_H):
            for col in range(SCREEN_W):
                v = pixels_u32[(MESEN_ROW_OFFSET + row) * SCREEN_W + col]
                r = (v >> 16) & 0xFF
                g = (v >>  8) & 0xFF
                b =  v        & 0xFF
                pixels.append((r, g, b))

        _write_png(ref_path, pixels, SCREEN_W, SCREEN_H)
        print(f"  Saved reference: {ref_path}")
    finally:
        Path(out_bin).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test cases
# Each entry: (test_id, rom_rel, ref_png_rel, n_frames)
# Paths are relative to PPU_ROMS (submodules/SNES/PPU/).
# ---------------------------------------------------------------------------

PPU_TEST_ROMS = [
    (
        "bg1_2bpp",
        "BGMAP/8x8/2BPP/8x8BG1Map2BPP32x328PAL/8x8BG1Map2BPP32x328PAL.sfc",
        "BGMAP/8x8/2BPP/8x8BG1Map2BPP32x328PAL/8x8BG1Map2BPP32x328PAL.png",
        5,
    ),
    (
        "bg2_2bpp",
        "BGMAP/8x8/2BPP/8x8BG2Map2BPP32x328PAL/8x8BG2Map2BPP32x328PAL.sfc",
        "BGMAP/8x8/2BPP/8x8BG2Map2BPP32x328PAL/8x8BG2Map2BPP32x328PAL.png",
        5,
    ),
    (
        "bg3_2bpp",
        "BGMAP/8x8/2BPP/8x8BG3Map2BPP32x328PAL/8x8BG3Map2BPP32x328PAL.sfc",
        "BGMAP/8x8/2BPP/8x8BG3Map2BPP32x328PAL/8x8BG3Map2BPP32x328PAL.png",
        5,
    ),
    (
        "bg4_2bpp",
        "BGMAP/8x8/2BPP/8x8BG4Map2BPP32x328PAL/8x8BG4Map2BPP32x328PAL.sfc",
        "BGMAP/8x8/2BPP/8x8BG4Map2BPP32x328PAL/8x8BG4Map2BPP32x328PAL.png",
        5,
    ),
    (
        "bg_4bpp",
        "BGMAP/8x8/4BPP/8x8BGMap4BPP32x328PAL/8x8BGMap4BPP32x328PAL.sfc",
        "BGMAP/8x8/4BPP/8x8BGMap4BPP32x328PAL/8x8BGMap4BPP32x328PAL.png",
        5,
    ),
    (
        "tile_flip",
        "BGMAP/8x8/8BPP/TileFlip/8x8BGMapTileFlip.sfc",
        "BGMAP/8x8/8BPP/TileFlip/8x8BGMapTileFlip.png",
        20,
    ),
    (
        "mode7_rotzoom",
        "Mode7/RotZoom/RotZoom.sfc",
        "Mode7/RotZoom/RotZoom.png",
        10,
    ),
    (
        "window_hdma",
        "Window/WindowHDMA/WindowHDMA.sfc",
        "Window/WindowHDMA/WindowHDMA.png",
        3,  # reference captured at brightness=3 (3 NMIs into FadeIN)
    ),
    (
        "mosaic_mode3",
        "Mosaic/Mode3/MosaicMode3.sfc",
        "Mosaic/Mode3/MosaicMode3.png",
        2,  # reference captured at brightness=2 (2 NMIs into FadeIN)
    ),
]


@pytest.mark.parametrize(
    "test_id,rom_rel,ref_rel,n_frames",
    PPU_TEST_ROMS,
    ids=[t[0] for t in PPU_TEST_ROMS],
)
def test_ppu_screenshot(request, test_id, rom_rel, ref_rel, n_frames):
    """Compare PySNES framebuffer against the Mesen reference PNG."""
    rom_path = PPU_ROMS / rom_rel
    ref_path = PPU_ROMS / ref_rel

    if not rom_path.exists():
        pytest.skip(f"ROM not found: {rom_path}")

    if request.config.getoption("--update-refs"):
        mesen = _mesen_bin(request.config)
        _generate_ref_png(mesen, rom_path, ref_path, n_frames)
        return

    if not ref_path.exists():
        pytest.skip(f"Reference PNG not found: {ref_path}")

    ref_pixels, ref_w, ref_h = _read_png_pixels(ref_path)
    if ref_w != SCREEN_W or ref_h != SCREEN_H:
        pytest.skip(f"Reference is {ref_w}×{ref_h}, expected {SCREEN_W}×{SCREEN_H}")

    got_pixels = _run_pysnes(rom_path, n_frames)

    assert len(ref_pixels) == len(got_pixels) == SCREEN_W * SCREEN_H

    mismatches = [
        (i, ref_pixels[i], got_pixels[i])
        for i in range(len(ref_pixels))
        if ref_pixels[i] != got_pixels[i]
    ]

    if mismatches:
        out_path = ACTUALS_DIR / f"{test_id}_actual.png"
        _write_png(out_path, got_pixels, SCREEN_W, SCREEN_H)
        pct = 100 * len(mismatches) / len(ref_pixels)
        first = mismatches[:5]
        pytest.fail(
            f"{len(mismatches)} pixels differ ({pct:.1f}%) for '{test_id}'.\n"
            f"First mismatches (pixel_idx, expected_rgb, got_rgb): {first}\n"
            f"Actual output saved to: {out_path}"
        )
