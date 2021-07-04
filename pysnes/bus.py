from .rom import Rom


class Bus:
    def __init__(self, rom: Rom) -> None:
        self.rom = rom
        self.cpu_registers = [0] * (0x44FF - 0x4200)

    def __getitem__(self, addr: int) -> int:
        if 0x8000 <= addr <= 0xFFFF:
            # LoROM section (program memory)
            return self.rom[addr - 0x8000]
        elif 0x4200 <= addr <= 0x44FF:
            # 0x4200 DMA, PPU2, hardware registers
            return self.cpu_registers[addr - 0x4200]

        raise RuntimeError(
            "Error accessing unmamped memory region: 0x{:06X}".format(addr)
        )

    def __setitem__(self, addr: int, data: int) -> None:
        """self.rom[addr + offset] = value"""
