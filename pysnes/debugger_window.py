"""
PySNES Debugger Window — Tkinter UI.
Reads CPU/PPU/bus state directly (no copies) when the emulator is paused.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .debugger import Debugger
    from .cpu.cpu import Cpu
    from .bus.bus import Bus
    from .ppu.ppu import Ppu

# Memory regions selectable in the memory view
_REGIONS = ["WRAM", "VRAM", "CGRAM"]

# Bytes displayed per row in the hex view
_HEX_COLS = 16


def _flags_str(cpu) -> str:
    p = cpu.P
    names = ("N", "V", "M", "X", "D", "I", "Z", "C")
    bits  = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)
    return "".join(n if p & b else n.lower() for n, b in zip(names, bits))


class DebuggerWindow:
    def __init__(self, cpu: Cpu, bus: Bus, ppu: Ppu, debugger: Debugger) -> None:
        self._cpu = cpu
        self._bus = bus
        self._ppu = ppu
        self._debugger = debugger

        self.root = tk.Tk()
        self.root.title("PySNES Debugger")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._mem_region = tk.StringVar(value="WRAM")
        self._mem_addr_var = tk.StringVar(value="0000")
        self._mem_addr: int = 0

        self._build_ui()
        self.refresh()
        self._poll()  # start the notify-queue polling loop

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self.root
        root.configure(bg="#1e1e1e")

        # ── Top: registers + disassembly side by side ──────────────────
        top = ttk.Frame(root)
        top.pack(fill="both", expand=True, padx=6, pady=(6, 3))

        self._reg_text = self._make_text(top, width=42, height=6)
        self._reg_text.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self._disasm_text = self._make_text(top, width=62, height=12)
        self._disasm_text.pack(side="left", fill="both", expand=True)

        # ── Middle: memory view ────────────────────────────────────────
        mid = ttk.Frame(root)
        mid.pack(fill="both", expand=True, padx=6, pady=3)

        mem_ctrl = ttk.Frame(mid)
        mem_ctrl.pack(fill="x")

        ttk.Label(mem_ctrl, text="Region:").pack(side="left")
        for r in _REGIONS:
            ttk.Radiobutton(mem_ctrl, text=r, variable=self._mem_region, value=r,
                            command=self._on_mem_region_change).pack(side="left", padx=2)
        ttk.Label(mem_ctrl, text="  Addr:").pack(side="left")
        addr_entry = ttk.Entry(mem_ctrl, textvariable=self._mem_addr_var, width=6)
        addr_entry.pack(side="left")
        addr_entry.bind("<Return>", self._on_mem_addr_change)

        self._mem_text = self._make_text(mid, width=80, height=10)
        self._mem_text.pack(fill="both", expand=True, pady=(2, 0))

        # ── Bottom: breakpoints + controls ────────────────────────────
        bot = ttk.Frame(root)
        bot.pack(fill="both", padx=6, pady=(3, 6))

        bp_frame = ttk.LabelFrame(bot, text="Breakpoints")
        bp_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self._bp_list = tk.Listbox(bp_frame, bg="#252526", fg="#d4d4d4",
                                   selectbackground="#094771", font=("Courier", 10),
                                   height=6, width=12)
        self._bp_list.pack(side="left", fill="both", expand=True)

        bp_btns = ttk.Frame(bp_frame)
        bp_btns.pack(side="left", padx=4)
        ttk.Button(bp_btns, text="Break at PC",
                   command=self._cmd_toggle_bp_at_pc).pack(fill="x", pady=2)
        ttk.Button(bp_btns, text="Remove selected",
                   command=self._cmd_remove_bp).pack(fill="x", pady=2)

        ctrl = ttk.LabelFrame(bot, text="Controls")
        ctrl.pack(side="left", fill="y")
        ttk.Button(ctrl, text="Step (N)",     command=self._cmd_step).pack(fill="x", pady=2, padx=6)
        ttk.Button(ctrl, text="Continue (C)", command=self._cmd_continue).pack(fill="x", pady=2, padx=6)
        ttk.Button(ctrl, text="Pause",        command=self._cmd_pause).pack(fill="x", pady=2, padx=6)

        # ── Status bar ────────────────────────────────────────────────
        self._status_var = tk.StringVar(value="Running")
        ttk.Label(root, textvariable=self._status_var, anchor="w").pack(
            fill="x", padx=6, pady=(0, 4))

    def _make_text(self, parent, **kwargs) -> tk.Text:
        t = tk.Text(parent, bg="#1e1e1e", fg="#d4d4d4",
                    insertbackground="#d4d4d4",
                    font=("Courier", 10), state="disabled",
                    relief="flat", borderwidth=1, **kwargs)
        t.tag_configure("pc",      foreground="#569cd6", background="#094771")
        t.tag_configure("bp",      foreground="#f44747")
        t.tag_configure("history", foreground="#808080")
        t.tag_configure("reg_label", foreground="#9cdcfe")
        t.tag_configure("reg_val",   foreground="#ce9178")
        return t

    # ------------------------------------------------------------------
    # Polling loop (Tkinter thread only) — checks emulator → window queue
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Called every 100 ms in the Tkinter thread to process refresh signals."""
        if not self._debugger._notify_queue.empty():
            # Drain all pending notifications; a single refresh is enough
            while not self._debugger._notify_queue.empty():
                self._debugger._notify_queue.get_nowait()
            self.refresh()
        self.root.after(100, self._poll)

    # ------------------------------------------------------------------
    # Refresh — always called from the Tkinter thread
    # ------------------------------------------------------------------

    def refresh(self) -> None:
        cpu = self._cpu
        paused = self._debugger._pysnes.paused

        self._status_var.set("PAUSED" if paused else "Running")

        self._refresh_registers(cpu)
        if paused:
            self._refresh_disassembly(cpu)
            self._refresh_memory()
        self._refresh_breakpoints()

    def _refresh_registers(self, cpu) -> None:
        p = _flags_str(cpu)
        text = (
            f" A: {cpu.A.w:04X}   X: {cpu.X.w:04X}   Y: {cpu.Y.w:04X}\n"
            f" S: {cpu.S.w:04X}   D: {cpu.D.w:04X}  DB: {cpu.DB.l:02X}\n"
            f"PC: {cpu.PC.d:06X}   P: {p}  EF: {int(cpu.EF)}\n"
            f"MC: {self._debugger._scheduler.master_clock}\n"
        )
        self._set_text(self._reg_text, text)

    def _refresh_disassembly(self, cpu) -> None:
        current_pc = cpu.PC.d
        bps = self._debugger._breakpoints

        # History: last instructions from trace_log (up to 5)
        history = list(cpu.trace_log)[-5:]
        # Forward: current PC + 4 more
        forward = self._debugger.disassemble_forward(current_pc, 5)

        self._disasm_text.configure(state="normal")
        self._disasm_text.delete("1.0", "end")

        for line in history:
            addr_str = line[:6]
            tag = "bp" if int(addr_str, 16) in bps else "history"
            self._disasm_text.insert("end", line[:40] + "\n", tag)

        for i, line in enumerate(forward):
            addr_str = line[:6]
            is_current = (i == 0)
            is_bp = int(addr_str, 16) in bps
            tag = "pc" if is_current else ("bp" if is_bp else "")
            prefix = "► " if is_current else "  "
            self._disasm_text.insert("end", prefix + line[:38] + "\n", tag)

        self._disasm_text.configure(state="disabled")

    def _refresh_memory(self) -> None:
        region = self._mem_region.get()
        base = self._mem_addr
        data = self._read_memory(region, base, _HEX_COLS * 8)

        lines = []
        for row in range(0, len(data), _HEX_COLS):
            chunk = data[row:row + _HEX_COLS]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
            lines.append(f"{region}:{base + row:04X}  {hex_part:<{_HEX_COLS * 3}}  {ascii_part}")

        self._set_text(self._mem_text, "\n".join(lines))

    def _read_memory(self, region: str, base: int, length: int) -> bytes:
        if region == "WRAM":
            result = bytearray()
            for offset in range(length):
                addr = base + offset
                if addr < 0x2000:
                    result.append(self._bus.low_ram[addr])
                elif addr < 0x10000:
                    result.append(self._bus.high_ram[addr - 0x2000])
                elif addr < 0x80000:
                    result.append(self._bus.extended_ram[addr - 0x10000])
                else:
                    result.append(0)
            return bytes(result)
        elif region == "VRAM":
            end = min(base + length, len(self._ppu.vram))
            return bytes(self._ppu.vram[base:end])
        elif region == "CGRAM":
            end = min(base + length, len(self._ppu.cgram))
            return bytes(self._ppu.cgram[base:end])
        return b"\x00" * length

    def _refresh_breakpoints(self) -> None:
        bps = sorted(self._debugger._breakpoints)
        self._bp_list.delete(0, "end")
        for addr in bps:
            self._bp_list.insert("end", f"{addr:06X}")

    def _set_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # ------------------------------------------------------------------
    # Event handlers / button commands
    # ------------------------------------------------------------------

    def _on_mem_region_change(self) -> None:
        self._mem_addr = 0
        self._mem_addr_var.set("0000")
        self._refresh_memory()

    def _on_mem_addr_change(self, _event=None) -> None:
        try:
            self._mem_addr = int(self._mem_addr_var.get(), 16)
        except ValueError:
            self._mem_addr = 0
            self._mem_addr_var.set("0000")
        self._refresh_memory()

    def _cmd_toggle_bp_at_pc(self) -> None:
        addr = self._cpu.PC.d
        self._debugger._cmd_queue.put(("toggle_bp", addr))

    def _cmd_remove_bp(self) -> None:
        sel = self._bp_list.curselection()
        if not sel:
            return
        addr = int(self._bp_list.get(sel[0]), 16)
        self._debugger._cmd_queue.put(("toggle_bp", addr))

    def _cmd_step(self) -> None:
        self._debugger._cmd_queue.put(("step",))

    def _cmd_continue(self) -> None:
        self._debugger._cmd_queue.put(("continue",))
        self._status_var.set("Running")

    def _cmd_pause(self) -> None:
        self._debugger._cmd_queue.put(("pause",))

    def _on_close(self) -> None:
        self.root.quit()  # stops mainloop; destroy() is called in the daemon thread
