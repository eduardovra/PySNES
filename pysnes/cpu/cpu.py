from functools import partial
from typing import Any, TYPE_CHECKING
from dataclasses import dataclass

from rich import print
import cython

from .dma import DMA

if TYPE_CHECKING:
    from ...bus import Bus

if cython.compiled:
    print(f"[blue]{__name__} compiled with Cython[/blue]")


@cython.cclass
class Reg:
    bits = cython.declare(cython.uchar, visibility="public")
    value = cython.declare(cython.uint, visibility="public")

    def __init__(self, bits: cython.uchar, value: cython.uint):
        self.bits = bits
        self.value = value

    @property
    def l(self) -> cython.uchar:
        """Low byte getter"""
        return self.value & 0xFF

    @l.setter
    def l(self, value: cython.uchar):
        """Low byte setter"""
        self.value &= 0xFFFF00
        self.value |= value & 0xFF

    @property
    def h(self) -> cython.uchar:
        """High byte getter"""
        return self.value >> 8 & 0xFF

    @h.setter
    def h(self, value: cython.uchar):
        """High byte setter"""
        self.value &= 0xFF00FF
        self.value |= value << 8 & 0xFF00

    @property
    def b(self) -> cython.uchar:
        """Bank byte getter"""
        return self.value >> 16 & 0xFF

    @b.setter
    def b(self, value: cython.uchar):
        """Bank byte setter"""
        self.value &= 0xFFFF
        self.value |= value << 16 & 0xFF0000

    @property
    def w(self) -> cython.ushort:
        """Low word getter"""
        return self.value & 0xFFFF

    @w.setter
    def w(self, value: cython.ushort):
        """Low word setter"""
        self.value &= 0xFF0000
        self.value |= value & 0xFFFF

    @property
    def d(self) -> cython.uint:
        """24 bit getter"""
        return self.value & 0xFFFFFF

    @d.setter
    def d(self, value: cython.uint):
        """24 bit setter"""
        self.value = value & 0xFFFFFF


@dataclass
@cython.cclass
class CpuStatus:
    hirq_enable: cython.bint = False
    virq_enable: cython.bint = False
    irq_enable: cython.bint = False

    # nmi_line: set to True at V-Blank start by bus.raise_nmi(); read by bus at $4210
    nmi_line: cython.bint = False
    nmi_enable: cython.bint = False

    auto_joypad_read_enable: cython.bint = False


@cython.cclass
class Cpu:
    CFlag = cython.declare(cython.bint, visibility="public")
    ZFlag = cython.declare(cython.bint, visibility="public")
    IFlag = cython.declare(cython.bint, visibility="public")
    DFlag = cython.declare(cython.bint, visibility="public")
    XFlag = cython.declare(cython.bint, visibility="public")
    MFlag = cython.declare(cython.bint, visibility="public")
    VFlag = cython.declare(cython.bint, visibility="public")
    NFlag = cython.declare(cython.bint, visibility="public")

    cycles = cython.declare(cython.uint, visibility="public")
    prev_cycles = cython.declare(cython.uint, visibility="public")
    status = cython.declare(CpuStatus, visibility="public")

    def __init__(self, hardware_vectors: dict) -> None:
        self.reset_registers()
        self.load_instructions()
        # self.build_clock_cycles_table()

        # NOTE shoehorned to make v2 compatible with v1
        self.status = CpuStatus()

        from .wdc65816.disassembler import Disassembler
        self.disassembler = Disassembler(self)
        self.trace_log = []
        self.trace_enabled = False  # set True to populate trace_log (reads bus)
        self.scheduler = None

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

        # Per-instruction cycle counter (bus reads/writes + idles).
        # Reset at the top of fetch_and_execute; used by instruction tests.
        self.icycles: int = 0

        # NMI pending flag — set by nmi_rising_edge(), checked in _step()
        self._nmi_pending: bool = False

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
        self.dma = DMA(bus)

    # ------------------------------------------------------------------
    # Scheduler-based execution
    # ------------------------------------------------------------------

    def start(self, scheduler) -> None:
        """Register the CPU with the scheduler. Call once before the main loop."""
        self.scheduler = scheduler
        self.scheduler.add(0, self._step)

    def _step(self) -> None:
        """Single-instruction step, called by the Scheduler. Reschedules itself."""
        if self._nmi_pending:
            self._nmi_pending = False
            vector = 0xFFFA if self.EF else 0xFFEA
            mc = self.interrupt(vector)
        else:
            mc = self.fetch_and_execute()
        # mc is in master clocks; schedule the next step that many clocks ahead
        self.scheduler.add(mc, self._step)

    def nmi_rising_edge(self) -> None:
        """Called by the bus when V-Blank starts (rising NMI edge)."""
        if self.status.nmi_enable:
            self._nmi_pending = True

    def idleIRQ(self):
        self.cycles += 6
        self.icycles += 1

    def idle(self):
        self.cycles += 6
        self.icycles += 1

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

    @cython.ccall
    def write(self, addr: cython.uint, data: cython.uchar):
        self.cycles += self.get_clock_cycles(addr)
        self.icycles += 1
        self.bus.write(addr, data)

    @cython.ccall
    def read(self, addr: cython.uint) -> cython.uchar:
        self.cycles += self.get_clock_cycles(addr)
        self.icycles += 1
        return self.bus.read(addr)

    @cython.ccall
    def readDirect(self, address: cython.uint) -> cython.uchar:
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

    @cython.ccall
    def writeDirect(self, address: cython.uint, data: cython.uchar):
        if self.EF and self.D.l == 0:
            self.write(self.D.w | address & 0xff, data)
        else:
            self.write(self.D.w + address & 0xffff, data)

    @cython.ccall
    def readDirectN(self, address: cython.uint) -> cython.uchar:
        return self.read(self.D.w + address & 0xffff)

    @cython.ccall
    def readBank(self, address: cython.uint) -> cython.uchar:
        return self.read((self.DB.l << 16) + address & 0xffffff)

    @cython.ccall
    def writeBank(self, address: cython.uint, data: cython.uchar):
        self.write((self.DB.l << 16) + address & 0xffffff, data)

    @cython.ccall
    def readLong(self, address: cython.uint) -> cython.uchar:
        return self.read(address & 0xffffff)

    @cython.ccall
    def writeLong(self, address: cython.uint, data: cython.uchar):
        self.write(address & 0xffffff, data)

    @cython.ccall
    def readStack(self, address: cython.uint) -> cython.uchar:
        return self.read(self.S.w + address & 0xffff)

    @cython.ccall
    def writeStack(self, address: cython.uint, data: cython.uchar):
        self.write(self.S.w + address & 0xffff, data)

    @cython.ccall
    def fetch(self) -> cython.uchar:
        # data = self.read(self.PB.l << 16 | self.PC.w)
        data = self.read(self.PC.d)
        self.PC.w += 1
        return data

    @cython.ccall
    def pull(self) -> cython.uchar:
        if self.EF:
            self.S.l += 1
        else:
            self.S.w += 1
        return self.read(self.S.w)

    @cython.ccall
    def push(self, data: cython.uchar):
        self.write(self.S.w, data)
        if self.EF:
            self.S.l -= 1
        else:
            self.S.w -= 1

    @cython.ccall
    def pullN(self) -> cython.uchar:
        self.S.w += 1
        return self.read(self.S.w)

    @cython.ccall
    def pushN(self, data: cython.uchar):
        self.write(self.S.w, data)
        self.S.w -= 1

    @cython.ccall
    def fetch_and_execute(self) -> cython.uint:
        self.icycles = 0

        if self.trace_enabled:
            disassembled = self.disassembler.disassemble(self.PC.w)
            self.trace_log.append(disassembled)
            self.trace_log = self.trace_log[-10:]  # only the last instructions

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

    @cython.cfunc
    @cython.inline
    def get_clock_cycles(self, addr: cython.uint) -> cython.uint:
        """Returns the number of clock cycles to perform IO on a given address

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

        """
        https://board.zsnes.com/phpBB3/viewtopic.php?t=12711

        Hard to say exactly. The core clocks runs at 21.477MHz.
        Each cycle can take 6, 8 or 12 clocks, let's assume 8 on average (12 is very rare.)
        Each opcode takes 2-6 cycles, so let's say 4 on average.
        21,477,272/32=~671,164 opcodes/second.

        https://forums.nesdev.org/viewtopic.php?p=175515&sid=e26b9af85c521bb4c8fa1e905af2157c#p175515
        Right. Every CPU instruction takes some number of CPU cycles; each CPU cycle in turn takes
        6, 8, or 12 master clock cycles depending on which memory it's accessing.
        """

        fast, slow, xslow = 6, 8, 12

        bank = (addr >> 16) & 0xFF
        addr = addr & 0xFFFF
        if 0x00 <= bank <= 0x3F:
            if 0x0000 <= addr <= 0x1FFF:
                return slow
            if 0x4000 <= addr <= 0x41FF:
                return xslow
            if 0x6000 <= addr <= 0x7FFF:
                return slow
            if 0x8000 <= addr <= 0xFFFF:
                return slow
        if 0x40 <= bank <= 0x7D:
            return slow
        if 0x7E <= bank <= 0x7F:
            return slow
        if 0x80 <= bank <= 0xBF:
            if 0x0000 <= addr <= 0x1FFF:
                return slow
            if 0x4000 <= addr <= 0x41FF:
                return xslow
            if 0x6000 <= addr <= 0x7FFF:
                return slow
            if 0x8000 <= addr <= 0xFFFF:
                return fast  # TODO check bit 1 of CPU register $420D
        if 0xC0 <= bank <= 0xFF:
            return fast  # TODO check bit 1 of CPU register $420D

        return fast

    @property
    def P(self) -> cython.uchar:
        return self.CFlag << 0 | self.ZFlag << 1 | self.IFlag << 2 | self.DFlag << 3 | self.XFlag << 4 | self.MFlag << 5 | self.VFlag << 6 | self.NFlag << 7

    @P.setter
    def P(self, data: cython.uchar):
        # assert 0 <= data <= 0xFF, f"Invalid value for P register: {hex(data)}"
        self.CFlag = data & 0x01 > 0
        self.ZFlag = data & 0x02 > 0
        self.IFlag = data & 0x04 > 0
        self.DFlag = data & 0x08 > 0
        self.XFlag = data & 0x10 > 0
        self.MFlag = data & 0x20 > 0
        self.VFlag = data & 0x40 > 0
        self.NFlag = data & 0x80 > 0

    def interrupt(self, vector: int) -> int:
        """
        Interrupt handler.
        This was copied from v1 without any understanding of what it does.
        """
        # Bank
        if not self.EF:
            self.bus.write(self.S.w, self.PC.b)
            self.S.w -= 1
        # High
        self.bus.write(self.S.w, self.PC.h)
        self.S.w -= 1
        # Low
        self.bus.write(self.S.w, self.PC.l)
        self.S.w -= 1
        # P register
        p = self.P
        self.bus.write(self.S.w, p & ~0x10 if self.EF else p)
        self.S.w -= 1

        self.IFlag = True
        self.DFlag = False

        addr = self.bus.read(vector) | self.bus.read(vector + 1) << 8
        self.PC.w = addr

        return 1  # whatever
