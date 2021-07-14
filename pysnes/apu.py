import csv


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
    """
    Audio system
    SPC700 & ARAM
    DSP
    8-bit SPC700, runs at ~1Mhz ...with the effective
    speed being half (each instruction takes a minimum of 2 cycles)
    1.024 MHz
    Wikipedia:
    Clock rates
    Input: 24.576 MHz
    SPC700: 1.024 MHz

    BSNES:
    DSP clock (~24576khz) / 12 (~2048khz) is fed into the SMP
    """

    FREQUENCY = 2048000  # 2048khz

    OPCODES_ADDRESSING_MODE_TABLE = {
        "Implied": [
            0x00,
            0x1D,
            0x20,
            0x40,
            0x60,
            0x80,
            0xA0,
            0xBD,
            0xC0,
            0xCF,
            0xE0,
            0xEE,
            0xDD,
            0x5D,
            0xBC,
            0x3D,
            0xFC,
            0xFD,
            0xAF,
            0x6D,
            0x6F,
            0x7D,
            0x2E,  # Handled in mnemonic
            0xDE,  # Handled in mnemonic
        ],
        "Immediate": [0x68, 0x8D, 0xAD, 0xCD, 0xC8, 0xE8],
        "ImmediateDataToDirectPage": [0x8F, 0x78],
        "Absolute": [
            0x0C,
            0x2C,
            0x3F,
            0x4C,
            0x5E,
            0x6C,
            0x8C,
            0xAC,
            0xC5,
            0xC9,
            0xCC,
            0xE5,
            0xEC,
        ],
        "AbsoluteXIndexedIndirect": [0x1F],
        "AbsoluteBooleanBit": [0xAA],
        "Indirect": [0xC6],
        "IndirectYIndexed": [0xD7],
        "IndirectAutoIncremet": [],
        "IndirectPageToIndirectPage": [0x19, 0x39, 0x59, 0x79, 0x99, 0xB9],
        "Relative": [0x90, 0xB0, 0xF0, 0x30, 0xD0, 0x10, 0x50, 0x70, 0x2F],
        "DirectPage": [0xBA, 0xDA, 0xC4, 0xEB, 0x7E, 0x84, 0xE4, 0xCB, 0xAB],
        "XIndexedAbsolute": [0x75, 0xD5, 0xF5],
        "XIndexedDirectPage": [0xF4, 0xD4, 0xDB],
        "YIndexedDirectPage": [0xD9],
    }

    def __init__(self) -> None:
        # Registers
        self.PC = 0xFFC0  # Program Counter (16 bit)
        self.A = 0x00  # Accumulator (8 bit)
        self.X = 0x00  # X Index Register (8 bit)
        self.Y = 0x00  # Y Index Register (8 bit)
        self.SP = 0xEF  # Stack Pointer (8 bit)
        # self.PSW = 0  # Program Status Word (8 bit)
        # YA  YA paired 16-bit register TODO

        # Flags stored in PSW Register
        self.N = 0  # Negative
        self.V = 0  # Overflow
        self.P = 0  # Direct page
        self.B = 0  # Break
        self.H = 0  # Half carry
        self.I = 0  # Interrupt enabled (unused)
        self.Z = 1  # Zero
        self.C = 0  # Carry

        self.load_instructions()

        # SPC Memory Map and Registers
        # Range         Description
        # 0000 - 00EF	Page 0
        # 00F0 - 00FF	Registers
        # 0100 - 01FF	Page 1
        # 0200 - FFBF	Memory
        # FFC0 - FFFF	Memory (read / write)
        # FFC0 - FFFF	Memory (write only)*
        # FFC0 - FFFF	64 byte IPL ROM (read only)*

        self.page_0 = bytearray(0x00F0)
        self.page_1 = bytearray(0x0100)

        # The IO Port0-4 registers have separete memory for R/W
        self.ports_r = bytearray(4)  # APU reads from
        self.ports_w = bytearray(4)  # APU writes to

        self.timers = [Timer(self, 128), Timer(self, 128), Timer(self, 16)]

        # Registers
        self.test_register = 0x0A  # F0 (write-only)
        self.control_register = 0x80  # F1 (write only)
        self.dsp_register_address = 0x00  # F2 (r/w)
        self.dsp_register_data = 0x00  # F3 (r/w)
        # self.timers = bytearray(3)  # FA/FB/FC (/w)
        # self.counters = bytearray(3)  # FD/FE/FF (r/)

        # Control register 0xF1
        self.ipl_rom_enable = True

        self.memory = bytearray(0xFFBF - 0x0200 + 1)

        # IPL ROOM (boot code) - 64 bytes
        # fmt: off
        self.ipl_rom = bytes((
            0xCD,0xEF,0xBD,0xE8,0x00,0xC6,0x1D,0xD0,0xFC,0x8F,0xAA,0xF4,0x8F,0xBB,0xF5,0x78,
            0xCC,0xF4,0xD0,0xFB,0x2F,0x19,0xEB,0xF4,0xD0,0xFC,0x7E,0xF4,0xD0,0x0B,0xE4,0xF5,
            0xCB,0xF4,0xD7,0x00,0xFC,0xD0,0xF3,0xAB,0x01,0x10,0xEF,0x7E,0xF4,0x10,0xEB,0xBA,
            0xF6,0xDA,0x00,0xBA,0xF4,0xC4,0xF4,0xDD,0x5D,0xD0,0xDB,0x1F,0x00,0x00,0xC0,0xFF,
        ))
        # fmt: on

    def __getitem__(self, addr: int) -> int:
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
            "Error reading unmamped memory region: 0x{:06X}".format(addr)
        )

    def __setitem__(self, addr: int, value: int) -> None:
        assert 0x00 <= value <= 0xFF, "Attemped to write value bigger than 1 byte"

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
            # print(f"  APU write [{hex(addr)}] <== {hex(value)}")
            self.ports_w[addr - 0x00F4] = value
        elif 0x00FA <= addr <= 0x00FC:
            timer = self.timers[addr - 0x00FA]
            timer.target = value
        elif 0x0100 <= addr <= 0x01FF:
            self.page_1[addr - 0x0100] = value
        elif 0x0200 <= addr <= 0xFFBF:
            # print(f"[{hex(addr)}] <== {hex(value)}")
            self.memory[addr - 0x0200] = value
        else:
            raise RuntimeError(
                "Error writting unmamped memory region: 0x{:06X}".format(addr)
            )

    @property
    def PSW(self) -> int:
        return (
            self.N << 7
            | self.V << 6
            | self.P << 5
            | self.B << 4
            | self.H << 3
            | self.I << 2
            | self.Z << 1
            | self.C << 0
        )

    @PSW.setter
    def PSW(self, value: int) -> None:
        self.N = (value & 0x80) >> 7
        self.V = (value & 0x40) >> 6
        self.P = (value & 0x20) >> 5
        self.B = (value & 0x10) >> 4
        self.H = (value & 0x08) >> 3
        self.I = (value & 0x04) >> 2
        self.Z = (value & 0x02) >> 1
        self.C = (value & 0x01) >> 0

    @property
    def test_register(self) -> int:
        return 0x00  # Write only register

    @test_register.setter
    def test_register(self, data: int) -> None:
        if self.P:
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

        if data & 0x10:
            self.ports_r[0] = 0x00
            self.ports_r[1] = 0x00

        if data & 0x20:
            self.ports_r[2] = 0x00
            self.ports_r[3] = 0x00

        self.ipl_rom_enable = bool(data & 0x80)

    def load_instructions(self) -> None:
        self.instruction_set = [{}] * 256
        with open("spc700.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                opcode = int(row["HEX"], 16)
                mnemonic = row["Assembler Example"].split(" ", 1)[0]
                # TODO Determine addressing mode
                addr_mode_str = row["Assembler Example"][len(mnemonic) + 1 :]

                self.instruction_set[opcode] = {
                    "Mnemonic": mnemonic,
                    "Example": row["Assembler Example"],
                    "AddressingMode": None,
                    "AddressingModeStr": addr_mode_str,
                    "Flags": [f for f in row["Flags Set"] if f != "-"],
                    "Bytes": int(row["Bytes"]),
                    # "Cycles": int(row["Cycles"]), # TODO Don't know if it's gonna be important
                }

        # Add addressing mode
        for mode, opcodes in self.OPCODES_ADDRESSING_MODE_TABLE.items():
            for opcode in opcodes:
                self.instruction_set[opcode]["AddressingMode"] = mode

    def tick(self) -> None:
        self.step_timers()
        self.fetch_and_execute()

    def step_timers(self) -> None:
        for timer in self.timers:
            timer.step(1)  # TODO count real clock cycles

    def fetch_and_execute(self) -> None:
        # Fetch opcode
        opcode = self[self.PC]
        self.PC += 1
        # Get reference to instruction metadata
        instruction = self.instruction_set[opcode]
        # if not (0xFFC0 <= self.PC <= 0xFFFF):  # Skip IPL
        if not instruction.get("AddressingMode"):  # Unimplemented instructions only
            print("\033[93mAPU", hex(self.PC - 1), hex(opcode), instruction, "\033[0m")
        # Determine addressing mode and fetch operand address
        addr_mode_method = getattr(self, instruction["AddressingMode"])
        addr = addr_mode_method()
        # Execute instruction
        method_name = "_".join((instruction["Mnemonic"], "{:02X}".format(opcode)))
        instruction_method = getattr(self, method_name)
        instruction_method(addr)

    #######################################################
    # Addressing Modes                                    #
    #######################################################

    def Implied(self) -> int:
        """Implied"""
        return 0

    def Immediate(self) -> int:
        """Immediate = #i"""
        addr = self.PC
        self.PC += 1
        return addr

    def Absolute(self) -> int:
        """Absolute = !a"""
        addr_low = self[self.PC]
        self.PC += 1
        addr_high = self[self.PC]
        self.PC += 1
        return addr_low | addr_high << 8

    def AbsoluteXIndexedIndirect(self) -> int:
        """Absolute X-Indexed Indirect = [!a+X]"""
        addr_low = self[self.PC]
        self.PC += 1
        addr_high = self[self.PC]
        self.PC += 1
        addr = ((addr_low | addr_high << 8) + self.X) & 0xFFFF
        return self[addr] | self[addr + 1] << 8

    def AbsoluteBooleanBit(self) -> int:
        """Absolute Boolean Bit = m.b"""
        addr_low = self[self.PC]
        self.PC += 1
        addr_high = self[self.PC]
        self.PC += 1
        return addr_low | addr_high << 8

    def Indirect(self) -> int:
        """Indirect = (X)"""
        addr = self.X
        return addr

    def IndirectAutoIncremet(self) -> int:
        """Indirect Auto-Increment = (X)+"""
        raise

    def IndirectPageToIndirectPage(self) -> int:
        """Indirect Page to Indirect Page = (X), (Y)"""
        return self.X

    def Relative(self) -> int:
        """Relative = r"""
        r = self[self.PC]
        # Convert two-s complement representation to signed int
        if r & 0x80:
            r = (-1) * ((~r & 0xFF) + 1)
        self.PC += 1
        addr = self.PC + r
        return addr

    def DirectPage(self) -> int:
        """Direct Page = d"""
        addr = self.PC
        self.PC += 1
        return addr

    def ImmediateDataToDirectPage(self) -> int:
        """Immediate Data to Direct Page = d, #i"""
        addr = self.PC
        self.PC += 2
        return addr

    def IndirectYIndexed(self) -> int:
        """Indirect Y-Indexed = [d]+Y"""
        page = 0x0100 if self.P else 0x0000
        relative_addr = self[self.PC] | page
        d_value = self[relative_addr] | self[relative_addr + 1] << 8
        addr = d_value + self.Y  # TODO dont know if Y can be negative
        self.PC += 1
        return addr

    def XIndexedAbsolute(self) -> int:
        """X-Indexed Absolute = !a+X"""
        addr_low = self[self.PC]
        self.PC += 1
        addr_high = self[self.PC]
        self.PC += 1
        addr = ((addr_low | addr_high << 8) + self.X) & 0xFFFF
        return addr

    def XIndexedDirectPage(self) -> int:
        """X-Indexed Direct Page = d+X"""
        page = 0x0100 if self.P else 0x0000
        addr = self[self.PC]
        self.PC += 1
        return page | (addr + self.X)

    def YIndexedDirectPage(self) -> int:
        """Y-Indexed Direct Page = d+Y"""
        page = 0x0100 if self.P else 0x0000
        addr = self[self.PC]
        self.PC += 1
        return page | (addr + self.Y)

    #######################################################
    # Instructions                                        #
    #######################################################

    def NOP_00(self, addr: int) -> None:
        """do nothing"""

    def CLRC_60(self, addr: int) -> None:
        """C = 0"""
        self.C = 0

    def CLRP_20(self, addr: int) -> None:
        """P = 0"""
        self.P = 0

    def CLRV_E0(self, addr: int) -> None:
        """V = 0, H = 0"""
        self.V = 0
        self.H = 0

    def MOV_D5(self, addr: int) -> None:
        """(a+X) = A"""
        self[addr] = self.A

    def MOV_D6(self, addr: int) -> None:
        """(a+Y) = A"""
        self[addr] = self.A

    def MOV_CD(self, addr: int) -> None:
        """X = i"""
        self.X = self[addr]
        self.N = 1 if self.X & 0x80 else 0
        self.Z = 1 if self.X == 0 else 0

    def MOV_5D(self, addr: int) -> None:
        """X = A"""
        self.X = self.A
        self.N = 1 if self.X & 0x80 else 0
        self.Z = 1 if self.X == 0 else 0

    def MOV_E9(self, addr: int) -> None:
        """X = (a)"""
        self.X = self[addr]
        self.N = 1 if self.X & 0x80 else 0
        self.Z = 1 if self.X == 0 else 0

    def MOV_AF(self, addr: int) -> None:
        """(X++) = A"""
        self.X = (
            self.X + 1
        ) & 0xFF  # TODO confirm if the increment is before or after the memory access
        self.A = self[self.X]

    def MOV_8D(self, addr: int) -> None:
        """Y = i"""
        self.Y = self[addr]
        self.N = 1 if self.Y & 0x80 else 0
        self.Z = 1 if self.Y == 0 else 0

    def MOV_FD(self, addr: int) -> None:
        """Y = A"""
        self.Y = self.A
        self.N = 1 if self.Y & 0x80 else 0
        self.Z = 1 if self.Y == 0 else 0

    def MOV_EB(self, addr: int) -> None:
        """Y = (d)"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self.Y = self[absolute_addr]
        self.N = 1 if self.Y & 0x80 else 0
        self.Z = 1 if self.Y == 0 else 0

    def MOV_EC(self, addr: int) -> None:
        """Y = (a)"""
        self.Y = self[addr]
        self.N = 1 if self.Y & 0x80 else 0
        self.Z = 1 if self.Y == 0 else 0

    def MOV_BD(self, addr: int) -> None:
        """SP = X"""
        self.SP = self.X

    def MOV_E8(self, addr: int) -> None:
        """A = i"""
        self.A = self[addr]
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def MOV_7D(self, addr: int) -> None:
        """A = X"""
        self.A = self.X
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def MOV_DD(self, addr: int) -> None:
        """A = Y"""
        self.A = self.Y
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def MOV_E4(self, addr: int) -> None:
        """A = (d)"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self.A = self[absolute_addr]
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def MOV_F4(self, addr: int) -> None:
        """A = (d+X)"""
        self.A = self[addr]
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def MOV_E5(self, addr: int) -> None:
        """A = (a)"""
        self.A = self[addr]
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def MOV_F5(self, addr: int) -> None:
        """A = (a+X)"""
        self.A = self[addr]
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def MOV_C4(self, addr: int) -> None:
        """(d) = A        (read)"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self[absolute_addr] = self.A

    def MOV_CB(self, addr: int) -> None:
        """(d) = Y        (read)"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self[absolute_addr] = self.Y

    def MOV_8F(self, addr: int) -> None:
        """(d) = i"""
        value = self[addr]
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr + 1] | page
        self[absolute_addr] = value

    def MOV_C5(self, addr: int) -> None:
        """(a) = A"""
        self[addr] = self.A

    def MOV_C9(self, addr: int) -> None:
        """(a) = X"""
        self[addr] = self.X

    def MOV_CC(self, addr: int) -> None:
        """(a) = Y"""
        self[addr] = self.Y

    def MOV_C6(self, addr: int) -> None:
        """(X) = A"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self.X | page
        self[absolute_addr] = self.A

    def MOV_D7(self, addr: int) -> None:
        """([d]+Y) = A    (read)"""
        self[addr] = self.A

    def MOV_D4(self, addr: int) -> None:
        """(d+X) = A"""
        self[addr] = self.A

    def MOV_DB(self, addr: int) -> None:
        """(d+X) = Y"""
        self[addr] = self.Y

    def MOV_D9(self, addr: int) -> None:
        """(d+Y) = X"""
        self[addr] = self.X

    def MOVW_BA(self, addr: int) -> None:
        """YA = word (d)"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self.A = self[absolute_addr]
        self.Y = self[absolute_addr + 1]
        self.N = 1 if self.Y & 0xFF else 0
        self.Z = 1 if self.Y == 0 and self.A == 0 else 0

    def MOVW_DA(self, addr: int) -> None:
        """word (d) = YA  (read low only)"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self[absolute_addr] = self.A  # TODO not sure about order
        self[absolute_addr + 1] = self.Y

    def MOV1_AA(self, addr: int) -> None:
        """C = (m.b)"""
        bit = addr >> 13
        data = self[addr & 0x1FFF]
        self.C = 1 if (data & (1 << bit)) else 0

    def BCC_90(self, addr: int) -> None:
        """PC+=r  if C == 0"""
        if self.C == 0:
            self.PC = addr

    def BCS_B0(self, addr: int) -> None:
        """PC+=r  if C == 1"""
        if self.C == 1:
            self.PC = addr

    def BEQ_F0(self, addr: int) -> None:
        """PC+=r  if Z == 1"""
        if self.Z == 1:
            self.PC = addr

    def BMI_30(self, addr: int) -> None:
        """PC+=r  if N == 1"""
        if self.N == 1:
            self.PC = addr

    def BNE_D0(self, addr: int) -> None:
        """PC+=r  if Z == 0"""
        if self.Z == 0:
            self.PC = addr

    def BPL_10(self, addr: int) -> None:
        """PC+=r  if N == 0"""
        if self.N == 0:
            self.PC = addr

    def BVC_50(self, addr: int) -> None:
        """PC+=r  if V == 0"""
        if self.V == 0:
            self.PC = addr

    def BVS_70(self, addr: int) -> None:
        """PC+=r  if V == 1"""
        if self.V == 1:
            self.PC = addr

    def BRA_2F(self, addr: int) -> None:
        """PC+=r"""
        self.PC = addr

    def JMP_1F(self, addr: int) -> None:
        """PC = [a+X]"""
        self.PC = addr

    def CBNE_DE(self, addr: int) -> None:
        """CMP A, (d+X) then BNE"""
        # Exception --> Set addr mode as implied and handle
        # everything in here
        addr = self[self.PC]
        self.PC += 1
        page = self.P << 8
        data = self[page | (addr + self.X)]
        displacement = self[self.PC]
        self.PC += 1
        if self.A != data:
            # Convert two's complement representation to signed int
            if displacement & 0x80:
                displacement = (-1) * ((~displacement & 0xFF) + 1)
            self.PC += displacement

    def CBNE_2E(self, addr: int) -> None:
        """CMP A, (d) then BNE"""
        # Exception --> Set addr mode as implied and handle
        # everything in here
        addr = self[self.PC]
        self.PC += 1
        page = self.P << 8
        data = self[page | addr]
        displacement = self[self.PC]
        self.PC += 1
        if self.A != data:
            # Convert two's complement representation to signed int
            if displacement & 0x80:
                displacement = (-1) * ((~displacement & 0xFF) + 1)
            self.PC += displacement

    def CALL_3F(self, addr: int) -> None:
        """(SP--)=PCh, (SP--)=PCl, PC=a"""
        self[self.SP] = (self.PC >> 8) & 0xFF
        self.SP -= 1
        self[self.SP] = self.PC & 0xFF
        self.SP -= 1
        self.PC = addr

    def RET_6F(self, addr: int) -> None:
        """Pop PC"""
        self.SP += 1
        low_addr = self[self.SP]
        self.SP += 1
        high_addr = self[self.SP]
        self.PC = low_addr | high_addr << 8

    def PUSH_2D(self, addr: int) -> None:
        """(SP--) = A"""
        self[self.SP] = self.A
        self.SP -= 1

    def PUSH_0D(self, addr: int) -> None:
        """(SP--) = Flags"""
        self[self.SP] = self.PSW
        self.SP -= 1

    def PUSH_4D(self, addr: int) -> None:
        """(SP--) = X"""
        self[self.SP] = self.X
        self.SP -= 1

    def PUSH_6D(self, addr: int) -> None:
        """(SP--) = Y"""
        self[self.SP] = self.Y
        self.SP -= 1

    def POP_AE(self, addr: int) -> None:
        """A = (++SP)"""
        self.SP += 1
        self.A = self[self.SP]

    def POP_8E(self, addr: int) -> None:
        """Flags = (++SP)"""
        self.SP += 1
        self.PSW = self[self.SP]

    def POP_CE(self, addr: int) -> None:
        """X = (++SP)"""
        self.SP += 1
        self.X = self[self.SP]

    def POP_EE(self, addr: int) -> None:
        """Y = (++SP)"""
        self.SP += 1
        self.Y = self[self.SP]

    def CMP_68(self, addr: int) -> None:
        """A - i"""
        i = self[addr]
        result = self.A - i
        self.N = 1 if result < 0x00 else 0
        self.Z = 1 if result == 0 else 0
        self.C = 1 if result > 0xFF else 0  # TODO not sure

    def CMP_75(self, addr: int) -> None:
        """A - (a+X)"""
        i = self[addr]
        result = self.A - i
        self.N = 1 if result < 0x00 else 0
        self.Z = 1 if result == 0 else 0
        self.C = 1 if result > 0xFF else 0  # TODO not sure

    def CMP_C8(self, addr: int) -> None:
        """X - i"""
        i = self[addr]
        result = self.X - i
        self.N = 1 if result < 0x00 else 0
        self.Z = 1 if result == 0 else 0
        self.C = 1 if result > 0xFF else 0  # TODO not sure

    def CMP_78(self, addr: int) -> None:
        """(d) - i"""
        i = self[addr]
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr + 1] | page
        result = self[absolute_addr] - i
        self.N = 1 if result < 0x00 else 0
        self.Z = 1 if result == 0 else 0
        self.C = 1 if result > 0xFF else 0  # TODO not sure

    def CMP_7E(self, addr: int) -> None:
        """Y - (d)"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        result = self.Y - self[absolute_addr]
        self.N = 1 if result < 0x00 else 0
        self.Z = 1 if result == 0 else 0
        self.C = 1 if result > 0xFF else 0  # TODO not sure

    def CMP_5E(self, addr: int) -> None:
        """Y - (a)"""
        result = self.Y - self[addr]
        self.N = 1 if result < 0x00 else 0
        self.Z = 1 if result == 0 else 0
        self.C = 1 if result > 0xFF else 0  # TODO not sure

    def INC_BC(self, addr: int) -> None:
        """A++"""
        self.A = (self.A + 1) & 0xFF
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def INC_3D(self, addr: int) -> None:
        """X++"""
        self.X = (self.X + 1) & 0xFF
        self.N = 1 if self.X & 0x80 else 0
        self.Z = 1 if self.X == 0 else 0

    def INC_FC(self, addr: int) -> None:
        """Y++"""
        self.Y = (self.Y + 1) & 0xFF
        self.N = 1 if self.Y & 0x80 else 0
        self.Z = 1 if self.Y == 0 else 0

    def INC_AB(self, addr: int) -> None:
        """(d)++"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self[absolute_addr] = (self[absolute_addr] + 1) & 0xFF
        self.N = 1 if self[absolute_addr] & 0x80 else 0
        self.Z = 1 if self[absolute_addr] == 0 else 0

    def DEC_1D(self, addr: int) -> None:
        """X--"""
        self.X -= 1
        self.N = 1 if self.X & 0x80 else 0
        self.Z = 1 if self.X == 0 else 0

    def ADC(self, x: int, y: int) -> int:
        result = x + y + self.C
        self.C = result > 0xFF
        self.Z = (result & 0xFF) == 0
        self.H = (x ^ y ^ result) & 0x10
        self.V = ~(x ^ y) & (x ^ result) & 0x80
        self.N = result & 0x80
        return result & 0xFF

    def ADC_99(self, addr: int) -> None:
        """(X) = (X)+(Y)+C"""
        x = self[self.P << 8 | self.X]
        y = self[self.P << 8 | self.Y]
        result = self.ADC(x, y)
        self[self.P << 8 | self.X] = result

    def ADC_88(self, addr: int) -> None:
        """A = A+i+C"""
        value = self[addr]
        self.A = self.ADC(self.A, value)

    def ADC_86(self, addr: int) -> None:
        """A = A+(X)+C"""
        raise
        value = self[addr]
        self.A = self.ADC(self.A, value)

    def ADC_97(self, addr: int) -> None:
        """A = A+([d]+Y)+C"""
        raise
        value = self[addr]
        self.A = self.ADC(self.A, value)

    def ADC_87(self, addr: int) -> None:
        """A = A+([d+X])+C"""
        raise
        value = self[addr]
        self.A = self.ADC(self.A, value)

    def ADC_84(self, addr: int) -> None:
        """A = A+(d)+C"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        value = self[absolute_addr]
        self.A = self.ADC(self.A, value)

    def ADC_94(self, addr: int) -> None:
        """A = A+(d+X)+C"""
        raise
        value = self[addr]
        self.A = self.ADC(self.A, value)

    def ADC_85(self, addr: int) -> None:
        """A = A+(a)+C"""
        raise
        value = self[addr]
        self.A = self.ADC(self.A, value)

    def ADC_95(self, addr: int) -> None:
        """A = A+(a+X)+C"""
        raise
        value = self[addr]
        self.A = self.ADC(self.A, value)

    def ADC_96(self, addr: int) -> None:
        """A = A+(a+Y)+C"""
        raise
        value = self[addr]
        self.A = self.ADC(self.A, value)

    def ADC_89(self, addr: int) -> None:
        """(dd) = (dd)+(d)+C"""
        raise NotImplementedError

    def ADC_98(self, addr: int) -> None:
        """(d) = (d)+i+C"""
        raise NotImplementedError

    def MUL_CF(self, addr: int) -> None:
        """YA = Y * A, NZ on Y only"""
        ya = self.Y * self.A
        self.A = (ya >> 0) & 0xFF
        self.Y = (ya >> 8) & 0xFF
        # result is set based on y (high-byte) only
        self.Z = 1 if self.Y == 0 else 0
        self.N = 1 if self.Y & 0x80 else 0
