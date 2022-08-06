from functools import partial
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...bus import Bus

from .wdc65816.instructions import INSTRUCTIONS
from .wdc65816.addressing_modes import WDC65816AddressingModes
from .wdc65816.opcodes import WDC65816Opcodes

class Cpu:

    def __init__(self) -> None:
        self.reset_registers()
        self.load_instructions()

    def reset_registers(self):
        # Registers
        self.A: int = 0x0000  # Accumulator
        self.X: int = 0x0000  # X Index Register
        self.Y: int = 0x0000  # Y Index Register
        self.D: int = 0x0000  # Direct Page Register
        self.S: int = 0x01FF  # Stack Pointer
        self.P = 0x34  # Status register
        self.PB: int = 0x00  # Program Bank Register
        self.DB: int = 0x00  # Data Bank Register
        self.PC: int = 0x00  # self.hardware_vectors["emulation"]["RESET"]

        # bsnes
        # r.vector = 0xfffc;  //reset vector address

        # Emulation flag
        self.EF: bool = True  # Starts enabled

        # Debug stuff
        self.address = 0  # Last accessed address
        self.data = 0  # Last accessed data
        self.breakpoint = None
        self.print_debug = False

    def load_instructions(self):
        self.instructions: Any = [None] * 256
        self.debug_symbols: Any = [""] * 256

        # wrapper to pick correct method based on register values at runtime
        def wrapper(self, register: str, addr_mode: str, *args):
            if not register:
                suffix = ""
            elif getattr(self, register):
                suffix = "8"
            else:
                suffix = "16"

            method_addr_mode = getattr(WDC65816AddressingModes, f"{addr_mode}{suffix}")

            try:
                opcode_register, op_code_function, *args = args
                if getattr(self, opcode_register):
                    suffix = "8"
                else:
                    suffix = "16"

                method_opcode = getattr(WDC65816Opcodes, f"{op_code_function}{suffix}")
                return method_addr_mode(self, method_opcode, *args)
            except:
                if not args:
                    raise
                return method_addr_mode(self, *args)

        # load instructions into main table and setup up debugging symbols
        for opcode, reg_addr_mode, addr_mode, *args in INSTRUCTIONS:
            self.instructions[opcode] = partial(wrapper, self, reg_addr_mode, addr_mode, *args)
            self.debug_symbols[opcode] = addr_mode
            if args:
                args = " ".join(str(a) for a in args)
                self.debug_symbols[opcode] += f" {args}"
            self.debug_symbols[opcode] = self.debug_symbols[opcode].ljust(30)

    def attach(self, bus: "Bus") -> None:
        self.bus = bus

    def write(self, addr, data):
        self.bus[addr] = data

    def read(self, addr):
        return self.bus[addr]

    def fetch(self):
        data = self.read(self.PB << 16 | self.PC)
        assert isinstance(data, int) and 0 <= data <= 0xFF
        self.PC = (self.PC + 1) & 0xFFFF
        return data

    def fetch_and_execute(self):
        opcode = self.fetch()

        debug_str = "\033[92mCPU 0x{:06X} {} {}\033[0m".format(
            self.PB << 16 | self.PC - 1,
            self.debug_symbols[opcode].ljust(40),
            "", #self.cpu,
        )
        print(debug_str)

        instruction = self.instructions[opcode]
        instruction()

    @property
    def P(self) -> int:
        return self.CF << 0 | self.ZF << 1 | self.IF << 2 | self.DF << 3 | self.XF << 4 | self.MF << 5 | self.VF << 6 | self.NF << 7

    @P.setter
    def P(self, data: int):
        self.CF = bool(data & 0x01)
        self.ZF = bool(data & 0x02)
        self.IF = bool(data & 0x04)
        self.DF = bool(data & 0x08)
        self.XF = bool(data & 0x10)
        self.MF = bool(data & 0x20)
        self.VF = bool(data & 0x40)
        self.NF = bool(data & 0x80)
