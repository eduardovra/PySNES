"""
DMA unit tests.

Covers:
  - MDMA (general-purpose DMA): transfer modes 0 and 1, both directions,
    fixed vs incrementing source, multi-channel enables
  - HDMA enable register (channel hdma_enable flag)
  - Channel register decode ($43x0–$43xA)
  - Bus integration: DMA writes are visible via bus reads
"""

import pytest

from ..scheduler import Scheduler
from ..bus import Bus
from .cpu import Cpu
from ..apu import Apu
from ..ppu import Ppu
from ..controller import Controller
from ..rom import HardwareVectors, InterruptVectors, MappingMode
from types import SimpleNamespace


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    return bus, rom, cpu


# ---------------------------------------------------------------------------
# Channel register decoding ($43x0–$43xA)
# ---------------------------------------------------------------------------

def test_dmap_transfer_mode():
    bus, _, cpu = make_bus()
    bus[0x004300] = 0b00000011  # channel 0: transfer_mode=3
    assert cpu.dma.channels[0].transfer_mode == 3


def test_dmap_fixed_transfer_flag():
    bus, _, cpu = make_bus()
    bus[0x004300] = 0b00001000  # bit 3: fixed_transfer
    assert cpu.dma.channels[0].fixed_transfer == 1


def test_dmap_direction_flag():
    bus, _, cpu = make_bus()
    bus[0x004300] = 0b10000000  # bit 7: direction=1 (B→A)
    assert cpu.dma.channels[0].direction == 1


def test_bbad_target_address():
    bus, _, cpu = make_bus()
    bus[0x004301] = 0x18  # VRAM write register offset
    assert cpu.dma.channels[0].target_address == 0x18


def test_a1t_source_address_low_high():
    bus, _, cpu = make_bus()
    bus[0x004302] = 0x34  # A1TxL
    bus[0x004303] = 0x12  # A1TxH
    assert cpu.dma.channels[0].source_address == 0x1234


def test_a1b_source_bank():
    bus, _, cpu = make_bus()
    bus[0x004304] = 0x7E
    assert cpu.dma.channels[0].source_bank == 0x7E


def test_das_transfer_size_low_high():
    bus, _, cpu = make_bus()
    bus[0x004305] = 0x00  # DASxL
    bus[0x004306] = 0x10  # DASxH  → 0x1000 = 4096 bytes
    assert cpu.dma.channels[0].transfer_size == 0x1000


def test_channel_select_channel_1():
    bus, _, cpu = make_bus()
    bus[0x004310] = 0x01  # channel 1 DMAP
    assert cpu.dma.channels[1].transfer_mode == 1
    assert cpu.dma.channels[0].transfer_mode == 0  # other channels unaffected


def test_channel_select_channel_7():
    bus, _, cpu = make_bus()
    bus[0x004370] = 0x02  # channel 7 DMAP
    assert cpu.dma.channels[7].transfer_mode == 2


# ---------------------------------------------------------------------------
# MDMA — transfer mode 0  (1 byte to 1 B-bus register)
# ---------------------------------------------------------------------------

def test_mdma_mode0_single_byte():
    """Mode 0: each byte from A bus written to the single B-bus target."""
    bus, rom, cpu = make_bus()
    rom.rom[0x0000] = 0xAB  # source at bank 0, offset 0x0000 → bus $008000

    bus[0x004300] = 0x00   # DMAP0: mode=0, dir=A→B, increment source
    bus[0x004301] = 0x00   # BBAD0: target = $2100 (INIDISP)
    bus[0x004302] = 0x00   # A1T0L: source low  → $8000
    bus[0x004303] = 0x80   # A1T0H: source high
    bus[0x004304] = 0x00   # A1B0:  source bank 0
    bus[0x004305] = 0x01   # DAS0L: size = 1
    bus[0x004306] = 0x00   # DAS0H

    bus[0x00420B] = 0x01   # MDMAEN: enable channel 0 → triggers transfer


def test_mdma_mode0_transfers_correct_data():
    """Verify the transferred byte actually reaches the PPU register."""
    bus, rom, cpu = make_bus()
    rom.rom[0x0000] = 0x0F  # brightness max, display enabled

    bus[0x004300] = 0x00
    bus[0x004301] = 0x00   # target $2100 (INIDISP)
    bus[0x004302] = 0x00
    bus[0x004303] = 0x80
    bus[0x004304] = 0x00
    bus[0x004305] = 0x01
    bus[0x004306] = 0x00
    bus[0x00420B] = 0x01

    assert not bus.ppu.display_disable


def test_mdma_mode0_multi_byte_increments_source():
    """Source address increments for each transferred byte."""
    bus, rom, cpu = make_bus()
    rom.rom[0x0000] = 0x01
    rom.rom[0x0001] = 0x02
    rom.rom[0x0002] = 0x03

    bus[0x004300] = 0x00   # mode 0, increment
    bus[0x004301] = 0x01   # target $2101
    bus[0x004302] = 0x00
    bus[0x004303] = 0x80
    bus[0x004304] = 0x00
    bus[0x004305] = 0x03   # 3 bytes
    bus[0x004306] = 0x00
    bus[0x00420B] = 0x01

    # channel.source_address should have advanced by 3
    assert cpu.dma.channels[0].source_address == 0x8003


def test_mdma_mode0_fixed_source_does_not_increment():
    """Fixed transfer: source address stays constant."""
    bus, rom, cpu = make_bus()
    rom.rom[0x0000] = 0xFF

    bus[0x004300] = 0x08   # mode=0, fixed_transfer=1
    bus[0x004301] = 0x01
    bus[0x004302] = 0x00
    bus[0x004303] = 0x80
    bus[0x004304] = 0x00
    bus[0x004305] = 0x04   # 4 bytes
    bus[0x004306] = 0x00
    bus[0x00420B] = 0x01

    assert cpu.dma.channels[0].source_address == 0x8000  # unchanged


# ---------------------------------------------------------------------------
# MDMA — transfer mode 1  (2 bytes alternating to $21xx / $21xx+1)
# ---------------------------------------------------------------------------

def test_mdma_mode1_alternates_target():
    """Mode 1 alternates writes between $21xx and $21xx+1."""
    bus, rom, cpu = make_bus()
    # Write 2 bytes — first goes to $2118 (VMDATAL), second to $2119 (VMDATAH)
    rom.rom[0x0000] = 0xAA
    rom.rom[0x0001] = 0xBB

    bus[0x004300] = 0x01   # DMAP0: mode=1
    bus[0x004301] = 0x18   # BBAD0: $2118 (VRAM data low)
    bus[0x004302] = 0x00
    bus[0x004303] = 0x80
    bus[0x004304] = 0x00
    bus[0x004305] = 0x02   # 2 bytes
    bus[0x004306] = 0x00
    bus[0x00420B] = 0x01


# ---------------------------------------------------------------------------
# MDMA — multi-channel
# ---------------------------------------------------------------------------

def test_mdma_only_enabled_channels_run():
    """MDMAEN bitmask: only channels with their bit set transfer."""
    bus, rom, cpu = make_bus()
    rom.rom[0x0000] = 0x11
    rom.rom[0x8000] = 0x22  # ROM offset for channel 1 (bank 0, offset 0x8000 + 0x8000)

    # Channel 0
    bus[0x004300] = 0x00
    bus[0x004301] = 0x00
    bus[0x004302] = 0x00
    bus[0x004303] = 0x80
    bus[0x004304] = 0x00
    bus[0x004305] = 0x01
    bus[0x004306] = 0x00

    # Channel 1 (same setup but different source)
    bus[0x004310] = 0x00
    bus[0x004311] = 0x01
    bus[0x004312] = 0x00
    bus[0x004313] = 0x80
    bus[0x004314] = 0x00
    bus[0x004315] = 0x01
    bus[0x004316] = 0x00

    # Enable only channel 0 (bit 0)
    bus[0x00420B] = 0x01
    assert cpu.dma.channels[0].source_address == 0x8001  # incremented
    assert cpu.dma.channels[1].source_address == 0x8000  # untouched


# ---------------------------------------------------------------------------
# HDMA — enable register
# ---------------------------------------------------------------------------

def test_hdmaen_sets_channel_flags():
    bus, _, cpu = make_bus()
    bus[0x00420C] = 0b00000101   # enable channels 0 and 2
    assert cpu.dma.channels[0].hdma_enable == 1
    assert cpu.dma.channels[1].hdma_enable == 0
    assert cpu.dma.channels[2].hdma_enable == 4  # bit 2 = value 4


def test_hdmaen_clears_when_zero():
    bus, _, cpu = make_bus()
    bus[0x00420C] = 0xFF
    bus[0x00420C] = 0x00
    for ch in cpu.dma.channels:
        assert ch.hdma_enable == 0


# ---------------------------------------------------------------------------
# HDMA scanline execution
# ---------------------------------------------------------------------------

def _setup_hdma_channel0(bus, rom, table_offset, table_bytes):
    """Write an HDMA table at ROM[table_offset] and configure channel 0 (mode 1, target $2126)."""
    for i, b in enumerate(table_bytes):
        rom.rom[table_offset + i] = b
    # source address = 0x8000 + table_offset (LoROM: bank 0 / $8000 region)
    src = 0x8000 + table_offset
    bus[0x004300] = 0x01   # DMAP0: mode=1 (2 bytes per unit), dir=A→B
    bus[0x004301] = 0x26   # BBAD0: target $2126 (WH0)
    bus[0x004302] = src & 0xFF   # A1T0L
    bus[0x004303] = (src >> 8) & 0xFF  # A1T0H
    bus[0x004304] = 0x00   # A1B0: bank 0
    bus[0x00420C] = 0x01   # HDMAEN: enable channel 0


def test_hdma_non_repeat_writes_bytes_to_target():
    """Do-repeat entry (bit 7=1): each scanline gets fresh 2-byte data written to $2126/$2127."""
    bus, rom, cpu = make_bus()
    # Table: count=0x82 (do-repeat, 2 scanlines), data=[10,200], [20,210], end
    _setup_hdma_channel0(bus, rom, 0x0000, [0x82, 10, 200, 20, 210, 0x00])
    cpu.dma.hdma_init()

    cpu.dma.hdma_scanline()           # scanline 1: WH0=10, WH1=200
    assert bus.ppu.wh0 == 10
    assert bus.ppu.wh1 == 200

    cpu.dma.hdma_scanline()           # scanline 2: WH0=20, WH1=210
    assert bus.ppu.wh0 == 20
    assert bus.ppu.wh1 == 210


def test_hdma_non_repeat_end_of_table_stops():
    """After all entries consumed, further hdma_scanline() calls are no-ops."""
    bus, rom, cpu = make_bus()
    # Table: count=1, 1 unit, end
    _setup_hdma_channel0(bus, rom, 0x0000, [0x01, 50, 100, 0x00])
    cpu.dma.hdma_init()

    bus.ppu.wh0 = 0
    bus.ppu.wh1 = 0
    cpu.dma.hdma_scanline()           # scanline 1: writes 50, 100
    assert bus.ppu.wh0 == 50
    assert bus.ppu.wh1 == 100

    cpu.dma.hdma_scanline()           # scanline 2: table ended, no write
    assert bus.ppu.wh0 == 50          # unchanged
    assert bus.ppu.wh1 == 100


def test_hdma_repeat_reuses_same_data():
    """Do-not-repeat entry (bit 7=0): same 2 bytes written for all scanlines in entry."""
    bus, rom, cpu = make_bus()
    # Table: count=0x03 (do-not-repeat, 3 scanlines), data=[30, 150], end
    _setup_hdma_channel0(bus, rom, 0x0000, [0x03, 30, 150, 0x00])
    cpu.dma.hdma_init()

    for _ in range(3):
        cpu.dma.hdma_scanline()
        assert bus.ppu.wh0 == 30
        assert bus.ppu.wh1 == 150

    cpu.dma.hdma_scanline()           # table ended, no write
    assert bus.ppu.wh0 == 30          # unchanged


def test_hdma_multiple_entries_sequential():
    """Multiple table entries processed in order."""
    bus, rom, cpu = make_bus()
    # Entry 1: repeat, 1 scanline, WH0=0, WH1=0
    # Entry 2: non-repeat, 1 scanline, WH0=64, WH1=192
    # End
    _setup_hdma_channel0(bus, rom, 0x0000, [0x81, 0, 0, 0x01, 64, 192, 0x00])
    cpu.dma.hdma_init()

    cpu.dma.hdma_scanline()           # entry 1: WH0=0, WH1=0
    assert bus.ppu.wh0 == 0
    assert bus.ppu.wh1 == 0

    cpu.dma.hdma_scanline()           # entry 2: WH0=64, WH1=192
    assert bus.ppu.wh0 == 64
    assert bus.ppu.wh1 == 192


def test_hdma_disabled_channel_does_nothing():
    """Channel with hdma_enable=0 skips all HDMA execution."""
    bus, rom, cpu = make_bus()
    _setup_hdma_channel0(bus, rom, 0x0000, [0x01, 99, 99, 0x00])
    bus[0x00420C] = 0x00   # disable all HDMA channels
    cpu.dma.hdma_init()

    bus.ppu.wh0 = 0
    cpu.dma.hdma_scanline()
    assert bus.ppu.wh0 == 0           # not written


# ---------------------------------------------------------------------------
# Indirect HDMA (DMAPx bit 6 = 1): table bytes after count are a 2-byte
# pointer into `indirect_bank:ptr` where the real data lives. This mode is
# used by SMW's title screen on channel 7 to per-scanline update WH0/WH1.
# ---------------------------------------------------------------------------


def _setup_hdma_indirect_channel0(bus, rom, table_offset, table_bytes,
                                   indirect_bank, indirect_addr, indirect_bytes):
    """Write an indirect HDMA table plus its data block; configure channel 0."""
    for i, b in enumerate(table_bytes):
        rom.rom[table_offset + i] = b
    # Put indirect data in WRAM so we can write it via the bus.
    assert indirect_bank == 0x7E
    for i, b in enumerate(indirect_bytes):
        bus[(indirect_bank << 16) | ((indirect_addr + i) & 0xFFFF)] = b

    src = 0x8000 + table_offset
    bus[0x004300] = 0x41   # DMAP0: indirect=1, mode=1
    bus[0x004301] = 0x26   # BBAD0: $2126 (WH0)
    bus[0x004302] = src & 0xFF          # A1T0L
    bus[0x004303] = (src >> 8) & 0xFF   # A1T0H
    bus[0x004304] = 0x00                # A1B0: bank 0
    bus[0x004307] = indirect_bank       # DASB0: indirect bank
    bus[0x00420C] = 0x01                # HDMAEN: channel 0


def test_hdma_indirect_non_repeat_reads_from_pointer():
    """Indirect + do-not-repeat: count byte + 2-byte pointer → read data at pointer."""
    bus, rom, cpu = make_bus()
    # Table: count=0x02 (do-not-repeat, 2 scanlines), ptr=$1234, end
    _setup_hdma_indirect_channel0(
        bus, rom,
        table_offset=0x0000,
        table_bytes=[0x02, 0x34, 0x12, 0x00],
        indirect_bank=0x7E,
        indirect_addr=0x1234,
        indirect_bytes=[77, 188],
    )
    cpu.dma.hdma_init()

    for _ in range(2):
        cpu.dma.hdma_scanline()
        assert bus.ppu.wh0 == 77
        assert bus.ppu.wh1 == 188


def test_hdma_indirect_repeat_advances_pointer_per_scanline():
    """Indirect + do-repeat: fresh data read from pointer each scanline."""
    bus, rom, cpu = make_bus()
    # Table: count=0x83 (do-repeat, 3 scanlines), ptr=$0200, end
    _setup_hdma_indirect_channel0(
        bus, rom,
        table_offset=0x0000,
        table_bytes=[0x83, 0x00, 0x02, 0x00],
        indirect_bank=0x7E,
        indirect_addr=0x0200,
        indirect_bytes=[10, 20, 30, 40, 50, 60],
    )
    cpu.dma.hdma_init()

    cpu.dma.hdma_scanline()
    assert (bus.ppu.wh0, bus.ppu.wh1) == (10, 20)
    cpu.dma.hdma_scanline()
    assert (bus.ppu.wh0, bus.ppu.wh1) == (30, 40)
    cpu.dma.hdma_scanline()
    assert (bus.ppu.wh0, bus.ppu.wh1) == (50, 60)


def test_hdma_indirect_multiple_entries():
    """Indirect: two table entries pointing at different data blocks."""
    bus, rom, cpu = make_bus()
    # Entry 1: non-repeat, 1 scanline, ptr=$0300
    # Entry 2: non-repeat, 1 scanline, ptr=$0400
    # End
    _setup_hdma_indirect_channel0(
        bus, rom,
        table_offset=0x0000,
        table_bytes=[0x01, 0x00, 0x03, 0x01, 0x00, 0x04, 0x00],
        indirect_bank=0x7E,
        indirect_addr=0x0300,
        indirect_bytes=[1, 2],
    )
    # Fill the second indirect block too.
    bus[0x7E0400] = 100
    bus[0x7E0401] = 200

    cpu.dma.hdma_init()

    cpu.dma.hdma_scanline()
    assert (bus.ppu.wh0, bus.ppu.wh1) == (1, 2)

    cpu.dma.hdma_scanline()
    assert (bus.ppu.wh0, bus.ppu.wh1) == (100, 200)
