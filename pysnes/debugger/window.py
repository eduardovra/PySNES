"""
PySNES Debugger Window — Tkinter UI.
Reads CPU/PPU/bus state directly (no copies) when the emulator is paused.
All reads use direct Python attribute access — never bus.read() — to avoid
hardware register side effects (e.g. OAM/CGRAM address auto-increment).
"""
from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import Debugger
    from ..cpu.cpu import Cpu
    from ..bus.bus import Bus
    from ..ppu.ppu import Ppu

# Memory regions selectable in the memory view
_REGIONS = ["WRAM", "VRAM", "CGRAM", "ROM"]

# Bytes displayed per row in the hex view
_HEX_COLS = 16


def _cpu_flags_str(cpu) -> str:
    p = cpu.P
    names = ("N", "V", "M", "X", "D", "I", "Z", "C")
    bits  = (0x80, 0x40, 0x20, 0x10, 0x08, 0x04, 0x02, 0x01)
    return "".join(n if p & b else n.lower() for n, b in zip(names, bits))


def _apu_flags_str(apu) -> str:
    flags = (
        ("N", apu.NF), ("V", apu.VF), ("P", apu.PF), ("B", apu.BF),
        ("H", apu.HF), ("I", apu.IF), ("Z", apu.ZF), ("C", apu.CF),
    )
    return "".join(n if v else n.lower() for n, v in flags)


class DebuggerWindow:
    def __init__(self, cpu: Cpu, bus: Bus, ppu: Ppu, debugger: Debugger) -> None:
        self._cpu = cpu
        self._bus = bus
        self._ppu = ppu
        self._debugger = debugger

        self.root = tk.Tk()
        self.root.title("PySNES Debugger")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._mem_region_val: str = "WRAM"
        self._mem_addr: int = 0
        self._bp_rendered: tuple[int, ...] = ()

        self._build_ui()
        self.refresh()
        self._poll()  # start the notify-queue polling loop

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = self.root
        root.configure(bg="#1e1e1e")

        # ── Top: registers (tabbed) + disassembly side by side ─────────
        top = ttk.Frame(root)
        top.pack(fill="both", expand=True, padx=6, pady=(6, 3))

        reg_notebook = ttk.Notebook(top)
        reg_notebook.pack(side="left", fill="both", expand=True, padx=(0, 4))

        for tab_name, attr in (("CPU", "_cpu_reg_text"),
                                ("APU", "_apu_reg_text"),
                                ("PPU", "_ppu_reg_text"),
                                ("Stack", "_stack_text")):
            frame = ttk.Frame(reg_notebook)
            reg_notebook.add(frame, text=tab_name)
            t = self._make_text(frame, width=44, height=12)
            t.pack(fill="both", expand=True)
            setattr(self, attr, t)

        self._disasm_text = self._make_text(top, width=62, height=12)
        self._disasm_text.pack(side="left", fill="both", expand=True)

        # ── Middle: memory view ────────────────────────────────────────
        mid = ttk.Frame(root)
        mid.pack(fill="both", expand=True, padx=6, pady=3)

        mem_ctrl = ttk.Frame(mid)
        mem_ctrl.pack(fill="x")

        ttk.Label(mem_ctrl, text="Region:").pack(side="left")
        self._region_buttons: dict[str, ttk.Radiobutton] = {}
        for r in _REGIONS:
            btn = ttk.Radiobutton(mem_ctrl, text=r, value=r,
                                  command=lambda region=r: self._on_mem_region_change(region))
            btn.pack(side="left", padx=2)
            if r == self._mem_region_val:
                btn.state(["selected"])
            self._region_buttons[r] = btn
        ttk.Label(mem_ctrl, text="  Addr:").pack(side="left")
        self._addr_entry = ttk.Entry(mem_ctrl, width=6)
        self._addr_entry.insert(0, "0000")
        self._addr_entry.pack(side="left")
        self._addr_entry.bind("<Return>", self._on_mem_addr_change)

        self._mem_text = self._make_text(mid, width=80, height=8)
        self._mem_text.pack(fill="both", expand=True, pady=(2, 0))

        # ── Bottom: breakpoints + controls ────────────────────────────
        bot = ttk.Frame(root)
        bot.pack(fill="both", padx=6, pady=(3, 6))

        bp_frame = ttk.LabelFrame(bot, text="Breakpoints")
        bp_frame.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self._bp_list = tk.Listbox(bp_frame, bg="#252526", fg="#d4d4d4",
                                   selectbackground="#094771", font=("Courier", 10),
                                   height=5, width=12)
        self._bp_list.pack(side="left", fill="both", expand=True)

        bp_btns = ttk.Frame(bp_frame)
        bp_btns.pack(side="left", padx=4)

        add_row = ttk.Frame(bp_btns)
        add_row.pack(fill="x", pady=2)
        self._bp_addr_entry = ttk.Entry(add_row, width=8)
        self._bp_addr_entry.pack(side="left")
        self._bp_addr_entry.bind("<Return>", lambda _e: self._cmd_add_bp())
        ttk.Button(add_row, text="Add", command=self._cmd_add_bp).pack(side="left", padx=(2, 0))

        ttk.Button(bp_btns, text="Break at PC",
                   command=self._cmd_toggle_bp_at_pc).pack(fill="x", pady=2)
        ttk.Button(bp_btns, text="Remove selected",
                   command=self._cmd_remove_bp).pack(fill="x", pady=2)

        ctrl = ttk.LabelFrame(bot, text="Controls")
        ctrl.pack(side="left", fill="y")
        ttk.Button(ctrl, text="Step (N)",     command=self._cmd_step).pack(fill="x", pady=2, padx=6)
        ttk.Button(ctrl, text="Continue (C)", command=self._cmd_continue).pack(fill="x", pady=2, padx=6)
        ttk.Button(ctrl, text="Pause",        command=self._cmd_pause).pack(fill="x", pady=2, padx=6)
        ttk.Button(ctrl, text="Reset",        command=self._cmd_reset).pack(fill="x", pady=2, padx=6)

        # ── Status bar ────────────────────────────────────────────────
        self._status_label = ttk.Label(root, text="Running", anchor="w")
        self._status_label.pack(fill="x", padx=6, pady=(0, 4))

    def _make_text(self, parent, **kwargs) -> tk.Text:
        t = tk.Text(parent, bg="#1e1e1e", fg="#d4d4d4",
                    insertbackground="#d4d4d4",
                    font=("Courier", 10), state="disabled",
                    relief="flat", borderwidth=1, **kwargs)
        t.tag_configure("pc",      foreground="#569cd6", background="#094771")
        t.tag_configure("bp",      foreground="#f44747")
        t.tag_configure("history", foreground="#808080")
        return t

    # ------------------------------------------------------------------
    # Polling loop (Tkinter thread only) — checks emulator → window queue
    # ------------------------------------------------------------------

    def _poll(self) -> None:
        """Called every 100 ms in the Tkinter thread to process refresh signals."""
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

        status = "PAUSED" if paused else "Running"
        self._status_label.config(text=status)
        self.root.title(f"PySNES Debugger — {status}")

        if paused:
            self._refresh_cpu_tab(cpu)
            self._refresh_apu_tab(self._debugger._pysnes.apu)
            self._refresh_ppu_tab(self._ppu)
            self._refresh_stack_tab(cpu)
            self._refresh_disassembly(cpu)
            self._refresh_memory()
        self._refresh_breakpoints()

    # ── CPU tab ────────────────────────────────────────────────────────

    def _refresh_cpu_tab(self, cpu) -> None:
        p = _cpu_flags_str(cpu)
        st = cpu.status
        mc = self._debugger._scheduler.master_clock
        text = (
            f" A:{cpu.A.w:04X}  X:{cpu.X.w:04X}  Y:{cpu.Y.w:04X}  S:{cpu.S.w:04X}\n"
            f" D:{cpu.D.w:04X}  DB:{cpu.DB.l:02X}  PC:{cpu.PC.d:06X}\n"
            f" P:{p}  EF:{int(cpu.EF)}\n"
            f"\n"
            f" NMI en:{int(st.nmi_enable)}"
            f"  IRQ en:{int(st.irq_enable)}\n"
            f" AutoJoy:{int(st.auto_joypad_read_enable)}"
            f"  FastROM:{int(st.fast_rom)}\n"
            f" WAI:{int(cpu.wai)}  STP:{int(cpu.stp)}\n"
            f"\n"
            f" Cycles:{cpu.cycles}  MC:{mc}\n"
        )
        self._set_text(self._cpu_reg_text, text)

    # ── APU tab ────────────────────────────────────────────────────────

    def _refresh_apu_tab(self, apu) -> None:
        flags = _apu_flags_str(apu)
        t0, t1, t2 = apu.timers[0], apu.timers[1], apu.timers[2]
        pr = apu.ports_r
        pw = apu.ports_w
        text = (
            f" PC:{apu.PC:04X}  A:{apu.A:02X}  X:{apu.X:02X}"
            f"  Y:{apu.Y:02X}  S:{apu.S:02X}\n"
            f" PSW:{flags}\n"
            f"\n"
            f" T0: en={int(t0.enable)} tgt={t0.target:02X}"
            f" cnt={t0.stage2:02X}\n"
            f" T1: en={int(t1.enable)} tgt={t1.target:02X}"
            f" cnt={t1.stage2:02X}\n"
            f" T2: en={int(t2.enable)} tgt={t2.target:02X}"
            f" cnt={t2.stage2:02X}\n"
            f"\n"
            f" ports_r: {pr[0]:02X} {pr[1]:02X} {pr[2]:02X} {pr[3]:02X}\n"
            f" ports_w: {pw[0]:02X} {pw[1]:02X} {pw[2]:02X} {pw[3]:02X}\n"
        )
        self._set_text(self._apu_reg_text, text)

    # ── PPU tab ────────────────────────────────────────────────────────

    def _refresh_ppu_tab(self, ppu) -> None:
        vram_addr = (ppu.vmaddh << 8) | ppu.vmaddl
        b1, b2, b3, b4 = ppu.bg1, ppu.bg2, ppu.bg3, ppu.bg4
        text = (
            f" Mode:{ppu._bgmode}  BG3Hi:{int(ppu._bgpriority)}"
            f"  Bright:{ppu.display_brightness:02X}"
            f"  Dis:{int(ppu.display_disable)}\n"
            f" VRAM:{vram_addr:04X}"
            f"  incr:{ppu.vmain_addr_increment_amount}"
            f"  mode:{ppu.vmain_addr_increment_mode}\n"
            f"\n"
            f"     scr    td    hofs  vofs\n"
            f" BG1:{b1.screen_addr:04X}  {b1.tiledata_addr:04X}"
            f"  {b1.hoffset:04X}  {b1.voffset:04X}\n"
            f" BG2:{b2.screen_addr:04X}  {b2.tiledata_addr:04X}"
            f"  {b2.hoffset:04X}  {b2.voffset:04X}\n"
            f" BG3:{b3.screen_addr:04X}  {b3.tiledata_addr:04X}"
            f"  {b3.hoffset:04X}  {b3.voffset:04X}\n"
            f" BG4:{b4.screen_addr:04X}  {b4.tiledata_addr:04X}"
            f"  {b4.hoffset:04X}  {b4.voffset:04X}\n"
            f"\n"
            f" OAM addr:{ppu._oamadd:03X}"
            f"  td:{ppu.oam_tiledata_address:04X}"
            f"  size:{ppu.oam_base_size}\n"
            f" H:{ppu.h_counter:03d}  V:{ppu.v_counter:03d}"
            f"  Frame:{ppu.frames}\n"
        )
        self._set_text(self._ppu_reg_text, text)

    # ── Stack tab ──────────────────────────────────────────────────────

    def _refresh_stack_tab(self, cpu) -> None:
        # Standard 65816 stack: push writes at S then decrements, so the
        # most-recently-pushed (next-to-pop) byte lives at S+1. Show 16
        # entries from S+1 going up toward higher addresses.
        s = cpu.S.w
        self._stack_text.configure(state="normal")
        self._stack_text.delete("1.0", "end")
        self._stack_text.insert("end", f" S = {s:04X}\n\n")
        for i in range(1, 17):
            addr = (s + i) & 0xFFFF
            byte = self._read_bank0(addr)
            prefix = "► " if i == 1 else "  "
            tag = "pc" if i == 1 else ""
            self._stack_text.insert("end", f"{prefix}{addr:04X}: {byte:02X}\n", tag)
        self._stack_text.configure(state="disabled")

    def _read_bank0(self, addr: int) -> int:
        addr &= 0xFFFF
        if addr < 0x2000:
            return self._bus.low_ram[addr]
        return self._bus.high_ram[addr - 0x2000]

    # ── Disassembly ────────────────────────────────────────────────────

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

    # ── Memory view ────────────────────────────────────────────────────

    def _refresh_memory(self) -> None:
        region = self._mem_region_val
        base = self._mem_addr
        data = self._read_memory(region, base, _HEX_COLS * 8)

        lines = []
        for row in range(0, len(data), _HEX_COLS):
            chunk = data[row:row + _HEX_COLS]
            hex_part = " ".join(f"{b:02X}" for b in chunk)
            ascii_part = "".join(chr(b) if 0x20 <= b < 0x7F else "." for b in chunk)
            lines.append(f"{region}:{base + row:06X}  {hex_part:<{_HEX_COLS * 3}}  {ascii_part}")

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
        elif region == "ROM":
            data = self._bus.rom.rom
            end = min(base + length, len(data))
            return bytes(data[base:end])
        return b"\x00" * length

    # ── Breakpoints ────────────────────────────────────────────────────

    def _refresh_breakpoints(self) -> None:
        bps = tuple(sorted(self._debugger._breakpoints))
        if bps == self._bp_rendered:
            return  # avoid clobbering the user's selection on the 100ms poll
        self._bp_rendered = bps
        self._bp_list.delete(0, "end")
        for addr in bps:
            self._bp_list.insert("end", f"{addr:06X}")

    # ── Helpers ────────────────────────────────────────────────────────

    def _set_text(self, widget: tk.Text, content: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", content)
        widget.configure(state="disabled")

    # ------------------------------------------------------------------
    # Event handlers / button commands
    # ------------------------------------------------------------------

    def _on_mem_region_change(self, region: str) -> None:
        self._mem_region_val = region
        self._mem_addr = 0
        self._addr_entry.delete(0, "end")
        self._addr_entry.insert(0, "0000")
        self._refresh_memory()

    def _on_mem_addr_change(self, _event=None) -> None:
        try:
            self._mem_addr = int(self._addr_entry.get(), 16)
        except ValueError:
            self._mem_addr = 0
            self._addr_entry.delete(0, "end")
            self._addr_entry.insert(0, "0000")
        self._refresh_memory()

    def _cmd_add_bp(self) -> None:
        raw = self._bp_addr_entry.get().strip()
        try:
            addr = int(raw, 16)
        except ValueError:
            return
        self._bp_addr_entry.delete(0, "end")
        self._debugger._cmd_queue.put(("toggle_bp", addr))

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
        done = threading.Event()
        self._debugger._cmd_queue.put(("step", done))
        done.wait()   # blocks Tkinter thread until main thread finishes the step
        self.refresh()

    def _cmd_continue(self) -> None:
        self._debugger._cmd_queue.put(("continue",))
        self._status_label.config(text="Running")

    def _cmd_pause(self) -> None:
        self._debugger._cmd_queue.put(("pause",))

    def _cmd_reset(self) -> None:
        self._debugger._cmd_queue.put(("reset",))

    def _on_close(self) -> None:
        self.root.quit()  # stops mainloop; destroy() is called in the daemon thread
