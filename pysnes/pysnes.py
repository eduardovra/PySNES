import argparse
from ctypes import byref
import time
from enum import IntEnum
import sys
import platform

import sdl2 as sdl
import imgui
import cython
from rich import print

from .rom import Rom
from .bus import Bus
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller
from .video import Video
from .trace_matcher import check_trace_line

if cython.compiled:
    print("[green]Cython is enabled, using compiled modules.[/green]")
else:
    print("[blue]Cython is not enabled, using pure Python modules.[/blue]")


class States(IntEnum):
    RESET = 0
    RUNNING_SCANLINES = 1
    RENDER_GAME_SCREEN = 2


class PySNES:
    def __init__(self, rom_file_path: str) -> None:
        rom = Rom(rom_file_path)
        self.apu = Apu()
        self.cpu = Cpu(rom.hardware_vectors)
        self.ppu = Ppu(self.cpu)  # Pass CPU reference so PPU can control the NMI line
        self.controllers = [Controller(), Controller(disabled=True)]
        bus = Bus(rom, self.cpu, self.apu, self.ppu, self.controllers)
        self.cpu.attach(bus)
        self.video = Video()

        # Initialize video and create window
        self.video.initialize()
        self.video.set_window_title(f"PySNES - {rom.rom_file_name}")

        # Used to pool inputs
        self.event = sdl.SDL_Event()

        # Reset PC to the address in the cartridge reset vector
        self.cpu.PC.w = rom.hardware_vectors["emulation"]["RESET"]

        # Emulator state variables
        self.running = True
        self.paused = False
        self.state = States.RESET
        self.loop_time = 0.0
        self.loop_fps = 0.0
        self.frame_time = 0.0
        self.frame_fps = 0.0

    def create_gui(self) -> None:
        # possible way to render game to imgui window
        # https://www.codingwiththomas.com/blog/rendering-an-opengl-framebuffer-into-a-dear-imgui-window
        imgui.new_frame()

        # is_open is set when the window is expanded, is_visible is set when the x button is clicked
        is_open, is_visible = imgui.begin("Trace log", True)
        if is_open:
            # debug_str = self.cpu.disassembler.disassemble(self.cpu.PC.w)
            # debug_str += f" V:{self.ppu.v_counter:03} H:{self.ppu.h_counter:03} F:{self.ppu.frames}"
            # if not self.paused:
            #     print(f"[green]{debug_str}[/green]")  # trace log
            for log in self.cpu.trace_log:
                imgui.text_colored(log, 0, 255, 0)
        imgui.end()

        is_open, is_visible = imgui.begin("CPU Registers", True)
        if is_open:
            imgui.text(f"Loop time: {self.loop_time:.4f}")
            imgui.text(f"Loops per sec: {self.loop_fps:.4f}")
            imgui.text(f"Frame time: {self.frame_time:.4f}")
            imgui.text(f"Frames per sec: {self.frame_fps:.4f}")
            imgui.text(f"PC: 0x{self.cpu.PC.value:06X}")
            imgui.text(f"A: 0x{self.cpu.A.value:04X}")
            imgui.text(f"X: 0x{self.cpu.X.value:04X}")
            imgui.text(f"Y: 0x{self.cpu.Y.value:04X}")
            imgui.text(f"SP: 0x{self.cpu.S.value:04X}")
            imgui.text(f"DB: 0x{self.cpu.DB.value:02X}")
            imgui.text(f"P: 0x{self.cpu.P:02X}")
            if imgui.button("Continue" if self.paused else "Pause"):
                self.paused = not self.paused
        imgui.end()

        # add textures images
        is_open, is_visible = imgui.begin("PPU", True)
        if is_open:
            scale = 4
            imgui.image(self.video.texture, 256 * scale, 239 * scale)
        imgui.end()

    def main(self):
        """Main loop"""
        # Main state machine
        while self.running:
            loop_start = time.time()

            if self.state == States.RESET:
                frame_start = time.time()
                self.scanline = 0
                self.ppu.vertices.clear()
                self.state = States.RUNNING_SCANLINES

            elif self.state == States.RUNNING_SCANLINES and not self.paused:
                # Run one scanline on the CPU, PPU and APU
                self.run_scanline()
                self.scanline += 1

                """
                Visible scanlines (NTSC): 224 (or 239 in high-res mode).
                Total scanlines (NTSC): 262.
                Total scanlines (PAL): 312.
                """
                if self.scanline == 262:
                    self.state = States.RENDER_GAME_SCREEN

            elif self.state == States.RENDER_GAME_SCREEN and not self.paused:
                # Draw the vertices
                # vertices = np.array(self.ppu.vertices, dtype=np.float32)
                # self.video.draw_vertices(vertices, 0, self.video.WINDOW_WIDTH - 224, 256, 224)

                # Draw textures
                self.video.draw_textures(self.ppu.main_bgs)

                # Calculate frame time
                self.frame_time = time.time() - frame_start
                self.frame_fps = 1 / self.frame_time

                self.state = States.RESET

            # Pool inputs
            self.process_inputs()

            # Create ImGUI components
            self.create_gui()

            # Swap buffers
            self.video.update_screen()

            # Calculate loop time
            self.loop_time = time.time() - loop_start
            self.loop_fps = 1 / self.loop_time

        # Broken out of main loop
        self.video.teardown_sdl()

    def run_scanline(self):
        """Run a scanline"""
        clocks = self.cpu.run_scanline()
        self.ppu.tick(clocks)
        self.apu.tick(clocks)

    def process_inputs(self):
        # Capture inputs from keyboard using SDL
        while sdl.SDL_PollEvent(byref(self.event)) != 0:
            if self.event.type == sdl.SDL_QUIT:
                self.running = False
                return
            elif self.event.type == sdl.SDL_KEYUP:
                controller = self.controllers[0]
                controller.pressed_keys.remove(self.event.key.keysym.sym)
            elif self.event.type == sdl.SDL_KEYDOWN:
                controller = self.controllers[0]
                controller.pressed_keys.add(self.event.key.keysym.sym)

            self.video.impl.process_event(self.event)

        self.video.impl.process_inputs()


def print_python_info():
    """Print information about the Python interpreter being used"""
    print(f"[blue]Python Information:[/blue]")
    print(f"  Version: {sys.version}")
    print(f"  Executable: {sys.executable}")
    print(f"  Implementation: {platform.python_implementation()}")
    print(f"  Compiler: {platform.python_compiler()}")
    print(f"  Build: {platform.python_build()}")
    print(f"  Platform: {platform.platform()}")
    print()


def main():
    # Print Python interpreter information
    print_python_info()

    rom = "roms/test_oam.smc"
    # rom = "roms/snes_oam_test/1-random.smc"
    # rom = "roms/snes_oam_test/2-low.smc"
    # rom = "roms/snes_oam_test/3-high.smc"
    # rom = "roms/snes_adc_sbc/test_adc.smc"
    rom = "roms/SNES Test Program .smc"  # Lots of ppu tests
    rom = "roms/SNES Test Program.sfc"
    # rom = "submodules/snes-test-roms/jonasquinn-test-roms/test_oam/test_oam.smc"
    # rom = "submodules/snes-test-roms/jonasquinn-test-roms/snes_adc_sbc/test_adc.smc"
    # rom = "submodules/snes-test-roms/jonasquinn-test-roms/test_hdma/test_hdmasync.smc"
    # rom = "submodules/snes-test-roms/jonasquinn-test-roms/test_dmatiming/demo.smc"

    rom = "submodules/SNES/CPUTest/CPU/ADC/CPUADC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/AND/CPUAND.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/ASL/CPUASL.sfc"
    rom = "submodules/SNES/CPUTest/CPU/BIT/CPUBIT.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/BRA/CPUBRA.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/CMP/CPUCMP.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/DEC/CPUDEC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/EOR/CPUEOR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/INC/CPUINC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/JMP/CPUJMP.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/LDR/CPULDR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/LSR/CPULSR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/MOV/CPUMOV.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/MSC/CPUMSC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/ORA/CPUORA.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/PHL/CPUPHL.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/PSR/CPUPSR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/RET/CPURET.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/ROL/CPUROL.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/ROR/CPUROR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/SBC/CPUSBC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/STR/CPUSTR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/TRN/CPUTRN.sfc"

    # rom = "submodules/SNES/CPUTest/SPC700/ADC/SPC700ADC.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/AND/SPC700AND.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/DEC/SPC700DEC.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/EOR/SPC700EOR.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/INC/SPC700INC.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/ORA/SPC700ORA.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/SBC/SPC700SBC.sfc"

    # PeterLemon PPU tests
    # rom = "submodules/SNES/PPU/BGMAP/8x8/2BPP/8x8BG1Map2BPP32x328PAL/8x8BG1Map2BPP32x328PAL.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/2BPP/8x8BG2Map2BPP32x328PAL/8x8BG2Map2BPP32x328PAL.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/2BPP/8x8BG3Map2BPP32x328PAL/8x8BG3Map2BPP32x328PAL.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/2BPP/8x8BG4Map2BPP32x328PAL/8x8BG4Map2BPP32x328PAL.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/4BPP/8x8BGMap4BPP32x328PAL/8x8BGMap4BPP32x328PAL.sfc"
    rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/32x32/8x8BGMap8BPP32x32.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/32x64/8x8BGMap8BPP32x64.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/64x32/8x8BGMap8BPP64x32.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/64x64/8x8BGMap8BPP64x64.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/TileFlip/8x8BGMapTileFlip.sfc"
    rom = "submodules/SNES/PPU/Mosaic/Mode3/MosaicMode3.sfc"

    # rom = "roms/Super Mario World (U) [!].smc"
    # rom = "roms/Donkey Kong Country (U) (V1.2) [!].smc"
    # rom = "roms/Legend of Zelda, The - A Link to the Past (USA).sfc"
    # rom = "roms/Super Bomberman 5 Gold Cartridge (J) [!].smc"
    # rom = "roms/Final Fight (USA).sfc"
    # rom = "roms/SimCity (USA).sfc"
    # rom = "roms/Magical Quest Starring Mickey Mouse, The (USA).sfc"

    pysnes = PySNES(rom)

    # add trace crosscheck
    # trace_file = "submodules/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ADC/CPUADC-trace.log"
    # with open(trace_file, "r") as f:
    #     while line := f.readline():
    #         check_trace_line(line, pysnes.cpu)
    #         pysnes.tick()

    # while pysnes.tick():
    #     pass

    pysnes.main()

    pysnes.video.teardown_sdl()

    return

    trace = "roms/Super Mario World (U) [!]-trace.log"
    with open(trace, "r") as f:
        line_number = 0
        error_count_apu = 0
        error_count_cpu = 0

        while True:
            line_number += 1
            line = f.readline()
            print(line.rstrip())

            if line[0] == ".":
                pysnes.apu.fetch_and_execute(trace_line=line)
            else:
                pysnes.cpu.fetch_and_execute(trace_line=line)
