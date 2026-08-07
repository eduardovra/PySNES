#!/usr/bin/env python3
"""
Run Mesen multiple times with scripts/mesen_layers.lua, each time forcing
a different TM/TS mask to isolate a single BG/OBJ layer on the main or
sub screen, then convert each .bin to a .png for visual inspection.

Usage:
    python3 scripts/dump_mesen_layers.py <rom> [--frame N] [--out-dir DIR]

Default: frame 560, output to /tmp/mesen_layers/.

Output files per config:
    mesen_layer_all.png        baseline — no override
    mesen_layer_bg1.png        TM = BG1 only
    mesen_layer_bg2.png        TM = BG2 only
    mesen_layer_bg3.png        TM = BG3 only
    mesen_layer_bg4.png        TM = BG4 only
    mesen_layer_obj.png        TM = OBJ only
    mesen_layer_sub_bg2.png    TM=0, TS=BG2 only
"""

import argparse
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCREEN_W = 256
MESEN_BUF_H = 239
MESEN_ROW_OFFSET = 7
VISIBLE_H = 224
EXPECTED_SIZE = SCREEN_W * MESEN_BUF_H * 4

# name, tm_mask (or None = no override), ts_mask (or None)
CONFIGS = [
    ("all", None, None),
    ("bg1", 0x01, 0x00),
    ("bg2", 0x02, 0x00),
    ("bg3", 0x04, 0x00),
    ("bg4", 0x08, 0x00),
    ("obj", 0x10, 0x00),
    ("sub_bg2", 0x00, 0x02),
]


def mesen_bin() -> str:
    candidates = [
        os.environ.get("MESEN_BIN"),
        str(
            REPO_ROOT
            / "submodules/Mesen2/bin/linux-x64/Release/linux-x64/publish/Mesen"
        ),
    ]
    cfg_path = REPO_ROOT / "settings.json"
    if cfg_path.exists():
        try:
            candidates.insert(
                1, json.loads(cfg_path.read_text()).get("mesen_bin")
            )
        except Exception:
            pass
    for c in candidates:
        if c and Path(c).is_file() and os.access(c, os.X_OK):
            return c
    raise FileNotFoundError(
        "Mesen binary not found. Build the submodule or set MESEN_BIN."
    )


def run_mesen(
    mesen: str, rom: Path, out_bin: Path, frame: int, tm_mask, ts_mask
) -> None:
    lua_script = REPO_ROOT / "scripts/mesen_layers.lua"
    env = os.environ.copy()
    env["MESEN_FRAMES"] = str(frame)
    env["MESEN_OUTPUT_BIN"] = str(out_bin)
    if tm_mask is not None:
        env["MESEN_TM_MASK"] = str(tm_mask)
    if ts_mask is not None:
        env["MESEN_TS_MASK"] = str(ts_mask)
    proc = subprocess.run(
        [mesen, "--testrunner", str(rom), str(lua_script)],
        env=env,
        capture_output=True,
        timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Mesen exited {proc.returncode}\n"
            f"stdout: {proc.stdout.decode(errors='replace')[-500:]}\n"
            f"stderr: {proc.stderr.decode(errors='replace')[-500:]}"
        )
    if not out_bin.is_file() or out_bin.stat().st_size < EXPECTED_SIZE:
        raise RuntimeError(
            f"Expected {EXPECTED_SIZE} bytes at {out_bin}, "
            f"got {out_bin.stat().st_size if out_bin.is_file() else 'missing'}"
        )


def bin_to_png(bin_path: Path, png_path: Path) -> None:
    from PIL import Image

    raw = bin_path.read_bytes()
    pixels_u32 = struct.unpack(
        f"<{SCREEN_W * MESEN_BUF_H}I", raw[:EXPECTED_SIZE]
    )
    img = Image.new("RGB", (SCREEN_W, VISIBLE_H))
    out = img.load()
    for row in range(VISIBLE_H):
        for col in range(SCREEN_W):
            v = pixels_u32[(MESEN_ROW_OFFSET + row) * SCREEN_W + col]
            out[col, row] = ((v >> 16) & 0xFF, (v >> 8) & 0xFF, v & 0xFF)
    img.save(png_path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--frame", type=int, default=560)
    ap.add_argument("--out-dir", default="/tmp/mesen_layers")
    args = ap.parse_args()

    rom_path = Path(args.rom).resolve()
    if not rom_path.is_file():
        print(f"ROM not found: {rom_path}", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    mesen = mesen_bin()

    for name, tm, ts in CONFIGS:
        out_bin = out_dir / f"mesen_layer_{name}.bin"
        out_png = out_dir / f"mesen_layer_{name}.png"
        print(f"capturing {name:<8} tm={tm} ts={ts} ...", flush=True)
        run_mesen(mesen, rom_path, out_bin, args.frame, tm, ts)
        bin_to_png(out_bin, out_png)
        print(f"  → {out_png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
