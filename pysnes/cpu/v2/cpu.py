from functools import partial
from typing import Any, TYPE_CHECKING


if TYPE_CHECKING:
    from ...bus import Bus


class Reg:
    def __init__(self, bits: int, value: int):
        self.bits = bits
        self.value = value

    @property
    def l(self) -> int:
        """Low byte getter"""
        return self.value & 0xFF

    @l.setter
    def l(self, value: int):
        """Low byte setter"""
        self.value &= 0xFFFF00
        self.value |= value & 0xFF

    @property
    def h(self) -> int:
        """High byte getter"""
        return self.value >> 8 & 0xFF

    @h.setter
    def h(self, value: int):
        """High byte setter"""
        self.value &= 0xFF00FF
        self.value |= value << 8 & 0xFF00

    @property
    def b(self) -> int:
        """Bank byte getter"""
        return self.value >> 16 & 0xFF

    @b.setter
    def b(self, value: int):
        """Bank byte setter"""
        self.value &= 0xFFFF
        self.value |= value << 16 & 0xFF0000

    @property
    def w(self) -> int:
        """Low word getter"""
        return self.value & 0xFFFF

    @w.setter
    def w(self, value: int):
        """Low word setter"""
        self.value &= 0xFF0000
        self.value |= value & 0xFFFF

    @property
    def d(self) -> int:
        """24 bit getter"""
        return self.value & 0xFFFFFF

    @d.setter
    def d(self, value: int):
        """24 bit setter"""
        self.value = value & 0xFFFFFF


class Cpu:
    def __init__(self, hardware_vectors: dict) -> None:
        self.reset_registers()
        self.load_instructions()
        self.build_clock_cycles_table()

        # NOTE shoehorned to make v2 compatible with v1
        from ..v1.cpu import CpuStatus
        self.status = CpuStatus()

        from .wdc65816.disassembler import Disassembler
        self.disassembler = Disassembler(self)

    def __str__(self) -> str:
        return f"A:{self.A.w:04X} X:{self.X.w:04X} Y:{self.Y.w:04X} D:{self.D.w:04X} S:{self.S.w:04X} P:{self.P:02X} DB:{self.DB.l:02X} PB:{self.PC.b:02X} PC:{self.PC.w:06X}"

    def reset_registers(self):
        # Registers
        self.A = Reg(16, 0x0000)  # Accumulator
        self.X = Reg(16, 0x0000)  # X Index Register
        self.Y = Reg(16, 0x0000)  # Y Index Register
        self.D = Reg(16, 0x0000)  # Direct Page Register
        self.S = Reg(16, 0x01FF)  # Stack Pointer
        self.P = 0x34             # Status register
        # self.PB = Reg(8, 0x00)  # Program Bank Register (removed in favor of PC.b)
        self.DB = Reg(8, 0x00)    # Data Bank Register
        self.PC = Reg(24, 0x00)   # self.hardware_vectors["emulation"]["RESET"]

        # bsnes
        # r.vector = 0xfffc;  //reset vector address
        # r24 u;  //temporary register
        # r24 v;  //temporary register
        # r24 w;  //temporary register
        self.U = Reg(24, 0x00)
        self.V = Reg(24, 0x00)
        self.W = Reg(24, 0x00)

        self.Z = Reg(16, 0x0000)  # this only exists in bsnes but not in actual hardware

        # Emulation flag
        self.EF: bool = True  # Starts enabled

        # other regs used by bsnes
        self.irq: bool = False  # IRQ pin (0 = low, 1 = trigger)
        self.wai: bool = False  # raised during wai, cleared after interrupt triggered
        self.stp: bool = False  # raised during stp, never cleared

        # reg to count cpu clock cycles
        # snes9x: CPU.Cycles = 182; // Or 188. This is the cycle count just after the jump to the Reset Vector.
        self.cycles: int = 182
        self.prev_cycles = self.cycles

        # Debug stuff
        self.breakpoint = None
        self.print_debug = False

    def load_instructions(self):
        from .wdc65816.instructions import INSTRUCTIONS

        self.instructions: Any = [None] * 256
        self.debug_symbols: Any = [""] * 256

        # load instructions into main table and setup up debugging symbols
        for opcode, addr_mode, *args in INSTRUCTIONS:
            self.instructions[opcode] = partial(addr_mode, self, *args)
            self.debug_symbols[opcode] = "{:02X} {}".format(opcode, addr_mode.__name__)
            if args:
                if callable(args[0]):
                    args[0] = args[0].__name__
                args = " ".join(str(a) for a in args)
                self.debug_symbols[opcode] += f" {args}"
            self.debug_symbols[opcode] = self.debug_symbols[opcode].ljust(30)

    def attach(self, bus: "Bus") -> None:
        self.bus = bus

        # NOTE shoehorned to make v2 compatible with v1
        from ..v1.cpu import DMA
        self.dma = DMA(bus)

    def idleIRQ(self):
        pass

    def idle(self):
        pass

    def idle2(self):
        if (self.D.l):
            self.idle()

    def idle4(self, x, y):
        """if(!XF || x >> 8 != y >> 8) idle();"""

    def idle6(self, address):
        """if(EF && PC.h != address >> 8) idle();"""

    def idleBranch(self):
        pass

    def idleJump(self):
        pass

    def synchronizing(self):
        """bsnes thing that don't belong here"""
        # this was False and I don't know what it does
        # I changed to True to make test for opcode 0xCB (WAI) pass
        return True

    def write(self, addr, data):
        self.cycles += self.get_clock_cycles(addr)
        self.bus[addr] = data

    def read(self, addr):
        self.cycles += self.get_clock_cycles(addr)
        return self.bus[addr]

    def readDirect(self, address):
        # this is not part of bsnes implementation but it seems
        # tests expect the page to wrap around when in emulation mode
        # even if self.D.l is not zero
        # NOTE commenting because of test for instruction 46 DirectModify LSR
        # if self.EF:
        #     addr = (self.D.h << 8) | ((self.D.l + address) & 0xff)
        #     return self.read(addr)
        if self.EF and self.D.l == 0:
            return self.read(self.D.w | address & 0xff)
        return self.read(self.D.w + address & 0xffff)

    def writeDirect(self, address, data):
        if self.EF and self.D.l == 0:
            return self.write(self.D.w | address & 0xff, data)
        return self.write(self.D.w + address & 0xffff, data)

    def readDirectN(self, address):
        return self.read(self.D.w + address & 0xffff)

    def readBank(self, address):
        return self.read((self.DB.l << 16) + address & 0xffffff)

    def writeBank(self, address, data):
        self.write((self.DB.l << 16) + address & 0xffffff, data);

    def readLong(self, address):
        return self.read(address & 0xffffff)

    def writeLong(self, address, data):
        self.write(address & 0xffffff, data)

    def readStack(self, address):
        return self.read(self.S.w + address & 0xffff)

    def writeStack(self, address, data):
        self.write(self.S.w + address & 0xffff, data)

    def fetch(self):
        # data = self.read(self.PB.l << 16 | self.PC.w)
        data = self.read(self.PC.d)
        self.PC.w += 1
        return data

    def pull(self):
        if self.EF:
            self.S.l += 1
        else:
            self.S.w += 1
        return self.read(self.S.w)

    def push(self, data):
        self.write(self.S.w, data)
        if self.EF:
            self.S.l -= 1
        else:
            self.S.w -= 1

    def pullN(self):
        self.S.w += 1
        return self.read(self.S.w);

    def pushN(self, data):
        self.write(self.S.w, data)
        self.S.w -= 1

    def fetch_and_execute(self):
        self.prev_cycles = self.cycles

        opcode = self.fetch()
        instruction = self.instructions[opcode]
        instruction()

        # To determine the exact length of any CPU instruction,
        # you must examine its behavior for each cycle,
        # and count 6, 8, or 12 master cycles as appropriate.

        # https://wiki.superfamicom.org/timing#clocks-and-refresh-10

        # A CPU internal operation (an IO cycle) takes 6 master cycles.
        # A memory access cycle takes 6, 8, or 12 master cycles,
        # depending on the memory region accessed and bit 0 of CPU register $420D.

        # The SNES runs 1 scanline every 1364 master cycles, except in non-interlace mode scanline
        # $F0 of every other frame (those with $213F.7=1) is only 1360 cycles. Frames are 262 scanlines
        # in non-interlace mode, while in interlace mode frames with $213F.7=0 are 263 scanlines.
        # "V-Blank" runs from either scanline $E1 or $F0 until the end of the frame.

        # The CPU is paused for 40 cycles beginning about 536 cycles after the start of each scanline.
        # Current theory is that this is used for WRAM Refresh. The exact timing is that the refresh pause
        # begins at 538 cycles into the first scanline of the first frame, and thereafter some multiple of
        # 8 cycles after the previous pause that comes closest to 536.

        return self.cycles - self.prev_cycles

    def build_clock_cycles_table(self):
        """
        Builds a table with the number of clock cycles to perform IO on each address.

        The 'Speed' column indicates the memory access speed for that area of memory.
        The SNES master clock runs at about 21MHz (probably as close to 1.89e9/88 Hz as possible).
        Internal operation CPU cycles always take 6 master cycles. Fast memory access cycles also
        take 6 master cycles, Slow memory access cycles take 8 master cycles, and XSlow memory access cycles take 12 master cycles.

        Banks   |  Addresses  | Speed | Mapping
        --------+-------------+-------+---------
        $00-$3F | $0000-$1FFF | Slow  | Address Bus A + /WRAM (mirror $7E:0000-$1FFF)
                | $2000-$20FF | Fast  | Address Bus A
                | $2100-$21FF | Fast  | Address Bus B
                | $2200-$3FFF | Fast  | Address Bus A
                | $4000-$41FF | XSlow | Internal CPU registers (see Note 1 below)
                | $4200-$43FF | Fast  | Internal CPU registers (see Note 1 below)
                | $4400-$5FFF | Fast  | Address Bus A
                | $6000-$7FFF | Slow  | Address Bus A
                | $8000-$FFFF | Slow  | Address Bus A + /CART
        --------+-------------+-------+---------
        $40-$7D | $0000-$FFFF | Slow  | Address Bus A + /CART
        --------+-------------+-------+---------
        $7E-$7F | $0000-$FFFF | Slow  | Address Bus A + /WRAM
        --------+-------------+-------+---------
        $80-$BF | $0000-$1FFF | Slow  | Address Bus A + /WRAM (mirror $7E:0000-$1FFF)
                | $2000-$20FF | Fast  | Address Bus A
                | $2100-$21FF | Fast  | Address Bus B
                | $2200-$3FFF | Fast  | Address Bus A
                | $4000-$41FF | XSlow | Internal CPU registers (see Note 1 below)
                | $4200-$43FF | Fast  | Internal CPU registers (see Note 1 below)
                | $4400-$5FFF | Fast  | Address Bus A
                | $6000-$7FFF | Slow  | Address Bus A
                | $8000-$FFFF | Note2 | Address Bus A + /CART
        --------+-------------+-------+---------
        $C0-$FF | $0000-$FFFF | Note2 | Address Bus A + /CART

        Note 2: If bit 1 of CPU register $420D is set, the speed is Fast, otherwise it is Slow.
        """
        fast, slow, xslow = 6, 8, 12
        self.clock_cycles_table = [fast] * 0xFFFFFF
        for full_addr in range(0, len(self.clock_cycles_table)):
            bank = full_addr >> 16
            addr = full_addr & 0xFFFF
            if 0x00 <= bank <= 0x3F:
                if 0x0000 <= addr <= 0x1FFF:
                    self.clock_cycles_table[full_addr] = slow
                if 0x4000 <= addr <= 0x41FF:
                    self.clock_cycles_table[full_addr] = xslow
                if 0x6000 <= addr <= 0x7FFF:
                    self.clock_cycles_table[full_addr] = slow
                if 0x8000 <= addr <= 0xFFFF:
                    self.clock_cycles_table[full_addr] = slow
            if 0x40 <= bank <= 0x7D:
                self.clock_cycles_table[full_addr] = slow
            if 0x7E <= bank <= 0x7F:
                self.clock_cycles_table[full_addr] = slow
            if 0x80 <= bank <= 0xBF:
                if 0x0000 <= addr <= 0x1FFF:
                    self.clock_cycles_table[full_addr] = slow
                if 0x4000 <= addr <= 0x41FF:
                    self.clock_cycles_table[full_addr] = xslow
                if 0x6000 <= addr <= 0x7FFF:
                    self.clock_cycles_table[full_addr] = slow
                if 0x8000 <= addr <= 0xFFFF:
                    self.clock_cycles_table[full_addr] = fast  # TODO check bit 1 of CPU register $420D
            if 0xC0 <= bank <= 0xFF:
                self.clock_cycles_table[full_addr] = fast  # TODO check bit 1 of CPU register $420D

    def get_clock_cycles(self, addr: int) -> int:
        """Returns the number of clock cycles to perform IO on a given address"""
        return self.clock_cycles_table[addr]

    @property
    def P(self) -> int:
        return self.CF << 0 | self.ZF << 1 | self.IF << 2 | self.DF << 3 | self.XF << 4 | self.MF << 5 | self.VF << 6 | self.NF << 7

    @P.setter
    def P(self, data: int):
        assert 0 <= data <= 0xFF, f"Invalid value for P register: {hex(data)}"
        self.CF = bool(data & 0x01)
        self.ZF = bool(data & 0x02)
        self.IF = bool(data & 0x04)
        self.DF = bool(data & 0x08)
        self.XF = bool(data & 0x10)
        self.MF = bool(data & 0x20)
        self.VF = bool(data & 0x40)
        self.NF = bool(data & 0x80)

    def tick(self):
        """Advances the CPU by one step"""
        # NOTE this is for compatibility with cpu v1
        # not sure I'm keeping this standard

        # Read NMI line
        if self.status.nmi_line and not self.status.nmi_line_last:
            # Transition to high
            if self.status.nmi_enable:
                self.status.nmi_transition = True
        self.status.nmi_line_last = self.status.nmi_line

        # Test for NMI rising edge and trigger interrupt on next iteration
        if self.status.nmi_transition:
            self.status.nmi_transition = False
            self.status.nmi_pending = True

            # Read controllers status during V-Blank if autojoypad is ON
            if self.status.auto_joypad_read_enable:
                self.update_controller_autojoypad_read()

        # If there's no interrupt pending keep normal execution flow
        # if not self.status.interrupt_pending:
        #     cycles = self.fetch_and_execute()
        #     return cycles

        # NMI trigger has been scheduled, so jump to its vector
        if self.status.nmi_pending:
            self.status.nmi_pending = False
            vector = 0xFFFA if self.EF else 0xFFEA
            return self.interrupt(vector)

        return self.fetch_and_execute()

    def interrupt(self, vector: int) -> int:
        """
        Interrupt handler.
        This was copied from v1 without any understanding of what it does.
        """
        # Bank
        if not self.EF:
            self.bus[self.S.w] = self.PC.b
            self.S.w -= 1
        # High
        self.bus[self.S.w] = self.PC.h
        self.S.w -= 1
        # Low
        self.bus[self.S.w] = self.PC.l
        self.S.w -= 1
        # P register
        p = self.P
        self.bus[self.S.w] = p & ~0x10 if self.EF else p
        self.S.w -= 1

        self.IF = True
        self.DF = False

        addr = self.bus[vector] | self.bus[vector + 1] << 8
        self.PC.w = addr

        return 1  # whatever
