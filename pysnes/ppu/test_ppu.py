"""
PPU screenshot regression tests.

Each test loads a pre-built ROM from submodules/SNES/PPU/ (PeterLemon collection),
runs PySNES headlessly for N frames, and compares the 256×224 framebuffer against
a Mesen-generated reference PNG stored in tests/ppu_references/.

Reference images are generated once via `pytest --update-refs` and committed.
On normal runs the references must already exist; the test fails if they don't.

Marks: @pytest.mark.ppu  — excluded from the default suite with -m "not ppu"
"""

import os
import struct
import zlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.ppu

REPO_ROOT    = Path(__file__).parent.parent.parent
PPU_ROMS     = REPO_ROOT / "submodules" / "SNES" / "PPU"
REFS_DIR     = REPO_ROOT / "tests" / "ppu_references"
MC_PER_FRAME = 262 * 1364
SCREEN_W     = 256
SCREEN_H     = 224


# ---------------------------------------------------------------------------
# PNG helpers (no Pillow dependency)
# ---------------------------------------------------------------------------

def _read_png_pixels(path: Path) -> list:
    """Return a flat list of (R, G, B) tuples from a 256×224 RGB PNG."""
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
    return pixels


def _write_png(path: Path, pixels: list, width: int, height: int) -> None:
    """Write a flat list of (R, G, B) tuples as a 256×224 RGB PNG."""
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

def _run_pysnes(rom_path: Path, n_frames: int = 5) -> list:
    """Run PySNES headlessly for n_frames and return 256×224 list of (R,G,B) tuples."""
    from pysnes.pysnes import PySNES  # noqa: PLC0415

    pysnes = PySNES(str(rom_path), settings={"headless": True})
    pysnes.cpu.start(pysnes.scheduler)
    pysnes.ppu.start()

    for _ in range(n_frames):
        frame_end = pysnes.scheduler.master_clock + MC_PER_FRAME
        pysnes.scheduler.run_to(frame_end)

    # main_bgs is a flat list of u32 ARGB/XRGB values, 256×262
    # Only the first SCREEN_H rows are visible output
    pixels = []
    for y in range(SCREEN_H):
        for x in range(SCREEN_W):
            u32 = pysnes.ppu.main_bgs[y * SCREEN_W + x]
            r = (u32 >> 16) & 0xFF
            g = (u32 >>  8) & 0xFF
            b = (u32 >>  0) & 0xFF
            pixels.append((r, g, b))
    return pixels


# ---------------------------------------------------------------------------
# Mesen reference generation
# ---------------------------------------------------------------------------

def _run_mesen_screenshot(rom_path: Path, ref_path: Path, n_frames: int = 5) -> None:
    """Run Mesen headlessly and save a reference PNG for the given ROM."""
    import socket
    import subprocess
    import threading

    mesen_candidates = [
        os.environ.get("MESEN_BIN"),
        str(REPO_ROOT / "tools" / "Mesen"),
    ]
    mesen = next((p for p in mesen_candidates if p and Path(p).exists()), None)
    if mesen is None:
        pytest.skip("Mesen not found — set MESEN_BIN or place binary at tools/Mesen")

    lua_script = str(REPO_ROOT / "scripts" / "mesen_screenshot.lua")
    if not Path(lua_script).exists():
        pytest.skip(f"Lua script not found: {lua_script}")

    env = os.environ.copy()
    env.setdefault("DISPLAY", ":0")
    env["MESEN_FRAMES"]     = str(n_frames)
    env["MESEN_OUTPUT_PNG"] = str(ref_path)
    ref_path.parent.mkdir(parents=True, exist_ok=True)

    result = subprocess.run(
        [mesen, "--testrunner", str(rom_path), lua_script],
        capture_output=True, text=True, timeout=120, env=env,
    )
    if result.returncode != 0 or not ref_path.exists():
        pytest.fail(
            f"Mesen failed to generate reference for {rom_path.name}.\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------

# Each entry: (test_id, rom_path_relative_to_PPU_ROMS, n_frames)
PPU_TEST_ROMS = [
    ("bg1_2bpp",   "BGMAP/8x8/2BPP/8x8BG1Map2BPP32x328PAL/8x8BG1Map2BPP32x328PAL.sfc",  5),
    ("bg2_2bpp",   "BGMAP/8x8/2BPP/8x8BG2Map2BPP32x328PAL/8x8BG2Map2BPP32x328PAL.sfc",  5),
    ("bg3_2bpp",   "BGMAP/8x8/2BPP/8x8BG3Map2BPP32x328PAL/8x8BG3Map2BPP32x328PAL.sfc",  5),
    ("bg4_2bpp",   "BGMAP/8x8/2BPP/8x8BG4Map2BPP32x328PAL/8x8BG4Map2BPP32x328PAL.sfc",  5),
    ("bg_4bpp",    "BGMAP/8x8/4BPP/8x8BGMap4BPP32x328PAL/8x8BGMap4BPP32x328PAL.sfc",    5),
    ("bg_8bpp",    "BGMAP/8x8/8BPP/32x32/8x8BGMap8BPP32x32.sfc",                         5),
    ("tile_flip",  "BGMAP/8x8/8BPP/TileFlip/8x8BGMapTileFlip.sfc",                       5),
    ("mode7_rotzoom", "Mode7/RotZoom/RotZoom.sfc",                                       10),
    ("window_hdma",   "Window/WindowHDMA/WindowHDMA.sfc",                                 5),
    ("mosaic_mode3",  "Mosaic/Mode3/MosaicMode3.sfc",                                     5),
]


@pytest.mark.parametrize("test_id,rom_rel,n_frames", PPU_TEST_ROMS, ids=[t[0] for t in PPU_TEST_ROMS])
def test_ppu_screenshot(test_id, rom_rel, n_frames, request):
    """Compare PySNES framebuffer against Mesen reference PNG."""
    rom_path = PPU_ROMS / rom_rel
    if not rom_path.exists():
        pytest.skip(f"ROM not found: {rom_path}")

    ref_path = REFS_DIR / f"{test_id}.png"
    update_refs = request.config.getoption("--update-refs", default=False)

    if update_refs:
        _run_mesen_screenshot(rom_path, ref_path, n_frames)
        pytest.skip(f"Reference updated: {ref_path}")

    if not ref_path.exists():
        pytest.fail(
            f"No reference image for '{test_id}'.\n"
            f"Generate it with: pytest pysnes/ppu/test_ppu.py -k {test_id} --update-refs"
        )

    ref_pixels  = _read_png_pixels(ref_path)
    got_pixels  = _run_pysnes(rom_path, n_frames)

    assert len(ref_pixels) == len(got_pixels) == SCREEN_W * SCREEN_H

    mismatches = [
        (i, ref_pixels[i], got_pixels[i])
        for i in range(len(ref_pixels))
        if ref_pixels[i] != got_pixels[i]
    ]

    if mismatches:
        # Save actual output for inspection
        out_path = REFS_DIR / f"{test_id}_actual.png"
        _write_png(out_path, got_pixels, SCREEN_W, SCREEN_H)
        pct = 100 * len(mismatches) / len(ref_pixels)
        first = mismatches[:5]
        pytest.fail(
            f"{len(mismatches)} pixels differ ({pct:.1f}%) for '{test_id}'.\n"
            f"First mismatches (idx, expected, got): {first}\n"
            f"Actual output saved to: {out_path}"
        )
