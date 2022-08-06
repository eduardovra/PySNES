import os
import json
from unittest.mock import call, patch, Mock

import pytest
from rich import print

from .cpu import Cpu
from .bus import Bus
from .apu import Apu
from .ppu import Ppu
from .rom import Rom
from .controller import Controller


TESTS_PATH = "ProcessorTests/65816/v1"

def get_test_cases():
    onlyfiles = [
        os.path.join(TESTS_PATH, f) for f in os.listdir(TESTS_PATH)
        if os.path.isfile(os.path.join(TESTS_PATH, f)) #and f == 'ea.n.json'  # EA -> NOP
    ]

    test_cases, test_ids = [], []
    for file_path in onlyfiles:
        print(file_path)
        with open(file_path) as f:
            for test_case in json.load(f):
                test_ids.append(test_case["name"])
                test_cases.append(test_case)
                if len(test_cases) >= 10:
                    return test_cases, test_ids

    return test_cases, test_ids


TEST_CASES, TEST_IDS = get_test_cases()


@pytest.mark.parametrize('test_case', TEST_CASES, ids=TEST_IDS)
def test(test_case):
    hardware_vectors = {"emulation": {"RESET": 0}}
    rom = Rom("roms/Super Mario World (U) [!].smc")
    cpu = Cpu(hardware_vectors)
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
    p = Cpu.StatusRegister()
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
    def getitem(*args, **kwargs):
        data = real_getitem(*args, **kwargs)
        calls_performed.append(f"getitem({args}) -> {data}")
        return data
    real_setitem = Bus.__setitem__
    def setitem(*args, **kwargs):
        calls_performed.append(f"settitem({args})")
        return real_setitem(*args, **kwargs)

    print("\nInitiating test")
    with patch.object(Bus, "__getitem__", autospec=True) as mock_getitem, \
            patch.object(Bus, "__setitem__", autospec=True) as mock_setitem:
        mock_getitem.side_effect = getitem
        mock_setitem.side_effect = setitem
        while cpu.PC != final["pc"]:
            cpu.fetch_and_execute()

    calls_expected = []
    for address, value, outputs in test_case["cycles"]:
        if outputs[3] == 'r':
            calls_expected.append(f"getitem({address}) -> {value}")
        elif outputs[3] == 'w':
            calls_expected.append(f"setitem({address}, {value})")

    assert calls_performed == calls_expected

    #assert mock_getitem.mock_calls == [
    #    call(bus, 14005826),
    #    call(bus, 46659),
    #    call(bus, 46660),
    #]

    # TODO check on registers and ram
    assert cpu.PC == final["pc"]
    assert cpu.S == final["s"]
    assert cpu.A == final["a"]
    assert cpu.X == final['x']
    assert cpu.Y == final['y']
    assert cpu.emulation == final['e']
    p = Cpu.StatusRegister()
    p.set(initial["p"], cpu.emulation)
    assert cpu.P.get(cpu.emulation) == p.get(cpu.emulation)
    assert cpu.D == final['d']
    assert cpu.DB == final['dbr']
    assert cpu.PB == final['pbr']
    print("\nChecking on memory")
    for addr, value in final["ram"]:
        assert cpu.bus[addr] == value

    # TODO intercept memory access calls (using mock?) and compare with data["cycles"]
