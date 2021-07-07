from .rom import Rom
from .bus import Bus
from .cpu import Cpu
from .apu import Apu


class PySNES:
    def __init__(self, rom_file_path: str) -> None:
        rom = Rom(rom_file_path)
        self.apu = Apu()
        bus = Bus(rom, self.apu)
        self.cpu = Cpu(bus, rom.hardware_vectors)

    def tick(self):
        """
        Process one frame
        """
        cycles = self.cpu.tick()
        self.apu.tick()

        # TODO tick the same number of cycles on the other components (PPU, Timer, etc)
        # TODO Sleep to keep limit frequency on 60Hz

        return False


if __name__ == "__main__":
    rom = "snes_oam_test/1-random.smc"
    rom = "snes_oam_test/2-low.smc"
    rom = "Super Mario World (U) [!].smc"
    pysnes = PySNES(rom)
    while not pysnes.tick():
        pass
