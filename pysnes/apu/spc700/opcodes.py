
from ctypes import c_uint8


class SPC700Opcodes:
    """
    Opcodes implementation

    Notes:
    Python stores negative integers as two's complement and that's why bitwise operations won't work correctly
    https://stackoverflow.com/questions/46044936/bitwise-and-between-negative-and-positive-numbers

    """

    def ADC(self, x, y):
        #assert False
        result = x + y + int(self.CF)
        self.CF = bool(result > 0xFF)
        self.ZF = bool(result & 0xFF == 0)
        self.HF = bool((x ^ y ^ result) & 0x10)
        self.VF = bool(~(x ^ y) & (x ^ result) & 0x80)
        self.NF = bool(result & 0x80)
        return result & 0xFF

    def AND(self, a: int, b: int) -> int:
        """a & b"""
        assert a >= 0
        assert b >= 0
        result = (a & b) & 0xFF
        self.NF = bool(result & 0x80)
        self.ZF = result == 0
        assert (a & b) >= 0
        return result

    def ASL(self, x):
        assert x >= 0
        self.CF = bool(x & 0x80)
        x = (x << 1) & 0xFF
        self.NF = bool(x & 0x80)
        self.ZF = x == 0
        assert (x << 1) >= 0
        return x

    def CMP(self, x, y):
        z = x - y
        #assert z >= 0
        #self.CF = z >= 0  # bsnes version
        self.CF = z > 0xFF
        self.ZF = c_uint8(z).value == 0
        #self.NF = bool(z & 0x80)  # bsnes version
        self.NF = z < 0
        return x

    def DEC(self, x):
        assert x >= 0
        assert (x - 1) >= 0
        x = (x - 1) & 0xFF
        self.NF = bool(x & 0x80)
        self.ZF = x == 0
        return x

    def EOR(self, x, y):
        assert x >= 0
        assert y >= 0
        data = (x ^ y) & 0xFF
        self.ZF = data == 0
        self.NF = bool(data & 0x80)
        assert (x ^ y) >= 0
        return data

    def INC(self, data):
        assert data >= 0
        result = (data + 1) & 0xFF
        self.NF = bool(result & 0x80)
        self.ZF = result == 0
        assert (data + 1) >= 0
        return result

    def LD(self, x, y):
        assert y >= 0
        self.ZF = y == 0
        self.NF = bool(y & 0x80)
        return y

    def LSR(self, x):
        assert x >= 0
        self.CF = bool(x & 0x01)
        x = (x >> 1) & 0xFF
        self.NF = bool(x & 0x80)
        self.ZF = x == 0
        assert (x >> 1) >= 0
        return x

    def OR(self, a: int, b: int) -> int:
        assert a >= 0
        assert b >= 0
        result = (a | b) & 0xFF
        self.NF = bool(result & 0x80)
        self.ZF = result == 0
        assert (a | b) >= 0
        return result

    def ROL(self, x):
        assert x >= 0
        carry = self.CF
        self.CF = bool(x & 0x80)
        x = (carry << 7 | x >> 1) & 0xFF
        self.ZF = x == 0
        self.NF = bool(x & 0x80)
        assert (carry << 7 | x >> 1) >= 0
        return x

    def ROR(self, x):
        assert x >= 0
        carry = self.CF
        self.CF = bool(x & 0x01)
        x = (carry << 7 | x >> 1) & 0xFF
        self.ZF = x == 0
        self.NF = bool(x & 0x80)
        assert (carry << 7 | x >> 1) >= 0
        return x

    def SBC(self, x: int, y: int) -> int:
        #assert False
        assert x >= 0
        assert y >= 0
        return SPC700Opcodes.ADC(self, x & 0xFF, ~y & 0xFF)

    def ADW(self, x, y):
        #assert False
        assert x >= 0
        assert y >= 0
        self.CF = False
        z = SPC700Opcodes.ADC(self, x, y)
        z |= SPC700Opcodes.ADC(self, x >> 8, y >> 8) << 8
        z &= 0xFFFF
        self.ZF = z == 0
        return z

    def CPW(self, x, y):
        assert x >= 0
        assert y >= 0
        z = x - y
        self.CF = z >= 0
        self.ZF = z & 0xFFFF == 0
        self.NF = z < 0  # bool(z & 0x8000)
        return x

    def LDW(self, x, y):
        #assert False
        assert y >= 0
        self.ZF = y == 0
        self.NF = bool(y & 0x8000)
        return y

    def SBW(self, x, y):
        #assert False
        assert x >= 0
        assert y >= 0
        self.CF = True
        z = SPC700Opcodes.SBC(self, x, y)
        z |= SPC700Opcodes.SBC(self, x >> 8, y >> 8) << 8
        self.ZF = z & 0xFFFF == 0
        return z
