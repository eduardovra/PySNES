from .rom import Rom
from .bus import Bus
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu


class PySNES:
    def __init__(self, rom_file_path: str) -> None:
        rom = Rom(rom_file_path)
        self.apu = Apu()
        self.cpu = Cpu(rom.hardware_vectors)
        self.ppu = Ppu()
        bus = Bus(rom, self.cpu, self.apu, self.ppu)
        self.cpu.attach(bus)
        self.ticks = 0

    def tick(self):
        """
        Process one frame
        """
        if self.cpu.PC == 0xE4A9:
            print("++++ BREAK ++++")
            self.ppu.render()  # Render frame
            return True

        cycles = self.cpu.tick()
        self.apu.tick()

        # TODO tick the same number of cycles on the other components (PPU, Timer, etc)
        # TODO Sleep to keep limit frequency on 60Hz

        # self.ticks += 1
        # return self.ticks > 10000000
        return False


def main():
    rom = "snes_oam_test/1-random.smc"
    # rom = "snes_oam_test/2-low.smc"
    # rom = "snes_adc_sbc/test_adc.smc"
    # rom = "Super Mario World (U) [!].smc"
    pysnes = PySNES(rom)
    while not pysnes.tick():
        pass


if __name__ == "__main__":
    import cProfile

    # cProfile.run("main()", sort="cumulative")
    main()
