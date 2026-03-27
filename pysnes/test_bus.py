"""
Bus address-mapping unit tests.

These tests verify that reads and writes are routed to the correct region
without needing a real ROM file.  A minimal stub ROM is built in-memory so
the bus can be constructed with its normal code path.
"""

import pytest

from .scheduler import Scheduler
from .bus import Bus
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROM_SIZE = 512 * 1024  # 512 KB — enough for LoROM bank 0


class StubRom:
    """Minimal ROM stub with a writable bytearray backing store."""

    def __init__(self, size=ROM_SIZE):
        self.rom = bytearray(size)
        # Populate reset vector so Cpu() doesn't choke
        self.hardware_vectors = {
            "emulation": {"RESET": 0x8000, "NMI": 0x8000, "IRQ": 0x8000,
                          "COP": 0x8000, "ABORT": 0x8000},
            "native":    {"RESET": 0x8000, "NMI": 0x8000, "IRQ": 0x8000,
                          "BRK": 0x8000, "COP": 0x8000, "ABORT": 0x8000},
        }

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
    return bus, rom, cpu, apu, ppu


# ---------------------------------------------------------------------------
# Low RAM  ($0000–$1FFF, mirrored from bank $7E)
# ---------------------------------------------------------------------------

def test_low_ram_write_read_bank00():
    bus, *_ = make_bus()
    bus[0x000100] = 0xAB
    assert bus[0x000100] == 0xAB


def test_low_ram_mirror_bank3f():
    """Banks $00–$3F mirror the same Low RAM."""
    bus, *_ = make_bus()
    bus[0x000200] = 0x42
    assert bus[0x3F0200] == 0x42


def test_low_ram_mirror_bank7e():
    """Bank $7E $0000–$1FFF is the canonical Low RAM."""
    bus, *_ = make_bus()
    bus[0x7E0500] = 0x99
    assert bus[0x000500] == 0x99


def test_low_ram_boundary_last_byte():
    bus, *_ = make_bus()
    bus[0x001FFF] = 0x77
    assert bus[0x001FFF] == 0x77


# ---------------------------------------------------------------------------
# High RAM  ($7E2000–$7E7FFF)
# ---------------------------------------------------------------------------

def test_high_ram_write_read():
    bus, *_ = make_bus()
    bus[0x7E2000] = 0x11
    assert bus[0x7E2000] == 0x11


def test_high_ram_boundary():
    bus, *_ = make_bus()
    bus[0x7E7FFF] = 0xCC
    assert bus[0x7E7FFF] == 0xCC


# ---------------------------------------------------------------------------
# Extended RAM  ($7E8000–$7FFFFF)
# ---------------------------------------------------------------------------

def test_extended_ram_write_read():
    bus, *_ = make_bus()
    bus[0x7E8000] = 0x55
    assert bus[0x7E8000] == 0x55


def test_extended_ram_boundary():
    bus, *_ = make_bus()
    bus[0x7FFFFF] = 0xEE
    assert bus[0x7FFFFF] == 0xEE


# ---------------------------------------------------------------------------
# LoROM  (bank $00, $8000–$FFFF  →  ROM offset 0x0000–0x7FFF)
# ---------------------------------------------------------------------------

def test_lorom_read_bank00():
    bus, rom, *_ = make_bus()
    rom.rom[0x0010] = 0xBE   # ROM offset 0x0010 == bus addr 0x008010
    assert bus[0x008010] == 0xBE


def test_lorom_read_bank01():
    bus, rom, *_ = make_bus()
    # bank 1: ROM offset = 1*0x8000 + (addr-0x8000) = 0x8000 + 0x0020 = 0x8020
    rom.rom[0x8020] = 0xCA
    assert bus[0x018020] == 0xCA


def test_lorom_mirror_high_bank():
    """Banks $80–$FD mirror banks $00–$7D."""
    bus, rom, *_ = make_bus()
    rom.rom[0x0005] = 0x12
    # bank $80 mirrors bank $00
    assert bus[0x808005] == 0x12


def test_lorom_write_to_rom_region_stored():
    """Writes to ROM-mapped addresses go to rom.rom (test harness behaviour)."""
    bus, rom, *_ = make_bus()
    bus[0x008100] = 0x7F
    assert rom.rom[0x0100] == 0x7F


# ---------------------------------------------------------------------------
# APU I/O ports  ($2140–$2143)
# ---------------------------------------------------------------------------

def test_apu_port_read_returns_ports_w():
    bus, _, _, apu, _ = make_bus()
    apu.ports_w[0] = 0xAA
    apu.ports_w[1] = 0xBB
    assert bus[0x002140] == 0xAA
    assert bus[0x002141] == 0xBB


def test_apu_port_write_updates_ports_r():
    bus, _, _, apu, _ = make_bus()
    bus[0x002140] = 0xCC
    assert apu.ports_r[0] == 0xCC


def test_apu_port_write_all_four():
    bus, _, _, apu, _ = make_bus()
    for i, val in enumerate([0x10, 0x20, 0x30, 0x40]):
        bus[0x002140 + i] = val
    assert list(apu.ports_r) == [0x10, 0x20, 0x30, 0x40]


# ---------------------------------------------------------------------------
# PPU registers (spot-checks)
# ---------------------------------------------------------------------------

def test_ppu_inidisp_write():
    bus, _, _, _, ppu = make_bus()
    bus[0x002100] = 0x0F   # display enable, max brightness
    assert not ppu.display_disable


def test_ppu_bgmode_write():
    bus, _, _, _, ppu = make_bus()
    bus[0x002105] = 0x01
    assert ppu._bgmode == 0x01


# ---------------------------------------------------------------------------
# NMITIMEN / RDNMI  ($4200 / $4210)
# ---------------------------------------------------------------------------

def test_nmitimen_enables_nmi(make_bus=make_bus):
    bus, _, cpu, *_ = make_bus()
    bus[0x004200] = 0x80   # bit 7 = NMI enable
    assert cpu.status.nmi_enable


def test_rdnmi_clears_nmi_line():
    bus, _, cpu, *_ = make_bus()
    cpu.status.nmi_line = True
    bus[0x004210]          # reading RDNMI clears the line
    assert not cpu.status.nmi_line


# ---------------------------------------------------------------------------
# HVBJOY  ($4212)
# ---------------------------------------------------------------------------

def test_hvbjoy_vblank_bit():
    bus, *_ = make_bus()
    bus.vblank = True
    val = bus[0x004212]
    assert val & (1 << 7)


def test_hvbjoy_hblank_bit():
    bus, *_ = make_bus()
    bus.hblank = True
    val = bus[0x004212]
    assert val & (1 << 6)


def test_hvbjoy_no_blanks():
    bus, *_ = make_bus()
    bus.vblank = False
    bus.hblank = False
    val = bus[0x004212]
    assert not (val & (1 << 7))
    assert not (val & (1 << 6))
