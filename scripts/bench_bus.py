"""
Bus read/write micro-benchmark.

Run from the project root:
    uv run --python pypy3.10 scripts/bench_bus.py          # without Cython build
    make build && uv run --python pypy3.10 scripts/bench_bus.py  # with Cython build

Reports ns/op for each hot-path branch in Bus.__getitem__ / __setitem__.
"""

import timeit
import sys
from pathlib import Path

# Ensure project root is on path when running as a script
sys.path.insert(0, str(Path(__file__).parent.parent))

from pysnes.scheduler import Scheduler
from pysnes.bus import Bus
from pysnes.cpu import Cpu
from pysnes.apu import Apu
from pysnes.ppu import Ppu
from pysnes.controller import Controller
from pysnes.rom import HardwareVectors, InterruptVectors, MappingMode
from types import SimpleNamespace


ROM_SIZE = 512 * 1024


class StubRom:
    def __init__(self, size=ROM_SIZE):
        self.rom = bytearray(size)
        self.snes_header = SimpleNamespace(mapping_mode=MappingMode.LOROM)
        self.hardware_vectors = HardwareVectors(
            native=InterruptVectors(cop=0x8000, brk=0x8000, abort=0x8000,
                                    nmi=0x8000, reset=0, irq=0x8000),
            emulation=InterruptVectors(cop=0x8000, brk=0, abort=0x8000,
                                       nmi=0x8000, reset=0x8000, irq=0x8000),
        )

    def __getitem__(self, addr):
        if 0 <= addr < len(self.rom):
            return self.rom[addr]
        return 0


def make_bus():
    rom = StubRom()
    scheduler = Scheduler()
    apu = Apu()
    cpu = Cpu(rom.hardware_vectors)
    ppu = Ppu()
    controllers = [Controller(), Controller(disabled=True)]
    bus = Bus(rom, cpu, apu, ppu, controllers, scheduler)
    cpu.attach(bus)
    ppu.attach(scheduler, bus)
    return bus


ITERATIONS = 500_000
REPEAT = 3

CASES = [
    # (label, setup, stmt)
    # --- via __getitem__/__setitem__ (Python slot dispatch → thin wrapper → read/write) ---
    ("low_ram_read       []",  "",  "bus.read(0x000100)"),
    ("low_ram_write      []",  "",  "bus.__setitem__(0x000100, 0xAB)"),
    ("rom_read           []",  "",  "bus.read(0x008010)"),
    ("high_ram_read      []",  "",  "bus.read(0x7E3000)"),
    ("extended_ram_read  []",  "",  "bus.read(0x7E8000)"),
    ("rdnmi_read         []",  "",  "bus.read(0x004210)"),
    ("hvbjoy_read        []",  "",  "bus.read(0x004212)"),
    ("apu_port_read      []",  "",  "bus.read(0x002140)"),
    # --- via bus.read()/bus.write() (direct Python call into cfunc; inlined when called from Cython) ---
    ("low_ram_read    .read",  "",  "bus.read(0x000100)"),
    ("low_ram_write  .write",  "",  "bus.write(0x000100, 0xAB)"),
    ("rom_read        .read",  "",  "bus.read(0x008010)"),
    ("high_ram_read   .read",  "",  "bus.read(0x7E3000)"),
    ("extended_ram    .read",  "",  "bus.read(0x7E8000)"),
    ("rdnmi_read      .read",  "",  "bus.read(0x004210)"),
    ("hvbjoy_read     .read",  "",  "bus.read(0x004212)"),
    ("apu_port_read   .read",  "",  "bus.read(0x002140)"),
]

COL_W = 22

def run():
    bus = make_bus()
    # Pre-warm
    for _ in range(1000):
        bus.read(0x000100)
        bus.read(0x008010)

    print(f"\n{'Label':<{COL_W}}  {'ns/op':>8}  {'total ms':>10}")
    print("-" * (COL_W + 24))

    for label, setup, stmt in CASES:
        times = timeit.repeat(
            stmt=stmt,
            setup=setup,
            globals={"bus": bus},
            number=ITERATIONS,
            repeat=REPEAT,
        )
        best_s = min(times)
        ns_per_op = best_s / ITERATIONS * 1e9
        total_ms = best_s * 1000
        print(f"{label:<{COL_W}}  {ns_per_op:>8.1f}  {total_ms:>10.1f}")

    print()


if __name__ == "__main__":
    run()
