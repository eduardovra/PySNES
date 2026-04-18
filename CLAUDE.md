# PySNES - Claude Code Context

## Project Goal

A SNES emulator written in Python, targeting real-time emulation speed while keeping elegant Python syntax. The performance strategy is Cython (pure Python mode) compiled with PyPy 3.10, or a combination of both.

The codebase is in active development. CPU and SPC700 instruction tests pass against the SingleStepTests suite. Super Mario World boots past the SPC700 IPL handshake and second-stage audio upload and renders the animated title screen (branch `apu-sync-timing-fixes`).

## Build & Run

### Prerequisites
- PyPy 3.10 (from tarball, NOT snap — snap version had window display issues)
- uv (package manager)
- SDL2 system library (`libsdl2-dev`)

### Commands
```bash
# Install dependencies
uv sync --python pypy@3.10

# Build (Cython compile all .py files into a .so)
make build          # uses PyPy 3.10 by default

# Run
uv run --python pypy3.10 pysnes roms/game.sfc                     # script entry point (recommended)
uv run --python pypy3.10 pysnes roms/game.sfc --trace roms/game-trace.log  # with CPU trace
uv run --python pypy3.10 -m pysnes.pysnes roms/game.sfc           # equivalent module form

# Clean build artifacts
make clean

# Profile
make profile        # runs with cProfile
```

## Debug Instrumentation

The emulator has built-in debug tools controllable via Unix signals (no GUI required):

```bash
# Run emulator — PID is printed to stdout on startup
uv run --python pypy@3.10 -m pysnes.pysnes roms/game.sfc &

# Trigger screenshot → saves screenshot.bmp (Claude can read as image)
kill -USR1 <pid>

# Trigger memory dumps → saves vram_dump.bin, cgram_dump.bin, wram_dump.bin
kill -USR2 <pid>
```

**Headless mode (for Claude and automation):** Always run emulators headless — never launch a windowed emulator from a Claude tool call.
- PySNES: set `PYSNES_HEADLESS=1`. Suppresses the SDL2 window and avoids the glibc malloc/ctypes crashes seen in windowed pure-Python runs.
- Mesen2: use `--testrunner <lua-script> <rom>` (NOT `--headless --lua`, that still opens a window). The Lua script calls `emu.stop()` / `emu.exit()` when done. Artifacts get written to paths the Lua passes via env vars (e.g. `MESEN_OUTPUT_BIN`).
- Any other emulator: use its equivalent headless/offscreen flag. If one doesn't exist, stop and ask rather than launching with a window.

Use signal-driven screenshots, direct framebuffer reads, or Lua-dumped .bin artifacts for snapshots. Interactive launches are the user's job, not Claude's.

```bash
PYSNES_HEADLESS=1 uv run --python pypy@3.10 -m pysnes.pysnes roms/game.sfc &

# Mesen2 headless (writes a screenshot at MESEN_OUTPUT_BIN):
MESEN_FRAMES=400 MESEN_OUTPUT_BIN=/tmp/mesen.bin \
  submodules/Mesen2/bin/linux-x64/Release/linux-x64/publish/Mesen \
  --testrunner scripts/mesen_screenshot.lua "roms/Super Mario World (U) [!].smc"
```

- **F11** / **SIGUSR1** → save `screenshot.bmp` (SDL2 framebuffer snapshot)
- **F10** / **SIGUSR2** → save `vram_dump.bin`, `cgram_dump.bin`, `wram_dump.bin`
- **SPACE** → pause/resume
- FPS is shown in the window title bar

### CPU Trace Comparison
On startup, `pysnes.py` opens `cpu_trace.log` and compares CPU execution against the bsnes reference trace `roms/Super Mario World (U) [!]-trace.log`. The first divergence is printed to stdout. Limited to first 100k CPU instructions.

### Reference Assets (`roms/`)
- `Super Mario World (U) [!]-trace.log` — 1.25M line bsnes CPU+APU trace from reset vector
- `Super Mario World (U) [!]-vram.bin` / `-cgram.bin` / `-wram.bin` / `-oam.bin` — bsnes memory snapshots at an unknown execution point (not directly comparable without matching frame count)

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
pysnes/pysnes.py               Main emulator class (PySNES) + entry point
pysnes/bus/bus.py              Memory bus - routes reads/writes to all peripherals
pysnes/rom.py                  ROM parser (LoROM/HiROM, header, vectors)
pysnes/controller/controller.py  SNES controller input (keyboard mapping)
pysnes/video/video.py          Video renderer wrapper
pysnes/video/video_sdl2.py     SDL2 2D rendering engine (hardware-accelerated)
pysnes/scheduler/scheduler.py  Event-driven master-clock scheduler
pysnes/cpu/cpu.py              WDC65816 CPU core
pysnes/cpu/dma.py              DMA/HDMA engine
pysnes/cpu/wdc65816/           65816 instruction set, opcodes, addressing modes, disassembler
pysnes/apu/apu.py              SPC700 audio CPU core + APU port I/O
pysnes/apu/spc700/             SPC700 instructions, opcodes, addressing modes
pysnes/ppu/ppu.py              Picture Processing Unit (main graphics pipeline)
pysnes/ppu/data_structures.py  Background and sprite data structures
pysnes/debugger/debugger.py    Debugger + live UI window
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
- **OAM Y wrapping**: X sign-extension done; Y still uses the `y==240 → hide` heuristic, which is close but not exactly hardware-accurate.
- **HiROM**: LoROM is the primary target; HiROM may have mapping issues
- **Window effects**: masking/windowing not implemented
- **Color math**: SNES special effects processing not implemented

### Not Implemented
- Audio output (DSP registers are accessed but no actual sound synthesis)
- SRAM / save states
- PPU Mode 0-7 full support (only basic modes work)
- Overscan mode (partially recognized)

## PPU Test Status

### Passing (ppu_improvements branch)
| Test | ROM | Notes |
|------|-----|-------|
| bg1_2bpp | BGMAP/8x8/2BPP/8x8BG1Map2BPP32x328PAL | 5 frames |
| bg2_2bpp | BGMAP/8x8/2BPP/8x8BG2Map2BPP32x328PAL | 5 frames |
| bg3_2bpp | BGMAP/8x8/2BPP/8x8BG3Map2BPP32x328PAL | 5 frames |
| bg4_2bpp | BGMAP/8x8/2BPP/8x8BG4Map2BPP32x328PAL | 5 frames |
| bg_4bpp | BGMAP/8x8/4BPP/8x8BGMap4BPP32x328PAL | 5 frames |
| tile_flip | BGMAP/8x8/8BPP/TileFlip | 20 frames (FadeIN finishes at frame 15) |
| window_hdma | Window/WindowHDMA | 3 frames (brightness=3 into FadeIN) |
| mosaic_mode3 | Mosaic/Mode3 | 2 frames (brightness=2 into FadeIN) |
| scroll tests | synthetic (no ROM) | 18 unit tests in test_ppu_scroll.py |

### Failing / Excluded
| Test | Status | Root Cause |
|------|--------|------------|
| bg_8bpp | removed | ROM scrolls 1px/frame — any timing difference = totally different image |
| mode7_rotzoom | NotImplementedError | Mode 7 matrix transform not implemented |

### Key PPU Fixes (this branch)
- `tiledata_addr` formula: `<< 12` → `<< 13` (8KB steps, not 4KB) in `bg12nba_set` / `bg34nba_set`
- Scanline offset: `orgy = scry - 1` correctly writes scanline N to row N-1 of framebuffer
- Bus registers: implemented missing BG scroll, BG tilemap/tiledata address registers
- HDMA engine: `hdma_init()` per-frame, `hdma_scanline()` per H-blank; render-before-HDMA ordering
- HDMA bit 7 semantics: 0 = do-not-repeat (same data per scanline), 1 = do-repeat (fresh data per scanline)
- Window masking: W1 enable/invert for BG1-BG4 via W12SEL/W34SEL/TMW applied per-pixel

## Integration Testing (Mesen oracle)

Mesen 2 is used as a reference oracle for integration tests.
It lives as a git submodule at `submodules/Mesen2/`. Build it with `USE_GCC=true make -C submodules/Mesen2` (requires .NET 8 SDK, SDL2, and gcc with C++17 support). The default `mesen_bin` path in `settings.py` points to the submodule build output. Override with `MESEN_BIN` env var or `"mesen_bin"` in `settings.json` if needed.

**First-run setup:** Before running integration tests, open Mesen2 once and enable Lua script permissions:
1. Open the **Script Window** (via the debugger menu)
2. Go to **Settings > Script Window > Restrictions**
3. Enable **"Allow access to I/O and OS functions"**
4. Enable **"Allow network access"**

Without these, the Lua oracle scripts cannot use file I/O or open sockets to communicate with PySNES.

```bash
# Tier 1 — find first diverging frame (CPU/SPC registers + WRAM CRC32):
uv run --python pypy@3.10 pytest pysnes/test_integration.py::test_frame_divergence -v -s

# Tier 2 — find exact diverging CPU instruction:
uv run --python pypy@3.10 pytest pysnes/test_integration.py::test_instruction_divergence -v -s

# Custom ROM / frame count / instruction count:
SNES_ROM="roms/mygame.sfc" uv run --python pypy@3.10 pytest pysnes/test_integration.py -v -s --frames 120 --instructions 200000

# Skip integration tests in normal suite:
uv run --python pypy@3.10 pytest pysnes/ -m "not integration"
```

- Mesen Lua scripts are in `scripts/mesen_oracle.lua` (Tier 1) and `scripts/mesen_trace.lua` (Tier 2)
- Port is passed to Lua via `MESEN_PORT` env var; frame/instruction count via `MESEN_FRAMES`/`MESEN_INSTRUCTIONS`
- `PYSNES_HEADLESS=1` suppresses SDL2 window during PySNES fixture runs
- Alternative oracle: BizHawk; Lua API reference at https://tasvideos.org/Bizhawk/LuaFunctions

## Testing

```bash
# All tests
uv run --python pypy@3.10 pytest pysnes/

# CPU tests (TomHarte's ProcessorTests / SingleStepTests 65816)
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py

# SPC700 instruction tests (SingleStepTests spc700)
uv run --python pypy@3.10 pytest pysnes/apu/test_spc700.py

# APU / timer / interrupt / scheduler unit tests
uv run --python pypy@3.10 pytest pysnes/apu/test_apu.py pysnes/apu/test_timers.py pysnes/bus/test_interrupts.py pysnes/scheduler/test_scheduler.py

# PPU scroll unit tests (synthetic, no ROM needed):
uv run --python pypy@3.10 pytest pysnes/ppu/test_ppu_scroll.py -v

# PPU screenshot regression tests (requires reference PNGs in tests/ppu_references/)
uv run --python pypy@3.10 pytest pysnes/ppu/test_ppu.py -m ppu
# Generate/update reference PNGs from Mesen (run once, then commit the PNGs):
uv run --python pypy@3.10 pytest pysnes/ppu/test_ppu.py -m ppu --update-refs

# Filter options (apply to test_cpu.py and test_spc700.py)
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py --opcode ea           # single opcode
uv run --python pypy@3.10 pytest pysnes/apu/test_spc700.py --opcode d0        # single opcode
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py --max-per-opcode 0    # all cases (unlimited)
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py --max-per-opcode 10   # 10 cases per opcode
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py --mode e              # emulation mode only (65816)
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py --mode n              # native mode only (65816)
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py --opcode ea --mode n  # combine filters
```

- 65816 test data is at `submodules/65816/v1/` (files named `{opcode}.{e|n}.json`)
- SPC700 test data is at `submodules/SingleStepTests_spc700/v1/`
- Tests verify: initial state → execute instruction → final registers, RAM, and memory access sequence
- CPU (`pysnes/cpu/cpu.py`) and APU (`pysnes/apu/apu.py`) are the tested implementations
- `pytest-xdist` is available for parallel execution. Test params are `(file, index)` refs, not full dicts; collection is cached to `.pytest_cache/ss_{cpu,spc700}_<key>.pickle` under an `fcntl.flock` so workers after the first just read the pickle.
- **Recommended invocation: `-n auto --dist=loadgroup`** for `test_cpu.py` and `test_spc700.py`. Each param carries an `xdist_group(file_path)` marker, so `--dist=loadgroup` pins all cases from one JSON file to a single worker; a single-slot file cache in `_load_case` then parses that JSON only once per worker. Delete `.pytest_cache/ss_*.pickle` if you suspect stale cache (it's keyed on filter args + JSON mtimes and should self-invalidate).
- Cycle count is checked against `len(test_case["cycles"])` for every CPU opcode. The 65816 harness does not verify per-cycle bus-status bits (VDA/VPA/VPB/MLB/M/X/E); only R/W.

## Performance Notes
- Cython compiles all Python to C for speed
- SDL2 rendering is 10-20x faster than the previous OpenGL approach
- ImGui was dropped — it was killing performance (replaced by Rich TUI)
- Current FPS target: ~60 Hz; last measured around 21-22 FPS with SDL2
- `Profile.prof` exists in root — can be analyzed with pstats/snakeviz
- `make profile` runs cProfile
- **Cython HTML annotation reports**: after `make build`, each `.py` file gets a `.html` counterpart (e.g. `ppu.html`). Open it in a browser — yellow-highlighted lines are slow paths that still go through the Python interpreter. Darker yellow = more interpreter calls. These are the primary indicator of Cython optimization bottlenecks: typed variables, `@cython.cfunc`, and avoiding Python builtins (`zip`, `reversed`, `**`) on hot paths eliminate the yellow.

### Benchmarking Rule
**Before and after every performance change, measure and record results.** Use the relevant benchmark for the component being optimized:
- **CPU throughput**: `uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py --opcode ea -s` — look for "instr/sec" in output
- **APU throughput**: `uv run --python pypy@3.10 pytest pysnes/apu/test_spc700.py --opcode 00 -s` — look for "instr/sec"
- **FPS (full emulator)**: run with a ROM and read the FPS from the window title bar
- **PPU rendering throughput**: `time uv run --python pypy@3.10 pytest pysnes/ppu/test_ppu.py -m ppu` — wall-clock time dominated by PPU rendering; fully automated and reproducible

Document results in the PR/commit message as: `before: X instr/sec → after: Y instr/sec (+Z%)` or `before: Xs → after: Ys` for PPU.

## Git Workflow
- **Always create a new branch off `main` before making changes.** Check `git branch` first; if already on a feature branch (not `main`), continue there. If on `main`, run `git checkout -b <descriptive-branch-name>` before editing any files.
- **Never rebase** unless explicitly instructed. Use `git merge` to integrate changes (e.g. `git merge origin/main` to resolve PR conflicts). Rebase rewrites history and requires force-push, which is destructive for shared branches.
- **Never force push** unless explicitly instructed. Always use plain `git push`.

## Key Design Decisions
- **Pure Python mode Cython**: No `.pyx` files — all `.py` files compiled by Cython. This allows running without a build step during development.
- **PyPy + Cython**: Can run either way — PyPy JIT or Cython-compiled CPython. Cython build is the primary path.
- **SDL2 over OpenGL/ImGui**: Switched for major performance gains. Don't reintroduce OpenGL/ImGui.
- **Automated testing**: We aim for every functionallity to be covered by automated tests. When there is a change to be made, the tests need to be created first to perfectly outline the end goal.
- **Scanline-based timing**: CPU runs until scanline budget, then PPU renders that scanline. This is not how real SNES hardware operates, but it's a compromise to improve performance in hopes for most games to work.

## ROM for Testing
- ROM files are in `roms/` directory (not committed to git)
- ROM path is passed as a positional CLI argument: `python -m pysnes.pysnes <rom>`
- Optional `--trace <ref>` flag enables CPU trace comparison against a reference log

## APU↔CPU Handshake Notes

Super Mario World boots to the animated title screen on branch `apu-sync-timing-fixes`. Three APU-related fixes live on that branch:

1. **Cycle-accurate APU sync on CPU port reads** — in `pysnes/bus/bus.py` the sync target is `scheduler.master_clock + (cpu.cycles - cpu.prev_cycles)` so the APU catches up to the actual bus-cycle time of the $2140–$2143 read, not the instruction start.
2. **Exact 21477272/1024000 MC↔APU-clock ratio** — integer 21 approximation accumulated ~60 MC drift over IPL boot; exact ratio eliminates it.
3. **SPC-side port writes no longer mirror into the CPU→SPC latch** — the four $F4/$2140-style I/O pairs are independent physical registers (one SPC-writes/CPU-reads, one CPU-writes/SPC-reads). An old mirror in `Apu._write` corrupted the CPU→SPC latch on every SPC write, so the N-SPC driver read back its own acknowledgement bytes instead of the CPU's handshake values and the second-stage upload deadlocked.

**cycles vs icycles** (reference):
- `icycles`: counts bus transactions for the current instruction (each read/write/idle = +1). What SingleStepTests verify.
- `cycles`: counts actual SNES master clock units elapsed (each bus cycle adds 6, 8, or 12 MC depending on memory region). What the scheduler uses.
