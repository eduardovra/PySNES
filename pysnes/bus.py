# cython: profile=True

from typing import List

import cython
from rich import print

from .rom import Rom
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller


@cython.cclass
class Bus:
    def __init__(
        self,
        rom: Rom,
        cpu: Cpu,
        apu: Apu,
        ppu: Ppu,
        controllers: List[Controller],
        scheduler,
    ) -> None:
        self.rom = rom  # LoROM section (program memory)
        self.cpu = cpu
        self.apu = apu  # Sound system [0x2140-0x217F]
        self.ppu = ppu
        self.scheduler = scheduler
        self.low_ram = bytearray(0x2000)
        self.high_ram = bytearray(0xE000)
        self.dma_ppu2_hw_registers = bytearray(0x44FF - 0x4200 + 1)
        self.extended_ram = bytearray(0x7FFFFF - 0x7E8000 + 1)
        self.controller_port1, self.controller_port2 = controllers

        # H/V blank flags owned by the bus; set by the PPU scheduler events
        self.hblank: bool = False
        self.vblank: bool = False

    def raise_nmi(self) -> None:
        """Called by PPU at V-Blank start (rising NMI edge)."""
        self.cpu.status.nmi_line = True
        if self.cpu.status.auto_joypad_read_enable:
            self._update_controller_autojoypad_read()
        self.cpu.nmi_rising_edge()

    def lower_nmi(self) -> None:
        """Called by PPU at V-Blank end (falling NMI edge)."""
        self.cpu.status.nmi_line = False

    def _update_controller_autojoypad_read(self) -> None:
        self.controller_port1.latch(0)
        self.controller_port1.latch(1)
        self.controller_port1.joy_h = 0
        for bit in reversed(range(8)):
            if self.controller_port1.data() & 1:
                self.controller_port1.joy_h |= 1 << bit
        self.controller_port1.joy_l = 0
        for bit in reversed(range(8)):
            if self.controller_port1.data() & 1:
                self.controller_port1.joy_l |= 1 << bit

    def __getitem__(self, abs_addr: cython.uint) -> cython.uchar:
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
                        self.apu.sync_to(self.scheduler.master_clock)
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
                    self.cpu.status.nmi_line = False  # Reading clears the line

                    return data
                if addr == 0x4212:  # HVBJOY - PPU Status
                    return (
                        (1 << 5)  # This bit is unmapped but the test program keeps reading it
                        | self.hblank << 6
                        | self.vblank << 7
                    )
                if addr == 0x4218:  # JOY1L
                    return self.controller_port1.joy_l
                if addr == 0x4219:  # JOY1H
                    return self.controller_port1.joy_h
                if addr == 0x421A:  # JOY2L
                    return self.controller_port2.joy_l
                if addr == 0x421B:  # JOY2H
                    return self.controller_port2.joy_h

                return self.dma_ppu2_hw_registers[addr - 0x4200]

        print(f"[yellow]Reading unmapped memory region: 0x{abs_addr:06X}[/yellow]")
        return 0

    def __setitem__(self, abs_addr: cython.uint, data: cython.uchar):
        assert 0x000000 <= abs_addr <= 0xFFFFFF, "Address outside 24 bit range"
        assert 0x00 <= data <= 0xFF, "Data outside 8 bit range"

        bank = abs_addr >> 16 & 0xFF
        addr = abs_addr & 0xFFFF

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
                    self.ppu.mosaic_enabled = [bool(data & (1 << i)) for i in range(4)]
                    self.ppu.mosaic_size = (data >> 4) + 1  # Not sure if I should add 1 here - (0=Smallest/1x1, 0Fh=Largest/16x16)
                    return

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
                    self.ppu.bg1.hoffset = data << 8 | (self.ppu.latch_bgofs_ppu1 & ~7) | (self.ppu.latch_bgofs_ppu2 & 7)
                    self.ppu.latch_bgofs_ppu1 = data
                    self.ppu.latch_bgofs_ppu2 = data
                    return
                if addr == 0x210E:  # BG1VOFS
                    self.ppu.bg1.voffset = data << 8 | self.ppu.latch_bgofs_ppu1
                    self.ppu.latch_bgofs_ppu1 = data
                    return
                if addr == 0x210F:  # BG2HOFS
                    self.ppu.bg2.hoffset = data << 8 | (self.ppu.latch_bgofs_ppu1 & ~7) | (self.ppu.latch_bgofs_ppu2 & 7)
                    self.ppu.latch_bgofs_ppu1 = data
                    self.ppu.latch_bgofs_ppu2 = data
                    return
                if addr == 0x2110:  # BG2VOFS
                    self.ppu.bg2.voffset = data << 8 | self.ppu.latch_bgofs_ppu1
                    self.ppu.latch_bgofs_ppu1 = data
                    return
                if addr == 0x2111:  # BG3HOFS
                    self.ppu.bg3.hoffset = data << 8 | (self.ppu.latch_bgofs_ppu1 & ~7) | (self.ppu.latch_bgofs_ppu2 & 7)
                    self.ppu.latch_bgofs_ppu1 = data
                    self.ppu.latch_bgofs_ppu2 = data
                    return
                if addr == 0x2112:  # BG3VOFS
                    self.ppu.bg3.voffset = data << 8 | self.ppu.latch_bgofs_ppu1
                    self.ppu.latch_bgofs_ppu1 = data
                    return
                if addr == 0x2113:  # BG4HOFS
                    self.ppu.bg4.hoffset = data << 8 | (self.ppu.latch_bgofs_ppu1 & ~7) | (self.ppu.latch_bgofs_ppu2 & 7)
                    self.ppu.latch_bgofs_ppu1 = data
                    self.ppu.latch_bgofs_ppu2 = data
                    return
                if addr == 0x2114:  # BG4VOFS
                    self.ppu.bg4.voffset = data << 8 | self.ppu.latch_bgofs_ppu1
                    self.ppu.latch_bgofs_ppu1 = data
                    return

                # VRAM registers
                if addr == 0x2115:  # VMAIN
                    self.ppu.vmain = data
                    return
                if addr == 0x2116:  # VMADDL
                    self.ppu.vmaddl = data
                    return
                if addr == 0x2117:  # VMADDH
                    self.ppu.vmaddh = data
                    return
                if addr == 0x2118:  # VMDATAL
                    self.ppu.vmdatal = data
                    return
                if addr == 0x2119:  # VMDATAH
                    self.ppu.vmdatah = data
                    return

                if addr == 0x211A:  # M7SEL
                    # raise NotImplementedError("M7SEL register not implemented")
                    """
                    7-6   Screen Over (see below)
                    5-2   Not used
                    1     Screen V-Flip (0=Normal, 1=Flipped)     ;\flip 256x256 "screen"
                    0     Screen H-Flip (0=Normal, 1=Flipped)     ;/
                    Screen Over (when exceeding the 128x128 tile BG Map size):
                        0=Wrap within 128x128 tile area
                        1=Wrap within 128x128 tile area (same as 0)
                        2=Outside 128x128 tile area is Transparent
                        3=Outside 128x128 tile area is filled by Tile 00h
                    """
                    self.ppu.m7sel = data
                    return

                # if 0x211B <= addr <= 0x2120:  # M7A to M7Y
                #     raise NotImplementedError(f"{addr:<#04x} register not implemented")

                # CGRAM registers
                if addr == 0x2121:  # CGADD
                    self.ppu.cgadd = data
                    return
                if addr == 0x2122:  # CGDATA
                    self.ppu.cgdata = data
                    return

                # if 0x2123 <= addr <= 0x212B:
                #     raise NotImplementedError(f"{addr:<#04x} register not implemented")

                if addr == 0x212C:  # TM
                    self.ppu.tm_set(data)
                    return

                if addr == 0x212D:  # TS
                    self.ppu.ts_set(data)
                    return

                # if 0x212E <= addr <= 0x2132:
                #     raise NotImplementedError(f"{addr:<#04x} register not implemented")

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
                    self.apu.sync_to(self.scheduler.master_clock)
                    self.apu.ports_r[addr - 0x2140] = data
                    return

            elif addr == 0x4016:  # JOYSER0
                self.controller_port1.latch(data & 1)
                self.controller_port2.latch(data & 1)
                return

            elif addr == 0x4017:  # JOYSER1
                return  # Writes to this addr are ignored

            elif addr == 0x420B:  # MDMAEN
                self.cpu.dma.mdmaen_set(data)
                return

            elif addr == 0x420C:  # HDMAEN
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
                    # If NMI is being enabled while V-Blank line is already high, trigger immediately.
                    # nmi_enable must be set first so nmi_rising_edge() sees it as True.
                    was_enabled = self.cpu.status.nmi_enable
                    self.cpu.status.nmi_enable = bool(data & 0x80)
                    if data & 0x80:
                        if not was_enabled and self.cpu.status.nmi_line:
                            self.cpu.nmi_rising_edge()
                    return

                if 0x4300 <= addr <= 0x43FF:
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

        print(f"[yellow]Writting unmapped memory region: 0x{abs_addr:06X} = 0x{data:02X}[/yellow]")
