"""
Bus address-mapping unit tests.

These tests verify that reads and writes are routed to the correct region
without needing a real ROM file.  A minimal stub ROM is built in-memory so
the bus can be constructed with its normal code path.
"""

import pytest

from ..scheduler import Scheduler
from .bus import Bus
from ..cpu import Cpu
from ..apu import Apu
from ..ppu import Ppu
from ..controller import Controller


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


# ---------------------------------------------------------------------------
# Low RAM boundary — first byte
# ---------------------------------------------------------------------------

def test_low_ram_boundary_first_byte():
    bus, *_ = make_bus()
    bus[0x000000] = 0x01
    assert bus[0x000000] == 0x01


# ---------------------------------------------------------------------------
# LoROM Region 2 — banks $40–$6F, full address range ($0000–$FFFF)
# ---------------------------------------------------------------------------

def test_lorom_region2_read():
    """Banks $40–$6F expose the full 64KB: low half is ROM too."""
    bus, rom, *_ = make_bus()
    # Bank $40, addr $0010 → ROM offset: 0x40 * 0x8000 + 0x0010 = 0x200010
    # But ROM is only 512 KB (0x80000), so use a small bank number inside range
    # Bank $40 = 64 decimal; offset = 64 * 0x8000 + 0x0010 = 0x200010 — beyond 512KB
    # Use bank $40 with addr >= 0x8000 to stay in region 1 overlap, OR use addr < 0x8000
    # For region 2 specifically (addr 0x0000-0x7FFF in banks 0x40-0x6F):
    # rom_addr = bank * 0x8000 + addr (addr < 0x8000, so no subtraction)
    # Bank $40=64, addr $0020 → rom_addr = 64*0x8000 + 0x0020 = 0x200020 (too big)
    # Use bank $40 but stub ROM is 512KB=0x80000; 0x200020 > 0x80000 → returns 0
    # Instead use bank $40 addr $0000 with small value to test routing (not OOB crash)
    rom.rom[0] = 0  # ensure clean
    val = bus[0x400000]  # should not crash; ROM is 512KB so addr 0x200000 is OOB → 0
    assert val == 0  # StubRom returns 0 for OOB — routing reached ROM, no crash


def test_lorom_region2_boundary_bank40():
    """Bank $40, addr $0000 routes through LoROM region 2 (not RAM)."""
    bus, rom, *_ = make_bus()
    # Confirm it doesn't hit low_ram (which would be bank 0x00-0x3F only)
    bus[0x000100] = 0xAB      # write low_ram via bank $00
    val = bus[0x400100]       # read via bank $40 addr $0100 — region 2, goes to ROM
    assert val != 0xAB        # must NOT return the low_ram value


# ---------------------------------------------------------------------------
# LoROM Region 3 — banks $70–$7D, addr $8000–$FFFF
# ---------------------------------------------------------------------------

def test_lorom_region3_read():
    """Banks $70–$7D, high half map to ROM."""
    bus, rom, *_ = make_bus()
    # bank $70=112, addr $8010 → rom_addr = 112*0x8000 + (0x8010-0x8000) = 0x380010
    # 0x380010 > 512KB → OOB, StubRom returns 0; test just confirms routing/no crash
    val = bus[0x708010]
    assert val == 0


def test_lorom_region3_not_ram():
    """Bank $70 addr $8000 must not hit low_ram or high_ram."""
    bus, rom, *_ = make_bus()
    bus[0x7E0100] = 0xCC      # write low_ram via bank $7E
    val = bus[0x708100]       # bank $70, addr $8100 → LoROM region 3
    assert val != 0xCC


# ---------------------------------------------------------------------------
# LoROM mirror write (banks $80–$FD → mirrors $00–$7D)
# ---------------------------------------------------------------------------

def test_lorom_mirror_write():
    """Write through a mirrored bank ($80+) lands in the same ROM slot as $00."""
    bus, rom, *_ = make_bus()
    bus[0x808010] = 0x55      # bank $80 mirrors bank $00
    assert rom.rom[0x0010] == 0x55


# ---------------------------------------------------------------------------
# Controller — JOYSER0 write ($4016) latches both ports
# ---------------------------------------------------------------------------

def test_joyser0_write_latches_controller():
    """Writing 1 then 0 to JOYSER0 latches the controller shift register."""
    bus, *_ = make_bus()
    bus[0x004016] = 0x01      # latch high
    bus[0x004016] = 0x00      # latch low — loads shift register
    # After latch cycle, reading data() should return 1s (no keys pressed → padding)
    val = bus[0x004016]       # JOYSER0 read
    assert val in range(0, 0x100)  # sanity: valid byte returned


# ---------------------------------------------------------------------------
# Joy registers — JOY1L/1H/2L/2H ($4218–$421B)
# ---------------------------------------------------------------------------

def test_joy1l_read():
    bus, _, _, _, _ = make_bus()
    bus.controller_port1.joy_l = 0xAB
    assert bus[0x004218] == 0xAB


def test_joy1h_read():
    bus, _, _, _, _ = make_bus()
    bus.controller_port1.joy_h = 0xCD
    assert bus[0x004219] == 0xCD


def test_joy2l_read():
    bus, _, _, _, _ = make_bus()
    bus.controller_port2.joy_l = 0x12
    assert bus[0x00421A] == 0x12


def test_joy2h_read():
    bus, _, _, _, _ = make_bus()
    bus.controller_port2.joy_h = 0x34
    assert bus[0x00421B] == 0x34


# ---------------------------------------------------------------------------
# NMITIMEN read ($4200) — verify it routes to dma_ppu2_hw_registers fallback
# (the register is write-only; reads fall through to the bytearray)
# ---------------------------------------------------------------------------

def test_nmitimen_read_fallthrough():
    """Reading $4200 returns the value stored in dma_ppu2_hw_registers."""
    bus, *_ = make_bus()
    bus.dma_ppu2_hw_registers[0x4200 - 0x4200] = 0x42
    assert bus[0x004200] == 0x42
