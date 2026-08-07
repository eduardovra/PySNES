"""
Tests for Debugger logic — covers the code paths triggered by every UI button.

Buttons enqueue commands via _cmd_queue; drain_commands() is the consumer.
These tests drive drain_commands() directly, so no Tkinter display is needed.
"""

import threading

import pytest

from .debugger import Debugger, BreakpointHit


# ---------------------------------------------------------------------------
# Minimal stubs
# ---------------------------------------------------------------------------


class _PC:
    def __init__(self, addr: int = 0x008000):
        self.d = addr


class _Cpu:
    def __init__(self):
        self.PC = _PC()
        self.MFlag = True
        self.XFlag = True
        self.trace_enabled = False
        self._steps: int = 0

    def _step(self):
        self._steps += 1


class _Scheduler:
    """Minimal scheduler: run_one() calls cpu._step() once."""

    def __init__(self, cpu: _Cpu):
        self._cpu = cpu
        self.master_clock = 0
        self._queue: list = []  # empty — no stale events to pop

    def run_one(self):
        self._cpu._step()


class _RealisticScheduler:
    """
    Scheduler that captures function references at schedule time, just like the
    real Scheduler.  This is critical for reproducing the stale-reference bug:
    when step_one_instruction() installs the hook AFTER the CPU has already
    scheduled its next step, the event in the queue still holds _original_step,
    so the first run_one() fires it directly, bypassing the hook.
    """

    def __init__(self):
        self._queue: list = []
        self.master_clock: int = 0

    def add(self, delay: int, fn) -> None:
        self._queue.append((self.master_clock + delay, fn))
        self._queue.sort(key=lambda x: x[0])  # keep ordered by time

    def run_one(self) -> None:
        t, fn = self._queue.pop(0)
        self.master_clock = t
        fn()

    def peek_fn(self):
        return self._queue[0][1] if self._queue else None


class _RealisticCpu:
    """
    CPU that reschedules itself via the scheduler, exactly like the real CPU.
    The key line is `scheduler.add(mc, self._step)` — `self._step` is evaluated
    at call time and captures the current instance attribute.
    """

    def __init__(self, scheduler: _RealisticScheduler):
        self._sched = scheduler
        self.PC = _PC()
        self.MFlag = True
        self.XFlag = True
        self.trace_enabled = False
        self._steps: int = 0

    def _step(self) -> None:
        self._steps += 1
        self._sched.add(6, self._step)  # reschedules self._step (current attr)


class _PySNES:
    def __init__(self):
        self.paused = False
        self.cpu = _Cpu()
        self.scheduler = _Scheduler(self.cpu)
        self.bus = object()
        self.ppu = object()
        self.apu = object()


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def pysnes():
    return _PySNES()


@pytest.fixture
def debugger(pysnes):
    dbg = Debugger(pysnes)
    dbg.attach()
    return dbg


# ---------------------------------------------------------------------------
# toggle_breakpoint
# ---------------------------------------------------------------------------


def test_toggle_breakpoint_adds(debugger):
    debugger.toggle_breakpoint(0x8000)
    assert 0x8000 in debugger._breakpoints


def test_toggle_breakpoint_removes(debugger):
    debugger.toggle_breakpoint(0x8000)
    debugger.toggle_breakpoint(0x8000)
    assert 0x8000 not in debugger._breakpoints


def test_toggle_breakpoint_installs_hook(debugger, pysnes):
    debugger.toggle_breakpoint(0x8000)
    assert pysnes.cpu._step == debugger._hooked_step


def test_toggle_breakpoint_removes_hook_when_no_breakpoints(debugger, pysnes):
    debugger.toggle_breakpoint(0x8000)
    debugger.toggle_breakpoint(0x8000)
    assert pysnes.cpu._step == debugger._original_step


# ---------------------------------------------------------------------------
# _hooked_step — normal execution (no breakpoint, no step mode)
# ---------------------------------------------------------------------------


def test_hooked_step_normal_calls_original(debugger, pysnes):
    debugger.toggle_breakpoint(
        0x9000
    )  # install hook but breakpoint is elsewhere
    pysnes.cpu.PC.d = 0x8000
    before = pysnes.cpu._steps
    debugger._hooked_step()
    assert pysnes.cpu._steps == before + 1
    assert debugger._instr_count == 1


# ---------------------------------------------------------------------------
# _hooked_step — breakpoint hit
# ---------------------------------------------------------------------------


def test_breakpoint_hit_raises(debugger, pysnes):
    debugger.toggle_breakpoint(0x8000)
    pysnes.cpu.PC.d = 0x8000
    with pytest.raises(BreakpointHit):
        debugger._hooked_step()


def test_breakpoint_hit_pauses_emulator(debugger, pysnes):
    debugger.toggle_breakpoint(0x8000)
    pysnes.cpu.PC.d = 0x8000
    with pytest.raises(BreakpointHit):
        debugger._hooked_step()
    assert pysnes.paused is True


def test_breakpoint_hit_executes_instruction(debugger, pysnes):
    """The instruction at the breakpoint address must still execute."""
    debugger.toggle_breakpoint(0x8000)
    pysnes.cpu.PC.d = 0x8000
    before = pysnes.cpu._steps
    with pytest.raises(BreakpointHit):
        debugger._hooked_step()
    assert pysnes.cpu._steps == before + 1


def test_breakpoint_hit_notifies_window(debugger):
    debugger._window = object()  # any truthy value triggers notification
    debugger.toggle_breakpoint(0x8000)
    debugger._pysnes.cpu.PC.d = 0x8000
    with pytest.raises(BreakpointHit):
        debugger._hooked_step()
    assert not debugger._notify_queue.empty()


# ---------------------------------------------------------------------------
# step_one_instruction
# ---------------------------------------------------------------------------


def test_step_one_instruction_advances_instr_count(debugger):
    before = debugger._instr_count
    debugger.step_one_instruction()
    assert debugger._instr_count == before + 1


def test_step_one_instruction_calls_cpu_step(debugger, pysnes):
    before = pysnes.cpu._steps
    debugger.step_one_instruction()
    assert pysnes.cpu._steps == before + 1


def test_step_one_instruction_does_not_install_hook(debugger, pysnes):
    """step_one_instruction no longer uses the hook mechanism — cpu._step stays as original."""
    debugger.step_one_instruction()
    assert pysnes.cpu._step == debugger._original_step


# ---------------------------------------------------------------------------
# drain_commands — "pause" button
# ---------------------------------------------------------------------------


def test_drain_pause_sets_paused(debugger, pysnes):
    debugger._cmd_queue.put(("pause",))
    debugger.drain_commands()
    assert pysnes.paused is True


def test_drain_pause_notifies(debugger):
    debugger._window = object()
    debugger._cmd_queue.put(("pause",))
    debugger.drain_commands()
    assert not debugger._notify_queue.empty()


# ---------------------------------------------------------------------------
# drain_commands — "continue" button
# ---------------------------------------------------------------------------


def test_drain_continue_clears_paused(debugger, pysnes):
    pysnes.paused = True
    debugger._cmd_queue.put(("continue",))
    debugger.drain_commands()
    assert pysnes.paused is False


# ---------------------------------------------------------------------------
# drain_commands — "step" button
# ---------------------------------------------------------------------------


def test_drain_step_advances_instr_count(debugger):
    before = debugger._instr_count
    done = threading.Event()
    debugger._cmd_queue.put(("step", done))
    debugger.drain_commands()
    assert debugger._instr_count == before + 1


def test_drain_step_sets_event(debugger):
    done = threading.Event()
    debugger._cmd_queue.put(("step", done))
    debugger.drain_commands()
    assert done.is_set()


# ---------------------------------------------------------------------------
# drain_commands — "toggle_bp" (Break at PC / Remove selected buttons)
# ---------------------------------------------------------------------------


def test_drain_toggle_bp_adds_breakpoint(debugger):
    debugger._cmd_queue.put(("toggle_bp", 0x8010))
    debugger.drain_commands()
    assert 0x8010 in debugger._breakpoints


def test_drain_toggle_bp_removes_breakpoint(debugger):
    debugger.toggle_breakpoint(0x8010)
    debugger._cmd_queue.put(("toggle_bp", 0x8010))
    debugger.drain_commands()
    assert 0x8010 not in debugger._breakpoints


def test_drain_toggle_bp_notifies(debugger):
    debugger._window = object()
    debugger._cmd_queue.put(("toggle_bp", 0x8010))
    debugger.drain_commands()
    assert not debugger._notify_queue.empty()


# ---------------------------------------------------------------------------
# drain_commands — multiple commands processed in one call
# ---------------------------------------------------------------------------


def test_drain_processes_all_queued_commands(debugger, pysnes):
    debugger._cmd_queue.put(("pause",))
    debugger._cmd_queue.put(("continue",))
    debugger.drain_commands()
    assert pysnes.paused is False


# ---------------------------------------------------------------------------
# BreakpointHit propagates through a scheduler loop
# ---------------------------------------------------------------------------


def test_breakpoint_exits_scheduler_run_to(pysnes):
    """Simulate the main loop: BreakpointHit raised inside scheduler.run_to()."""
    dbg = Debugger(pysnes)
    dbg.attach()
    dbg.toggle_breakpoint(0x8000)
    pysnes.cpu.PC.d = 0x8000

    # Patch run_to to loop calling cpu._step (like the real scheduler)
    def fake_run_to(target):
        for _ in range(10):
            pysnes.cpu._step()

    pysnes.scheduler.run_to = fake_run_to

    caught = False
    try:
        pysnes.scheduler.run_to(999)
    except BreakpointHit:
        caught = True

    assert caught
    assert pysnes.paused is True
    # Only one instruction should have executed (the one at the breakpoint)
    assert pysnes.cpu._steps == 1


# ---------------------------------------------------------------------------
# Stale scheduler reference bug — step_one_instruction must execute exactly
# one instruction even when the queued event was captured before hook install
# ---------------------------------------------------------------------------


def test_step_one_instruction_executes_exactly_one_instruction_with_realistic_scheduler():
    """
    Reproduces the real-world bug: when step_one_instruction() is called, the
    scheduler queue already holds a reference to _original_step (captured while
    the emulator was running, before the hook was installed).  The first
    run_one() fires _original_step directly, bypassing the hook, so _instr_count
    is not incremented and the loop fires run_one() again — executing a SECOND
    instruction before exiting.

    This test uses _RealisticScheduler (stores function refs at schedule time)
    and _RealisticCpu (reschedules self._step each call) to reproduce the exact
    conditions that exist in the real emulator after a frame completes.
    """
    scheduler = _RealisticScheduler()
    cpu = _RealisticCpu(scheduler)

    pysnes = _PySNES()
    pysnes.cpu = cpu
    pysnes.scheduler = scheduler

    dbg = Debugger(pysnes)
    dbg.attach()
    # After attach(), _install_hooks() set cpu._step = _original_step.
    # Simulate the CPU having scheduled its next step at the end of a frame:
    # this event captures cpu._step at schedule time — i.e. _original_step.
    scheduler.add(0, cpu._step)

    steps_before = cpu._steps
    dbg.step_one_instruction()

    assert cpu._steps - steps_before == 1, (
        f"step_one_instruction() executed {cpu._steps - steps_before} instructions; "
        f"expected exactly 1"
    )
