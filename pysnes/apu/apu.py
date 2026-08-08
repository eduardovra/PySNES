from typing import Any

from .dsp import Dsp
from .spc700.disassembler import SPC700Disassembler
from .spc700.instructions_spc700 import INSTRUCTIONS


class InstructionSlot:
    """Replaces functools.partial for instruction dispatch.

    Stores func + up to 4 extra args as individual C fields (no tuple).
    slot.call() dispatches via C vtable,
    bypassing Python's __call__ protocol overhead.
    """

    def __init__(self, func, a0, a1=None, a2=None, a3=None):
        self._func = func
        self._a0 = a0
        self._a1 = a1
        self._a2 = a2
        self._a3 = a3
        if a3 is not None:
            self._nargs = 4
        elif a2 is not None:
            self._nargs = 3
        elif a1 is not None:
            self._nargs = 2
        else:
            self._nargs = 1

    def call(self):
        if self._nargs == 1:
            self._func(self._a0)
        elif self._nargs == 2:
            self._func(self._a0, self._a1)
        elif self._nargs == 3:
            self._func(self._a0, self._a1, self._a2)
        else:
            self._func(self._a0, self._a1, self._a2, self._a3)


class Timer:
    def __init__(self, apu: "Apu", frequency: int) -> None:
        self.apu = apu
        self.frequency = frequency
        self.stage0 = 0x00
        self.stage2 = 0x00
        self.stage3 = 0x00
        self.stage3_shadow = 0x00
        self.enable = False
        self.target = 0x00

    _STATE_FIELDS = (
        "frequency",
        "stage0",
        "stage2",
        "stage3",
        "stage3_shadow",
        "enable",
        "target",
    )

    def dump_state(self) -> dict:
        return {f: getattr(self, f) for f in self._STATE_FIELDS}

    def load_state(self, d: dict) -> None:
        for f in self._STATE_FIELDS:
            setattr(self, f, d[f])

    def step(self, clocks: int) -> None:
        self.stage0 = (self.stage0 + clocks) & 0xFF
        if self.stage0 < self.frequency:
            return
        self.stage0 = (self.stage0 - self.frequency) & 0xFF

        if not self.enable:
            return
        if not self.apu.timers_enable or self.apu.timers_disable:
            return

        self.stage2 = (self.stage2 + 1) & 0xFF
        if self.stage2 != self.target:
            return

        self.stage2 = 0
        self.stage3 = (self.stage3 + 1) & 0x0F


class Apu:
    # Registers Flags Timing Registers (raw storage) Test register ($F0) fields
    # Debug Memory regions Instruction dispatch Memory access tracing (None =
    # disabled; set to [] in tests to capture accesses) Flat I/O mode: when
    # True, reads/writes to $F0-$FC bypass I/O routing and use page_0 directly.
    # Set by the single-step test harness so that CPU unit tests see a simple
    # flat-RAM model instead of DSP/port indirection. Instruction trace

    def __init__(self) -> None:
        self.reset_registers()
        self.allocate_memory()
        self.load_instructions()
        self._disassembler = SPC700Disassembler(self)
        self.dsp = Dsp(self.read_ram)

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
            f"{timer.stage2:02X}/{timer.stage3:02X}/{timer.target:02X}"
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
        self.A = 0x00  # Accumulator (8 bit)
        self.X = 0x00  # X Index Register (8 bit)
        self.Y = 0x00  # Y Index Register (8 bit)
        self.S = 0xEF  # Stack Pointer (8 bit) - always on page 1

        # Flags stored in PSW Register
        self.NF = False  # Negative
        self.VF = False  # Overflow
        self.PF = False  # Direct page
        self.BF = False  # Break
        self.HF = False  # Half carry
        self.IF = False  # Interrupt enabled (unused)
        self.ZF = True  # Zero
        self.CF = False  # Carry

        self.timers = [Timer(self, 128), Timer(self, 128), Timer(self, 16)]

        # Catchup clock tracking: master clock value at last APU sync. APU runs
        # at ~1.024 MHz; 1 APU clock ≈ 21 master clocks (21477272/1024000).
        # Start 2 APU bus cycles ahead of master-clock 0 to model the SPC700
        # reset vector fetch that Mesen performs (Spc::Reset ->
        # ReadWord(ResetVector)) before any IPL ROM instruction runs.  Without
        # this the APU trails by ~42 MC and the SMW main-CPU↔APU handshake loop
        # exits one iteration late.
        self._last_synced_mc: int = -(2 * 21477272 // 1024000)
        # Fixed-point remainder for the APU cycle budget (in units of MC_DEN).
        # Avoids lossy MC↔APU-cycle round-trips in sync_to.
        self._apu_mc_frac: int = 0

        # Per-instruction cycle counter.  Reset at the top of fetch_and_execute;
        # incremented by every read_external, write_external, and idle() call so
        # tests can assert the total cycle count matches the reference data.
        self.cycles: int = 0

        self._control_register_raw = 0x80  # F1 raw written value (for readback)
        self.test_register = 0x0A  # F0 (write-only)
        self.control_register = 0x80  # F1 (write only)
        self.dsp_register_address = 0x00  # F2 (r/w)
        self.dsp_register_data = 0x00  # F3 (r/w)
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
        self._io_flat = False
        self.trace_enabled = False
        self.trace_log = []

        if hasattr(self, "dsp") and self.dsp is not None:
            self.dsp = Dsp(self.read_ram)

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

        # 0x00–0xFF; upper 16 bytes used by _io_flat mode
        self.page_0 = bytearray(0x0100)
        self.page_1 = bytearray(0x0100)

        # The IO Port0-4 registers have separete memory for R/W
        self.ports_r = bytearray(4)  # APU reads from
        self.ports_w = bytearray(4)  # APU writes to

    _SCALAR_STATE = (
        "PC",
        "A",
        "X",
        "Y",
        "S",
        "NF",
        "VF",
        "PF",
        "BF",
        "HF",
        "IF",
        "ZF",
        "CF",
        "_last_synced_mc",
        "_apu_mc_frac",
        "cycles",
        "_control_register_raw",
        "dsp_register_address",
        "dsp_register_data",
        "auxio4",
        "auxio5",
        "ipl_rom_enable",
        "timers_disable",
        "ram_writable",
        "ram_disable",
        "timers_enable",
        "external_wait_states",
        "internal_wait_states",
    )

    def dump_state(self) -> dict:
        return {
            "memory": bytes(self.memory),
            "page_0": bytes(self.page_0),
            "page_1": bytes(self.page_1),
            "ports_r": bytes(self.ports_r),
            "ports_w": bytes(self.ports_w),
            "scalars": {f: getattr(self, f) for f in self._SCALAR_STATE},
            "timers": [t.dump_state() for t in self.timers],
        }

    def load_state(self, d: dict) -> None:
        self.memory[:] = d["memory"]
        self.page_0[: len(d["page_0"])] = d["page_0"]
        self.page_1[:] = d["page_1"]
        self.ports_r[:] = d["ports_r"]
        self.ports_w[:] = d["ports_w"]
        for f, v in d["scalars"].items():
            setattr(self, f, v)
        for t, ts in zip(self.timers, d["timers"], strict=True):
            t.load_state(ts)

    def load_instructions(self):
        self.instructions: Any = [None] * 256
        self.debug_symbols: Any = [""] * 256
        for opcode, addr_mode, *args in INSTRUCTIONS:
            self.instructions[opcode] = InstructionSlot(addr_mode, self, *args)
            self.debug_symbols[opcode] = f"{addr_mode.__name__}"
            if args:
                if hasattr(args[0], "__name__"):
                    self.debug_symbols[opcode] += (
                        f" {args[0].__name__} {args[1:]}"
                    )
                else:
                    self.debug_symbols[opcode] += f" {args}"
            self.debug_symbols[opcode] = self.debug_symbols[opcode].ljust(30)

    def idle(self):
        """One internal CPU cycle with no external memory access."""
        self.cycles += 1

    def generate_audio_frame(self, n_samples: int):
        """Generate n_samples of 16-bit stereo audio. Returns numpy array shape
        (n_samples, 2)."""
        return self.dsp.generate_samples(n_samples)

    def read_ram(self, addr: int) -> int:
        """Read APU RAM for DSP use — no cycle increment, no I/O
        side-effects."""
        addr &= 0xFFFF
        if addr <= 0x00EF:
            return self.page_0[addr]
        if addr <= 0x00FF:
            return 0  # I/O register range — BRR data never lives here
        if addr <= 0x01FF:
            return self.page_1[addr - 0x0100]
        if addr <= 0xFFBF:
            return self.memory[addr - 0x0200]
        return self.ipl_rom[addr - 0xFFC0]

    def load_program(self, data):
        """Used for testing only"""
        self.ipl_rom = data

    def load_spc(self, spc) -> None:
        """Load SPC700 state from a parsed SpcFile, bypassing the IPL boot
        sequence."""
        ram = spc.ram

        # Page 0 ($0000-$00EF) — general RAM
        self.page_0[:0x00F0] = ram[0x0000:0x00F0]
        # I/O register range $00F0-$00FF is not stored in RAM; skip it.
        # Page 1 ($0100-$01FF)
        self.page_1[:] = ram[0x0100:0x0200]
        # Main RAM ($0200-$FFBF)
        self.memory[:] = ram[0x0200:0xFFC0]
        # Extra RAM overlays IPL ROM area ($FFC0-$FFFF)
        self.ipl_rom = bytearray(spc.extra_ram)

        # CPU registers
        self.PC = spc.pc
        self.A = spc.a
        self.X = spc.x
        self.Y = spc.y
        self.PSW = spc.psw
        self.S = spc.sp

        # DSP registers
        for addr, val in enumerate(spc.dsp_regs):
            self.dsp.write_register(addr, val)

        self.auxio4 = ram[0x00F8]
        self.auxio5 = ram[0x00F9]
        self.dsp_register_address = ram[0x00F2]

        # Timer targets ($FA-$FC) live in the I/O region skipped above — restore
        # explicitly.
        for i in range(3):
            self.timers[i].target = ram[0x00FA + i]

        # Control register enables/disables timers and may reset port latches
        # (bits 4/5). Set it before restoring ports_r so the port reset doesn't
        # clobber the saved values.
        self.control_register = ram[0x00F1]
        self.ipl_rom_enable = False

        # Restore ports_r/$F4-$F7 after control_register write (bits 4/5 would
        # clear them).
        for i in range(4):
            self.ports_r[i] = ram[0x00F4 + i]
            self.ports_w[i] = ram[0x00F4 + i]

    def _read(self, addr: int) -> int:
        self.cycles += 1
        if addr <= 0x00EF or addr <= 0x00FC and self._io_flat:
            result = self.page_0[addr]
        elif addr == 0x00F0:
            result = self.test_register
        elif addr == 0x00F1:
            result = self.control_register
        elif addr == 0x00F2:
            result = self.dsp_register_address
        elif addr == 0x00F3:
            result = self.dsp.read_register(self.dsp_register_address)
            self.dsp_register_data = result
        elif addr <= 0x00F7:
            result = self.ports_r[addr - 0x00F4]
        elif addr == 0x00F8:
            result = self.auxio4
        elif addr == 0x00F9:
            result = self.auxio5
        elif addr <= 0x00FC:
            result = self.timers[addr - 0x00FA].target
        elif addr <= 0x00FF:
            timer: Timer = self.timers[addr - 0x00FD]
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

    def _write(self, addr: int, value: int) -> None:
        self.cycles += 1
        if self._mem_log is not None:
            self._mem_log.append((addr, value, "write"))
        if addr <= 0x00EF or addr <= 0x00FC and self._io_flat:
            self.page_0[addr] = value
        elif addr == 0x00F0:
            self.test_register = value
        elif addr == 0x00F1:
            self.control_register = value
        elif addr == 0x00F2:
            self.dsp_register_address = value
        elif addr == 0x00F3:
            self.dsp_register_data = value
            self.dsp.write_register(self.dsp_register_address, value)
        elif addr <= 0x00F7:
            # $F4-$F7 from SPC side: writing updates the SPC→CPU latch
            # (ports_w). The CPU→SPC latch (ports_r) is separate hardware; do
            # NOT mirror — the SPC reads back whatever the main CPU last wrote,
            # not its own writes.
            self.ports_w[addr - 0x00F4] = value
        elif addr == 0x00F8:
            self.auxio4 = value
        elif addr == 0x00F9:
            self.auxio5 = value
        elif addr <= 0x00FC:
            self.timers[addr - 0x00FA].target = value
        elif addr <= 0x00FF:
            timer: Timer = self.timers[addr - 0x00FD]
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
            raise NotImplementedError(
                f"Write to unmapped APU address 0x{addr:04X}"
            )

    def write(self, addr: int, data: int) -> None:
        self._write(addr, data)

    def read(self, addr: int) -> int:
        return self._read(addr)

    def store(self, addr: int, data: int) -> None:
        self._write((self.PF << 8) | (addr & 0xFF), data)

    def load(self, addr: int) -> int:
        return self._read((self.PF << 8) | (addr & 0xFF))

    def pull(self) -> int:
        self.S = (self.S + 1) & 0xFF
        return self._read(0x100 | self.S)

    def push(self, data: int) -> None:
        self._write(0x100 | self.S, data & 0xFF)
        self.S = (self.S - 1) & 0xFF

    def fetch(self) -> int:
        data = self._read(self.PC)
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
        return (
            f"{disasm:<24} A:{self.A:02X} X:{self.X:02X} "
            f"Y:{self.Y:02X} S:{self.S:02X} PSW:{self.PSW:02X} {flags}"
        )

    def fetch_and_execute(self):
        self.cycles = 0
        pc = self.PC
        opcode = self.fetch()
        if self.trace_enabled:
            line = self._format_trace(pc, opcode)
            self.trace_log.append(line)
            self.trace_log = self.trace_log[-10:]
        if self.print_debug:
            print(
                f"\033[93mAPU 0x{self.PC - 1:04X} 0x{opcode:02X} "
                f"{self.debug_symbols[opcode]} [{self.address:04X}] "
                f"[{self.data:02X}] {str(self)}\033[0m"
            )
        self.instructions[opcode].call()

    # Approximate master-clock-to-APU-clock ratio (integer division)
    # 21477272 / 1024000 ≈ 20.979 (integer-approx; exact ratio used in sync_to)
    _APU_MC_PER_CLOCK: int = 21
    _APU_MC_NUM: int = 21477272
    _APU_MC_DEN: int = 1024000

    def sync_to(self, master_clock: int) -> None:
        """Catch the APU up to the given master clock value.

        Called lazily whenever the CPU reads or writes an APU I/O port, ensuring
        the APU has run up to that point in time before the port value is
        sampled.

        Each call drains the full budget up to master_clock so the CPU observes
        the port value as of its access time (the last write at or before now).
        """
        elapsed = master_clock - self._last_synced_mc
        if elapsed <= 0:
            return
        self._last_synced_mc = master_clock

        # Fixed-point accumulator: add elapsed MC scaled by MC_DEN so we never
        # lose fractional cycles across calls.  One APU cycle costs MC_NUM
        # units.
        self._apu_mc_frac += elapsed * self._APU_MC_DEN
        while self._apu_mc_frac >= self._APU_MC_NUM:
            self.fetch_and_execute()
            self.step_timers(self.cycles)
            self._apu_mc_frac -= self.cycles * self._APU_MC_NUM

    def step_timers(self, clocks: int) -> None:
        self.timers[0].step(clocks)
        self.timers[1].step(clocks)
        self.timers[2].step(clocks)

    def read_external(self, addr: int) -> int:
        # $F4-$F7: external read returns the SPC output latch (ports_w).
        # In flat-IO mode the whole $F0-$FC range uses page_0, so fall
        # through to _read() which already handles that.
        if 0xF4 <= addr <= 0xF7 and not self._io_flat:
            return self.ports_w[addr - 0xF4]
        return self._read(addr)

    def write_external(self, addr: int, value: int) -> None:
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
        return (
            0
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

    @property
    def control_register(self) -> int:
        return self._control_register_raw

    @control_register.setter
    def control_register(self, data: int) -> None:
        self._control_register_raw = data
        # 0->1 transistion resets timers
        timer0: Timer = self.timers[0]
        timer0_enable = timer0.enable
        timer0_enable_flag = bool(data & 0x01)
        timer0.enable = timer0_enable_flag
        if timer0_enable_flag and not timer0_enable:
            timer0.stage2 = 0
            timer0.stage3 = 0

        timer1: Timer = self.timers[1]
        timer1_enable = timer1.enable
        timer1_enable_flag = bool(data & 0x02)
        timer1.enable = timer1_enable_flag
        if timer1_enable_flag and not timer1_enable:
            timer1.stage2 = 0
            timer1.stage3 = 0

        timer2: Timer = self.timers[2]
        timer2_enable = timer2.enable
        timer2_enable_flag = bool(data & 0x04)
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
