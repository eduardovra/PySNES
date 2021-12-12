from ctypes import c_int8

class SPC700AddressingModes:
    """Addressing modes implementation"""
    def ImmediateRead(self, func, reg):
        """Immediate = #i"""
        b = self.fetch()
        a = getattr(self, reg)
        result = func(self, a, b)
        setattr(self, reg, result)

    def ImpliedModify(self, func, reg):
        data = getattr(self, reg)
        data = func(self, data)
        setattr(self, reg, data)

    def DirectImmediateCompare(self, func):
        immediate = self.fetch()
        address = self.fetch()
        data = self.load(address)
        func(self, data, immediate)

    def DirectImmediateWrite(self):
        immediate = self.fetch()
        address = self.fetch()
        self.store(address, immediate)

    def DirectModify(self, func):
        addr = self.fetch()
        data = self.load(addr)
        result = func(self, data)
        self.store(addr, result)

    def Branch(self, cond):
        data = self.fetch()
        take = cond(self)
        if take:
            displacement = c_int8(data)
            self.PC += displacement.value

    def Transfer(self, src, dst):
        data = getattr(self, src)
        setattr(self, dst, data)
        self.ZF = data == 0
        self.NF = bool(data & 0x80)

    def IndirectXWrite(self, reg):
        data = getattr(self, reg)
        self.store(self.X, data)
