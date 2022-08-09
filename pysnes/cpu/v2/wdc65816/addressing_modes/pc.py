from typing import TYPE_CHECKING, Callable
from ctypes import c_int8

if TYPE_CHECKING:
    from ...cpu import Cpu


def Branch(cpu: "Cpu", cond: Callable):
    take = cond(cpu)
    if take:
        cpu.U.l = cpu.fetch()
        displacement = c_int8(cpu.U.l)
        cpu.V.w = cpu.PC.d + displacement.value
        cpu.idle6(cpu.V.w)
        cpu.idle()
        cpu.PC.w = cpu.V.w
        cpu.idleBranch()
    else:
        cpu.fetch()
