from typing import TYPE_CHECKING, Callable, Optional
from ctypes import c_int8

if TYPE_CHECKING:
    from ...cpu import Cpu

from .decorator import decorator_mode_8bit


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


@decorator_mode_8bit
def ImmediateRead(cpu: "Cpu", mode_8bit: bool, func):
    if mode_8bit:
        cpu.W.l = cpu.fetch()
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.W.l = cpu.fetch()
        cpu.W.h = cpu.fetch()
        func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def BankRead(cpu: "Cpu", mode_8bit: bool, func, i: str = ""):
    I = getattr(cpu, i, None)

    if mode_8bit:
        if I is None:
            cpu.V.l = cpu.fetch()
            cpu.V.h = cpu.fetch()
            cpu.W.l = cpu.readBank(cpu.V.w + 0)
            func(cpu, mode_8bit, cpu.W.l)
        else:
            cpu.V.l = cpu.fetch()
            cpu.V.h = cpu.fetch()
            cpu.idle4(cpu.V.w, cpu.V.w + I.w)
            cpu.W.l = cpu.readBank(cpu.V.w + I.w + 0)
            func(cpu, mode_8bit, cpu.W.l)
    else:
        if I is None:
            cpu.V.l = cpu.fetch()
            cpu.V.h = cpu.fetch()
            cpu.W.l = cpu.readBank(cpu.V.w + 0)
            cpu.W.h = cpu.readBank(cpu.V.w + 1)
            func(cpu, mode_8bit, cpu.W.w)
        else:
            cpu.V.l = cpu.fetch()
            cpu.V.h = cpu.fetch()
            cpu.idle4(cpu.V.w, cpu.V.w + I.w)
            cpu.W.l = cpu.readBank(cpu.V.w + I.w + 0)
            cpu.W.h = cpu.readBank(cpu.V.w + I.w + 1)
            func(cpu, mode_8bit, cpu.W.w)
