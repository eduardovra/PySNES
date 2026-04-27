# cython: auto_pickle=False
from typing import Any

import cython

from .spc700.instructions_spc700 import INSTRUCTIONS
from .spc700.disassembler import SPC700Disassembler


@cython.cclass
class InstructionSlot:
    """Replaces functools.partial for instruction dispatch.

    Stores func + up to 4 extra args as individual C fields (no tuple).
    cython.cast(InstructionSlot, slot).call() dispatches via C vtable,
    bypassing Python's __call__ protocol overhead.
    """
    _func  = cython.declare(object)
    _a0    = cython.declare(object)   # always the apu instance
    _a1    = cython.declare(object)
    _a2    = cython.declare(object)
    _a3    = cython.declare(object)
    _nargs = cython.declare(cython.int)

    def __init__(self, func, a0, a1=None, a2=None, a3=None):
        self._func  = func
        self._a0    = a0
        self._a1    = a1
        self._a2    = a2
        self._a3    = a3
        if a3 is not None:
            self._nargs = 4
        elif a2 is not None:
            self._nargs = 3
        elif a1 is not None:
            self._nargs = 2
        else:
            self._nargs = 1

    @cython.ccall
    def call(self):
        if self._nargs == 1:
            self._func(self._a0)
        elif self._nargs == 2:
            self._func(self._a0, self._a1)
        elif self._nargs == 3:
            self._func(self._a0, self._a1, self._a2)
        else:
            self._func(self._a0, self._a1, self._a2, self._a3)


@cython.cclass
class Timer:
    apu = cython.declare(object)
    frequency = cython.declare(cython.uint, visibility="public")
    stage0 = cython.declare(cython.uchar, visibility="public")
    stage1 = cython.declare(cython.uchar, visibility="public")
    stage2 = cython.declare(cython.uchar, visibility="public")
    stage3 = cython.declare(cython.uchar, visibility="public")
    stage3_shadow = cython.declare(cython.uchar, visibility="public")
    line = cython.declare(cython.bint, visibility="public")
    enable = cython.declare(cython.bint, visibility="public")
    target = cython.declare(cython.uchar, visibility="public")

    def __init__(self, apu: "Apu", frequency: int) -> None:
        self.apu = apu
        self.frequency = frequency
        self.stage0 = 0x00
        self.stage1 = 0x00
        self.stage2 = 0x00
        self.stage3 = 0x00
        self.stage3_shadow = 0x00
        self.line = False
        self.enable = False
        self.target = 0x00

    @cython.cfunc
    def step(self, clocks: cython.uint):
        # stage 0 increment
        self.stage0 = (self.stage0 + clocks) & 0xFF
        if self.stage0 < self.frequency:
            return
        self.stage0 = (self.stage0 - self.frequency) & 0xFF

        # stage 1 increment
        self.stage1 ^= 1
        self.syncronize_stage1()

    @cython.cfunc
    def syncronize_stage1(self):
        level: cython.bint = self.stage1
        if not self.apu.timers_enable:
            level = 0
        if self.apu.timers_disable:
            level = 0
        # only pulse on 1->0 transition
        if not self.lower(level):
            return

        # stage 2 increment
        if not self.enable:
            return
        self.stage2 = (self.stage2 + 1) & 0xFF
        if self.stage2 != self.target:
            return

        # stage 3 increment
        self.stage2 = 0
        self.stage3 = (self.stage3 + 1) & 0x0F

    @cython.cfunc
    def lower(self, level: cython.bint) -> cython.bint:
        if self.line and not level:
            self.line = False
            return True
        elif not self.line and level:
            self.line = True
        return False


@cython.cclass
class Apu:
    # Registers
    PC = cython.declare(cython.uint, visibility="public")
    A = cython.declare(cython.uchar, visibility="public")
    X = cython.declare(cython.uchar, visibility="public")
    Y = cython.declare(cython.uchar, visibility="public")
    S = cython.declare(cython.uchar, visibility="public")
    # Flags
    NF = cython.declare(cython.bint, visibility="public")
    VF = cython.declare(cython.bint, visibility="public")
    PF = cython.declare(cython.bint, visibility="public")
    BF = cython.declare(cython.bint, visibility="public")
    HF = cython.declare(cython.bint, visibility="public")
    IF = cython.declare(cython.bint, visibility="public")
    ZF = cython.declare(cython.bint, visibility="public")
    CF = cython.declare(cython.bint, visibility="public")
    # Timing
    timers = cython.declare(object, visibility="public")
    _last_synced_mc = cython.declare(cython.long, visibility="public")
    _ports_w_dirty = cython.declare(cython.bint, visibility="public")
    cycles = cython.declare(cython.uint, visibility="public")
    # Registers (raw storage)
    _control_register_raw = cython.declare(cython.uchar, visibility="public")
    dsp_register_address = cython.declare(cython.uchar, visibility="public")
    dsp_register_data = cython.declare(cython.uchar, visibility="public")
    auxio4 = cython.declare(cython.uchar, visibility="public")
    auxio5 = cython.declare(cython.uchar, visibility="public")
    ipl_rom_enable = cython.declare(cython.bint, visibility="public")
    # Test register ($F0) fields
    timers_disable = cython.declare(cython.bint, visibility="public")
    ram_writable = cython.declare(cython.bint, visibility="public")
    ram_disable = cython.declare(cython.bint, visibility="public")
    timers_enable = cython.declare(cython.bint, visibility="public")
    external_wait_states = cython.declare(cython.uchar, visibility="public")
    internal_wait_states = cython.declare(cython.uchar, visibility="public")
    # Debug
    address = cython.declare(cython.uint, visibility="public")
    data = cython.declare(cython.uint, visibility="public")
    breakpoint = cython.declare(object, visibility="public")
    print_debug = cython.declare(cython.bint, visibility="public")
    # Memory regions
    memory = cython.declare(object, visibility="public")
    ipl_rom = cython.declare(object, visibility="public")
    page_0 = cython.declare(object, visibility="public")
    page_1 = cython.declare(object, visibility="public")
    ports_r = cython.declare(object, visibility="public")
    ports_w = cython.declare(object, visibility="public")
    # Instruction dispatch
    instructions = cython.declare(object, visibility="public")
    debug_symbols = cython.declare(object, visibility="public")
    # Memory access tracing (None = disabled; set to [] in tests to capture accesses)
    _mem_log = cython.declare(object, visibility="public")
    # Instruction trace
    trace_enabled = cython.declare(cython.bint, visibility="public")
    trace_log = cython.declare(object, visibility="public")
    _disassembler = cython.declare(object, visibility="public")

    def __init__(self) -> None:
        self.reset_registers()
        self.allocate_memory()
        self.load_instructions()
        self._disassembler = SPC700Disassembler(self)

    def __str__(self) -> str:
        flags = [
            "N" if self.NF else "n",
            "V" if self.VF else "v",
            "P" if self.PF else "p",
            "B" if self.BF else "b",
            "H" if self.HF else "h",
            "I" if self.IF else "i",
            "Z" if self.ZF else "z",
            "C" if self.CF else "c",
        ]
        timers = ["1" if timer.enable else "0" for timer in self.timers]
        counters = [
            f"{timer.stage1}/{timer.stage2:02X}/{timer.stage3:02X}/{timer.target:02X}"
            for timer in self.timers
        ]
        return "A:{:02X} X:{:02X} Y:{:02X} S:{:02X} F:{} T:{} C:{}".format(
            self.A,
            self.X,
            self.Y,
            self.S,
            "".join(flags),
            ",".join(timers),
            ",".join(counters),
        )

    def reset_registers(self):
        # Registers
        self.PC = 0xFFC0  # Program Counter (16 bit)
        self.A =  0x00    # Accumulator (8 bit)
        self.X =  0x00    # X Index Register (8 bit)
        self.Y =  0x00    # Y Index Register (8 bit)
        self.S =  0xEF    # Stack Pointer (8 bit) - always on page 1

        # Flags stored in PSW Register
        self.NF = False  # Negative
        self.VF = False  # Overflow
        self.PF = False  # Direct page
        self.BF = False  # Break
        self.HF = False  # Half carry
        self.IF = False  # Interrupt enabled (unused)
        self.ZF = True   # Zero
        self.CF = False  # Carry

        self.timers = [Timer(self, 128), Timer(self, 128), Timer(self, 16)]

        # Catchup clock tracking: master clock value at last APU sync.
        # APU runs at ~1.024 MHz; 1 APU clock ≈ 21 master clocks (21477272/1024000).
        # Start 2 APU bus cycles ahead of master-clock 0 to model the SPC700 reset
        # vector fetch that Mesen performs (Spc::Reset -> ReadWord(ResetVector))
        # before any IPL ROM instruction runs.  Without this the APU trails by ~42 MC
        # and the SMW main-CPU↔APU handshake loop exits one iteration late.
        self._last_synced_mc: int = -(2 * 21477272 // 1024000)
        # Set when APU writes to ports_w; causes sync_to to yield so the CPU
        # can observe each intermediate port value before the APU runs further.
        self._ports_w_dirty: bool = False

        # Per-instruction cycle counter.  Reset at the top of fetch_and_execute;
        # incremented by every __getitem__, __setitem__, and idle() call so tests
        # can assert the total cycle count matches the reference data.
        self.cycles: int = 0

        self._control_register_raw = 0x80  # F1 raw written value (for readback)
        self.test_register = 0x0A  # F0 (write-only)
        self.control_register = 0x80  # F1 (write only)
        self.dsp_register_address = 0x00  # F2 (r/w)
        self.dsp_register_data = 0x00  # F3 (r/w)
        # self.timers = bytearray(3)  # FA/FB/FC (/w)
        # self.counters = bytearray(3)  # FD/FE/FF (r/)
        # $F8/$F9 AUXIO4/AUXIO5: general-purpose 8-bit R/W scratch registers
        self.auxio4 = 0
        self.auxio5 = 0

        # Control register 0xF1
        self.ipl_rom_enable = True

        # Debug stuff
        self.address = 0  # Last accessed address
        self.data = 0  # Last accessed data
        self.breakpoint = None
        self.print_debug = False
        self._mem_log = None
        self.trace_enabled = False
        self.trace_log = []

    def allocate_memory(self):
        # Init memory regions
        self.memory = bytearray(0xFFBF - 0x0200 + 1)

        # IPL ROM (boot code) - 64 bytes
        # fmt: off
        self.ipl_rom = bytes((
            0xCD,0xEF,0xBD,0xE8,0x00,0xC6,0x1D,0xD0,0xFC,0x8F,0xAA,0xF4,0x8F,0xBB,0xF5,0x78,
            0xCC,0xF4,0xD0,0xFB,0x2F,0x19,0xEB,0xF4,0xD0,0xFC,0x7E,0xF4,0xD0,0x0B,0xE4,0xF5,
            0xCB,0xF4,0xD7,0x00,0xFC,0xD0,0xF3,0xAB,0x01,0x10,0xEF,0x7E,0xF4,0x10,0xEB,0xBA,
            0xF6,0xDA,0x00,0xBA,0xF4,0xC4,0xF4,0xDD,0x5D,0xD0,0xDB,0x1F,0x00,0x00,0xC0,0xFF,
        ))
        # fmt: on

        self.page_0 = bytearray(0x00F0) # dont think this makes sense... needs checking
        self.page_1 = bytearray(0x0100)

        # The IO Port0-4 registers have separete memory for R/W
        self.ports_r = bytearray(4)  # APU reads from
        self.ports_w = bytearray(4)  # APU writes to

    def load_instructions(self):
        self.instructions: Any = [None] * 256
        self.debug_symbols: Any = [""] * 256
        for opcode, addr_mode, *args in INSTRUCTIONS:
            self.instructions[opcode] = InstructionSlot(addr_mode, self, *args)
            self.debug_symbols[opcode] = f"{addr_mode.__name__}"
            if args:
                if hasattr(args[0], "__name__"):
                    self.debug_symbols[opcode] += f" {args[0].__name__} {args[1:]}"
                else:
                    self.debug_symbols[opcode] += f" {args}"
            self.debug_symbols[opcode] = self.debug_symbols[opcode].ljust(30)

    @cython.ccall
    def idle(self):
        """One internal CPU cycle with no external memory access."""
        self.cycles += 1

    def load_program(self, data):
        """Used for testing only"""
        self.ipl_rom = data

    @cython.cfunc
    def _read(self, addr: cython.uint) -> cython.uint:
        self.cycles += 1
        result: cython.uint
        if addr <= 0x00EF:
            result = self.page_0[addr]
        elif addr == 0x00F0:
            result = self.test_register
        elif addr == 0x00F1:
            result = self.control_register
        elif addr == 0x00F2:
            result = self.dsp_register_address
        elif addr == 0x00F3:
            result = self.dsp_register_data
        elif addr <= 0x00F7:
            result = self.ports_r[addr - 0x00F4]
        elif addr == 0x00F8:
            result = self.auxio4
        elif addr == 0x00F9:
            result = self.auxio5
        elif addr <= 0x00FC:
            result = cython.cast(Timer, self.timers[addr - 0x00FA]).target
        elif addr <= 0x00FF:
            timer: Timer = cython.cast(Timer, self.timers[addr - 0x00FD])
            result = timer.stage3
            timer.stage3_shadow = result
            timer.stage3 = 0
        elif addr <= 0x01FF:
            result = self.page_1[addr - 0x0100]
        elif addr <= 0xFFBF:
            result = self.memory[addr - 0x0200]
        else:
            result = self.ipl_rom[addr - 0xFFC0]
        if self._mem_log is not None:
            self._mem_log.append((addr, result, "read"))
        return result

    @cython.cfunc
    def _write(self, addr: cython.uint, value: cython.uint):
        self.cycles += 1
        if self._mem_log is not None:
            self._mem_log.append((addr, value, "write"))
        if addr <= 0x00EF:
            self.page_0[addr] = value
        elif addr == 0x00F0:
            self.test_register = value
        elif addr == 0x00F1:
            self.control_register = value
        elif addr == 0x00F2:
            self.dsp_register_address = value
        elif addr == 0x00F3:
            self.dsp_register_data = value
        elif addr <= 0x00F7:
            # $F4-$F7 from SPC side: writing updates the SPC→CPU latch (ports_w).
            # The CPU→SPC latch (ports_r) is separate hardware; do NOT mirror — the
            # SPC reads back whatever the main CPU last wrote, not its own writes.
            self.ports_w[addr - 0x00F4] = value
            self._ports_w_dirty = True
        elif addr == 0x00F8:
            self.auxio4 = value
        elif addr == 0x00F9:
            self.auxio5 = value
        elif addr <= 0x00FC:
            cython.cast(Timer, self.timers[addr - 0x00FA]).target = value
        elif addr <= 0x00FF:
            timer: Timer = cython.cast(Timer, self.timers[addr - 0x00FD])
            timer.stage3 = value
            timer.stage3_shadow = value
        elif addr <= 0x01FF:
            self.page_1[addr - 0x0100] = value
        elif addr <= 0xFFBF:
            self.memory[addr - 0x0200] = value
        elif addr <= 0xFFFF:
            if isinstance(self.ipl_rom, bytearray):
                self.ipl_rom[addr - 0xFFC0] = value
        else:
            raise NotImplementedError(f"Write to unmapped APU address 0x{addr:04X}")

    @cython.ccall
    def write(self, addr: cython.uint, data: cython.uint):
        self._write(addr, data)

    @cython.ccall
    def read(self, addr: cython.uint) -> cython.uint:
        return self._read(addr)

    @cython.ccall
    def store(self, addr: cython.uint, data: cython.uint):
        self._write((self.PF << 8) | (addr & 0xFF), data)

    @cython.ccall
    def load(self, addr: cython.uint) -> cython.uint:
        return self._read((self.PF << 8) | (addr & 0xFF))

    @cython.ccall
    def pull(self) -> cython.uint:
        self.S = (self.S + 1) & 0xFF
        return self._read(0x100 | self.S)

    @cython.ccall
    def push(self, data: cython.uint):
        self._write(0x100 | self.S, data & 0xFF)
        self.S = (self.S - 1) & 0xFF

    @cython.ccall
    def fetch(self) -> cython.uint:
        data: cython.uint = self._read(self.PC)
        self.PC = (self.PC + 1) & 0xFFFF
        return data

    def _format_trace(self, pc: int, opcode: int) -> str:
        disasm = self._disassembler.disassemble(pc)
        flags = (
            ("N" if self.NF else "n")
            + ("V" if self.VF else "v")
            + ("P" if self.PF else "p")
            + ("B" if self.BF else "b")
            + ("H" if self.HF else "h")
            + ("I" if self.IF else "i")
            + ("Z" if self.ZF else "z")
            + ("C" if self.CF else "c")
        )
        return "{:<24} A:{:02X} X:{:02X} Y:{:02X} S:{:02X} PSW:{:02X} {}".format(
            disasm,
            self.A, self.X, self.Y, self.S,
            self.PSW,
            flags,
        )

    @cython.ccall
    def fetch_and_execute(self):
        self.cycles = 0
        pc = self.PC
        opcode = self.fetch()
        if self.trace_enabled:
            line = self._format_trace(pc, opcode)
            self.trace_log.append(line)
            self.trace_log = self.trace_log[-10:]
        if self.print_debug:
            print("\033[93mAPU 0x{:04X} 0x{:02X} {} [{:04X}] [{:02X}] {}\033[0m".format(
                self.PC - 1, opcode, self.debug_symbols[opcode],
                self.address, self.data, str(self),
            ))
        cython.cast(InstructionSlot, self.instructions[opcode]).call()

    # Approximate master-clock-to-APU-clock ratio (integer division)
    _APU_MC_PER_CLOCK: int = 21  # 21477272 / 1024000 ≈ 20.979 (integer-approx; exact ratio used in sync_to)
    _APU_MC_NUM: int = 21477272
    _APU_MC_DEN: int = 1024000

    def sync_to(self, master_clock: int) -> None:
        """Catch the APU up to the given master clock value.

        Called lazily whenever the CPU reads or writes an APU I/O port, ensuring
        the APU has run up to that point in time before the port value is sampled.

        Stops early when the APU writes to ports_w so the CPU always observes
        each intermediate value rather than only seeing the final state after a
        large batch of ticks.  The remaining time is picked up on the next call.
        """
        elapsed = master_clock - self._last_synced_mc
        if elapsed <= 0:
            return
        # Target APU clock cycles to run using the exact ratio (21477272/1024000)
        # rather than integer 21 — over the SPC700 IPL ROM boot (~2400 APU cycles)
        # the truncation to 21 accumulates ~60 MC of drift, enough to skew the
        # main-CPU↔APU handshake by a full CPU loop iteration (see SMW boot).
        target_apu_clocks = elapsed * self._APU_MC_DEN // self._APU_MC_NUM
        self._ports_w_dirty = False
        apu_clocks_run = 0
        while apu_clocks_run < target_apu_clocks:
            self.fetch_and_execute()
            self.step_timers(self.cycles)
            apu_clocks_run += self.cycles
            if self._ports_w_dirty:
                # The APU wrote a port — advance _last_synced_mc by only what
                # we've run, even if it overshoots mc (the APU has "pre-run").
                self._last_synced_mc += apu_clocks_run * self._APU_MC_NUM // self._APU_MC_DEN
                return
        self._last_synced_mc += apu_clocks_run * self._APU_MC_NUM // self._APU_MC_DEN

    @cython.ccall
    def step_timers(self, clocks: cython.uint):
        cython.cast(Timer, self.timers[0]).step(clocks)
        cython.cast(Timer, self.timers[1]).step(clocks)
        cython.cast(Timer, self.timers[2]).step(clocks)

    def __getitem__(self, addr: int) -> int:
        # $F4-$F7: external read returns the SPC output latch (ports_w),
        # since that is the value the SPC last wrote there.
        if 0xF4 <= addr <= 0xF7:
            return self.ports_w[addr - 0xF4]
        return self._read(addr)

    def __setitem__(self, addr: int, value: int) -> None:
        # $F4-$F7: external write sets both latches so that the SPC reads the
        # initialized value back (ports_r) and the verify check also passes
        # (ports_w).  In actual emulation _write/_read keep them split; this
        # path is only used from tests.
        if 0xF4 <= addr <= 0xF7:
            self.ports_r[addr - 0xF4] = value
            self.ports_w[addr - 0xF4] = value
            return
        self._write(addr, value)

    @property
    def PSW(self) -> int:
        return (0
            | self.NF << 7
            | self.VF << 6
            | self.PF << 5
            | self.BF << 4
            | self.HF << 3
            | self.IF << 2
            | self.ZF << 1
            | self.CF << 0
        )

    @PSW.setter
    def PSW(self, value: int) -> None:
        self.NF = bool(value & 0x80)
        self.VF = bool(value & 0x40)
        self.PF = bool(value & 0x20)
        self.BF = bool(value & 0x10)
        self.HF = bool(value & 0x08)
        self.IF = bool(value & 0x04)
        self.ZF = bool(value & 0x02)
        self.CF = bool(value & 0x01)

    @property
    def YA(self) -> int:
        return self.Y << 8 | self.A

    @YA.setter
    def YA(self, data: int) -> None:
        self.A = data >> 0 & 0xFF
        self.Y = data >> 8 & 0xFF

    @property
    def test_register(self) -> int:
        return (
            (int(self.timers_disable) << 0)
            | (int(self.ram_writable) << 1)
            | (int(self.ram_disable) << 2)
            | (int(self.timers_enable) << 3)
            | (self.external_wait_states << 4)
            | (self.internal_wait_states << 6)
        )

    @test_register.setter
    def test_register(self, data: int) -> None:
        if self.PF:
            return  # writes only valid when P flag is clear

        self.timers_disable = bool(data >> 0 & 1)
        self.ram_writable = bool(data >> 1 & 1)
        self.ram_disable = bool(data >> 2 & 1)
        self.timers_enable = bool(data >> 3 & 1)
        self.external_wait_states = int(data >> 4 & 3)
        self.internal_wait_states = int(data >> 6 & 3)

        cython.cast(Timer, self.timers[0]).syncronize_stage1()
        cython.cast(Timer, self.timers[1]).syncronize_stage1()
        cython.cast(Timer, self.timers[2]).syncronize_stage1()

    @property
    def control_register(self) -> int:
        return self._control_register_raw

    @control_register.setter
    def control_register(self, data: int) -> None:
        self._control_register_raw = data
        # 0->1 transistion resets timers
        timer0: Timer = cython.cast(Timer, self.timers[0])
        timer0_enable: cython.bint = timer0.enable
        timer0_enable_flag: cython.bint = bool(data & 0x01)
        timer0.enable = timer0_enable_flag
        if timer0_enable_flag and not timer0_enable:
            timer0.stage2 = 0
            timer0.stage3 = 0

        timer1: Timer = cython.cast(Timer, self.timers[1])
        timer1_enable: cython.bint = timer1.enable
        timer1_enable_flag: cython.bint = bool(data & 0x02)
        timer1.enable = timer1_enable_flag
        if timer1_enable_flag and not timer1_enable:
            timer1.stage2 = 0
            timer1.stage3 = 0

        timer2: Timer = cython.cast(Timer, self.timers[2])
        timer2_enable: cython.bint = timer2.enable
        timer2_enable_flag: cython.bint = bool(data & 0x04)
        timer2.enable = timer2_enable_flag
        if timer2_enable_flag and not timer2_enable:
            timer2.stage2 = 0
            timer2.stage3 = 0

        if data & 0x10:  # reset CPU→APU input ports 0/1 (ports_r only)
            self.ports_r[0] = 0x00
            self.ports_r[1] = 0x00

        if data & 0x20:  # reset CPU→APU input ports 2/3 (ports_r only)
            self.ports_r[2] = 0x00
            self.ports_r[3] = 0x00

        self.ipl_rom_enable = bool(data & 0x80)
