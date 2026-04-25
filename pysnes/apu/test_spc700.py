"""
SPC700 instruction tests using the SingleStepTests suite.

Each test case from the JSON files specifies:
  initial  — register values and RAM contents before execution
  final    — expected register values and RAM after execution
  cycles   — expected memory accesses (read/write) and internal waits

Mirrors the structure of test_cpu.py for the WDC65816.

Test data: submodules/SingleStepTests_spc700/v1/
"""

import os
import ijson
import pytest
from collections import defaultdict

from .apu import Apu
from pysnes._ss_cache import get_or_build


TESTS_PATH = "submodules/SingleStepTests_spc700/v1"

_FILE_CACHE_KEY: str | None = None
_FILE_CACHE_VAL: list | None = None


def _load_case(file_path: str, index: int) -> dict:
    global _FILE_CACHE_KEY, _FILE_CACHE_VAL
    if _FILE_CACHE_KEY != file_path:
        with open(file_path, 'rb') as f:
            _FILE_CACHE_VAL = list(ijson.items(f, 'item'))
        _FILE_CACHE_KEY = file_path
    return _FILE_CACHE_VAL[index]


def _write_mem(apu: Apu, addr: int, value: int) -> None:
    """Write directly to APU backing memory, bypassing I/O side-effects."""
    if addr <= 0x00EF:
        apu.page_0[addr] = value
    elif addr <= 0x00FF:
        # I/O register range — use __setitem__ (which mirrors port writes to
        # ports_r so the APU can read back what was initialised here).
        apu[addr] = value
    elif addr <= 0x01FF:
        apu.page_1[addr - 0x0100] = value
    elif addr <= 0xFFBF:
        apu.memory[addr - 0x0200] = value
    else:
        # 0xFFC0–0xFFFF: IPL ROM range — make writable and disable ROM overlay
        if isinstance(apu.ipl_rom, (bytes, bytearray)):
            apu.ipl_rom = bytearray(apu.ipl_rom)
        apu.ipl_rom[addr - 0xFFC0] = value
        apu.ipl_rom_enable = False


def _parse_test_index(opcode_filter, max_per_opcode, mode):
    limit = 1 if max_per_opcode is None else max_per_opcode
    prefix = opcode_filter.lower() if opcode_filter else None
    onlyfiles = sorted(
        os.path.join(TESTS_PATH, f)
        for f in os.listdir(TESTS_PATH)
        if os.path.isfile(os.path.join(TESTS_PATH, f))
        and f.lower().endswith(".json")
        and (prefix is None or f.lower().startswith(prefix))
    )

    test_counter = defaultdict(int)
    params, test_ids = [], []

    for file_path in onlyfiles:
        with open(file_path, 'rb') as f:
            for i, name in enumerate(ijson.items(f, 'item.name')):
                test_id = name.replace(" ", "_")
                if limit > 0 and test_counter[test_id[:2]] >= limit:
                    continue
                test_counter[test_id[:2]] += 1
                test_ids.append(test_id)
                params.append((file_path, i))
                if len(params) >= 1_000_000:
                    return params, test_ids

    return params, test_ids


def get_test_cases(opcode_filter=None, max_per_opcode=None, mode=None):
    """Load SPC700 test cases.

    opcode_filter:   optional hex prefix (e.g. "00") to restrict to one opcode.
    max_per_opcode:  max cases per opcode variant; 0 = unlimited (default: 1).
    mode:            ignored (SPC700 has no emulation/native distinction).
    """
    if not os.path.isdir(TESTS_PATH):
        return [], []

    filter_args = (opcode_filter, max_per_opcode, mode)
    raw_params, test_ids = get_or_build(
        "spc700",
        TESTS_PATH,
        filter_args,
        lambda: _parse_test_index(opcode_filter, max_per_opcode, mode),
    )
    test_cases = [
        pytest.param(rp, marks=pytest.mark.xdist_group(rp[0])) for rp in raw_params
    ]
    return test_cases, test_ids


def test_spc700(test_case):
    file_path, index = test_case
    test_case = _load_case(file_path, index)
    apu = Apu()

    # ── Load initial state ────────────────────────────────────────────────
    initial = test_case["initial"]
    for addr, value in initial["ram"]:
        _write_mem(apu, addr, value)

    apu.PC = initial["pc"]
    apu.A  = initial["a"]
    apu.X  = initial["x"]
    apu.Y  = initial["y"]
    apu.S  = initial["sp"]
    apu.PSW = initial["psw"]

    # ── Build expected cycle sequence ────────────────────────────────────
    # Cycles: [address, value, "read"/"write"/"wait"]
    # "wait" entries are internal cycles (no memory transaction).
    # Entries with null value are ghost reads the hardware performs but whose
    # value is discarded; they count toward the cycle total but are excluded
    # from the memory-access sequence check (same convention as the 65816 tests).
    expected_cycles = test_case["cycles"]
    expected_mem = [
        (addr, value, kind)
        for addr, value, kind in expected_cycles
        if kind in ("read", "write") and addr is not None and value is not None
    ]
    expected_cycle_count = len(expected_cycles)

    apu._mem_log = []
    apu.fetch_and_execute()
    actual_cycle_count = apu.cycles
    performed_mem = list(apu._mem_log)
    apu._mem_log = None

    # ── Verify final register state ───────────────────────────────────────
    final = test_case["final"]
    assert apu.PC  == final["pc"],  f"PC:  {hex(apu.PC)}  != {hex(final['pc'])}"
    assert apu.A   == final["a"],   f"A:   {hex(apu.A)}   != {hex(final['a'])}"
    assert apu.X   == final["x"],   f"X:   {hex(apu.X)}   != {hex(final['x'])}"
    assert apu.Y   == final["y"],   f"Y:   {hex(apu.Y)}   != {hex(final['y'])}"
    assert apu.S   == final["sp"],  f"SP:  {hex(apu.S)}   != {hex(final['sp'])}"
    assert apu.PSW == final["psw"], f"PSW: {hex(apu.PSW)} != {hex(final['psw'])}"

    for addr, value in final["ram"]:
        # 0xFD-0xFF are timer counters that clear on read; use the shadow
        # (last-read/written value) to avoid a second clear-on-read here.
        if 0xFD <= addr <= 0xFF:
            got = apu.timers[addr - 0xFD].stage3_shadow
        else:
            got = apu[addr]
        assert got == value, f"ram[{hex(addr)}] = {hex(got)} != {hex(value)}"

    # ── Verify memory access sequence and total cycle count ──────────────
    assert performed_mem == expected_mem, (
        f"Memory accesses differ:\n"
        f"  expected: {expected_mem}\n"
        f"  got:      {performed_mem}"
    )
    # apu.cycles is incremented by every __getitem__, __setitem__, and idle()
    # call, giving the full instruction cycle count including internal waits.
    assert actual_cycle_count == expected_cycle_count, (
        f"Cycle count: got {actual_cycle_count}, expected {expected_cycle_count}"
    )
