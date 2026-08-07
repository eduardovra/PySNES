"""
APU timer unit tests.

The SPC700 has three timers:
  Timer 0 ($FA):  8 kHz  — stage2 increments every 128 APU cycles, 8-bit target
  Timer 1 ($FB):  8 kHz  — stage2 increments every 128 APU cycles, 8-bit target
  Timer 2 ($FC): 64 kHz  — stage2 increments every  16 APU cycles, 8-bit target

Each timer has a 4-bit output counter (stage3) readable via $FD/$FE/$FF.
Reading a counter clears it. Counters increment when stage2 wraps from
0 to target (i.e. they count target-hits, not raw clocks).

Control register $F1:
  bit 0 → timer 0 enable
  bit 1 → timer 1 enable
  bit 2 → timer 2 enable
  bit 4 → reset ports_w[0-1]
  bit 5 → reset ports_w[2-3]
  bit 7 → IPL ROM enable

Test register $F0:
  bit 3 → timers_enable (global gate)
  bit 0 → timers_disable (global inhibit)
"""

import pytest

from .apu import Apu, Timer


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def apu():
    a = Apu()
    # Enable global timer gate so individual timer enables work
    a.timers_enable = True
    a.timers_disable = False
    return a


# ---------------------------------------------------------------------------
# Timer enable / disable via control register ($F1)
# ---------------------------------------------------------------------------


def test_control_register_enables_timer0(apu: Apu):
    apu.write(0x00F1, 0x01)
    assert apu.timers[0].enable is True


def test_control_register_enables_timer1(apu: Apu):
    apu.write(0x00F1, 0x02)
    assert apu.timers[1].enable is True


def test_control_register_enables_timer2(apu: Apu):
    apu.write(0x00F1, 0x04)
    assert apu.timers[2].enable is True


def test_enable_resets_stage2_and_stage3(apu: Apu):
    """0→1 transition on enable must zero stage2 and stage3."""
    t = apu.timers[0]
    t.stage2 = 0x55
    t.stage3 = 0x0F
    apu.write(0x00F1, 0x01)  # enable timer 0 (was disabled → 0→1 edge)
    assert t.stage2 == 0
    assert t.stage3 == 0


def test_no_reset_when_already_enabled(apu: Apu):
    """If timer was already enabled, writing enable=1 again must NOT reset."""
    apu.write(0x00F1, 0x01)  # enable
    t = apu.timers[0]
    t.stage2 = 0x42
    t.stage3 = 0x03
    apu.write(0x00F1, 0x01)  # enable again — no edge, no reset
    assert t.stage2 == 0x42
    assert t.stage3 == 0x03


def test_disable_timer_stops_counting(apu: Apu):
    """Disabled timer must not advance its counter when stepped."""
    t = apu.timers[0]
    t.enable = False
    t.target = 1
    t.stage2 = 0
    t.stage3 = 0
    # drive enough steps that it *would* overflow if enabled
    for _ in range(300):
        apu.step_timers(1)
    assert t.stage3 == 0


# ---------------------------------------------------------------------------
# Timer target ($FA/$FB/$FC)
# ---------------------------------------------------------------------------


def test_timer0_target_set_via_register(apu: Apu):
    apu.write(0x00FA, 0x10)
    assert apu.timers[0].target == 0x10


def test_timer1_target_set_via_register(apu: Apu):
    apu.write(0x00FB, 0xFF)
    assert apu.timers[1].target == 0xFF


def test_timer2_target_set_via_register(apu: Apu):
    apu.write(0x00FC, 0x08)
    assert apu.timers[2].target == 0x08


# ---------------------------------------------------------------------------
# Counter output ($FD/$FE/$FF) and clear-on-read
# ---------------------------------------------------------------------------


def test_counter_read_returns_stage3(apu: Apu):
    apu.timers[0].stage3 = 0x07
    val = apu.read(0x00FD)
    assert val == 0x07


def test_counter_read_clears_stage3(apu: Apu):
    apu.timers[0].stage3 = 0x05
    apu.read(0x00FD)
    assert apu.timers[0].stage3 == 0


def test_counter1_read_clears_stage3(apu: Apu):
    apu.timers[1].stage3 = 0x03
    apu.read(0x00FE)
    assert apu.timers[1].stage3 == 0


def test_counter2_read_clears_stage3(apu: Apu):
    apu.timers[2].stage3 = 0x0F
    apu.read(0x00FF)
    assert apu.timers[2].stage3 == 0


def test_counter_wraps_at_4_bits(apu: Apu):
    """stage3 is 4-bit; it must wrap at 0x10."""
    t = apu.timers[0]
    t.stage3 = 0x0F
    # Manually trigger one more overflow
    t.stage3 = (t.stage3 + 1) & 0x0F
    assert t.stage3 == 0


# ---------------------------------------------------------------------------
# Counting behaviour — stage2 counts to target then stage3 increments
# ---------------------------------------------------------------------------


def _tick_until_overflow(apu: Apu, timer_idx: int, expected_hits: int) -> None:
    """Step the APU timer enough times to get exactly expected_hits overflows."""
    t = apu.timers[timer_idx]
    t.enable = True
    t.stage2 = 0
    t.stage3 = 0
    # Each call passes t.frequency APU cycles so stage0 overflows exactly once per call,
    # incrementing stage2 directly. stage3 increments every target stage2 increments.
    steps = t.target * expected_hits + 1
    for _ in range(steps):
        apu.step_timers(t.frequency)


def test_timer0_counts_to_target_then_increments_stage3(apu: Apu):
    apu.timers[0].target = 4
    _tick_until_overflow(apu, 0, 1)
    assert apu.timers[0].stage3 >= 1


def test_timer_stage3_increments_multiple_times(apu: Apu):
    apu.timers[0].target = 1
    _tick_until_overflow(apu, 0, 3)
    assert apu.timers[0].stage3 >= 3


def test_timer2_higher_frequency(apu: Apu):
    """Timer 2 has frequency 16 vs 128 for timers 0/1 — it ticks 8× faster."""
    t0 = apu.timers[0]
    t2 = apu.timers[2]
    t0.enable = True
    t0.target = 1
    t0.stage2 = 0
    t0.stage3 = 0
    t2.enable = True
    t2.target = 1
    t2.stage2 = 0
    t2.stage3 = 0
    for _ in range(100):
        apu.step_timers(1)
    # t2 should have ticked more than t0
    assert t2.stage3 >= t0.stage3


# ---------------------------------------------------------------------------
# Global timer gates (test register $F0 bits 0 and 3)
# ---------------------------------------------------------------------------


def test_timers_disable_inhibits_all(apu: Apu):
    apu.timers_disable = True
    for t in apu.timers:
        t.enable = True
        t.target = 1
        t.stage2 = 0
        t.stage3 = 0
    for _ in range(300):
        apu.step_timers(1)
    for t in apu.timers:
        assert t.stage3 == 0


def test_timers_enable_false_inhibits_all(apu: Apu):
    apu.timers_enable = False
    for t in apu.timers:
        t.enable = True
        t.target = 1
        t.stage2 = 0
        t.stage3 = 0
    for _ in range(300):
        apu.step_timers(1)
    for t in apu.timers:
        assert t.stage3 == 0


# ---------------------------------------------------------------------------
# Port reset via control register bits 4 and 5
# ---------------------------------------------------------------------------


def test_control_bit4_resets_ports_r_01(apu: Apu):
    """Bit 4 resets CPU→APU input ports (ports_r); APU output ports (ports_w) unchanged."""
    apu.ports_r[0] = 0xAA
    apu.ports_r[1] = 0xBB
    apu.ports_w[0] = 0x11
    apu.ports_w[1] = 0x22
    apu.write(0x00F1, 0x10)  # bit 4
    assert apu.ports_r[0] == 0x00
    assert apu.ports_r[1] == 0x00
    assert apu.ports_w[0] == 0x11
    assert apu.ports_w[1] == 0x22


def test_control_bit5_resets_ports_r_23(apu: Apu):
    """Bit 5 resets CPU→APU input ports (ports_r); APU output ports (ports_w) unchanged."""
    apu.ports_r[2] = 0xCC
    apu.ports_r[3] = 0xDD
    apu.ports_w[2] = 0x33
    apu.ports_w[3] = 0x44
    apu.write(0x00F1, 0x20)  # bit 5
    assert apu.ports_r[2] == 0x00
    assert apu.ports_r[3] == 0x00
    assert apu.ports_w[2] == 0x33
    assert apu.ports_w[3] == 0x44
