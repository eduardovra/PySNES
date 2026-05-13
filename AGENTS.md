# PySNES - Agents Context

## Project Goal

A SNES emulator written in Python, targeting real-time emulation speed while keeping elegant Python syntax. The performance strategy is Cython (pure Python mode) compiled with PyPy 3.10, or a combination of both.

The codebase is in active development. CPU and SPC700 instruction tests pass against the SingleStepTests suite. Super Mario World boots past the SPC700 IPL handshake and second-stage audio upload and renders the animated title screen.

## Build & Run

### Prerequisites
- PyPy 3.10 (from tarball, NOT snap — snap version had window display issues)
- uv (package manager)
- SDL2 system library (`libsdl2-dev`)

### Commands
```bash
# Install dependencies (interpreter is pinned in .python-version → pypy@3.10)
uv sync

# Build (Cython compile all .py files into a .so)
make build          # uses PyPy 3.10 by default

# Run
uv run pysnes roms/game.sfc                     # script entry point (recommended)
uv run pysnes roms/game.sfc --trace roms/game-trace.log  # with CPU trace
uv run -m pysnes.pysnes roms/game.sfc           # equivalent module form

# Clean build artifacts
make clean

# Profile
make profile        # runs with cProfile
```

## Debug Instrumentation

The emulator has built-in debug tools controllable via Unix signals (no GUI required):

```bash
# Run emulator — PID is printed to stdout on startup
uv run -m pysnes.pysnes roms/game.sfc &

# Trigger screenshot → saves screenshot.bmp (Claude can read as image)
kill -USR1 <pid>

# Trigger memory dumps → saves vram_dump.bin, cgram_dump.bin, wram_dump.bin
kill -USR2 <pid>
```

**Headless mode (for Claude and automation):** Always run emulators headless — never launch a windowed emulator from a Claude tool call.
- PySNES: pass `--headless` on the command line. Suppresses the SDL2 window and avoids the glibc malloc/ctypes crashes seen in windowed pure-Python runs.
- Mesen2: use `--testrunner <lua-script> <rom>` (NOT `--headless --lua`, that still opens a window). The Lua script calls `emu.stop()` / `emu.exit()` when done. Artifacts get written to paths the Lua passes via env vars (e.g. `MESEN_OUTPUT_BIN`).
- Any other emulator: use its equivalent headless/offscreen flag. If one doesn't exist, stop and ask rather than launching with a window.

Use signal-driven screenshots, direct framebuffer reads, or Lua-dumped .bin artifacts for snapshots. Interactive launches are the user's job, not Claude's.

```bash
uv run -m pysnes.pysnes --headless roms/game.sfc &

# Mesen2 headless (writes a screenshot at MESEN_OUTPUT_BIN):
MESEN_FRAMES=400 MESEN_OUTPUT_BIN=/tmp/mesen.bin \
  submodules/Mesen2/bin/linux-x64/Release/linux-x64/publish/Mesen \
  --testrunner scripts/mesen_screenshot.lua "roms/Super Mario World (U) [!].smc"
```

- **F11** / **SIGUSR1** → save `screenshot.bmp` (SDL2 framebuffer snapshot)
- **F10** / **SIGUSR2** → save `vram_dump.bin`, `cgram_dump.bin`, `wram_dump.bin`
- **F5** → save state to `<rom>.state` (next frame boundary)
- **F6** → load state from `<rom>.state` (next frame boundary; F9 was avoided because GNOME and several WMs grab it)
- **SPACE** → pause/resume
- FPS is shown in the window title bar

### Save states

Single slot per ROM at `<rom>.state`. The file has a JSON metadata header
(parseable on any Python build) followed by a pickle payload. Loads are
gated by a SHA-256 compatibility hash of the running Python build + state-
bearing source code; mismatches refuse to load with a clear error rather
than half-restore. ROM identity is checked too — a state from one ROM
won't load into another.

Inspect a state file's metadata without loading the payload:

```python
from pysnes.savestate import read_header
read_header("roms/Super Mario World (U) [!].state")
# → {"compat_hash": "...", "rom_title": "SUPER MARIOWORLD",
#    "saved_at": "2026-04-30T...", "python_impl": "pypy 7.3.19", ...}
```

### Driving the emulator programmatically

`pysnes.harness` wraps a headless PySNES instance for scripted control —
useful for diagnostic tools that want to drive the emulator past boot
without launching a window. Save states make this practical: play to the
broken state, F5, then load it from the harness.

```python
from pysnes.harness import Harness

ROM = "roms/Super Mario World (U) [!].smc"

# Load a curated checkpoint and trace what the game does for one frame
with Harness(ROM, load_state="roms/smw_welcome.state") as h:
    writes = []
    h.on_write_range(0x2121, 0x2122, lambda h, a, v:
        writes.append((h.scanline, a & 0xFFFF, v)))
    h.run_frames(1)
    for sl, addr, val in sorted(writes):
        print(f"sl={sl:3d} ${addr:04X} = {val:02X}")
```

Other Harness operations: `run_frames(n)`, `tap(buttons)`, `screenshot(path)`,
`cgram(start, end)`, `vram(start, len)`, `oam()`, `wram(addr, len)`,
`cpu_state()`, `ppu_state()`, `set_breakpoint(addr) + run_until_break()`,
`save_state(path)`, `load_state(path)`.

There's also an NDJSON RPC variant:

```bash
uv run python -m pysnes.harness.cli --rom "roms/Super Mario World (U) [!].smc"
# stdin:  {"method": "run_frames", "args": {"n": 60}}
# stdout: {"ok": true, "result": {"frame": 60, ...}}
```

### CPU Trace Comparison
On startup, `pysnes.py` opens `cpu_trace.log` and compares CPU execution against the bsnes reference trace `roms/Super Mario World (U) [!]-trace.log`. The first divergence is printed to stdout. Limited to first 100k CPU instructions.

### Reference Assets (`roms/`)
- `Super Mario World (U) [!]-trace.log` — 1.25M line bsnes CPU+APU trace from reset vector
- `Super Mario World (U) [!]-vram.bin` / `-cgram.bin` / `-wram.bin` / `-oam.bin` — bsnes memory snapshots at an unknown execution point (not directly comparable without matching frame count)

### Build System Notes
- **Cython compilation is on hold.** PyPy alone is ~20× faster than CPython+Cython for this codebase as it currently stands, so the project runs from pure-Python source under PyPy. The `make build_pysnes` target and Cython decorators in the source still work, but you do not need to run `make build_pysnes` to develop or test — pure-Python source under PyPy is the supported path. If `*.so` files exist (left over from a previous build), Python imports them in preference to the `.py` source; `find pysnes -name "*.so" -delete` to fall back to the `.py` files.
- **Cython version is pinned to 3.1.1** — DO NOT upgrade to 3.1.2, it has a "multiple definitions of function" bug: https://stackoverflow.com/questions/79687815/cython-multiple-definitions-of-function
- **Python version must be ~3.10** — ImGui (still in `pyproject.toml`) didn't compile in 3.11 with PyPy
- All `.py` files in `pysnes/` are compiled into a single monolithic Cython `.so` extension
- `setup.py` compiles everything and links against SDL2
- `cythonize()` uses `cache=True` and `nthreads=cpu_count()` — only changed `.py` files are re-transpiled; Cython step is parallelised
- Generated `.c` and `.html` files sit alongside `.py` files but are git-ignored
- The C compilation step (setuptools) always recompiles all `.o` files due to a setuptools regression — this is a known limitation

## Architecture

```
pysnes/pysnes.py    Main emulator class + entry point
pysnes/cpu/         WDC65816 CPU, DMA/HDMA engine, instruction set
pysnes/apu/         SPC700 APU, S-DSP, SPC file support
pysnes/ppu/         PPU graphics pipeline, data structures
pysnes/bus/         Memory bus (address decoding, register routing)
pysnes/scheduler/   Event-driven master-clock scheduler
pysnes/video/       SDL2 video renderer
pysnes/audio/       SDL2 audio output
pysnes/controller/  SNES controller input
pysnes/savestate/   Save state serialization
pysnes/harness/     Headless scripting harness + NDJSON RPC CLI
pysnes/debugger/    Live debug TUI
pysnes/rom.py       ROM parser (LoROM/HiROM, header, vectors)
```

### Main Loop (scanline-based)
1. For each of 262 scanlines per frame:
   - CPU executes instructions until scanline cycle budget is reached
   - PPU renders that scanline (backgrounds, sprites, palette)
   - APU ticks 3x per CPU scanline
2. When all scanlines done → render frame buffer via SDL2 → back to scanline 0

### Component Details
- **CPU**: WDC65816, 3.58 MHz, 16-bit with 6502 emulation mode
- **APU**: SPC700 @ 1.024 MHz, 3 timers, 4 I/O ports, 64KB address space, embedded IPL ROM
- **PPU**: 64KB VRAM, 512B CGRAM, OAM, 4 backgrounds, 256×224 output
- **Bus**: 24-bit address space — LoROM/HiROM mapping, RAM, PPU/APU registers, DMA
- **Video/Audio**: SDL2 hardware-accelerated renderer + 32 kHz stereo audio queue

## Implementation Status

- WDC65816 CPU: all 256 opcodes, all addressing modes, flags, registers. Passes all 512 SingleStepTests (1 case/opcode/mode by default)
- SPC700 APU: full instruction set, registers, memory, timers, I/O ports to CPU. Passes all 25,600 SingleStepTests cases at 100/opcode
- PPU: all 8 BG modes (some with approximations), sprites, color math, window masking, HDMA, mosaic
- S-DSP: BRR decoding, ADSR/GAIN, Gaussian interpolation, echo/reverb, 8-voice mixing
- Save states, memory bus, ROM loading, SDL2 video and audio, keyboard input, debug TUI

Known gaps are documented as `# TODO` comments at the relevant code sites.


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
uv run pytest pysnes/test_integration.py::test_frame_divergence -v -s

# Tier 2 — find exact diverging CPU instruction:
uv run pytest pysnes/test_integration.py::test_instruction_divergence -v -s

# Custom ROM / frame count / instruction count:
SNES_ROM="roms/mygame.sfc" uv run pytest pysnes/test_integration.py -v -s --frames 120 --instructions 200000

# Skip integration tests in normal suite:
uv run pytest pysnes/ -m "not integration"
```

- Mesen Lua scripts are in `scripts/mesen_oracle.lua` (Tier 1) and `scripts/mesen_trace.lua` (Tier 2)
- Port is passed to Lua via `MESEN_PORT` env var; frame/instruction count via `MESEN_FRAMES`/`MESEN_INSTRUCTIONS`
- `PYSNES_HEADLESS=1` suppresses SDL2 window during PySNES fixture runs
- Alternative oracle: BizHawk; Lua API reference at https://tasvideos.org/Bizhawk/LuaFunctions

## Testing

```bash
# All tests
uv run pytest pysnes/

# CPU tests (TomHarte's ProcessorTests / SingleStepTests 65816)
uv run pytest pysnes/cpu/test_cpu.py

# SPC700 instruction tests (SingleStepTests spc700)
uv run pytest pysnes/apu/test_spc700.py

# APU / timer / interrupt / scheduler unit tests
uv run pytest pysnes/apu/test_apu.py pysnes/apu/test_timers.py pysnes/bus/test_interrupts.py pysnes/scheduler/test_scheduler.py

# PPU unit tests (synthetic, no ROM, no Mesen):
uv run pytest pysnes/ppu/test_ppu_scroll.py pysnes/ppu/test_ppu_sprites.py pysnes/ppu/test_ppu_bgmode.py pysnes/ppu/test_ppu_registers.py pysnes/ppu/test_ppu_bg_window.py pysnes/ppu/test_ppu_color_math.py pysnes/ppu/test_ppu_color_math_window.py pysnes/ppu/test_ppu_mosaic.py pysnes/ppu/test_ppu_forced_blank.py -v

# PPU screenshot regression tests (Mesen is the live oracle — no static reference PNGs needed):
uv run pytest pysnes/ppu/test_ppu.py -m ppu

# Filter options (apply to test_cpu.py and test_spc700.py)
uv run pytest pysnes/cpu/test_cpu.py --opcode ea           # single opcode
uv run pytest pysnes/apu/test_spc700.py --opcode d0        # single opcode
uv run pytest pysnes/cpu/test_cpu.py --max-per-opcode 0    # all cases (unlimited)
uv run pytest pysnes/cpu/test_cpu.py --max-per-opcode 10   # 10 cases per opcode
uv run pytest pysnes/cpu/test_cpu.py --mode e              # emulation mode only (65816)
uv run pytest pysnes/cpu/test_cpu.py --mode n              # native mode only (65816)
uv run pytest pysnes/cpu/test_cpu.py --opcode ea --mode n  # combine filters
```

- 65816 test data is at `submodules/65816/v1/` (files named `{opcode}.{e|n}.json`)
- SPC700 test data is at `submodules/SingleStepTests_spc700/v1/`
- Tests verify: initial state → execute instruction → final registers, RAM, and memory access sequence
- CPU (`pysnes/cpu/cpu.py`) and APU (`pysnes/apu/apu.py`) are the tested implementations
- `pytest-xdist` is available for parallel execution. Test params are `(file, index)` refs, not full dicts; collection is cached to `.pytest_cache/ss_{cpu,spc700}_<key>.pickle` under an `fcntl.flock` so workers after the first just read the pickle.
- **Recommended invocation: `-n auto --dist=loadgroup`** for `test_cpu.py` and `test_spc700.py`. Each param carries an `xdist_group(file_path)` marker, so `--dist=loadgroup` pins all cases from one JSON file to a single worker; a single-slot file cache in `_load_case` then parses that JSON only once per worker. Delete `.pytest_cache/ss_*.pickle` if you suspect stale cache (it's keyed on filter args + JSON mtimes and should self-invalidate).
- Cycle count is checked against `len(test_case["cycles"])` for every CPU opcode. The 65816 harness does not verify per-cycle bus-status bits (VDA/VPA/VPB/MLB/M/X/E); only R/W.


## Git Workflow
- **Always create a new branch off `main` before making changes.** Check `git branch` first; if already on a feature branch (not `main`), continue there. If on `main`, run `git checkout -b <descriptive-branch-name>` before editing any files.
- **Never rebase** unless explicitly instructed. Use `git merge` to integrate changes (e.g. `git merge origin/main` to resolve PR conflicts). Rebase rewrites history and requires force-push, which is destructive for shared branches.
- **Never force push** unless explicitly instructed. Always use plain `git push`.

## Key Design Decisions
- **Pure Python mode Cython**: No `.pyx` files — all `.py` files compiled by Cython. This allows running without a build step during development.
- **PyPy + Cython**: Can run either way — PyPy JIT or Cython-compiled CPython. Pure PyPy (no build step) is faster; every `.so` call breaks the JIT trace, causing a ~5× slowdown when PPU/APU are compiled.
- **SDL2 over OpenGL/ImGui**: Switched for major performance gains. Don't reintroduce OpenGL/ImGui.
- **Automated testing**: We aim for every functionallity to be covered by automated tests. When there is a change to be made, the tests need to be created first to perfectly outline the end goal.
- **Scanline-based timing**: CPU runs until scanline budget, then PPU renders that scanline. This is not how real SNES hardware operates, but it's a compromise to improve performance in hopes for most games to work.

## ROM for Testing
- ROM files are in `roms/` directory (not committed to git)
- ROM path is passed as a positional CLI argument: `python -m pysnes.pysnes <rom>`
- Optional `--trace <ref>` flag enables CPU trace comparison against a reference log

