# PySNES Component Audit

Missing features and Cython performance analysis for CPU, APU, and PPU.

---

## CPU (`pysnes/cpu/cpu.py`)

**Status: COMPLETE** — all known missing features and Cython hot spots addressed.

### Resolved Items

| Issue | Resolution |
|---|---|
| `idle4()` / `idle6()` were `pass` stubs | Implemented with correct bsnes semantics |
| `interrupt()` returned 1 MC, used raw `bus.write()` | Fixed: 2 idles + cpu.write/read, returns actual MC |
| `get_clock_cycles()` ignored $420D FastROM | Wired through `CpuStatus.fast_rom` |
| `CpuStatus` used `@dataclass` + `@cython.cclass` | Replaced with `cython.declare()` fields |
| `ccall` on hot read/write methods | Changed to `@cython.cfunc` |
| `functools.partial` instruction dispatch | Replaced with `InstructionSlot` cclass + `cython.cast` (+28%: ~9.8M → 12.5M instr/sec) |
| `idleBranch()` / `idleJump()` stubs | Confirmed correct as no-ops — `idle6` handles page-cross penalty; verified with 20+ test cases per branch opcode |
| `synchronizing()` hardcoded `True` | Not a CPU bug — WAI/STP spin loop is scheduler design; correct for single-step tests |

---

## APU (`pysnes/apu/apu.py`)

**Status: COMPLETE** (except DSP/audio synthesis — separate feature work)

### Resolved Items

| Issue | Resolution |
|---|---|
| Timer `step()` hardcoded `clocks = 128` | Fixed: uses passed `clocks` arg; `sync_to` passes `self.cycles` after each instruction |
| `A`/`X`/`Y`/`S`/`PC` property setters with asserts | Removed — replaced property wrappers with plain attributes |
| `fetch()` / `__setitem__` asserts | Removed |
| `fetch_and_execute()` try/except/finally + always-allocated debug strings | Removed; debug printing gated on `print_debug` flag |
| Port reset bits 4/5 reset both `ports_r` and `ports_w` | Fixed: only `ports_r` (CPU→APU input) is reset, matching bsnes hardware behavior |
| `Apu` / `Timer` plain Python classes — all attrs dict-backed | Converted to `@cython.cclass` with `cython.declare()` fields; hot methods annotated `@cython.ccall` / `@cython.cfunc` |
| `f8` / `f9` registers unknown purpose | Confirmed correct as-is — they are general-purpose RAM bytes with no special hardware behavior |
| `__getitem__`/`__setitem__` if-elif dispatch | Replaced with `_read`/`_write` `@cython.cfunc`; `_mem_log` field replaces test patching (+10%: 16.3M → 17.9M instr/sec) |
| `functools.partial` instruction dispatch | Replaced with `InstructionSlot` cclass + `cython.cast` (+48%: 17.9M → 26.5M instr/sec) |

### Remaining (out of scope for this branch)

| Issue | Impact |
|---|---|
| DSP register writes (`$F2`/`$F3`) are no-ops | No audio synthesis; sound absent entirely — separate feature |

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

### Testing Strategy

Screenshot comparison against Mesen reference output. Each test:
1. Runs PySNES for N frames on a known ROM
2. Captures the framebuffer
3. Compares pixel-by-pixel against a Mesen-generated reference PNG

**Available test ROMs** (`submodules/SNES/PPU/` — PeterLemon collection, pre-built `.sfc` + reference `.png` per ROM):

| Feature | ROM | Reference PNG |
|---|---|---|
| BG1 2BPP tilemap | `BGMAP/8x8/2BPP/8x8BG1Map2BPP32x328PAL/` | ✅ included |
| BG2 2BPP tilemap | `BGMAP/8x8/2BPP/8x8BG2Map2BPP32x328PAL/` | ✅ included |
| BG3 2BPP tilemap | `BGMAP/8x8/2BPP/8x8BG3Map2BPP32x328PAL/` | ✅ included |
| BG4 2BPP tilemap | `BGMAP/8x8/2BPP/8x8BG4Map2BPP32x328PAL/` | ✅ included |
| BG 4BPP tilemap | `BGMAP/8x8/4BPP/8x8BGMap4BPP32x328PAL/` | ✅ included |
| BG 8BPP tilemap (multiple sizes) | `BGMAP/8x8/8BPP/*/` | ✅ included |
| Tile flip | `BGMAP/8x8/8BPP/TileFlip/` | ✅ included |
| Mode 7 rotation/zoom | `Mode7/RotZoom/` | — |
| Mode 7 perspective | `Mode7/Perspective/` | — |
| Window masking (HDMA) | `Window/WindowHDMA/` | — |
| Mosaic (Mode 3) | `Mosaic/Mode3/` | — |
| Mosaic (Mode 5) | `Mosaic/Mode5/` | — |
| HDMA wave | `HDMA/WaveHDMA/` | — |
| HiColor blend | `Blend/HiColor/*/` | — |
| Interlace | `Interlace/*/` | — |

**Coverage gaps** — no pre-built test ROMs available for:
- BG modes 2, 4, 5, 6 (PeterLemon organises by BPP depth, not mode number)
- Sprites / OAM rendering
- Color math / CGADSUB sub-screen blending
- 16×16 BG tiles
- Backdrop transparency

For these gaps, minimal test ROMs will need to be authored (65816 assembly using `ca65` or byte-array generation in Python).

### Action Plan (ordered by impact)

| Priority | Item | Test ROM available |
|---|---|---|
| 1 | Build screenshot comparison test harness (run ROM → capture framebuffer → diff vs reference) | infrastructure |
| 2 | Fix `draw_point()` — writes pixel color but never stores to `main_bgs`; sprites and tiles are invisible | need to author |
| 3 | Fix backdrop color — applied unconditionally; should only show for transparent pixels | BG tilemap ROMs |
| 4 | Fix `bgmode` / `oamaddl` / `oamaddh` `NotImplementedError` getters | BG tilemap ROMs |
| 5 | Fix VRAM address remapping crash (`assert remapping == 0`) | BG tilemap ROMs |
| 6 | Implement BG modes 2, 4, 5, 6 | need to author |
| 7 | Implement Mode 7 (rotation/scaling) | `Mode7/RotZoom.sfc` |
| 8 | Implement window masking | `Window/WindowHDMA.sfc` |
| 9 | Implement color math / sub-screen blending | need to author |
| 10 | Fix 16×16 BG tiles | need to author |
| 11 | Cython hot spots (`main_bgs`, `draw_tile`, `get_u32_color`, NDC floats, `vram` memoryview) | any BG tilemap ROM |

---

## Summary Table

| Component | Game-Breaking Missing Features | Cython Bottleneck |
|---|---|---|
| **CPU** | ✅ Complete | ✅ Complete |
| **APU** | ✅ Complete (DSP/audio out of scope) | ✅ Complete (`__getitem__`/`__setitem__` dispatch is remaining bottleneck) |
| **PPU** | Modes 2/4/5/6/7 missing, `draw_point` discards output (sprites invisible), window/color-math absent, 16×16 tiles broken, 3× `NotImplementedError` getters | `main_bgs` Python list, `get_u32_color` untyped + `bpp**2`, `draw_tile` uses Python `zip`/`reversed`, NDC floats computed but unused |
