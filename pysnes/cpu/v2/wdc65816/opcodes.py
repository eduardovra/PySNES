from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..cpu import Cpu


def AND8(cpu: "Cpu", data: int):
    cpu.A.l &= data
    cpu.ZF = cpu.A.l == 0
    cpu.NF = bool(cpu.A.l & 0x80)
    return cpu.A.l


def AND16(cpu: "Cpu", data: int):
    cpu.A.w &= data
    cpu.ZF = cpu.A.w == 0
    cpu.NF = bool(cpu.A.w & 0x8000)
    return cpu.A.w
