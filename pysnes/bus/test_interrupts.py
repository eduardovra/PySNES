"""
Interrupt unit tests (NMI / IRQ).

Covers:
  - NMITIMEN ($4200) NMI enable/disable, HIRQ/VIRQ enable
  - NMI rising-edge behaviour: pending flag set only when enabled
  - Immediate NMI trigger when enabling while nmi_line is already high
  - RDNMI ($4210) read clears nmi_line
  - CPU _nmi_pending → execute NMI handler in fetch_and_execute loop
  - IRQ enable flags stored correctly
"""

import pytest

from ..scheduler import Scheduler
from .bus import Bus
from ..cpu import Cpu
from ..apu import Apu
from ..ppu import Ppu
from ..controller import Controller
from ..rom import HardwareVectors, InterruptVectors


# ---------------------------------------------------------------------------
# Helpers (shared with other test modules)
# ---------------------------------------------------------------------------

ROM_SIZE = 512 * 1024


class StubRom:
    def __init__(self, size=ROM_SIZE):
        self.rom = bytearray(size)
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
    return bus, cpu


# ---------------------------------------------------------------------------
# NMITIMEN ($4200) — NMI enable / disable
# ---------------------------------------------------------------------------

def test_nmitimen_enables_nmi():
    bus, cpu = make_bus()
    bus[0x004200] = 0x80
    assert cpu.status.nmi_enable is True


def test_nmitimen_disables_nmi():
    bus, cpu = make_bus()
    bus[0x004200] = 0x80
    bus[0x004200] = 0x00
    assert cpu.status.nmi_enable is False


def test_nmitimen_hirq_enable():
    bus, cpu = make_bus()
    bus[0x004200] = 0x10
    assert cpu.status.hirq_enable is True
    assert cpu.status.irq_enable is True


def test_nmitimen_virq_enable():
    bus, cpu = make_bus()
    bus[0x004200] = 0x20
    assert cpu.status.virq_enable is True
    assert cpu.status.irq_enable is True


def test_nmitimen_hirq_and_virq_both_set_irq_enable():
    bus, cpu = make_bus()
    bus[0x004200] = 0x30
    assert cpu.status.irq_enable is True


def test_nmitimen_neither_hirq_nor_virq_clears_irq_enable():
    bus, cpu = make_bus()
    bus[0x004200] = 0x30
    bus[0x004200] = 0x00
    assert cpu.status.irq_enable is False


def test_nmitimen_auto_joypad_read_enable():
    bus, cpu = make_bus()
    bus[0x004200] = 0x01
    assert cpu.status.auto_joypad_read_enable is True


# ---------------------------------------------------------------------------
# NMI rising-edge behaviour
# ---------------------------------------------------------------------------

def test_nmi_rising_edge_sets_pending_when_enabled():
    bus, cpu = make_bus()
    bus[0x004200] = 0x80          # enable NMI
    cpu.nmi_rising_edge()
    assert cpu._nmi_pending is True


def test_nmi_rising_edge_does_not_set_pending_when_disabled():
    bus, cpu = make_bus()
    # NMI disabled by default
    cpu.nmi_rising_edge()
    assert cpu._nmi_pending is False


def test_nmi_enable_with_line_already_high_triggers_immediately():
    """Enabling NMI while nmi_line is already asserted triggers a rising edge."""
    bus, cpu = make_bus()
    cpu.status.nmi_line = True
    # Writing 0x80 to NMITIMEN while nmi_line is high should trigger immediately
    bus[0x004200] = 0x80
    assert cpu._nmi_pending is True


def test_nmi_enable_with_line_low_does_not_trigger():
    bus, cpu = make_bus()
    cpu.status.nmi_line = False
    bus[0x004200] = 0x80
    assert cpu._nmi_pending is False


def test_raise_nmi_sets_nmi_line():
    bus, cpu = make_bus()
    bus[0x004200] = 0x80
    bus.raise_nmi()
    assert cpu.status.nmi_line is True


def test_lower_nmi_clears_nmi_line():
    bus, cpu = make_bus()
    bus.raise_nmi()
    bus.lower_nmi()
    assert cpu.status.nmi_line is False


# ---------------------------------------------------------------------------
# RDNMI ($4210)
# ---------------------------------------------------------------------------

def test_rdnmi_read_clears_nmi_line():
    bus, cpu = make_bus()
    cpu.status.nmi_line = True
    _ = bus[0x004210]
    assert cpu.status.nmi_line is False


def test_rdnmi_read_while_line_low_leaves_it_low():
    bus, cpu = make_bus()
    cpu.status.nmi_line = False
    _ = bus[0x004210]
    assert cpu.status.nmi_line is False


def test_rdnmi_bit7_reflects_nmi_line():
    bus, cpu = make_bus()
    cpu.status.nmi_line = True
    val = bus[0x004210]
    assert val & 0x80


def test_rdnmi_bit7_clear_when_line_low():
    bus, cpu = make_bus()
    cpu.status.nmi_line = False
    val = bus[0x004210]
    assert not (val & 0x80)


# ---------------------------------------------------------------------------
# TIMEUP / IRQ state
# ---------------------------------------------------------------------------

def test_irq_flags_independent_of_nmi():
    """Setting HIRQ enable must not disturb NMI enable and vice versa."""
    bus, cpu = make_bus()
    bus[0x004200] = 0x80  # NMI only
    assert cpu.status.nmi_enable is True
    assert cpu.status.hirq_enable is False
    assert cpu.status.irq_enable is False

    bus[0x004200] = 0x10  # HIRQ only
    assert cpu.status.nmi_enable is False
    assert cpu.status.hirq_enable is True
    assert cpu.status.irq_enable is True


# ---------------------------------------------------------------------------
# interrupt() cycle counting
# ---------------------------------------------------------------------------

def test_interrupt_advances_cycles_native_mode():
    """interrupt() must count bus cycles (not return a flat 1 MC)."""
    bus, cpu = make_bus()
    cpu.EF = False  # native mode: 8 bus cycles (2 idle + push PBR/PCH/PCL/P + 2 vector reads)
    cpu.S.w = 0x01FF
    cycles_before = cpu.cycles
    cpu.interrupt(0xFFEA)  # native NMI vector
    elapsed_mc = cpu.cycles - cycles_before
    # 2 idles (6 MC each) + 4 writes to stack in slow RAM (8 MC each) + 2 reads from ROM $FFxx (8 MC each)
    # = 12 + 32 + 16 = 60 MC
    assert elapsed_mc == 60, f"Expected 60 MC, got {elapsed_mc}"


def test_interrupt_advances_cycles_emulation_mode():
    """Emulation mode skips PBR push: 7 bus cycles total."""
    bus, cpu = make_bus()
    cpu.EF = True  # emulation mode: 7 bus cycles (2 idle + push PCH/PCL/P + 2 vector reads)
    cpu.S.w = 0x01FF
    cycles_before = cpu.cycles
    cpu.interrupt(0xFFFA)  # emulation NMI vector
    elapsed_mc = cpu.cycles - cycles_before
    # 2 idles (6 MC each) + 3 writes to stack in slow RAM (8 MC each) + 2 reads from ROM $FFxx (8 MC each)
    # = 12 + 24 + 16 = 52 MC
    assert elapsed_mc == 52, f"Expected 52 MC, got {elapsed_mc}"


def test_interrupt_returns_correct_mc_for_scheduler():
    """_step() relies on interrupt() return value to reschedule itself."""
    bus, cpu = make_bus()
    cpu.EF = False
    cpu.S.w = 0x01FF
    mc = cpu.interrupt(0xFFEA)
    assert mc == 60, f"interrupt() must return elapsed MC, got {mc}"
