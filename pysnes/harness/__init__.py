"""Programmatic emulator harness for PySNES.

A small wrapper around a headless `PySNES` instance that exposes the operations
needed to drive the emulator from a script or RPC: advance frames, send
controller input, read memory, set breakpoints, and observe register writes.

Example:

    from pysnes.harness import Harness

    with Harness("roms/Super Mario World (U) [!].smc") as h:
        h.run_frames(120)
        h.tap("Start")        # press, then release — produces a clean edge
        h.run_frames(60)
        h.screenshot("title.png")
        print("CGRAM[0..4]:", h.cgram(0, 4).hex())
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Iterable, Optional, Sequence, Union

import numpy as np
import sdl2

from pysnes.harness._png import write_png

# NTSC timing — must match pysnes/ppu/ppu.py
SCREEN_W = 256
SCREEN_H = 224
SCANLINES_PER_FRAME = 262
MC_PER_SCANLINE = 1364
MC_PER_FRAME = SCANLINES_PER_FRAME * MC_PER_SCANLINE  # 357,368

# Same mapping as pysnes/controller/controller.py:30-41
_BUTTON_KEYS = {
    "R": sdl2.SDLK_c,
    "L": sdl2.SDLK_d,
    "X": sdl2.SDLK_s,
    "A": sdl2.SDLK_x,
    "Right": sdl2.SDLK_RIGHT,
    "Left": sdl2.SDLK_LEFT,
    "Down": sdl2.SDLK_DOWN,
    "Up": sdl2.SDLK_UP,
    "Start": sdl2.SDLK_RETURN,
    "Select": sdl2.SDLK_QUOTE,
    "Y": sdl2.SDLK_a,
    "B": sdl2.SDLK_z,
}

# Macro event: (frames_to_run, buttons_held_during_those_frames_or_None)
MacroEvent = tuple[int, Optional[Iterable[str]]]
WriteHook = Callable[["Harness", int, int], None]


def _resolve_buttons(buttons: Union[str, Iterable[str], None]) -> set[int]:
    if buttons is None:
        return set()
    names: Iterable[str] = [buttons] if isinstance(buttons, str) else buttons
    keys: set[int] = set()
    for name in names:
        if name not in _BUTTON_KEYS:
            raise ValueError(
                f"unknown button {name!r}; valid: {sorted(_BUTTON_KEYS)}"
            )
        keys.add(_BUTTON_KEYS[name])
    return keys


class Harness:
    """Headless PySNES driver. See module docstring for usage."""

    def __init__(
        self,
        rom_path: Union[str, Path],
        sram_path: Optional[Union[str, Path]] = None,
        load_state: Optional[Union[str, Path]] = None,
    ):
        # Defer the import so unrelated tools (e.g. the CLI's --help) don't pay
        # the boot cost of importing the emulator.
        from pysnes.pysnes import PySNES  # noqa: PLC0415

        self.rom_path = str(rom_path)
        self._pysnes = PySNES(self.rom_path, settings={"headless": True})
        if sram_path is not None:
            self._pysnes.sram_path = Path(sram_path)
            self._pysnes._load_sram(self._pysnes.bus)
        self._pysnes.cpu.start(self._pysnes.scheduler)
        self._pysnes.ppu.start()
        if load_state is not None:
            self.load_state(load_state)

        # Bus-write hooks: list of (lo, hi, fn). Wrap bus.write once.
        self._hooks: list[tuple[int, int, WriteHook]] = []
        self._original_bus_write = None
        self._closed = False

    # ------------------------------------------------------------------
    # State accessors
    # ------------------------------------------------------------------
    @property
    def frame(self) -> int:
        return int(self._pysnes.ppu.frames)

    @property
    def scanline(self) -> int:
        return int(self._pysnes.ppu.v_counter)

    @property
    def master_clock(self) -> int:
        return int(self._pysnes.scheduler.master_clock)

    @property
    def paused(self) -> bool:
        return bool(self._pysnes.paused)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------
    def run_frames(self, n: int) -> None:
        """Advance the scheduler by exactly `n` frames worth of master clocks."""
        if n <= 0:
            return
        sched = self._pysnes.scheduler
        sched.run_to(sched.master_clock + n * MC_PER_FRAME)

    def run_until(
        self,
        predicate: Callable[["Harness"], bool],
        max_frames: int = 600,
    ) -> bool:
        """Step one frame at a time until `predicate(self)` is truthy.

        Returns True if the predicate matched, False if `max_frames` elapsed
        first. Useful for "run until paused" / "run until we reach scanline X
        on a specific frame" without writing the loop in caller code.
        """
        for _ in range(max_frames):
            self.run_frames(1)
            if predicate(self):
                return True
        return False

    def run_to_scanline(self, v: int) -> None:
        """Within the current frame, advance to the start of scanline `v`.

        Errors if the requested scanline has already passed in this frame.
        """
        if not (0 <= v < SCANLINES_PER_FRAME):
            raise ValueError(f"scanline {v} out of range [0, {SCANLINES_PER_FRAME})")
        if v < self.scanline:
            raise ValueError(
                f"scanline {v} already past in current frame (now at {self.scanline})"
            )
        delta = (v - self.scanline) * MC_PER_SCANLINE
        sched = self._pysnes.scheduler
        sched.run_to(sched.master_clock + delta)

    # ------------------------------------------------------------------
    # Controller input
    # ------------------------------------------------------------------
    def press(self, buttons: Union[str, Iterable[str]]) -> None:
        """Add buttons to the held set without releasing anything else."""
        self._pysnes.controllers[0].pressed_keys |= _resolve_buttons(buttons)

    def release(self, buttons: Union[str, Iterable[str]]) -> None:
        """Remove buttons from the held set."""
        self._pysnes.controllers[0].pressed_keys -= _resolve_buttons(buttons)

    def clear_input(self) -> None:
        self._pysnes.controllers[0].pressed_keys = set()

    def tap(
        self,
        buttons: Union[str, Iterable[str]],
        hold_frames: int = 2,
        gap_frames: int = 1,
    ) -> None:
        """Press for `hold_frames`, release for `gap_frames`.

        Game menus typically only register a button on its rising edge — held
        input across many frames looks like a single press, and back-to-back
        presses without a release gap don't re-trigger. This helper enforces
        the edge.
        """
        keys = _resolve_buttons(buttons)
        self._pysnes.controllers[0].pressed_keys |= keys
        self.run_frames(hold_frames)
        self._pysnes.controllers[0].pressed_keys -= keys
        if gap_frames > 0:
            self.run_frames(gap_frames)

    def play(self, macro: Sequence[MacroEvent]) -> None:
        """Run a macro: a sequence of (frames, buttons_held) events.

        For each event, set the held button set, run that many frames, then
        move on. `buttons` can be None (no input), a single name ("Start"),
        or an iterable of names. The held set is reset between events — if
        you want a button held across two events, list it in both.
        """
        for frames, buttons in macro:
            self._pysnes.controllers[0].pressed_keys = _resolve_buttons(buttons)
            self.run_frames(frames)
        self.clear_input()

    # ------------------------------------------------------------------
    # Screenshot
    # ------------------------------------------------------------------
    def screenshot(self, path: Union[str, Path]) -> None:
        """Write the current framebuffer to a 256×224 PNG.

        Reads `ppu.main_bgs` directly and applies the current INIDISP
        brightness, mirroring the capture path in
        `pysnes/ppu/test_ppu.py:_run_pysnes` but vectorized.
        """
        ppu = self._pysnes.ppu
        brightness = int(ppu.display_brightness)
        # main_bgs is sized for a full 262-scanline frame (line 125 in ppu.py),
        # but only the first 224 are the visible display.
        visible = SCREEN_W * SCREEN_H
        u32 = np.frombuffer(ppu.main_bgs, dtype=np.uint32, count=visible)
        r5 = (u32 >> 27) & 0x1F
        g5 = (u32 >> 19) & 0x1F
        b5 = (u32 >> 11) & 0x1F
        r5 = (r5 * brightness) // 15
        g5 = (g5 * brightness) // 15
        b5 = (b5 * brightness) // 15
        r8 = ((r5 << 3) | (r5 >> 2)).astype(np.uint8)
        g8 = ((g5 << 3) | (g5 >> 2)).astype(np.uint8)
        b8 = ((b5 << 3) | (b5 >> 2)).astype(np.uint8)
        rgb = np.stack([r8, g8, b8], axis=-1).reshape(-1).tobytes()
        write_png(Path(path), rgb, SCREEN_W, SCREEN_H)

    # ------------------------------------------------------------------
    # Memory accessors (no side effects — direct python attribute reads)
    # ------------------------------------------------------------------
    def cgram(self, start: int = 0, end: int = 512) -> bytes:
        return bytes(self._pysnes.ppu.cgram[start:end])

    def vram(self, start: int = 0, length: int = 0x10000) -> bytes:
        return bytes(self._pysnes.ppu.vram[start : start + length])

    def oam(self) -> bytes:
        return bytes(self._pysnes.ppu.oam.oam)

    def wram(self, addr: int, length: int) -> bytes:
        """Read WRAM by absolute SNES address.

        Bus map:
          $7E0000-$7E1FFF → bus.low_ram
          $7E2000-$7EFFFF → bus.high_ram
          $7F0000-$7FFFFF → bus.extended_ram
        """
        bus = self._pysnes.bus
        out = bytearray()
        for i in range(length):
            a = addr + i
            if 0x7E0000 <= a <= 0x7E1FFF:
                out.append(bus.low_ram[a - 0x7E0000])
            elif 0x7E2000 <= a <= 0x7EFFFF:
                out.append(bus.high_ram[a - 0x7E2000])
            elif 0x7F0000 <= a <= 0x7FFFFF:
                out.append(bus.extended_ram[a - 0x7F0000])
            else:
                raise ValueError(f"address ${a:06X} not in WRAM range")
        return bytes(out)

    # ------------------------------------------------------------------
    # Register snapshots
    # ------------------------------------------------------------------
    def cpu_state(self) -> dict[str, Any]:
        c = self._pysnes.cpu
        return {
            "PC": c.PC.d,
            "A": c.A.w,
            "X": c.X.w,
            "Y": c.Y.w,
            "D": c.D.w,
            "S": c.S.w,
            "P": c.P,
            "DB": c.DB.l,
            "PB": c.PC.b,
            "EF": int(c.EF),
        }

    def ppu_state(self) -> dict[str, Any]:
        p = self._pysnes.ppu
        return {
            "frame": int(p.frames),
            "v_counter": int(p.v_counter),
            "h_counter": int(p.h_counter),
            "bgmode": int(p._bgmode),
            "display_brightness": int(p.display_brightness),
            "display_disable": bool(p.display_disable),
            "field": int(p.field),
        }

    # ------------------------------------------------------------------
    # Breakpoints (reuses the existing debugger hook)
    # ------------------------------------------------------------------
    def set_breakpoint(self, addr: int) -> None:
        if addr not in self._pysnes.debugger._breakpoints:
            self._pysnes.debugger.toggle_breakpoint(addr)

    def clear_breakpoint(self, addr: int) -> None:
        if addr in self._pysnes.debugger._breakpoints:
            self._pysnes.debugger.toggle_breakpoint(addr)

    def run_until_break(self, max_frames: int = 600) -> bool:
        """Resume and run until the CPU hits a breakpoint or budget runs out."""
        self._pysnes.paused = False
        for _ in range(max_frames):
            self.run_frames(1)
            if self._pysnes.paused:
                return True
        return False

    # ------------------------------------------------------------------
    # Bus-write hooks
    # ------------------------------------------------------------------
    def on_write(self, addr: int, fn: WriteHook) -> None:
        self.on_write_range(addr, addr, fn)

    def on_write_range(self, lo: int, hi: int, fn: WriteHook) -> None:
        """Fire `fn(harness, addr, value)` on every bus write whose address
        falls in [lo, hi] (inclusive).

        If both bounds fit in the low 16 bits (lo, hi < 0x10000), the match
        is bank-insensitive — i.e. `on_write_range(0x2121, 0x2122, ...)` fires
        for writes from any bank, which is what you almost always want for
        I/O registers ($2100-$5FFF). Pass a 24-bit range if you really need
        a specific bank.

        Hook callbacks fire synchronously inside the write — `harness.frame`
        and `harness.scanline` reflect the PPU state at the moment of write.
        """
        if not self._hooks:
            self._install_bus_wrapper()
        self._hooks.append((lo, hi, fn))

    def _install_bus_wrapper(self) -> None:
        bus = self._pysnes.bus
        # Cython is disabled at runtime here ("Cython is not enabled, using
        # pure Python modules"), so bus.write is an ordinary bound method we
        # can rebind. Save the original for restoration in close().
        self._original_bus_write = bus.write

        hooks = self._hooks  # captured by closure; mutated in place
        harness = self

        def _wrapped(abs_addr, data):
            # Fire hooks first so they observe pre-write state. Most callers
            # only care about the address+value, but this matches the
            # behavior of a write-watch.
            low = abs_addr & 0xFFFF
            for lo, hi, fn in hooks:
                if hi < 0x10000:
                    # Bank-insensitive (typical for I/O registers)
                    if lo <= low <= hi:
                        fn(harness, abs_addr, data)
                else:
                    if lo <= abs_addr <= hi:
                        fn(harness, abs_addr, data)
            return harness._original_bus_write(abs_addr, data)

        bus.write = _wrapped
        # __setitem__ in pysnes/bus/bus.py:679 calls self.write(...), so it
        # automatically picks up the wrapper. No need to patch __setitem__.

    def _uninstall_bus_wrapper(self) -> None:
        if self._original_bus_write is not None:
            self._pysnes.bus.write = self._original_bus_write
            self._original_bus_write = None
        self._hooks.clear()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def close(self) -> None:
        if self._closed:
            return
        self._uninstall_bus_wrapper()
        # Don't auto-save SRAM: harness sessions are diagnostic, and saving
        # would silently mutate the user's save file with whatever input
        # macros did. Callers can call _save_sram() explicitly if needed.
        self._closed = True

    def save_state(self, path: Union[str, Path]) -> None:
        from pysnes import savestate  # noqa: PLC0415
        savestate.save(self._pysnes, str(path))

    def load_state(self, path: Union[str, Path]) -> None:
        from pysnes import savestate  # noqa: PLC0415
        savestate.load(self._pysnes, str(path))

    def __enter__(self) -> "Harness":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
