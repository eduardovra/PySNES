from functools import partial
from typing import Any

from ..register_types import Reg8, Reg16

from .spc700.instructions_spc700 import INSTRUCTIONS


class Timer:
    TIMER_WAIT_STATES = (2, 4, 8, 16)  # Clock dividers

    def __init__(self, apu: "Apu", frequency: int) -> None:
        self.apu = apu
        self.frequency = frequency
        self.stage0 = 0x00  # 8 bits
        self.stage1 = 0x00  # 8 bits
        self.stage2 = 0x00  # 8 bits
        self.stage3 = 0x0  # 4 bits

        self.line = False
        self.enable = False
        self.target = 0x00  # 8 bits

    def step(self, _clocks: int) -> None:
        wait_states = self.apu.internal_wait_states  # TODO can be external
        clocks = self.TIMER_WAIT_STATES[wait_states]
        clocks = 128

        # stage 0 increment
        self.stage0 = (self.stage0 + clocks) & 0xFF
        if self.stage0 < self.frequency:
            return
        self.stage0 = (self.stage0 - self.frequency) & 0xFF

        # stage 1 increment
        self.stage1 ^= 1  # Toogle
        self.syncronize_stage1()

    def syncronize_stage1(self) -> None:
        level = self.stage1
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

    def lower(self, level) -> bool:
        if self.line and not level:
            self.line = False
            return True
        elif not self.line and level:
            self.line = True
        return False


class Apu:

    def __init__(self) -> None:
        self.reset_registers()
        self.allocate_memory()
        self.load_instructions()

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
        self.S =  0xEF    # Stack Pointer (8 bit) - always on page 1 --> TODO first version used 0x1EF

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

        # Catchup clock tracking: master clock value at last APU sync
        # APU runs at ~1.024 MHz; 1 APU clock ≈ 21 master clocks (21477272/1024000)
        self._last_synced_mc: int = 0
        # Set when APU writes to ports_w; causes sync_to to yield so the CPU
        # can observe each intermediate port value before the APU runs further.
        self._ports_w_dirty: bool = False

        # Per-instruction cycle counter.  Reset at the top of fetch_and_execute;
        # incremented by every __getitem__, __setitem__, and idle() call so tests
        # can assert the total cycle count matches the reference data.
        self.cycles: int = 0

        self.test_register = 0x0A  # F0 (write-only)
        self.control_register = 0x80  # F1 (write only)
        self.dsp_register_address = 0x00  # F2 (r/w)
        self.dsp_register_data = 0x00  # F3 (r/w)
        # self.timers = bytearray(3)  # FA/FB/FC (/w)
        # self.counters = bytearray(3)  # FD/FE/FF (r/)
        self.f8 = 0  # TODO don't remember what this is
        self.f9 = 0  # TODO don't remember what this is

        # Control register 0xF1
        self.ipl_rom_enable = True

        # Debug stuff
        self.address = 0  # Last accessed address
        self.data = 0  # Last accessed data
        self.breakpoint = None
        self.print_debug = False

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
            self.instructions[opcode] = partial(addr_mode, self, *args)
            self.debug_symbols[opcode] = f"{addr_mode.__name__}"
            if args:
                if hasattr(args[0], "__name__"):
                    self.debug_symbols[opcode] += f" {args[0].__name__} {args[1:]}"
                else:
                    self.debug_symbols[opcode] += f" {args}"
            self.debug_symbols[opcode] = self.debug_symbols[opcode].ljust(30)

    def idle(self) -> None:
        """One internal CPU cycle with no external memory access."""
        self.cycles += 1

    def load_program(self, data):
        """Used for testing only"""
        self.ipl_rom = data

    def write(self, addr, data):
        self[addr] = data

    def read(self, addr):
        return self[addr]

    def store(self, addr, data):
        self[(self.PF << 8) | (addr & 0xFF)] = data

    def load(self, addr):
        return self[(self.PF << 8) | (addr & 0xFF)]

    def pull(self):
        self.S = (self.S + 1) & 0xFF
        return self.read(0x100 | self.S)

    def push(self, data):
        self.write(0x100 | self.S, data & 0xFF)
        self.S = (self.S - 1) & 0xFF

    def fetch(self):
        data = self.read(self.PC)
        assert isinstance(data, int) and 0 <= data <= 0xFF
        self.PC = (self.PC + 1) & 0xFFFF
        return data

    def fetch_and_execute(self):
        self.cycles = 0
        opcode = self.fetch()

        debug_str = "APU 0x{:04X} 0x{:02X} {}".format(
            self.PC - 1,
            opcode,
            self.debug_symbols[opcode],
        )
        apu_str = str(self)

        instruction = self.instructions[opcode]

        try:
            instruction()
        except:
            if not self.print_debug:
                print("\033[93m{} [{:04X}] [{:02X}] {}\033[0m".format(
                        debug_str,
                        self.address,
                        self.data,
                        apu_str,
                    ))
            raise
        finally:
            if self.print_debug:
                print("\033[93m{} [{:04X}] [{:02X}] {}\033[0m".format(
                    debug_str,
                    self.address,
                    self.data,
                    apu_str,
                ))

    # Approximate master-clock-to-APU-clock ratio (integer division)
    _APU_MC_PER_CLOCK: int = 21  # 21477272 / 1024000 ≈ 20.979

    def sync_to(self, master_clock: int) -> None:
        """Catch the APU up to the given master clock value.

        Called lazily whenever the CPU reads or writes an APU I/O port, ensuring
        the APU has run up to that point in time before the port value is sampled.

        Stops early when the APU writes to ports_w so the CPU always observes
        each intermediate value rather than only seeing the final state after a
        large batch of ticks.  The remaining time is picked up on the next call.
        """
        elapsed = master_clock - self._last_synced_mc
        apu_ticks = elapsed // self._APU_MC_PER_CLOCK
        self._ports_w_dirty = False
        for i in range(apu_ticks):
            self.step_timers(1)
            self.fetch_and_execute()
            if self._ports_w_dirty:
                self._last_synced_mc += (i + 1) * self._APU_MC_PER_CLOCK
                return
        self._last_synced_mc += apu_ticks * self._APU_MC_PER_CLOCK

    def step_timers(self, clocks: int) -> None:
        for timer in self.timers:
            timer.step(clocks)

    def __getitem__(self, addr: int) -> int:
        self.cycles += 1

        # if 0xF0 <= addr <= 0xF3:
        #    print(f"!!! Reading register {hex(addr)}")

        if 0x0000 <= addr <= 0x00EF:
            return self.page_0[addr]
        elif addr == 0x00F0:
            return self.test_register
        elif addr == 0x00F1:
            return self.control_register
        elif addr == 0x00F2:
            return self.dsp_register_address
        elif addr == 0x00F3:
            return self.dsp_register_data
        elif 0x00F4 <= addr <= 0x00F7:
            # print(f"  APU read [{hex(addr)}] ==> {hex(self.ports_r[addr - 0x00F4])}")
            return self.ports_r[addr - 0x00F4]
        elif addr == 0x00F8:
            return self.f8
        elif addr == 0x00F9:
            return self.f9
        elif 0x00FA <= addr <= 0x00FC:
            return 0  # TODO handle write only access
        elif 0x00FD <= addr <= 0x00FF:
            timer = self.timers[addr - 0x00FD]
            data = timer.stage3
            timer.stage3 = 0
            return data
        elif 0x0100 <= addr <= 0x01FF:
            return self.page_1[addr - 0x0100]
        elif 0x0200 <= addr <= 0xFFBF:
            return self.memory[addr - 0x0200]
        elif 0xFFC0 <= addr <= 0xFFFF:
            return self.ipl_rom[addr - 0xFFC0]

        raise RuntimeError(
            "Error reading unmamped memory region: 0x{:04X}".format(addr)
        )

    def __setitem__(self, addr: int, value: int) -> None:
        self.cycles += 1
        assert isinstance(addr, int)
        assert isinstance(value, int)
        assert 0x00 <= value <= 0xFF, f"Attemped to write value bigger than 1 byte: {hex(value)}"

        # if 0xF0 <= addr <= 0xF3:
        #    print(f"!!! Writing register {hex(addr)} <== {hex(value)}")

        if 0x0000 <= addr <= 0x00EF:
            self.page_0[addr] = value
        elif addr == 0x00F0:
            self.test_register = value
        elif addr == 0x00F1:
            self.control_register = value
        elif addr == 0x00F2:
            self.dsp_register_address = value
        elif addr == 0x00F3:
            self.dsp_register_data = value
        elif 0x00F4 <= addr <= 0x00F7:
            self.ports_w[addr - 0x00F4] = value
            self._ports_w_dirty = True
        elif addr == 0x00F8:
            self.f8 = value
        elif addr == 0x00F9:
            self.f9 = value
        elif 0x00FA <= addr <= 0x00FC:
            timer = self.timers[addr - 0x00FA]
            timer.target = value
        elif 0x00FD <= addr <= 0x00FF:
            self.timers[addr - 0x00FD].stage3 = value
        elif 0x0100 <= addr <= 0x01FF:
            self.page_1[addr - 0x0100] = value
        elif 0x0200 <= addr <= 0xFFBF:
            # print(f"[{hex(addr)}] <== {hex(value)}")
            self.memory[addr - 0x0200] = value
        else:
            print(
                "Error writting unmamped memory region: 0x{:04X} <== 0x{:04X}".format(
                    addr, value
                )
            )

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

        for timer in self.timers:
            timer.syncronize_stage1()

    @property
    def control_register(self) -> int:
        return 0x00  # Write only register

    @control_register.setter
    def control_register(self, data: int) -> None:
        # 0->1 transistion resets timers
        timer0 = self.timers[0]
        timer0_enable = timer0.enable
        timer0_enable_flag = bool(data & 0x01)
        timer0.enable = timer0_enable_flag
        if timer0_enable_flag and not timer0_enable:
            timer0.stage2 = 0
            timer0.stage3 = 0

        timer1 = self.timers[1]
        timer1_enable = timer1.enable
        timer1_enable_flag = bool(data & 0x02)
        timer1.enable = timer1_enable_flag
        if timer1_enable_flag and not timer1_enable:
            timer1.stage2 = 0
            timer1.stage3 = 0

        timer2 = self.timers[2]
        timer2_enable = timer2.enable
        timer2_enable_flag = bool(data & 0x04)
        timer2.enable = timer2_enable_flag
        if timer2_enable_flag and not timer2_enable:
            timer2.stage2 = 0
            timer2.stage3 = 0

        if data & 0x10:  # TODO not sure if r or w ports should be reset
            self.ports_r[0] = 0x00
            self.ports_r[1] = 0x00
            self.ports_w[0] = 0x00
            self.ports_w[1] = 0x00
            self._ports_w_dirty = True

        if data & 0x20:  # TODO not sure if r or w ports should be reset
            self.ports_r[2] = 0x00
            self.ports_r[3] = 0x00
            self.ports_w[2] = 0x00
            self.ports_w[3] = 0x00
            self._ports_w_dirty = True

        self.ipl_rom_enable = bool(data & 0x80)

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, value):
        assert isinstance(value, int)
        self._data = value

    @property
    def A(self):
        return self._A

    @A.setter
    def A(self, value):
        assert isinstance(value, int)
        assert 0 <= value <= 0xFF
        self._A = value

    @property
    def X(self):
        return self._X

    @X.setter
    def X(self, value):
        assert isinstance(value, int)
        assert 0 <= value <= 0xFF
        self._X = value

    @property
    def Y(self):
        return self._Y

    @Y.setter
    def Y(self, value):
        assert isinstance(value, int)
        assert 0 <= value <= 0xFF
        self._Y = value

    @property
    def S(self):
        return self._S

    @S.setter
    def S(self, value):
        assert isinstance(value, int)
        assert 0 <= value <= 0xFF
        self._S = value

    @property
    def PC(self):
        return self._PC

    @PC.setter
    def PC(self, value):
        assert isinstance(value, int)
        assert 0 <= value <= 0xFFFF
        self._PC = value
