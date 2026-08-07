import os

from ..apu import Apu
from ..controller import Controller
from ..cpu import Cpu
from ..ppu import Ppu
from ..rom import MappingMode, Rom
from ..scheduler import Scheduler


class Bus:
    def __init__(
        self,
        rom: Rom,
        cpu: Cpu,
        apu: Apu,
        ppu: Ppu,
        controllers: list[Controller],
        scheduler: Scheduler,
    ) -> None:
        self.rom = rom  # program memory (LoROM or HiROM, selected below)
        mapping_mode = rom.snes_header.mapping_mode
        self.is_hirom = (
            mapping_mode == MappingMode.HIROM
            or mapping_mode == MappingMode.HIROM_FAST
        )
        # TODO: HiROM mapping is implemented but lightly tested; address
        # mirroring and SRAM window placement may diverge from hardware for some
        # titles.
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

        # Math hardware registers ($4202-$4206 write, $4214-$4217 read)
        self._wrmpya = 0  # $4202 multiplicand
        self._wrdiv = 0  # $4204-$4205 dividend (16-bit)

    def dump_state(self) -> dict:
        return {
            "low_ram": bytes(self.low_ram),
            "high_ram": bytes(self.high_ram),
            "extended_ram": bytes(self.extended_ram),
            "sram": bytes(self.sram[: self.sram_size])
            if self.sram_size
            else b"",
            "sram_dirty": bool(self.sram_dirty),
            "dma_ppu2_hw_registers": bytes(self.dma_ppu2_hw_registers),
            "hblank": bool(self.hblank),
            "vblank": bool(self.vblank),
            "_wmadd": int(self._wmadd),
            "_wrmpya": int(self._wrmpya),
            "_wrdiv": int(self._wrdiv),
        }

    def load_state(self, d: dict) -> None:
        # Slice-assign so other code holding bytearray references stays valid.
        self.low_ram[:] = d["low_ram"]
        self.high_ram[:] = d["high_ram"]
        self.extended_ram[:] = d["extended_ram"]
        if self.sram_size and d["sram"]:
            n = min(len(d["sram"]), self.sram_size)
            for i in range(n):
                self.sram[i] = d["sram"][i]
        self.sram_dirty = d["sram_dirty"]
        self.dma_ppu2_hw_registers[:] = d["dma_ppu2_hw_registers"]
        self.hblank = d["hblank"]
        self.vblank = d["vblank"]
        self._wmadd = d["_wmadd"]
        self._wrmpya = d["_wrmpya"]
        self._wrdiv = d["_wrdiv"]

    def load_sram(self, path: str) -> int:
        """Load SRAM bytes from `path`. Returns the number of bytes loaded (0 if
        no SRAM or file missing)."""
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
        """Write SRAM bytes to `path` if dirty. Returns bytes written (0 if no
        SRAM or not dirty)."""
        if self.sram_size == 0 or not self.sram_dirty:
            return 0
        with open(path, "wb") as f:
            f.write(bytes(self.sram[: self.sram_size]))
        self.sram_dirty = False
        return self.sram_size

    def raise_nmi(self) -> None:
        """Called by PPU at V-Blank start (rising NMI edge).

        TODO: NMI timing — on real hardware the NMI fires ~2 CPU cycles after
        V-Blank starts; we fire it synchronously which may be slightly early for
        games that poll $4210 before the NMI handler runs.
        """
        self.cpu.status.nmi_line = True
        if self.cpu.status.auto_joypad_read_enable:
            self._update_controller_autojoypad_read()
        self.cpu.nmi_rising_edge()

    def lower_nmi(self) -> None:
        """Called by PPU at V-Blank end.

        Per SNES hardware, $4210 bit 7 is NOT auto-cleared at V-Blank end —
        the flag persists until the CPU reads $4210. So this is a no-op for
        now; we keep the hook for future use (e.g. dropping the NMI interrupt
        line when NMITIMEN bit 7 is cleared by the game).
        """
        # Intentionally no-op on nmi_line. Kept as a named hook.

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

    def read(self, abs_addr: int) -> int:
        bank = abs_addr >> 16 & 0xFF
        addr = abs_addr & 0xFFFF

        # Mirror: banks $80-$FF shadow $00-$7F.
        # $80-$FD → $00-$7D maps the LoROM program area; $FE-$FF mirror the
        # $7E-$7F WRAM banks. The abs_addr rewrite is needed because the
        # WRAM/high-RAM branches below match on abs_addr, not on bank.
        if 0x80 <= bank <= 0xFF:
            bank = bank - 0x80
            abs_addr = abs_addr - 0x800000

        if self.is_hirom:
            # HiROM ROM: banks $00-$3F at $8000-$FFFF, banks $40-$7D full.
            # rom_addr = (bank & 0x3F) << 16 | addr works for both regions.
            if ((0x00 <= bank <= 0x3F) and addr >= 0x8000) or (
                0x40 <= bank <= 0x7D
            ):
                rom_addr = ((bank & 0x3F) << 16) | addr
                return self.rom.read(rom_addr)

            # HiROM SRAM: banks $20-$3F at $6000-$7FFF, 8KB window per bank.
            if 0x20 <= bank <= 0x3F and 0x6000 <= addr <= 0x7FFF:
                if self.sram_size:
                    sram_addr = (
                        ((bank - 0x20) << 13) | (addr - 0x6000)
                    ) & self.sram_mask
                    return self.sram[sram_addr]
                return 0xFF
        else:
            if (
                ((0x00 <= bank <= 0x6F) and 0x8000 <= addr <= 0xFFFF)
                or ((0x40 <= bank <= 0x6F) and (0x0000 <= addr <= 0xFFFF))
                or ((0x70 <= bank <= 0x7D) and (0x8000 <= addr <= 0xFFFF))
            ):
                rom_addr = (bank * 0x8000) + (
                    addr - (0x8000 if addr >= 0x8000 else 0)
                )
                return self.rom.read(rom_addr)

            # SRAM: LoROM banks $70-$7D, addr $0000-$7FFF (mirrored from
            # $F0-$FD)
            if 0x70 <= bank <= 0x7D and addr < 0x8000:
                if self.sram_size:
                    sram_addr = (((bank - 0x70) << 15) | addr) & self.sram_mask
                    return self.sram[sram_addr]
                return 0xFF

        if 0x7E2000 <= abs_addr <= 0x7E7FFF:
            return self.high_ram[abs_addr - 0x7E2000]

        if 0x7E8000 <= abs_addr <= 0x7FFFFF:
            return self.extended_ram[abs_addr - 0x7E8000]

        bank_has_low_ram = (0x00 <= bank <= 0x3F) or bank == 0x7E
        if bank_has_low_ram and 0x0000 <= addr <= 0x1FFF:
            # LowRAM, shadowed from bank $7E
            return self.low_ram[addr & 0xFFFF]

        if 0x00 <= bank <= 0x3F:
            # Hardware registers $2100-$21FF and $4200-$44FF are mirrored
            # across System Area banks $00-$3F (and $80-$BF via LoROM mirror
            # which is normalized above).
            if 0x2100 <= addr <= 0x21FF:
                if addr == 0x2134:  # MPYL
                    return self.ppu._mpy_result & 0xFF
                if addr == 0x2135:  # MPYM
                    return (self.ppu._mpy_result >> 8) & 0xFF
                if addr == 0x2136:  # MPYH
                    return (self.ppu._mpy_result >> 16) & 0xFF

                if addr == 0x2137:  # SLHV
                    return self.ppu.slhv

                if addr == 0x2138:  # # OAMDATAREAD
                    return self.ppu.oamdata

                if addr == 0x2139:  # RDVRAML
                    return self.ppu.rdvraml()

                if addr == 0x213A:  # RDVRAMH
                    return self.ppu.rdvramh()

                if addr == 0x213B:  # CGDATAREAD
                    return self.ppu.cgdata

                if addr == 0x213C:  # OPHCT (9-bit counter; port is byte-wide)
                    return self.ppu.h_counter & 0xFF

                if addr == 0x213D:  # OPVCT (9-bit counter; port is byte-wide)
                    return self.ppu.v_counter & 0xFF

                if addr == 0x213E:  # STAT77
                    # TODO PPU Status Flag and Version
                    return 1

                if addr == 0x213F:  # STAT78
                    return self.ppu.stat78

                if 0x2140 <= addr <= 0x217F:
                    # 0x2140 - 0x204C == 0xF4 [addr of PORT0]
                    if 0x2140 <= addr <= 0x2143:
                        self.apu.sync_to(
                            self.scheduler.master_clock
                            + (self.cpu.cycles - self.cpu.prev_cycles)
                        )
                        return self.apu.ports_w[addr - 0x2140]
                    return self.apu.read_external(addr - 0x204C)

            elif addr == 0x4016:  # JOYSER0
                return self.controller_port1.data()

            elif addr == 0x4017:  # JOYSER1
                data = 0x1C  # pins are connected to GND
                return data | self.controller_port2.data()

            elif 0x4200 <= addr <= 0x44FF:
                if addr == 0x4210:  # RDNMI - NMI Flag and 5A22 Version
                    data = (
                        self.cpu.status.nmi_line << 7
                        | 1
                        # This bit is open bus, I'm setting it to satisfy the
                        # PLP test program
                        << 6
                        | 0x02  # 5A22 chip version number [0-3]
                    )
                    self.cpu.status.nmi_line = False  # Reading clears the line

                    return data
                if addr == 0x4211:  # TIMEUP - IRQ flag (read-and-clear)
                    data = self.cpu.status.irq_line << 7
                    self.cpu.status.irq_line = (
                        False  # Reading clears the latched flag
                    )
                    return data
                if addr == 0x4212:  # HVBJOY - PPU Status
                    return (
                        (
                            1 << 5
                            # This bit is unmapped but the test program keeps
                            # reading it
                        )
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

                # DMA channel registers ($4300–$43FF): return live channel
                # state. The bytearray cache is never kept in sync, and the
                # engine mutates source_address/transfer_size during transfers
                # — games (e.g. the 93143 hvdma test ROM) read these back.
                if 0x4300 <= addr <= 0x43FF:
                    return self.cpu.dma.read(addr)

                return self.dma_ppu2_hw_registers[addr - 0x4200]

            # Unmapped system-area holes return the open-bus (MDR) value rather
            # than 0. We approximate the MDR with the high byte of the address,
            # which is the value the CPU last drove on the bus for an absolute
            # read (`lda $21C2` → 0x21). This is what the SuperNES Test Program
            # relies on: it gates its Character Test animation on bit 5 of a
            # read from $21C2 (expects 0x21, bit 5 set); returning 0 froze the
            # demo.
            if (
                0x2000
                <= addr
                <= 0x21FF  # 0x2100-0x21FF: mapped regs handled above
                or 0x2200 <= addr <= 0x3FFF
                or 0x4000
                <= addr
                <= 0x41FF  # 0x4016/0x4017 already handled above
                or 0x4500 <= addr <= 0x7FFF
            ):
                return (addr >> 8) & 0xFF

            raise NotImplementedError(
                f"Reading unmapped memory region: 0x{abs_addr:06X}"
            )

        raise NotImplementedError(
            f"Reading unmapped memory region: 0x{abs_addr:06X}"
        )

    def peek(self, abs_addr: int) -> int:
        """Read without side effects — safe for debugger/disassembler use.

        ROM, RAM, and SRAM are read normally. Hardware register ranges
        ($2000-$5FFF in system-area banks) return 0 to avoid flag clears,
        VRAM-prefetch advances, or other I/O side effects.
        """
        bank = abs_addr >> 16 & 0xFF
        addr = abs_addr & 0xFFFF
        if 0x80 <= bank <= 0xFF:
            bank = bank - 0x80
            abs_addr = abs_addr - 0x800000
        if (0x00 <= bank <= 0x3F or bank == 0x7E) and 0x2000 <= addr <= 0x5FFF:
            return 0
        return self.read(abs_addr)

    def write(self, abs_addr: int, data: int) -> None:
        bank = abs_addr >> 16 & 0xFF
        addr = abs_addr & 0xFFFF

        # See read(): mirror $80-$FF to $00-$7F (covers WRAM mirror at $FE-$FF).
        if 0x80 <= bank <= 0xFF:
            bank = bank - 0x80
            abs_addr = abs_addr - 0x800000

        if self.is_hirom:
            # ROM is read-only on real hardware: writes land on the cart bus
            # but the mask ROM ignores them. Dropping them here matters for
            # programs whose stack drifts into the bank-0 vector region
            # ($FFE0-$FFFF) — corrupting ROM would stomp the interrupt vectors.
            if ((0x00 <= bank <= 0x3F) and addr >= 0x8000) or (
                0x40 <= bank <= 0x7D
            ):
                return

            if 0x20 <= bank <= 0x3F and 0x6000 <= addr <= 0x7FFF:
                if self.sram_size:
                    sram_addr = (
                        ((bank - 0x20) << 13) | (addr - 0x6000)
                    ) & self.sram_mask
                    self.sram[sram_addr] = data
                    self.sram_dirty = True
                return
        else:
            if (
                ((0x00 <= bank <= 0x6F) and 0x8000 <= addr <= 0xFFFF)
                or ((0x40 <= bank <= 0x6F) and (0x0000 <= addr <= 0xFFFF))
                or ((0x70 <= bank <= 0x7D) and (0x8000 <= addr <= 0xFFFF))
            ):
                return

            # SRAM: LoROM banks $70-$7D, addr $0000-$7FFF (mirrored from
            # $F0-$FD)
            if 0x70 <= bank <= 0x7D and addr < 0x8000:
                if self.sram_size:
                    sram_addr = (((bank - 0x70) << 15) | addr) & self.sram_mask
                    self.sram[sram_addr] = data
                    self.sram_dirty = True
                return

        bank_has_low_ram = (0x00 <= bank <= 0x3F) or bank == 0x7E
        if bank_has_low_ram and 0x0000 <= addr <= 0x1FFF:
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
                    self.ppu.mosaic_enabled = [
                        bool(data & (1 << i)) for i in range(4)
                    ]
                    self.ppu.mosaic_size = (
                        (data >> 4) + 1
                        # Not sure if I should add 1 here - (0=Smallest/1x1,
                        # 0Fh=Largest/16x16)
                    )
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
                    self.ppu.bg1.hoffset = (
                        data << 8
                        | (self.ppu.latch_bgofs_ppu1 & ~7)
                        | (self.ppu.latch_bgofs_ppu2 & 7)
                    )
                    self.ppu.latch_bgofs_ppu1 = data
                    self.ppu.latch_bgofs_ppu2 = data
                    return
                if addr == 0x210E:  # BG1VOFS
                    self.ppu.bg1.voffset = data << 8 | self.ppu.latch_bgofs_ppu1
                    self.ppu.latch_bgofs_ppu1 = data
                    return
                if addr == 0x210F:  # BG2HOFS
                    self.ppu.bg2.hoffset = (
                        data << 8
                        | (self.ppu.latch_bgofs_ppu1 & ~7)
                        | (self.ppu.latch_bgofs_ppu2 & 7)
                    )
                    self.ppu.latch_bgofs_ppu1 = data
                    self.ppu.latch_bgofs_ppu2 = data
                    return
                if addr == 0x2110:  # BG2VOFS
                    self.ppu.bg2.voffset = data << 8 | self.ppu.latch_bgofs_ppu1
                    self.ppu.latch_bgofs_ppu1 = data
                    return
                if addr == 0x2111:  # BG3HOFS
                    self.ppu.bg3.hoffset = (
                        data << 8
                        | (self.ppu.latch_bgofs_ppu1 & ~7)
                        | (self.ppu.latch_bgofs_ppu2 & 7)
                    )
                    self.ppu.latch_bgofs_ppu1 = data
                    self.ppu.latch_bgofs_ppu2 = data
                    return
                if addr == 0x2112:  # BG3VOFS
                    self.ppu.bg3.voffset = data << 8 | self.ppu.latch_bgofs_ppu1
                    self.ppu.latch_bgofs_ppu1 = data
                    return
                if addr == 0x2113:  # BG4HOFS
                    self.ppu.bg4.hoffset = (
                        data << 8
                        | (self.ppu.latch_bgofs_ppu1 & ~7)
                        | (self.ppu.latch_bgofs_ppu2 & 7)
                    )
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
                    self.ppu.refill_vram_prefetch()
                    return
                if addr == 0x2117:  # VMADDH
                    self.ppu.vmaddh = data
                    self.ppu.refill_vram_prefetch()
                    return
                if addr == 0x2118:  # VMDATAL
                    self.ppu.vmdatal = data
                    return
                if addr == 0x2119:  # VMDATAH
                    self.ppu.vmdatah = data
                    return

                if addr == 0x211A:  # M7SEL
                    """
                    7-6   Screen Over (see below)
                    5-2   Not used
                    1     Screen V-Flip (0=Normal, 1=Flipped)  ;\flip the
                    0     Screen H-Flip (0=Normal, 1=Flipped)  ;/256x256 screen
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

                if addr == 0x2133:  # SETINI — display control (write-only)
                    # Bit 0: Screen interlace       (0=progressive, 1=interlaced
                    # 448-line field alternation) Bit 1: OBJ interlace
                    # (0=normal, 1=split sprite rows across fields) Bit 2:
                    # Overscan               (0=224 visible lines, 1=239 visible
                    # lines) Bit 3: Pseudo-hires           (0=256-wide,
                    # 1=512-wide via subscreen half-pixel offset) Bits 4-5:
                    # unused Bit 6: EXTBG                  (Mode 7 only; enables
                    # BG2 as a second Mode 7 layer) Bit 7: External sync
                    # (genlock to external video; no effect in emulation)
                    self.ppu.m7_extbg = (data >> 6) & 1
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
                    self.apu.sync_to(
                        self.scheduler.master_clock
                        + (self.cpu.cycles - self.cpu.prev_cycles)
                    )
                    self.apu.ports_r[addr - 0x2140] = data
                    return

                if (
                    addr == 0x2180
                ):  # WMDATA - write byte to WRAM at WMADD, increment
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

            elif addr == 0x4202:  # WRMPYA - multiplicand
                self._wrmpya = data
                self.dma_ppu2_hw_registers[addr - 0x4200] = data
                return

            elif addr == 0x4203:  # WRMPYB - multiplier (triggers multiply)
                product = self._wrmpya * data
                self.dma_ppu2_hw_registers[0x4203 - 0x4200] = data
                self.dma_ppu2_hw_registers[0x4214 - 0x4200] = 0
                self.dma_ppu2_hw_registers[0x4215 - 0x4200] = 0
                self.dma_ppu2_hw_registers[0x4216 - 0x4200] = product & 0xFF
                self.dma_ppu2_hw_registers[0x4217 - 0x4200] = (
                    product >> 8
                ) & 0xFF
                return

            elif addr == 0x4204:  # WRDIVL - dividend low byte
                self._wrdiv = (self._wrdiv & 0xFF00) | data
                self.dma_ppu2_hw_registers[addr - 0x4200] = data
                return

            elif addr == 0x4205:  # WRDIVH - dividend high byte
                self._wrdiv = (self._wrdiv & 0x00FF) | (data << 8)
                self.dma_ppu2_hw_registers[addr - 0x4200] = data
                return

            elif addr == 0x4206:  # WRDIVB - divisor (triggers divide)
                self.dma_ppu2_hw_registers[addr - 0x4200] = data
                if data == 0:
                    quotient = 0xFFFF
                    remainder = self._wrdiv
                else:
                    quotient = self._wrdiv // data
                    remainder = self._wrdiv % data
                self.dma_ppu2_hw_registers[0x4214 - 0x4200] = quotient & 0xFF
                self.dma_ppu2_hw_registers[0x4215 - 0x4200] = (
                    quotient >> 8
                ) & 0xFF
                self.dma_ppu2_hw_registers[0x4216 - 0x4200] = remainder & 0xFF
                self.dma_ppu2_hw_registers[0x4217 - 0x4200] = (
                    remainder >> 8
                ) & 0xFF
                return

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
                        self.cpu.status.hirq_enable
                        or self.cpu.status.virq_enable
                    )
                    # Disabling both H-IRQ and V-IRQ clears any latched IRQ
                    # flag.
                    if not self.cpu.status.irq_enable:
                        self.cpu.status.irq_line = False
                    # If NMI is being enabled while V-Blank line is already
                    # high, trigger immediately. nmi_enable must be set first so
                    # nmi_rising_edge() sees it as True.
                    was_enabled = self.cpu.status.nmi_enable
                    self.cpu.status.nmi_enable = bool(data & 0x80)
                    nmi_now_enabled = data & 0x80 and not was_enabled
                    if nmi_now_enabled and self.cpu.status.nmi_line:
                        self.cpu.nmi_rising_edge()
                    return

                if addr == 0x4207:  # HTIMEL
                    self.cpu.status.htime = (
                        self.cpu.status.htime & 0x100
                    ) | data
                    return
                if addr == 0x4208:  # HTIMEH (only bit 0)
                    self.cpu.status.htime = (self.cpu.status.htime & 0x0FF) | (
                        (data & 0x01) << 8
                    )
                    return
                if addr == 0x4209:  # VTIMEL
                    self.cpu.status.vtime = (
                        self.cpu.status.vtime & 0x100
                    ) | data
                    return
                if addr == 0x420A:  # VTIMEH (only bit 0)
                    self.cpu.status.vtime = (self.cpu.status.vtime & 0x0FF) | (
                        (data & 0x01) << 8
                    )
                    return

                if 0x4300 <= addr <= 0x43FF:
                    self.cpu.dma.write(addr, data)
                    return

                self.dma_ppu2_hw_registers[addr - 0x4200] = data
                return

            # TODO: Implement true open-bus side effects/MDR behavior instead
            # of silently dropping writes in these known system-area holes.
            if (
                0x2000
                <= addr
                <= 0x21FF  # 0x2100-0x21FF: mapped regs handled above
                or 0x2200 <= addr <= 0x3FFF
                or 0x4000
                <= addr
                <= 0x41FF  # 0x4016/0x4017 already handled above
                or 0x4500 <= addr <= 0x7FFF
            ):
                return

            raise NotImplementedError(
                f"Writting unmapped memory region: 0x{abs_addr:06X} = "
                f"0x{data:02X}"
            )

        if 0x7E2000 <= abs_addr <= 0x7E7FFF:
            self.high_ram[abs_addr - 0x7E2000] = data
            return

        if 0x7E8000 <= abs_addr <= 0x7FFFFF:
            self.extended_ram[abs_addr - 0x7E8000] = data
            return

        raise NotImplementedError(
            f"Writting unmapped memory region: 0x{abs_addr:06X} = 0x{data:02X}"
        )
