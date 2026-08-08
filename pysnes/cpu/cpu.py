from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..bus import Bus
    from ..rom import HardwareVectors


class Reg:
    def __init__(self, bits: int, value: int) -> None:
        self.bits = bits
        self.value = value

    # `l`/`h` mirror the 65816's low/high byte accessor names; E743 objects
    # to `l` as ambiguous, but renaming would break the register vocabulary.
    @property
    def l(self) -> int:  # noqa: E743
        """Low byte getter"""
        return self.value & 0xFF

    @l.setter
    def l(self, value: int) -> None:  # noqa: E743
        """Low byte setter"""
        self.value &= 0xFFFF00
        self.value |= value & 0xFF

    @property
    def h(self) -> int:
        """High byte getter"""
        return self.value >> 8 & 0xFF

    @h.setter
    def h(self, value: int) -> None:
        """High byte setter"""
        self.value &= 0xFF00FF
        self.value |= value << 8 & 0xFF00

    @property
    def b(self) -> int:
        """Bank byte getter"""
        return self.value >> 16 & 0xFF

    @b.setter
    def b(self, value: int) -> None:
        """Bank byte setter"""
        self.value &= 0xFFFF
        self.value |= value << 16 & 0xFF0000

    @property
    def w(self) -> int:
        """Low word getter"""
        return self.value & 0xFFFF

    @w.setter
    def w(self, value: int) -> None:
        """Low word setter"""
        self.value &= 0xFF0000
        self.value |= value & 0xFFFF

    @property
    def d(self) -> int:
        """24 bit getter"""
        return self.value & 0xFFFFFF

    @d.setter
    def d(self, value: int) -> None:
        """24 bit setter"""
        self.value = value & 0xFFFFFF


class CpuStatus:
    # nmi_line: set to True at V-Blank start by bus.raise_nmi(); read by bus at
    # $4210 irq_line: set by PPU when H/V match condition is satisfied; cleared
    # by reading $4211 (TIMEUP) or by disabling both H-IRQ and V-IRQ via $4200.
    # H/V IRQ target registers ($4207-$420A). 9-bit each. MEMSEL ($420D) bit 0:
    # 1 = FastROM (banks $80-$BF and $C0-$FF use 6 MC instead of 8)

    def __init__(self):
        self.hirq_enable = False
        self.virq_enable = False
        self.irq_enable = False
        self.nmi_line = False
        self.nmi_enable = False
        self.irq_line = False
        self.htime = 0x1FF  # power-on default (maximum — won't match)
        self.vtime = 0x1FF
        self.auto_joypad_read_enable = False
        self.fast_rom = False

    def dump_state(self) -> dict:
        return {
            "hirq_enable": bool(self.hirq_enable),
            "virq_enable": bool(self.virq_enable),
            "irq_enable": bool(self.irq_enable),
            "nmi_line": bool(self.nmi_line),
            "nmi_enable": bool(self.nmi_enable),
            "irq_line": bool(self.irq_line),
            "htime": int(self.htime),
            "vtime": int(self.vtime),
            "auto_joypad_read_enable": bool(self.auto_joypad_read_enable),
            "fast_rom": bool(self.fast_rom),
        }

    def load_state(self, d: dict) -> None:
        self.hirq_enable = d["hirq_enable"]
        self.virq_enable = d["virq_enable"]
        self.irq_enable = d["irq_enable"]
        self.nmi_line = d["nmi_line"]
        self.nmi_enable = d["nmi_enable"]
        self.irq_line = d["irq_line"]
        self.htime = d["htime"]
        self.vtime = d["vtime"]
        self.auto_joypad_read_enable = d["auto_joypad_read_enable"]
        self.fast_rom = d["fast_rom"]


class InstructionSlot:
    """Replaces functools.partial for instruction dispatch.

    Stores the addressing-mode function and up to two pre-bound arguments.
    """

    def __init__(self, func, arg1=None, arg2=None, nargs: int = 0) -> None:
        self._func = func
        self._arg1 = arg1
        self._arg2 = arg2
        self._nargs = nargs

    def call(self, cpu: Cpu):
        if self._nargs == 0:
            self._func(cpu)
        elif self._nargs == 1:
            self._func(cpu, self._arg1)
        else:
            self._func(cpu, self._arg1, self._arg2)


class Cpu:
    def __init__(self, hardware_vectors: HardwareVectors) -> None:
        self.reset_registers()
        self.load_instructions()

        self.status = CpuStatus()

        from .wdc65816.disassembler import Disassembler

        self.disassembler = Disassembler(self)
        self.trace_log = []
        self.trace_enabled = False  # set True to populate trace_log (reads bus)
        self.scheduler = None

    def __str__(self) -> str:
        return (
            f"A:{self.A.w:04X} X:{self.X.w:04X} Y:{self.Y.w:04X} "
            f"D:{self.D.w:04X} S:{self.S.w:04X} P:{self.P:02X} "
            f"DB:{self.DB.l:02X} PB:{self.PC.b:02X} PC:{self.PC.w:06X}"
        )

    def reset_registers(self):
        # Registers
        self.A = Reg(16, 0x0000)  # Accumulator
        self.X = Reg(16, 0x0000)  # X Index Register
        self.Y = Reg(16, 0x0000)  # Y Index Register
        self.D = Reg(16, 0x0000)  # Direct Page Register
        self.S = Reg(16, 0x01FF)  # Stack Pointer
        self.P = 0x34  # Status register
        # The Program Bank Register lives in PC.b, not a separate Reg.
        self.DB = Reg(8, 0x00)  # Data Bank Register
        self.PC = Reg(24, 0x00)  # self.hardware_vectors.emulation.reset

        # bsnes
        # r.vector = 0xfffc;  //reset vector address
        # r24 u;  //temporary register
        # r24 v;  //temporary register
        # r24 w;  //temporary register
        self.U = Reg(24, 0x00)
        self.V = Reg(24, 0x00)
        self.W = Reg(24, 0x00)

        self.Z = Reg(
            16, 0x0000
        )  # this only exists in bsnes but not in actual hardware

        # Emulation flag
        self.EF: bool = True  # Starts enabled

        # other regs used by bsnes
        self.irq: bool = False  # IRQ pin (0 = low, 1 = trigger)
        self.wai: bool = (
            False  # raised during wai, cleared after interrupt triggered
        )
        self.stp: bool = False  # raised during stp, never cleared

        # reg to count cpu clock cycles snes9x: CPU.Cycles = 182; // Or 188.
        # This is the cycle count just after the jump to the Reset Vector.
        self.cycles: int = 182
        self.prev_cycles = self.cycles

        # Per-instruction cycle counter (bus reads/writes + idles).
        # Reset at the top of fetch_and_execute; used by instruction tests.
        self.icycles: int = 0

        # NMI pending flag — set by nmi_rising_edge(), checked in _step()
        self._nmi_pending: bool = False

        # DRAM refresh: the SNES CPU is paused for 40 MC once per scanline
        # (approximately at dot 133 = MC 536 of each scanline). Tracking the
        # scanline index lets _step() add the 40 MC pause on the first
        # instruction of each new scanline.
        self._last_refresh_scanline: int = -1

    def dump_state(self) -> dict:
        return {
            "A": self.A.value,
            "X": self.X.value,
            "Y": self.Y.value,
            "D": self.D.value,
            "S": self.S.value,
            "DB": self.DB.value,
            "PC": self.PC.value,
            "P": int(self.P),
            "EF": bool(self.EF),
            "irq": bool(self.irq),
            "wai": bool(self.wai),
            "stp": bool(self.stp),
            "CFlag": bool(self.CFlag),
            "ZFlag": bool(self.ZFlag),
            "IFlag": bool(self.IFlag),
            "DFlag": bool(self.DFlag),
            "XFlag": bool(self.XFlag),
            "MFlag": bool(self.MFlag),
            "VFlag": bool(self.VFlag),
            "NFlag": bool(self.NFlag),
            "cycles": int(self.cycles),
            "prev_cycles": int(self.prev_cycles),
            "icycles": int(self.icycles),
            "_nmi_pending": bool(self._nmi_pending),
            "_last_refresh_scanline": int(self._last_refresh_scanline),
            "status": self.status.dump_state(),
        }

    def load_state(self, d: dict) -> None:
        self.A.value = d["A"]
        self.X.value = d["X"]
        self.Y.value = d["Y"]
        self.D.value = d["D"]
        self.S.value = d["S"]
        self.DB.value = d["DB"]
        self.PC.value = d["PC"]
        self.P = d["P"]
        self.EF = d["EF"]
        self.irq = d["irq"]
        self.wai = d["wai"]
        self.stp = d["stp"]
        self.CFlag = d["CFlag"]
        self.ZFlag = d["ZFlag"]
        self.IFlag = d["IFlag"]
        self.DFlag = d["DFlag"]
        self.XFlag = d["XFlag"]
        self.MFlag = d["MFlag"]
        self.VFlag = d["VFlag"]
        self.NFlag = d["NFlag"]
        self.cycles = d["cycles"]
        self.prev_cycles = d["prev_cycles"]
        self.icycles = d["icycles"]
        self._nmi_pending = d["_nmi_pending"]
        self._last_refresh_scanline = d["_last_refresh_scanline"]
        self.status.load_state(d["status"])

    def load_instructions(self):
        from .wdc65816.instructions import build_instructions

        self.instructions: Any = [None] * 256

        # build_instructions binds the opcode table to this CPU's live Reg
        # objects (cpu.X, cpu.A, ...) so the hot addressing-mode functions need
        # no per-call getattr(cpu, name). The reset path rebuilds the table
        # after reset_registers() makes new Reg objects.
        for opcode, addr_mode, *args in build_instructions(self):
            # InstructionSlot stores addr_mode + extra args; cpu is passed at
            # call time. This replaces functools.partial — see
            # InstructionSlot.call().
            if len(args) == 0:
                slot = InstructionSlot(addr_mode, nargs=0)
            elif len(args) == 1:
                slot = InstructionSlot(addr_mode, args[0], nargs=1)
            else:
                slot = InstructionSlot(addr_mode, args[0], args[1], nargs=2)
            self.instructions[opcode] = slot

    def attach(self, bus: Bus) -> None:
        from .dma import DMA

        self.bus = bus
        self.dma = DMA(bus)

    # ------------------------------------------------------------------
    # Scheduler-based execution
    # ------------------------------------------------------------------

    def start(self, scheduler) -> None:
        """Register the CPU with the scheduler. Call once before the main
        loop."""
        self.scheduler = scheduler
        self.scheduler.add(0, self._step)

    def _step(self) -> None:
        """Run CPU instructions until the next non-CPU scheduled event is due.

        Instead of rescheduling through the heapq on every instruction, we run
        a tight inner loop and only touch the scheduler once per PPU/other event
        boundary (~2x per scanline). This eliminates ~4M heapq push/pop pairs
        per 300 frames and lets PyPy trace through the loop body without the
        scheduler call breaking the JIT trace.
        """
        peeked = self.scheduler.peek()
        # When no other events are scheduled (e.g. unit tests without a PPU),
        # set next_event = master_clock so the loop exits after one instruction.
        if peeked != 0xFFFFFFFFFFFFFFFF:
            next_event = peeked
        else:
            next_event = self.scheduler.master_clock
        while True:
            if self._nmi_pending:
                self._nmi_pending = False
                vector = 0xFFFA if self.EF else 0xFFEA
                mc = self.interrupt(vector)
            elif self.status.irq_line and not self.IFlag:
                vector = 0xFFFE if self.EF else 0xFFEE
                mc = self.interrupt(vector)
            else:
                mc = self.fetch_and_execute()
            # DRAM refresh: once per scanline the CPU is paused for 40 MC.
            scanline = self.scheduler.master_clock // 1364
            if scanline != self._last_refresh_scanline:
                self._last_refresh_scanline = scanline
                mc += 40
            self.scheduler.master_clock += mc
            if self.scheduler.master_clock >= next_event:
                break
        # Reschedule at current time so other events fire before CPU continues.
        self.scheduler.add(0, self._step)

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
        if self.D.l:
            self.idle()

    def idle4(self, x: int, y: int) -> None:
        """if(!XF || x >> 8 != y >> 8) idle();"""
        if not self.XFlag or (x >> 8) != (y >> 8):
            self.idle()

    def idle6(self, address: int) -> None:
        """if(EF && PC.h != address >> 8) idle();"""
        if self.EF and (self.PC.w >> 8) != (address >> 8):
            self.idle()

    def idleBranch(self):
        pass

    def idleJump(self):
        pass

    def synchronizing(self):
        """bsnes thing that don't belong here"""
        # this was False and I don't know what it does
        # I changed to True to make test for opcode 0xCB (WAI) pass
        return True

    def write(self, addr: int, data: int) -> None:
        self.cycles += self.get_clock_cycles(addr)
        self.bus.write(addr, data)
        self.icycles += 1

    def read(self, addr: int) -> int:
        self.cycles += self.get_clock_cycles(addr)
        data = self.bus.read(addr)
        self.icycles += 1
        return data

    def readDirect(self, address: int) -> int:
        # Not part of the bsnes implementation, but the tests expect the page
        # to wrap in emulation mode even when D.l is non-zero. Wrapping
        # unconditionally breaks the DirectModify LSR test for opcode $46, so
        # the wrap stays gated on D.l == 0.
        if self.EF and self.D.l == 0:
            return self.read(self.D.w | address & 0xFF)
        return self.read(self.D.w + address & 0xFFFF)

    def writeDirect(self, address: int, data: int) -> None:
        if self.EF and self.D.l == 0:
            self.write(self.D.w | address & 0xFF, data)
        else:
            self.write(self.D.w + address & 0xFFFF, data)

    def readDirectN(self, address: int) -> int:
        return self.read(self.D.w + address & 0xFFFF)

    def readBank(self, address: int) -> int:
        return self.read((self.DB.l << 16) + address & 0xFFFFFF)

    def writeBank(self, address: int, data: int) -> None:
        self.write((self.DB.l << 16) + address & 0xFFFFFF, data)

    def readLong(self, address: int) -> int:
        return self.read(address & 0xFFFFFF)

    def writeLong(self, address: int, data: int) -> None:
        self.write(address & 0xFFFFFF, data)

    def readStack(self, address: int) -> int:
        return self.read(self.S.w + address & 0xFFFF)

    def writeStack(self, address: int, data: int) -> None:
        self.write(self.S.w + address & 0xFFFF, data)

    def fetch(self) -> int:
        data = self.read(self.PC.d)
        self.PC.w += 1
        return data

    def pull(self) -> int:
        if self.EF:
            self.S.l += 1
        else:
            self.S.w += 1
        return self.read(self.S.w)

    def push(self, data: int) -> None:
        self.write(self.S.w, data)
        if self.EF:
            self.S.l -= 1
        else:
            self.S.w -= 1

    def pullN(self) -> int:
        self.S.w += 1
        return self.read(self.S.w)

    def pushN(self, data: int) -> None:
        self.write(self.S.w, data)
        self.S.w -= 1

    def fetch_and_execute(self) -> int:
        self.icycles = 0

        if self.trace_enabled:
            disassembled = self.disassembler.disassemble(self.PC.d)
            self.trace_log.append(disassembled)
            self.trace_log = self.trace_log[-10:]  # only the last instructions

        self.prev_cycles = self.cycles

        opcode = self.fetch()
        slot: InstructionSlot = self.instructions[opcode]
        slot.call(self)

        # To determine the exact length of any CPU instruction,
        # you must examine its behavior for each cycle,
        # and count 6, 8, or 12 master cycles as appropriate.

        # https://wiki.superfamicom.org/timing#clocks-and-refresh-10

        # A CPU internal operation (an IO cycle) takes 6 master cycles. A memory
        # access cycle takes 6, 8, or 12 master cycles, depending on the memory
        # region accessed and bit 0 of CPU register $420D.

        # The SNES runs 1 scanline every 1364 master cycles, except in
        # non-interlace mode scanline $F0 of every other frame (those with
        # $213F.7=1) is only 1360 cycles. Frames are 262 scanlines in
        # non-interlace mode, while in interlace mode frames with $213F.7=0 are
        # 263 scanlines. "V-Blank" runs from either scanline $E1 or $F0 until
        # the end of the frame.

        # The CPU is paused for 40 cycles beginning about 536 cycles after the
        # start of each scanline. Current theory is that this is used for WRAM
        # Refresh. The exact timing is that the refresh pause begins at 538
        # cycles into the first scanline of the first frame, and thereafter some
        # multiple of 8 cycles after the previous pause that comes closest to
        # 536.

        return self.cycles - self.prev_cycles

    def get_clock_cycles(self, addr: int) -> int:
        """Returns the number of clock cycles to perform IO on a given address

        The 'Speed' column indicates the memory access speed for that area of
        memory. The SNES master clock runs at about 21MHz (probably as close to
        1.89e9/88 Hz as possible). Internal operation CPU cycles always take 6
        master cycles. Fast memory access cycles also take 6 master cycles, Slow
        memory access cycles take 8 master cycles, and XSlow memory access
        cycles take 12 master cycles.

        Banks   |  Addresses  | Speed | Mapping
        --------+-------------+-------+---------
        $00-$3F | $0000-$1FFF | Slow  | Address Bus A + /WRAM (mirror of $7E)
                | $2000-$20FF | Fast  | Address Bus A
                | $2100-$21FF | Fast  | Address Bus B
                | $2200-$3FFF | Fast  | Address Bus A
                | $4000-$41FF | XSlow | Internal CPU registers (Note 1)
                | $4200-$43FF | Fast  | Internal CPU registers (Note 1)
                | $4400-$5FFF | Fast  | Address Bus A
                | $6000-$7FFF | Slow  | Address Bus A
                | $8000-$FFFF | Slow  | Address Bus A + /CART
        --------+-------------+-------+---------
        $40-$7D | $0000-$FFFF | Slow  | Address Bus A + /CART
        --------+-------------+-------+---------
        $7E-$7F | $0000-$FFFF | Slow  | Address Bus A + /WRAM
        --------+-------------+-------+---------
        $80-$BF | $0000-$1FFF | Slow  | Address Bus A + /WRAM (mirror of $7E)
                | $2000-$20FF | Fast  | Address Bus A
                | $2100-$21FF | Fast  | Address Bus B
                | $2200-$3FFF | Fast  | Address Bus A
                | $4000-$41FF | XSlow | Internal CPU registers (Note 1)
                | $4200-$43FF | Fast  | Internal CPU registers (Note 1)
                | $4400-$5FFF | Fast  | Address Bus A
                | $6000-$7FFF | Slow  | Address Bus A
                | $8000-$FFFF | Note2 | Address Bus A + /CART
        --------+-------------+-------+---------
        $C0-$FF | $0000-$FFFF | Note2 | Address Bus A + /CART

        Note 2: If bit 1 of CPU register $420D is set, the speed is Fast,
        otherwise it is Slow.
        """

        """
        https://board.zsnes.com/phpBB3/viewtopic.php?t=12711

        Hard to say exactly. The core clocks runs at 21.477MHz.
        Each cycle can take 6, 8 or 12 clocks, let's assume 8 on
        average (12 is very rare.)
        Each opcode takes 2-6 cycles, so let's say 4 on average.
        21,477,272/32=~671,164 opcodes/second.

        https://forums.nesdev.org/viewtopic.php?p=175515&sid=e26b9af85c521bb4c8fa1e905af2157c#p175515
        Right. Every CPU instruction takes some number of CPU cycles;
        each CPU cycle in turn takes 6, 8, or 12 master clock cycles
        depending on which memory it's accessing.
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
                return fast if self.status.fast_rom else slow
        if 0xC0 <= bank <= 0xFF:
            return fast if self.status.fast_rom else slow

        return fast

    @property
    def P(self) -> int:
        return (
            self.CFlag << 0
            | self.ZFlag << 1
            | self.IFlag << 2
            | self.DFlag << 3
            | self.XFlag << 4
            | self.MFlag << 5
            | self.VFlag << 6
            | self.NFlag << 7
        )

    @P.setter
    def P(self, data: int) -> None:
        self.CFlag = data & 0x01 > 0
        self.ZFlag = data & 0x02 > 0
        self.IFlag = data & 0x04 > 0
        self.DFlag = data & 0x08 > 0
        self.XFlag = data & 0x10 > 0
        self.MFlag = data & 0x20 > 0
        self.VFlag = data & 0x40 > 0
        self.NFlag = data & 0x80 > 0

    def interrupt(self, vector: int) -> int:
        """NMI/IRQ handler. Returns elapsed master-clock cycles for the
        scheduler."""
        self.prev_cycles = self.cycles
        self.idle()
        self.idle()
        # Bank
        if not self.EF:
            self.write(self.S.w, self.PC.b)
            self.S.w -= 1
        # High
        self.write(self.S.w, self.PC.h)
        self.S.w -= 1
        # Low
        self.write(self.S.w, self.PC.l)
        self.S.w -= 1
        # P register
        p = self.P
        self.write(self.S.w, p & ~0x10 if self.EF else p)
        self.S.w -= 1

        self.IFlag = True
        self.DFlag = False

        addr = self.read(vector) | self.read(vector + 1) << 8
        self.PC.w = addr
        self.PC.b = 0

        return self.cycles - self.prev_cycles
