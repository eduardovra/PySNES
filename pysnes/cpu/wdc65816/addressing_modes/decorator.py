from typing import TYPE_CHECKING
import functools

if TYPE_CHECKING:
    from ...cpu import Cpu


def decorator_mode_8bit(func):
    """Creates function variants for 8/16 bit modes based on M/X flag"""
    @functools.wraps(func)
    def mf_wrapper(cpu: "Cpu", *args, **kwargs):
        return func(cpu, cpu.MFlag, *args, **kwargs)
    func.MF = mf_wrapper

    @functools.wraps(func)
    def xf_wrapper(cpu: "Cpu", *args, **kwargs):
        return func(cpu, cpu.XFlag, *args, **kwargs)
    func.XF = xf_wrapper

    return func
