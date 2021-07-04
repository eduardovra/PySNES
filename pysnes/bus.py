from .rom import Rom


class Bus:
    # TODO consider banks
    def __init__(self, rom: Rom) -> None:
        self.rom = rom  # LoROM section (program memory)
        self.low_ram = [0] * (0x7E1FFF - 0x7E0000)
        self.pp1_apu_hw_registers = [0] * (0x21FF - 0x2100)
        self.dma_ppu2_hw_registers = [0] * (0x44FF - 0x4200)
        self.extended_ram = [0] * (0x7FFFFF - 0x7E8000)

    def __getitem__(self, addr: int) -> int:
        if 0x0000 <= addr <= 0x1FFF:
            return self.low_ram[addr & 0xFFFF]  # LowRAM, shadowed from bank $7E
        elif 0x8000 <= addr <= 0xFFFF:
            return self.rom[addr - 0x8000]
        elif 0x2100 <= addr <= 0x21FF:
            return self.pp1_apu_hw_registers[addr - 0x2100]
        elif 0x4200 <= addr <= 0x44FF:
            return self.dma_ppu2_hw_registers[addr - 0x4200]
        elif 0x7E0000 <= addr <= 0x7E1FFF:
            return self.low_ram[addr & 0xFFFF]
        elif 0x7E8000 <= addr <= 0x7FFFFF:
            return self.extended_ram[addr - 0x7E8000]

        raise RuntimeError(
            "Error reading unmamped memory region: 0x{:06X}".format(addr)
        )

    def __setitem__(self, addr: int, data: int) -> None:
        assert 0x00 <= data <= 0xFF

        if 0x0000 <= addr <= 0x1FFF:
            self.low_ram[addr & 0xFFFF] = data & 0xFF
        elif 0x2100 <= addr <= 0x21FF:
            self.pp1_apu_hw_registers[addr - 0x2100] = data & 0xFF
        elif 0x4200 <= addr <= 0x44FF:
            self.dma_ppu2_hw_registers[addr - 0x4200] = data & 0xFF
        elif 0x7E0000 <= addr <= 0x7E1FFF:
            self.low_ram[addr & 0xFFFF] = data & 0xFF
        elif 0x7E8000 <= addr <= 0x7FFFFF:
            self.extended_ram[addr - 0x7E8000] = data & 0xFF
        else:
            raise RuntimeError(
                "Error writting unmamped memory region: 0x{:06X}".format(addr)
            )
