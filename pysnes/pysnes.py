from .rom import Rom
from .bus import Bus
from .cpu import Cpu
from .apu import Apu


class PySNES:
    def __init__(self, rom_file_path: str) -> None:
        rom = Rom(rom_file_path)
        self.apu = Apu()
        bus = Bus(rom, self.apu)
        self.cpu = Cpu(bus)

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
    pysnes = PySNES("Super Mario World (U) [!].smc")
    while not pysnes.tick():
        pass
