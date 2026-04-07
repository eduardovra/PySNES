# PySNES Debugger UI Plan

## Goal

Build a separate debugger window for the SNES emulator with:
- CPU registers display
- Disassembly view (history + forward look)
- Memory view (WRAM, VRAM, CGRAM)
- Breakpoint support (pause at address, step one instruction)

Requirement: zero overhead on the emulator main loop when the debugger window is closed.

---

## Options Considered

### Option A: Tkinter ✅ CHOSEN

**Available?** Confirmed: `uv run --python pypy@3.10 python3 -c "import tkinter"` works.
**New deps?** None — Tkinter is stdlib.

Tkinter runs in a **daemon thread** with its own `mainloop()`. The emulator main loop stays on the main thread (SDL2 requires it). A thread-safe snapshot dict + `queue.Queue` bridges the two.

**Overhead:** zero on hot path. Snapshot copy after each frame costs ~microseconds (just attribute reads into a dict). Tkinter thread not started until F12 is pressed.

**Widgets available:** `ttk.Frame`, `ttk.Label` (registers), `tkinter.Text` (disassembly + memory hex), `ttk.Treeview` (breakpoint list), `ttk.Entry` (address input), `ttk.Button` (Step/Continue/Break).

### Option B: Web browser (http.server built-in)

- HTTP server in daemon thread, emulator pushes JSON snapshots, browser polls at 10 Hz.
- Con: Requires opening a browser tab manually; HTML hex views are clunkier than Tkinter widgets.

### Option C: SDL2 second window with SDL_ttf

- Con: `SDL_ttf` is not in deps; all text layout, hex alignment, and event handling for a second SDL_Window are manual — high implementation cost.

### Option D: Dear ImGui (already in pyproject.toml)

- Specifically designed for game debugger UIs.
- Con: CLAUDE.md explicitly says "Don't reintroduce OpenGL/ImGui".

---

## Design

### Threading Model

```
Main thread (SDL2 + emulator):          Tkinter thread (daemon):
  scheduler.run_to(frame_end)             root.mainloop()
  → push_snapshot()  ──lock──────────→  _on_refresh()  (root.after(100, ...))
  ← drain_commands() ←─queue──────────  button click handlers
```

**`push_snapshot()`** — called once per frame, builds a shallow dict of CPU/PPU state.

**`drain_commands()`** — called each main loop iteration, processes commands from the Tkinter thread (toggle breakpoint, step, continue, pause).

### Breakpoints

Hook `cpu._step` using the same pattern as `start_trace()` in `pysnes.py:109-117`. Swap the wrapper in/out based on whether breakpoints are active:

```python
def _install_hooks(self):
    if self._breakpoints or self._step_mode:
        self.cpu._step = self._hooked_step
    else:
        self.cpu._step = self._original_step
```

Breakpoints stored in a `set` of 24-bit PC integers. **Zero overhead when empty** — raw `_step` is installed, no wrapper runs.

### Step-One-Instruction

```python
def step_one_instruction(self):
    target = self._instr_count + 1
    while self._instr_count < target:
        self.scheduler.run_one()   # already exists in scheduler.py:44
```

`scheduler.run_one()` fires the single earliest event. The hook increments `_instr_count` when a CPU step completes. PPU/APU events between CPU instructions fire correctly.

### Memory View (Safe Reads)

**Never call `bus.read()`** from the debugger — I/O registers at `0x2000–0x5FFF` have side effects. Read raw bytearrays directly:

| Region | Safe access |
|--------|-------------|
| WRAM 0x000–0x1FFF | `bus.low_ram[addr]` |
| WRAM 0x2000–0x7FFF | `bus.high_ram[addr - 0x2000]` |
| WRAM 0x8000–0xFFFF | `bus.extended_ram[addr - 0x8000]` |
| VRAM | `ppu.vram[addr]` |
| CGRAM | `ppu.cgram[addr]` |
| I/O 0x2000–0x5FFF | Display as `??` |

### Disassembly View

- **Backward (history)**: `cpu.trace_log` — last 10 disassembled instruction strings already stored.
- **Forward (upcoming)**: call `cpu.disassembler.disassemble(pc)` in a loop. Advance PC by opcode length using a lookup table (65816 lengths are deterministic given M/X flags).

### Window Layout

```
┌─ PySNES Debugger ──────────────────────────────────────────────┐
│ ┌─ CPU Registers ────────────────────────────────────────────┐ │
│ │  A: 0000   X: 0001   Y: 0000   S: 01FF   D: 0000          │ │
│ │  DB: 00    PC: 008078   P: NvMxdIzC   EF: 1               │ │
│ │  MC: 12345678                                              │ │
│ └────────────────────────────────────────────────────────────┘ │
│ ┌─ Disassembly ──────────────────────────────────────────────┐ │
│ │  008073 lda #$00                                           │ │
│ │  008075 sta $2100                                          │ │
│ │► 008078 jsr $8082                          ← current PC   │ │
│ │  00807B nop                                               │ │
│ └────────────────────────────────────────────────────────────┘ │
│ ┌─ Memory ──────┐ ┌─ Breakpoints ───────┐ ┌─ Controls ──────┐ │
│ │ WRAM▼ 7E:0000 │ │ 008078              │ │ [Step]          │ │
│ │ 00 00 00 00…  │ │ 00C0FF              │ │ [Continue]      │ │
│ │ 00 00 00 00…  │ │                     │ │ [Break at PC]   │ │
│ │ addr: [0000]  │ │ [Remove]            │ │ [Pause]         │ │
│ └───────────────┘ └─────────────────────┘ └─────────────────┘ │
└────────────────────────────────────────────────────────────────┘
```

### SDL2 Key Bindings (extend `process_inputs()`)

| Key | Action |
|-----|--------|
| F12 | Open debugger window |
| SPACE | Pause/resume (existing) |
| F10 | Memory dump (existing) |
| F11 | Screenshot (existing) |

All debug interactions (step, breakpoints, memory navigation) happen in the Tkinter window.

---

## Performance Impact

| Mode | Overhead |
|------|----------|
| Window closed | **Zero** — Tkinter thread not started |
| Window open, running | ~microseconds/frame for snapshot dict build |
| Breakpoints active | One `set.__contains__` per CPU instruction (~50 ns, ~3%) |
| Paused / stepping | Emulator halted — irrelevant |

---

## Files to Create / Modify

### New: `pysnes/debugger.py`

`Debugger` class:
- `attach(self)` — wraps `cpu._step` (mirrors `start_trace()` pattern in `pysnes.py:109`)
- `_install_hooks(self)` — swaps wrapper in/out based on breakpoint state
- `_hooked_step(self)` — checks breakpoints, step-mode, increments `_instr_count`
- `toggle_breakpoint(addr)`, `step_one_instruction(self)`
- `push_snapshot(self)` — builds snapshot dict from `cpu`, `ppu`, `bus`, `scheduler`
- `drain_commands(self)` — processes command queue from Tkinter thread
- `_disassemble_forward(pc, count)` — loops `cpu.disassembler.disassemble()`
- `open_window(self)` — starts Tkinter daemon thread

### New: `pysnes/debugger_window.py`

`DebuggerWindow` Tkinter class:
- Widget creation and layout (registers, disassembly, memory, breakpoints, buttons)
- `_on_refresh(self)` — `root.after(100, ...)` callback: reads snapshot, updates widgets
- Button/click handlers that push to command queue

### Modified: `pysnes/pysnes.py`

1. Import and instantiate `Debugger` after `cpu.attach(bus)` (~line 41)
2. Call `debugger.push_snapshot()` once per frame after `scheduler.run_to()`
3. Call `debugger.drain_commands()` each main loop iteration
4. Add F12 key handler in `process_inputs()` to call `debugger.open_window()`

### Unchanged: `cpu.py`, `scheduler.py`, `bus.py`, `disassembler.py`

---

## Verification

1. Run emulator → FPS unchanged (no debugger overhead).
2. Press F12 → Tkinter window opens, registers update at ~10 Hz.
3. Click "Pause" → game halts, Tkinter shows "PAUSED".
4. Click "Step" → PC advances by exactly one instruction.
5. Click "Break at PC" → breakpoint added; click "Continue" → game pauses when PC is revisited.
6. Select VRAM in memory dropdown → hex values match `vram_dump.bin`.
7. Close Tkinter window → daemon thread exits; game continues unaffected.
