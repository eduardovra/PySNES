from typing import TYPE_CHECKING, Callable
from ctypes import c_int8

if TYPE_CHECKING:
    from ...cpu import Cpu


def ClearFlag(cpu: "Cpu", flag: str):
    setattr(cpu, flag, False)


def NoOperation(cpu: "Cpu"):
    pass
