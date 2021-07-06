from .apu import Apu
from .rom import Rom


class Bus:
    # TODO consider banks
    def __init__(self, rom: Rom, apu: Apu) -> None:
        self.rom = rom  # LoROM section (program memory)
        self.apu = apu  # Sound system [0x2140-0x217F]
        self.low_ram = [0] * (0x7E1FFF - 0x7E0000)
        self.pp1_apu_hw_registers = [0] * (0x21FF - 0x2100)
        self.dma_ppu2_hw_registers = [0] * (0x44FF - 0x4200)
        self.extended_ram = [0] * (0x7FFFFF - 0x7E8000)

        # TODO move to somewhere else
        # Initialize APU
        # Wait for port $2140 to be $AA and port $2141 to be $BB.
        # (This means the ROM program is through initializing, and is ready to begin a transfer.)
        # self[0x2140] = 0xAA
        # self[0x2141] = 0xBB

    def __getitem__(self, addr: int) -> int:
        if 0x0000 <= addr <= 0x1FFF:
            return self.low_ram[addr & 0xFFFF]  # LowRAM, shadowed from bank $7E
        elif 0x2100 <= addr <= 0x21FF:
            if 0x2140 <= addr <= 0x217F:
                # 0x2140 - 0x204C == 0xF4 [addr of PORT0]
                if 0x2140 <= addr <= 0x2143:  # TODO ugly
                    return self.apu.ports_w[addr - 0x2140]
                return self.apu[addr - 0x204C]
            return self.pp1_apu_hw_registers[addr - 0x2100]
        elif 0x4200 <= addr <= 0x44FF:
            return self.dma_ppu2_hw_registers[addr - 0x4200]
        elif 0x8000 <= addr <= 0xFFFF:
            return self.rom[addr - 0x8000]
        elif 0x0E8000 <= addr <= 0x0EFFFF:  # Shadowed
            return self.rom[addr - 0x0E8000]
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
            if 0x2140 <= addr <= 0x2143:  # TODO ugly
                self.apu.ports_r[addr - 0x2140] = data & 0xFF
            else:
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
