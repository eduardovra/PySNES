from typing import Callable

from ...cpu import Cpu, Reg

from .decorator import decorator_mode_8bit


@decorator_mode_8bit
def ImpliedModify(cpu: Cpu, mode_8bit: bool, func: Callable, M: Reg):
    if mode_8bit:
        cpu.idleIRQ()
        M.l = func(cpu, mode_8bit, M.l)
    else:
        cpu.idleIRQ()
        M.w = func(cpu, mode_8bit, M.w)


@decorator_mode_8bit
def BankModify(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.V.l = cpu.fetch()
        cpu.V.h = cpu.fetch()
        cpu.W.l = cpu.readBank(cpu.V.w + 0)
        # 65816 emulation (EF=1) replays the 6502-era RMW dummy write-back of
        # the unmodified value in place of the native-mode internal idle.
        if cpu.EF:
            cpu.writeBank(cpu.V.w + 0, cpu.W.l)
        else:
            cpu.idle()
        cpu.W.l = func(cpu, mode_8bit, cpu.W.l)
        cpu.writeBank(cpu.V.w + 0, cpu.W.l)
    else:
        cpu.V.l = cpu.fetch()
        cpu.V.h = cpu.fetch()
        cpu.W.l = cpu.readBank(cpu.V.w + 0)
        cpu.W.h = cpu.readBank(cpu.V.w + 1)
        cpu.idle()
        cpu.W.w = func(cpu, mode_8bit, cpu.W.w)
        cpu.writeBank(cpu.V.w + 1, cpu.W.h)
        cpu.writeBank(cpu.V.w + 0, cpu.W.l)


@decorator_mode_8bit
def BankIndexedModify(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.V.l = cpu.fetch()
        cpu.V.h = cpu.fetch()
        cpu.idle()
        cpu.W.l = cpu.readBank(cpu.V.w + cpu.X.w + 0)
        # See BankModify: EF=1 dummy write-back in place of the native idle.
        if cpu.EF:
            cpu.writeBank(cpu.V.w + cpu.X.w + 0, cpu.W.l)
        else:
            cpu.idle()
        cpu.W.l = func(cpu, mode_8bit, cpu.W.l)
        cpu.writeBank(cpu.V.w + cpu.X.w + 0, cpu.W.l)
    else:
        cpu.V.l = cpu.fetch()
        cpu.V.h = cpu.fetch()
        cpu.idle()
        cpu.W.l = cpu.readBank(cpu.V.w + cpu.X.w + 0)
        cpu.W.h = cpu.readBank(cpu.V.w + cpu.X.w + 1)
        cpu.idle()
        cpu.W.w = func(cpu, mode_8bit, cpu.W.w)
        cpu.writeBank(cpu.V.w + cpu.X.w + 1, cpu.W.h)
        cpu.writeBank(cpu.V.w + cpu.X.w + 0, cpu.W.l)


@decorator_mode_8bit
def DirectModify(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.W.l = cpu.readDirect(cpu.U.l + 0)
        # See BankModify: EF=1 dummy write-back in place of the native idle.
        if cpu.EF:
            cpu.writeDirect(cpu.U.l + 0, cpu.W.l)
        else:
            cpu.idle()
        cpu.W.l = func(cpu, mode_8bit, cpu.W.l)
        cpu.writeDirect(cpu.U.l + 0, cpu.W.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.W.l = cpu.readDirect(cpu.U.l + 0)
        cpu.W.h = cpu.readDirect(cpu.U.l + 1)
        cpu.idle()
        cpu.W.w = func(cpu, mode_8bit, cpu.W.w)
        cpu.writeDirect(cpu.U.l + 1, cpu.W.h)
        cpu.writeDirect(cpu.U.l + 0, cpu.W.l)


@decorator_mode_8bit
def DirectIndexedModify(cpu: Cpu, mode_8bit: bool, func: Callable):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.idle()
        cpu.W.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
        # See BankModify: EF=1 dummy write-back in place of the native idle.
        if cpu.EF:
            cpu.writeDirect(cpu.U.l + cpu.X.w + 0, cpu.W.l)
        else:
            cpu.idle()
        cpu.W.l = func(cpu, mode_8bit, cpu.W.l)
        cpu.writeDirect(cpu.U.l + cpu.X.w + 0, cpu.W.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.idle()
        cpu.W.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
        cpu.W.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1)
        cpu.idle()
        cpu.W.w = func(cpu, mode_8bit, cpu.W.w)
        cpu.writeDirect(cpu.U.l + cpu.X.w + 1, cpu.W.h)
        cpu.writeDirect(cpu.U.l + cpu.X.w + 0, cpu.W.l)
