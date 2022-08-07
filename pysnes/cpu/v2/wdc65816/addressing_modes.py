from typing import TYPE_CHECKING, Callable
from ctypes import c_int8
import functools

if TYPE_CHECKING:
    from ..cpu import Cpu

"""
//both the accumulator and index registers can independently be in either 8-bit or 16-bit mode.
//controlled via the M/X flags, this changes the execution details of various instructions.
//rather than implement four instruction tables for all possible combinations of these bits,
//instead use macro abuse to generate all four tables based off of a single template table.
auto WDC65816::instruction() -> void {
  //a = instructions unaffected by M/X flags
  //m = instructions affected by M flag (1 = 8-bit; 0 = 16-bit)
  //x = instructions affected by X flag (1 = 8-bit; 0 = 16-bit)
"""


def decorator_mode_8bit(func):
    """Creates function variants for 8/16 bit modes based on M/X flag"""
    @functools.wraps(func)
    def mf_wrapper(cpu: "Cpu", *args, **kwargs):
        return func(cpu, cpu.MF, *args, **kwargs)
    func.MF = mf_wrapper

    @functools.wraps(func)
    def xf_wrapper(cpu: "Cpu", *args, **kwargs):
        return func(cpu, cpu.XF, *args, **kwargs)
    func.XF = xf_wrapper

    return func


# TODO remove once all modes are implemented
def __getattr__(name: str):
    @decorator_mode_8bit
    def not_implemented(*args, **kwargs):
        raise NotImplementedError(name)
    try:
        return globals()[name]
    except KeyError:
        return not_implemented


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


def ClearFlag(cpu: "Cpu", flag: str):
    setattr(cpu, flag, False)


def NoOperation(cpu: "Cpu"):
    pass


@decorator_mode_8bit
def ImmediateRead(cpu: "Cpu", mode_8bit: bool, func):
    if mode_8bit:
        cpu.W.l = cpu.fetch()
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.W.l = cpu.fetch()
        cpu.W.h = cpu.fetch()
        func(cpu, mode_8bit, cpu.W.w)
