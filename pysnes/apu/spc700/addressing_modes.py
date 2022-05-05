from ctypes import c_int8

class SPC700AddressingModes:
    """Addressing modes implementation (alphabetical order)"""

    def AbsoluteBitModify(self, mode):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        bit = self.address >> 13
        self.address &= 0x1fff
        self.data = self.read(self.address)

        if mode == 0:  # or addr:bit
            self.CF |= bool(self.data & 1 << bit)
        elif mode == 1:  # or !addr:bit
            self.CF |= not bool(self.data & 1 << bit)
        elif mode == 2:  # and addr:bit
            self.CF &= bool(self.data & 1 << bit)
        elif mode == 3:  # and !addr:bit
            self.CF &= not bool(self.data & 1 << bit)
        elif mode == 4:  # eor addr:bit
            self.CF ^= bool(self.data & 1 << bit)
        elif mode == 5:  # ld addr:bit
            self.CF = bool(self.data & 1 << bit)
        elif mode == 6:  # st addr:bit
            self.data &= ~(1 << bit)
            self.data |= self.CF << bit
            self.write(self.address, self.data)
        elif mode == 7:  # not addr:bit
            self.data ^= 1 << bit
            self.write(self.address, self.data)

    def AbsoluteBitSet(self, bit, value):
        self.address = self.fetch()
        self.data = self.load(self.address)
        self.data &= ~(1 << bit)
        self.data |= value << bit
        self.store(self.address, self.data)

    def AbsoluteRead(self, func, reg):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = self.read(self.address)
        value = getattr(self, reg)
        result = func(self, value, self.data)
        setattr(self, reg, result)

    def AbsoluteModify(self, func):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = self.read(self.address)
        result = func(self, self.data)
        self.store(self.address, result)

    def AbsoluteWrite(self, reg_data):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = getattr(self, reg_data)
        self.write(self.address, self.data)

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

    def Branch(self, cond):
        self.data = self.fetch()
        take = cond(self)
        if take:
            displacement = c_int8(self.data)
            #assert displacement.value >= 0
            self.PC = (self.PC + displacement.value) & 0xFFFF

    def BranchBit(self, bit: int, match: bool):
        self.address = self.fetch()
        self.data = self.load(self.address)
        assert self.data >= 0
        displacement = self.fetch()
        if bool(self.data & 1 << bit) == match:
            self.PC = (c_int8(displacement).value + self.PC) & 0xFFFF

    def BranchNotDirect(self):
        self.address = self.fetch()
        self.data = self.load(self.address)
        displacement = self.fetch()
        if self.A != self.data:
            self.PC = (c_int8(displacement).value + self.PC) & 0xFFFF

    def BranchNotDirectDecrement(self):
        self.address = self.fetch()
        self.data = self.load(self.address)
        self.data -= 1
        self.store(self.address, self.data)
        displacement = self.fetch()
        if self.data != 0:
            self.PC = (c_int8(displacement).value + self.PC) & 0xFFFF

    def BranchNotDirectIndexed(self, reg_index):
        index = getattr(self, reg_index)
        self.address = self.fetch()
        self.data = self.load(self.address + index)
        displacement = self.fetch()
        if self.A != self.data:
            self.PC = (c_int8(displacement).value + self.PC) & 0xFFFF

    def BranchNotYDecrement(self):
        displacement = self.fetch()
        #assert (self.Y - 1) >= 0
        self.Y = (self.Y - 1) & 0xFF
        if self.Y != 0:
            self.PC = (c_int8(displacement).value + self.PC) & 0xFFFF

    def Break(self):
        self.push(self.PC >> 8)
        self.push(self.PC >> 0)
        self.push(self.PSW)
        self.address = self.read(0xffde + 0)
        self.address |= self.read(0xffde + 1) << 8
        self.PC = self.address
        self.IF = False
        self.BF = True

    def CallAbsolute(self):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.push(self.PC >> 8)
        self.push(self.PC >> 0)
        self.PC = self.address

    def CallPage(self):
        self.address = self.fetch()
        self.push(self.PC >> 8)
        self.push(self.PC >> 0)
        self.address = 0xff00 | self.address
        self.PC = self.address

    def CallTable(self, vector):
        self.push(self.PC >> 8)
        self.push(self.PC >> 0)
        self.address = 0xffde - (vector << 1)
        pc = self.read(self.address + 0)
        pc |= self.read(self.address + 1) << 8
        self.address = pc
        self.PC = pc

    def ComplementCarry(self):
        self.CF = not self.CF

    def DecimalAdjustAdd(self):
        if self.CF or self.A > 0x99:
            self.A += 0x60
            self.CF = True

        if self.HF or (self.A & 15) > 0x09:
            self.A += 0x06

        self.ZF = self.A == 0
        self.NF = bool(self.A & 0x80)

    def DecimalAdjustSub(self):
        if not self.CF or self.A > 0x99:
            self.A -= 0x60
            self.CF = False

        if not self.HF or (self.A & 15) > 0x09:
            self.A -= 0x06

        self.ZF = self.A == 0
        self.NF = bool(self.A & 0x80)

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

    def DirectDirectCompare(self, func):
        source = self.fetch()
        rhs = self.load(source)
        target = self.fetch()
        lhs = self.load(target)
        lhs = func(self, lhs, rhs)

    def DirectDirectModify(self, func):
        source = self.fetch()
        rhs = self.load(source)
        target = self.fetch()
        lhs = self.load(target)
        lhs = func(self, lhs, rhs)
        self.store(target, lhs)

    def DirectDirectWrite(self):
        source = self.fetch()
        self.data = self.load(source)
        self.address = self.fetch()
        self.store(self.address, self.data)

    def DirectImmediateCompare(self, func):
        immediate = self.fetch()
        self.address = self.fetch()
        self.data = self.load(self.address)
        func(self, self.data, immediate)

    def DirectImmediateModify(self, func):
        immediate = self.fetch()
        self.address = self.fetch()
        self.data = self.load(self.address)
        self.data = func(self, self.data, immediate)
        self.store(self.address, self.data)

    def DirectImmediateWrite(self):
        self.data = self.fetch()
        self.address = self.fetch()
        self.store(self.address, self.data)

    def DirectCompareWord(self, func):
        self.address = self.fetch()
        self.data = self.load(self.address + 0)
        self.data |= self.load(self.address + 1) << 8
        self.data &= 0xFFFF
        self.YA = func(self, self.YA, self.data)

    def DirectReadWord(self, func):
        self.address = self.fetch()
        self.data = self.load(self.address + 0) | self.load(self.address + 1) << 8
        self.YA = func(self, self.YA, self.data)

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

    def DirectWriteWord(self):
        self.address = self.fetch()
        self.data = self.YA
        self.store(self.address + 0, self.A)
        self.store(self.address + 1, self.Y)

    def DirectIndexedRead(self, func, reg_target, reg_index):
        self.address = self.fetch()
        index = getattr(self, reg_index)
        self.data = self.load(self.address + index)
        target = getattr(self, reg_target)
        result = func(self, target, self.data)
        setattr(self, reg_target, result)

    def DirectIndexedModify(self, func, reg):
        index = getattr(self, reg)
        self.address = (self.fetch() + index) & 0xFF
        self.data = self.load(self.address)
        self.data = func(self, self.data)
        self.store(self.address, self.data)

    def DirectIndexedWrite(self, reg_data, reg_index):
        self.data = getattr(self, reg_data)
        index = getattr(self, reg_index)
        self.address = self.fetch() + index
        #self.load(self.address)
        self.store(self.address, self.data)

    def Divide(self):
        ya = self.YA
        # overflow set if quotient >= 256
        self.HF = (self.Y & 15) >= (self.X & 15)
        self.VF = self.Y >= self.X
        if self.Y < (self.X << 1):
            # if quotient is <= 511 (will fit into 9-bit result)
            #self.A = ya / self.X
            #self.Y = ya % self.X
            self.A = (ya // self.X) & 0xFF
            self.Y = (ya % self.X) & 0xFF
        else:
            # otherwise, the quotient won't fit into VF + A
            # this emulates the odd behavior of the S-SMP in this case
            #self.A = 255 - (ya - (self.X << 9)) / (256 - self.X)
            #self.Y = self.X   + (ya - (self.X << 9)) % (256 - self.X)
            self.A = (255 - (ya - (self.X << 9)) // (256 - self.X)) & 0xFF
            self.Y = (self.X + (ya - (self.X << 9)) % (256 - self.X)) & 0xFF
        # result is set based on a (quotient) only
        self.ZF = self.A == 0
        self.NF = bool(self.A & 0x80)

    def ExchangeNibble(self):
        self.A = (self.A >> 4 & 0x0F) | (self.A << 4 & 0xF0)
        self.ZF = self.A == 0
        self.NF = bool(self.A & 0x80)

    def FlagSet(self, flag: str, value: bool):
        setattr(self, flag, value)

    def ImmediateRead(self, func, reg):
        """Immediate = #i"""
        self.address = self.PC  # for debugging
        self.data = self.fetch()
        a = getattr(self, reg)
        result = func(self, a, self.data)
        setattr(self, reg, result)

    def ImpliedModify(self, func, reg):
        data = getattr(self, reg)
        self.data = func(self, data)
        setattr(self, reg, self.data)

    def IndexedIndirectRead(self, func, reg):
        index = getattr(self, reg)
        indirect = self.fetch()
        self.address = self.load(indirect + index + 0);
        self.address |= self.load(indirect + index + 1) << 8
        self.data = self.read(self.address)
        self.A = func(self, self.A, self.data)

    def IndexedIndirectWrite(self, reg_data, reg_index):
        self.data = getattr(self, reg_data)
        index = getattr(self, reg_index)
        indirect = self.fetch()
        self.address = self.load(indirect + index + 0)
        self.address |= self.load(indirect + index + 1) << 8
        self.write(self.address, self.data)

    def IndirectIndexedRead(self, func, reg_index):
        index = getattr(self, reg_index)
        indirect = self.fetch()
        self.address = self.load(indirect + 0)
        self.address |= self.load(indirect + 1) << 8
        self.address = self.address + index
        self.data = self.read(self.address)
        self.A = func(self, self.A, self.data)

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

    def IndirectXRead(self, func):
        self.address = self.X
        self.data = self.load(self.address)
        self.A = func(self, self.A, self.data)

    def IndirectXWrite(self, reg):
        self.data = getattr(self, reg)
        self.address = self.X
        self.store(self.address, self.data)

    def IndirectXIncrementRead(self, reg_data):
        self.data = self.load(self.X)
        self.X = self.X + 1
        self.ZF = self.data == 0
        self.NF = bool(self.data & 0x80)

    def IndirectXIncrementWrite(self, reg_data):
        self.data = getattr(self, reg_data)
        self.address = self.X
        self.X = self.X + 1
        self.store(self.address, self.data)

    def IndirectXCompareIndirectY(self, func):
        rhs = self.load(self.Y)
        lhs = self.load(self.X)
        lhs = func(self, lhs, rhs)

    def IndirectXWriteIndirectY(self, func):
        rhs = self.load(self.Y)
        lhs = self.load(self.X)
        lhs = func(self, lhs, rhs)
        self.store(self.X, lhs)

    def JumpAbsolute(self):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.PC = self.address

    def JumpIndirectX(self):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.address = self.address + self.X
        pc = self.read(self.address + 0)
        pc |= self.read(self.address + 1) << 8
        self.PC = pc & 0xFFFF

    def Multiply(self):
        ya = (self.Y * self.A) & 0xFFFF
        self.A = ya >> 0 & 0xFF
        self.Y = ya >> 8 & 0xFF
        # result is set based on y (high-byte) only
        self.ZF = self.Y == 0
        self.NF = bool(self.Y & 0x80)

    def NoOperation(self):
        pass

    def OverflowClear(self):
        self.HF = False
        self.VF = False

    def Pull(self, reg):
        data = self.pull()
        setattr(self, reg, data)

    def PullP(self):
        self.PSW = self.pull()

    def Push(self, reg: str):
        data = getattr(self, reg)
        self.push(data)

    def ReturnInterrupt(self):
        self.PSW = self.pull()
        self.address = self.pull()
        self.address |= self.pull() << 8
        self.PC = self.address

    def ReturnSubroutine(self):
        self.address = self.pull()
        self.address |= self.pull() << 8
        self.PC = self.address

    def Stop(self):
        # seems to be a bsnes thing, dont know how to implement this yet
        assert False
        #r.stop = true;
        #while(r.stop && !synchronizing()) {
        #    read(PC);
        #    idle();
        #}

    def TestSetBitsAbsolute(self, bit_set):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = self.read(self.address)
        self.ZF = (self.A - self.data) == 0
        self.NF = bool((self.A - self.data) & 0x80)
        self.write(self.address, self.data | self.A if bit_set else self.data & ~self.A)

    def Transfer(self, src, dst):
        self.data = getattr(self, src)
        assert self.data <= 0xFF # may be a problem when copying stack pointer 0x1EF
        setattr(self, dst, self.data)
        # hack to match apu v1
        #if dst == "S":
        #    self.S |= 0x100
        self.ZF = self.data == 0
        self.NF = bool(self.data & 0x80)

    def Wait(self):
        # seems to be a bsnes thing, dont know how to implement this yet
        assert False
        #r.wait = true;
        #while(r.wait && !synchronizing()) {
        #    read(PC);
        #    idle();
        #}
