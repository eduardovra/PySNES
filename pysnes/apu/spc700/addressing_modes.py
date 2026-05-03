class SPC700AddressingModes:
    """Addressing modes implementation (alphabetical order)"""

    def AbsoluteBitModify(self, mode):
        # OR1/AND1/EOR1/NOT1/MOV1 C,m.b  — 5 cycles (read-only), 6 cycles (write)
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        bit = self.address >> 13
        self.address &= 0x1fff
        self.data = self.read(self.address)

        if mode == 0:  # OR1  C,m.b     — 5 cycles
            self.idle()
            self.CF |= bool(self.data & 1 << bit)
        elif mode == 1:  # OR1  C,/m.b   — 5 cycles
            self.idle()
            self.CF |= not bool(self.data & 1 << bit)
        elif mode == 2:  # AND1 C,m.b    — 4 cycles (no idle)
            self.CF &= bool(self.data & 1 << bit)
        elif mode == 3:  # AND1 C,/m.b   — 4 cycles (no idle)
            self.CF &= not bool(self.data & 1 << bit)
        elif mode == 4:  # EOR1 C,m.b    — 5 cycles
            self.idle()
            self.CF ^= bool(self.data & 1 << bit)
        elif mode == 5:  # MOV1 C,m.b    — 4 cycles (no idle)
            self.CF = bool(self.data & 1 << bit)
        elif mode == 6:  # MOV1 m.b,C    — 6 cycles (idle + write)
            self.idle()
            self.data &= ~(1 << bit)
            self.data |= self.CF << bit
            self.write(self.address, self.data)
        elif mode == 7:  # NOT1 m.b      — 5 cycles (write, no idle)
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
        # ASL/LSR/ROL/ROR/INC/DEC !a — 5 cycles
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = self.read(self.address)
        result = func(self, self.data)
        self.write(self.address, result)

    def AbsoluteWrite(self, reg_data):
        # MOV !a,A/X/Y — 5 cycles: opcode + fetch_lo + fetch_hi + dummy_read + write
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = getattr(self, reg_data)
        self.read(self.address)  # dummy read before write (hardware behaviour)
        self.write(self.address, self.data)

    def AbsoluteIndexedRead(self, func, reg):
        # OP A,!a+X/Y — 5 cycles
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        index = getattr(self, reg)
        self.idle()
        self.data = self.read((self.address + index) & 0xFFFF)
        self.A = func(self, self.A, self.data)

    def AbsoluteIndexedWrite(self, index):
        # MOV !a+X,A / MOV !a+Y,A — 6 cycles: opcode + lo + hi + idle + dummy_read + write
        index = getattr(self, index)
        assert index >= 0
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.address = (self.address + index) & 0xFFFF
        self.idle()
        self.read(self.address)  # dummy read before write (hardware behaviour)
        self.write(self.address, self.A)

    def Branch(self, cond):
        # Bcc rel — 2 cycles not taken, 4 cycles taken
        self.data = self.fetch()
        take = cond(self)
        if take:
            displacement = self.data if self.data < 0x80 else self.data - 0x100
            self.idle()
            self.idle()
            self.PC = (self.PC + displacement) & 0xFFFF

    def BranchBit(self, bit: int, match: bool):
        # BBC/BBS dp.bit,rel — 5 cycles not taken, 7 cycles taken
        self.address = self.fetch()
        self.data = self.load(self.address)
        assert self.data >= 0
        displacement = self.fetch()
        self.idle()
        if bool(self.data & 1 << bit) == match:
            self.idle()
            self.idle()
            displacement = displacement if displacement < 0x80 else displacement - 0x100
            self.PC = (displacement + self.PC) & 0xFFFF

    def BranchNotDirect(self):
        # CBNE dp,rel — 5 cycles not taken, 7 cycles taken
        self.address = self.fetch()
        self.data = self.load(self.address)
        displacement = self.fetch()
        self.idle()
        if self.A != self.data:
            self.idle()
            self.idle()
            displacement = displacement if displacement < 0x80 else displacement - 0x100
            self.PC = (displacement + self.PC) & 0xFFFF

    def BranchNotDirectDecrement(self):
        # DBNZ dp,rel — 5 cycles not taken, 7 cycles taken
        self.address = self.fetch()
        self.data = self.load(self.address)
        self.data = (self.data - 1) & 0xFF
        self.store(self.address, self.data)
        displacement = self.fetch()
        if self.data != 0:
            self.idle()
            self.idle()
            displacement = displacement if displacement < 0x80 else displacement - 0x100
            self.PC = (displacement + self.PC) & 0xFFFF

    def BranchNotDirectIndexed(self, reg_index):
        # CBNE dp+X,rel — 6 cycles not taken, 8 cycles taken
        index = getattr(self, reg_index)
        self.address = self.fetch()
        self.idle()
        self.data = self.load(self.address + index)
        self.idle()
        displacement = self.fetch()
        if self.A != self.data:
            self.idle()
            self.idle()
            displacement = displacement if displacement < 0x80 else displacement - 0x100
            self.PC = (displacement + self.PC) & 0xFFFF

    def BranchNotYDecrement(self):
        # DBNZ Y,rel — 4 cycles not taken, 6 cycles taken
        # Hardware reads pc+1 twice (ghost + real); model as 2 idles before fetch
        self.idle()
        self.idle()
        displacement = self.fetch()
        self.Y = (self.Y - 1) & 0xFF
        if self.Y != 0:
            self.idle()
            self.idle()
            displacement = displacement if displacement < 0x80 else displacement - 0x100
            self.PC = (displacement + self.PC) & 0xFFFF

    def Break(self):
        # BRK — 8 cycles
        self.idle()
        self.push(self.PC >> 8)
        self.push(self.PC >> 0)
        self.push(self.PSW)
        self.address = self.read(0xffde + 0)
        self.address |= self.read(0xffde + 1) << 8
        self.PC = self.address
        self.IF = False
        self.BF = True
        self.idle()

    def CallAbsolute(self):
        # JSR !a — 8 cycles
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.idle()
        self.idle()
        self.push(self.PC >> 8)
        self.push(self.PC >> 0)
        self.idle()
        self.PC = self.address

    def CallPage(self):
        # PCALL dp — 6 cycles
        self.address = self.fetch()
        self.idle()
        self.push(self.PC >> 8)
        self.push(self.PC >> 0)
        self.address = 0xff00 | self.address
        self.idle()
        self.PC = self.address

    def CallTable(self, vector):
        # TCALL n — 8 cycles: opcode + dummy read(PC) + idle + pushPCH + pushPCL + idle + readLo + readHi
        self.read(self.PC)  # dummy read of next byte, PC unchanged
        self.idle()
        self.push(self.PC >> 8)
        self.push(self.PC >> 0)
        self.address = 0xffde - (vector << 1)
        self.idle()
        pc = self.read(self.address + 0)
        pc |= self.read(self.address + 1) << 8
        self.address = pc
        self.PC = pc

    def ComplementCarry(self):
        # NOTC — 3 cycles
        self.idle()
        self.idle()
        self.CF = not self.CF

    def DecimalAdjustAdd(self):
        # DAA — 3 cycles
        self.idle()
        self.idle()
        if self.CF or self.A > 0x99:
            self.A = (self.A + 0x60) & 0xFF
            self.CF = True

        if self.HF or (self.A & 15) > 0x09:
            self.A = (self.A + 0x06) & 0xFF

        self.ZF = self.A == 0
        self.NF = bool(self.A & 0x80)

    def DecimalAdjustSub(self):
        # DAS — 3 cycles
        self.idle()
        self.idle()
        if not self.CF or self.A > 0x99:
            self.A = (self.A - 0x60) & 0xFF
            self.CF = False

        if not self.HF or (self.A & 15) > 0x09:
            self.A = (self.A - 0x06) & 0xFF

        self.ZF = self.A == 0
        self.NF = bool(self.A & 0x80)

    def DirectRead(self, func, reg):
        self.address = self.fetch()
        self.data = self.load(self.address)
        self.data = func(self, getattr(self, reg), self.data)
        setattr(self, reg, self.data)

    def DirectModify(self, func):
        # ASL/LSR/ROL/ROR/INC/DEC dp — 4 cycles
        self.address = self.fetch()
        data = self.load(self.address)
        self.data = func(self, data)
        self.store(self.address, self.data)

    def DirectWrite(self, reg):
        # MOV dp,A/X/Y — 4 cycles: opcode + fetch_dp + dummy_read + write
        self.data = getattr(self, reg)
        self.address = self.fetch()
        self.load(self.address)  # dummy read before write (hardware behaviour)
        self.store(self.address, self.data)

    def DirectDirectCompare(self, func):
        # CMP dp1,dp2 — 6 cycles: opcode + fetch_src + load_src + fetch_tgt + load_tgt + idle
        source = self.fetch()
        rhs = self.load(source)
        target = self.fetch()
        lhs = self.load(target)
        self.idle()
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
        # CMP dp,#i — 5 cycles
        immediate = self.fetch()
        self.address = self.fetch()
        self.data = self.load(self.address)
        self.idle()
        func(self, self.data, immediate)

    def DirectImmediateModify(self, func):
        # AND/OR/EOR dp,#i (modify variant) — 5 cycles
        immediate = self.fetch()
        self.address = self.fetch()
        self.data = self.load(self.address)
        self.data = func(self, self.data, immediate)
        self.store(self.address, self.data)

    def DirectImmediateWrite(self):
        # MOV dp,#i — 5 cycles (includes a dummy read of the destination)
        self.data = self.fetch()
        self.address = self.fetch()
        self.load(self.address)  # dummy read before write (hardware behaviour)
        self.store(self.address, self.data)

    def DirectCompareWord(self, func):
        # CMPW YA,dp — 4 cycles
        self.address = self.fetch()
        self.data = self.load(self.address + 0)
        self.data |= self.load(self.address + 1) << 8
        self.data &= 0xFFFF
        self.YA = func(self, self.YA, self.data)

    def DirectReadWord(self, func):
        # ADDW/SUBW YA,dp — 5 cycles
        self.address = self.fetch()
        self.data = self.load(self.address + 0) | self.load(self.address + 1) << 8
        self.idle()
        self.YA = func(self, self.YA, self.data)

    def DirectModifyWord(self, adjust):
        # INCW/DECW dp — 6 cycles: opcode + fetch + read_lo + write_lo + read_hi + write_hi
        self.address = self.fetch()
        lo = self.load(self.address)
        lo_new = (lo + adjust) & 0xFF
        borrow_carry = (lo + adjust) >> 8  # -1 (borrow) or +1 (carry) or 0
        self.store(self.address, lo_new)
        hi = self.load(self.address + 1)
        hi_new = (hi + borrow_carry) & 0xFF
        self.store(self.address + 1, hi_new)
        self.data = lo_new | (hi_new << 8)
        self.ZF = self.data == 0
        self.NF = bool(self.data & 0x8000)

    def DirectWriteWord(self):
        # MOVW dp,YA — 5 cycles
        self.address = self.fetch()
        self.data = self.YA
        self.load(self.address + 0)  # dummy read before word write
        self.store(self.address + 0, self.A)
        self.store(self.address + 1, self.Y)

    def DirectIndexedRead(self, func, reg_target, reg_index):
        # OP A,dp+X/Y — 4 cycles
        self.address = self.fetch()
        index = getattr(self, reg_index)
        self.idle()
        self.data = self.load((self.address + index) & 0xFF)
        target = getattr(self, reg_target)
        result = func(self, target, self.data)
        setattr(self, reg_target, result)

    def DirectIndexedModify(self, func, reg):
        # ASL/LSR/ROL/ROR/INC/DEC dp+X — 5 cycles
        index = getattr(self, reg)
        self.address = (self.fetch() + index) & 0xFF
        self.idle()
        self.data = self.load(self.address)
        self.data = func(self, self.data)
        self.store(self.address, self.data)

    def DirectIndexedWrite(self, reg_data, reg_index):
        # MOV dp+X,A / MOV dp+Y,A — 5 cycles: opcode + fetch_dp + idle + dummy_read + write
        self.data = getattr(self, reg_data)
        index = getattr(self, reg_index)
        self.address = (self.fetch() + index) & 0xFF
        self.idle()
        self.load(self.address)  # dummy read before write (hardware behaviour)
        self.store(self.address, self.data)

    def Divide(self):
        # DIV — 12 cycles
        for _ in range(11):
            self.idle()
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
        # XCN A — 5 cycles
        for _ in range(4):
            self.idle()
        self.A = (self.A >> 4 & 0x0F) | (self.A << 4 & 0xF0)
        self.ZF = self.A == 0
        self.NF = bool(self.A & 0x80)

    def FlagSet(self, flag: str, value: bool):
        # CLRC/SETC/CLRP/SETP: 2 cycles; EI/DI: 3 cycles
        self.idle()
        if flag == "IF":
            self.idle()  # EI/DI need one extra cycle
        setattr(self, flag, value)

    def ImmediateRead(self, func, reg):
        """Immediate = #i"""
        self.address = self.PC  # for debugging
        self.data = self.fetch()
        a = getattr(self, reg)
        result = func(self, a, self.data)
        setattr(self, reg, result)

    def ImpliedModify(self, func, reg):
        # ASL/LSR/ROL/ROR/INC/DEC A/X/Y — 2 cycles
        self.idle()
        data = getattr(self, reg)
        self.data = func(self, data)
        setattr(self, reg, self.data)

    def IndexedIndirectRead(self, func, reg):
        # OP A,(dp+X) — 6 cycles
        index = getattr(self, reg)
        indirect = self.fetch()
        self.idle()
        self.address = self.load(indirect + index + 0)
        self.address |= self.load(indirect + index + 1) << 8
        self.data = self.read(self.address)
        self.A = func(self, self.A, self.data)

    def IndexedIndirectWrite(self, reg_data, reg_index):
        # MOV (dp+X),A — 7 cycles: opcode + fetch + idle + ptr_lo + ptr_hi + dummy_read + write
        self.data = getattr(self, reg_data)
        index = getattr(self, reg_index)
        indirect = self.fetch()
        self.idle()
        self.address = self.load(indirect + index + 0)
        self.address |= self.load(indirect + index + 1) << 8
        self.read(self.address)  # dummy read before write (hardware behaviour)
        self.write(self.address, self.data)

    def IndirectIndexedRead(self, func, reg_index):
        # OP A,(dp)+Y — 6 cycles
        index = getattr(self, reg_index)
        indirect = self.fetch()
        self.address = self.load(indirect + 0)
        self.address |= self.load(indirect + 1) << 8
        self.address = (self.address + index) & 0xFFFF
        self.idle()
        self.data = self.read(self.address)
        self.A = func(self, self.A, self.data)

    def IndirectIndexedWrite(self, data, index):
        # MOV (dp)+Y,A — 7 cycles: opcode + fetch + ptr_lo + ptr_hi + idle + dummy_read + write
        data = getattr(self, data)
        index = getattr(self, index)
        assert index >= 0
        indirect = self.fetch()
        self.address = self.load(indirect + 0)
        self.address |= self.load(indirect + 1) << 8
        self.address = (self.address + index) & 0xFFFF
        self.idle()
        self.read(self.address)  # dummy read before write (hardware behaviour)
        self.data = data
        self.write(self.address, self.data)

    def IndirectXRead(self, func):
        # OP A,(X) — 3 cycles
        self.address = self.X
        self.idle()
        self.data = self.load(self.address)
        self.A = func(self, self.A, self.data)

    def IndirectXWrite(self, reg):
        # MOV (X),A — 4 cycles: opcode + idle + dummy_read + write
        self.data = getattr(self, reg)
        self.address = self.X
        self.idle()
        self.load(self.address)  # dummy read before write (hardware behaviour)
        self.store(self.address, self.data)

    def IndirectXIncrementRead(self, reg_data):
        # MOV A,(X)+ — 4 cycles: opcode + ghost_read + read(X) + idle
        self.idle()  # ghost read of PC+1
        self.data = self.load(self.X)
        self.X = (self.X + 1) & 0xFF
        setattr(self, reg_data, self.data)
        self.ZF = self.data == 0
        self.NF = bool(self.data & 0x80)
        self.idle()

    def IndirectXIncrementWrite(self, reg_data):
        # MOV (X)+,A — 4 cycles
        self.data = getattr(self, reg_data)
        self.address = self.X
        self.X = (self.X + 1) & 0xFF
        self.idle()
        self.store(self.address, self.data)
        self.idle()

    def IndirectXCompareIndirectY(self, func):
        # CMP (X),(Y) — 5 cycles
        self.idle()
        rhs = self.load(self.Y)
        lhs = self.load(self.X)
        self.idle()
        lhs = func(self, lhs, rhs)

    def IndirectXWriteIndirectY(self, func):
        # OP (X),(Y) — 5 cycles
        self.idle()
        rhs = self.load(self.Y)
        lhs = self.load(self.X)
        lhs = func(self, lhs, rhs)
        self.store(self.X, lhs)

    def JumpAbsolute(self):
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.PC = self.address

    def JumpIndirectX(self):
        # JMP (!a+X) — 6 cycles
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.address = (self.address + self.X) & 0xFFFF
        self.idle()
        pc = self.read(self.address)
        pc |= self.read((self.address + 1) & 0xFFFF) << 8
        self.PC = pc & 0xFFFF

    def Multiply(self):
        # MUL — 9 cycles
        for _ in range(8):
            self.idle()
        ya = (self.Y * self.A) & 0xFFFF
        self.A = ya >> 0 & 0xFF
        self.Y = ya >> 8 & 0xFF
        # result is set based on y (high-byte) only
        self.ZF = self.Y == 0
        self.NF = bool(self.Y & 0x80)

    def NoOperation(self):
        # NOP — 2 cycles
        self.idle()

    def OverflowClear(self):
        # CLRV — 2 cycles
        self.idle()
        self.HF = False
        self.VF = False

    def Pull(self, reg):
        # POP reg — 4 cycles
        self.idle()
        self.idle()
        data = self.pull()
        setattr(self, reg, data)

    def PullP(self):
        # POP PSW — 4 cycles
        self.idle()
        self.idle()
        self.PSW = self.pull()

    def Push(self, reg: str):
        # PUSH reg — 4 cycles
        self.idle()
        self.idle()
        data = getattr(self, reg)
        self.push(data)

    def ReturnInterrupt(self):
        # RTI — 6 cycles
        self.idle()
        self.PSW = self.pull()
        self.address = self.pull()
        self.address |= self.pull() << 8
        self.PC = self.address
        self.idle()

    def ReturnSubroutine(self):
        # RTS — 5 cycles
        self.idle()
        self.address = self.pull()
        self.address |= self.pull() << 8
        self.PC = self.address
        self.idle()

    def Stop(self):
        # STOP — loops with ghost reads (null value) and waits; 3 iterations = 6 extra cycles
        for _ in range(3):
            self.idle()  # ghost read of PC (null value, not tracked as memory access)
            self.idle()  # internal wait

    def TestSetBitsAbsolute(self, bit_set):
        # TSET1/TCLR1 !a — 6 cycles: opcode + lo + hi + read + read(dummy) + write
        self.address = self.fetch()
        self.address |= self.fetch() << 8
        self.data = self.read(self.address)
        self.ZF = (self.A - self.data) & 0xFF == 0
        self.NF = bool((self.A - self.data) & 0x80)
        self.read(self.address)  # second read (dummy before write, hardware behaviour)
        self.write(self.address, self.data | self.A if bit_set else self.data & ~self.A & 0xFF)

    def Transfer(self, src, dst):
        # MOV reg,reg — 2 cycles
        self.idle()
        self.data = getattr(self, src)
        setattr(self, dst, self.data)
        if dst != "S":  # TXS does not affect flags; other transfers do
            self.ZF = self.data == 0
            self.NF = bool(self.data & 0x80)

    def Wait(self):
        # SLEEP — loops with ghost reads (null value) and waits; 3 iterations = 6 extra cycles
        for _ in range(3):
            self.idle()  # ghost read of PC (null value, not tracked as memory access)
            self.idle()  # internal wait
