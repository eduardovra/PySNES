from ..cpu import Cpu


def ADC(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        if not cpu.DFlag:
            result = cpu.A.l + data + cpu.CFlag
        else:
            result = (cpu.A.l & 0x0f) + (data & 0x0f) + (cpu.CFlag << 0)
            if result > 0x09:
                result += 0x06
            cpu.CFlag = result > 0x0f
            result = (cpu.A.l & 0xf0) + (data & 0xf0) + (cpu.CFlag << 4) + (result & 0x0f)

        cpu.VFlag = bool(~(cpu.A.l ^ data) & (cpu.A.l ^ result) & 0x80)
        if cpu.DFlag and result > 0x9f:
            result += 0x60
        cpu.CFlag = result > 0xff
        cpu.ZFlag = result & 0xff == 0
        cpu.NFlag = bool(result & 0x80)

        cpu.A.l = result
        return cpu.A.l
    else:
        if not cpu.DFlag:
            result = cpu.A.w + data + cpu.CFlag
        else:
            result = (cpu.A.w & 0x000f) + (data & 0x000f) + (cpu.CFlag << 0)
            if result > 0x0009:
                result += 0x0006
            cpu.CFlag = result > 0x000f
            result = (cpu.A.w & 0x00f0) + (data & 0x00f0) + (cpu.CFlag <<  4) + (result & 0x000f)
            if result > 0x009f:
                result += 0x0060
            cpu.CFlag = result > 0x00ff
            result = (cpu.A.w & 0x0f00) + (data & 0x0f00) + (cpu.CFlag <<  8) + (result & 0x00ff)
            if result > 0x09ff:
                result += 0x0600
            cpu.CFlag = result > 0x0fff
            result = (cpu.A.w & 0xf000) + (data & 0xf000) + (cpu.CFlag << 12) + (result & 0x0fff)

        cpu.VFlag = bool(~(cpu.A.w ^ data) & (cpu.A.w ^ result) & 0x8000)
        if cpu.DFlag and result > 0x9fff:
            result += 0x6000
        cpu.CFlag = result > 0xffff
        cpu.ZFlag = result & 0xffff == 0
        cpu.NFlag = bool(result & 0x8000)

        cpu.A.w = result
        return cpu.A.w


def AND(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l &= data
        cpu.ZFlag = cpu.A.l == 0
        cpu.NFlag = bool(cpu.A.l & 0x80)
        return cpu.A.l
    else:
        cpu.A.w &= data
        cpu.ZFlag = cpu.A.w == 0
        cpu.NFlag = bool(cpu.A.w & 0x8000)
        return cpu.A.w


def ASL(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.CFlag = bool(data & 0x80)
        data <<= 1
        cpu.ZFlag = data & 0xff == 0
        cpu.NFlag = bool(data & 0x80)
        return data;
    else:
        cpu.CFlag = bool(data & 0x8000)
        data <<= 1
        cpu.ZFlag = data & 0xffff == 0
        cpu.NFlag = bool(data & 0x8000)
        return data


def BIT(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZFlag = (data & cpu.A.l) == 0
        cpu.VFlag = bool(data & 0x40)
        cpu.NFlag = bool(data & 0x80)
        return data
    else:
        cpu.ZFlag = (data & cpu.A.w) == 0
        cpu.VFlag = bool(data & 0x4000)
        cpu.NFlag = bool(data & 0x8000)
        return data


def CMP(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.A.l - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xff == 0
        cpu.NFlag = bool(result & 0x80)
        return result
    else:
        result = cpu.A.w - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xffff == 0
        cpu.NFlag = bool(result & 0x8000)
        return result


def CPX(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.X.l - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xff == 0
        cpu.NFlag = bool(result & 0x80)
        return result
    else:
        result = cpu.X.w - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xffff == 0
        cpu.NFlag = bool(result & 0x8000)
        return result


def CPY(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.Y.l - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xff == 0
        cpu.NFlag = bool(result & 0x80)
        return result
    else:
        result = cpu.Y.w - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xffff == 0
        cpu.NFlag = bool(result & 0x8000)
        return result


def DEC(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        data = (data - 1) & 0xff
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x80)
        return data
    else:
        data = (data - 1) & 0xffff
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x8000)
        return data


def EOR(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l ^= data
        cpu.ZFlag = cpu.A.l == 0
        cpu.NFlag = bool(cpu.A.l & 0x80)
        return cpu.A.l
    else:
        cpu.A.w ^= data
        cpu.ZFlag = cpu.A.w == 0
        cpu.NFlag = bool(cpu.A.w & 0x8000)
        return cpu.A.w


def INC(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        data = (data + 1) & 0xFF
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x80)
        return data
    else:
        data = (data + 1) & 0xFFFF
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x8000)
        return data


def LDA(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l = data;
        cpu.ZFlag = cpu.A.l == 0;
        cpu.NFlag = bool(cpu.A.l & 0x80)
        return data;
    else:
        cpu.A.w = data;
        cpu.ZFlag = cpu.A.w == 0;
        cpu.NFlag = bool(cpu.A.w & 0x8000)
        return data;


def LDX(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.X.l = data
        cpu.ZFlag = cpu.X.l == 0
        cpu.NFlag = bool(cpu.X.l & 0x80)
        return data
    else:
        cpu.X.w = data
        cpu.ZFlag = cpu.X.w == 0
        cpu.NFlag = bool(cpu.X.w & 0x8000)
        return data


def LDY(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.Y.l = data
        cpu.ZFlag = cpu.Y.l == 0
        cpu.NFlag = bool(cpu.Y.l & 0x80)
        return data
    else:
        cpu.Y.w = data
        cpu.ZFlag = cpu.Y.w == 0
        cpu.NFlag = bool(cpu.Y.w & 0x8000)
        return data


def LSR(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.CFlag = bool(data & 1)
        data = (data >> 1) & 0xFF
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x80)
        return data
    else:
        cpu.CFlag = data & 1
        data = (data >> 1) & 0xFFFF
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x8000)
        return data


def ORA(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l |= data
        cpu.ZFlag = cpu.A.l == 0
        cpu.NFlag = bool(cpu.A.l & 0x80)
        return cpu.A.l
    else:
        cpu.A.w |= data
        cpu.ZFlag = cpu.A.w == 0
        cpu.NFlag = bool(cpu.A.w & 0x8000)
        return cpu.A.w


def ROL(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        carry = cpu.CFlag
        cpu.CFlag = bool(data & 0x80)
        data = (data << 1 | carry) & 0xFF
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x80)
        return data
    else:
        carry = cpu.CFlag
        cpu.CFlag = bool(data & 0x8000)
        data = (data << 1 | carry) & 0xFFFF
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x8000)
        return data


def ROR(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        carry = cpu.CFlag
        cpu.CFlag = bool(data & 1)
        data = carry << 7 | data >> 1
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x80)
        return data
    else:
        carry = cpu.CFlag
        cpu.CFlag = bool(data & 1)
        data = carry << 15 | data >> 1
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x8000)
        return data


def SBC(cpu: Cpu, mode_8bit: bool, data: int):
    # bsnes - result is always an int
    data = ~data  # this may come as 8bit or 16bit - masking below
    if mode_8bit:
        data &= 0xff

        if not cpu.DFlag:
            result = cpu.A.l + data + cpu.CFlag
        else:
            result = (cpu.A.l & 0x0f) + (data & 0x0f) + (cpu.CFlag << 0)
            if result <= 0x0f:
                result -= 0x06
            cpu.CFlag = result > 0x0f
            result = (cpu.A.l & 0xf0) + (data & 0xf0) + (cpu.CFlag << 4) + (result & 0x0f)

        cpu.VFlag = bool(~(cpu.A.l ^ data) & (cpu.A.l ^ result) & 0x80)
        if cpu.DFlag and result <= 0xff:
            result -= 0x60
        cpu.CFlag = result > 0xff
        cpu.ZFlag = result & 0xff == 0
        cpu.NFlag = bool(result & 0x80)

        cpu.A.l = result
        return cpu.A.l
    else:
        data &= 0xffff

        if not cpu.DFlag:
            result = cpu.A.w + data + cpu.CFlag
        else:
            result = (cpu.A.w & 0x000f) + (data & 0x000f) + (cpu.CFlag << 0)
            if result <= 0x000f:
                result -= 0x0006
            cpu.CFlag = result > 0x000f
            result = (cpu.A.w & 0x00f0) + (data & 0x00f0) + (cpu.CFlag <<  4) + (result & 0x000f)
            if result <= 0x00ff:
                result -= 0x0060
            cpu.CFlag = result > 0x00ff
            result = (cpu.A.w & 0x0f00) + (data & 0x0f00) + (cpu.CFlag <<  8) + (result & 0x00ff)
            if result <= 0x0fff:
                result -= 0x0600
            cpu.CFlag = result > 0x0fff
            result = (cpu.A.w & 0xf000) + (data & 0xf000) + (cpu.CFlag << 12) + (result & 0x0fff)

        cpu.VFlag = bool(~(cpu.A.w ^ data) & (cpu.A.w ^ result) & 0x8000)
        if cpu.DFlag and result <= 0xffff:
            result -= 0x6000
        cpu.CFlag = result > 0xffff
        cpu.ZFlag = result & 0xffff == 0
        cpu.NFlag = bool(result & 0x8000)

        cpu.A.w = result
        return cpu.A.w


def TRB(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZFlag = (data & cpu.A.l) == 0
        data &= ~cpu.A.l
        return data
    else:
        cpu.ZFlag = (data & cpu.A.w) == 0
        data &= ~cpu.A.w
        return data


def TSB(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZFlag = (data & cpu.A.l) == 0
        data |= cpu.A.l
        return data
    else:
        cpu.ZFlag = (data & cpu.A.w) == 0
        data |= cpu.A.w
        return data
