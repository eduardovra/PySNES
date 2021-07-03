from .bus import Bus
from .instructions import InstructionSet


class Cpu:
    class StatusRegister:
        # The status register bits 7,6,3,2,1,0 (nvdizc) function the same as the 6502 status register bits.

        # 7 n Negative flag
        # 6 v Overflow flag
        # 5 m Accumulator/Memory Select
        # 4 x Index Register Select
        # 3 d Decimal flag
        # 2 i Interrupt mask
        # 1 z Zero flag
        # 0 c Carry flag

        def __init__(self, emulation_mode: int) -> None:
            self.emulation_mode = emulation_mode
            self.initialize()

        def initialize(self):
            self.N = 0
            self.V = 0
            self.D = 0
            self.I = 0
            self.Z = 0
            self.C = 0

            if self.emulation_mode:
                self.B = 0  # B BRK flag bit - Emulation mode only
            else:
                self.M = 0  # Accumulator/Memory Select
                self.X = 0  # Index Register Select

        def get(self) -> int:
            value = (
                (self.N << 7)
                | (self.V << 6)
                | (self.D << 3)
                | (self.I << 2)
                | (self.Z << 1)
                | (self.C << 0)
            )

            if self.emulation_mode:
                value |= self.B << 4
            else:
                value |= (self.M << 5) | (self.X << 4)

            return value

    def __init__(self, bus: Bus) -> None:
        self.bus = bus
        self.instruction_set = InstructionSet(self)

        # Emulation bit
        self.emulation = 1  # Starts enabled

        # Registers
        self.A: int = 0  # Accumulator
        self.X: int = 0  # X Index Register
        self.Y: int = 0  # Y Index Register
        self.D: int = 0  # Direct Page Register
        self.S: int = 0  # Stack Pointer
        self.PB: int = 0  # Program Bank Register
        self.DB: int = 0  # Data Bank Register
        self.PC: int = 0x8000  # Program Counter TODO read from reset int vector
        self.P = self.StatusRegister(emulation_mode=self.emulation)

    def tick(self) -> int:
        cycles = self.fetch_and_execute()
        return cycles

    def fetch_and_execute(self) -> int:
        opcode = self.bus[self.PC]
        return self.instruction_set.execute(opcode)
