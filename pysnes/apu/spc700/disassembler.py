from ctypes import c_int8

from .instructions_spc700 import INSTRUCTIONS
from .opcodes_spc700 import SPC700Opcodes

_OPNAMES = {
    SPC700Opcodes.OR: "OR",
    SPC700Opcodes.AND: "AND",
    SPC700Opcodes.EOR: "EOR",
    SPC700Opcodes.CMP: "CMP",
    SPC700Opcodes.ADC: "ADC",
    SPC700Opcodes.SBC: "SBC",
    SPC700Opcodes.LD: "MOV",
    SPC700Opcodes.ASL: "ASL",
    SPC700Opcodes.LSR: "LSR",
    SPC700Opcodes.ROL: "ROL",
    SPC700Opcodes.ROR: "ROR",
    SPC700Opcodes.INC: "INC",
    SPC700Opcodes.DEC: "DEC",
    SPC700Opcodes.ADW: "ADDW",
    SPC700Opcodes.SBW: "SUBW",
    SPC700Opcodes.CPW: "CMPW",
    SPC700Opcodes.LDW: "MOVW",
}

_BRANCH_MNEMS = {
    0x10: "BPL",
    0x30: "BMI",
    0x50: "BVC",
    0x70: "BVS",
    0x90: "BCC",
    0xB0: "BCS",
    0xD0: "BNE",
    0xF0: "BEQ",
    0x2F: "BRA",
}

_ABS_BIT_MODS = [
    ("OR1", "C,${a:04X}.{b}"),
    ("OR1", "C,/${a:04X}.{b}"),
    ("AND1", "C,${a:04X}.{b}"),
    ("AND1", "C,/${a:04X}.{b}"),
    ("EOR1", "C,${a:04X}.{b}"),
    ("MOV1", "C,${a:04X}.{b}"),
    ("MOV1", "${a:04X}.{b},C"),
    ("NOT1", "${a:04X}.{b}"),
]


def _rel(byte, pc_after):
    return (pc_after + c_int8(byte).value) & 0xFFFF


def _build_table():
    table = [("???", 0, lambda pc: "")] * 256

    for entry in INSTRUCTIONS:
        opcode, addr_mode, *args = entry
        name = addr_mode.__name__

        if name == "NoOperation":
            table[opcode] = ("NOP", 0, lambda pc: "")

        elif name == "Wait":
            table[opcode] = ("SLEEP", 0, lambda pc: "")

        elif name == "Stop":
            table[opcode] = ("STOP", 0, lambda pc: "")

        elif name == "Break":
            table[opcode] = ("BRK", 0, lambda pc: "")

        elif name == "OverflowClear":
            table[opcode] = ("CLRV", 0, lambda pc: "")

        elif name == "ComplementCarry":
            table[opcode] = ("NOTC", 0, lambda pc: "")

        elif name == "DecimalAdjustAdd":
            table[opcode] = ("DAA", 0, lambda pc: "")

        elif name == "DecimalAdjustSub":
            table[opcode] = ("DAS", 0, lambda pc: "")

        elif name == "Divide":
            table[opcode] = ("DIV", 0, lambda pc: "YA,X")

        elif name == "ExchangeNibble":
            table[opcode] = ("XCN", 0, lambda pc: "A")

        elif name == "Multiply":
            table[opcode] = ("MUL", 0, lambda pc: "YA")

        elif name == "ReturnSubroutine":
            table[opcode] = ("RET", 0, lambda pc: "")

        elif name == "ReturnInterrupt":
            table[opcode] = ("RETI", 0, lambda pc: "")

        elif name == "CallTable":
            n = args[0]
            table[opcode] = ("TCALL", 0, lambda pc, _n=n: f"{_n}")

        elif name == "FlagSet":
            flag, val = args
            mnem = {
                ("CF", False): "CLRC",
                ("CF", True): "SETC",
                ("PF", False): "CLRP",
                ("PF", True): "SETP",
                ("IF", True): "EI",
                ("IF", False): "DI",
            }[(flag, val)]
            table[opcode] = (mnem, 0, lambda pc: "")

        elif name == "Push":
            reg = args[0]
            table[opcode] = ("PUSH", 0, lambda pc, r=reg: r)

        elif name == "Pull":
            reg = args[0]
            table[opcode] = ("POP", 0, lambda pc, r=reg: r)

        elif name == "PullP":
            table[opcode] = ("POP", 0, lambda pc: "PSW")

        elif name == "Transfer":
            src, dst = args
            table[opcode] = ("MOV", 0, lambda pc, d=dst, s=src: f"{d},{s}")

        elif name == "IndirectXRead":
            func = args[0]
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 0, lambda pc: "A,(X)")

        elif name == "IndirectXWrite":
            reg = args[0]
            table[opcode] = ("MOV", 0, lambda pc, r=reg: f"(X),{r}")

        elif name == "IndirectXIncrementRead":
            table[opcode] = ("MOV", 0, lambda pc: "A,(X)+")

        elif name == "IndirectXIncrementWrite":
            table[opcode] = ("MOV", 0, lambda pc: "(X)+,A")

        elif name == "IndirectXWriteIndirectY":
            func = args[0]
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 0, lambda pc: "(X),(Y)")

        elif name == "IndirectXCompareIndirectY":
            table[opcode] = ("CMP", 0, lambda pc: "(X),(Y)")

        elif name == "ImpliedModify":
            func, reg = args
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 0, lambda pc, r=reg: r)

        elif name == "Branch":
            mnem = _BRANCH_MNEMS.get(opcode, "B??")
            table[opcode] = (mnem, 1, lambda pc, b: f"${_rel(b, pc + 2):04X}")

        elif name == "BranchNotYDecrement":
            table[opcode] = (
                "DBNZ",
                1,
                lambda pc, b: f"Y,${_rel(b, pc + 2):04X}",
            )

        elif name == "BranchNotDirect":
            table[opcode] = (
                "CBNE",
                2,
                lambda pc, d, r: f"${d:02X},${_rel(r, pc + 3):04X}",
            )

        elif name == "BranchNotDirectDecrement":
            table[opcode] = (
                "DBNZ",
                2,
                lambda pc, d, r: f"${d:02X},${_rel(r, pc + 3):04X}",
            )

        elif name == "BranchNotDirectIndexed":
            table[opcode] = (
                "CBNE",
                2,
                lambda pc, d, r: f"${d:02X}+X,${_rel(r, pc + 3):04X}",
            )

        elif name == "BranchBit":
            bit, match = args
            mnem = "BBS" if match else "BBC"
            table[opcode] = (
                mnem,
                2,
                lambda pc, d, r, b=bit: f"${d:02X}.{b},${_rel(r, pc + 3):04X}",
            )

        elif name == "AbsoluteBitSet":
            bit, val = args
            mnem = "SET1" if val else "CLR1"
            table[opcode] = (mnem, 1, lambda pc, d, b=bit: f"${d:02X}.{b}")

        elif name == "AbsoluteBitModify":
            mode = args[0]
            mnem, fmt = _ABS_BIT_MODS[mode]
            table[opcode] = (
                mnem,
                2,
                lambda pc, lo, hi, _fmt=fmt, _m=mode: _fmt.format(
                    a=(hi << 8 | lo) & 0x1FFF, b=(hi << 8 | lo) >> 13
                ),
            )

        elif name == "ImmediateRead":
            func, reg = args
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 1, lambda pc, i, r=reg: f"{r},#${i:02X}")

        elif name == "DirectRead":
            func, reg = args
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 1, lambda pc, d, r=reg: f"{r},${d:02X}")

        elif name == "DirectModify":
            func = args[0]
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 1, lambda pc, d: f"${d:02X}")

        elif name == "DirectWrite":
            reg = args[0]
            table[opcode] = ("MOV", 1, lambda pc, d, r=reg: f"${d:02X},{r}")

        elif name == "DirectModifyWord":
            mnem = "INCW" if args[0] > 0 else "DECW"
            table[opcode] = (mnem, 1, lambda pc, d: f"${d:02X}")

        elif name == "DirectIndexedRead":
            func, reg_t, reg_i = args
            mnem = _OPNAMES[func]
            table[opcode] = (
                mnem,
                1,
                lambda pc, d, rt=reg_t, ri=reg_i: f"{rt},${d:02X}+{ri}",
            )

        elif name == "DirectIndexedModify":
            func, reg = args
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 1, lambda pc, d, r=reg: f"${d:02X}+{r}")

        elif name == "DirectIndexedWrite":
            reg_d, reg_i = args
            table[opcode] = (
                "MOV",
                1,
                lambda pc, d, rd=reg_d, ri=reg_i: f"${d:02X}+{ri},{rd}",
            )

        elif name == "IndexedIndirectRead":
            func, reg = args
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 1, lambda pc, d, r=reg: f"A,(${d:02X}+{r})")

        elif name == "IndirectIndexedRead":
            func, reg = args
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 1, lambda pc, d, r=reg: f"A,(${d:02X})+{r}")

        elif name == "IndexedIndirectWrite":
            reg_d, reg_i = args
            table[opcode] = (
                "MOV",
                1,
                lambda pc, d, rd=reg_d, ri=reg_i: f"(${d:02X}+{ri}),{rd}",
            )

        elif name == "IndirectIndexedWrite":
            reg_d, reg_i = args
            table[opcode] = (
                "MOV",
                1,
                lambda pc, d, rd=reg_d, ri=reg_i: f"(${d:02X})+{ri},{rd}",
            )

        elif name == "DirectReadWord":
            func = args[0]
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 1, lambda pc, d: f"YA,${d:02X}")

        elif name == "DirectWriteWord":
            table[opcode] = ("MOVW", 1, lambda pc, d: f"${d:02X},YA")

        elif name == "DirectCompareWord":
            table[opcode] = ("CMPW", 1, lambda pc, d: f"YA,${d:02X}")

        elif name == "DirectDirectModify" or name == "DirectDirectCompare":
            func = args[0]
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 2, lambda pc, s, t: f"${t:02X},${s:02X}")

        elif name == "DirectDirectWrite":
            table[opcode] = ("MOV", 2, lambda pc, s, t: f"${t:02X},${s:02X}")

        elif name == "DirectImmediateModify":
            func = args[0]
            mnem = _OPNAMES[func]
            table[opcode] = (mnem, 2, lambda pc, i, d: f"${d:02X},#${i:02X}")

        elif name == "DirectImmediateCompare":
            table[opcode] = ("CMP", 2, lambda pc, i, d: f"${d:02X},#${i:02X}")

        elif name == "DirectImmediateWrite":
            table[opcode] = ("MOV", 2, lambda pc, i, d: f"${d:02X},#${i:02X}")

        elif name == "AbsoluteRead":
            func, reg = args
            mnem = _OPNAMES[func]
            table[opcode] = (
                mnem,
                2,
                lambda pc, lo, hi, r=reg: f"{r},${(hi << 8 | lo):04X}",
            )

        elif name == "AbsoluteModify":
            func = args[0]
            mnem = _OPNAMES[func]
            table[opcode] = (
                mnem,
                2,
                lambda pc, lo, hi: f"${(hi << 8 | lo):04X}",
            )

        elif name == "AbsoluteWrite":
            reg = args[0]
            table[opcode] = (
                "MOV",
                2,
                lambda pc, lo, hi, r=reg: f"${(hi << 8 | lo):04X},{r}",
            )

        elif name == "AbsoluteIndexedRead":
            func, reg = args
            mnem = _OPNAMES[func]
            table[opcode] = (
                mnem,
                2,
                lambda pc, lo, hi, r=reg: f"A,${(hi << 8 | lo):04X}+{r}",
            )

        elif name == "AbsoluteIndexedWrite":
            reg = args[0]
            table[opcode] = (
                "MOV",
                2,
                lambda pc, lo, hi, r=reg: f"${(hi << 8 | lo):04X}+{r},A",
            )

        elif name == "TestSetBitsAbsolute":
            mnem = "TSET1" if args[0] else "TCLR1"
            table[opcode] = (
                mnem,
                2,
                lambda pc, lo, hi: f"${(hi << 8 | lo):04X}",
            )

        elif name == "JumpAbsolute":
            table[opcode] = (
                "JMP",
                2,
                lambda pc, lo, hi: f"${(hi << 8 | lo):04X}",
            )

        elif name == "JumpIndirectX":
            table[opcode] = (
                "JMP",
                2,
                lambda pc, lo, hi: f"(${(hi << 8 | lo):04X}+X)",
            )

        elif name == "CallAbsolute":
            table[opcode] = (
                "JSR",
                2,
                lambda pc, lo, hi: f"${(hi << 8 | lo):04X}",
            )

        elif name == "CallPage":
            table[opcode] = ("PCALL", 1, lambda pc, d: f"${d:02X}")

    return table


_TABLE = _build_table()


class SPC700Disassembler:
    def __init__(self, apu):
        self.apu = apu

    def _peek(self, addr):
        addr &= 0xFFFF
        if addr <= 0x00EF:
            return self.apu.page_0[addr]
        if addr <= 0x00FF:
            return 0  # I/O region — skip side-effect read
        if addr <= 0x01FF:
            return self.apu.page_1[addr - 0x0100]
        if addr <= 0xFFBF:
            return self.apu.memory[addr - 0x0200]
        return self.apu.ipl_rom[addr - 0xFFC0]

    def disassemble(self, pc):
        opcode = self._peek(pc)
        mnem, n_bytes, fmt_fn = _TABLE[opcode]
        operands = [self._peek((pc + 1 + i) & 0xFFFF) for i in range(n_bytes)]
        operand_str = fmt_fn(pc, *operands)
        return f"{pc:04X}  {mnem:<5} {operand_str}"
