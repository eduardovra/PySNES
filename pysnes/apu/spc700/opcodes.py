
from ctypes import c_uint8


class SPC700Opcodes:
    """Opcodes implementation"""

    def ADC(self, x, y):
        result = x + y + int(self.CF)
        self.CF = bool(result > 0xFF)
        self.ZF = bool(result & 0xFF == 0)
        self.HF = bool((x ^ y ^ result) & 0x10)
        self.VF = bool(~(x ^ y) & (x ^ result) & 0x80)
        self.NF = bool(result & 0x80)
        return result & 0xFF

    def AND(self, a: int, b: int) -> int:
        """a & b"""
        result = a & b
        self.NF = bool(result & 0x80)
        self.ZF = result == 0
        return result

    def ASL(self, x):
        self.CF = bool(x & 0x80)
        x = (x << 1) & 0xFF
        self.NF = bool(x & 0x80)
        self.ZF = x == 0
        return x

    def CMP(self, x, y):
        z = x - y
        self.CF = z >= 0
        self.ZF = c_uint8(z) == 0
        self.NF = bool(z & 0x80)
        return x

    def DEC(self, x):
        x = (x - 1) & 0xFF
        self.NF = bool(x & 0x80)
        self.ZF = x == 0
        return x

    def EOR(self, x, y):
        data = x ^ y
        self.ZF = data == 0
        self.NF = bool(data & 0x80)
        return data

    def INC(self, data):
        result = (data + 1) & 0xFF
        self.NF = bool(result & 0x80)
        self.ZF = result == 0
        return result

    def LD(self, x, y):
        self.ZF = y == 0
        self.NF = bool(y & 0x80)
        return y

    def LSR(self, x):
        self.CF = bool(x & 0x01)
        x >>= 1
        self.NF = bool(x & 0x80)
        self.ZF = x == 0
        return x

    def OR(self, a: int, b: int) -> int:
        result = a | b
        self.NF = bool(result & 0x80)
        self.ZF = result == 0
        return result

    def ROL(self, x):
        carry = self.CF
        self.CF = bool(x & 0x80)
        x = (carry << 7 | x >> 1) & 0xFF
        self.ZF = x == 0
        self.NF = bool(x & 0x80)
        return x

    def ROR(self, x):
        carry = self.CF
        self.CF = bool(x & 0x01)
        x = (carry << 7 | x >> 1) & 0xFF
        self.ZF = x == 0
        self.NF = bool(x & 0x80)
        return x

    def SBC(self, x: int, y: int) -> int:
        return self.ADC(x & 0xFF, ~y & 0xFF)

    def ADW(self, x, y):
        self.CF = False
        z = self.ADC(x, y)
        z |= self.ADC(x >> 8, y >> 8) << 8
        z &= 0xFFFF
        self.ZF = z == 0
        return z

    def CPW(self, x, y):
        z = x - y
        self.CF = z >= 0
        self.ZF = z & 0xFFFF == 0
        self.NF = bool(z & 0x8000)
        return x
    
    def LDW(self, x, y):
        self.ZF = y == 0
        self.NF = bool(y & 0x8000)
        return y

    def SBW(self, x, y):
        self.CF = True
        z = self.SBC(x, y)
        z |= self.SBC(x >> 8, y >> 8) << 8
        self.ZF = z & 0xFFFF == 0
        return z
