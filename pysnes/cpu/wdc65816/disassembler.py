from ctypes import c_uint8, c_int8, c_uint16, c_int16
import cython  # https://cython.readthedocs.io/en/latest/src/quickstart/cythonize.html
from ..cpu import Cpu


class Disassembler:
    def __init__(self, cpu: Cpu) -> None:
        self.cpu = cpu
        self.build_table()

    def read(self, address):
        # $00-3f,80-bf:2000-5fff: do not attempt to read I/O registers from the disassembler:
        # this is because such reads are much more likely to have side effects to emulation.
        if((address & 0x40ffff) >= 0x2000 and (address & 0x40ffff) <= 0x5fff):
            return 0x00

        return self.cpu.read(address)
        # return readDisassembler(address);

    def readByte(self, address):
        return self.read(address)

    def readWord(self, address):
        data = self.readByte(address + 0) << 0
        return data | self.readByte(address + 1) << 8

    def readLong(self, address):
        data = self.readByte(address + 0) << 0
        return data | self.readWord(address + 1) << 8

    def disassemble(self, address: int) -> str:
        """Disassemble the instruction at the given address"""
        self.pc = address
        self.effective = 0

        self.opcode   = self.read(address); address = (address + 1) & 0xFFFF;  # address.bit(0,15)++;
        self.operand0 = self.read(address); address = (address + 1) & 0xFFFF;  # address.bit(0,15)++;
        self.operand1 = self.read(address); address = (address + 1) & 0xFFFF;  # address.bit(0,15)++;
        self.operand2 = self.read(address); address = (address + 1) & 0xFFFF;  # address.bit(0,15)++;

        self.operandByte = self.operand0 << 0
        self.operandWord = self.operand0 << 0 | self.operand1 << 8
        self.operandLong = self.operand0 << 0 | self.operand1 << 8 | self.operand2 << 16

        _, name, func = self.TABLE[self.opcode]
        operand = func()

        s = f"{self.pc:06X} {name} {operand.ljust(10, ' ')} [{self.effective:06X}] "

        s += f"A:{self.cpu.A.w:04X} X:{self.cpu.X.w:04X} Y:{self.cpu.Y.w:04X} S:{self.cpu.S.w:04X} D:{self.cpu.D.w:04X} DB:{self.cpu.DB.l:02X} "

        if self.cpu.EF:
            s += "N" if self.cpu.NFlag else "n"
            s += "V" if self.cpu.VFlag else "v"
            s += "1" if self.cpu.MFlag else "0"
            s += "B" if self.cpu.XFlag else "b"
            s += "D" if self.cpu.DFlag else "d"
            s += "I" if self.cpu.IFlag else "i"
            s += "Z" if self.cpu.ZFlag else "z"
            s += "C" if self.cpu.CFlag else "c"
        else:
            s += "N" if self.cpu.NFlag else "n"
            s += "V" if self.cpu.VFlag else "v"
            s += "M" if self.cpu.MFlag else "m"
            s += "X" if self.cpu.XFlag else "x"
            s += "D" if self.cpu.DFlag else "d"
            s += "I" if self.cpu.IFlag else "i"
            s += "Z" if self.cpu.ZFlag else "z"
            s += "C" if self.cpu.CFlag else "c"

        return s

    def absolute(self):
        self.effective = self.cpu.PC.b << 16 | self.operandWord
        return f"${self.operandWord:04X}"

    def absolutePC(self):
        self.effective = self.pc & 0xff0000 | self.operandWord
        return f"${self.operandWord:04X}"

    def absoluteX(self):
        self.effective = (self.cpu.PC.b << 16) + self.operandWord + self.cpu.X.w
        return f"${self.operandWord:04X},x"

    def absoluteY(self):
        self.effective = (self.cpu.PC.b << 16) + self.operandWord + self.cpu.Y.w
        return f"${self.operandWord:04X},y"

    def absoluteLong(self):
        self.effective = self.operandLong
        return f"${self.operandLong:06X}"

    def absoluteLongX(self):
        self.effective = self.operandLong + self.cpu.X.w
        return f"${self.operandLong:06X},x"

    def direct(self):
        self.effective = self.cpu.D.w + self.operandByte
        return f"${self.operandByte:02X}"

    def directX(self):
        self.effective = self.cpu.D.w + self.operandByte + self.cpu.X.w
        return f"${self.operandByte:02X},x"

    def directY(self):
        self.effective = c_uint16(self.cpu.D.w + self.operandByte + self.cpu.Y.w).value
        return f"${self.operandByte:02X},y"

    def immediate(self):
        return f"#${self.operandByte:02X}"

    def immediateA(self):
        if self.cpu.MFlag:
            return f"#${self.operandByte:02X}"
        return f"#${self.operandWord:04X}"

    def immediateX(self):
        if self.cpu.XFlag:
            return f"#${self.operandByte:02X}"
        return f"#${self.operandWord:04X}"

    def implied(self):
        return ""

    def indexedIndirectX(self):
        self.effective = c_uint16(self.cpu.D.w + self.operandByte + self.cpu.X.w).value
        self.effective = self.cpu.PC.b << 16 | self.readWord(self.effective)
        return f"(${self.operandByte:02X},x)"

    def indirect(self):
        self.effective = c_uint16(self.cpu.D.w + self.operandByte).value
        self.effective = self.cpu.PC.b << 16 | self.readWord(self.effective)
        return f"(${self.operandByte:02X})"

    def indirectPC(self):
        self.effective = self.operandWord
        self.effective = self.pc & 0xff0000 | self.readWord(self.effective)
        return f"(${self.operandWord:04X})"

    def indirectX(self):
        self.effective = self.operandWord
        self.effective = self.pc & 0xff0000 | c_uint16(self.effective + self.cpu.X.w).value
        self.effective = self.pc & 0xff0000 | self.readWord(self.effective)
        return f"(${self.operandWord:04X},x)"

    def indirectIndexedY(self):
        self.effective = c_uint16(self.cpu.D.w + self.operandByte).value
        self.effective = (self.cpu.PC.b << 16) + self.readWord(self.effective) + self.cpu.Y.w
        return f"(${self.operandByte:02X}),y"

    def indirectLong(self):
        self.effective = c_uint16(self.cpu.D.w + self.operandByte).value
        self.effective = self.readLong(self.effective)
        return f"[${self.operandByte:02X}]"

    def indirectLongPC(self):
        self.effective = self.readLong(self.operandWord)
        return f"[${self.operandWord:04X}]"

    def indirectLongY(self):
        self.effective = c_uint16(self.cpu.D.w + self.operandByte).value
        self.effective = self.readLong(self.effective) + self.cpu.Y.w
        return f"[${self.operandByte:02X}],y"

    def move(self):
        return f"${self.operand0:02X}=${self.operand1:02X}"

    def relative(self):
        self.effective = self.pc & 0xff0000 | c_uint16(self.pc + 2 + c_int8(self.operandByte).value).value
        return f"${self.effective:04X}"

    def relativeWord(self):
        self.effective = self.pc & 0xff0000 | c_uint16(self.pc + 3 + c_int16(self.operandWord).value).value
        return f"${self.effective:04X}"

    def stack(self):
        self.effective = c_uint16(self.cpu.S.w + self.operandByte).value
        return f"${self.operandByte:02X},s"

    def stackIndirect(self):
        self.effective = c_uint16(self.operandByte + self.cpu.S.w).value
        self.effective = (self.cpu.PC.b << 16) + self.readWord(self.effective) + self.cpu.Y.w
        return f"(${self.operandByte:02X},s),y)"

    def build_table(self) -> None:
        """Build the instruction table"""
        # NOTE: This is a list of tuples.
        # The first element is the opcode,
        # the second element is the mnemonic,
        # and the third element is the addressing mode.
        self.TABLE = [
            (0x00, "brk", self.immediate),
            (0x01, "ora", self.indexedIndirectX),
            (0x02, "cop", self.immediate),
            (0x03, "ora", self.stack),
            (0x04, "tsb", self.direct),
            (0x05, "ora", self.direct),
            (0x06, "asl", self.direct),
            (0x07, "ora", self.indirectLong),
            (0x08, "php", self.implied),
            (0x09, "ora", self.immediateA),
            (0x0A, "asl", self.implied),
            (0x0B, "phd", self.implied),
            (0x0C, "tsb", self.absolute),
            (0x0D, "ora", self.absolute),
            (0x0E, "asl", self.absolute),
            (0x0F, "ora", self.absoluteLong),
            (0x10, "bpl", self.relative),
            (0x11, "ora", self.indirectIndexedY),
            (0x12, "ora", self.indirect),
            (0x13, "ora", self.stackIndirect),
            (0x14, "trb", self.direct),
            (0x15, "ora", self.directX),
            (0x16, "asl", self.directX),
            (0x17, "ora", self.indirectLongY),
            (0x18, "clc", self.implied),
            (0x19, "ora", self.absoluteY),
            (0x1A, "inc", self.implied),
            (0x1B, "tas", self.implied),
            (0x1C, "trb", self.absolute),
            (0x1D, "ora", self.absoluteX),
            (0x1E, "asl", self.absoluteX),
            (0x1F, "ora", self.absoluteLongX),
            (0x20, "jsr", self.absolutePC),
            (0x21, "and", self.indexedIndirectX),
            (0x22, "jsl", self.absoluteLong),
            (0x23, "and", self.stack),
            (0x24, "bit", self.direct),
            (0x25, "and", self.direct),
            (0x26, "rol", self.direct),
            (0x27, "and", self.indirectLong),
            (0x28, "plp", self.implied),
            (0x29, "and", self.immediateA),
            (0x2A, "rol", self.implied),
            (0x2B, "pld", self.implied),
            (0x2C, "bit", self.absolute),
            (0x2D, "and", self.absolute),
            (0x2E, "rol", self.absolute),
            (0x2F, "and", self.absoluteLong),
            (0x30, "bmi", self.relative),
            (0x31, "and", self.indirectIndexedY),
            (0x32, "and", self.indirect),
            (0x33, "and", self.stackIndirect),
            (0x34, "bit", self.directX),
            (0x35, "and", self.directX),
            (0x36, "rol", self.directX),
            (0x37, "and", self.indirectLongY),
            (0x38, "sec", self.implied),
            (0x39, "and", self.absoluteY),
            (0x3A, "dec", self.implied),
            (0x3B, "tsa", self.implied),
            (0x3C, "bit", self.absoluteX),
            (0x3D, "and", self.absoluteX),
            (0x3E, "rol", self.absoluteX),
            (0x3F, "and", self.absoluteLongX),
            (0x40, "rti", self.implied),
            (0x41, "eor", self.indexedIndirectX),
            (0x42, "wdm", self.immediate),
            (0x43, "eor", self.stack),
            (0x44, "mvp", self.move),
            (0x45, "eor", self.direct),
            (0x46, "lsr", self.direct),
            (0x47, "eor", self.indirectLong),
            (0x48, "pha", self.implied),
            (0x49, "eor", self.immediateA),
            (0x4A, "lsr", self.implied),
            (0x4B, "phk", self.implied),
            (0x4C, "jmp", self.absolutePC),
            (0x4D, "eor", self.absolute),
            (0x4E, "lsr", self.absolute),
            (0x4F, "eor", self.absoluteLong),
            (0x50, "bvc", self.relative),
            (0x51, "eor", self.indirectIndexedY),
            (0x52, "eor", self.indirect),
            (0x53, "eor", self.stackIndirect),
            (0x54, "mvn", self.move),
            (0x55, "eor", self.directX),
            (0x56, "lsr", self.directX),
            (0x57, "eor", self.indirectLongY),
            (0x58, "cli", self.implied),
            (0x59, "eor", self.absoluteY),
            (0x5A, "phy", self.implied),
            (0x5B, "tcd", self.implied),
            (0x5C, "jml", self.absoluteLong),
            (0x5D, "eor", self.absoluteX),
            (0x5E, "lsr", self.absoluteX),
            (0x5F, "eor", self.absoluteLongX),
            (0x60, "rts", self.implied),
            (0x61, "adc", self.indexedIndirectX),
            (0x62, "per", self.absolute),
            (0x63, "adc", self.stack),
            (0x64, "stz", self.direct),
            (0x65, "adc", self.direct),
            (0x66, "ror", self.direct),
            (0x67, "adc", self.indirectLong),
            (0x68, "pla", self.implied),
            (0x69, "adc", self.immediateA),
            (0x6A, "ror", self.implied),
            (0x6B, "rtl", self.implied),
            (0x6C, "jmp", self.indirectPC),
            (0x6D, "adc", self.absolute),
            (0x6E, "ror", self.absolute),
            (0x6F, "adc", self.absoluteLong),
            (0x70, "bvs", self.relative),
            (0x71, "adc", self.indirectIndexedY),
            (0x72, "adc", self.indirect),
            (0x73, "adc", self.stackIndirect),
            (0x74, "stz", self.directX),
            (0x75, "adc", self.directX),
            (0x76, "ror", self.directX),
            (0x77, "adc", self.indirectLongY),
            (0x78, "sei", self.implied),
            (0x79, "adc", self.absoluteY),
            (0x7A, "ply", self.implied),
            (0x7B, "tda", self.implied),
            (0x7C, "jmp", self.indirectX),
            (0x7D, "adc", self.absoluteX),
            (0x7E, "ror", self.absoluteX),
            (0x7F, "adc", self.absoluteLongX),
            (0x80, "bra", self.relative),
            (0x81, "sta", self.indexedIndirectX),
            (0x82, "brl", self.relativeWord),
            (0x83, "sta", self.stack),
            (0x84, "sty", self.direct),
            (0x85, "sta", self.direct),
            (0x86, "stx", self.direct),
            (0x87, "sta", self.indirectLong),
            (0x88, "dey", self.implied),
            (0x89, "bit", self.immediateA),
            (0x8A, "txa", self.implied),
            (0x8B, "phb", self.implied),
            (0x8C, "sty", self.absolute),
            (0x8D, "sta", self.absolute),
            (0x8E, "stx", self.absolute),
            (0x8F, "sta", self.absoluteLong),
            (0x90, "bcc", self.relative),
            (0x91, "sta", self.indirectIndexedY),
            (0x92, "sta", self.indirect),
            (0x93, "sta", self.stackIndirect),
            (0x94, "sty", self.directX),
            (0x95, "sta", self.directX),
            (0x96, "stx", self.directY),
            (0x97, "sta", self.indirectLongY),
            (0x98, "tya", self.implied),
            (0x99, "sta", self.absoluteY),
            (0x9A, "txs", self.implied),
            (0x9B, "txy", self.implied),
            (0x9C, "stz", self.absolute),
            (0x9D, "sta", self.absoluteX),
            (0x9E, "stz", self.absoluteX),
            (0x9F, "sta", self.absoluteLongX),
            (0xA0, "ldy", self.immediateX),
            (0xA1, "lda", self.indexedIndirectX),
            (0xA2, "ldx", self.immediateX),
            (0xA3, "lda", self.stack),
            (0xA4, "ldy", self.direct),
            (0xA5, "lda", self.direct),
            (0xA6, "ldx", self.direct),
            (0xA7, "lda", self.indirectLong),
            (0xA8, "tay", self.implied),
            (0xA9, "lda", self.immediateA),
            (0xAA, "tax", self.implied),
            (0xAB, "plb", self.implied),
            (0xAC, "ldy", self.absolute),
            (0xAD, "lda", self.absolute),
            (0xAE, "ldx", self.absolute),
            (0xAF, "lda", self.absoluteLong),
            (0xB0, "bcs", self.relative),
            (0xB1, "lda", self.indirectIndexedY),
            (0xB2, "lda", self.indirect),
            (0xB3, "lda", self.stackIndirect),
            (0xB4, "ldy", self.directX),
            (0xB5, "lda", self.directX),
            (0xB6, "ldx", self.directY),
            (0xB7, "lda", self.indirectLongY),
            (0xB8, "clv", self.implied),
            (0xB9, "lda", self.absoluteY),
            (0xBA, "tsx", self.implied),
            (0xBB, "tyx", self.implied),
            (0xBC, "ldy", self.absoluteX),
            (0xBD, "lda", self.absoluteX),
            (0xBE, "ldx", self.absoluteY),
            (0xBF, "lda", self.absoluteLongX),
            (0xC0, "cpy", self.immediateX),
            (0xC1, "cmp", self.indexedIndirectX),
            (0xC2, "rep", self.immediate),
            (0xC3, "cmp", self.stack),
            (0xC4, "cpy", self.direct),
            (0xC5, "cmp", self.direct),
            (0xC6, "dec", self.direct),
            (0xC7, "cmp", self.indirectLong),
            (0xC8, "iny", self.implied),
            (0xC9, "cmp", self.immediateA),
            (0xCA, "dex", self.implied),
            (0xCB, "wai", self.implied),
            (0xCC, "cpy", self.absolute),
            (0xCD, "cmp", self.absolute),
            (0xCE, "dec", self.absolute),
            (0xCF, "cmp", self.absoluteLong),
            (0xD0, "bne", self.relative),
            (0xD1, "cmp", self.indirectIndexedY),
            (0xD2, "cmp", self.indirect),
            (0xD3, "cmp", self.stackIndirect),
            (0xD4, "pei", self.indirect),
            (0xD5, "cmp", self.directX),
            (0xD6, "dec", self.directX),
            (0xD7, "cmp", self.indirectLongY),
            (0xD8, "cld", self.implied),
            (0xD9, "cmp", self.absoluteY),
            (0xDA, "phx", self.implied),
            (0xDB, "stp", self.implied),
            (0xDC, "jmp", self.indirectLongPC),
            (0xDD, "cmp", self.absoluteX),
            (0xDE, "dec", self.absoluteX),
            (0xDF, "cmp", self.absoluteLongX),
            (0xE0, "cpx", self.immediateX),
            (0xE1, "sbc", self.indexedIndirectX),
            (0xE2, "sep", self.immediate),
            (0xE3, "sbc", self.stack),
            (0xE4, "cpx", self.direct),
            (0xE5, "sbc", self.direct),
            (0xE6, "inc", self.direct),
            (0xE7, "sbc", self.indirectLong),
            (0xE8, "inx", self.implied),
            (0xE9, "sbc", self.immediateA),
            (0xEA, "nop", self.implied),
            (0xEB, "xba", self.implied),
            (0xEC, "cpx", self.absolute),
            (0xED, "sbc", self.absolute),
            (0xEE, "inc", self.absolute),
            (0xEF, "sbc", self.absoluteLong),
            (0xF0, "beq", self.relative),
            (0xF1, "sbc", self.indirectIndexedY),
            (0xF2, "sbc", self.indirect),
            (0xF3, "sbc", self.stackIndirect),
            (0xF4, "pea", self.absolute),
            (0xF5, "sbc", self.directX),
            (0xF6, "inc", self.directX),
            (0xF7, "sbc", self.indirectLongY),
            (0xF8, "sed", self.implied),
            (0xF9, "sbc", self.absoluteY),
            (0xFA, "plx", self.implied),
            (0xFB, "xce", self.implied),
            (0xFC, "jsr", self.indirectX),
            (0xFD, "sbc", self.absoluteX),
            (0xFE, "inc", self.absoluteX),
            (0xFF, "sbc", self.absoluteLongX),
        ]
