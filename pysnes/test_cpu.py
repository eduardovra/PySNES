import os
import json
from unittest.mock import call, patch, Mock

import pytest
from rich import print

from .cpu.v1.cpu import Cpu as CpuV1
from .cpu.v2.cpu import Cpu as CpuV2



TESTS_PATH = "ProcessorTests/65816/v1"

def get_test_cases():
    onlyfiles = [
        os.path.join(TESTS_PATH, f) for f in os.listdir(TESTS_PATH)
        if os.path.isfile(os.path.join(TESTS_PATH, f)) #and f.upper().startswith('A0')  # EA -> NOP, 29 -> AND, A0 -> LDY
    ]

    test_cases, test_ids = [], []
    for file_path in onlyfiles:
        with open(file_path) as f:
            for test_case in json.load(f):
                test_ids.append(test_case["name"].replace(" ", "_"))
                test_cases.append(test_case)
                if len(test_cases) >= 1000000:
                    return test_cases, test_ids

    return test_cases, test_ids


TEST_CASES, TEST_IDS = get_test_cases()


class FakeBus:
    def __init__(self):
        self.memory = bytearray(2**24)

    def __getitem__(self, addr):
        return self.memory[addr]

    def __setitem__(self, addr, value):
        self.memory[addr] = value


@pytest.mark.parametrize('test_case', TEST_CASES, ids=TEST_IDS)
def test_v2(test_case):
    cpu = CpuV2()
    bus = FakeBus()
    cpu.attach(bus)

    initial = test_case["initial"]
    cpu.PC.w = initial["pc"]
    cpu.S.w = initial["s"]
    cpu.A.w = initial["a"]
    cpu.X.w = initial["x"]
    cpu.Y.w = initial["y"]
    cpu.EF = bool(initial["e"])
    cpu.P = initial["p"]
    cpu.D.w = initial["d"]
    cpu.DB.l = initial["dbr"]
    cpu.PB.l = initial["pbr"]
    #print("Loading ram values")
    for addr, value in initial["ram"]:
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
            calls_expected.append(f"getitem({address}) -> {value}")
        elif outputs[3] == 'w':
            calls_expected.append(f"setitem({address}, {value})")

    real_getitem = FakeBus.__getitem__
    def getitem(self, address):
        value = real_getitem(self, address)
        calls_performed.append(f"getitem({address}) -> {value}")
        return value
    real_setitem = FakeBus.__setitem__
    def setitem(self, address, value):
        calls_performed.append(f"settitem({address}, {value})")
        return real_setitem(self, address, value)

    #print("\nInitiating test")
    with patch.object(FakeBus, "__getitem__", autospec=True) as mock_getitem, \
            patch.object(FakeBus, "__setitem__", autospec=True) as mock_setitem:
        mock_getitem.side_effect = getitem
        mock_setitem.side_effect = setitem
        while cpu.PC.w != final["pc"]:  # TODO consider PBR
            cpu.fetch_and_execute()

    # check on registers and ram
    assert cpu.PC.w == final["pc"]
    assert cpu.S.w == final["s"]
    assert cpu.A.w == final["a"]
    assert cpu.X.w == final['x']
    assert cpu.Y.w == final['y']
    assert cpu.EF == bool(final['e'])
    assert cpu.P == final["p"]
    assert cpu.D.w == final['d']
    assert cpu.DB.l == final['dbr']
    assert cpu.PB.l == final['pbr']
    #print("\nChecking on memory")
    for addr, value in final["ram"]:
        assert cpu.bus[addr] == value

    # check on read/write cycles
    assert calls_performed == calls_expected


@pytest.mark.parametrize('test_case', TEST_CASES, ids=TEST_IDS)
def test_v1(test_case):
    from .bus import Bus
    from .apu import Apu
    from .ppu import Ppu
    from .rom import Rom
    from .controller import Controller

    hardware_vectors = {"emulation": {"RESET": 0}}
    rom = Rom("roms/Super Mario World (U) [!].smc")
    cpu = CpuV1(hardware_vectors)
    apu = Apu()
    ppu = Ppu(cpu)  # Pass CPU reference so PPU can control the NMI line
    bus = Bus(rom, cpu, apu, ppu, [Controller(), Controller()])
    cpu.attach(bus)

    #print(test_case)
    initial = test_case["initial"]
    cpu.PC = initial["pc"]
    cpu.S = initial["s"]
    cpu.A = initial["a"]
    cpu.X = initial["x"]
    cpu.Y = initial["y"]
    cpu.emulation = initial["e"]
    p = CpuV1.StatusRegister()
    p.set(initial["p"], cpu.emulation)
    cpu.P = p
    cpu.D = initial["d"]
    cpu.DB = initial["dbr"]
    cpu.PB = initial["pbr"]
    print("Loading ram values")
    for addr, value in initial["ram"]:
        cpu.bus[addr] = value

    final = test_case["final"]

    calls_performed = []

    real_getitem = Bus.__getitem__
    def getitem(self, address):
        value = real_getitem(self, address)
        calls_performed.append(f"getitem({address}) -> {value}")
        return value
    real_setitem = Bus.__setitem__
    def setitem(self, address, value):
        calls_performed.append(f"settitem({address}, {value})")
        return real_setitem(self, address, value)

    print("\nInitiating test")
    with patch.object(Bus, "__getitem__", autospec=True) as mock_getitem, \
            patch.object(Bus, "__setitem__", autospec=True) as mock_setitem:
        mock_getitem.side_effect = getitem
        mock_setitem.side_effect = setitem
        while cpu.PC != final["pc"]:
            cpu.fetch_and_execute()

    # check on registers and ram
    assert cpu.PC == final["pc"]
    assert cpu.S == final["s"]
    assert cpu.A == final["a"]
    assert cpu.X == final['x']
    assert cpu.Y == final['y']
    assert cpu.emulation == final['e']
    p = CpuV1.StatusRegister()
    p.set(initial["p"], cpu.emulation)
    assert cpu.P.get(cpu.emulation) == p.get(cpu.emulation)
    assert cpu.D == final['d']
    assert cpu.DB == final['dbr']
    assert cpu.PB == final['pbr']
    print("\nChecking on memory")
    for addr, value in final["ram"]:
        assert cpu.bus[addr] == value

    # check on read/write cycles
    calls_expected = []
    for address, value, outputs in test_case["cycles"]:
        # The environment used does not activate RAM unless one of VDA, VPA or VPB is active,
        # therefore affected bus transactions with the read line set do not produce a value.
        # null is recorded in its place.
        if value is None:
            continue

        if outputs[3] == 'r':
            calls_expected.append(f"getitem({address}) -> {value}")
        elif outputs[3] == 'w':
            calls_expected.append(f"setitem({address}, {value})")

    assert calls_performed == calls_expected


# VP == VPB

"""
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