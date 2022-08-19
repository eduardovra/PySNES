from functools import partial
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from ...bus import Bus


class Reg:
    def __init__(self, bits: int, value: int):
        self.bits = bits
        self.value = value

    @property
    def l(self) -> int:
        """Low byte getter"""
        return self.value & 0xFF

    @l.setter
    def l(self, value: int):
        """Low byte setter"""
        self.value &= 0xFFFF00
        self.value |= value & 0xFF

    @property
    def h(self) -> int:
        """High byte getter"""
        return self.value >> 8 & 0xFF

    @h.setter
    def h(self, value: int):
        """High byte setter"""
        self.value &= 0xFF00FF
        self.value |= value << 8 & 0xFF00

    @property
    def b(self) -> int:
        """Bank byte getter"""
        return self.value >> 16 & 0xFF

    @b.setter
    def b(self, value: int):
        """Bank byte setter"""
        self.value &= 0xFFFF
        self.value |= value << 16 & 0xFF0000

    @property
    def w(self) -> int:
        """Low word getter"""
        return self.value & 0xFFFF

    @w.setter
    def w(self, value: int):
        """Low word setter"""
        self.value &= 0xFF0000
        self.value |= value & 0xFFFF

    @property
    def d(self) -> int:
        """24 bit getter"""
        return self.value & 0xFFFFFF

    @d.setter
    def d(self, value: int):
        """24 bit setter"""
        self.value = value & 0xFFFFFF


class Cpu:
    def __init__(self) -> None:
        self.reset_registers()
        self.load_instructions()

    def reset_registers(self):
        # Registers
        self.A = Reg(16, 0x0000)  # Accumulator
        self.X = Reg(16, 0x0000)  # X Index Register
        self.Y = Reg(16, 0x0000)  # Y Index Register
        self.D = Reg(16, 0x0000)  # Direct Page Register
        self.S = Reg(16, 0x01FF)  # Stack Pointer
        self.P = 0x34             # Status register
        self.PB = Reg(8, 0x00)    # Program Bank Register
        self.DB = Reg(8, 0x00)    # Data Bank Register
        self.PC = Reg(24, 0x00)   # self.hardware_vectors["emulation"]["RESET"]

        # bsnes
        # r.vector = 0xfffc;  //reset vector address
        # r24 u;  //temporary register
        # r24 v;  //temporary register
        # r24 w;  //temporary register
        self.U = Reg(24, 0x00)
        self.V = Reg(24, 0x00)
        self.W = Reg(24, 0x00)

        # Emulation flag
        self.EF: bool = True  # Starts enabled

        # Debug stuff
        self.breakpoint = None
        self.print_debug = False

    def load_instructions(self):
        from .wdc65816.instructions import INSTRUCTIONS

        self.instructions: Any = [None] * 256
        self.debug_symbols: Any = [""] * 256

        # load instructions into main table and setup up debugging symbols
        for opcode, addr_mode, *args in INSTRUCTIONS:
            self.instructions[opcode] = partial(addr_mode, self, *args)
            self.debug_symbols[opcode] = "{:02X} {}".format(opcode, addr_mode.__name__)
            if args:
                if callable(args[0]):
                    args[0] = args[0].__name__
                args = " ".join(str(a) for a in args)
                self.debug_symbols[opcode] += f" {args}"
            self.debug_symbols[opcode] = self.debug_symbols[opcode].ljust(30)

    def attach(self, bus: "Bus") -> None:
        self.bus = bus

    def idle(self):
        pass

    def idle2(self):
        if (self.D.l):
            self.idle()

    def idle4(self, x, y):
        #if(!XF || x >> 8 != y >> 8) idle();
        pass

    def write(self, addr, data):
        self.bus[addr] = data

    def read(self, addr):
        return self.bus[addr]

    def readDirect(self, address):
        # this is not part of bsnes implementation but it seems
        # tests expect the page to wrap around when in emulation mode
        # even if self.D.l is not zero
        if self.EF:
            addr = (self.D.h << 8) | ((self.D.l + address) & 0xff)
            return self.read(addr)
        if self.EF and self.D.l == 0:
            return self.read(self.D.w | address & 0xff)
        return self.read(self.D.w + address & 0xffff)

    def writeDirect(self, address, data):
        if self.EF and self.D.l == 0:
            return self.write(self.D.w | address & 0xff, data)
        return self.write(self.D.w + address & 0xffff, data)

    def readDirectN(self, address):
        return self.read(self.D.w + address & 0xffff)

    def readBank(self, address):
        return self.read((self.DB.l << 16) + address & 0xffffff)

    def writeBank(self, address, data):
        self.write((self.DB.l << 16) + address & 0xffffff, data);

    def readLong(self, address):
        return self.read(address & 0xffffff)

    def writeLong(self, address, data):
        self.write(address & 0xffffff, data)

    def readStack(self, address):
        return self.read(self.S.w + address & 0xffff)

    def writeStack(self, address, data):
        self.write(self.S.w + address & 0xffff, data)

    def fetch(self):
        data = self.read(self.PB.l << 16 | self.PC.w)
        self.PC.w += 1
        return data

    def fetch_and_execute(self):
        opcode = self.fetch()

        debug_str = "\033[92mCPU 0x{:06X} {} {}\033[0m".format(
            self.PB.l << 16 | self.PC.w - 1,
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
