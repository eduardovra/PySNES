from typing import TYPE_CHECKING

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


def NoOperation(cpu: "Cpu"):
    pass


def ImmediateRead8(cpu: "Cpu", func):
    cpu.W.l = cpu.fetch()
    func(cpu, cpu.W.l)


def ImmediateRead16(cpu: "Cpu", func):
    cpu.W.l = cpu.fetch()
    cpu.W.h = cpu.fetch()
    func(cpu, cpu.W.w)
