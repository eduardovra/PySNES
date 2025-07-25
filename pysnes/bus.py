from typing import List

from rich import print

from .rom import Rom
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller


class Bus:
    def __init__(
        self, rom: Rom, cpu: Cpu, apu: Apu, ppu: Ppu, controllers: List[Controller]
    ) -> None:
        self.rom = rom  # LoROM section (program memory)
        self.cpu = cpu
        self.apu = apu  # Sound system [0x2140-0x217F]
        self.ppu = ppu
        self.low_ram = bytearray(0x2000)
        self.high_ram = bytearray(0xE000)
        self.dma_ppu2_hw_registers = bytearray(0x44FF - 0x4200 + 1)
        self.extended_ram = bytearray(0x7FFFFF - 0x7E8000 + 1)
        self.controller_port1, self.controller_port2 = controllers

        # i'll set up an unammaped memory region to capture all writes the test
        # does and are not necessarily mapped on real hardware
        self.unmapped = bytearray(2**24)  # 24 bits -> 16Mb

    def __getitem__(self, abs_addr: int) -> int:
        assert 0x000000 <= abs_addr <= 0xFFFFFF, "Address outside 24 bit range"

        bank = abs_addr >> 16 & 0xFF
        addr = abs_addr & 0xFFFF

        # mirror LoROM sections
        if 0x80 <= bank <= 0xFD:
            bank = bank - 0x80

        if ((0x00 <= bank <= 0x6F) and 0x8000 <= addr <= 0xFFFF) or \
            ((0x40 <= bank <= 0x6F) and (0x0000 <= addr <= 0xFFFF)) or \
            ((0x70 <= bank <= 0x7D) and (0x8000 <= addr <= 0xFFFF)):
            rom_addr = (bank * 0x8000) + (addr - (0x8000 if addr >= 0x8000 else 0))
            return self.rom[rom_addr]

        if 0x7E2000 <= abs_addr <= 0x7E7FFF:
            return self.high_ram[abs_addr - 0x7E2000]

        if 0x7E8000 <= abs_addr <= 0x7FFFFF:
            return self.extended_ram[abs_addr - 0x7E8000]

        if (0x00 <= bank <= 0x3F) or bank == 0x7E:
            if 0x0000 <= addr <= 0x1FFF:
                return self.low_ram[addr & 0xFFFF]  # LowRAM, shadowed from bank $7E

        if bank == 0x00:
            # TODO dont know how to map the other banks yet
            if 0x2100 <= addr <= 0x21FF:
                if addr == 0x2137:  # SLHV
                    return self.ppu.slhv

                if addr == 0x2138:  # # OAMDATAREAD
                    return self.ppu.oamdata

                if addr == 0x213B:  # CGDATAREAD
                    return self.ppu.cgdata

                if addr == 0x213C:  # OPHCT
                    return self.ppu.h_counter

                if addr == 0x213D:  # OPVCT
                    return self.ppu.v_counter

                if addr == 0x213E:  # STAT77
                    # TODO PPU Status Flag and Version
                    return 1

                if addr == 0x213F:  # STAT78
                    return self.ppu.stat78

                if 0x2140 <= addr <= 0x217F:
                    # 0x2140 - 0x204C == 0xF4 [addr of PORT0]
                    if 0x2140 <= addr <= 0x2143:  # TODO ugly
                        print(f"  CPU read [{hex(addr)}] ==> {hex(self.apu.ports_w[addr - 0x2140])}")
                        return self.apu.ports_w[addr - 0x2140]
                    return self.apu[addr - 0x204C]

            elif addr == 0x4016:  # JOYSER0
                return self.controller_port1.data()

            elif addr == 0x4017:  # JOYSER1
                data = 0x1C  # pins are connected to GND
                return data | self.controller_port2.data()

            elif 0x4200 <= addr <= 0x44FF:
                if addr == 0x4210:  # RDNMI - NMI Flag and 5A22 Version
                    data = (
                        self.cpu.status.nmi_line << 7
                        | 1 << 6  # This bit is open bus, I'm setting it to satisfy the PLP test program
                        | 0x02  # 5A22 chip version number [0-3]
                    )
                    # if self.cpu.status.nmi_line:
                    # if self.cpu.PC.value == 0x8218 and self.cpu.status.nmi_line:
                    #     breakpoint()
                    # if not self.cpu.status.nmi_hold: # (bsnes)

                    if self.cpu.status.nmi_line:
                        print(f"Clearing NMI line due to read from 0x{addr:04X}")

                    self.cpu.status.nmi_line = False  # Reading clears the line

                    return data
                if addr == 0x4212:  # HVBJOY - PPU Status
                    # H-Blank hcounter <= 2 or hcounter >= 1096
                    # V-Blank vcounter >= ppu.vdisp
                    return (
                        (
                            1 << 5
                        )  # This bit is unmmaped but the test program keeps reading it
                        | self.cpu.status.h_blank_on << 6
                        | self.cpu.status.v_blank_on << 7
                    )
                if addr == 0x4218:  # JOY1L
                    return self.controller_port1.joy_l
                if addr == 0x4219:  # JOY1H
                    return self.controller_port1.joy_h
                if addr == 0x421A:  # JOY2L
                    return self.controller_port2.joy_l
                if addr == 0x421B:  # JOY2H
                    return self.controller_port2.joy_h

                if 0x421C <= addr <= 0x421F:  # Auto Joypad Read registers
                    print(f"[yellow]Reading unmamped memory region: 0x{abs_addr:06X}[/yellow]")

                if 0x4300 <= addr <= 0x43FF:
                    print("READ DMA REGISTER: {}" % hex(addr))
                return self.dma_ppu2_hw_registers[addr - 0x4200]

        # TODO Just for testing the ROM
        print(f"[yellow]Reading unmamped memory region: 0x{abs_addr:06X}[/yellow]")
        #assert 0
        return self.unmapped[abs_addr]

        raise RuntimeError(
            "Error reading unmamped memory region: 0x{:06X}".format(abs_addr)
        )

    def __setitem__(self, abs_addr: int, data: int) -> None:
        assert 0x000000 <= abs_addr <= 0xFFFFFF, "Address outside 24 bit range"
        assert 0x00 <= data <= 0xFF, "Data outside 8 bit range"

        bank = abs_addr >> 16 & 0xFF
        addr = abs_addr & 0xFFFF

        # TODO dealing with the addresses tests are sending
        # mirror LoROM sections
        if 0x80 <= bank <= 0xFD:
            bank = bank - 0x80

        if ((0x00 <= bank <= 0x6F) and 0x8000 <= addr <= 0xFFFF) or \
            ((0x40 <= bank <= 0x6F) and (0x0000 <= addr <= 0xFFFF)) or \
            ((0x70 <= bank <= 0x7D) and (0x8000 <= addr <= 0xFFFF)):
            rom_addr = (bank * 0x8000) + (addr - (0x8000 if addr >= 0x8000 else 0))
            self.rom.rom[rom_addr] = data
            return

        if (0x00 <= bank <= 0x3F) or bank == 0x7E:
            if 0x0000 <= addr <= 0x1FFF:
                self.low_ram[addr & 0xFFFF] = data
                return

        if bank == 0x00:
            if 0x2100 <= addr <= 0x21FF:
                # if 0x2102 <= addr <= 0x2104:
                #    print("WRITE OAM REGISTER: %s = %s" % (hex(addr), hex(data)))
                # if 0x2115 <= addr <= 0x2119:
                #    print("WRITE VRAM REGISTER: %s = %s" % (hex(addr), hex(data)))
                # if 0x2121 <= addr <= 0x2122:
                #    print("WRITE CGRAM REGISTER: %s = %s" % (hex(addr), hex(data)))

                if addr == 0x2100:  # INIDISP
                    self.ppu.inidisp_set(data)
                    return

                # OAM registers
                if addr == 0x2101:  # OBSEL
                    self.ppu.obsel_set(data)
                    return
                if addr == 0x2102:  # OAMADDL
                    self.ppu.oamaddl = data
                    return
                if addr == 0x2103:  # OAMADDH
                    self.ppu.oamaddh = data
                    return
                if addr == 0x2104:  # OAMDATA
                    self.ppu.oamdata = data
                    return

                if addr == 0x2106:  # MOSAIC
                    return  # TODO

                if addr == 0x2105:  # BGMODE
                    # Mode 0 == 2bpp in all BGs
                    # DCBA == 0 using 8x8 tiles in all BGs
                    self.ppu.bgmode = data
                    return
                if addr == 0x2107:  # BG1SC
                    self.ppu.bg1sc_set(data)
                    return
                if addr == 0x2108:  # BG2SC
                    self.ppu.bg2sc_set(data)
                    return
                if addr == 0x2109:  # BG3SC
                    self.ppu.bg3sc_set(data)
                    return
                if addr == 0x210A:  # BG4SC
                    self.ppu.bg4sc_set(data)
                    return
                if addr == 0x210B:  # BG12NBA
                    self.ppu.bg12nba_set(data)
                    return
                if addr == 0x210C:  # BG34NBA
                    self.ppu.bg34nba_set(data)
                    return

                if addr == 0x210D:  # BG1HOFS
                    return  # TODO
                if addr == 0x210E:  # BG1VOFS
                    return  # TODO
                if addr == 0x210F:  # BG2HOFS
                    self.ppu.bg2.hoffset = data << 8 | (self.ppu.latch_bgofs_ppu1 & ~7) | (self.ppu.latch_bgofs_ppu2 & 7)
                    self.ppu.latch_bgofs_ppu1 = data
                    self.ppu.latch_bgofs_ppu2 = data
                    #print(f"self.ppu.bg2.hoffset {self.ppu.bg2.hoffset}")
                    return
                if addr == 0x2110:  # BG2VOFS
                    self.ppu.bg2.voffset = data << 8 | self.ppu.latch_bgofs_ppu1
                    self.ppu.latch_bgofs_ppu1 = data
                    return
                if addr == 0x2111:  # BG3HOFS
                    return  # TODO
                if addr == 0x2112:  # BG3VOFS
                    return  # TODO
                if addr == 0x2113:  # BG4HOFS
                    return  # TODO
                if addr == 0x2114:  # BG4VOFS
                    return  # TODO

                # VRAM registers
                if addr == 0x2115:  # VMAIN
                    self.ppu.vmain = data
                    return
                if addr == 0x2116:  # VMADDL
                    self.ppu.vmaddl.value = data
                    return
                if addr == 0x2117:  # VMADDH
                    self.ppu.vmaddh.value = data
                    return
                if addr == 0x2118:  # VMDATAL
                    self.ppu.vmdatal = data
                    return
                if addr == 0x2119:  # VMDATAH
                    self.ppu.vmdatah = data
                    return

                if 0x211A <= addr <= 0x2120:  # M7SEL
                    return  # TODO

                # CGRAM registers
                if addr == 0x2121:  # CGADD
                    self.ppu.cgadd = data
                    return
                if addr == 0x2122:  # CGDATA
                    self.ppu.cgdata = data
                    return

                if 0x2123 <= addr <= 0x212B:
                    return  # TODO

                if addr == 0x212C:  # TM
                    self.ppu.tm_set(data)
                    return

                if addr == 0x212D:  # TS
                    self.ppu.ts_set(data)
                    return

                if 0x212E <= addr <= 0x2132:
                    return  # TODO

                if addr == 0x2133:  # SETINI
                    # TODO 4 is overscan mode bit - display 239 lines instead of normal 224
                    assert data in (0, 4), f"Value not suported: data={data}"
                    return

                if addr == 0x2134:  # MPYL
                    return  # Not writable
                if addr == 0x2135:  # MPYM
                    return  # Not writable
                if addr == 0x2136:  # MPYH
                    return  # Not writable
                if addr == 0x2137:  # SLHV
                    return  # Not writable

                if 0x2140 <= addr <= 0x2143:  # TODO ugly
                    print(f"  CPU write [{hex(addr)}] <== {hex(data)}")
                    self.apu.ports_r[addr - 0x2140] = data
                    return

            elif addr == 0x4016:  # JOYSER0
                self.controller_port1.latch(data & 1)
                self.controller_port2.latch(data & 1)
                return

            elif addr == 0x4017:  # JOYSER1
                return  # Writes to this addr are ignored

            elif addr == 0x420B:  # MDMAEN
                # print("WRITE DMA REGISTER: %s = %s" % (hex(addr), hex(data)))
                self.cpu.dma.mdmaen_set(data)
                return

            elif addr == 0x420C:  # HDMAEN
                # print("WRITE HDMA REGISTER: %s = %s" % (hex(addr), hex(data)))
                self.cpu.dma.hdmaen_set(data)
                return

            elif 0x4200 <= addr <= 0x44FF:
                if addr == 0x4200:  # NMITIMEN
                    self.cpu.status.auto_joypad_read_enable = bool(data & 0x01)
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

                if 0x4300 <= addr <= 0x43FF:
                    # print("WRITE DMA REGISTER: %s = %s" % (hex(addr), hex(data)))
                    self.cpu.dma[addr] = data
                    return

                self.dma_ppu2_hw_registers[addr - 0x4200] = data
                return

        if 0x7E2000 <= abs_addr <= 0x7E7FFF:
            self.high_ram[abs_addr - 0x7E2000] = data
            return

        if 0x7E8000 <= abs_addr <= 0x7FFFFF:
            self.extended_ram[abs_addr - 0x7E8000] = data
            return

        # TODO Just for testing the ROM
        print(f"[yellow]Writting unmamped memory region: 0x{abs_addr:06X} = 0x{data:02X}[/yellow]")
        self.unmapped[abs_addr] = data
        return

        raise RuntimeError(
            "Error writting unmamped memory region: 0x{:06X}".format(abs_addr)
        )
