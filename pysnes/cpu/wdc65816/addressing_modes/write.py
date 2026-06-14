from ...cpu import Cpu, Reg

from .decorator import decorator_mode_8bit

# Shared read-only zero register used as the "no index" offset (i.w == 0).
# The source `F` and index `i` register args are pre-resolved to Reg objects (or
# None for an absent index) at table-build time, avoiding per-call getattr.
_ZERO = Reg(16, 0)


@decorator_mode_8bit
def BankWrite(cpu: Cpu, mode_8bit: bool, F: Reg, i: Reg | None = None):
    if mode_8bit:
        if i is None:
            cpu.V.l = cpu.fetch()
            cpu.V.h = cpu.fetch()
            cpu.writeBank(cpu.V.w + 0, F.l)
        else:
            cpu.V.l = cpu.fetch()
            cpu.V.h = cpu.fetch()
            cpu.idle()
            cpu.writeBank(cpu.V.w + i.w + 0, F.l)
    else:
        if i is None:
            cpu.V.l = cpu.fetch()
            cpu.V.h = cpu.fetch()
            cpu.writeBank(cpu.V.w + 0, F.l)
            cpu.writeBank(cpu.V.w + 1, F.h)
        else:
            cpu.V.l = cpu.fetch()
            cpu.V.h = cpu.fetch()
            cpu.idle()
            cpu.writeBank(cpu.V.w + i.w + 0, F.l)
            cpu.writeBank(cpu.V.w + i.w + 1, F.h)


@decorator_mode_8bit
def LongWrite(cpu: Cpu, mode_8bit: bool, i: Reg = _ZERO):
    if mode_8bit:
        cpu.V.l = cpu.fetch()
        cpu.V.h = cpu.fetch()
        cpu.V.b = cpu.fetch()
        cpu.writeLong(cpu.V.d + i.w + 0, cpu.A.l)
    else:
        cpu.V.l = cpu.fetch()
        cpu.V.h = cpu.fetch()
        cpu.V.b = cpu.fetch()
        cpu.writeLong(cpu.V.d + i.w + 0, cpu.A.l)
        cpu.writeLong(cpu.V.d + i.w + 1, cpu.A.h)


@decorator_mode_8bit
def DirectWrite(cpu: Cpu, mode_8bit: bool, F: Reg, i: Reg | None = None):
    off = i.w if i is not None else 0

    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        if i is not None:
            cpu.idle()
        cpu.writeDirect(cpu.U.l + off + 0, F.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        if i is not None:
            cpu.idle()
        cpu.writeDirect(cpu.U.l + off + 0, F.l)
        cpu.writeDirect(cpu.U.l + off + 1, F.h)


@decorator_mode_8bit
def IndirectWrite(cpu: Cpu, mode_8bit: bool):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirect(cpu.U.l + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + 1)
        cpu.writeBank(cpu.V.w + 0, cpu.A.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirect(cpu.U.l + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + 1)
        cpu.writeBank(cpu.V.w + 0, cpu.A.l)
        cpu.writeBank(cpu.V.w + 1, cpu.A.h)


@decorator_mode_8bit
def IndexedIndirectWrite(cpu: Cpu, mode_8bit: bool):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.idle()
        cpu.V.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1)
        cpu.writeBank(cpu.V.w + 0, cpu.A.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.idle()
        cpu.V.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1)
        cpu.writeBank(cpu.V.w + 0, cpu.A.l)
        cpu.writeBank(cpu.V.w + 1, cpu.A.h)


@decorator_mode_8bit
def IndirectIndexedWrite(cpu: Cpu, mode_8bit: bool):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirect(cpu.U.l + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + 1)
        cpu.idle()
        cpu.writeBank(cpu.V.w + cpu.Y.w + 0, cpu.A.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirect(cpu.U.l + 0)
        cpu.V.h = cpu.readDirect(cpu.U.l + 1)
        cpu.idle()
        cpu.writeBank(cpu.V.w + cpu.Y.w + 0, cpu.A.l)
        cpu.writeBank(cpu.V.w + cpu.Y.w + 1, cpu.A.h)


@decorator_mode_8bit
def IndirectLongWrite(cpu: Cpu, mode_8bit: bool, i: Reg = _ZERO):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirectN(cpu.U.l + 0)
        cpu.V.h = cpu.readDirectN(cpu.U.l + 1)
        cpu.V.b = cpu.readDirectN(cpu.U.l + 2)
        cpu.writeLong(cpu.V.d + i.w + 0, cpu.A.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle2()
        cpu.V.l = cpu.readDirectN(cpu.U.l + 0)
        cpu.V.h = cpu.readDirectN(cpu.U.l + 1)
        cpu.V.b = cpu.readDirectN(cpu.U.l + 2)
        cpu.writeLong(cpu.V.d + i.w + 0, cpu.A.l)
        cpu.writeLong(cpu.V.d + i.w + 1, cpu.A.h)


@decorator_mode_8bit
def StackWrite(cpu: Cpu, mode_8bit: bool):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle()
        cpu.writeStack(cpu.U.l + 0, cpu.A.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle()
        cpu.writeStack(cpu.U.l + 0, cpu.A.l)
        cpu.writeStack(cpu.U.l + 1, cpu.A.h)


@decorator_mode_8bit
def IndirectStackWrite(cpu: Cpu, mode_8bit: bool):
    if mode_8bit:
        cpu.U.l = cpu.fetch()
        cpu.idle()
        cpu.V.l = cpu.readStack(cpu.U.l + 0)
        cpu.V.h = cpu.readStack(cpu.U.l + 1)
        cpu.idle()
        cpu.writeBank(cpu.V.w + cpu.Y.w + 0, cpu.A.l)
    else:
        cpu.U.l = cpu.fetch()
        cpu.idle()
        cpu.V.l = cpu.readStack(cpu.U.l + 0)
        cpu.V.h = cpu.readStack(cpu.U.l + 1)
        cpu.idle()
        cpu.writeBank(cpu.V.w + cpu.Y.w + 0, cpu.A.l)
        cpu.writeBank(cpu.V.w + cpu.Y.w + 1, cpu.A.h)
