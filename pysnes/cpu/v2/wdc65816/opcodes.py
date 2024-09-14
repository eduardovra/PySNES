from ..cpu import Cpu


# TODO remove once all opcodes are implemented
def __getattr__(name: str):
    def not_implemented(*args, **kwargs):
        raise NotImplementedError(name)
    try:
        return globals()[name]
    except KeyError:
        return not_implemented


def ADC(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        if not cpu.DF:
            result = cpu.A.l + data + cpu.CF
        else:
            result = (cpu.A.l & 0x0f) + (data & 0x0f) + (cpu.CF << 0)
            if result > 0x09:
                result += 0x06
            cpu.CF = result > 0x0f
            result = (cpu.A.l & 0xf0) + (data & 0xf0) + (cpu.CF << 4) + (result & 0x0f)

        cpu.VF = bool(~(cpu.A.l ^ data) & (cpu.A.l ^ result) & 0x80)
        if cpu.DF and result > 0x9f:
            result += 0x60
        cpu.CF = result > 0xff
        cpu.ZF = result & 0xff == 0
        cpu.NF = bool(result & 0x80)

        cpu.A.l = result
        return cpu.A.l
    else:
        if not cpu.DF:
            result = cpu.A.w + data + cpu.CF
        else:
            result = (cpu.A.w & 0x000f) + (data & 0x000f) + (cpu.CF << 0)
            if result > 0x0009:
                result += 0x0006
            cpu.CF = result > 0x000f
            result = (cpu.A.w & 0x00f0) + (data & 0x00f0) + (cpu.CF <<  4) + (result & 0x000f)
            if result > 0x009f:
                result += 0x0060
            cpu.CF = result > 0x00ff
            result = (cpu.A.w & 0x0f00) + (data & 0x0f00) + (cpu.CF <<  8) + (result & 0x00ff)
            if result > 0x09ff:
                result += 0x0600
            cpu.CF = result > 0x0fff
            result = (cpu.A.w & 0xf000) + (data & 0xf000) + (cpu.CF << 12) + (result & 0x0fff)

        cpu.VF = bool(~(cpu.A.w ^ data) & (cpu.A.w ^ result) & 0x8000)
        if cpu.DF and result > 0x9fff:
            result += 0x6000
        cpu.CF = result > 0xffff
        cpu.ZF = result & 0xffff == 0
        cpu.NF = bool(result & 0x8000)

        cpu.A.w = result
        return cpu.A.w


def AND(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l &= data
        cpu.ZF = cpu.A.l == 0
        cpu.NF = bool(cpu.A.l & 0x80)
        return cpu.A.l
    else:
        cpu.A.w &= data
        cpu.ZF = cpu.A.w == 0
        cpu.NF = bool(cpu.A.w & 0x8000)
        return cpu.A.w


def ASL(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.CF = bool(data & 0x80)
        data <<= 1
        cpu.ZF = data & 0xff == 0
        cpu.NF = bool(data & 0x80)
        return data;
    else:
        cpu.CF = bool(data & 0x8000)
        data <<= 1
        cpu.ZF = data & 0xffff == 0
        cpu.NF = bool(data & 0x8000)
        return data


def BIT(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZF = (data & cpu.A.l) == 0
        cpu.VF = bool(data & 0x40)
        cpu.NF = bool(data & 0x80)
        return data
    else:
        cpu.ZF = (data & cpu.A.w) == 0
        cpu.VF = bool(data & 0x4000)
        cpu.NF = bool(data & 0x8000)
        return data


def CMP(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.A.l - data
        cpu.CF = result >= 0
        cpu.ZF = result & 0xff == 0
        cpu.NF = bool(result & 0x80)
        return result
    else:
        result = cpu.A.w - data
        cpu.CF = result >= 0
        cpu.ZF = result & 0xffff == 0
        cpu.NF = bool(result & 0x8000)
        return result


def CPX(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.X.l - data
        cpu.CF = result >= 0
        cpu.ZF = result & 0xff == 0
        cpu.NF = bool(result & 0x80)
        return result
    else:
        result = cpu.X.w - data
        cpu.CF = result >= 0
        cpu.ZF = result & 0xffff == 0
        cpu.NF = bool(result & 0x8000)
        return result


def CPY(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.Y.l - data
        cpu.CF = result >= 0
        cpu.ZF = result & 0xff == 0
        cpu.NF = bool(result & 0x80)
        return result
    else:
        result = cpu.Y.w - data
        cpu.CF = result >= 0
        cpu.ZF = result & 0xffff == 0
        cpu.NF = bool(result & 0x8000)
        return result


def DEC(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        data = (data - 1) & 0xff
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x80)
        return data
    else:
        data = (data - 1) & 0xffff
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x8000)
        return data


def EOR(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l ^= data
        cpu.ZF = cpu.A.l == 0
        cpu.NF = bool(cpu.A.l & 0x80)
        return cpu.A.l
    else:
        cpu.A.w ^= data
        cpu.ZF = cpu.A.w == 0
        cpu.NF = bool(cpu.A.w & 0x8000)
        return cpu.A.w


def INC(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        data = (data + 1) & 0xFF
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x80)
        return data
    else:
        data = (data + 1) & 0xFFFF
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x8000)
        return data


def LDA(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l = data;
        cpu.ZF = cpu.A.l == 0;
        cpu.NF = bool(cpu.A.l & 0x80)
        return data;
    else:
        cpu.A.w = data;
        cpu.ZF = cpu.A.w == 0;
        cpu.NF = bool(cpu.A.w & 0x8000)
        return data;


def LDX(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.X.l = data
        cpu.ZF = cpu.X.l == 0
        cpu.NF = bool(cpu.X.l & 0x80)
        return data
    else:
        cpu.X.w = data
        cpu.ZF = cpu.X.w == 0
        cpu.NF = bool(cpu.X.w & 0x8000)
        return data


def LDY(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.Y.l = data
        cpu.ZF = cpu.Y.l == 0
        cpu.NF = bool(cpu.Y.l & 0x80)
        return data
    else:
        cpu.Y.w = data
        cpu.ZF = cpu.Y.w == 0
        cpu.NF = bool(cpu.Y.w & 0x8000)
        return data


def LSR(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.CF = bool(data & 1)
        data = (data >> 1) & 0xFF
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x80)
        return data
    else:
        cpu.CF = data & 1
        data = (data >> 1) & 0xFFFF
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x8000)
        return data


def ORA(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l |= data
        cpu.ZF = cpu.A.l == 0
        cpu.NF = bool(cpu.A.l & 0x80)
        return cpu.A.l
    else:
        cpu.A.w |= data
        cpu.ZF = cpu.A.w == 0
        cpu.NF = bool(cpu.A.w & 0x8000)
        return cpu.A.w


def ROL(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        carry = cpu.CF
        cpu.CF = bool(data & 0x80)
        data = data << 1 | carry  # do i need to mask this?
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x80)
        return data
    else:
        carry = cpu.CF
        cpu.CF = bool(data & 0x8000)
        data = data << 1 | carry
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x8000)
        return data


def ROR(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        carry = cpu.CF
        cpu.CF = bool(data & 1)
        data = carry << 7 | data >> 1
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x80)
        return data
    else:
        carry = cpu.CF
        cpu.CF = bool(data & 1)
        data = carry << 15 | data >> 1
        cpu.ZF = data == 0
        cpu.NF = bool(data & 0x8000)
        return data


def SBC(cpu: Cpu, mode_8bit: bool, data: int):
    # bsnes - result is always an int
    data = ~data  # this may come as 8bit or 16bit - might need to mask this
    if mode_8bit:
        if not cpu.DF:
            result = cpu.A.l + data + cpu.CF
        else:
            result = (cpu.A.l & 0x0f) + (data & 0x0f) + (cpu.CF << 0)
            if result <= 0x0f:
                result -= 0x06
            cpu.CF = result > 0x0f
            result = (cpu.A.l & 0xf0) + (data & 0xf0) + (cpu.CF << 4) + (result & 0x0f)

        cpu.VF = bool(~(cpu.A.l ^ data) & (cpu.A.l ^ result) & 0x80)
        if cpu.DF and result <= 0xff:
            result -= 0x60
        cpu.CF = result > 0xff
        cpu.ZF = result & 0xff == 0
        cpu.NF = bool(result & 0x80)

        cpu.A.l = result
        return cpu.A.l
    else:
        if not cpu.DF:
            result = cpu.A.w + data + cpu.CF
        else:
            result = (cpu.A.w & 0x000f) + (data & 0x000f) + (cpu.CF << 0)
            if result <= 0x000f:
                result -= 0x0006
            cpu.CF = result > 0x000f
            result = (cpu.A.w & 0x00f0) + (data & 0x00f0) + (cpu.CF <<  4) + (result & 0x000f)
            if result <= 0x00ff:
                result -= 0x0060
            cpu.CF = result > 0x00ff
            result = (cpu.A.w & 0x0f00) + (data & 0x0f00) + (cpu.CF <<  8) + (result & 0x00ff)
            if result <= 0x0fff:
                result -= 0x0600
            cpu.CF = result > 0x0fff
            result = (cpu.A.w & 0xf000) + (data & 0xf000) + (cpu.CF << 12) + (result & 0x0fff)

        cpu.VF = bool(~(cpu.A.w ^ data) & (cpu.A.w ^ result) & 0x8000)
        if cpu.DF and result <= 0xffff:
            result -= 0x6000
        cpu.CF = result > 0xffff
        cpu.ZF = result & 0xffff == 0
        cpu.NF = bool(result & 0x8000)

        cpu.A.w = result
        return cpu.A.w


def TRB(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZF = (data & cpu.A.l) == 0
        data &= ~cpu.A.l
        return data
    else:
        cpu.ZF = (data & cpu.A.w) == 0
        data &= ~cpu.A.w
        return data


def TSB(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZF = (data & cpu.A.l) == 0
        data |= cpu.A.l
        return data
    else:
        cpu.ZF = (data & cpu.A.w) == 0
        data |= cpu.A.w
        return data
