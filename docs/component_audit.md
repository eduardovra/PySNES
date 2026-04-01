# PySNES Component Audit

Missing features and Cython performance analysis for CPU, APU, and PPU.

---

## CPU (`pysnes/cpu/cpu.py`)

### Missing / Broken Features

| Issue | Location | Impact |
|---|---|---|
| `idle4()` and `idle6()` are `pass` stubs | cpu.py:230–238 | Index-register page-crossing and page-wrap idle cycles never fire; timing wrong for many instructions |
| `idleBranch()` and `idleJump()` are `pass` stubs | cpu.py:236–240 | Branch-taken page-crossing extra cycle lost; affects timing accuracy |
| `get_clock_cycles()` ignores $420D bit 0 (FastROM) | cpu.py:457,459 | Banks $80–$BF and $C0–$FF always return `fast` instead of checking the ROM speed register; games that configure FastROM will have wrong timings |
| `interrupt()` returns `1` MC instead of actual cycles | cpu.py:505 | NMI/IRQ handler takes effectively 0 master-clock time; scheduler budget is off for interrupt-heavy games |
| `interrupt()` uses raw `bus.write()` | cpu.py:486–502 | Bypasses `cpu.write()`, so no cycle counting for the stack pushes during interrupts |
| `synchronizing()` hardcoded to `True` | cpu.py:243–246 | WAI/STP opcode behavior may differ from hardware |
| `CpuStatus` uses `@dataclass` + `@cython.cclass` | cpu.py:81–92 | `dataclasses` module loaded at class creation (Cython score 328); double-decorator combo has overhead |

### Cython Performance Hot Spots

| Score | Location | Problem |
|---|---|---|
| 328 | cpu.py:83 `class CpuStatus` | `@dataclass` triggers `__pyx_t_2 = __Pyx_Load_dataclasses_Module()` — Python module load at class definition |
| 117 | cpu.py:124 `__str__` | f-string with many attribute accesses through Python `GetAttrStr` |
| 105 | cpu.py:249,270,285,289,293,301 `write*` methods | All `@cython.ccall` methods generate Python wrappers (overhead when called from Python-layer addressing modes) |
| 93 | cpu.py:254,261,281,284,292,300 `read*` methods | Same as above — Python wrapper generation for every `ccall` variant |

**Key structural issue**: `self.instructions[opcode]` stores `functools.partial` objects in a Python list. Every `fetch_and_execute()` call does a Python list lookup followed by a Python `partial.__call__`. This is the innermost hot loop and is unavoidably Python.

---

## APU (`pysnes/apu/apu.py`)

### Missing / Broken Features

| Issue | Location | Impact |
|---|---|---|
| Timer `step()` hardcodes `clocks = 128`, ignoring the computed wait_states | apu.py:24–26 | Timer frequency always runs at divider 128, ignoring the Test Register (F0) wait-state bits |
| `f8` / `f9` registers have no known purpose | apu.py:140–141 | Stored and returned as-is; no hardware behavior modeled |
| DSP register writes (`$F2`/`$F3`) are no-ops | apu.py:348–350 | No audio DSP emulated; sound synthesis absent entirely |
| Port reset uncertainty for bits 4/5 of control register | apu.py:474,481 | TODO: unclear whether `ports_r` or `ports_w` should be reset; current code resets both |
| `A`, `X`, `Y`, `S`, `PC` setters have `assert isinstance()` + bounds checks | apu.py:500–547 | Python asserts run in hot register-write paths; should be removed or gated on debug flag |
| `fetch()` has `assert isinstance(data, int)` | apu.py:216 | Assert in the innermost fetch loop |
| `__setitem__` has 3 `assert` calls | apu.py:334–336 | Asserts on every memory write |
| `fetch_and_execute()` wraps instruction call in try/except/finally | apu.py:233–251 | Exception handling has Python overhead even when no exception is raised; debug printing always allocates strings |

### Cython Performance Hot Spots

| Score | Location | Problem |
|---|---|---|
| 79 | apu.py:437 `control_register.setter` | Pure Python property setter; no `@cython.cclass` on `Apu` means all attrs are dict-backed |
| 75 | apu.py:418 `test_register.setter` | Same — untyped Python class |
| 73 | apu.py:402 `YA.setter` | Python property with untyped int ops |
| 72 | apu.py:387 `PSW.setter` | `bool()` calls on every flag set; untyped |
| 68 | apu.py:323 `__setitem__` | Long if-elif chain without typed `addr` parameter; every branch is a Python integer comparison |
| 57 | apu.py:281 `__getitem__` | Same problem as `__setitem__` |
| 60 | apu.py:256 `sync_to` | Outer catch-up loop calls `fetch_and_execute()` which has try/except/finally overhead per instruction |
| 56 | apu.py:23 `Timer.step` | `Timer` is a plain Python class; `self.apu.internal_wait_states` is a dict attribute lookup |
| 55 | apu.py:504,514,524 `A`/`X`/`Y` setters | Assert + isinstance check on every register write |

**Root structural issue**: `Apu` and `Timer` are plain Python classes — no `@cython.cclass`. All attribute accesses go through the Python instance `__dict__`, which Cython cannot optimize. Compare with `Cpu` which uses `@cython.cclass` with `cython.declare()` for each field.

---

## PPU (`pysnes/ppu/ppu.py`)

### Missing / Broken Features

**BG Modes:**

| Issue | Location | Impact |
|---|---|---|
| Modes 2, 4, 5, 6 not implemented | ppu.py:453 | `raise NotImplementedError` — any game using these modes crashes |
| Mode 7 (rotation/scaling) not rendered | bus.py:299–312 | M7SEL/M7A-M7Y registers stored but render path absent; F-Zero, Pilotwings etc. broken |
| 16×16 BG tiles not rendered | ppu.py:105–110 | `bg.tile_size` is set from $2105 but `draw_background_scanline()` always treats tiles as 8×8 |
| BG3 priority bit (`_bgpriority`) only partially used | ppu.py:419–427 | Mode 1 BG3 priority toggle works, but other mode interactions untested |

**Rendering:**

| Issue | Location | Impact |
|---|---|---|
| `draw_point()` never writes to `main_bgs` | ppu.py:697–745 | Method computes pixel color but discards it — effectively dead code; `draw_tile()` / `draw_tiles()` path (used by sprites) produces no output |
| Backdrop color applied to every pixel, not only transparent ones | ppu.py:740 | Layers that should show through to backdrop may be overdrawn incorrectly |
| Mosaic effect disabled (`and False`) | ppu.py:575 | Code written but permanently disabled |
| Window masking not implemented | bus.py:326–327 | $2123–$212B writes silently ignored; no window clipping |
| Color math / sub-screen blending not implemented | bus.py:337–338 | $2130–$2132 silently ignored; SNES transparency effects absent |
| Sprite visibility uses `obj.y != 240` hack | ppu.py:831 | Should use proper X/Y bounds check with wrapping; sprites at wrong positions may be drawn or skipped |
| OAM priority rotation (`_oam_priority_activation`) unused | ppu.py:229–231 | Sprite priority cycling on first sprite never applied |

**Register reads (raise NotImplementedError or return wrong data):**

| Register | Location | Issue |
|---|---|---|
| `bgmode` getter | ppu.py:101 | `raise NotImplementedError` — any read of $2105 crashes |
| `oamaddl` getter | ppu.py:217 | `raise NotImplementedError` |
| `oamaddh` getter | ppu.py:226 | `raise NotImplementedError` |
| `stat78` ($213F) | ppu.py:200 | Only returns frame field; PAL/interlace/etc. bits absent |
| `slhv` ($2137) latch | ppu.py:207 | Always returns 0; should latch H/V counter |
| VRAM address remapping | ppu.py:123 | `assert remapping == 0` — crashes if games use remapping modes 1–3 |
| INIDISP OAM address reset | ppu.py:95 | TODO: OAM address not reset on first blank line write |

### Cython Performance Hot Spots

| Score | Location | Problem |
|---|---|---|
| 141 | ppu.py:697 `draw_point` | Highest score in file; `zip()` over Python lists, tuple returns, called per-pixel from `draw_tile` |
| 116 | ppu.py:661 `draw_tile` | Uses `zip()`, `list(reversed(range(...)))`, Python sequences in hot per-scanline loop |
| 115 | ppu.py:599 `draw_tiles` | Python keyword-arg call, `getattr`/`setattr` for mosaic, no typed args |
| 105/105 | ppu.py:683,694 | `zip(line_sequence, y_sequence)` and `zip(pixel_sequence, x_sequence)` — Python `zip` builtin called in innermost loops |
| 101 | ppu.py:747 `get_rbg_colors` | `bpp ** 2` Python exponentiation; returns Python tuple; called per-pixel |
| 98 | ppu.py:770 `get_u32_color` | Same `bpp ** 2` issue; called 256× per scanline per BG layer |
| 66 | ppu.py:871 `OAM.__init__` | `[Object() for i in range(128)]` allocates 128 Python objects at init |
| 64 | ppu.py:884 `OAM.__setitem__` | `OAM` is a plain Python class (no `@cython.cclass`) |

**Root structural issues in PPU:**

1. **`main_bgs` is a Python list** (`[0x00] * 256 * 262`). Item assignment `self.main_bgs[y * width + x] = u32_color` goes through Python even in compiled code. Should be a `cython.uint[:]` typed memoryview.

2. **`draw_background_scanline()` inner loop (256 iterations)** is marked `@cython.cfunc` but calls `get_u32_color()` which is a regular Python method with untyped args and `bpp ** 2`.

3. **`draw_scanline_backdrop()` computes unused NDC floats** — `x_ndc`, `y_ndc` are computed each iteration but never used (leftover from OpenGL era).

4. **`get_rbg_colors()` / `get_rbg_backdrop_color()`** compute floating-point `r/g/b` normalized values (also unused; leftover from OpenGL). Dead computation on every call.

5. **`vram` is untyped `bytearray`** — in Cython, `bytearray` indexing goes through Python without a typed memoryview declaration.

---

## Summary Table

| Component | Game-Breaking Missing Features | Cython Bottleneck |
|---|---|---|
| **CPU** | `idle4/6/Branch/Jump` stubs (wrong timing), `interrupt()` MC=1, FastROM flag ignored | `instructions` dispatch via Python `partial`; `ccall` wrappers; `dataclass` on `CpuStatus` |
| **APU** | No audio DSP, timer wait-states hardcoded, `assert` in hot paths, try/except in fetch loop | No `@cython.cclass` on `Apu`/`Timer` — all attrs dict-backed; typed memoryviews missing |
| **PPU** | Modes 2/4/5/6/7 missing, `draw_point` discards output (sprites invisible), window/color-math absent, 16×16 tiles broken, 3× `NotImplementedError` getters | `main_bgs` Python list, `get_u32_color` untyped + `bpp**2`, `draw_tile` uses Python `zip`/`reversed`, NDC floats computed but unused |
