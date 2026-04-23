"""
Bus address-mapping unit tests.

These tests verify that reads and writes are routed to the correct region
without needing a real ROM file.  A minimal stub ROM is built in-memory so
the bus can be constructed with its normal code path.
"""

from types import SimpleNamespace

import pytest

from ..scheduler import Scheduler
from .bus import Bus
from ..cpu import Cpu
from ..apu import Apu
from ..ppu import Ppu
from ..controller import Controller
from ..rom import HardwareVectors, InterruptVectors, MappingMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROM_SIZE = 512 * 1024  # 512 KB — enough for LoROM bank 0


class StubRom:
    """Minimal ROM stub with a writable bytearray backing store."""

    def __init__(self, size=ROM_SIZE, sram_size=0, mapping_mode=MappingMode.LOROM):
        self.rom = bytearray(size)
        self.sram_size = sram_size
        self.snes_header = SimpleNamespace(mapping_mode=mapping_mode)
        # Populate reset vector so Cpu() doesn't choke
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


def make_bus(sram_size=0, mapping_mode=MappingMode.LOROM):
    rom = StubRom(sram_size=sram_size, mapping_mode=mapping_mode)
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
# OPHCT / OPVCT  ($213C / $213D)
#
# The H/V counters are 9-bit values (0..339 and 0..261), but the register
# port is byte-wide. Returning the raw integer lets values > 255 leak out,
# which crashes CPU opcode fetches that land in the register region.
# ---------------------------------------------------------------------------

def test_ophct_read_is_byte_sized():
    bus, *_, ppu = make_bus()
    ppu.h_counter = 274           # dot count at H-blank start
    val = bus[0x00213C]
    assert 0 <= val <= 0xFF


def test_opvct_read_is_byte_sized():
    bus, *_, ppu = make_bus()
    ppu.v_counter = 261           # last scanline in a non-interlace frame
    val = bus[0x00213D]
    assert 0 <= val <= 0xFF


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


# ---------------------------------------------------------------------------
# MEMSEL ($420D) — FastROM speed select (bit 0)
# ---------------------------------------------------------------------------

def test_memsel_fastrom_off_by_default():
    """Banks $80-$BF/$C0-$FF use slow (8 MC) by default."""
    bus, _rom, cpu, *_ = make_bus()
    # Bank $C0, any address → slow without FastROM
    assert cpu.get_clock_cycles(0xC00000) == 8


def test_memsel_fastrom_on_sets_fast_speed():
    """Writing 1 to $420D enables FastROM: banks $80-$BF/$C0-$FF use fast (6 MC)."""
    bus, _rom, cpu, *_ = make_bus()
    bus[0x00420D] = 0x01  # MEMSEL: enable FastROM
    assert cpu.get_clock_cycles(0xC00000) == 6


def test_memsel_fastrom_on_bank_80():
    """FastROM also applies to banks $80-$BF."""
    bus, _rom, cpu, *_ = make_bus()
    bus[0x00420D] = 0x01
    assert cpu.get_clock_cycles(0x808000) == 6


def test_memsel_fastrom_off_bank_80():
    """Without FastROM, banks $80-$BF are slow."""
    bus, _rom, cpu, *_ = make_bus()
    assert cpu.get_clock_cycles(0x808000) == 8


def test_memsel_fastrom_toggle():
    """FastROM can be disabled after being enabled."""
    bus, _rom, cpu, *_ = make_bus()
    bus[0x00420D] = 0x01
    assert cpu.get_clock_cycles(0xC00000) == 6
    bus[0x00420D] = 0x00
    assert cpu.get_clock_cycles(0xC00000) == 8


# ---------------------------------------------------------------------------
# SRAM (LoROM) — banks $70-$7D, addr $0000-$7FFF (mirrored at $F0-$FD)
# ---------------------------------------------------------------------------

def test_sram_basic_write_read():
    """Bank $70 $0000 writes and reads through SRAM."""
    bus, *_ = make_bus(sram_size=0x2000)  # 8KB
    bus[0x700000] = 0xAB
    assert bus[0x700000] == 0xAB


def test_sram_distinct_from_wram():
    """SRAM is a separate buffer from WRAM."""
    bus, *_ = make_bus(sram_size=0x2000)
    bus[0x7E0100] = 0x11       # WRAM
    bus[0x700100] = 0x22       # SRAM (same low address, different region)
    assert bus[0x7E0100] == 0x11
    assert bus[0x700100] == 0x22


def test_sram_mirror_bank_f0():
    """Bank $F0 mirrors bank $70."""
    bus, *_ = make_bus(sram_size=0x2000)
    bus[0x700010] = 0x55
    assert bus[0xF00010] == 0x55


def test_sram_upper_bank_7d():
    """Bank $7D is the last SRAM bank; address should wrap per sram_size."""
    bus, *_ = make_bus(sram_size=0x2000)  # 8KB -> mask $1FFF
    # Bank $7D addr $0000 maps to SRAM offset (0xD<<15) & 0x1FFF = 0x0000
    bus[0x7D0000] = 0x77
    assert bus[0x700000] == 0x77  # same SRAM byte due to wrap


def test_sram_size_masking_2kb():
    """With 2KB SRAM, addresses $0000 and $0800 alias the same byte."""
    bus, *_ = make_bus(sram_size=0x800)  # 2KB
    bus[0x700000] = 0xAA
    assert bus[0x700800] == 0xAA
    bus[0x700801] = 0xBB
    assert bus[0x700001] == 0xBB


def test_sram_size_masking_8kb():
    """With 8KB SRAM, $0000 and $2000 alias; $0000 and $1FFF do not."""
    bus, *_ = make_bus(sram_size=0x2000)
    bus[0x700000] = 0x01
    bus[0x701FFF] = 0x02
    assert bus[0x700000] == 0x01
    assert bus[0x701FFF] == 0x02
    # Wrap: $2000 aliases $0000
    bus[0x702000] = 0x99
    assert bus[0x700000] == 0x99


def test_sram_no_sram_read_returns_open_bus():
    """When sram_size is 0, SRAM reads return 0xFF (open bus)."""
    bus, *_ = make_bus(sram_size=0)
    assert bus[0x700000] == 0xFF


def test_sram_no_sram_write_ignored():
    """When sram_size is 0, SRAM writes are silently ignored (no crash)."""
    bus, *_ = make_bus(sram_size=0)
    bus[0x700000] = 0xAB  # must not raise
    assert bus[0x700000] == 0xFF


def test_sram_save_noop_when_clean(tmp_path):
    """A fresh bus with no SRAM writes should not create a .srm file."""
    path = tmp_path / "game.srm"
    bus, *_ = make_bus(sram_size=0x2000)
    assert bus.save_sram(str(path)) == 0
    assert not path.exists()


def test_sram_save_noop_after_save(tmp_path):
    """After saving, a second save with no further writes is a no-op."""
    path = tmp_path / "game.srm"
    bus, *_ = make_bus(sram_size=0x2000)
    bus[0x700000] = 0xAB
    assert bus.save_sram(str(path)) == 0x2000
    mtime = path.stat().st_mtime_ns
    assert bus.save_sram(str(path)) == 0       # nothing dirty
    assert path.stat().st_mtime_ns == mtime    # file untouched


def test_sram_load_then_save_is_noop(tmp_path):
    """Loading SRAM doesn't make it dirty — a subsequent save does nothing."""
    path = tmp_path / "game.srm"
    path.write_bytes(b"\xAA" * 0x2000)
    bus, *_ = make_bus(sram_size=0x2000)
    assert bus.load_sram(str(path)) == 0x2000
    # Save to a different path to make the no-op check unambiguous
    out = tmp_path / "out.srm"
    assert bus.save_sram(str(out)) == 0
    assert not out.exists()


def test_sram_write_sets_dirty(tmp_path):
    """A write via the bus after load makes SRAM dirty again."""
    path = tmp_path / "game.srm"
    path.write_bytes(b"\x00" * 0x2000)
    bus, *_ = make_bus(sram_size=0x2000)
    bus.load_sram(str(path))
    bus[0x700010] = 0x42
    out = tmp_path / "out.srm"
    assert bus.save_sram(str(out)) == 0x2000
    assert out.read_bytes()[0x10] == 0x42


def test_sram_roundtrip_save_load(tmp_path):
    """Write to SRAM, save, create new bus, load — contents preserved."""
    path = tmp_path / "game.srm"
    bus, *_ = make_bus(sram_size=0x2000)
    bus[0x700000] = 0xDE
    bus[0x700001] = 0xAD
    bus[0x701FFF] = 0xEF
    n = bus.save_sram(str(path))
    assert n == 0x2000
    assert path.stat().st_size == 0x2000

    bus2, *_ = make_bus(sram_size=0x2000)
    assert bus2[0x700000] == 0x00  # fresh
    loaded = bus2.load_sram(str(path))
    assert loaded == 0x2000
    assert bus2[0x700000] == 0xDE
    assert bus2[0x700001] == 0xAD
    assert bus2[0x701FFF] == 0xEF


def test_sram_save_noop_when_no_sram(tmp_path):
    """No .srm file written when cart has no SRAM."""
    path = tmp_path / "game.srm"
    bus, *_ = make_bus(sram_size=0)
    assert bus.save_sram(str(path)) == 0
    assert not path.exists()


def test_sram_load_missing_file_noop(tmp_path):
    """Loading from a non-existent file returns 0 and leaves SRAM untouched."""
    bus, *_ = make_bus(sram_size=0x800)
    bus[0x700000] = 0x5A
    assert bus.load_sram(str(tmp_path / "missing.srm")) == 0
    assert bus[0x700000] == 0x5A


def test_sram_load_smaller_file_preserves_tail(tmp_path):
    """Loading a file smaller than sram_size only overwrites the leading bytes."""
    path = tmp_path / "partial.srm"
    path.write_bytes(b"\x11\x22")
    bus, *_ = make_bus(sram_size=0x800)
    bus[0x700100] = 0xFE       # tail byte to preserve
    loaded = bus.load_sram(str(path))
    assert loaded == 2
    assert bus[0x700000] == 0x11
    assert bus[0x700001] == 0x22
    assert bus[0x700100] == 0xFE  # unchanged


def test_sram_upper_half_still_rom():
    """Bank $70 $8000-$FFFF is ROM, not SRAM — reads must not return SRAM data."""
    bus, rom, *_ = make_bus(sram_size=0x2000)
    bus[0x700000] = 0xCC                 # SRAM at offset 0
    # Bank $00 $8000 -> ROM offset 0; set it so we can verify $70 $8000 hits ROM
    # (bank $70 $8000 -> ROM offset 0x380000 which is OOB on 512KB StubRom -> 0)
    assert bus[0x708000] != 0xCC         # not SRAM
    assert bus[0x708000] == 0             # OOB ROM read returns 0 from StubRom


# ---------------------------------------------------------------------------
# RDVRAML / RDVRAMH  ($2139 / $213A) bus dispatch
# ---------------------------------------------------------------------------

def test_rdvraml_routes_to_ppu():
    """$2139 returns the low byte of the PPU's VRAM prefetch buffer."""
    bus, _, _, _, ppu = make_bus()
    ppu.vram[0x0010 * 2 + 0] = 0xAA
    ppu.vram[0x0010 * 2 + 1] = 0xBB
    bus[0x002115] = 0x00            # VMAIN: increment on low read
    bus[0x002116] = 0x10            # VMADDL — triggers prefetch
    bus[0x002117] = 0x00            # VMADDH — triggers prefetch
    assert bus[0x002139] == 0xAA


def test_rdvramh_routes_to_ppu():
    """$213A returns the high byte of the PPU's VRAM prefetch buffer."""
    bus, _, _, _, ppu = make_bus()
    ppu.vram[0x0020 * 2 + 0] = 0x11
    ppu.vram[0x0020 * 2 + 1] = 0x22
    bus[0x002115] = 0x80
    bus[0x002116] = 0x20
    bus[0x002117] = 0x00
    assert bus[0x00213A] == 0x22


# ---------------------------------------------------------------------------
# Open-bus behavior for unmapped regions in banks $00-$3F
# ---------------------------------------------------------------------------
# Real hardware returns the last value on the CPU data bus (MDR). We return 0
# as a simplification — the important thing is that reads don't raise.

def test_open_bus_unmapped_2000_range():
    """Reads in $2000-$20FF (unmapped, below PPU regs) must not raise."""
    bus, *_ = make_bus()
    assert bus[0x0020F1] == 0    # Final Fight / SimCity touch this region


def test_open_bus_unmapped_2200_range():
    """Reads in $2200-$3FFF (unmapped, above PPU regs) must not raise."""
    bus, *_ = make_bus()
    assert bus[0x0027A8] == 0    # Zelda touches this


def test_open_bus_unmapped_mirrored_bank():
    """The same open-bus behavior applies through the $80-$BF LoROM mirror."""
    bus, *_ = make_bus()
    assert bus[0x8020F1] == 0
    assert bus[0x8027A8] == 0


# ---------------------------------------------------------------------------
# WRAM mirror: banks $FE-$FF shadow $7E-$7F
# ---------------------------------------------------------------------------

def test_wram_mirror_bank_fe_low_ram():
    """Bank $FE addr $0000-$1FFF mirrors Low RAM."""
    bus, *_ = make_bus()
    bus[0x7E0100] = 0x42
    assert bus[0xFE0100] == 0x42


def test_wram_mirror_bank_fe_high_ram():
    """Bank $FE addr $2000-$7FFF mirrors High RAM (Zelda reads $FE2002)."""
    bus, *_ = make_bus()
    bus[0x7E2002] = 0xA5
    assert bus[0xFE2002] == 0xA5


def test_wram_mirror_bank_ff_extended_ram():
    """Bank $FF addr $0000-$FFFF mirrors the $7F page of WRAM."""
    bus, *_ = make_bus()
    bus[0x7F8000] = 0x5A
    assert bus[0xFF8000] == 0x5A


# ---------------------------------------------------------------------------
# Unmapped writes in the system area should be silently dropped (open-bus)
# ---------------------------------------------------------------------------

def test_write_unmapped_2000_range_is_dropped():
    """Writes to $2000-$20FF must not raise (Final Fight hits this)."""
    bus, *_ = make_bus()
    bus[0x0020B4] = 0xE1   # must not raise


def test_write_unmapped_2200_range_is_dropped():
    """Writes to $2200-$3FFF must not raise."""
    bus, *_ = make_bus()
    bus[0x003000] = 0xFF


def test_write_unmapped_stack_region_dropped():
    """Writes to $7FFF in bank $00 (above LowRAM, not a register) must not raise."""
    bus, *_ = make_bus()
    bus[0x007FFF] = 0x00   # Zelda's stack push hits this


# ---------------------------------------------------------------------------
# HiROM mapping — banks $C0-$FF full (mirror $40-$7D), $00-$3F upper half
# (mirror $80-$BF). Formula: rom_addr = (bank & 0x3F) << 16 | addr.
# ---------------------------------------------------------------------------

def test_hirom_read_bank_c0_low_half():
    """Bank $C0 addr $0000 → rom_addr 0x000000 (first byte of ROM image)."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    rom.rom[0x000000] = 0xAB
    assert bus[0xC00000] == 0xAB


def test_hirom_read_bank_c0_high_half():
    """Bank $C0 addr $8000 → rom_addr 0x008000."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    rom.rom[0x008000] = 0xBC
    assert bus[0xC08000] == 0xBC


def test_hirom_read_bank_c1_spans_full_64kb():
    """Bank $C1 maps 64KB starting at rom_addr 0x010000."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    rom.rom[0x010000] = 0x11
    rom.rom[0x01FFFF] = 0x22
    assert bus[0xC10000] == 0x11
    assert bus[0xC1FFFF] == 0x22


def test_hirom_read_bank_00_upper_half():
    """Bank $00 addr $8000 is the upper half of HiROM bank $C0 → rom_addr 0x008000."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    rom.rom[0x008000] = 0xCD
    assert bus[0x008000] == 0xCD


def test_hirom_read_bank_07_upper_half():
    """Bank $07 addr $FFFF → rom_addr 0x07FFFF (last byte of stub ROM)."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    rom.rom[0x07FFFF] = 0xDE
    assert bus[0x07FFFF] == 0xDE


def test_hirom_read_bank_40_mirrors_bank_c0():
    """Banks $40-$7D mirror $C0-$FD (same full-bank layout)."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    rom.rom[0x000100] = 0xEF
    assert bus[0x400100] == 0xEF


def test_hirom_read_bank_80_mirrors_bank_00_upper_half():
    """Banks $80-$BF at $8000-$FFFF mirror banks $00-$3F upper halves."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    rom.rom[0x008100] = 0xF0
    assert bus[0x808100] == 0xF0


def test_hirom_write_to_rom_region():
    """Writes to HiROM-mapped addresses go to rom.rom (test harness behaviour)."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    bus[0xC00001] = 0x7F
    assert rom.rom[0x000001] == 0x7F


def test_hirom_bank_00_low_half_is_lowram_not_rom():
    """HiROM banks $00-$3F below $8000 are system area (LowRAM / I/O), NOT ROM."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    bus[0x000100] = 0xFA
    # Must go to low_ram, not rom.rom
    assert rom.rom[0x000100] != 0xFA
    # And read-back returns the low_ram value
    assert bus[0x000100] == 0xFA


def test_hirom_bank_40_full_not_lowram():
    """HiROM bank $40 addr $0000 is ROM (not LowRAM, unlike LoROM bank $40)."""
    bus, rom, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    rom.rom[0x000200] = 0xCC
    # Confirm LowRAM access separately to prove routing diverges
    bus[0x000200] = 0xDD          # writes LowRAM (bank $00 addr $0200)
    assert bus[0x400200] == 0xCC  # still reads HiROM


# ---------------------------------------------------------------------------
# HiROM SRAM — banks $20-$3F / $A0-$BF at $6000-$7FFF, 8KB window per bank
# ---------------------------------------------------------------------------

def test_hirom_sram_bank_20():
    """HiROM SRAM: bank $20 addr $6000 → SRAM offset 0."""
    bus, *_ = make_bus(sram_size=0x2000, mapping_mode=MappingMode.HIROM)
    bus[0x206000] = 0x11
    assert bus[0x206000] == 0x11


def test_hirom_sram_mirror_bank_a0():
    """HiROM SRAM bank $A0 mirrors bank $20 (via $80-$FF bank mirror)."""
    bus, *_ = make_bus(sram_size=0x2000, mapping_mode=MappingMode.HIROM)
    bus[0x206001] = 0x22
    assert bus[0xA06001] == 0x22


def test_hirom_sram_multiple_banks():
    """Bank $21 addr $6000 → SRAM offset 0x2000 (8KB stride per bank)."""
    bus, *_ = make_bus(sram_size=0x8000, mapping_mode=MappingMode.HIROM)
    bus[0x206000] = 0x44
    bus[0x216000] = 0x33
    assert bus[0x206000] == 0x44
    assert bus[0x216000] == 0x33


def test_hirom_sram_size_masking_8kb():
    """With 8KB SRAM, bank $21 wraps back to bank $20."""
    bus, *_ = make_bus(sram_size=0x2000, mapping_mode=MappingMode.HIROM)
    bus[0x206000] = 0x55
    # sram_mask = 0x1FFF; bank $21 offset = 0x2000 & 0x1FFF = 0
    assert bus[0x216000] == 0x55


def test_hirom_sram_no_sram_returns_open_bus():
    """Reading HiROM SRAM with sram_size=0 returns 0xFF (open bus)."""
    bus, *_ = make_bus(sram_size=0, mapping_mode=MappingMode.HIROM)
    assert bus[0x206000] == 0xFF


def test_hirom_sram_window_bounds():
    """Bank $20 addr $5FFF is NOT SRAM (below the $6000-$7FFF window)."""
    bus, *_ = make_bus(sram_size=0x2000, mapping_mode=MappingMode.HIROM)
    # $5FFF is above LowRAM ($0000-$1FFF) and hits the system-area fallthrough.
    # Must not be routed as SRAM; a write there must not persist as a readable
    # SRAM byte at offset $5FFF & sram_mask.
    bus[0x206000] = 0xAA          # SRAM byte 0
    # $205FFF would alias SRAM offset $5FFF & 0x1FFF = 0x1FFF if we wrongly
    # routed it; ensure it does NOT overwrite byte 0.
    bus[0x205FFF] = 0x00          # should be dropped (system area)
    assert bus[0x206000] == 0xAA


def test_hirom_bank_00_low_ram_still_works():
    """HiROM must not accidentally claim bank $00 $0000-$1FFF as ROM."""
    bus, *_ = make_bus(mapping_mode=MappingMode.HIROM)
    bus[0x000100] = 0x42
    assert bus[0x000100] == 0x42
    assert bus[0x7E0100] == 0x42  # LowRAM canonical


def test_hirom_bank_00_hw_registers_still_work():
    """HiROM bank $00 $2100-$21FF must still hit PPU registers, not ROM."""
    bus, _, _, _, ppu = make_bus(mapping_mode=MappingMode.HIROM)
    bus[0x002100] = 0x0F  # INIDISP, display enable
    assert not ppu.display_disable


# ---------------------------------------------------------------------------
# Math hardware ($4202-$4206 write, $4214-$4217 read)
# ---------------------------------------------------------------------------

def test_multiply_basic():
    """Writing WRMPYB ($4203) triggers 8x8 unsigned multiply; result in $4216-$4217."""
    bus, *_ = make_bus()
    bus[0x004202] = 5   # WRMPYA = 5
    bus[0x004203] = 3   # WRMPYB = 3 → product = 15
    assert bus[0x004216] == 15   # RDMPYL low byte
    assert bus[0x004217] == 0    # RDMPYH high byte
    assert bus[0x004214] == 0    # RDDIVL cleared after multiply
    assert bus[0x004215] == 0    # RDDIVH cleared after multiply


def test_multiply_overflow():
    """255 * 255 = 65025 = 0xFE01; verify high byte."""
    bus, *_ = make_bus()
    bus[0x004202] = 255
    bus[0x004203] = 255
    assert bus[0x004216] == 0x01   # low byte
    assert bus[0x004217] == 0xFE   # high byte


def test_divide_basic():
    """Writing WRDIVB ($4206) triggers 16÷8 unsigned divide; quotient in $4214-$4215, remainder in $4216-$4217."""
    bus, *_ = make_bus()
    bus[0x004204] = 100 & 0xFF    # WRDIVL low byte of 100
    bus[0x004205] = 100 >> 8      # WRDIVH high byte of 100
    bus[0x004206] = 7             # WRDIVB = 7 → 100 / 7 = 14 rem 2
    assert bus[0x004214] == 14    # RDDIVL quotient low
    assert bus[0x004215] == 0     # RDDIVH quotient high
    assert bus[0x004216] == 2     # RDMPYL remainder low
    assert bus[0x004217] == 0     # RDMPYH remainder high


def test_divide_high_dividend():
    """16-bit dividend: WRDIVL=0, WRDIVH=1 → dividend=256; 256/16=16 rem 0."""
    bus, *_ = make_bus()
    bus[0x004205] = 1   # high byte → dividend = 256
    bus[0x004204] = 0   # low byte
    bus[0x004206] = 16  # divisor
    assert bus[0x004214] == 16
    assert bus[0x004215] == 0
    assert bus[0x004216] == 0
    assert bus[0x004217] == 0


def test_divide_by_zero():
    """Divide by zero: quotient=$FFFF, remainder=dividend."""
    bus, *_ = make_bus()
    bus[0x004204] = 0x34
    bus[0x004205] = 0x12   # dividend = 0x1234
    bus[0x004206] = 0      # divide by zero
    assert bus[0x004214] == 0xFF
    assert bus[0x004215] == 0xFF
    assert bus[0x004216] == 0x34  # remainder = dividend low
    assert bus[0x004217] == 0x12  # remainder = dividend high
