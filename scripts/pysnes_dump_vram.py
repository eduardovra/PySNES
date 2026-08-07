#!/usr/bin/env python3
"""Run PySNES headless for N frames, then dump VRAM + selected PPU regs.

Usage:
    python3 scripts/pysnes_dump_vram.py <rom> [--frames N] [--out BASE]

Writes:
    <BASE>.vram   64KB of VRAM as-is
    <BASE>.json   selected PPU state (bg scroll, tilemap bases, screen enable)
"""

import argparse
import json
import os
import sys
from pathlib import Path

MC_PER_FRAME = 262 * 1364

os.environ.setdefault("PYSNES_HEADLESS", "1")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--frames", type=int, default=560)
    ap.add_argument("--out", default="/tmp/mesen_layers/pysnes_state")
    ap.add_argument(
        "--force-tmw",
        type=lambda s: int(s, 0),
        default=None,
        help="Force TMW to this value before last frame's render (diagnostic)",
    )
    args = ap.parse_args()

    from pysnes.pysnes import PySNES

    pysnes = PySNES(args.rom, settings={"headless": True})
    pysnes.cpu.start(pysnes.scheduler)
    pysnes.ppu.start()

    for i in range(args.frames):
        if args.force_tmw is not None and i == args.frames - 1:
            pysnes.ppu.tmw = args.force_tmw
        frame_end = pysnes.scheduler.master_clock + MC_PER_FRAME
        pysnes.scheduler.run_to(frame_end)

    ppu = pysnes.ppu
    state = {
        "bgmode": getattr(ppu, "bgmode", None),
        "tm": ppu.bg1.main_screen_enable * 1
        | ppu.bg2.main_screen_enable * 2
        | ppu.bg3.main_screen_enable * 4
        | ppu.bg4.main_screen_enable * 8,
        "ts": ppu.bg1.sub_screen_enable * 1
        | ppu.bg2.sub_screen_enable * 2
        | ppu.bg3.sub_screen_enable * 4
        | ppu.bg4.sub_screen_enable * 8,
        "tmw": ppu.tmw,
        "tsw": ppu.tsw,
        "w12sel": ppu.w12sel,
        "w34sel": ppu.w34sel,
        "wobjsel": ppu.wobjsel,
        "wh0": ppu.wh0,
        "wh1": ppu.wh1,
        "wh2": ppu.wh2,
        "wh3": ppu.wh3,
        "cgwsel": ppu.cgwsel,
        "cgadsub": ppu.cgadsub,
        "coldata_r": ppu.coldata_r,
        "coldata_g": ppu.coldata_g,
        "coldata_b": ppu.coldata_b,
        "bg1": dict(
            screen_addr=ppu.bg1.screen_addr,
            tiledata_addr=ppu.bg1.tiledata_addr,
            hoffset=ppu.bg1.hoffset,
            voffset=ppu.bg1.voffset,
            screen_size=getattr(ppu.bg1, "screen_size", None),
            main=ppu.bg1.main_screen_enable,
            sub=ppu.bg1.sub_screen_enable,
        ),
        "bg2": dict(
            screen_addr=ppu.bg2.screen_addr,
            tiledata_addr=ppu.bg2.tiledata_addr,
            hoffset=ppu.bg2.hoffset,
            voffset=ppu.bg2.voffset,
            screen_size=getattr(ppu.bg2, "screen_size", None),
            main=ppu.bg2.main_screen_enable,
            sub=ppu.bg2.sub_screen_enable,
        ),
        "bg3": dict(
            screen_addr=ppu.bg3.screen_addr,
            tiledata_addr=ppu.bg3.tiledata_addr,
            hoffset=ppu.bg3.hoffset,
            voffset=ppu.bg3.voffset,
            screen_size=getattr(ppu.bg3, "screen_size", None),
            main=ppu.bg3.main_screen_enable,
            sub=ppu.bg3.sub_screen_enable,
        ),
        "bg4": dict(
            screen_addr=ppu.bg4.screen_addr,
            tiledata_addr=ppu.bg4.tiledata_addr,
            hoffset=ppu.bg4.hoffset,
            voffset=ppu.bg4.voffset,
            screen_size=getattr(ppu.bg4, "screen_size", None),
            main=ppu.bg4.main_screen_enable,
            sub=ppu.bg4.sub_screen_enable,
        ),
    }

    base = Path(args.out)
    base.parent.mkdir(parents=True, exist_ok=True)
    with open(f"{base}.vram", "wb") as f:
        f.write(bytes(ppu.vram))
    with open(f"{base}.cgram", "wb") as f:
        f.write(bytes(ppu.cgram))
    with open(f"{base}.json", "w") as f:
        json.dump(state, f, indent=2)

    # Dump the composite framebuffer: 256 x 224 u32 RGBA (big-endian component
    # order inside u32 as written by PPU: (r<<24)|(g<<16)|(b<<8)|a).
    # Write as little-endian u32 so a consumer can `np.frombuffer(..., '<u4')`.
    import struct

    SCREEN_W, SCREEN_H = 256, 224
    with open(f"{base}.bin", "wb") as f:
        for i in range(SCREEN_W * SCREEN_H):
            v = ppu.main_bgs[i]
            f.write(struct.pack("<I", v & 0xFFFFFFFF))

    print(
        f"dumped {base}.vram ({len(ppu.vram)}B), .cgram, .json, .bin",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
