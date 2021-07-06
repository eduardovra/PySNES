import csv


class Apu:
    """
    Audio system
    SPC700 & ARAM
    DSP
    """

    OPCODES_ADDRESSING_MODE_TABLE = {
        "Implied": [
            0xBD,
            0x00,
            0x20,
            0x40,
            0x60,
            0x80,
            0xA0,
            0xC0,
            0xE0,
            0x1D,
            0xDD,
            0x5D,
            0xBC,
            0x3D,
            0xFC,
        ],
        "Immediate": [0xCD, 0xE8],
        "Indirect": [0xC6],
        "Relative": [0x90, 0xB0, 0xF0, 0x30, 0xD0, 0x10, 0x50, 0x70, 0x2F],
        "DirectPage": [0xBA, 0xDA, 0xC4, 0xEB, 0x7E, 0xE4, 0xCB],
        "ImmediateDataToDirectPage": [0x8F, 0x78],
        "IndirectYIndexed": [0xD7],
    }

    def __init__(self) -> None:
        # Registers
        self.PC = 0xFFC0  # Program Counter (16 bit)
        self.A = 0  # Accumulator (8 bit)
        self.X = 0  # X Index Register (8 bit)
        self.Y = 0  # Y Index Register (8 bit)
        self.SP = 0  # Stack Pointer (8 bit)
        # self.PSW = 0  # Program Status Word (8 bit)
        # YA  YA paired 16-bit register TODO

        # Flags stored in PSW Register
        self.N = 0  # Negative
        self.V = 0  # Overflow
        self.P = 0  # Direct page
        self.B = 0  # Break
        self.H = 0  # Half carry
        self.I = 0  # Interrupt enabled (unused)
        self.Z = 0  # Zero
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
        # self.memory = [0] * 0xFFFF

        self.page_0 = bytearray(1 + 0x00EF - 0x0000)

        # The IO Port0-4 registers have separete memory for R/W
        self.ports_r = bytearray(4)  # APU reads from
        self.ports_w = bytearray(4)  # APU writes to

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
        elif 0x00F4 <= addr <= 0x00F7:
            # print(f"  APU read [{hex(addr)}] ==> {hex(self.ports_r[addr - 0x00F4])}")
            return self.ports_r[addr - 0x00F4]
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
        elif 0x00F4 <= addr <= 0x00F7:
            print(f"  APU write [{hex(addr)}] <== {hex(value)}")
            self.ports_w[addr - 0x00F4] = value
        elif 0x0200 <= addr <= 0xFFBF:
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

    def load_instructions(self) -> None:
        self.instruction_set = [{}] * 256
        with open("spc700.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                opcode = int(row["HEX"], 16)
                mnemonic = row["Assembler Example"].split(" ", 1)[0]
                # TODO Determine addressing mode
                addr_mode_str = row["Assembler Example"][len(mnemonic) + 1 :]

                # if addr_mode_str == "X, #i":
                #    addressing_mode = "Immediate"
                # else:
                #    addressing_mode = None

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
        self.fetch_and_execute()

    def fetch_and_execute(self) -> None:
        # Fetch opcode
        opcode = self[self.PC]
        self.PC += 1
        # Get reference to instruction metadata
        instruction = self.instruction_set[opcode]
        # print("\033[93mAPU", hex(self.PC), hex(opcode), instruction, "\033[0m")
        # Determine addressing mode and fetch operand address
        addr_mode_method = getattr(self, instruction["AddressingMode"])
        addr = addr_mode_method()
        # Execute instruction
        method_name = "_".join((instruction["Mnemonic"], "{:02X}".format(opcode)))
        instruction_method = getattr(self, method_name)
        instruction_method(addr)
        # TODO Update SPW flags

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

    def Indirect(self) -> int:
        """Indirect = (X)"""
        addr = self.X
        return addr

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

    def update_flags(self, value: int) -> None:
        """Update SPW flags based on resulting value from previous operation"""

    #######################################################
    # Instructions                                        #
    #######################################################

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

    def MOV_EB(self, addr: int) -> None:
        """Y = (d)"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self.Y = self[absolute_addr]
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

    def MOV_C6(self, addr: int) -> None:
        """(X) = A"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self.X | page
        self[absolute_addr] = self.A

    def MOV_D7(self, addr: int) -> None:
        """([d]+Y) = A    (read)"""
        self[addr] = self.A

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

    def DEC_1D(self, addr: int) -> None:
        """X--"""
        self.X -= 1
        self.N = 1 if self.X & 0x80 else 0
        self.Z = 1 if self.X == 0 else 0

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
