from ctypes import c_int8

class SPC700AddressingModes:
    """Addressing modes implementation"""

    def ImmediateRead(self, func, reg):
        """Immediate = #i"""
        self.address = self.PC
        self.data = self.fetch()
        a = getattr(self, reg)
        result = func(self, a, self.data)
        setattr(self, reg, result)

    def ImpliedModify(self, func, reg):
        data = getattr(self, reg)
        self.data = func(self, data)
        setattr(self, reg, self.data)

    def DirectImmediateCompare(self, func):
        immediate = self.fetch()
        self.address = self.fetch()
        self.data = self.load(self.address)
        func(self, self.data, immediate)

    def DirectImmediateWrite(self):
        self.data = self.fetch()
        self.address = self.fetch()
        self.store(self.address, self.data)

    def DirectRead(self, func, reg):
        self.address = self.fetch()
        self.data = self.load(self.address)
        self.data = func(self, getattr(self, reg), self.data)
        setattr(self, reg, self.data)

    def DirectModify(self, func):
        self.address = self.fetch()
        data = self.load(self.address)
        self.data = func(self, data)
        self.store(self.address, self.data)

    def DirectWrite(self, reg):
        self.data = getattr(self, reg)
        self.address = self.fetch()
        self.store(self.address, self.data)

    def DirectReadWord(self, func):
        self.address = self.fetch()
        self.data = self.load(self.address + 0) | self.load(self.address + 1) << 8
        self.YA = func(self, self.YA, self.data)

    def DirectWriteWord(self):
        self.address = self.fetch()
        self.data = self.YA
        self.store(self.address + 0, self.A)
        self.store(self.address + 1, self.Y)

    def Branch(self, cond):
        self.data = self.fetch()
        take = cond(self)
        if take:
            displacement = c_int8(self.data)
            self.PC = (self.PC + displacement.value) & 0xFFFF

    def Transfer(self, src, dst):
        self.data = getattr(self, src)
        assert self.data <= 0xFF
        setattr(self, dst, self.data)
        self.ZF = self.data == 0
        self.NF = bool(self.data & 0x80)

    def IndirectXWrite(self, reg):
        self.data = getattr(self, reg)
        self.address = self.X
        self.store(self.address, self.data)
