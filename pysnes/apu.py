import csv


class Apu:
    """
    Audio system
    SPC700 & ARAM
    DSP
    """

    OPCODES_ADDRESSING_MODE_TABLE = {
        "Implied": [0xBD, 0x00, 0x20, 0x40, 0x60, 0x80, 0xA0, 0xC0, 0xE0, 0x1D],
        "Immediate": [0xCD, 0xE8],
        "Indirect": [0xC6],
        "Relative": [0xD0],
        "ImmediateDataToDirectPage": [0x8F, 0x78],
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

        self.page_0 = [0] * (1 + 0x00EF - 0x0000)

        # The IO Port0-4 registers have separete memory for R/W
        self.ports_r = [0] * 4  # APU reads from
        self.ports_w = [0] * 4  # APU writes to

        # IPL ROOM (boot code) - 64 bytes
        # fmt: off
        self.ipl_rom = (
            0xCD,0xEF,0xBD,0xE8,0x00,0xC6,0x1D,0xD0,0xFC,0x8F,0xAA,0xF4,0x8F,0xBB,0xF5,0x78,
            0xCC,0xF4,0xD0,0xFB,0x2F,0x19,0xEB,0xF4,0xD0,0xFC,0x7E,0xF4,0xD0,0x0B,0xE4,0xF5,
            0xCB,0xF4,0xD7,0x00,0xFC,0xD0,0xF3,0xAB,0x01,0x10,0xEF,0x7E,0xF4,0x10,0xEB,0xBA,
            0xF6,0xDA,0x00,0xBA,0xF4,0xC4,0xF4,0xDD,0x5D,0xD0,0xDB,0x1F,0x00,0x00,0xC0,0xFF,
        )
        # fmt: on

    def __getitem__(self, addr: int) -> int:
        if 0x0000 <= addr <= 0x00EF:
            return self.page_0[addr]
        elif 0x00F4 <= addr <= 0x00F7:
            return self.ports_r[addr - 0x00F4]
        elif 0xFFC0 <= addr <= 0xFFFF:
            return self.ipl_rom[addr - 0xFFC0]

        raise RuntimeError(
            "Error reading unmamped memory region: 0x{:06X}".format(addr)
        )

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x0000 <= addr <= 0x00EF:
            self.page_0[addr] = value
        elif 0x00F4 <= addr <= 0x00F7:
            self.ports_w[addr - 0x00F4] = value
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
                    # "Cycles": int(row["Cycles"]), # TODO Don't if it's gonna be important
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
        print("APU", hex(self.PC), hex(opcode), instruction)
        # Determine addressing mode and fetch operand address
        addr_mode_method = getattr(self, instruction["AddressingMode"])
        addr = addr_mode_method()
        # Execute instruction
        method_name = "_".join((instruction["Mnemonic"], "{:02X}".format(opcode)))
        instruction_method = getattr(self, method_name)
        instruction_method(addr)
        # TODO Update SPW flags

    def Implied(self) -> int:
        return 0

    def Immediate(self) -> int:
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

    def ImmediateDataToDirectPage(self) -> int:
        """Immediate Data to Direct Page = d, #i"""
        addr = self.PC
        self.PC += 2
        return addr

    def update_flags(self, value: int) -> None:
        """Update SPW flags based on resulting value from previous operation"""

    def MOV_CD(self, addr: int) -> None:
        """X = i"""
        self.X = self[addr]
        self.N = 1 if self.X & 0x80 else 0
        self.Z = 1 if self.X == 0 else 0

    def MOV_BD(self, addr: int) -> None:
        """SP = X"""
        self.SP = self.X

    def MOV_E8(self, addr: int) -> None:
        """A = i"""
        self.A = self[addr]
        self.N = 1 if self.A & 0x80 else 0
        self.Z = 1 if self.A == 0 else 0

    def MOV_C6(self, addr: int) -> None:
        """(X) = A"""
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr] | page
        self[absolute_addr] = self.A

    def MOV_8F(self, addr: int) -> None:
        """(d) = i"""
        value = self[addr]
        page = 0x0100 if self.P else 0x0000
        absolute_addr = self[addr + 1] | page
        self[absolute_addr] = value

    def DEC_1D(self, addr: int) -> None:
        """X--"""
        self.X -= 1
        self.N = 1 if self.X & 0x80 else 0
        self.Z = 1 if self.X == 0 else 0

    def BNE_D0(self, addr: int) -> None:
        """PC+=r  if Z == 0"""
        if self.Z == 0:
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
