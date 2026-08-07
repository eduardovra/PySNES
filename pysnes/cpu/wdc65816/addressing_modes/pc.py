from typing import Callable

from ...cpu import Cpu


def Branch(cpu: Cpu, cond: Callable):
    take = cond(cpu)
    if take:
        cpu.U.l = cpu.fetch()
        # int8 displacement
        displacement = cpu.U.l if cpu.U.l < 0x80 else cpu.U.l - 0x100
        cpu.V.w = cpu.PC.d + displacement
        cpu.idle6(cpu.V.w)
        cpu.idle()
        cpu.PC.w = cpu.V.w
        cpu.idleBranch()
    else:
        cpu.fetch()


def BranchLong(cpu: Cpu):
    cpu.U.l = cpu.fetch()
    cpu.U.h = cpu.fetch()
    # int16 displacement
    displacement = cpu.U.w if cpu.U.w < 0x8000 else cpu.U.w - 0x10000
    cpu.V.w = cpu.PC.d + displacement
    cpu.idle()
    cpu.PC.w = cpu.V.w
    cpu.idleBranch()


def JumpShort(cpu: Cpu):
    cpu.W.l = cpu.fetch()
    cpu.W.h = cpu.fetch()
    cpu.PC.w = cpu.W.w
    cpu.idleJump()


def JumpLong(cpu: Cpu):
    cpu.V.l = cpu.fetch()
    cpu.V.h = cpu.fetch()
    cpu.V.b = cpu.fetch()
    cpu.PC.d = cpu.V.d
    cpu.idleJump()


def JumpIndirect(cpu: Cpu):
    cpu.V.l = cpu.fetch()
    cpu.V.h = cpu.fetch()
    cpu.W.l = cpu.read((cpu.V.w + 0) & 0xFFFF)
    cpu.W.h = cpu.read((cpu.V.w + 1) & 0xFFFF)
    cpu.PC.w = cpu.W.w
    cpu.idleJump()


def JumpIndexedIndirect(cpu: Cpu):
    cpu.V.l = cpu.fetch()
    cpu.V.h = cpu.fetch()
    cpu.idle()
    cpu.W.l = cpu.read(cpu.PC.b << 16 | (cpu.V.w + cpu.X.w + 0) & 0xFFFF)
    cpu.W.h = cpu.read(cpu.PC.b << 16 | (cpu.V.w + cpu.X.w + 1) & 0xFFFF)
    cpu.PC.w = cpu.W.w
    cpu.idleJump()


def JumpIndirectLong(cpu: Cpu):
    cpu.U.l = cpu.fetch()
    cpu.U.h = cpu.fetch()
    cpu.V.l = cpu.read((cpu.U.w + 0) & 0xFFFF)
    cpu.V.h = cpu.read((cpu.U.w + 1) & 0xFFFF)
    cpu.V.b = cpu.read((cpu.U.w + 2) & 0xFFFF)
    cpu.PC.d = cpu.V.d
    cpu.idleJump()


def CallShort(cpu: Cpu):
    cpu.W.l = cpu.fetch()
    cpu.W.h = cpu.fetch()
    cpu.idle()
    cpu.PC.w -= 1
    cpu.push(cpu.PC.h)
    cpu.push(cpu.PC.l)
    cpu.PC.w = cpu.W.w
    cpu.idleJump()


def CallLong(cpu: Cpu):
    cpu.V.l = cpu.fetch()
    cpu.V.h = cpu.fetch()
    cpu.pushN(cpu.PC.b)
    cpu.idle()
    cpu.V.b = cpu.fetch()
    cpu.PC.w -= 1
    cpu.pushN(cpu.PC.h)
    cpu.pushN(cpu.PC.l)
    cpu.PC.d = cpu.V.d
    if cpu.EF:
        cpu.S.h = 0x01
    cpu.idleJump()


def CallIndexedIndirect(cpu: Cpu):
    cpu.V.l = cpu.fetch()
    cpu.pushN(cpu.PC.h)
    cpu.pushN(cpu.PC.l)
    cpu.V.h = cpu.fetch()
    cpu.idle()
    cpu.W.l = cpu.read(cpu.PC.b << 16 | (cpu.V.w + cpu.X.w + 0) & 0xFFFF)
    cpu.W.h = cpu.read(cpu.PC.b << 16 | (cpu.V.w + cpu.X.w + 1) & 0xFFFF)
    cpu.PC.w = cpu.W.w
    if cpu.EF:
        cpu.S.h = 0x01
    cpu.idleJump()


def ReturnInterrupt(cpu: Cpu):
    cpu.idle()
    cpu.idle()
    cpu.P = cpu.pull()
    if cpu.EF:
        cpu.XFlag = True
        cpu.MFlag = True
    if cpu.XFlag:
        cpu.X.h = 0x00
        cpu.Y.h = 0x00
    cpu.PC.l = cpu.pull()
    if cpu.EF:
        cpu.PC.h = cpu.pull()
    else:
        cpu.PC.h = cpu.pull()
        cpu.PC.b = cpu.pull()
    cpu.idleJump()


def ReturnShort(cpu: Cpu):
    cpu.idle()
    cpu.idle()
    cpu.W.l = cpu.pull()
    cpu.W.h = cpu.pull()
    cpu.idle()
    cpu.PC.w = cpu.W.w
    cpu.PC.w += 1
    cpu.idleJump()


def ReturnLong(cpu: Cpu):
    cpu.idle()
    cpu.idle()
    cpu.V.l = cpu.pullN()
    cpu.V.h = cpu.pullN()
    cpu.V.b = cpu.pullN()
    cpu.PC.d = cpu.V.d
    cpu.PC.w += 1
    if cpu.EF:
        cpu.S.h = 0x01
    cpu.idleJump()
