class Apu:
    """
    Audio system
    SPC700 & ARAM
    DSP
    """

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

        # The IO Port0-4 registers have separete memory for R/W
        self.ports_r = [0] * 4  # APU reads from
        self.ports_w = [0] * 4  # APU writes to

        # Read IPL ROOM (boot code)
        with open("ipl.rom", "rb") as f:
            self.ipl_rom = f.read()  # 64 bytes

    def __getitem__(self, addr: int) -> int:
        if 0x00F4 <= addr <= 0x00F7:
            return self.ports_w[addr - 0x00F4]
        elif 0xFFC0 <= addr <= 0xFFFF:
            return self.ipl_rom[addr - 0xFFC0]

        raise RuntimeError(
            "Error reading unmamped memory region: 0x{:06X}".format(addr)
        )

    def __setitem__(self, addr: int, value: int) -> None:
        if 0x00F4 <= addr <= 0x00F7:
            self.ports_r[addr - 0x00F4] = value
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

    def tick(self) -> None:
        self.fetch_and_execute()

    def fetch_and_execute(self) -> None:
        opcode = self[self.PC]
        self.PC += 1
        print(opcode)
        # self.instruction_set.execute(opcode)
