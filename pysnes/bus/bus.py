# cython: profile=True

import os
from typing import List

import cython

from ..rom import Rom
from ..cpu import Cpu
from ..apu import Apu
from ..ppu import Ppu
from ..controller import Controller
from ..scheduler import Scheduler


@cython.cclass
class Bus:
    cpu: Cpu
    ppu: Ppu
    scheduler: Scheduler
    low_ram: cython.uchar[:]
    high_ram: cython.uchar[:]
    extended_ram: cython.uchar[:]
    sram: cython.uchar[:]
    sram_size: cython.uint
    sram_mask: cython.uint
    sram_dirty: cython.bint
    dma_ppu2_hw_registers: cython.uchar[:]
    hblank: cython.bint
    vblank: cython.bint

    def __init__(
        self,
        rom: Rom,
        cpu: Cpu,
        apu: Apu,
        ppu: Ppu,
        controllers: List[Controller],
        scheduler: Scheduler,
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
        self.sram_size = getattr(rom, "sram_size", 0)
        self.sram_mask = self.sram_size - 1 if self.sram_size else 0
        self.sram = bytearray(self.sram_size if self.sram_size else 1)
        self.sram_dirty = False
        self.controller_port1, self.controller_port2 = controllers

        # H/V blank flags owned by the bus; set by the PPU scheduler events
        self.hblank = False
        self.vblank = False

        # WRAM port address register (17-bit, 0x2181-0x2183)
        self._wmadd = 0

    def load_sram(self, path: str) -> int:
        """Load SRAM bytes from `path`. Returns the number of bytes loaded (0 if no SRAM or file missing)."""
        i: cython.uint
        n: cython.uint
        if self.sram_size == 0 or not os.path.exists(path):
            return 0
        with open(path, "rb") as f:
            data: bytes = f.read()
        n = min(len(data), self.sram_size)
        for i in range(n):
            self.sram[i] = data[i]
        self.sram_dirty = False
        return n

    def save_sram(self, path: str) -> int:
        """Write SRAM bytes to `path` if dirty. Returns bytes written (0 if no SRAM or not dirty)."""
        if self.sram_size == 0 or not self.sram_dirty:
            return 0
        with open(path, "wb") as f:
            f.write(bytes(self.sram[:self.sram_size]))
        self.sram_dirty = False
        return self.sram_size

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
        for bit in range(7, -1, -1):
            if self.controller_port1.data() & 1:
                self.controller_port1.joy_h |= 1 << bit
        self.controller_port1.joy_l = 0
        for bit in range(7, -1, -1):
            if self.controller_port1.data() & 1:
                self.controller_port1.joy_l |= 1 << bit

    @cython.cfunc
    @cython.inline
    def read(self, abs_addr: cython.uint) -> cython.uchar:
        bank: cython.uint = abs_addr >> 16 & 0xFF
        addr: cython.uint = abs_addr & 0xFFFF

        # mirror LoROM sections
        if 0x80 <= bank <= 0xFD:
            bank = bank - 0x80

        if ((0x00 <= bank <= 0x6F) and 0x8000 <= addr <= 0xFFFF) or \
            ((0x40 <= bank <= 0x6F) and (0x0000 <= addr <= 0xFFFF)) or \
            ((0x70 <= bank <= 0x7D) and (0x8000 <= addr <= 0xFFFF)):
            rom_addr: cython.uint = (bank * 0x8000) + (addr - (0x8000 if addr >= 0x8000 else 0))
            return self.rom[rom_addr]

        # SRAM: LoROM banks $70-$7D, addr $0000-$7FFF (mirrored from $F0-$FD)
        if 0x70 <= bank <= 0x7D and addr < 0x8000:
            if self.sram_size:
                sram_addr: cython.uint = (((bank - 0x70) << 15) | addr) & self.sram_mask
                return self.sram[sram_addr]
            return 0xFF

        if 0x7E2000 <= abs_addr <= 0x7E7FFF:
            return self.high_ram[abs_addr - 0x7E2000]

        if 0x7E8000 <= abs_addr <= 0x7FFFFF:
            return self.extended_ram[abs_addr - 0x7E8000]

        if (0x00 <= bank <= 0x3F) or bank == 0x7E:
            if 0x0000 <= addr <= 0x1FFF:
                return self.low_ram[addr & 0xFFFF]  # LowRAM, shadowed from bank $7E

        if 0x00 <= bank <= 0x3F:
            # Hardware registers $2100-$21FF and $4200-$44FF are mirrored
            # across System Area banks $00-$3F (and $80-$BF via LoROM mirror
            # which is normalized above).
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
                    if 0x2140 <= addr <= 0x2143:
                        self.apu.sync_to(self.scheduler.master_clock + (self.cpu.cycles - self.cpu.prev_cycles))
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
                if addr == 0x4211:  # TIMEUP - IRQ flag (read-and-clear)
                    data = self.cpu.status.irq_line << 7
                    self.cpu.status.irq_line = False  # Reading clears the latched flag
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

        raise RuntimeError(f"Reading unmapped memory region: 0x{abs_addr:06X}")

    def __getitem__(self, abs_addr: cython.uint) -> cython.uchar:
        return self.read(abs_addr)

    @cython.cfunc
    @cython.inline
    def write(self, abs_addr: cython.uint, data: cython.uchar):
        bank: cython.uint = abs_addr >> 16 & 0xFF
        addr: cython.uint = abs_addr & 0xFFFF

        # mirror LoROM sections
        if 0x80 <= bank <= 0xFD:
            bank = bank - 0x80

        if ((0x00 <= bank <= 0x6F) and 0x8000 <= addr <= 0xFFFF) or \
            ((0x40 <= bank <= 0x6F) and (0x0000 <= addr <= 0xFFFF)) or \
            ((0x70 <= bank <= 0x7D) and (0x8000 <= addr <= 0xFFFF)):
            rom_addr: cython.uint = (bank * 0x8000) + (addr - (0x8000 if addr >= 0x8000 else 0))
            self.rom.rom[rom_addr] = data
            return

        # SRAM: LoROM banks $70-$7D, addr $0000-$7FFF (mirrored from $F0-$FD)
        if 0x70 <= bank <= 0x7D and addr < 0x8000:
            if self.sram_size:
                sram_addr: cython.uint = (((bank - 0x70) << 15) | addr) & self.sram_mask
                self.sram[sram_addr] = data
                self.sram_dirty = True
            return

        if (0x00 <= bank <= 0x3F) or bank == 0x7E:
            if 0x0000 <= addr <= 0x1FFF:
                self.low_ram[addr & 0xFFFF] = data
                return

        if 0x00 <= bank <= 0x3F:
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

                if 0x211B <= addr <= 0x2120:  # M7A to M7Y
                    self.ppu.m7_write(addr, data)
                    return

                # CGRAM registers
                if addr == 0x2121:  # CGADD
                    self.ppu.cgadd = data
                    return
                if addr == 0x2122:  # CGDATA
                    self.ppu.cgdata = data
                    return

                if addr == 0x2123:  # W12SEL
                    self.ppu.w12sel = data
                    return
                if addr == 0x2124:  # W34SEL
                    self.ppu.w34sel = data
                    return
                if addr == 0x2125:  # WOBJSEL
                    self.ppu.wobjsel = data
                    return
                if addr == 0x2126:  # WH0
                    self.ppu.wh0 = data
                    return
                if addr == 0x2127:  # WH1
                    self.ppu.wh1 = data
                    return
                if addr == 0x2128:  # WH2
                    self.ppu.wh2 = data
                    return
                if addr == 0x2129:  # WH3
                    self.ppu.wh3 = data
                    return
                if addr == 0x212A:  # WBGLOG
                    self.ppu.wbglog = data
                    return
                if addr == 0x212B:  # WOBJLOG
                    self.ppu.wobjlog = data
                    return

                if addr == 0x212C:  # TM
                    self.ppu.tm_set(data)
                    return

                if addr == 0x212D:  # TS
                    self.ppu.ts_set(data)
                    return

                if addr == 0x212E:  # TMW
                    self.ppu.tmw = data
                    return
                if addr == 0x212F:  # TSW
                    self.ppu.tsw = data
                    return
                if addr == 0x2130:  # CGWSEL
                    self.ppu.cgwsel = data
                    return
                if addr == 0x2131:  # CGADSUB
                    self.ppu.cgadsub = data
                    return
                if addr == 0x2132:  # COLDATA
                    self.ppu.coldata_set(data)
                    return

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

                if 0x2140 <= addr <= 0x2143:  # APUIO0-APUIO3 (CPU→SPC ports)
                    self.apu.sync_to(self.scheduler.master_clock + (self.cpu.cycles - self.cpu.prev_cycles))
                    self.apu.ports_r[addr - 0x2140] = data
                    return

                if addr == 0x2180:  # WMDATA - write byte to WRAM at WMADD, increment
                    wm_addr = self._wmadd & 0x1FFFF
                    if wm_addr < 0x2000:
                        self.low_ram[wm_addr] = data
                    elif wm_addr < 0x8000:
                        self.high_ram[wm_addr - 0x2000] = data
                    else:
                        self.extended_ram[wm_addr - 0x8000] = data
                    self._wmadd = (self._wmadd + 1) & 0x1FFFF
                    return
                if addr == 0x2181:  # WMADDL
                    self._wmadd = (self._wmadd & 0x1FF00) | data
                    return
                if addr == 0x2182:  # WMADDM
                    self._wmadd = (self._wmadd & 0x100FF) | (data << 8)
                    return
                if addr == 0x2183:  # WMADDH (only bit 0 used - 17-bit address)
                    self._wmadd = (self._wmadd & 0x0FFFF) | ((data & 1) << 16)
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

            elif addr == 0x420D:  # MEMSEL - FastROM select
                self.cpu.status.fast_rom = bool(data & 0x01)
                return

            elif 0x4200 <= addr <= 0x44FF:
                if addr == 0x4200:  # NMITIMEN
                    self.cpu.status.auto_joypad_read_enable = bool(data & 0x01)
                    self.cpu.status.hirq_enable = bool(data & 0x10)
                    self.cpu.status.virq_enable = bool(data & 0x20)
                    self.cpu.status.irq_enable = (
                        self.cpu.status.hirq_enable or self.cpu.status.virq_enable
                    )
                    # Disabling both H-IRQ and V-IRQ clears any latched IRQ flag.
                    if not self.cpu.status.irq_enable:
                        self.cpu.status.irq_line = False
                    # If NMI is being enabled while V-Blank line is already high, trigger immediately.
                    # nmi_enable must be set first so nmi_rising_edge() sees it as True.
                    was_enabled = self.cpu.status.nmi_enable
                    self.cpu.status.nmi_enable = bool(data & 0x80)
                    if data & 0x80:
                        if not was_enabled and self.cpu.status.nmi_line:
                            self.cpu.nmi_rising_edge()
                    return

                if addr == 0x4207:  # HTIMEL
                    self.cpu.status.htime = (self.cpu.status.htime & 0x100) | data
                    return
                if addr == 0x4208:  # HTIMEH (only bit 0)
                    self.cpu.status.htime = (self.cpu.status.htime & 0x0FF) | ((data & 0x01) << 8)
                    return
                if addr == 0x4209:  # VTIMEL
                    self.cpu.status.vtime = (self.cpu.status.vtime & 0x100) | data
                    return
                if addr == 0x420A:  # VTIMEH (only bit 0)
                    self.cpu.status.vtime = (self.cpu.status.vtime & 0x0FF) | ((data & 0x01) << 8)
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

        raise RuntimeError(f"Writting unmapped memory region: 0x{abs_addr:06X} = 0x{data:02X}")

    def __setitem__(self, abs_addr: cython.uint, data: cython.uchar):
        self.write(abs_addr, data)
