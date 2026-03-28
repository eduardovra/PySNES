from collections import defaultdict
import os
import json
from unittest.mock import patch

from rich import print

from .cpu.v2.cpu import Cpu as CpuV2


TESTS_PATH = "submodules/65816/v1"

# Opcodes for which cycle counts are verified (expand as coverage grows).
CYCLE_CHECK_OPCODES = {"ea", "1a", "3a", "18", "38"}

# Per-worker file cache: avoids reloading the same JSON file for every test.
_FILE_CACHE: dict = {}


def _load_case(file_path: str, index: int) -> dict:
    if file_path not in _FILE_CACHE:
        with open(file_path) as f:
            _FILE_CACHE[file_path] = json.load(f)
    return _FILE_CACHE[file_path][index]


def get_test_cases(opcode_filter=None, max_per_opcode=None, mode=None):
    """Load test cases from the SingleStepTests suite.

    opcode_filter:   optional hex prefix (e.g. "29") to restrict to one opcode.
    max_per_opcode:  max cases per opcode variant; 0 = unlimited (default: 1).
    mode:            optional "e" or "n" to restrict to emulation/native mode.
    """
    if not os.path.isdir(TESTS_PATH):
        return [], []

    limit = 1 if max_per_opcode is None else max_per_opcode
    prefix = opcode_filter.upper() if opcode_filter else None

    def _include(filename):
        # filename format: {opcode}.{mode}.json  e.g. "29.e.json"
        parts = filename.split(".")
        if len(parts) != 3 or parts[2].lower() != "json":
            return False
        if prefix is not None and not parts[0].upper().startswith(prefix):
            return False
        if mode is not None and parts[1].lower() != mode.lower():
            return False
        return True

    onlyfiles = sorted(
        os.path.join(TESTS_PATH, f) for f in os.listdir(TESTS_PATH)
        if os.path.isfile(os.path.join(TESTS_PATH, f)) and _include(f)
    )

    test_counter = defaultdict(int)

    test_cases, test_ids = [], []
    for file_path in onlyfiles:
        with open(file_path) as f:
            for i, test_case in enumerate(json.load(f)):
                test_id = test_case["name"].replace(" ", "_")

                if limit > 0 and test_counter[test_id[0:4]] >= limit:
                    continue
                test_counter[test_id[0:4]] += 1

                test_ids.append(test_id)
                test_cases.append((file_path, i))

                if len(test_cases) >= 1_000_000:
                    return test_cases, test_ids

    return test_cases, test_ids


class FakeBus:
    def __init__(self):
        self.memory = bytearray(2**24)

    def __getitem__(self, addr):
        return self.memory[addr]

    def __setitem__(self, addr, value):
        self.memory[addr] = value


def test_v2(test_case):
    file_path, index = test_case
    test_case = _load_case(file_path, index)
    cpu = CpuV2(None)
    bus = FakeBus()
    cpu.attach(bus)

    initial = test_case["initial"]
    cpu.PC.w = initial["pc"]
    cpu.A.w = initial["a"]
    cpu.X.w = initial["x"]
    cpu.Y.w = initial["y"]
    cpu.EF = bool(initial["e"])
    # In 8-bit mode (Emulation Mode): The stack pointer (S) is restricted to an 8-bit value, meaning it can only point to
    # addresses within the range $0100 to $01FF (the first 256 bytes of page 1).
    # This effectively limits the stack to 256 bytes in this mode, similar to how the 6502 operates.
    if cpu.EF:
        cpu.S.l = initial["s"]
    else:
        cpu.S.w = initial["s"]
    cpu.P = initial["p"]
    cpu.D.w = initial["d"]
    cpu.DB.l = initial["dbr"]
    cpu.PC.b = initial["pbr"]
    print(f"Loaded CPU {cpu}")
    for addr, value in initial["ram"]:
        print(f"Loading cpu.bus[{hex(addr)}] = {hex(value)}")
        cpu.bus[addr] = value

    final = test_case["final"]
    calls_expected, calls_performed = [], []
    for address, value, outputs in test_case["cycles"]:
        # The environment used does not activate RAM unless one of VDA, VPA or VPB is active,
        # therefore affected bus transactions with the read line set do not produce a value.
        # null is recorded in its place.
        if value is None:
            continue

        if outputs[3] == 'r':
            calls_expected.append(f"getitem({hex(address)}) -> {hex(value)}")
        elif outputs[3] == 'w':
            calls_expected.append(f"setitem({hex(address)}, {hex(value)})")

    real_getitem = FakeBus.__getitem__
    def getitem(self, address):
        value = real_getitem(self, address)
        calls_performed.append(f"getitem({hex(address)}) -> {hex(value)}")
        return value
    real_setitem = FakeBus.__setitem__
    def setitem(self, address, value):
        calls_performed.append(f"setitem({hex(address)}, {hex(value)})")
        return real_setitem(self, address, value)

    # mocks to track memory access
    with patch.object(FakeBus, "__getitem__", autospec=True) as mock_getitem, \
            patch.object(FakeBus, "__setitem__", autospec=True) as mock_setitem:
        mock_getitem.side_effect = getitem
        mock_setitem.side_effect = setitem
        # while cpu.PC.w != final["pc"]:  # TODO consider PBR
        while len(calls_performed) < len(calls_expected):
            cpu.fetch_and_execute()

            # safety check to avoid infinite loops
            if len(calls_performed) > 0xFFFF:
                raise Exception("Infinite loop detected")

    # check on registers and ram
    assert cpu.PC.w == final["pc"], f"{hex(cpu.PC.w)} != {hex(final['pc'])}"
    assert cpu.S.w == final["s"], f"{hex(cpu.S.w)} != {hex(final['s'])}"
    assert cpu.A.w == final["a"], f"{hex(cpu.A.w)} != {hex(final['a'])}"
    assert cpu.X.w == final['x'], f"{hex(cpu.X.w)} != {hex(final['x'])}"
    assert cpu.Y.w == final['y'], f"{hex(cpu.Y.w)} != {hex(final['y'])}"
    assert cpu.EF == bool(final['e'])
    assert cpu.P == final["p"], f"{hex(cpu.P)} != {hex(final['p'])}"
    assert cpu.D.w == final['d'], f"{hex(cpu.D.w)} != {hex(final['d'])}"
    assert cpu.DB.l == final['dbr'], f"{hex(cpu.DB.l)} != {hex(final['dbr'])}"
    assert cpu.PC.b == final['pbr'], f"{hex(cpu.PC.b)} != {hex(final['pbr'])}"
    for addr, value in final["ram"]:
        assert cpu.bus[addr] == value, f"cpu.bus[{hex(addr)}] = {hex(cpu.bus[addr])} != {hex(value)}"

    # check on read/write cycles
    assert calls_performed == calls_expected

    # cycle count check (only for opcodes in CYCLE_CHECK_OPCODES)
    opcode_name = test_case["name"].split()[0].lower()
    if opcode_name in CYCLE_CHECK_OPCODES:
        expected_cycle_count = len(test_case["cycles"])
        assert cpu.icycles == expected_cycle_count, (
            f"cycle count: {cpu.icycles} != {expected_cycle_count}"
        )


# VP == VPB

r"""
=====================
Appendix C: IC Pinouts
=====================

           /=============\                     /=============\
       VP  I1          40I RES            Vss  I1          40I RES
      RDY  I2          39I VDA            RDY  I2          39I o2 (OUT)
    ABORT  I3          38I M/X       o1 (OUT)  I3          38I SO
      IRQ  I4          37I o2 (IN)        IRQ  I4          37I o2 (IN)
       ML  I5          36I BE              NC  I5          36I NC
      NMI  I6          35I E              NMI  I6          35I NC
      VPA  I7          34I R/W           SYNC  I7          34I R/W
      VDD  I8          33I D0/BA0         Vdd  I8          33I D0
       A0  I9  W65C816 32I D1/BA1          A0  I9   6502   32I D1
       A1  I10         31I D2/BA2          A1  I10         31I D2
       A2  I11         30I D3/BA3          A2  I11         30I D3
       A3  I12         29I D4/BA4          A3  I12         29I D4
       A4  I13         28I D5/BA5          A4  I13         28I D5
       A5  I14         27I D6/BA6          A5  I14         27I D6
       A6  I15         26I D7/BA7          A6  I15         26I D7
       A7  I16         25I A15             A7  I16         25I A15
       A8  I17         24I A14             A8  I17         24I A14
       A9  I18         23I A13             A9  I18         23I A13
      A10  I19         22I A12            A10  I19         22I A12
      A11  I20         21I Vss            A11  I20         21I Vss
           \=============/                     \=============/

Notes:
   ML: Memory Lock line (pin 5) is asserted low during the execution of
       the read-modify-write (asl,dec,inc,lsr,rol,ror,trb, and tsb
       instructions to inform other ics that the bus may not be claimed
       yet.

   VP: Vector Pull is asserted whenever any of the hardware vector
       address's are being accessed during an IRQ.

 Abort:  An input.  When asserted caused the current instruction to be
         aborted.

   VPA/VDA.  Valid Program Address and Valid Data Address.  These two
             signals extend on the 6502 SYNC line - to better handle
             DMA schemes.

       VPA   VDA
        0     0  -Internal Operation
        0     1  -Valid program address
        1     0  -Valid data address
        1     1  -Opcode fetch


    M/X: Memory and Index lines.  These signals are multiplexed on pin
         38.  M is available during phase zero and X during Phase one.
         These two signals reflect the contents of the status register
         m and x flags, allowing other devices to decode opcode fetches.

    E: Emulation pin.  This signal reflects the state of the processors
       emulation bit (E).
"""
