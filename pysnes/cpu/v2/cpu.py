from functools import partial
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...bus import Bus

from .wdc65816.instructions import INSTRUCTIONS


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
        self.EF = True  # Starts enabled

        # Debug stuff
        self.address = 0  # Last accessed address
        self.data = 0  # Last accessed data
        self.breakpoint = None
        self.print_debug = False

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

    def attach(self, bus: "Bus") -> None:
        self.bus = bus
        #self.dma = DMA(bus)  # TODO Ugly

    def read(self, addr):
        return self.bus[addr]

    def fetch(self):
        data = self.read(self.PB << 16 | self.PC)
        assert isinstance(data, int) and 0 <= data <= 0xFF
        self.PC = (self.PC + 1) & 0xFFFF
        return data

    def fetch_and_execute(self):
        opcode = self.fetch()

        #debug_str = "\033[92mCPU 0x{:06X} {} {}\033[0m".format(
        #    self.cpu.current_instruction_PC,
        #    str(instruction).ljust(40),
        #    self.cpu,
        #)

        #debug_str = "APU 0x{:04X} 0x{:02X} {}".format(
        #    self.PC - 1,
        #    opcode,
        #    self.debug_symbols[opcode],
        #)
        #apu_str = str(self)

        instruction = self.instructions[opcode]

        instruction()
        return

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
