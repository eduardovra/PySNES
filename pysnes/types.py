from ctypes import c_uint16, c_uint8


class Register:
    def __add__(self, value):
        cls = self.__class__
        return cls(self.value + value.value)



class Reg8(Register, c_uint8):
    def __repr__(self) -> str:
        return "{}(0x{:02X})".format(self.__class__.__name__, self.value)



class Reg16(Register, c_uint16):
    def __repr__(self) -> str:
        return "{}(0x{:04X})".format(self.__class__.__name__, self.value)
