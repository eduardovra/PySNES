from .rom import Rom
from .bus import Bus
from .cpu import Cpu


class PySNES:
    def __init__(self, rom_file_path: str) -> None:
        rom = Rom(rom_file_path)
        bus = Bus(rom)
        self.cpu = Cpu(bus)

    def tick(self):
        """
        Process one frame
        """
        cycles = self.cpu.tick()

        # TODO tick the same number of cycles on the other components (PPU, Timer, etc)
        # TODO Sleep to keep limit frequency on 60Hz

        return False


if __name__ == "__main__":
    pysnes = PySNES("Super Mario World (U) [!].smc")
    while not pysnes.tick():
        pass
