from ..cpu import Cpu


def ADC(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        if not cpu.DFlag:
            result = cpu.A.l + data + cpu.CFlag
        else:
            result = (cpu.A.l & 0x0F) + (data & 0x0F) + (cpu.CFlag << 0)
            if result > 0x09:
                result += 0x06
            cpu.CFlag = result > 0x0F
            result = (
                (cpu.A.l & 0xF0)
                + (data & 0xF0)
                + (cpu.CFlag << 4)
                + (result & 0x0F)
            )

        cpu.VFlag = bool(~(cpu.A.l ^ data) & (cpu.A.l ^ result) & 0x80)
        if cpu.DFlag and result > 0x9F:
            result += 0x60
        cpu.CFlag = result > 0xFF
        cpu.ZFlag = result & 0xFF == 0
        cpu.NFlag = bool(result & 0x80)

        cpu.A.l = result
        return cpu.A.l
    if not cpu.DFlag:
        result = cpu.A.w + data + cpu.CFlag
    else:
        result = (cpu.A.w & 0x000F) + (data & 0x000F) + (cpu.CFlag << 0)
        if result > 0x0009:
            result += 0x0006
        cpu.CFlag = result > 0x000F
        result = (
            (cpu.A.w & 0x00F0)
            + (data & 0x00F0)
            + (cpu.CFlag << 4)
            + (result & 0x000F)
        )
        if result > 0x009F:
            result += 0x0060
        cpu.CFlag = result > 0x00FF
        result = (
            (cpu.A.w & 0x0F00)
            + (data & 0x0F00)
            + (cpu.CFlag << 8)
            + (result & 0x00FF)
        )
        if result > 0x09FF:
            result += 0x0600
        cpu.CFlag = result > 0x0FFF
        result = (
            (cpu.A.w & 0xF000)
            + (data & 0xF000)
            + (cpu.CFlag << 12)
            + (result & 0x0FFF)
        )

    cpu.VFlag = bool(~(cpu.A.w ^ data) & (cpu.A.w ^ result) & 0x8000)
    if cpu.DFlag and result > 0x9FFF:
        result += 0x6000
    cpu.CFlag = result > 0xFFFF
    cpu.ZFlag = result & 0xFFFF == 0
    cpu.NFlag = bool(result & 0x8000)

    cpu.A.w = result
    return cpu.A.w


def AND(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l &= data
        cpu.ZFlag = cpu.A.l == 0
        cpu.NFlag = bool(cpu.A.l & 0x80)
        return cpu.A.l
    cpu.A.w &= data
    cpu.ZFlag = cpu.A.w == 0
    cpu.NFlag = bool(cpu.A.w & 0x8000)
    return cpu.A.w


def ASL(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.CFlag = bool(data & 0x80)
        data <<= 1
        cpu.ZFlag = data & 0xFF == 0
        cpu.NFlag = bool(data & 0x80)
        return data
    cpu.CFlag = bool(data & 0x8000)
    data <<= 1
    cpu.ZFlag = data & 0xFFFF == 0
    cpu.NFlag = bool(data & 0x8000)
    return data


def BIT(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZFlag = (data & cpu.A.l) == 0
        cpu.VFlag = bool(data & 0x40)
        cpu.NFlag = bool(data & 0x80)
        return data
    cpu.ZFlag = (data & cpu.A.w) == 0
    cpu.VFlag = bool(data & 0x4000)
    cpu.NFlag = bool(data & 0x8000)
    return data


def CMP(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.A.l - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xFF == 0
        cpu.NFlag = bool(result & 0x80)
        return result
    result = cpu.A.w - data
    cpu.CFlag = result >= 0
    cpu.ZFlag = result & 0xFFFF == 0
    cpu.NFlag = bool(result & 0x8000)
    return result


def CPX(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.X.l - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xFF == 0
        cpu.NFlag = bool(result & 0x80)
        return result
    result = cpu.X.w - data
    cpu.CFlag = result >= 0
    cpu.ZFlag = result & 0xFFFF == 0
    cpu.NFlag = bool(result & 0x8000)
    return result


def CPY(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        result = cpu.Y.l - data
        cpu.CFlag = result >= 0
        cpu.ZFlag = result & 0xFF == 0
        cpu.NFlag = bool(result & 0x80)
        return result
    result = cpu.Y.w - data
    cpu.CFlag = result >= 0
    cpu.ZFlag = result & 0xFFFF == 0
    cpu.NFlag = bool(result & 0x8000)
    return result


def DEC(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        data = (data - 1) & 0xFF
        cpu.ZFlag = data == 0
        cpu.NFlag = bool(data & 0x80)
        return data
    data = (data - 1) & 0xFFFF
    cpu.ZFlag = data == 0
    cpu.NFlag = bool(data & 0x8000)
    return data


def EOR(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l ^= data
        cpu.ZFlag = cpu.A.l == 0
        cpu.NFlag = bool(cpu.A.l & 0x80)
        return cpu.A.l
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
    data = (data + 1) & 0xFFFF
    cpu.ZFlag = data == 0
    cpu.NFlag = bool(data & 0x8000)
    return data


def LDA(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.A.l = data
        cpu.ZFlag = cpu.A.l == 0
        cpu.NFlag = bool(cpu.A.l & 0x80)
        return data
    cpu.A.w = data
    cpu.ZFlag = cpu.A.w == 0
    cpu.NFlag = bool(cpu.A.w & 0x8000)
    return data


def LDX(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.X.l = data
        cpu.ZFlag = cpu.X.l == 0
        cpu.NFlag = bool(cpu.X.l & 0x80)
        return data
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
        data &= 0xFF

        if not cpu.DFlag:
            result = cpu.A.l + data + cpu.CFlag
        else:
            result = (cpu.A.l & 0x0F) + (data & 0x0F) + (cpu.CFlag << 0)
            if result <= 0x0F:
                result -= 0x06
            cpu.CFlag = result > 0x0F
            result = (
                (cpu.A.l & 0xF0)
                + (data & 0xF0)
                + (cpu.CFlag << 4)
                + (result & 0x0F)
            )

        cpu.VFlag = bool(~(cpu.A.l ^ data) & (cpu.A.l ^ result) & 0x80)
        if cpu.DFlag and result <= 0xFF:
            result -= 0x60
        cpu.CFlag = result > 0xFF
        cpu.ZFlag = result & 0xFF == 0
        cpu.NFlag = bool(result & 0x80)

        cpu.A.l = result
        return cpu.A.l
    data &= 0xFFFF

    if not cpu.DFlag:
        result = cpu.A.w + data + cpu.CFlag
    else:
        result = (cpu.A.w & 0x000F) + (data & 0x000F) + (cpu.CFlag << 0)
        if result <= 0x000F:
            result -= 0x0006
        cpu.CFlag = result > 0x000F
        result = (
            (cpu.A.w & 0x00F0)
            + (data & 0x00F0)
            + (cpu.CFlag << 4)
            + (result & 0x000F)
        )
        if result <= 0x00FF:
            result -= 0x0060
        cpu.CFlag = result > 0x00FF
        result = (
            (cpu.A.w & 0x0F00)
            + (data & 0x0F00)
            + (cpu.CFlag << 8)
            + (result & 0x00FF)
        )
        if result <= 0x0FFF:
            result -= 0x0600
        cpu.CFlag = result > 0x0FFF
        result = (
            (cpu.A.w & 0xF000)
            + (data & 0xF000)
            + (cpu.CFlag << 12)
            + (result & 0x0FFF)
        )

    cpu.VFlag = bool(~(cpu.A.w ^ data) & (cpu.A.w ^ result) & 0x8000)
    if cpu.DFlag and result <= 0xFFFF:
        result -= 0x6000
    cpu.CFlag = result > 0xFFFF
    cpu.ZFlag = result & 0xFFFF == 0
    cpu.NFlag = bool(result & 0x8000)

    cpu.A.w = result
    return cpu.A.w


def TRB(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZFlag = (data & cpu.A.l) == 0
        data &= ~cpu.A.l
        return data
    cpu.ZFlag = (data & cpu.A.w) == 0
    data &= ~cpu.A.w
    return data


def TSB(cpu: Cpu, mode_8bit: bool, data: int):
    if mode_8bit:
        cpu.ZFlag = (data & cpu.A.l) == 0
        data |= cpu.A.l
        return data
    cpu.ZFlag = (data & cpu.A.w) == 0
    data |= cpu.A.w
    return data
