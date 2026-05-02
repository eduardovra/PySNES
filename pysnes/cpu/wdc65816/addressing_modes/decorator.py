from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...cpu import Cpu


def decorator_mode_8bit(func):
    """Creates fixed-arity function variants for 8/16-bit modes based on M/X flag.

    Three variants per flag (MF0/MF/MF2, XF0/XF/XF2) avoid *args/**kwargs
    so PyPy's JIT can trace through without tuple allocation.
    """
    def mf_0(cpu: "Cpu"):
        return func(cpu, cpu.MFlag)
    func.MF0 = mf_0

    def mf_1(cpu: "Cpu", a):
        return func(cpu, cpu.MFlag, a)
    func.MF = mf_1

    def mf_2(cpu: "Cpu", a, b):
        return func(cpu, cpu.MFlag, a, b)
    func.MF2 = mf_2

    def xf_0(cpu: "Cpu"):
        return func(cpu, cpu.XFlag)
    func.XF0 = xf_0

    def xf_1(cpu: "Cpu", a):
        return func(cpu, cpu.XFlag, a)
    func.XF = xf_1

    def xf_2(cpu: "Cpu", a, b):
        return func(cpu, cpu.XFlag, a, b)
    func.XF2 = xf_2

    return func
