from typing import Callable
from ctypes import c_int16

from ...cpu import Cpu, Reg
from .decorator import decorator_mode_8bit


@decorator_mode_8bit
def BitImmediate(cpu: Cpu, mode_8bit: bool):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.ZFlag = (cpu.U.l & cpu.A.l) == 0
    else:
        cpu.U.l = cpu.fetch()
        cpu.U.h = cpu.fetch()
        cpu.ZFlag = (cpu.U.w & cpu.A.w) == 0


def NoOperation(cpu: Cpu):
    cpu.idleIRQ()


def Prefix(cpu: Cpu):
    cpu.fetch()


def ExchangeBA(cpu: Cpu):
  cpu.idle()
  cpu.idle()
  cpu.A.w = cpu.A.w >> 8 | cpu.A.w << 8
  cpu.ZFlag = cpu.A.l == 0
  cpu.NFlag = bool(cpu.A.l & 0x80)


@decorator_mode_8bit
def BlockMove(cpu: Cpu, mode_8bit: bool, adjust: int):
    if mode_8bit:
        cpu.U.b = cpu.fetch()
        cpu.V.b = cpu.fetch()
        cpu.DB.l = cpu.U.b
        cpu.W.l = cpu.read(cpu.V.b << 16 | cpu.X.w)
        cpu.write(cpu.U.b << 16 | cpu.Y.w, cpu.W.l)
        cpu.idle()
        cpu.X.l += adjust
        cpu.Y.l += adjust
        cpu.idle()
        if cpu.A.w:
            cpu.PC.w -= 3
        cpu.A.w -= 1
    else:
        cpu.U.b = cpu.fetch()
        cpu.V.b = cpu.fetch()
        cpu.DB.l = cpu.U.b
        cpu.W.l = cpu.read(cpu.V.b << 16 | cpu.X.w)
        cpu.write(cpu.U.b << 16 | cpu.Y.w, cpu.W.l)
        cpu.idle()
        cpu.X.w += adjust
        cpu.Y.w += adjust
        cpu.idle()
        if cpu.A.w:
            cpu.PC.w -= 3
        cpu.A.w -= 1


def Interrupt(cpu: Cpu, get_vector: Callable):
    vector = Reg(16, get_vector(cpu))
    cpu.fetch()
    if not cpu.EF:
        cpu.push(cpu.PC.b)
    cpu.push(cpu.PC.h)
    cpu.push(cpu.PC.l)
    cpu.push(cpu.P)
    cpu.IFlag = True
    cpu.DFlag = False
    cpu.PC.l = cpu.read(vector.w + 0)
    cpu.PC.h = cpu.read(vector.w + 1)
    cpu.PC.b = 0x00


def Stop(cpu: Cpu):
    cpu.stp = True
    # Two ghost reads of PC+1 plus the first "stopped" cycle are visible on
    # the bus before the core actually halts (see TomHarte db.*.json traces).
    cpu.idle()
    cpu.idle()
    cpu.idle()
    while cpu.stp and not cpu.synchronizing():
        cpu.idle()


def Wait(cpu: Cpu):
    cpu.wai = True
    # Two ghost reads of PC+1 plus the first "waiting" cycle are visible on
    # the bus before the core blocks on an interrupt (cb.*.json traces).
    cpu.idle()
    cpu.idle()
    while cpu.wai and not cpu.synchronizing():
        cpu.idle()
    cpu.idle()


def ExchangeCE(cpu: Cpu):
    cpu.idleIRQ()
    cpu.CFlag, cpu.EF = cpu.EF, cpu.CFlag
    if cpu.EF:
        cpu.XFlag = True
        cpu.MFlag = True
        cpu.X.h = 0x00
        cpu.Y.h = 0x00
        cpu.S.h = 0x01


def SetFlag(cpu: Cpu, flag: str):
    cpu.idleIRQ()
    setattr(cpu, flag, True)


def ClearFlag(cpu: Cpu, flag: str):
    cpu.idleIRQ()
    setattr(cpu, flag, False)


def ResetP(cpu: Cpu):
    cpu.W.l = cpu.fetch()
    cpu.idle()
    cpu.P = cpu.P & ~cpu.W.l
    if cpu.EF:
        cpu.XFlag = True
        cpu.MFlag = True
    if cpu.XFlag:
        cpu.X.h = 0x00
        cpu.Y.h = 0x00


def SetP(cpu: Cpu):
    cpu.W.l = cpu.fetch()
    cpu.idle()
    cpu.P = cpu.P | cpu.W.l
    if cpu.EF:
        cpu.XFlag = True
        cpu.MFlag = True
    if cpu.XFlag:
        cpu.X.h = 0x00
        cpu.Y.h = 0x00


@decorator_mode_8bit
def Transfer(cpu: Cpu, mode_8bit: bool, f: str, t: str):
    F = getattr(cpu, f)
    T = getattr(cpu, t)
    if mode_8bit:
        cpu.idleIRQ()
        T.l = F.l
        cpu.ZFlag = T.l == 0
        cpu.NFlag = bool(T.l & 0x80)
    else:
        cpu.idleIRQ()
        T.w = F.w
        cpu.ZFlag = T.w == 0
        cpu.NFlag = bool(T.w & 0x8000)


def Transfer16(cpu: Cpu, f: str, t: str):
    Transfer(cpu, False, f, t)


def TransferCS(cpu: Cpu):
    cpu.idleIRQ()
    cpu.S.w = cpu.A.w
    if cpu.EF:
        cpu.S.h = 0x01


@decorator_mode_8bit
def TransferSX(cpu: Cpu, mode_8bit: bool):
    if mode_8bit:
        cpu.idleIRQ()
        cpu.X.l = cpu.S.l
        cpu.ZFlag = cpu.X.l == 0
        cpu.NFlag = bool(cpu.X.l & 0x80)
    else:
        cpu.idleIRQ()
        cpu.X.w = cpu.S.w
        cpu.ZFlag = cpu.X.w == 0
        cpu.NFlag = bool(cpu.X.w & 0x8000)


def TransferXS(cpu: Cpu):
    cpu.idleIRQ()
    if cpu.EF:
        cpu.S.l = cpu.X.l
    else:
        cpu.S.w = cpu.X.w


def Push8(cpu: Cpu, f: str):
    f_split = f.split(".")  # to suport 'PC.b'
    F = getattr(cpu, f_split[0])
    if len(f_split) > 1:
        F = getattr(F, f_split[1])

    # workaround for the fact that F can be an int (status reg) or a Reg
    F = F if isinstance(F, Reg) else Reg(8, F)

    cpu.idle()
    cpu.push(F.l)


@decorator_mode_8bit
def Push(cpu: Cpu, mode_8bit: bool, f: str):
    F = getattr(cpu, f)
    if mode_8bit:
        cpu.idle()
        cpu.push(F.l)
    else:
        cpu.idle()
        cpu.push(F.h)
        cpu.push(F.l)


def PushD(cpu: Cpu):
    cpu.idle()
    cpu.pushN(cpu.D.h)
    cpu.pushN(cpu.D.l)
    if cpu.EF:
        cpu.S.h = 0x01


@decorator_mode_8bit
def Pull(cpu: Cpu, mode_8bit: bool, t: str):
    T = getattr(cpu, t)
    if mode_8bit:
        cpu.idle()
        cpu.idle()
        T.l = cpu.pull()
        cpu.ZFlag = T.l == 0
        cpu.NFlag = bool(T.l & 0x80)
    else:
        cpu.idle()
        cpu.idle()
        T.l = cpu.pull()
        T.h = cpu.pull()
        cpu.ZFlag = T.w == 0
        cpu.NFlag = bool(T.w & 0x8000)


def PullD(cpu: Cpu):
    cpu.idle()
    cpu.idle()
    cpu.D.l = cpu.pullN()
    cpu.D.h = cpu.pullN()
    cpu.ZFlag = cpu.D.w == 0
    cpu.NFlag = bool(cpu.D.w & 0x8000)
    if cpu.EF:
        cpu.S.h = 0x01


def PullB(cpu: Cpu):
    cpu.idle()
    cpu.idle()
    cpu.DB.l = cpu.pull()
    cpu.ZFlag = cpu.DB.l == 0
    cpu.NFlag = bool(cpu.DB.l & 0x80)


def PullP(cpu: Cpu):
    cpu.idle()
    cpu.idle()
    cpu.P = cpu.pull()
    if cpu.EF:
        cpu.XFlag = True
        cpu.MFlag = True
    if cpu.XFlag:
        cpu.X.h = 0x00
        cpu.Y.h = 0x00


def PushEffectiveAddress(cpu: Cpu):
    cpu.W.l = cpu.fetch()
    cpu.W.h = cpu.fetch()
    cpu.pushN(cpu.W.h)
    cpu.pushN(cpu.W.l)
    if cpu.EF:
        cpu.S.h = 0x01


def PushEffectiveIndirectAddress(cpu: Cpu):
    cpu.U.l = cpu.fetch()
    cpu.idle2()
    cpu.W.l = cpu.readDirectN(cpu.U.l + 0)
    cpu.W.h = cpu.readDirectN(cpu.U.l + 1)
    cpu.pushN(cpu.W.h)
    cpu.pushN(cpu.W.l)
    if cpu.EF:
        cpu.S.h = 0x01


def PushEffectiveRelativeAddress(cpu: Cpu):
    cpu.V.l = cpu.fetch()
    cpu.V.h = cpu.fetch()
    cpu.idle()
    displacement = c_int16(cpu.V.w)
    cpu.W.w = cpu.PC.d + displacement.value
    cpu.pushN(cpu.W.h)
    cpu.pushN(cpu.W.l)
    if cpu.EF:
        cpu.S.h = 0x01
