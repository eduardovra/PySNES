"""
PySNES Debugger — hooks into cpu._step to support breakpoints and stepping.
Zero overhead while the emulator is running with no breakpoints set.
"""

from __future__ import annotations

import heapq
import queue
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..pysnes import PySNES


# Maps disassembler addressing-mode method names to byte lengths.
# Variable-length modes (immediateA, immediateX) are handled separately.
_MODE_LENGTHS: dict[str, int] = {
    "implied": 1,
    "immediate": 2,
    "direct": 2,
    "directX": 2,
    "directY": 2,
    "indirect": 2,
    "indexedIndirectX": 2,
    "indirectIndexedY": 2,
    "indirectLong": 2,
    "indirectLongY": 2,
    "relative": 2,
    "stack": 2,
    "stackIndirect": 2,
    "absolute": 3,
    "absoluteX": 3,
    "absoluteY": 3,
    "absolutePC": 3,
    "indirectPC": 3,
    "indirectX": 3,
    "relativeWord": 3,
    "move": 3,
    "per": 3,
    "absoluteLong": 4,
    "absoluteLongX": 4,
    "indirectLongPC": 4,
}


class BreakpointHit(Exception):
    pass


class Debugger:
    def __init__(self, pysnes: PySNES) -> None:
        self._pysnes = pysnes
        self._cpu = pysnes.cpu
        self._bus = pysnes.bus
        self._ppu = pysnes.ppu
        self._scheduler = pysnes.scheduler

        self._breakpoints: set[int] = set()
        self._instr_count: int = 0

        self._original_step = None
        self._cmd_queue: queue.Queue = queue.Queue()  # Tkinter → emulator
        self._notify_queue: queue.Queue = queue.Queue()  # emulator → Tkinter
        self._window = None

    def attach(self) -> None:
        """Wrap cpu._step. Call once after cpu.attach(bus)."""
        self._original_step = self._cpu._step
        self._install_hooks()

    def _install_hooks(self) -> None:
        """Install or remove the step wrapper based on whether it is needed."""
        if self._breakpoints:
            self._cpu._step = self._hooked_step
        else:
            self._cpu._step = self._original_step

    def _hooked_step(self) -> None:
        pc = self._cpu.PC.d
        if pc in self._breakpoints:
            # Execute the instruction, then pause (PC now points to the next
            # instruction)
            self._original_step()
            self._pysnes.paused = True
            self._install_hooks()
            self._notify_paused()
            raise BreakpointHit()
        self._original_step()
        self._instr_count += 1

    def toggle_breakpoint(self, addr: int) -> None:
        if addr in self._breakpoints:
            self._breakpoints.discard(addr)
        else:
            self._breakpoints.add(addr)
        self._install_hooks()

    def step_one_instruction(self) -> None:
        """Execute exactly one CPU instruction.

        The scheduler queue holds a CPU step event — either _original_step or
        the rebound _hooked_step. We drop *any* queued step (matching by
        bound-method equality, since _install_hooks rebinds _hooked_step on
        every call) and call _original_step() directly; the CPU's trailing
        scheduler.add inside _step will re-queue the next step, leaving the
        net event count unchanged.
        """
        q = self._scheduler._queue
        orig = self._original_step
        cur = self._cpu._step
        q[:] = [e for e in q if not (e[-1] == orig or e[-1] == cur)]
        heapq.heapify(q)
        self._original_step()
        self._instr_count += 1

    def _notify_paused(self) -> None:
        """Signal the Tkinter window to refresh. Thread-safe: puts to a
        queue."""
        if self._window is not None:
            self._notify_queue.put(True)

    def drain_commands(self) -> None:
        """Process commands from the Tkinter thread. Called every main loop
        iteration."""
        while not self._cmd_queue.empty():
            try:
                cmd = self._cmd_queue.get_nowait()
            except queue.Empty:
                break
            action = cmd[0]
            if action == "toggle_bp":
                self.toggle_breakpoint(cmd[1])
                self._notify_paused()
            elif action == "step":
                done_event = cmd[1]
                self.step_one_instruction()
                # unblocks Tkinter thread so it can refresh immediately
                done_event.set()
            elif action == "continue":
                self._pysnes.paused = False
            elif action == "pause":
                self._pysnes.paused = True
                self._notify_paused()
            elif action == "reset":
                self._pysnes.reset()

    def disassemble_forward(self, pc: int, count: int) -> list[str]:
        """Return up to `count` disassembled instruction strings starting at
        `pc`."""
        disasm = self._cpu.disassembler
        results = []
        for _ in range(count):
            try:
                line = disasm.disassemble(pc)
                results.append(line)
                pc = self._next_pc(pc)
            except Exception:
                break
        return results

    def _next_pc(self, pc: int) -> int:
        """Advance PC past the instruction at `pc` using the addressing mode
        table."""
        disasm = self._cpu.disassembler
        bank = pc & 0xFF0000
        addr = pc & 0xFFFF
        opcode = disasm.read(pc)
        _, _name, func = disasm.TABLE[opcode]
        func_name = func.__name__
        if func_name == "immediateA":
            length = 2 if self._cpu.MFlag else 3
        elif func_name == "immediateX":
            length = 2 if self._cpu.XFlag else 3
        else:
            length = _MODE_LENGTHS.get(func_name, 2)
        return bank | ((addr + length) & 0xFFFF)

    def open_window(self) -> None:
        """Open the Tkinter debug window in a daemon thread (idempotent)."""
        if self._window is not None:
            return  # already open; window is managed by the daemon thread

        import gc

        from .window import DebuggerWindow

        def _run():
            win = DebuggerWindow(self._cpu, self._bus, self._ppu, self)
            self._window = win
            # populate trace_log for disasm history
            self._cpu.trace_enabled = True
            win.root.mainloop()
            win.root.destroy()  # destroy in daemon (Tkinter) thread
            self._cpu.trace_enabled = False
            self._window = None
            # Force Tk object teardown on this (Tcl-owning) thread. On PyPy the
            # tracing GC would otherwise reclaim `win` later from the main
            # thread, triggering "Tcl_AsyncDelete: async handler deleted by
            # the wrong thread".
            win = None
            gc.collect()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
