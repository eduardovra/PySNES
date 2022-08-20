from ..cpu import Cpu


# TODO remove once all opcodes are implemented
def __getattr__(name: str):
    def not_implemented(*args, **kwargs):
        raise NotImplementedError(name)
    try:
        return globals()[name]
    except KeyError:
        return not_implemented


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
