import os
import json

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
    locations = [1]
    # query locations
    #...
    return locations

TEST_CASES = get_test_cases()


@pytest.mark.parametrize('test_case', TEST_CASES)
def test(test_case):
    hardware_vectors = {"emulation": {"RESET": 0}}
    rom = Rom("roms/Super Mario World (U) [!].smc")
    cpu = Cpu(hardware_vectors)
    apu = Apu()
    ppu = Ppu(cpu)  # Pass CPU reference so PPU can control the NMI line
    bus = Bus(rom, cpu, apu, ppu, [Controller(), Controller()])
    cpu.attach(bus)

    onlyfiles = [
        os.path.join(TESTS_PATH, f) for f in os.listdir(TESTS_PATH)
        if os.path.isfile(os.path.join(TESTS_PATH, f)) #and f == 'ea.n.json'  # EA -> NOP
    ]
    for file_path in onlyfiles:
        print(file_path)
        with open(file_path) as f:
            data = json.load(f)[0]
            print(data)
            initial = data["initial"]
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

            final = data["final"]

            print("\nInitiating test")
            while True:
                cpu.fetch_and_execute()
                #print(f"pc={cpu.PC}")
                if cpu.PC == final["pc"]:
                    break

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


            #break

    assert False
