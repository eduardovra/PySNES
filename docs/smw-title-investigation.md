# SMW Title Screen Investigation

Living document tracking progress on the SMW title-screen render pipeline.

## Status (2026-04-18)

SMW boots past the IPL handshake, past the Nintendo Presents splash,
and into the title screen. The title **fade-in** (frame ~300–340,
mosaic + brightness ramp) is now pixel-identical to Mesen at the
frames observed. The **title-curtain animation** (grass banner
sweeping up from the bottom with Mario/Yoshi/bird sprites) is still
broken: instead of the per-scanline HDMA window values Mesen writes,
PySNES's WRAM table is filled with `0x80`s, producing a single-pixel
window that masks everything except the dead-center column.

The curtain bug is a downstream symptom of a small CPU/APU timing
drift during boot that we have not fully closed.

## Fixes landed this session

PRs merged (all on `main`):

- `#10` sprite sub-tile bleed (d0eb43b) — multi-tile sprites
- `#10` sub-screen backdrop (`fa71a43`) — sky blue via `backdrop + COLDATA`
- `#10` HDMA indirect addressing (`46027e8`) — DMAPx bit 6
- `#10` 3× window default
- `#11` H/V IRQ (`$4207-$420A`, `$4211`, PPU timer match)
- `#12` CGADSUB subtract + half-intensity (bits 7/6)
- `#13` OAM priority ordering across modes 0/1/3
- `#14` Hardware-register bank mirror (`$2100-$21FF`, `$4200-$44FF` across banks `$00-$3F`)
- `#15` SRAM with `.srm` battery backup
- `#17` ROM header parsing dataclasses
- `#18` 40-MC DRAM refresh per scanline
- `#19` Low-effort TODO cleanup
- `#20` PPU mosaic per-BG block averaging (`$2106`)
- `#21` CGWSEL color-math windowing (bits 5:4 + WOBJSEL bits 4-7 + WOBJLOG bits 2-3)
- `#22` `$4210` RDNMI bit-7 persists through V-Blank end

Frame-400 Mesen diff evolution during the session:
- Before any of the above: ~16% pixel diff, mountains leaking, no grass banner
- After H/V IRQ + color-math subtract + sprite priority + bank mirror: 84%+ match, Mario renders, mountains fade correctly
- After CGWSEL windowing landed: frame 310 is **100% pixel-identical** to Mesen; frame 400 drops to 39.7% because CGWSEL correctly gates color math, exposing the upstream WRAM-table bug

## Remaining bug chain

1. **SMW NMI handler computes `WH0/WH1` table filled with `0x80` bytes** instead of a sweeping sequence
2. Root cause: **SMW's animation state machine takes a wrong branch** during the IPL handshake phase
3. Root cause: **our APU returns `0xAA` from `$2140` one CMP iteration earlier than Mesen's**
4. Root cause: **CPU/APU timing drift in our emulator**
   - Tier-2 instruction-level divergence at instruction **#1988**: PySNES already at `PC=$8087` (post-spin `sep #$20`), Mesen still at `PC=$8082` (another CMP)
   - Magnitude: ~12 MC (one CMP+BNE pair) ahead of Mesen by instruction 1988

This means our APU gets a tiny bit more effective clock budget than
Mesen's APU over the ~48K master clocks of boot code, finishes the IPL
memory-clear loop one iteration early, and latches `$AA` into its
`$F4` output before Mesen's APU does.

## Things tried that didn't close the drift

- **DRAM refresh (`#18`)** — moved divergence from 5 iterations behind to 1 ahead. Net improvement, but overshot by ~12 MC.
- **Cycle-count audit of all 256 CPU opcodes** — 23 opcodes have mis-counted cycle totals in SingleStepTests, but *none of them are executed* by SMW in the first 2000 instructions. Fixing them would be correct but won't move SMW.
- **SPC700 cycle counts** — verified correct; `test_spc700.py` enforces cycle-count equality and passes.
- **`$4210` RDNMI persistence (`#22`)** — architectural correctness fix, but SMW's first V-Blank is at MC 307K, well after the MC 48K handshake divergence. No timing impact on boot.
- **CGWSEL color-math windowing (`#21`)** — does not affect CPU/APU state; it only gates the post-render composite pass.

## Hypotheses not yet tested

- **Integer-rounding drift in `apu.sync_to`**: we use `elapsed * 1024000 // 21477272` (floor) for both directions. Mesen integrates differently (spc sample rate × 64 model). Small per-call rounding differences accumulate.
- **CPU cycle counts for instructions SMW actually uses** during boot. A per-opcode audit limited to SMW's hot set (`A9`/`A2`/`8D`/`E2`/`C2`/`18`/`38`/`78`/`9C`/`48`/`68`/`AB`/`BD`/`DD`/`F0`/`D0`/`CD`/`B0`/`90`…) could reveal a single off-by-one per-instruction.
- **Reset cycle count**: we initialize `cpu.cycles = 182` (snes9x value). Mesen may differ.
- **I/O port read cycles for `$2140`**: currently 6 MC (fast bus). Some sources claim it's xslow (12 MC) during active rendering or 8 MC in certain timing windows.

## Diagnostic scripts (committed)

- `scripts/pysnes_dump_vram.py` — headless dump of VRAM, CGRAM, PPU state, composite framebuffer
- `scripts/mesen_dump_state.lua` — Mesen-side equivalent dump (VRAM + PPU state JSON)
- `scripts/mesen_layers.lua` — per-layer capture with TM/TS overrides
- `scripts/mesen_screenshot.lua` — full screen buffer capture
- `scripts/mesen_trace.lua` — CPU instruction trace over TCP

Useful one-off probes that helped in this session (not committed,
under `/tmp/`):

- headless framebuffer snap at N frames, convert `main_bgs` to PNG with brightness applied
- `mesen_vs_pysnes.py` — side-by-side composite + per-pixel diff at a given frame
- Probe of APU sync progress (APU PC vs MC) at checkpointed MCs
- BG1-only vs Mesen-BG1-only comparison using `TM_MASK=0x01`
- Tier-2 test with `MESEN_PORT` listener to capture Mesen trace lines
- Trace of every CPU `$2140` read with returned value and APU state

## Next steps when this picks back up

1. **Compare CPU trace line-by-line for pre-spin instructions** (1-1980) between PySNES and Mesen — if state diverges before the spin, the cycle bug is in one of those earlier opcodes.
2. **Swap our integer-floor `sync_to` for fractional accumulation** (store last-sync-MC as a `(whole, remainder)` pair, or use a float) to eliminate sub-MC rounding bias.
3. **Try `cpu.cycles = 186` or `200` at reset** — snes9x's comment notes "182 Or 188. This is the cycle count just after the jump to the Reset Vector." Different emulators start at different values.
4. **Consider running SMW's boot under BizHawk or bsnes** to cross-check: if both bsnes and Mesen exit the spin at the same instruction count, the target is unambiguous; if they differ, our target is fuzzy.
