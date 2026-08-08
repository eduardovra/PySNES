import argparse
import contextlib
import heapq
import pathlib
import platform
import signal
import sys
import time
from collections import deque
from ctypes import byref

import sdl2 as sdl

from . import settings as settings_module
from .apu import Apu
from .audio import AudioSDL2
from .bus import Bus
from .controller import Controller
from .cpu import Cpu
from .debugger import BreakpointHit, Debugger
from .ppu import Ppu
from .rom import Rom
from .scheduler import Scheduler
from .spc_player import SpcPlayer
from .video import Video


class PySNES:
    def __init__(
        self, rom_file_path: str, settings: dict | None = None
    ) -> None:
        if settings is None:
            settings = settings_module.load()
        self.settings = settings

        rom = Rom(rom_file_path)
        self.rom_name = rom.rom_file_name
        self.sram_path = pathlib.Path(rom_file_path).with_suffix(".srm")
        self.scheduler = Scheduler()
        self.apu = Apu()
        self.cpu = Cpu(rom.hardware_vectors)
        self.ppu = Ppu()
        self.controllers = [Controller(), Controller(disabled=True)]
        bus = Bus(
            rom, self.cpu, self.apu, self.ppu, self.controllers, self.scheduler
        )
        self._load_sram(bus)
        self.cpu.attach(bus)
        self.cpu.trace_enabled = False
        self.ppu.attach(self.scheduler, bus)
        self.bus = bus
        self.debugger = Debugger(self)
        self.debugger.attach()
        self.video = Video()

        self.video.initialize(headless=settings.get("headless", False))
        self.video.set_window_title(f"PySNES - {self.rom_name}")

        self.audio = None
        if not settings.get("headless", False):
            try:
                self.audio = AudioSDL2()
                self.audio.initialize()
            except Exception as e:
                print(f"Audio init failed (continuing muted): {e}", flush=True)
        self._audio_frac = 0

        self.event = sdl.SDL_Event()

        # Reset PC to the address in the cartridge reset vector
        self._reset_vector: int = rom.hardware_vectors.emulation.reset
        self.cpu.PC.w = self._reset_vector

        # Emulator state
        self.running = True
        self.paused = False
        self.frame_time = 0.0
        self.frame_fps = 60.0
        self._max_frames: int = settings.get("max_frames", 0)
        self._frame_count: int = 0

        # Signal-triggered actions (set flag in handler, execute in main loop)
        self._screenshot_requested = False
        self._dump_requested = False
        self._save_state_requested = False
        self._load_state_requested = False
        self.state_path = pathlib.Path(rom_file_path).with_suffix(".state")
        signal.signal(signal.SIGUSR1, self._handle_sigusr1)
        signal.signal(signal.SIGUSR2, self._handle_sigusr2)

        # CPU trace: compare against bsnes reference
        self._trace_file = None
        self._trace_ref = None
        self._trace_ring: deque | None = (
            None  # ring-buffer mode; None = stream to file
        )
        self._trace_count = 0
        self._trace_limit = 100_000
        self._trace_diverged = False
        self._trace_active = False

        # APU trace
        self._apu_trace_file = None
        self._apu_trace_ref = None
        self._apu_trace_ring: deque | None = None
        self._apu_trace_diverged = False

    def _load_sram(self, bus):
        n = bus.load_sram(str(self.sram_path))
        if n:
            print(f"SRAM loaded from {self.sram_path} ({n} bytes)", flush=True)

    def _save_sram(self):
        n = self.bus.save_sram(str(self.sram_path))
        if n:
            print(f"SRAM saved to {self.sram_path} ({n} bytes)", flush=True)

    def _handle_sigusr1(self, _signum, _frame):
        self._screenshot_requested = True

    def _handle_sigusr2(self, _signum, _frame):
        self._dump_requested = True

    def _do_screenshot(self):
        path = "screenshot.bmp"
        self.video.save_screenshot(path)
        print(f"Screenshot saved to {path}", flush=True)

    def _do_save_state(self):
        from . import savestate  # noqa: PLC0415

        try:
            savestate.save(self, str(self.state_path))
            print(f"Saved state to {self.state_path}", flush=True)
        except Exception as e:
            print(f"Save state failed: {e}", flush=True)

    def _do_load_state(self):
        from . import savestate  # noqa: PLC0415

        try:
            savestate.load(self, str(self.state_path))
            print(f"Loaded state from {self.state_path}", flush=True)
        except FileNotFoundError:
            print(f"No state file at {self.state_path}", flush=True)
        except Exception as e:
            print(f"Load state failed: {e}", flush=True)

    def _do_memory_dump(self):
        vram = bytes(self.ppu.vram)
        cgram = bytes(self.ppu.cgram)
        wram = bytes(self.bus.low_ram) + bytes(self.bus.high_ram)

        with open("vram_dump.bin", "wb") as f:
            f.write(vram)
        with open("cgram_dump.bin", "wb") as f:
            f.write(cgram)
        with open("wram_dump.bin", "wb") as f:
            f.write(wram)
        print(
            f"Memory dumps saved: vram_dump.bin ({len(vram)}B), "
            f"cgram_dump.bin ({len(cgram)}B), wram_dump.bin ({len(wram)}B)",
            flush=True,
        )

    def reset(self) -> None:
        """Soft reset: restore CPU/APU to power-on state and jump to the reset
        vector."""
        # Drop any queued CPU step events so we can reschedule from scratch.
        # The debugger's _install_hooks rebinds _hooked_step on every call
        # (including from inside _hooked_step at breakpoint fire), so the
        # queued bound method may not be `is`-identical to self.cpu._step.
        # Bound methods with the same __self__ and __func__ compare equal,
        # so use == to match across rebinds.
        q = self.scheduler._queue
        orig = self.debugger._original_step
        cur = self.cpu._step
        q[:] = [e for e in q if not (e[-1] == orig or e[-1] == cur)]
        heapq.heapify(q)
        self.cpu.reset_registers()
        # reset_registers() makes new Reg objects; rebuild the instruction table
        # so its pre-resolved register references point at the live Reg
        # instances.
        self.cpu.load_instructions()
        self.cpu.PC.w = self._reset_vector
        self.apu.reset_registers()
        self.ppu.reset_registers()
        # Reschedule CPU step; _step may be the debugger hook if breakpoints are
        # active.
        self.scheduler.add(0, self.cpu._step)
        self.paused = True
        self.debugger._notify_paused()

    def start_trace(self, ref_path: str | None = None, last: int = 0):
        """Start CPU tracing to cpu_trace.log.

        ref_path: optional bsnes reference log to compare against.
        last: if > 0, keep only the last N lines in a ring buffer and write
              them on exit. If 0, stream every line to the file immediately
              (unlimited).
        """
        # Trace handles stay open until tracing stops, so no context manager.
        self._trace_file = open("cpu_trace.log", "w")  # noqa: SIM115
        self.cpu.trace_enabled = True
        if last > 0:
            self._trace_ring = deque(maxlen=last)
            self._trace_limit = 0  # no early stop in ring mode
            mode_str = f"last {last} lines"
        else:
            self._trace_ring = None
            self._trace_limit = 0  # unlimited streaming
            mode_str = "unlimited"
        if ref_path is not None:
            try:
                self._trace_ref = open(ref_path)  # noqa: SIM115
                print(
                    f"CPU trace started ({mode_str}, ref: {ref_path})",
                    flush=True,
                )
            except FileNotFoundError as e:
                print(
                    f"Warning: Could not open trace reference: {e}", flush=True
                )
        else:
            print(f"CPU trace started ({mode_str})", flush=True)

        # Wrap cpu._step so we can check the trace after each instruction
        original_step = self.cpu._step
        pysnes = self

        def traced_step():
            original_step()
            pysnes._check_trace()

        self.cpu._step = traced_step

    def start_trace_from(self, addr: int, limit: int = 100_000) -> None:
        """Start CPU tracing once PC first reaches `addr`.

        Writes to cpu_trace.log starting at the trigger point. Useful for
        diagnosing hangs that occur after a known entry point (e.g. a game-mode
        routine) without capturing millions of irrelevant boot instructions.
        """
        self._trace_limit = limit
        self._trace_count = 0
        self._trace_active = False
        self.cpu.trace_enabled = True
        print(
            f"[trace] waiting for PC=0x{addr:06X} (limit {limit} "
            "instructions) …",
            flush=True,
        )

        pysnes = self
        original_step = self.cpu._step

        def traced_step():
            original_step()
            pc = pysnes.cpu.PC.d
            if not pysnes._trace_active and pc == addr:
                pysnes._trace_active = True
                pysnes._trace_file = open(  # noqa: SIM115
                    "cpu_trace.log", "w"
                )
                print(
                    f"[trace] triggered at PC=0x{addr:06X} → cpu_trace.log",
                    flush=True,
                )
            if pysnes._trace_active:
                pysnes._check_trace()

        self.cpu._step = traced_step

    def _format_trace_line(self) -> str:
        """Format a CPU trace line matching bsnes format."""
        pc = self.cpu.PC.d
        # Use the last entry in trace_log (most recently executed)
        if self.cpu.trace_log:
            disasm = str(self.cpu.trace_log[-1])
        else:
            disasm = f"{pc:06x} ???"
        p = self.cpu.P
        flags = (
            ("N" if p & 0x80 else ".")
            + ("V" if p & 0x40 else ".")
            + ("1" if p & 0x20 else ".")
            + ("B" if p & 0x10 else ".")
            + ("D" if p & 0x08 else ".")
            + ("I" if p & 0x04 else ".")
            + ("Z" if p & 0x02 else ".")
            + ("C" if p & 0x01 else ".")
        )
        return (
            f"{disasm:<30} "
            f"A:{self.cpu.A.value:04X} X:{self.cpu.X.value:04X} "
            f"Y:{self.cpu.Y.value:04X} "
            f"S:{self.cpu.S.value:04X} D:{self.cpu.D.value:04X} "
            f"DB:{self.cpu.DB.value:02X} "
            f"{flags}"
        )

    def _check_trace(self):
        """Write one trace line and optionally compare against reference."""
        if self._trace_limit and self._trace_count >= self._trace_limit:
            return

        self._trace_count += 1
        line = self._format_trace_line()

        if self._trace_ring is not None:
            self._trace_ring.append(line)
        elif self._trace_file:
            self._trace_file.write(line + "\n")

        # Compare against reference (streaming mode only; up to first
        # divergence)
        if (
            self._trace_ring is None
            and not self._trace_diverged
            and self._trace_ref
        ):
            ref_line = self._trace_ref.readline()
            while ref_line and ref_line.startswith(".."):
                ref_line = self._trace_ref.readline()
            if ref_line:
                ref_line = ref_line.rstrip()
                if line[:6].lower() != ref_line[:6].lower():
                    print(
                        "\n*** TRACE DIVERGENCE at instruction "
                        f"{self._trace_count} ***",
                        flush=True,
                    )
                    print(f"  OUR: {line}", flush=True)
                    print(f"  REF: {ref_line}", flush=True)
                    self._trace_diverged = True
                    if self._trace_file:
                        self._trace_file.flush()

        if self._trace_limit and self._trace_count >= self._trace_limit:
            print(
                f"Trace limit reached ({self._trace_limit} instructions).",
                flush=True,
            )
            if self._trace_file:
                self._trace_file.flush()

    def start_apu_trace(self, ref_path: str | None = None, last: int = 0):
        """Start APU tracing to apu_trace.log.

        ref_path: optional reference log to compare against.
        last: if > 0, keep only the last N lines (ring buffer, written on exit).
              if 0, stream every line to the file immediately.
        """
        # Trace handles stay open until tracing stops, so no context manager.
        self._apu_trace_file = open("apu_trace.log", "w")  # noqa: SIM115
        self.apu.trace_enabled = True
        if last > 0:
            self._apu_trace_ring = deque(maxlen=last)
            mode_str = f"last {last} lines"
        else:
            self._apu_trace_ring = None
            mode_str = "unlimited"
        if ref_path is not None:
            try:
                self._apu_trace_ref = open(ref_path)  # noqa: SIM115
                print(
                    f"APU trace started ({mode_str}, ref: {ref_path})",
                    flush=True,
                )
            except FileNotFoundError as e:
                print(
                    f"Warning: Could not open APU trace reference: {e}",
                    flush=True,
                )
        else:
            print(f"APU trace started ({mode_str})", flush=True)

        original_fae = self.apu.fetch_and_execute
        pysnes = self

        def traced_fae():
            original_fae()
            if pysnes.apu.trace_log:
                pysnes._check_apu_trace(pysnes.apu.trace_log[-1])

        self.apu.fetch_and_execute = traced_fae

    def _check_apu_trace(self, line: str):
        if self._apu_trace_ring is not None:
            self._apu_trace_ring.append(line)
        elif self._apu_trace_file:
            self._apu_trace_file.write(line + "\n")

        if (
            self._apu_trace_ring is None
            and not self._apu_trace_diverged
            and self._apu_trace_ref
        ):
            ref_line = self._apu_trace_ref.readline()
            if ref_line:
                ref_line = ref_line.rstrip()
                if line[:4].lower() != ref_line[:4].lower():
                    print("\n*** APU TRACE DIVERGENCE ***", flush=True)
                    print(f"  OUR: {line}", flush=True)
                    print(f"  REF: {ref_line}", flush=True)
                    self._apu_trace_diverged = True
                    if self._apu_trace_file:
                        self._apu_trace_file.flush()

    def main(self):
        """Main loop driven by the event scheduler."""
        MC_PER_FRAME: int = 262 * 1364
        # Exact NTSC frame period: 21.477272 MHz / (262 lines * 1364 dots) ≈
        # 16.6836 ms
        FRAME_TIME_S: float = MC_PER_FRAME / 21_477_272.0
        _FRAME_HEADROOM_S: float = (
            0.001  # busy-wait the last 1 ms for precision
        )
        # EMA smoothing coefficient for FPS display (≈30-frame window)
        _FPS_ALPHA: float = 1.0 / 30.0

        self.cpu.start(self.scheduler)
        self.ppu.start()

        print(f"PID: {__import__('os').getpid()}", flush=True)

        frame_deadline = time.perf_counter()
        frame_tick = frame_deadline
        _bench_start = frame_deadline if self._max_frames else 0.0

        try:
            while self.running:
                if not self.paused:
                    # Reset deadline after a pause or any large gap so the
                    # emulator doesn't try to catch up across many frames at
                    # once.
                    now = time.perf_counter()
                    if now - frame_deadline > FRAME_TIME_S * 4:
                        frame_deadline = now
                        frame_tick = now

                    frame_end = self.scheduler.master_clock + MC_PER_FRAME
                    # On a breakpoint paused=True is already set: skip the
                    # draw and let the next iteration observe it.
                    with contextlib.suppress(BreakpointHit):
                        self.scheduler.run_to(frame_end)

                    if self.audio is not None:
                        # Ensure the SPC700 has run all its cycles for this
                        # frame. sync_to is normally called lazily from the bus
                        # on APU port access; if the CPU went the whole frame
                        # without touching APU ports the SPC700 would be behind
                        # and DSP register state would be stale.
                        self.apu.sync_to(self.scheduler.master_clock)
                        # Fixed-point accumulator matching Apu.sync_to pattern —
                        # avoids rounding drift. DSP rate = Apu._APU_MC_DEN / 32
                        # = 32000 Hz samples per frame ≈ MC_PER_FRAME *
                        # _APU_MC_DEN / (_APU_MC_NUM * 32) ≈ 532.48
                        self._audio_frac += MC_PER_FRAME * self.apu._APU_MC_DEN
                        n_samples = self._audio_frac // (
                            self.apu._APU_MC_NUM * 32
                        )
                        self._audio_frac %= self.apu._APU_MC_NUM * 32
                        samples = self.apu.generate_audio_frame(n_samples)
                        self.audio.queue_samples(samples)

                    self.video.draw_textures(self.ppu.main_bgs)
                    self.video.update_screen()

                    self._frame_count += 1
                    if (
                        self._max_frames
                        and self._frame_count >= self._max_frames
                    ):
                        elapsed = time.perf_counter() - _bench_start
                        if elapsed > 0:
                            avg_fps = self._frame_count / elapsed
                        else:
                            avg_fps = 0.0
                        print(
                            f"\nBenchmark: {self._frame_count} frames in "
                            f"{elapsed:.2f}s = {avg_fps:.2f} FPS",
                            flush=True,
                        )
                        self.running = False

                    # Wall-clock frame limiter: sleep to the next frame deadline
                    # so the emulator runs at exactly NTSC speed when
                    # computation finishes early. On slow frames we skip the
                    # sleep and start the next frame immediately.
                    frame_deadline += FRAME_TIME_S
                    remaining = frame_deadline - time.perf_counter()
                    if remaining > _FRAME_HEADROOM_S:
                        time.sleep(remaining - _FRAME_HEADROOM_S)
                    while time.perf_counter() < frame_deadline:
                        pass  # busy-wait the last ~1 ms for precision

                    now = time.perf_counter()
                    elapsed = now - frame_tick
                    frame_tick = now
                    actual_fps = 1.0 / elapsed if elapsed > 0 else 0.0
                    self.frame_fps = (
                        self.frame_fps * (1.0 - _FPS_ALPHA)
                        + actual_fps * _FPS_ALPHA
                    )

                    self.video.set_window_title(
                        f"PySNES - {self.rom_name} | {self.frame_fps:.1f} FPS"
                    )

                # Handle signal-triggered actions
                if self._screenshot_requested:
                    self._screenshot_requested = False
                    self._do_screenshot()
                if self._dump_requested:
                    self._dump_requested = False
                    self._do_memory_dump()
                if self._save_state_requested:
                    self._save_state_requested = False
                    self._do_save_state()
                if self._load_state_requested:
                    self._load_state_requested = False
                    self._do_load_state()

                self.debugger.drain_commands()

                self.process_inputs()

        finally:
            self._save_sram()
            if self._trace_ring is not None and self._trace_file:
                for line in self._trace_ring:
                    self._trace_file.write(line + "\n")
                print(
                    f"Trace written ({len(self._trace_ring)} lines).",
                    flush=True,
                )
            if self._trace_file:
                self._trace_file.close()
            if self._trace_ref:
                self._trace_ref.close()
            if self._apu_trace_ring is not None and self._apu_trace_file:
                for line in self._apu_trace_ring:
                    self._apu_trace_file.write(line + "\n")
                print(
                    f"APU trace written ({len(self._apu_trace_ring)} lines).",
                    flush=True,
                )
            if self._apu_trace_file:
                self._apu_trace_file.close()
            if self._apu_trace_ref:
                self._apu_trace_ref.close()
            self.video.teardown_sdl()
            if self.audio is not None:
                self.audio.close()

    def process_inputs(self):
        if not self.video.window:
            return
        while sdl.SDL_PollEvent(byref(self.event)) != 0:
            if self.event.type == sdl.SDL_QUIT:
                self.running = False
                return
            if self.event.type == sdl.SDL_KEYUP:
                self.controllers[0].pressed_keys.discard(
                    self.event.key.keysym.sym
                )
            elif self.event.type == sdl.SDL_KEYDOWN:
                self.controllers[0].pressed_keys.add(self.event.key.keysym.sym)
                if self.event.key.keysym.sym == sdl.SDLK_SPACE:
                    self.paused = not self.paused
                    if self.paused:
                        self.debugger._notify_paused()
                elif self.event.key.keysym.sym == sdl.SDLK_F11:
                    self._screenshot_requested = True
                elif self.event.key.keysym.sym == sdl.SDLK_F10:
                    self._dump_requested = True
                elif self.event.key.keysym.sym == sdl.SDLK_F5:
                    self._save_state_requested = True
                elif self.event.key.keysym.sym == sdl.SDLK_F6:
                    self._load_state_requested = True
                elif self.event.key.keysym.sym == sdl.SDLK_F12:
                    self.debugger.open_window()


def print_python_info():
    print(f"Python: {sys.version}")
    print(f"Implementation: {platform.python_implementation()}")
    print()


def main():
    print_python_info()

    parser = argparse.ArgumentParser(description="PySNES - SNES emulator")
    parser.add_argument(
        "rom", help="Path to ROM file (.smc/.sfc) or SPC audio file (.spc)"
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Write CPU trace to cpu_trace.log (unlimited)",
    )
    parser.add_argument(
        "--trace-ref",
        metavar="REF",
        help="Compare CPU trace against REF log (implies --trace)",
    )
    parser.add_argument(
        "--trace-limit",
        metavar="N",
        type=int,
        default=0,
        help=(
            "Keep only the last N trace lines; written to cpu_trace.log on exit"
        ),
    )
    parser.add_argument(
        "--trace-from",
        metavar="ADDR",
        help="Start CPU trace when PC first reaches ADDR (hex, e.g. 0x00A087)",
    )
    parser.add_argument(
        "--apu-trace",
        action="store_true",
        help="Write APU trace to apu_trace.log (unlimited)",
    )
    parser.add_argument(
        "--apu-trace-ref",
        metavar="REF",
        help="Compare APU trace against REF log (implies --apu-trace)",
    )
    parser.add_argument(
        "--apu-trace-limit",
        metavar="N",
        type=int,
        default=0,
        help="Keep only the last N APU trace lines; written on exit",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run without opening an SDL2 window",
    )
    parser.add_argument(
        "--max-frames",
        metavar="N",
        type=int,
        default=0,
        help="Exit after rendering N frames (0 = run forever)",
    )
    parser.add_argument(
        "--breakpoint",
        metavar="ADDR",
        action="append",
        help="Set breakpoint at address (hex, e.g. 0x00A087); may be repeated",
    )
    args = parser.parse_args()

    if pathlib.Path(args.rom).suffix.lower() == ".spc":
        SpcPlayer(args.rom).run()
        return

    settings = settings_module.load()
    if args.headless:
        settings["headless"] = True
    if args.max_frames:
        settings["max_frames"] = args.max_frames
    pysnes = PySNES(args.rom, settings=settings)

    if args.trace or args.trace_ref or args.trace_limit:
        pysnes.start_trace(args.trace_ref, last=args.trace_limit)
    if args.trace_from:
        pysnes.start_trace_from(int(args.trace_from, 16))
    if args.apu_trace or args.apu_trace_ref or args.apu_trace_limit:
        pysnes.start_apu_trace(args.apu_trace_ref, last=args.apu_trace_limit)
    if args.breakpoint:
        for addr_str in args.breakpoint:
            pysnes.debugger.toggle_breakpoint(int(addr_str, 16))
        print(
            f"Breakpoints set: {[hex(int(a, 16)) for a in args.breakpoint]}",
            flush=True,
        )

    pysnes.main()

    pysnes.video.teardown_sdl()


if __name__ == "__main__":
    main()
