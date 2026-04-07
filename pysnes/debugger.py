"""
PySNES Debugger — hooks into cpu._step to support breakpoints and stepping.
Zero overhead while the emulator is running with no breakpoints set.
"""
from __future__ import annotations

import queue
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .pysnes import PySNES


# Maps disassembler addressing-mode method names to byte lengths.
# Variable-length modes (immediateA, immediateX) are handled separately.
_MODE_LENGTHS: dict[str, int] = {
    "implied":            1,
    "immediate":          2,
    "direct":             2,
    "directX":            2,
    "directY":            2,
    "indirect":           2,
    "indexedIndirectX":   2,
    "indirectIndexedY":   2,
    "indirectLong":       2,
    "indirectLongY":      2,
    "relative":           2,
    "stack":              2,
    "stackIndirect":      2,
    "absolute":           3,
    "absoluteX":          3,
    "absoluteY":          3,
    "absolutePC":         3,
    "indirectPC":         3,
    "indirectX":          3,
    "relativeWord":       3,
    "move":               3,
    "per":                3,
    "absoluteLong":       4,
    "absoluteLongX":      4,
    "indirectLongPC":     4,
}


class Debugger:
    def __init__(self, pysnes: PySNES) -> None:
        self._pysnes = pysnes
        self._cpu = pysnes.cpu
        self._bus = pysnes.bus
        self._ppu = pysnes.ppu
        self._scheduler = pysnes.scheduler

        self._breakpoints: set[int] = set()
        self._step_mode: bool = False
        self._instr_count: int = 0

        self._original_step = None
        self._cmd_queue: queue.Queue = queue.Queue()
        self._window = None

    def attach(self) -> None:
        """Wrap cpu._step. Call once after cpu.attach(bus)."""
        self._original_step = self._cpu._step
        self._install_hooks()

    def _install_hooks(self) -> None:
        """Install or remove the step wrapper based on whether it is needed."""
        if self._breakpoints or self._step_mode:
            self._cpu._step = self._hooked_step
        else:
            self._cpu._step = self._original_step

    def _hooked_step(self) -> None:
        pc = self._cpu.PC.d
        if pc in self._breakpoints:
            # Execute the instruction, then pause (PC now points to the next instruction)
            self._original_step()
            self._pysnes.paused = True
            self._step_mode = False
            self._install_hooks()
            self._notify_paused()
            return
        if self._step_mode:
            self._step_mode = False
            self._original_step()
            self._instr_count += 1
            self._install_hooks()
            return
        self._original_step()
        self._instr_count += 1

    def toggle_breakpoint(self, addr: int) -> None:
        if addr in self._breakpoints:
            self._breakpoints.discard(addr)
        else:
            self._breakpoints.add(addr)
        self._install_hooks()

    def step_one_instruction(self) -> None:
        """Execute exactly one CPU instruction (including PPU/APU events)."""
        self._step_mode = True
        self._install_hooks()
        target = self._instr_count + 1
        while self._instr_count < target:
            self._scheduler.run_one()

    def _notify_paused(self) -> None:
        """Signal the Tkinter window to refresh. Called from the main thread."""
        if self._window is not None:
            self._window.root.after(0, self._window.refresh)

    def drain_commands(self) -> None:
        """Process commands from the Tkinter thread. Called every main loop iteration."""
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
                self.step_one_instruction()
                self._notify_paused()
            elif action == "continue":
                self._pysnes.paused = False
            elif action == "pause":
                self._pysnes.paused = True
                self._notify_paused()

    def disassemble_forward(self, pc: int, count: int) -> list[str]:
        """Return up to `count` disassembled instruction strings starting at `pc`."""
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
        """Advance PC past the instruction at `pc` using the addressing mode table."""
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
            # Window already exists; try to raise it
            try:
                self._window.root.after(0, self._window.root.lift)
            except Exception:
                pass
            return

        from .debugger_window import DebuggerWindow

        def _run():
            win = DebuggerWindow(self._cpu, self._bus, self._ppu, self)
            self._window = win
            self._cpu.trace_enabled = True   # populate trace_log for disasm history
            win.root.mainloop()
            win.root.destroy()               # destroy in daemon (Tkinter) thread
            self._cpu.trace_enabled = False
            self._window = None

        t = threading.Thread(target=_run, daemon=True)
        t.start()
