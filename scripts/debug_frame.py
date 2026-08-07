from pysnes.scheduler import Scheduler
from pysnes.rom import Rom
from pysnes.bus import Bus
from pysnes.cpu import Cpu
from pysnes.apu import Apu
from pysnes.ppu import Ppu
from pysnes.controller import Controller

rom = Rom("roms/SNES Test Program.sfc")
scheduler = Scheduler()
apu = Apu()
cpu = Cpu(rom.hardware_vectors)
ppu = Ppu()
controllers = [Controller(), Controller(disabled=True)]
bus = Bus(rom, cpu, apu, ppu, controllers, scheduler)
cpu.attach(bus)
ppu.attach(scheduler, bus)
cpu.PC.w = rom.hardware_vectors.emulation.reset

cpu.start(scheduler)
ppu.start()

MC_PER_FRAME = 262 * 1364
port_log = []

# Monkey-patch bus to log APU port accesses
_orig_get = bus.__class__.__getitem__


def _patched_get(self, abs_addr):
    val = _orig_get(self, abs_addr)
    addr = abs_addr & 0xFFFF
    if 0x2140 <= addr <= 0x2143:
        port_log.append(
            f"R ${addr:04X}={hex(val)} ports_w[{addr - 0x2140}]  CPU_PC={hex(cpu.PC.value)} A.l={hex(cpu.A.l)} MC={scheduler.master_clock}"
        )
    return val


_orig_set = bus.__class__.__setitem__


def _patched_set(self, abs_addr, data):
    addr = abs_addr & 0xFFFF
    if 0x2140 <= addr <= 0x2143:
        port_log.append(
            f"W ${addr:04X}={hex(data)}              CPU_PC={hex(cpu.PC.value)} A.l={hex(cpu.A.l)} MC={scheduler.master_clock}"
        )
    _orig_set(self, abs_addr, data)


bus.__class__.__getitem__ = _patched_get
bus.__class__.__setitem__ = _patched_set

# Run until CPU gets stuck (or 30 frames max)
for frame in range(30):
    scheduler.run_to(scheduler.master_clock + MC_PER_FRAME)

# Find where the stuck state (A.l=0x0 but port!=0x0) first occurs
print(f"Total APU port accesses: {len(port_log)}")
stuck = len(port_log)
for i, entry in enumerate(port_log):
    if (
        "R $2140=" in entry
        and "A.l=0x0 " in entry
        and "R $2140=0x0 " not in entry
    ):
        stuck = i
        break

print(f"First stuck read at entry {stuck}")
print(f"\nEntries {max(0, stuck - 10)} to {min(len(port_log), stuck + 5)}:")
for entry in port_log[max(0, stuck - 10) : min(len(port_log), stuck + 5)]:
    print(entry)

print()
print(
    f"CPU PC={hex(cpu.PC.value)}  A={hex(cpu.A.value)}  A.l={hex(cpu.A.l)}  P={hex(cpu.P):4s}"
)
print(
    f"apu.ports_r={list(apu.ports_r)}  apu.ports_w={list(apu.ports_w)}  apu.PC={hex(apu.PC)}"
)
