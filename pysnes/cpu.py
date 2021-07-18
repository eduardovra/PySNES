from typing import TYPE_CHECKING
from dataclasses import dataclass

from .instructions import InstructionSet

if TYPE_CHECKING:
    from .bus import Bus


@dataclass
class CpuStatus:
    hirq_enable: bool = False
    virq_enable: bool = False
    irq_enable: bool = False

    nmi_line: bool = False
    nmi_transition: bool = False
    nmi_enable: bool = False
    nmi_pending: bool = False
    nmi_hold: bool = False
    nmi_valid: bool = False

    v_blank_ticks: int = 0
    v_bank_on: bool = False

    @property
    def interrupt_pending(self) -> bool:
        return self.nmi_pending


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

    def __init__(self, hardware_vectors: dict) -> None:
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

        # Emulation state flags
        self.status = CpuStatus()

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

    def attach(self, bus: "Bus") -> None:
        self.bus = bus

    def tick(self) -> int:
        self.ticks += 1

        # Update the NMI line to reflect the v-bank period
        # I still don't know how to determine the correct
        # moment to trigger the line, so I'm establishing
        # something random:
        # 10000 ticks for v-bank off, 1000 ticks v-bank on
        if self.status.v_blank_ticks:
            self.status.v_blank_ticks -= 1
        else:
            if self.status.v_bank_on:
                # Transition to low
                self.status.v_bank_on = False
                self.status.nmi_line = False
                self.status.v_blank_ticks = 10000
            else:
                # Transition to high
                self.status.v_bank_on = True
                self.status.nmi_line = True
                self.status.v_blank_ticks = 1000
                if self.status.nmi_enable:
                    self.status.nmi_transition = True

        # Test for NMI rising edge and trigger interrupt on next iteration
        if self.status.nmi_transition:
            self.status.nmi_transition = False
            self.status.nmi_pending = True

        """
        # NMI Poll every 4 clock cycles
        if self.ticks & 0x02:
            if self.status.nmi_hold and self.status.nmi_enable:
                self.status.nmi_transition = True
            self.status.nmi_hold = False

            # Figure out the right timing to call this
            if self.ticks & 0x40:
                self.status.nmi_valid = not self.status.nmi_valid
                self.status.nmi_line = self.status.nmi_valid
                if self.status.nmi_line:
                    self.status.nmi_hold = True  # hold /NMI for four cycles
        """

        # If there's no interrupt pending keep normal execution flow
        if not self.status.interrupt_pending:
            cycles = self.fetch_and_execute()
            return cycles

        # NMI trigger has been scheduled, so jump to its vector
        if self.status.nmi_pending:
            self.status.nmi_pending = False
            vector = 0xFFFA if self.emulation else 0xFFEA
            return self.interrupt(vector)

        return 1

    def fetch_and_execute(self) -> int:
        self.opcode = self.bus[self.PC]
        self.PC += 1
        cycles = self.instruction_set.execute(self.opcode)
        return cycles

    def interrupt(self, vector: int) -> int:
        # Bank
        if self.emulation == 0:
            self.bus[self.S] = self.PC >> 16
            self.S -= 1
        # High
        self.bus[self.S] = self.PC >> 8
        self.S -= 1
        # Low
        self.bus[self.S] = self.PC & 0xFF
        self.S -= 1
        # P register
        p = self.P.get(self.emulation)
        self.bus[self.S] = p & ~0x10 if self.emulation else p
        self.S -= 1

        self.P.I = 1
        self.P.D = 0

        addr = self.bus[vector] | self.bus[vector + 1] << 8
        self.PC = addr

        return 1  # whatever
