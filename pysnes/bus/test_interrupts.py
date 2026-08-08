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

from types import SimpleNamespace

from ..apu import Apu
from ..controller import Controller
from ..cpu import Cpu
from ..ppu import Ppu
from ..rom import HardwareVectors, InterruptVectors, MappingMode
from ..scheduler import Scheduler
from .bus import Bus

# ---------------------------------------------------------------------------
# Helpers (shared with other test modules)
# ---------------------------------------------------------------------------

ROM_SIZE = 512 * 1024


class StubRom:
    def __init__(self, size=ROM_SIZE):
        self.rom = bytearray(size)
        self.snes_header = SimpleNamespace(mapping_mode=MappingMode.LOROM)
        self.hardware_vectors = HardwareVectors(
            native=InterruptVectors(
                cop=0x8000,
                brk=0x8000,
                abort=0x8000,
                nmi=0x8000,
                reset=0,
                irq=0x8000,
            ),
            emulation=InterruptVectors(
                cop=0x8000,
                brk=0,
                abort=0x8000,
                nmi=0x8000,
                reset=0x8000,
                irq=0x8000,
            ),
        )

    def read(self, addr):
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
    bus.write(0x004200, 0x80)
    assert cpu.status.nmi_enable is True


def test_nmitimen_disables_nmi():
    bus, cpu = make_bus()
    bus.write(0x004200, 0x80)
    bus.write(0x004200, 0x00)
    assert cpu.status.nmi_enable is False


def test_nmitimen_hirq_enable():
    bus, cpu = make_bus()
    bus.write(0x004200, 0x10)
    assert cpu.status.hirq_enable is True
    assert cpu.status.irq_enable is True


def test_nmitimen_virq_enable():
    bus, cpu = make_bus()
    bus.write(0x004200, 0x20)
    assert cpu.status.virq_enable is True
    assert cpu.status.irq_enable is True


def test_nmitimen_hirq_and_virq_both_set_irq_enable():
    bus, cpu = make_bus()
    bus.write(0x004200, 0x30)
    assert cpu.status.irq_enable is True


def test_nmitimen_neither_hirq_nor_virq_clears_irq_enable():
    bus, cpu = make_bus()
    bus.write(0x004200, 0x30)
    bus.write(0x004200, 0x00)
    assert cpu.status.irq_enable is False


def test_nmitimen_auto_joypad_read_enable():
    bus, cpu = make_bus()
    bus.write(0x004200, 0x01)
    assert cpu.status.auto_joypad_read_enable is True


# ---------------------------------------------------------------------------
# NMI rising-edge behaviour
# ---------------------------------------------------------------------------


def test_nmi_rising_edge_sets_pending_when_enabled():
    bus, cpu = make_bus()
    bus.write(0x004200, 0x80)  # enable NMI
    cpu.nmi_rising_edge()
    assert cpu._nmi_pending is True


def test_nmi_rising_edge_does_not_set_pending_when_disabled():
    bus, cpu = make_bus()
    # NMI disabled by default
    cpu.nmi_rising_edge()
    assert cpu._nmi_pending is False


def test_nmi_enable_with_line_already_high_triggers_immediately():
    """Enabling NMI while nmi_line is already asserted triggers a rising
    edge."""
    bus, cpu = make_bus()
    cpu.status.nmi_line = True
    # Writing 0x80 to NMITIMEN while nmi_line is high should trigger immediately
    bus.write(0x004200, 0x80)
    assert cpu._nmi_pending is True


def test_nmi_enable_with_line_low_does_not_trigger():
    bus, cpu = make_bus()
    cpu.status.nmi_line = False
    bus.write(0x004200, 0x80)
    assert cpu._nmi_pending is False


def test_raise_nmi_sets_nmi_line():
    bus, cpu = make_bus()
    bus.write(0x004200, 0x80)
    bus.raise_nmi()
    assert cpu.status.nmi_line is True


def test_lower_nmi_does_not_clear_nmi_line():
    """Per SNES hardware, V-Blank end does not auto-clear $4210 bit 7.

    lower_nmi() is a no-op on the NMI flag; the flag persists until the
    CPU reads $4210 (see test_rdnmi_bit7_persists_through_vblank_end).
    """
    bus, cpu = make_bus()
    bus.raise_nmi()
    bus.lower_nmi()
    assert cpu.status.nmi_line is True


# ---------------------------------------------------------------------------
# RDNMI ($4210)
# ---------------------------------------------------------------------------


def test_rdnmi_read_clears_nmi_line():
    bus, cpu = make_bus()
    cpu.status.nmi_line = True
    _ = bus.read(0x004210)
    assert cpu.status.nmi_line is False


def test_rdnmi_read_while_line_low_leaves_it_low():
    bus, cpu = make_bus()
    cpu.status.nmi_line = False
    _ = bus.read(0x004210)
    assert cpu.status.nmi_line is False


def test_rdnmi_bit7_reflects_nmi_line():
    bus, cpu = make_bus()
    cpu.status.nmi_line = True
    val = bus.read(0x004210)
    assert val & 0x80


def test_rdnmi_bit7_clear_when_line_low():
    bus, cpu = make_bus()
    cpu.status.nmi_line = False
    val = bus.read(0x004210)
    assert not (val & 0x80)


def test_rdnmi_bit7_persists_through_vblank_end():
    """Per SNES spec, $4210 bit 7 is set at V-Blank start and cleared ONLY by
    a read of $4210. V-Blank end does NOT auto-clear it."""
    bus, cpu = make_bus()
    bus.raise_nmi()  # simulate V-Blank start
    assert cpu.status.nmi_line is True
    bus.lower_nmi()  # simulate V-Blank end
    # Hardware: bit 7 should still be set until the game reads $4210.
    assert cpu.status.nmi_line is True, (
        "RDNMI bit 7 should persist through V-Blank end; only a $4210 read "
        "clears it"
    )
    # Now reading $4210 clears it.
    _ = bus.read(0x004210)
    assert cpu.status.nmi_line is False


# ---------------------------------------------------------------------------
# TIMEUP / IRQ state
# ---------------------------------------------------------------------------


def test_irq_flags_independent_of_nmi():
    """Setting HIRQ enable must not disturb NMI enable and vice versa."""
    bus, cpu = make_bus()
    bus.write(0x004200, 0x80)  # NMI only
    assert cpu.status.nmi_enable is True
    assert cpu.status.hirq_enable is False
    assert cpu.status.irq_enable is False

    bus.write(0x004200, 0x10)  # HIRQ only
    assert cpu.status.nmi_enable is False
    assert cpu.status.hirq_enable is True
    assert cpu.status.irq_enable is True


# ---------------------------------------------------------------------------
# interrupt() cycle counting
# ---------------------------------------------------------------------------


def test_interrupt_advances_cycles_native_mode():
    """interrupt() must count bus cycles (not return a flat 1 MC)."""
    bus, cpu = make_bus()
    # native mode: 8 bus cycles (2 idle + push PBR/PCH/PCL/P + 2 vector reads)
    cpu.EF = False
    cpu.S.w = 0x01FF
    cycles_before = cpu.cycles
    cpu.interrupt(0xFFEA)  # native NMI vector
    elapsed_mc = cpu.cycles - cycles_before
    # 2 idles (6 MC each) + 4 writes to stack in slow RAM (8 MC each) + 2 reads
    # from ROM $FFxx (8 MC each) = 12 + 32 + 16 = 60 MC
    assert elapsed_mc == 60, f"Expected 60 MC, got {elapsed_mc}"


def test_interrupt_advances_cycles_emulation_mode():
    """Emulation mode skips PBR push: 7 bus cycles total."""
    bus, cpu = make_bus()
    # emulation mode: 7 bus cycles (2 idle + push PCH/PCL/P + 2 vector reads)
    cpu.EF = True
    cpu.S.w = 0x01FF
    cycles_before = cpu.cycles
    cpu.interrupt(0xFFFA)  # emulation NMI vector
    elapsed_mc = cpu.cycles - cycles_before
    # 2 idles (6 MC each) + 3 writes to stack in slow RAM (8 MC each) + 2 reads
    # from ROM $FFxx (8 MC each) = 12 + 24 + 16 = 52 MC
    assert elapsed_mc == 52, f"Expected 52 MC, got {elapsed_mc}"


def test_interrupt_returns_correct_mc_for_scheduler():
    """_step() relies on interrupt() return value to reschedule itself."""
    bus, cpu = make_bus()
    cpu.EF = False
    cpu.S.w = 0x01FF
    mc = cpu.interrupt(0xFFEA)
    assert mc == 60, f"interrupt() must return elapsed MC, got {mc}"


def test_interrupt_resets_pb_to_zero_native():
    """Native NMI/IRQ entry must force PB to 0 so the handler runs in bank $00.

    Regression: SMW hung after "1 Player Game" because NMI fired while
    DecompressOverworldL2 was executing in bank $04; the handler then ran at
    $04:xxxx (data) instead of $00:xxxx (real handler), corrupting state.
    """
    bus, cpu = make_bus()
    cpu.EF = False
    cpu.PC.b = 0x04
    cpu.PC.w = 0xDD85
    cpu.S.w = 0x01FF
    # Place vector low/high at ROM offset $7FEA-$7FEB (LoROM map of
    # $00:FFEA-FFEB).
    bus.rom.rom[0x7FEA] = 0x6A
    bus.rom.rom[0x7FEB] = 0x81
    cpu.interrupt(0xFFEA)
    assert cpu.PC.b == 0x00, (
        f"PB must be 0 after interrupt, got ${cpu.PC.b:02X}"
    )
    assert cpu.PC.w == 0x816A
    # The original PBR ($04) must have been pushed before being cleared.
    assert bus.read(0x0001FF) == 0x04, (
        f"PBR not pushed; stack top = ${bus.read(0x0001FF):02X}"
    )


def test_interrupt_pb_is_zero_in_emulation_mode():
    """Emulation mode also lands in bank 0; no PBR is pushed."""
    bus, cpu = make_bus()
    cpu.EF = True
    cpu.PC.b = 0x04  # spurious; emulation should still drop us in bank 0
    cpu.PC.w = 0x1234
    cpu.S.w = 0x01FF
    bus.rom.rom[0x7FFA] = 0x00
    bus.rom.rom[0x7FFB] = 0x90
    cpu.interrupt(0xFFFA)
    assert cpu.PC.b == 0x00
    assert cpu.PC.w == 0x9000


# ---------------------------------------------------------------------------
# H/V IRQ — $4207-$420A target registers
# ---------------------------------------------------------------------------


def test_htime_low_write():
    bus, cpu = make_bus()
    bus.write(0x004208, 0x00)  # clear high bit first
    bus.write(0x004207, 0x80)
    assert cpu.status.htime == 0x080


def test_htime_high_write_only_bit0():
    bus, cpu = make_bus()
    bus.write(0x004207, 0x00)
    bus.write(0x004208, 0xFF)  # only bit 0 retained → HTIME high = 1
    assert cpu.status.htime == 0x100


def test_htime_full_9bit_target():
    bus, cpu = make_bus()
    bus.write(0x004207, 0x55)
    bus.write(0x004208, 0x01)
    assert cpu.status.htime == 0x155


def test_vtime_low_write():
    bus, cpu = make_bus()
    bus.write(0x00420A, 0x00)  # clear high bit first
    bus.write(0x004209, 0xC8)  # 200
    assert cpu.status.vtime == 200


def test_vtime_high_write_only_bit0():
    bus, cpu = make_bus()
    bus.write(0x004209, 0x00)
    bus.write(0x00420A, 0x01)
    assert cpu.status.vtime == 0x100


# ---------------------------------------------------------------------------
# $4211 TIMEUP — read-and-clear IRQ flag
# ---------------------------------------------------------------------------


def test_timeup_read_clears_irq_line():
    bus, cpu = make_bus()
    cpu.status.irq_line = True
    _ = bus.read(0x004211)
    assert cpu.status.irq_line is False


def test_timeup_bit7_reflects_irq_line():
    bus, cpu = make_bus()
    cpu.status.irq_line = True
    val = bus.read(0x004211)
    assert val & 0x80


def test_timeup_bit7_clear_when_line_low():
    bus, cpu = make_bus()
    cpu.status.irq_line = False
    val = bus.read(0x004211)
    assert not (val & 0x80)


# ---------------------------------------------------------------------------
# IRQ dispatch in CPU._step
# ---------------------------------------------------------------------------


def test_irq_pending_fires_interrupt_when_i_flag_clear():
    """_step() must fire IRQ when irq_line is high and IFlag is clear."""
    bus, cpu = make_bus()
    cpu.start(bus.scheduler)
    cpu.IFlag = False
    cpu.EF = True
    cpu.status.irq_line = True
    cpu.S.w = 0x01FF
    # Seed emulation-mode IRQ vector ($FFFE/F) = $8000 via LoROM mapping.
    bus.rom.rom[0x7FFE] = 0x00
    bus.rom.rom[0x7FFF] = 0x80
    bus.scheduler.run_one()
    assert cpu.PC.w == 0x8000
    assert cpu.IFlag is True  # IRQ dispatch sets IFlag


def test_irq_blocked_when_i_flag_set():
    """IRQ line high but I flag set → no interrupt dispatched."""
    bus, cpu = make_bus()
    cpu.start(bus.scheduler)
    cpu.IFlag = True
    cpu.status.irq_line = True
    cpu.S.w = 0x01FF
    cpu.PC.d = 0x008000
    bus.rom.rom[0] = 0xEA  # NOP opcode
    bus.scheduler.run_one()
    assert cpu.PC.w == 0x8001


def test_irq_not_dispatched_when_line_low():
    bus, cpu = make_bus()
    cpu.start(bus.scheduler)
    cpu.IFlag = False
    cpu.status.irq_line = False
    cpu.S.w = 0x01FF
    cpu.PC.d = 0x008000
    bus.rom.rom[0] = 0xEA  # NOP
    bus.scheduler.run_one()
    assert cpu.PC.w == 0x8001


def test_nmi_takes_priority_over_irq():
    """When both NMI and IRQ are pending, NMI wins."""
    bus, cpu = make_bus()
    cpu.start(bus.scheduler)
    cpu.IFlag = False
    cpu.EF = True
    cpu.status.nmi_enable = True
    cpu.nmi_rising_edge()
    cpu.status.irq_line = True
    cpu.S.w = 0x01FF
    bus.scheduler.run_one()
    # NMI consumed, IRQ line still high (NMI doesn't clear it)
    assert cpu._nmi_pending is False
    assert cpu.status.irq_line is True


# ---------------------------------------------------------------------------
# PPU → bus IRQ trigger at H/V match
# ---------------------------------------------------------------------------


def test_vrq_fires_at_vtime_scanline():
    """V-only IRQ: raise line when v_counter reaches VTIME."""
    bus, cpu = make_bus()
    bus.write(0x004209, 10)  # VTIME = 10
    bus.write(0x00420A, 0)
    bus.write(0x004200, 0x20)  # V-IRQ only
    # Simulate scanline advance by calling PPU hblank at VTIME line
    bus.ppu.v_counter = 10
    bus.ppu._irq_check()
    assert cpu.status.irq_line is True


def test_vrq_does_not_fire_on_other_scanlines():
    bus, cpu = make_bus()
    bus.write(0x004209, 10)
    bus.write(0x00420A, 0)
    bus.write(0x004200, 0x20)
    bus.ppu.v_counter = 9
    bus.ppu._irq_check()
    assert cpu.status.irq_line is False


def test_hrq_fires_every_scanline():
    """H-only IRQ: raise on every scanline (at HTIME)."""
    bus, cpu = make_bus()
    bus.write(0x004207, 100)
    bus.write(0x004208, 0)
    bus.write(0x004200, 0x10)  # H-IRQ only
    for v in (0, 50, 100, 200):
        bus.ppu.v_counter = v
        cpu.status.irq_line = False
        bus.ppu._irq_check()
        assert cpu.status.irq_line is True, f"H-IRQ did not fire at v={v}"


def test_hvrq_fires_only_at_vtime():
    """H+V IRQ: raise only at scanline VTIME."""
    bus, cpu = make_bus()
    bus.write(0x004207, 100)
    bus.write(0x004208, 0)
    bus.write(0x004209, 42)
    bus.write(0x00420A, 0)
    bus.write(0x004200, 0x30)  # both
    bus.ppu.v_counter = 41
    bus.ppu._irq_check()
    assert cpu.status.irq_line is False
    bus.ppu.v_counter = 42
    bus.ppu._irq_check()
    assert cpu.status.irq_line is True


def test_irq_disabled_does_not_raise():
    bus, cpu = make_bus()
    bus.write(0x004209, 10)
    bus.write(0x00420A, 0)
    bus.write(0x004200, 0x00)  # all IRQs disabled
    bus.ppu.v_counter = 10
    bus.ppu._irq_check()
    assert cpu.status.irq_line is False


def test_disabling_irq_via_nmitimen_clears_line():
    """Writing NMITIMEN with H/V IRQ both 0 should lower the IRQ line."""
    bus, cpu = make_bus()
    bus.write(0x004200, 0x20)
    cpu.status.irq_line = True
    bus.write(0x004200, 0x00)  # disable H/V IRQ
    assert cpu.status.irq_line is False
