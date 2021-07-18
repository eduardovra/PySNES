from .rom import Rom
from .cpu import Cpu
from .apu import Apu


class Bus:
    # TODO consider banks
    def __init__(self, rom: Rom, cpu: Cpu, apu: Apu) -> None:
        self.rom = rom  # LoROM section (program memory)
        self.cpu = cpu
        self.apu = apu  # Sound system [0x2140-0x217F]
        self.low_ram = bytearray(0x2000)
        self.high_ram = bytearray(0xE000)
        self.pp1_apu_hw_registers = bytearray(0xFF)
        self.dma_ppu2_hw_registers = bytearray(0x44FF - 0x4200 + 1)
        self.extended_ram = bytearray(0x7FFFFF - 0x7E8000 + 1)

    def __getitem__(self, abs_addr: int) -> int:
        assert 0x000000 <= abs_addr <= 0xFFFFFF, "Address outside 24 bit range"

        bank = abs_addr >> 16
        addr = abs_addr & 0xFFFF

        if (0x00 <= bank <= 0x3F) or bank == 0x7E:
            if 0x0000 <= addr <= 0x1FFF:
                return self.low_ram[addr & 0xFFFF]  # LowRAM, shadowed from bank $7E

        if bank == 0x00:
            # TODO dont know how to map the other banks yet
            if 0x2100 <= addr <= 0x21FF:
                if 0x2140 <= addr <= 0x217F:
                    # 0x2140 - 0x204C == 0xF4 [addr of PORT0]
                    if 0x2140 <= addr <= 0x2143:  # TODO ugly
                        # print(
                        #    f"  CPU read [{hex(addr)}] ==> {hex(self.apu.ports_w[addr - 0x2140])}"
                        # )
                        return self.apu.ports_w[addr - 0x2140]
                    return self.apu[addr - 0x204C]
                return self.pp1_apu_hw_registers[addr - 0x2100]
            elif 0x4200 <= addr <= 0x44FF:
                if addr == 0x4210:  # RDNMI
                    data = (
                        self.cpu.status.nmi_line << 7
                        | 0x02  # 5A22 chip version number [0-3]
                    )
                    # if not self.cpu.status.nmi_hold: # (bsnes)
                    if True:
                        self.cpu.status.nmi_line = False  # Reading clears the line
                    return data
                return self.dma_ppu2_hw_registers[addr - 0x4200]

        if (0x00 <= bank <= 0x6F) or (0x80 <= bank <= 0xFF):
            if 0x8000 <= addr <= 0xFFFF:
                if bank >= 0x80:
                    bank -= 0x80  # Mirror of 0x00-0x6F
                rom_addr = (bank * 0x8000) + (addr - 0x8000)
                return self.rom[rom_addr]

        if 0x7E2000 <= abs_addr <= 0x7E7FFF:
            return self.high_ram[abs_addr - 0x7E2000]

        if 0x7E8000 <= abs_addr <= 0x7FFFFF:
            return self.extended_ram[abs_addr - 0x7E8000]

        raise RuntimeError(
            "Error reading unmamped memory region: 0x{:06X}".format(abs_addr)
        )

    def __setitem__(self, abs_addr: int, data: int) -> None:
        assert 0x000000 <= abs_addr <= 0xFFFFFF, "Address outside 24 bit range"
        assert 0x00 <= data <= 0xFF

        bank = abs_addr >> 16
        addr = abs_addr & 0xFFFF

        if (0x00 <= bank <= 0x3F) or bank == 0x7E:
            if 0x0000 <= addr <= 0x1FFF:
                self.low_ram[addr & 0xFFFF] = data
                return

        if bank == 0x00:
            if 0x2100 <= addr <= 0x21FF:
                if 0x2140 <= addr <= 0x2143:  # TODO ugly
                    # print(f"  CPU write [{hex(addr)}] <== {hex(data)}")
                    self.apu.ports_r[addr - 0x2140] = data
                    return
                else:
                    self.pp1_apu_hw_registers[addr - 0x2100] = data
                    return
            elif 0x4200 <= addr <= 0x44FF:
                if addr == 0x4200:  # NMITIMEN
                    self.cpu.status.hirq_enable = bool(data & 0x10)
                    self.cpu.status.virq_enable = bool(data & 0x20)
                    self.cpu.status.irq_enable = (
                        self.cpu.status.hirq_enable or self.cpu.status.virq_enable
                    )
                    # Trigger transition if line is up when the flag is enabled
                    if data & 0x80:
                        if not self.cpu.status.nmi_enable and self.cpu.status.nmi_line:
                            self.cpu.status.nmi_transition = True
                    self.cpu.status.nmi_enable = bool(data & 0x80)
                    return
                self.dma_ppu2_hw_registers[addr - 0x4200] = data
                return

        if 0x7E2000 <= abs_addr <= 0x7E7FFF:
            self.high_ram[abs_addr - 0x7E2000] = data
            return

        if 0x7E8000 <= abs_addr <= 0x7FFFFF:
            self.extended_ram[abs_addr - 0x7E8000] = data
            return

        raise RuntimeError(
            "Error writting unmamped memory region: 0x{:06X}".format(abs_addr)
        )
