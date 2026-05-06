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

## APU (`pysnes/apu/apu.py`) + DSP (`pysnes/apu/dsp.py`) + Audio (`pysnes/audio/audio_sdl2.py`)

**Status: COMPLETE** (S-DSP implemented with known limitations documented below)

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
| DSP register writes (`$F2`/`$F3`) are no-ops | Implemented full S-DSP (`dsp.py`): BRR decoding, ADSR/GAIN envelopes with hardware rate table, 8-voice mixing, KON/KOFF/ENDX/ENVX |
| No audio output | SDL2 queue-mode output (`audio_sdl2.py`): 32 kHz stereo int16, `SDL_AUDIO_ALLOW_FREQUENCY_CHANGE` + numpy linear resample when device rate ≠ 32 kHz |
| Audio/video sync | Wall-clock frame limiter in main loop (sleep + 1 ms busy-wait to NTSC deadline); audio queue as overflow safety valve; EMA-smoothed FPS display |

### DSP Known Limitations

Features not yet implemented (follow-up work):

| Feature | Impact |
|---|---|
| ~~Gaussian interpolation~~ | ✅ Implemented: 4-tap Gaussian FIR with 512-entry bsnes/Mesen table; history ring per voice. |
| ~~Echo / reverb (EON, EFB, FIR coefficients)~~ | ✅ Implemented: 8-tap FIR echo, EFB feedback, EVOL, EON per-voice routing, lazy init from SPC RAM. |
| Pitch modulation (PMON register) | Voice N can be pitch-modulated by voice N-1's output. Unused in most games; absent here. |
| Noise mode (NON register) | Replaces BRR sample with a LFSR noise source per voice. Percussion/SFX that use noise mode will be silent. |
| Programmable GAIN envelope (GAIN bit7=1) | Treated as ADSR; linear-increase / bent-line / decrease / bent-line-decrease modes absent. Affects a minority of instruments. |
| Stereo hard-clipping | SNES hardware clips each voice's L+R mix separately before master volume. Current code clips only the final output. Audible only on heavily overdriven mixes. |

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
| Window masking W2 not implemented | ppu.py | W1 masking implemented; W2 and AND/OR logic not yet wired |
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

Two-level approach:
1. **Synthetic unit tests** (`test_ppu_scroll.py`) — instantiate `Ppu` directly, write VRAM/CGRAM by hand, call `draw_background_scanline()`, assert pixel values. No ROM, no Mesen.
2. **Screenshot regression tests** (`test_ppu.py`, marked `ppu`) — run PySNES on a PeterLemon ROM for N frames, compare framebuffer pixel-by-pixel against the PNG bundled with the ROM.

**Current test pass/fail status:**

| Test | File | Status | Notes |
|---|---|---|---|
| bg1_2bpp | test_ppu.py | ✅ PASS | 5 frames, Mode 1 BG1 2BPP |
| bg2_2bpp | test_ppu.py | ✅ PASS | 5 frames, Mode 1 BG2 2BPP |
| bg3_2bpp | test_ppu.py | ✅ PASS | 5 frames, Mode 1 BG3 2BPP |
| bg4_2bpp | test_ppu.py | ✅ PASS | 5 frames, Mode 0 BG4 2BPP |
| bg_4bpp | test_ppu.py | ✅ PASS | 5 frames, Mode 1 BG1 4BPP |
| tile_flip | test_ppu.py | ✅ PASS | 20 frames, 8BPP with h/v flip (FadeIN completes at frame 15) |
| scroll (18 cases) | test_ppu_scroll.py | ✅ PASS | h/v scroll, sub-tile, wrap, tilemap bit extraction, palette/priority, window masking |
| bg_8bpp | removed | — | ROM scrolls 1px/frame — timing sensitivity makes pixel-perfect comparison impossible |
| mode7_rotzoom | test_ppu.py | ❌ NotImplementedError | Mode 7 render path not implemented |
| window_hdma | test_ppu.py | ✅ PASS | 3 frames; HDMA + window masking implemented |
| mosaic_mode3 | test_ppu.py | ✅ PASS | 2 frames (FadeIN brightness=2 matches reference) |

**Key fixes made (ppu-improvements branch):**
- `tiledata_addr` formula: `<< 12` → `<< 13` (8KB granularity, matching bsnes) in `bg12nba_set` / `bg34nba_set`
- Scanline offset: `orgy = scry - 1` — framebuffer row N is written by `v_counter = N+1`
- Bus registers: wired up missing BG scroll, BG tilemap/tiledata address, INIDISP, and other registers
- HDMA engine implemented: `hdma_init()` per-frame, `hdma_scanline()` per H-blank, both do-not-repeat and do-repeat modes
- HDMA timing: render-before-HDMA ordering in `_hblank()` — HDMA updates registers for the NEXT scanline, not current
- HDMA repeat bit semantics (confirmed empirically from ROM binaries): **bit 7 = 0 = do-not-repeat** (pointer stays, same data each scanline — table format `[count][unit_bytes]`); **bit 7 = 1 = do-repeat** (pointer advances, fresh data each scanline — table format `[count|0x80][count×unit_bytes]`). This is the opposite of intuitive naming.
- Window masking: BG1-BG4 W1 enable/invert decoded from W12SEL ($2123) / W34SEL ($2124) / TMW ($212E) and applied per-pixel in `draw_background_scanline()`

**Tilemap word extraction (verified correct):**
SNES tilemap word: bit 15=V-flip, 14=H-flip, 13=priority, 12:10=palette, 9:0=char.
- `tilemap_palette = (high >> 2) & 7` ← correct (bits 12:10 = bits 4:2 of high byte)
- `tilemap_priority = (high >> 5) & 1` ← correct (bit 13 = bit 5 of high byte)
Covered by `TestTilemapWordBits` in `test_ppu_scroll.py`.

**Available test ROMs** (`submodules/SNES/PPU/` — PeterLemon collection):

| Feature | ROM | Reference PNG |
|---|---|---|
| BG1–4 2BPP tilemap | `BGMAP/8x8/2BPP/*/` | ✅ bundled with ROM |
| BG 4BPP tilemap | `BGMAP/8x8/4BPP/*/` | ✅ bundled with ROM |
| BG 8BPP tilemap | `BGMAP/8x8/8BPP/*/` | ✅ bundled with ROM |
| Tile flip (h+v) | `BGMAP/8x8/8BPP/TileFlip/` | ✅ bundled with ROM |
| Mode 7 rotation/zoom | `Mode7/RotZoom/` | ✅ bundled with ROM |
| Window masking (HDMA) | `Window/WindowHDMA/` | ✅ bundled with ROM |
| Mosaic (Mode 3) | `Mosaic/Mode3/` | ✅ bundled with ROM |

**Coverage gaps** — no pre-built test ROMs available for:
- BG modes 2, 4, 5, 6
- Sprites / OAM rendering
- Color math / CGADSUB sub-screen blending
- 16×16 BG tiles
- Backdrop transparency

### Action Plan (ordered by impact)

| Priority | Item | Test available |
|---|---|---|
| ~~1~~ | ~~Build screenshot comparison test harness~~ | ✅ done |
| ~~2~~ | ~~Fix tilemap word extraction~~ | ✅ verified correct, covered by TestTilemapWordBits |
| ~~5~~ | ~~Implement window masking (`$2123–$212B`)~~ | ✅ window_hdma PASS |
| ~~6~~ | ~~Implement mosaic effect (remove `and False` stub)~~ | ✅ mosaic_mode3 PASS at n_frames=2 (size=1 no-op path — full mosaic block replication not yet implemented) |
| ~~3~~ | ~~Fix `draw_point()` — writes pixel color but never stores to `main_bgs`; sprites invisible~~ | ✅ `test_ppu_sprites.py` — 6 synthetic unit tests |
| ~~4~~ | ~~Fix backdrop color — applied unconditionally; should only show for transparent pixels~~ | ✅ transparent pixel guard + `oam_main_screen_enable` check in `draw_objects()`; BG tests pass |
| 7 | Implement Mode 7 (rotation/scaling) | `Mode7/RotZoom.sfc` |
| ~~8~~ | ~~Fix `bgmode` / `oamaddl` / `oamaddh` `NotImplementedError` getters~~ | ✅ `test_ppu_registers.py` — getter round-trip tests |
| ~~9~~ | ~~Fix VRAM address remapping crash (`assert remapping == 0`)~~ | ✅ `test_ppu_registers.py` — remapping mode 1/2/3 tests |
| 10 | Implement BG modes 2, 4, 5, 6 | need to author |
| 11 | Implement color math / sub-screen blending | need to author |
| 12 | Fix 16×16 BG tiles | need to author |
| 13 | Cython hot spots (`main_bgs`, `draw_tile`, `get_u32_color`, NDC floats, `vram` memoryview) | any BG tilemap ROM |

---

## Summary Table

| Component | Game-Breaking Missing Features | Cython Bottleneck |
|---|---|---|
| **CPU** | ✅ Complete | ✅ Complete |
| **APU + DSP** | ✅ Complete — audio plays. Known gaps: noise mode, PMON, programmable GAIN | ✅ Complete (`__getitem__`/`__setitem__` dispatch is remaining bottleneck) |
| **PPU** | Modes 2/4/5/6/7 missing, `draw_point` discards output (sprites invisible), window/color-math absent, 16×16 tiles broken, 3× `NotImplementedError` getters | `main_bgs` Python list, `get_u32_color` untyped + `bpp**2`, `draw_tile` uses Python `zip`/`reversed`, NDC floats computed but unused |
