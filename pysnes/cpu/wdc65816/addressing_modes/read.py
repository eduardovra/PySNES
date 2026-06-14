from typing import Callable

from ...cpu import Cpu, Reg

from .decorator import decorator_mode_8bit

# Shared read-only zero register used as the "no index" offset (I.w == 0).
# The index arg `i` is pre-resolved to a Reg (or None) at table-build time, so
# the addressing modes below never do a per-call getattr(cpu, name).
_ZERO = Reg(16, 0)


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
def ImmediateRead(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.W.l = cpu.fetch()
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.W.l = cpu.fetch()
        cpu.W.h = cpu.fetch()
        func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def BankRead(cpu: Cpu, mode_8bit: bool, func: Callable, I: Reg | None = None):
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


@decorator_mode_8bit
def LongRead(cpu: Cpu, mode_8bit: bool, func: Callable, i: Reg | None = None):
    I = i if i is not None else _ZERO

    if mode_8bit:
        cpu.V.l = cpu.fetch()
        cpu.V.h = cpu.fetch()
        cpu.V.b = cpu.fetch()
        cpu.W.l = cpu.readLong(cpu.V.d + I.w + 0)
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.V.l = cpu.fetch()
        cpu.V.h = cpu.fetch()
        cpu.V.b = cpu.fetch()
        cpu.W.l = cpu.readLong(cpu.V.d + I.w + 0)
        cpu.W.h = cpu.readLong(cpu.V.d + I.w + 1)
        func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def DirectRead(cpu: Cpu, mode_8bit: bool, func: Callable, I: Reg | None = None):
    if mode_8bit:
        if I is None:
            cpu.U.l = cpu.fetch()
            cpu.idle2()
            cpu.W.l = cpu.readDirect(cpu.U.l + 0)
            func(cpu, mode_8bit, cpu.W.l)
        else:
            cpu.U.l = cpu.fetch()
            cpu.idle2()
            cpu.idle()
            cpu.W.l = cpu.readDirect(cpu.U.l + I.w + 0)
            func(cpu, mode_8bit, cpu.W.l)
    else:
        if I is None:
            cpu.U.l = cpu.fetch()
            cpu.idle2()
            cpu.W.l = cpu.readDirect(cpu.U.l + 0)
            cpu.W.h = cpu.readDirect(cpu.U.l + 1)
            func(cpu, mode_8bit, cpu.W.w)
        else:
            cpu.U.l = cpu.fetch()
            cpu.idle2()
            cpu.idle()
            cpu.W.l = cpu.readDirect(cpu.U.l + I.w + 0)
            cpu.W.h = cpu.readDirect(cpu.U.l + I.w + 1)
            func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def IndirectRead(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirect(cpu.U.l + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + 1)
        cpu.W.l = cpu.readBank(cpu.V.w + 0)
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirect(cpu.U.l + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + 1)
        cpu.W.l = cpu.readBank(cpu.V.w + 0)
        cpu.W.h = cpu.readBank(cpu.V.w + 1)
        func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def IndexedIndirectRead(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.idle()
        cpu.V.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1)
        cpu.W.l = cpu.readBank(cpu.V.w + 0)
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.idle()
        cpu.V.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1)
        cpu.W.l = cpu.readBank(cpu.V.w + 0)
        cpu.W.h = cpu.readBank(cpu.V.w + 1)
        func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def IndirectIndexedRead(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirect(cpu.U.l + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + 1)
        cpu.idle4(cpu.V.w, cpu.V.w + cpu.Y.w)
        cpu.W.l = cpu.readBank(cpu.V.w + cpu.Y.w + 0)
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirect(cpu.U.l + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + 1)
        cpu.idle4(cpu.V.w, cpu.V.w + cpu.Y.w)
        cpu.W.l = cpu.readBank(cpu.V.w + cpu.Y.w + 0)
        cpu.W.h = cpu.readBank(cpu.V.w + cpu.Y.w + 1)
        func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def IndirectLongRead(cpu: Cpu, mode_8bit: bool, func: Callable, i: Reg | None = None):
    I = i if i is not None else _ZERO

    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirectN(cpu.U.l + 0)
        cpu.V.h = cpu.readDirectN(cpu.U.l + 1)
        cpu.V.b = cpu.readDirectN(cpu.U.l + 2)
        cpu.W.l = cpu.readLong(cpu.V.d + I.w + 0)
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirectN(cpu.U.l + 0)
        cpu.V.h = cpu.readDirectN(cpu.U.l + 1)
        cpu.V.b = cpu.readDirectN(cpu.U.l + 2)
        cpu.W.l = cpu.readLong(cpu.V.d + I.w + 0)
        cpu.W.h = cpu.readLong(cpu.V.d + I.w + 1)
        func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def StackRead(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle()
        cpu.W.l = cpu.readStack(cpu.U.l + 0)
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle()
        cpu.W.l = cpu.readStack(cpu.U.l + 0)
        cpu.W.h = cpu.readStack(cpu.U.l + 1)
        func(cpu, mode_8bit, cpu.W.w)


@decorator_mode_8bit
def IndirectStackRead(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle()
        cpu.V.l = cpu.readStack(cpu.U.l + 0)
        cpu.V.h = cpu.readStack(cpu.U.l + 1)
        cpu.idle()
        cpu.W.l = cpu.readBank(cpu.V.w + cpu.Y.w + 0)
        func(cpu, mode_8bit, cpu.W.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle()
        cpu.V.l = cpu.readStack(cpu.U.l + 0)
        cpu.V.h = cpu.readStack(cpu.U.l + 1)
        cpu.idle()
        cpu.W.l = cpu.readBank(cpu.V.w + cpu.Y.w + 0)
        cpu.W.h = cpu.readBank(cpu.V.w + cpu.Y.w + 1)
        func(cpu, mode_8bit, cpu.W.w)
