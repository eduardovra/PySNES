from ctypes import byref

from sdl2 import *

from .rom import Rom
from .bus import Bus
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller


class PySNES:
    def __init__(self, rom_file_path: str) -> None:
        rom = Rom(rom_file_path)
        self.apu = Apu()
        self.cpu = Cpu(rom.hardware_vectors)
        self.ppu = Ppu(self.cpu)  # Pass CPU reference so PPU can control the NMI line
        self.controllers = [Controller(), Controller()]
        bus = Bus(rom, self.cpu, self.apu, self.ppu, self.controllers)
        self.cpu.attach(bus)
        self.ticks = 0
        self.setup_sdl()

    def setup_sdl(self) -> None:
        SDL_Init(SDL_INIT_VIDEO)
        self.window = SDL_CreateWindow(b"PySNES", 0, 0, 768, 768, SDL_WINDOW_SHOWN)
        self.renderer = SDL_CreateRenderer(self.window, -1, SDL_RENDERER_ACCELERATED)
        SDL_SetRenderDrawBlendMode(self.renderer, SDL_BLENDMODE_BLEND)
        SDL_RenderSetScale(self.renderer, 2, 2)
        self.event = SDL_Event()

    def teardown_sdl(self) -> None:
        SDL_DestroyRenderer(self.renderer)
        SDL_DestroyWindow(self.window)
        SDL_Quit()

    def tick(self):
        """
        Process one frame
        """
        # if self.cpu.PC == 0x0181EB:
        # if self.ticks == 150000:
        #    print("++++ BREAK ++++")
        #    self.ppu.render()  # Render frame
        #    return True

        # Capture inputs from keyboard using SDL
        while SDL_PollEvent(byref(self.event)) != 0:
            if self.event.type == SDL_QUIT:
                self.teardown_sdl()
                return True
            elif self.event.type == SDL_KEYUP:
                controller = self.controllers[0]
                controller.pressed_keys.remove(self.event.key.keysym.sym)
            elif self.event.type == SDL_KEYDOWN:
                controller = self.controllers[0]
                controller.pressed_keys.add(self.event.key.keysym.sym)

        # To determine the exact length of any CPU instruction,
        # you must examine its behavior for each cycle,
        # and count 6, 8, or 12 master cycles as appropriate.
        master_cycles = self.cpu.tick()
        master_cycles = 8 * 5  # TODO discard CPU value for now

        # Tick PPU with the number of master cycles used by the CPU
        # as it runs on the same clock source
        self.ppu.tick(master_cycles, self.renderer)

        # TODO figure out
        self.apu.tick()

        # TODO Sleep to limit frequency on 60Hz

        self.ticks += 1

        return False


def main():
    rom = "roms/test_oam.smc"
    # rom = "roms/snes_oam_test/1-random.smc"
    # rom = "roms/snes_oam_test/2-low.smc"
    # rom = "roms/snes_oam_test/3-high.smc"
    # rom = "roms/snes_adc_sbc/test_adc.smc"
    # rom = "roms/SNES Test Program .smc" # Lots of ppu tests
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/test_oam/test_oam.smc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/snes_adc_sbc/test_adc.smc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/test_hdma/test_hdmasync.smc"
    rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ADC/CPUADC.sfc"
    rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/AND/CPUAND.sfc"
    rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ASL/CPUASL.sfc"
    rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/BIT/CPUBIT.sfc"
    # rom = "roms/Super Mario World (U) [!].smc"
    pysnes = PySNES(rom)
    while not pysnes.tick():
        pass


if __name__ == "__main__":
    import cProfile

    # cProfile.run("main()", sort="cumulative")
    main()
