"""Deterministic CPU dispatch micro-benchmark.

Runs a tight loop of indexed read/write instructions (the addressing modes most
exercised in-game) through the real fetch_and_execute path, so dispatch-layer
changes can be measured without scene/JIT/OS noise.
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from types import SimpleNamespace
from pysnes.scheduler import Scheduler
from pysnes.bus import Bus
from pysnes.cpu import Cpu
from pysnes.apu import Apu
from pysnes.ppu import Ppu
from pysnes.controller import Controller
from pysnes.rom import HardwareVectors, InterruptVectors, MappingMode

# Program at LoROM bank0 $8000 (rom offset 0): a loop of indexed mem ops.
#   BD 00 10  LDA $1000,X     (BankRead, i=X)
#   9D 00 10  STA $1000,X     (BankWrite, i=X)
#   B5 20     LDA $20,X       (DirectRead, i=X)
#   95 20     STA $20,X       (DirectWrite, i=X)
#   80 F4     BRA -12         (loop to start)
PROGRAM = bytes([0xBD, 0x00, 0x10, 0x9D, 0x00, 0x10, 0xB5, 0x20, 0x95, 0x20, 0x80, 0xF4])


class StubRom:
    def __init__(self, size=512 * 1024):
        self.rom = bytearray(size)
        self.rom[0:len(PROGRAM)] = PROGRAM
        self.snes_header = SimpleNamespace(mapping_mode=MappingMode.LOROM)
        self.hardware_vectors = HardwareVectors(
            native=InterruptVectors(cop=0x8000, brk=0x8000, abort=0x8000, nmi=0x8000, reset=0x8000, irq=0x8000),
            emulation=InterruptVectors(cop=0x8000, brk=0x8000, abort=0x8000, nmi=0x8000, reset=0x8000, irq=0x8000),
        )

    def __getitem__(self, addr):
        return self.rom[addr] if 0 <= addr < len(self.rom) else 0

    def read(self, addr):
        return self.rom[addr] if 0 <= addr < len(self.rom) else 0


def make_cpu():
    rom = StubRom()
    sched = Scheduler()
    cpu = Cpu(rom.hardware_vectors)
    bus = Bus(rom, cpu, Apu(), Ppu(), [Controller(), Controller(disabled=True)], sched)
    cpu.attach(bus)
    cpu.PC.d = 0x008000
    cpu.EF = False           # native mode
    cpu.MFlag = False        # 16-bit A
    cpu.XFlag = False        # 16-bit X/Y
    cpu.DB.value = 0x00
    cpu.D.value = 0x0000
    cpu.X.value = 0x0000
    return cpu


def install_fused(cpu):
    """Replace the 4 benchmark opcodes with fully-fused, monomorphic handlers
    (no .MF wrapper, no string arg, no nargs branch) to measure the theoretical
    dispatch ceiling. Logic mirrors BankRead/DirectRead/BankWrite/DirectWrite
    with index=X exactly (same idle cycles)."""
    from pysnes.cpu.cpu import InstructionSlot
    from pysnes.cpu.wdc65816 import opcodes as OP
    LDA = OP.LDA

    def lda_abs_x(cpu):
        cpu.V.l = cpu.fetch(); cpu.V.h = cpu.fetch()
        cpu.idle4(cpu.V.w, cpu.V.w + cpu.X.w)
        if cpu.MFlag:
            cpu.W.l = cpu.readBank(cpu.V.w + cpu.X.w + 0)
            LDA(cpu, True, cpu.W.l)
        else:
            cpu.W.l = cpu.readBank(cpu.V.w + cpu.X.w + 0)
            cpu.W.h = cpu.readBank(cpu.V.w + cpu.X.w + 1)
            LDA(cpu, False, cpu.W.w)

    def sta_abs_x(cpu):
        cpu.V.l = cpu.fetch(); cpu.V.h = cpu.fetch(); cpu.idle()
        if cpu.MFlag:
            cpu.writeBank(cpu.V.w + cpu.X.w + 0, cpu.A.l)
        else:
            cpu.writeBank(cpu.V.w + cpu.X.w + 0, cpu.A.l)
            cpu.writeBank(cpu.V.w + cpu.X.w + 1, cpu.A.h)

    def lda_dp_x(cpu):
        cpu.U.l = cpu.fetch(); cpu.idle2(); cpu.idle()
        if cpu.MFlag:
            cpu.W.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
            LDA(cpu, True, cpu.W.l)
        else:
            cpu.W.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
            cpu.W.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1)
            LDA(cpu, False, cpu.W.w)

    def sta_dp_x(cpu):
        cpu.U.l = cpu.fetch(); cpu.idle2(); cpu.idle()
        if cpu.MFlag:
            cpu.writeDirect(cpu.U.l + cpu.X.w + 0, cpu.A.l)
        else:
            cpu.writeDirect(cpu.U.l + cpu.X.w + 0, cpu.A.l)
            cpu.writeDirect(cpu.U.l + cpu.X.w + 1, cpu.A.h)

    cpu.instructions[0xBD] = InstructionSlot(lda_abs_x, nargs=0)
    cpu.instructions[0x9D] = InstructionSlot(sta_abs_x, nargs=0)
    cpu.instructions[0xB5] = InstructionSlot(lda_dp_x, nargs=0)
    cpu.instructions[0x95] = InstructionSlot(sta_dp_x, nargs=0)


def install_closure(cpu):
    """Clean closure-factory version: op/index/flag captured as freevars, with
    branches the JIT may or may not fold. This is the readable implementation
    candidate — compare it to the literal 'fused' ceiling."""
    from pysnes.cpu.cpu import InstructionSlot
    from pysnes.cpu.wdc65816 import opcodes as OP
    LDA = OP.LDA

    # Per-(mode,index) factory: ONLY the operation is a freevar; index register
    # and memory accessor are baked as literals (monomorphic body, no branches
    # on captured constants). This is the clean factory we'd ship if it's fast.
    def bank_read_x(op, xflag=False):
        def execute(cpu):
            cpu.V.l = cpu.fetch(); cpu.V.h = cpu.fetch()
            cpu.idle4(cpu.V.w, cpu.V.w + cpu.X.w)
            if (cpu.XFlag if xflag else cpu.MFlag):
                cpu.W.l = cpu.readBank(cpu.V.w + cpu.X.w + 0); op(cpu, True, cpu.W.l)
            else:
                cpu.W.l = cpu.readBank(cpu.V.w + cpu.X.w + 0)
                cpu.W.h = cpu.readBank(cpu.V.w + cpu.X.w + 1); op(cpu, False, cpu.W.w)
        return execute

    def direct_read_x(op):
        def execute(cpu):
            cpu.U.l = cpu.fetch(); cpu.idle2(); cpu.idle()
            if cpu.MFlag:
                cpu.W.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0); op(cpu, True, cpu.W.l)
            else:
                cpu.W.l = cpu.readDirect(cpu.U.l + cpu.X.w + 0)
                cpu.W.h = cpu.readDirect(cpu.U.l + cpu.X.w + 1); op(cpu, False, cpu.W.w)
        return execute

    def sta_abs_x():
        def execute(cpu):
            cpu.V.l = cpu.fetch(); cpu.V.h = cpu.fetch(); cpu.idle()
            if cpu.MFlag:
                cpu.writeBank(cpu.V.w + cpu.X.w + 0, cpu.A.l)
            else:
                cpu.writeBank(cpu.V.w + cpu.X.w + 0, cpu.A.l)
                cpu.writeBank(cpu.V.w + cpu.X.w + 1, cpu.A.h)
        return execute

    def sta_dp_x():
        def execute(cpu):
            cpu.U.l = cpu.fetch(); cpu.idle2(); cpu.idle()
            if cpu.MFlag:
                cpu.writeDirect(cpu.U.l + cpu.X.w + 0, cpu.A.l)
            else:
                cpu.writeDirect(cpu.U.l + cpu.X.w + 0, cpu.A.l)
                cpu.writeDirect(cpu.U.l + cpu.X.w + 1, cpu.A.h)
        return execute

    cpu.instructions[0xBD] = InstructionSlot(bank_read_x(LDA), nargs=0)
    cpu.instructions[0x9D] = InstructionSlot(sta_abs_x(), nargs=0)
    cpu.instructions[0xB5] = InstructionSlot(direct_read_x(LDA), nargs=0)
    cpu.instructions[0x95] = InstructionSlot(sta_dp_x(), nargs=0)


def install_writeclosure(cpu):
    """DRY write factory: source register name as a freevar (resolved per call).
    Measures whether the compact version is fast enough vs literal variants."""
    from pysnes.cpu.cpu import InstructionSlot

    def bank_write(src, index="", xflag=False):
        def execute(cpu):
            cpu.V.l = cpu.fetch(); cpu.V.h = cpu.fetch()
            if index:
                cpu.idle()
            iw = cpu.X.w if index == "X" else (cpu.Y.w if index == "Y" else 0)
            S = cpu.A if src == "A" else (cpu.X if src == "X" else (cpu.Y if src == "Y" else cpu.Z))
            if (cpu.XFlag if xflag else cpu.MFlag):
                cpu.writeBank(cpu.V.w + iw + 0, S.l)
            else:
                cpu.writeBank(cpu.V.w + iw + 0, S.l)
                cpu.writeBank(cpu.V.w + iw + 1, S.h)
        return execute

    def direct_write(src, index="", xflag=False):
        def execute(cpu):
            cpu.U.l = cpu.fetch(); cpu.idle2()
            if index:
                cpu.idle()
            iw = cpu.X.w if index == "X" else (cpu.Y.w if index == "Y" else 0)
            S = cpu.A if src == "A" else (cpu.X if src == "X" else (cpu.Y if src == "Y" else cpu.Z))
            if (cpu.XFlag if xflag else cpu.MFlag):
                cpu.writeDirect(cpu.U.l + iw + 0, S.l)
            else:
                cpu.writeDirect(cpu.U.l + iw + 0, S.l)
                cpu.writeDirect(cpu.U.l + iw + 1, S.h)
        return execute

    cpu.instructions[0x9D] = InstructionSlot(bank_write("A", "X"), nargs=0)
    cpu.instructions[0x95] = InstructionSlot(direct_write("A", "X"), nargs=0)


def run(cpu, n):
    fae = cpu.fetch_and_execute
    for _ in range(n):
        fae()


def main():
    n = next((int(a) for a in sys.argv[1:] if a.isdigit()), 400_000)
    cpu = make_cpu()
    if "--fused" in sys.argv:
        install_fused(cpu)
    elif "--closure" in sys.argv:
        install_closure(cpu)
    elif "--writeclosure" in sys.argv:
        install_writeclosure(cpu)
    run(cpu, 100_000)  # warmup
    best = 1e9
    for _ in range(5):
        t0 = time.perf_counter()
        run(cpu, n)
        best = min(best, (time.perf_counter() - t0) / n * 1e9)
    print(f"PC=0x{cpu.PC.d:06X} (looping ok)  ->  {best:.1f} ns/instruction (best of 5)")


if __name__ == "__main__":
    main()
