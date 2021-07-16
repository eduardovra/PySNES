from .bus import Bus
from .instructions import InstructionSet


class Cpu:
    """
    The SNES's CPU (Central Processing Unit) is a 65c816 based processor.
    While its clock speed is at about 21 MHz, it's effective speed is considerably lower,
    at 3.58 MHz for quick access (i.e. hardware registers at $2100-$21FF in banks $00-$3F),
    2.68 MHz for slow access (i.e. ROM and RAM) and
    1.79 MHz for very slow access (i.e. hardware registers at $4000-$41FFF in banks $00 through $3F).
    """

    class StatusRegister:
        def __init__(self) -> None:
            self.N = 0  # Negative flag
            self.V = 0  # Overflow flag
            self.D = 0  # Decimal flag
            self.I = 0  # Interrupt mask
            self.Z = 0  # Zero flag
            self.C = 0  # Carry flag
            # Emulation mode only
            self.B = 0  # B BRK flag bit
            # Native mode only
            self.M = 0  # Accumulator/Memory Select
            self.X = 0  # Index Register Select

        def get(self, emulation_mode) -> int:
            value = (
                (self.N << 7)
                | (self.V << 6)
                | (self.D << 3)
                | (self.I << 2)
                | (self.Z << 1)
                | (self.C << 0)
            )

            if emulation_mode:
                value |= self.B << 4
            else:
                value |= (self.M << 5) | (self.X << 4)

            return value

        def set(self, value, emulation_mode) -> None:
            self.N = (value >> 7) & 0x01
            self.V = (value >> 6) & 0x01
            self.D = (value >> 3) & 0x01
            self.I = (value >> 2) & 0x01
            self.Z = (value >> 1) & 0x01
            self.C = (value >> 0) & 0x01

            if emulation_mode:
                self.B = (value >> 4) & 0x01
            else:
                self.M = (value >> 5) & 0x01
                self.X = (value >> 4) & 0x01

    def __init__(self, bus: Bus, hardware_vectors: dict) -> None:
        self.bus = bus
        self.hardware_vectors = hardware_vectors
        self.instruction_set = InstructionSet(self)

        # Emulation bit
        self.emulation = 1  # Starts enabled

        # Registers
        self.A: int = 0x0000  # Accumulator
        self.X: int = 0x0000  # X Index Register
        self.Y: int = 0x0000  # Y Index Register
        self.D: int = 0x0000  # Direct Page Register
        self.S: int = 0x0100  # Stack Pointer
        self.PB: int = 0x00  # Program Bank Register
        self.DB: int = 0x00  # Data Bank Register
        self.PC: int = self.hardware_vectors["emulation"]["RESET"]
        self.P = self.StatusRegister()

        # Debugging properties
        self.ticks = 0

    def __str__(self) -> str:
        flags = [
            "E" if self.emulation else "e",
            "N" if self.P.N else "n",
            "V" if self.P.V else "v",
            "M" if self.P.M else "m",
            "X" if self.P.X else "x",
            "D" if self.P.D else "d",
            "I" if self.P.I else "i",
            "Z" if self.P.Z else "z",
            "C" if self.P.C else "c",
        ]
        return "PC:{:06X} A:{:04X} X:{:04X} Y:{:04X} P:{}".format(
            self.PC, self.A, self.X, self.Y, "".join(flags)
        )

    def tick(self) -> int:
        self.ticks += 1
        cycles = self.fetch_and_execute()
        return cycles

    def fetch_and_execute(self) -> int:
        opcode = self.bus[self.PC]
        self.PC += 1
        cycles = self.instruction_set.execute(opcode)
        return cycles
