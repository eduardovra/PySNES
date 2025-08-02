#!/usr/bin/env python3
"""
PySNES emulator entry point.
Run this from the root directory: python run_pysnes.py
"""

import argparse
import sys
import os

# Add the project root to Python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pysnes.pysnes import main, PySNES
import sdl2 as sdl


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Python SNES emulator.")
    parser.add_argument('-p', '--profile', action='store_true', help='Enable profiler mode')
    parser.add_argument('-l', '--load', action='store_true', help='Load memory dumps from bsnes to test rendering')
    args = parser.parse_args()

    if args.profile:
        # import cProfile
        # from line_profiler import LineProfiler

        # lp = LineProfiler()
        # lp_wrapper = lp(main)
        # lp_wrapper()
        # lp.print_stats()

        # cProfile.run("main()", sort="cumulative")
        pass
    elif args.load:
        rom = "roms/Super Mario World (U) [!].smc"
        #rom = "roms/test_oam.smc"

        pysnes = PySNES(rom)

        rom_file_name, rom_extension = rom.split(".")

        with open(f"{rom_file_name}-vram.bin", "rb") as f:
            vram_dump = f.read()
            for i, b in enumerate(vram_dump):
                pysnes.ppu.vram[i] = b
        with open(f"{rom_file_name}-cgram.bin", "rb") as f:
            cgram_dump = f.read()
            for i, b in enumerate(cgram_dump):
                pysnes.ppu.cgram[i] = b
        with open(f"{rom_file_name}-oam.bin", "rb") as f:
            oam_dump = f.read()
            for i, b in enumerate(oam_dump):
                pysnes.ppu.oam.oam[i] = b

        # TODO load -apuram.bin -sram.bin -wram.bin
        # apuram is SPC700
        # sram is static ram, for save games. located in the cartridge

        with open(f"{rom_file_name}-wram.bin", "rb") as f:
            wram_dump = f.read()
            for i, b in enumerate(wram_dump):
                try:
                    pysnes.cpu.bus[i] = b
                except Exception as e:
                    # writing to some addresses will trigger operations
                    # that might fail but I don't care
                    print(e)

        pysnes.ppu.render()
        sdl.SDL_Delay(5000)
    else:
        main()
