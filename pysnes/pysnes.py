import argparse
from ctypes import byref

import sdl2 as sdl
import imgui
from imgui.integrations.sdl2 import SDL2Renderer
import OpenGL.GL as gl
import numpy as np
from rich import print

from .rom import Rom
from .bus import Bus
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller
from .video import Video
from .trace_matcher import check_trace_line


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
        self.frames = 0

        # Initialize video and create window
        self.video.initialize()

        self.event = sdl.SDL_Event()

        # Reset PC to the address in the cartridge reset vector
        self.cpu.PC.w = rom.hardware_vectors["emulation"]["RESET"]

        self.paused = False

    def draw_gui(self) -> None:
        # possible way to render game to imgui window
        # https://www.codingwiththomas.com/blog/rendering-an-opengl-framebuffer-into-a-dear-imgui-window
        imgui.new_frame()

        is_expand, show_custom_window = imgui.begin("Current instruction", True)
        if is_expand:
            debug_str = self.cpu.disassembler.disassemble(self.cpu.PC.w)
            debug_str += f" V:{self.ppu.v_counter:03} H:{self.ppu.h_counter:03} F:{self.ppu.frames}"
            # if not self.paused:
            #     print(f"[green]{debug_str}[/green]")  # trace log
            imgui.text_colored(debug_str, 0, 255, 0)
        imgui.end()
        is_expand, show_custom_window = imgui.begin("CPU Registers", True)
        if is_expand:
            imgui.text(f"Frames: {self.frames}")
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

    def tick(self):
        """Process one frame"""
        # Capture inputs from keyboard using SDL
        while sdl.SDL_PollEvent(byref(self.event)) != 0:
            if self.event.type == sdl.SDL_QUIT:
                return False
            elif self.event.type == sdl.SDL_KEYUP:
                controller = self.controllers[0]
                controller.pressed_keys.remove(self.event.key.keysym.sym)
            elif self.event.type == sdl.SDL_KEYDOWN:
                controller = self.controllers[0]
                controller.pressed_keys.add(self.event.key.keysym.sym)

            self.video.impl.process_event(self.event)

        self.video.impl.process_inputs()

        self.draw_gui()

        # To determine the exact length of any CPU instruction,
        # you must examine its behavior for each cycle,
        # and count 6, 8, or 12 master cycles as appropriate.
        if not self.paused:
            master_cycles = self.cpu.tick()

        # Tick PPU with the number of master cycles used by the CPU
        # as it runs on the same clock source

        # Clear the screen
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        # TEST DRAWING
        self.video.test_draw()

        self.ppu.tick(master_cycles)

        # self.apu.tick(master_cycles)

        # Draw the vertices
        self.video.draw_vertices(self.ppu.vertices)

        # TODO clear when all vertices are drawn
        #if len(self.ppu.vertices) > 100:
        #    self.ppu.vertices = np.array([], dtype=np.float32)

        self.video.update_screen() # Swap buffers

        # TODO Sleep to limit frequency on 60Hz
        # SDL_Delay(5)

        self.frames += 1

        return True  # keep running


def main():
    rom = "roms/test_oam.smc"
    # rom = "roms/snes_oam_test/1-random.smc"
    # rom = "roms/snes_oam_test/2-low.smc"
    # rom = "roms/snes_oam_test/3-high.smc"
    # rom = "roms/snes_adc_sbc/test_adc.smc"
    rom = "roms/SNES Test Program .smc"  # Lots of ppu tests
    rom = "roms/SNES Test Program.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/test_oam/test_oam.smc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/snes_adc_sbc/test_adc.smc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/test_hdma/test_hdmasync.smc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/test_dmatiming/demo.smc"

    rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ADC/CPUADC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/AND/CPUAND.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ASL/CPUASL.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/BIT/CPUBIT.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/BRA/CPUBRA.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/CMP/CPUCMP.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/DEC/CPUDEC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/EOR/CPUEOR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/INC/CPUINC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/JMP/CPUJMP.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/LDR/CPULDR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/LSR/CPULSR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/MOV/CPUMOV.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/MSC/CPUMSC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ORA/CPUORA.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/PHL/CPUPHL.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/PSR/CPUPSR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/RET/CPURET.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ROL/CPUROL.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ROR/CPUROR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/SBC/CPUSBC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/STR/CPUSTR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/TRN/CPUTRN.sfc"

    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/ADC/SPC700ADC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/AND/SPC700AND.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/DEC/SPC700DEC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/EOR/SPC700EOR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/INC/SPC700INC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/ORA/SPC700ORA.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/SBC/SPC700SBC.sfc"

    # rom = "roms/Super Mario World (U) [!].smc"
    # rom = "roms/Donkey Kong Country (U) (V1.2) [!].smc"
    # rom = "roms/Legend of Zelda, The - A Link to the Past (USA).sfc"
    # rom = "roms/Super Bomberman 5 Gold Cartridge (J) [!].smc"
    # rom = "roms/Final Fight (USA).sfc"
    # rom = "roms/SimCity (USA).sfc"
    # rom = "roms/Magical Quest Starring Mickey Mouse, The (USA).sfc"

    pysnes = PySNES(rom)

    # add trace crosscheck
    # trace_file = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ADC/CPUADC-trace.log"
    # with open(trace_file, "r") as f:
    #     while line := f.readline():
    #         check_trace_line(line, pysnes.cpu)
    #         pysnes.tick()

    while pysnes.tick():
        pass

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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Python SNES emulator.")
    parser.add_argument('-p', '--profile', action='store_true', help='Enable profiler mode')
    parser.add_argument('-l', '--load', action='store_true', help='Load memory dumps from bsnes to test rendering')
    args = parser.parse_args()

    if args.profile:
        import cProfile
        # from line_profiler import LineProfiler

        # lp = LineProfiler()
        # lp_wrapper = lp(main)
        # lp_wrapper()
        # lp.print_stats()

        cProfile.run("main()", sort="cumulative")
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

        pysnes.ppu.render(pysnes.renderer)
        SDL_Delay(5000)
    else:
        main()
