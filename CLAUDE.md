# PySNES - Claude Code Context

## Project Goal

A SNES emulator written in Python, targeting real-time emulation speed while keeping elegant Python syntax. The performance strategy is Cython (pure Python mode) compiled with PyPy 3.10, or a combination of both.

The codebase is in active development. CPU and SPC700 instruction tests pass against the SingleStepTests suite.

## Build & Run

### Prerequisites
- PyPy 3.10 (from tarball, NOT snap — snap version had window display issues)
- uv (package manager)
- SDL2 system library (`libsdl2-dev`)

### Commands
```bash
# Install dependencies
uv run --python pypy@3.10 pip install -r requirements.txt

# Build (Cython compile all .py files into a .so)
make build          # uses PyPy 3.10 by default

# Run
make run            # build + run
uv run --python pypy3.10 -m pysnes.pysnes   # without Cython build

# Clean build artifacts
make clean

# Profile
make profile        # runs with cProfile
```

### Build System Notes
- **Cython version is pinned to 3.1.1** — DO NOT upgrade to 3.1.2, it has a "multiple definitions of function" bug: https://stackoverflow.com/questions/79687815/cython-multiple-definitions-of-function
- **Python version must be ~3.10** — ImGui (now removed but still in pyproject.toml) didn't compile in 3.11 with PyPy
- All `.py` files in `pysnes/` are compiled into a single monolithic Cython `.so` extension
- `setup.py` compiles everything and links against SDL2
- `cythonize()` uses `cache=True` and `nthreads=cpu_count()` — only changed `.py` files are re-transpiled; Cython step is parallelised
- Generated `.c` and `.html` files sit alongside `.py` files but are git-ignored
- The C compilation step (setuptools) always recompiles all `.o` files due to a setuptools regression — this is a known limitation

## Architecture

```
pysnes/pysnes.py          Main emulator class (PySNES) + entry point
pysnes/bus.py             Memory bus - routes reads/writes to all peripherals
pysnes/rom.py             ROM parser (LoROM/HiROM, header, vectors)
pysnes/controller.py      SNES controller input (keyboard mapping)
pysnes/video.py           Video renderer wrapper
pysnes/video_sdl2.py      SDL2 2D rendering engine (hardware-accelerated)
pysnes/register_types.py  Register type definitions
pysnes/trace_matcher.py   CPU instruction trace verification tool
pysnes/cpu/v2/cpu.py      WDC65816 CPU core (v2 is active; v1 is legacy)
pysnes/cpu/v2/wdc65816/   65816 instruction set, opcodes, addressing modes, disassembler
pysnes/apu/apu_v2.py      SPC700 audio CPU core (v2 is active; apu.py is legacy)
pysnes/apu/spc700/        SPC700 instructions, opcodes, addressing modes
pysnes/ppu/ppu.py         Picture Processing Unit (~900 lines, main graphics pipeline)
pysnes/ppu/data_structures.py  Background and sprite data structures
```

### Main Loop (scanline-based)
1. For each of 262 scanlines per frame:
   - CPU executes instructions until scanline cycle budget is reached
   - PPU renders that scanline (backgrounds, sprites, palette)
   - APU ticks 3x per CPU scanline
2. When all scanlines done → render frame buffer via SDL2 → back to scanline 0

### Component Details
- **CPU**: WDC65816, 3.58 MHz, 16-bit with 6502 emulation mode. Full 256-opcode set, all addressing modes.
- **APU**: SPC700 @ 1.024 MHz. 3 timers, 4 I/O ports to main CPU, 64KB address space, embedded IPL ROM.
- **PPU**: 64KB VRAM, 512B CGRAM (256 colors), OAM sprites, 4 backgrounds (BG1-4), 256x256 pixel buffer.
- **Bus**: Routes 24-bit address space — LoROM mapping, RAM shadows, PPU/APU registers, DMA.
- **Video**: SDL2 hardware-accelerated 2D renderer. OpenGL and ImGui were removed for performance reasons.

## Implementation Status

### Fully Implemented
- WDC65816 CPU: all 256 opcodes, all addressing modes, flags, registers. Passes SingleStepTests (512 files, 1 case/opcode/mode by default; 6 pre-existing failures for opcodes 42/44/54 which are known broken)
- SPC700 APU: full instruction set, registers, memory, timers, I/O ports to CPU. Passes all 25,600 SingleStepTests cases at 100/opcode
- PPU basics: tilemap rendering, BG1-4, sprite composition, CGRAM palette
- Memory bus: address decoding, LoROM mapping, RAM regions, PPU/APU register access
- ROM loading: header parsing, vector extraction (RESET, NMI, IRQ, COP, ABORT)
- SDL2 video rendering
- Keyboard input (SNES controller mapping)
- Debug TUI: Rich-based live display (FPS, CPU registers, instruction trace) — toggle with F12, pause with SPACE

### Partially Implemented / Known TODOs
- **Mosaic effect**: stubbed (`if self.mosaic_enabled[bg.number - 1] and False:`)
- **PPU Mode 7**: M7A-M7Y matrix registers present but not functional
- **NMI/V-Blank**: basic implementation, timing edge cases likely
- **DMA/HDMA**: partial, timing accuracy unknown
- **OAM sprite wrapping**: has `TODO handle wrapping` comment in code
- **Backdrop color**: comment says it's incorrect — should only show when all layers above are transparent
- **HiROM**: LoROM is the primary target; HiROM may have mapping issues
- **Window effects**: masking/windowing not implemented
- **Color math**: SNES special effects processing not implemented

### Not Implemented
- Audio output (DSP registers are accessed but no actual sound synthesis)
- SRAM / save states
- PPU Mode 0-7 full support (only basic modes work)
- Overscan mode (partially recognized)

## Testing

```bash
# All tests
uv run --python pypy@3.10 pytest pysnes/

# CPU tests (TomHarte's ProcessorTests / SingleStepTests 65816)
uv run --python pypy@3.10 pytest pysnes/test_cpu.py

# SPC700 instruction tests (SingleStepTests spc700)
uv run --python pypy@3.10 pytest pysnes/test_spc700.py

# APU / timer / interrupt / scheduler unit tests
uv run --python pypy@3.10 pytest pysnes/apu/test_apu.py pysnes/test_timers.py pysnes/test_interrupts.py pysnes/test_scheduler.py

# Filter options (apply to test_cpu.py and test_spc700.py)
uv run --python pypy@3.10 pytest pysnes/test_cpu.py --opcode ea           # single opcode
uv run --python pypy@3.10 pytest pysnes/test_spc700.py --opcode d0        # single opcode
uv run --python pypy@3.10 pytest pysnes/test_cpu.py --max-per-opcode 0    # all cases (unlimited)
uv run --python pypy@3.10 pytest pysnes/test_cpu.py --max-per-opcode 10   # 10 cases per opcode
uv run --python pypy@3.10 pytest pysnes/test_cpu.py --mode e              # emulation mode only (65816)
uv run --python pypy@3.10 pytest pysnes/test_cpu.py --mode n              # native mode only (65816)
uv run --python pypy@3.10 pytest pysnes/test_cpu.py --opcode ea --mode n  # combine filters
```

- 65816 test data is at `submodules/65816/v1/` (files named `{opcode}.{e|n}.json`)
- SPC700 test data is at `submodules/SingleStepTests_spc700/v1/`
- Tests verify: initial state → execute instruction → final registers, RAM, and memory access sequence
- CPU v2 and APU v2 are the tested implementations
- `pytest-xdist` is available for parallel execution (memory is bounded — test params are `(file, index)` refs, not full dicts)
- **Do NOT use `-n auto` for `test_cpu.py`** — it spawns too many workers and crashes the machine. Use `-n 6` until CPU test worker memory footprint is reduced.
- Cycle count checking is enabled for opcodes in `CYCLE_CHECK_OPCODES` in `test_cpu.py` (currently: ea, 1a, 3a, 18, 38)

## Performance Notes
- Cython compiles all Python to C for speed
- SDL2 rendering is 10-20x faster than the previous OpenGL approach
- ImGui was dropped — it was killing performance (replaced by Rich TUI)
- Current FPS target: ~60 Hz; last measured around 21-22 FPS with SDL2
- `Profile.prof` exists in root — can be analyzed with pstats/snakeviz
- `make profile` runs cProfile

## Key Design Decisions
- **Pure Python mode Cython**: No `.pyx` files — all `.py` files compiled by Cython. This allows running without a build step during development.
- **PyPy + Cython**: Can run either way — PyPy JIT or Cython-compiled CPython. Cython build is the primary path.
- **SDL2 over OpenGL/ImGui**: Switched for major performance gains. Don't reintroduce OpenGL/ImGui.
- **v2 over v1**: CPU v2 and APU v2 are the active implementations. v1 directories are legacy — don't modify them.
- **Scanline-based timing**: CPU runs until scanline budget, then PPU renders that scanline. This is how real SNES hardware works.

## ROM for Testing
- ROM files are in `roms/` directory (not committed to git)
- `run_pysnes.py` has hardcoded ROM paths — update as needed for testing
- The `--load` flag in `run_pysnes.py` loads memory dumps from bsnes for rendering debug
