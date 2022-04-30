from ctypes import c_int8

class SPC700AddressingModes:
    """Addressing modes implementation (alphabetical order)"""

    def AbsoluteIndexedRead(self, func, reg):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        index = getattr(self, reg)
        self.data = self.read(self.address + index)
        self.A = func(self, self.A, self.data)

    def AbsoluteIndexedWrite(self, index):
        index = getattr(self, index)
        assert index >= 0
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.address = self.address + index
        self.store(self.address, self.A)

    def AbsoluteModify(self, func):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = self.load(self.address)
        result = func(self, self.data)
        self.store(self.address, result)

    def AbsoluteRead(self, func, reg):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = self.read(self.address)
        value = getattr(self, reg)
        result = func(self, value, self.data)
        setattr(self, reg, result)

    def BranchBit(self, bit: int, match: bool):
        self.address = self.fetch()
        self.data = self.load(self.address)
        assert self.data >= 0
        displacement = self.fetch()
        if bool(self.data & 1 << bit) == match:
            self.PC = (c_int8(displacement).value + self.PC) & 0xFFFF

    def BranchNotYDecrement(self):
        displacement = self.fetch()
        #assert (self.Y - 1) >= 0
        self.Y = (self.Y - 1) & 0xFF
        if self.Y != 0:
            self.PC = (c_int8(displacement).value + self.PC) & 0xFFFF

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

    def DirectCompareWord(self, func):
        self.address = self.fetch()
        self.data = self.load(self.address + 0)
        self.data |= self.load(self.address + 1) << 8
        self.data &= 0xFFFF
        self.YA = func(self, self.YA, self.data)

    def DirectImmediateCompare(self, func):
        immediate = self.fetch()
        self.address = self.fetch()
        self.data = self.load(self.address)
        func(self, self.data, immediate)

    def DirectImmediateWrite(self):
        self.data = self.fetch()
        self.address = self.fetch()
        self.store(self.address, self.data)

    def DirectIndexedModify(self, func, reg):
        index = getattr(self, reg)
        self.address = (self.fetch() + index) & 0xFF
        self.data = self.load(self.address)
        self.data = func(self, self.data)
        self.store(self.address, self.data)

    def DirectIndexedRead(self, func, reg_target, reg_index):
        self.address = self.fetch()
        index = getattr(self, reg_index)
        self.data = self.load(self.address + index)
        target = getattr(self, reg_target)
        result = func(self, target, self.data)
        setattr(self, reg_target, result)

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

    def DirectModifyWord(self, adjust):
        self.address = self.fetch()
        #self.data = self.load(self.address + 0) + adjust
        #self.store(self.address + 0, (self.data & 0xFF) >> 0)
        #self.data = (self.data + self.load(self.address + 1) << 8) & 0xFFFF
        #self.store(self.address + 1, (self.data >> 8) & 0xFF)
        self.data = self.load(self.address + 0) | self.load(self.address + 1) << 8
        self.data = (self.data + adjust) & 0xFFFF
        self.store(self.address + 0, (self.data >> 0) & 0xFF)
        self.store(self.address + 1, (self.data >> 8) & 0xFF)
        self.ZF = self.data == 0
        #self.NF = self.data < 0 or bool(self.data & 0x8000) # maybe this is the right way
        self.NF = bool(self.data & 0x8000)

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
            #assert displacement.value >= 0
            self.PC = (self.PC + displacement.value) & 0xFFFF

    def FlagSet(self, flag: str, value: bool):
        setattr(self, flag, value)

    def Pull(self, reg):
        data = self.pull()
        setattr(self, reg, data)

    def PullP(self):
        self.PSW = self.pull()

    def Push(self, reg: str):
        data = getattr(self, reg)
        self.push(data)

    def Transfer(self, src, dst):
        self.data = getattr(self, src)
        assert self.data <= 0xFF # may be a problem when copying stack pointer 0x1EF
        setattr(self, dst, self.data)
        # hack to match apu v1
        #if dst == "S":
        #    self.S |= 0x100
        self.ZF = self.data == 0
        self.NF = bool(self.data & 0x80)

    def IndirectIndexedWrite(self, data, index):
        data = getattr(self, data)
        index = getattr(self, index)
        assert index >= 0
        indirect = self.fetch()
        self.address = self.load(indirect + 0)
        self.address |= self.load(indirect + 1) << 8
        self.address = self.address + index
        self.data = data
        self.store(self.address, self.data);

#auto SPC700::instructionIndirectXRead(fpb op) -> void {
#  read(PC);
#  uint8 data = load(X);
#  A = alu(A, data);
#}
#
#auto SPC700::instructionIndirectXWrite(uint8& data) -> void {
#  read(PC);
#  load(X);
#  store(X, data);
#}

    def IndirectXWrite(self, reg):
        self.data = getattr(self, reg)
        self.address = self.X
        self.store(self.address, self.data)

    def OverflowClear(self):
        self.HF = False
        self.VF = False

    def JumpAbsolute(self):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.PC = self.address

    def JumpIndirectX(self):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.address = self.address + self.X
        pc = self.load(self.address + 0)
        pc |= self.load(self.address + 1) << 8
        self.PC = pc & 0xFFFF
