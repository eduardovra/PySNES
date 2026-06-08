from typing import TYPE_CHECKING
import functools

if TYPE_CHECKING:
    from ...cpu import Cpu


def decorator_mode_8bit(func):
    """Creates function variants for 8/16 bit modes based on M/X flag.

    The wrappers forward only positional args (the instruction table never
    passes keywords), so they avoid the per-call empty-**kwargs dict. They run
    once per executed M/X instruction, so the dispatch overhead matters.
    """
    @functools.wraps(func)
    def mf_wrapper(cpu: "Cpu", *args):
        return func(cpu, cpu.MFlag, *args)
    func.MF = mf_wrapper

    @functools.wraps(func)
    def xf_wrapper(cpu: "Cpu", *args):
        return func(cpu, cpu.XFlag, *args)
    func.XF = xf_wrapper

    return func
