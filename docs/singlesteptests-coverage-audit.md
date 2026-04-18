# SingleStepTests: what we verify vs what we ignore

## Context

Audit of the CPU (65816) and APU (SPC700) SingleStepTests harnesses to answer: are we actually checking instruction timing, and are any fields in the JSON test cases being discarded?

Short answer: **SPC700 is near-complete; CPU leaves a lot on the table.** Details and optional expansion work below.

## JSON schema reference

Both suites use `{name, initial, final, cycles}`. The third element of each cycle tuple differs between suites.

**65816** (`submodules/65816/v1/*.json`): `[address, value, status]` where `status` is an **8-char string** `VDA/VPA/VPB/R-W/MLB/M/X/E`. Example `"dp-remx-"` means VDA=d, VPA=p, VPB=-, R/W=r, MLB=e, M=m, X=x, E=-. Ghost-read cycles have `value: null`.

**SPC700** (`submodules/SingleStepTests_spc700/v1/*.json`): `[address, value, kind]` where `kind ∈ {"read", "write", "wait"}`. `"wait"` cycles have `address: null, value: null`; ghost reads have `value: null, kind: "read"`.

## What CPU tests verify (`pysnes/cpu/test_cpu.py`)

- Final registers: PC, S, A, X, Y, E, P, D, DB, PB — `test_cpu.py:191-200`
- Final RAM — `test_cpu.py:201-202`
- Bus transaction sequence (address + value, read vs write only) — `test_cpu.py:155-165, 205`
- Total cycle count — **only for 22 of 256 opcodes** in `CYCLE_CHECK_OPCODES` (`test_cpu.py:18-26, 209-213`)

### What CPU tests ignore from the JSON
1. **Cycle count for ~234 opcodes.** Everything outside the allowlist in `CYCLE_CHECK_OPCODES`. A missing idle cycle or a page-cross penalty in, say, `6D` (ADC abs) or `9C` (STZ abs) would pass silently.
2. **7 of 8 bits in the status string.** Only position 3 (`r`/`w`) is consulted (`test_cpu.py:162-164`). Ignored:
   - **VDA / VPA** (positions 0-1) — distinguishes opcode fetch vs data fetch vs internal.
   - **VPB** (position 2) — pulses during vector pulls; validates BRK/COP/IRQ/NMI/RESET bus behaviour.
   - **MLB** (position 4) — memory lock, pulses during RMW.
   - **M / X / E** (positions 5-7) — flag state sampled on each cycle (useful for instructions that change flags mid-instruction, e.g. `XCE`, `REP`, `SEP`, `PLP`, `RTI`).
3. **Ghost-read cycles** (`value is None`) are skipped entirely (`test_cpu.py:159-160`) — neither address nor presence is asserted. The internal/idle cycles that make up page-cross and RMW timing disappear from the comparison.
4. **Loop exits early on cycle count.** `while len(calls_performed) < len(calls_expected)` (`test_cpu.py:183`) — a buggy impl that emits *extra* non-idle accesses after the expected count would not be caught by this loop (though it'd fail the sequence equality check).

## What SPC700 tests verify (`pysnes/apu/test_spc700.py`)

- Final registers: PC, A, X, Y, SP, PSW — `test_spc700.py:149-154`
- Final RAM, with timer-shadow special case — `test_spc700.py:156-163`
- Bus transaction sequence including `kind` (`"read"` vs `"write"`) — `test_spc700.py:134-138, 166-170`
- **Total cycle count for every opcode**, counting read+write+wait (`test_spc700.py:139, 143, 173-175`). Cycle counter is bumped in `Apu.__getitem__`, `__setitem__`, and `idle()`.

### What SPC700 tests ignore from the JSON
- Essentially nothing material. `"wait"` entries are dropped from the memory-access diff but still counted (they have no address/value to check).

## Recommended expansion work

Ranked by bug-catching value vs implementation cost:

### 1. Enable CPU cycle-count check for all opcodes
Flip `CYCLE_CHECK_OPCODES` from allowlist to full set (or drop the guard). Likely to surface real bugs: most 65816 opcodes currently have no timing validation. Expect failures — expanding the list one opcode at a time has been the historical pattern per the comment at `test_cpu.py:15`. **Change site: `test_cpu.py:207-213`.**

### 2. Verify VPB on vector-pull paths
VPB (status string position 2) asserts during the 2-byte vector fetch in BRK/COP/IRQ/NMI/RESET. Assert that any cycle whose expected status has `'v'` at index 2 corresponds to a read from a vector address — catches whole classes of interrupt-handler bugs. **Change site: extend the expected-call builder at `test_cpu.py:155-165`.**

### 3. Assert ghost-read addresses and cycle positions
Instead of `continue` at `test_cpu.py:160`, record idle cycles as `idle(addr)` markers and have the CPU emit matching markers (SPC700 already has this concept). Validates page-cross idle timing, RMW double-write timing, etc.

### 4. (Lower value) Assert M/X/E per cycle
These flags are constant across most instructions, so coverage improvement is narrow — mostly catches XCE / REP / SEP / PLP / RTI edge cases. Consider only after 1–3.

Nothing to change on the SPC700 side.

## Critical files

- `pysnes/cpu/test_cpu.py` — CPU harness (lines 15-26, 155-165, 207-213 are the expansion points)
- `pysnes/apu/test_spc700.py` — SPC700 harness (reference implementation; no changes needed)
- `pysnes/cpu/cpu.py` — may need new hooks if we add idle-cycle markers (item 3)

## Verification

For any change adopted above:

```bash
# All CPU cases, full cycle-count check:
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py -n auto --dist=loadgroup

# Single opcode, all cases, for iterating on a specific failure:
uv run --python pypy@3.10 pytest pysnes/cpu/test_cpu.py --opcode 6d --max-per-opcode 0

# Confirm SPC700 still green:
uv run --python pypy@3.10 pytest pysnes/apu/test_spc700.py -n auto --dist=loadgroup
```

Known pre-existing CPU failures: opcodes 42, 44, 54 (documented in `CLAUDE.md`) — keep those in mind when triaging new failures.
