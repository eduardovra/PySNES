import argparse
from ctypes import byref
import signal
import time
import sys
import platform

import sdl2 as sdl
import cython

from .rom import Rom
from .scheduler import Scheduler
from .bus import Bus
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller
from .video import Video
from .debugger import Debugger
from . import settings as settings_module

if cython.compiled:
    print("Cython is enabled, using compiled modules.")
else:
    print("Cython is not enabled, using pure Python modules.")


class PySNES:
    def __init__(self, rom_file_path: str, settings: dict | None = None) -> None:
        if settings is None:
            settings = settings_module.load()
        self.settings = settings

        rom = Rom(rom_file_path)
        self.rom_name = rom.rom_file_name
        self.scheduler = Scheduler()
        self.apu = Apu()
        self.cpu = Cpu(rom.hardware_vectors)
        self.ppu = Ppu()
        self.controllers = [Controller(), Controller(disabled=True)]
        bus = Bus(rom, self.cpu, self.apu, self.ppu, self.controllers, self.scheduler)
        self.cpu.attach(bus)
        self.cpu.trace_enabled = False
        self.ppu.attach(self.scheduler, bus)
        self.bus = bus
        self.debugger = Debugger(self)
        self.debugger.attach()
        self.video = Video()

        self.video.initialize(headless=settings.get("headless", False))
        self.video.set_window_title(f"PySNES - {self.rom_name}")

        self.event = sdl.SDL_Event()

        # Reset PC to the address in the cartridge reset vector
        self.cpu.PC.w = rom.hardware_vectors["emulation"]["RESET"]

        # Emulator state
        self.running = True
        self.paused = False
        self.frame_time = 0.0
        self.frame_fps = 0.0

        # Signal-triggered actions (set flag in handler, execute in main loop)
        self._screenshot_requested = False
        self._dump_requested = False
        signal.signal(signal.SIGUSR1, self._handle_sigusr1)
        signal.signal(signal.SIGUSR2, self._handle_sigusr2)

        # CPU trace: compare against bsnes reference
        self._trace_file = None
        self._trace_ref = None
        self._trace_count = 0
        self._trace_limit = 100_000
        self._trace_diverged = False

    def _handle_sigusr1(self, _signum, _frame):
        self._screenshot_requested = True

    def _handle_sigusr2(self, _signum, _frame):
        self._dump_requested = True

    def _do_screenshot(self):
        path = "screenshot.bmp"
        self.video.save_screenshot(path)
        print(f"Screenshot saved to {path}", flush=True)

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
        print(f"Memory dumps saved: vram_dump.bin ({len(vram)}B), cgram_dump.bin ({len(cgram)}B), wram_dump.bin ({len(wram)}B)", flush=True)

    def start_trace(self, ref_path: str):
        """Open trace log file and bsnes reference for comparison."""
        try:
            self._trace_file = open("cpu_trace.log", "w")
            self._trace_ref = open(ref_path, "r")
            self.cpu.trace_enabled = True
            print(f"CPU trace started (limit {self._trace_limit} instructions, ref: {ref_path})", flush=True)
        except FileNotFoundError as e:
            print(f"Warning: Could not open trace reference: {e}", flush=True)
            self._trace_ref = None

        # Wrap cpu._step so we can check the trace after each instruction
        original_step = self.cpu._step
        pysnes = self

        def traced_step():
            original_step()
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
            f"A:{self.cpu.A.value:04X} X:{self.cpu.X.value:04X} Y:{self.cpu.Y.value:04X} "
            f"S:{self.cpu.S.value:04X} D:{self.cpu.D.value:04X} DB:{self.cpu.DB.value:02X} "
            f"{flags}"
        )

    def _check_trace(self):
        """Write one trace line and compare against reference. Continues past divergence."""
        if self._trace_count >= self._trace_limit:
            return

        pc = self.cpu.PC.d
        self._trace_count += 1

        if self._trace_file:
            line = self._format_trace_line()
            self._trace_file.write(line + "\n")

            # Compare against reference (up to first divergence only)
            if not self._trace_diverged and self._trace_ref:
                ref_line = self._trace_ref.readline()
                while ref_line and ref_line.startswith(".."):
                    ref_line = self._trace_ref.readline()
                if ref_line:
                    ref_line = ref_line.rstrip()
                    if line[:6].lower() != ref_line[:6].lower():
                        print(f"\n*** TRACE DIVERGENCE at instruction {self._trace_count} ***", flush=True)
                        print(f"  OUR: {line}", flush=True)
                        print(f"  REF: {ref_line}", flush=True)
                        self._trace_diverged = True
                        self._trace_file.flush()

        # Periodic PC report to spot infinite loops
        if self._trace_count % 10_000 == 0:
            print(f"[trace {self._trace_count}] PC=0x{pc:06X} MC={self.scheduler.master_clock}", flush=True)

        if self._trace_count >= self._trace_limit:
            print(f"Trace limit reached ({self._trace_limit} instructions).", flush=True)
            apu = self.bus.apu
            print(f"APU state: PC=0x{apu.PC:04X} A={apu.A:02X} X={apu.X:02X} Y={apu.Y:02X} S={apu.S:02X}", flush=True)
            print(f"  ports_r={list(apu.ports_r)} ports_w={list(apu.ports_w)}", flush=True)
            print(f"  last_synced_mc={apu._last_synced_mc} scheduler_mc={self.scheduler.master_clock}", flush=True)
            if self._trace_file:
                self._trace_file.flush()

    def main(self):
        """Main loop driven by the event scheduler."""
        MC_PER_FRAME: int = 262 * 1364

        self.cpu.start(self.scheduler)
        self.ppu.start()

        print(f"PID: {__import__('os').getpid()}", flush=True)

        frame_start = time.time()

        try:
            while self.running:
                if not self.paused:
                    frame_end = self.scheduler.master_clock + MC_PER_FRAME
                    self.scheduler.run_to(frame_end)

                    self.video.draw_textures(self.ppu.main_bgs)
                    self.video.update_screen()

                    self.frame_time = time.time() - frame_start
                    if self.frame_time > 0:
                        self.frame_fps = 1 / self.frame_time
                    frame_start = time.time()

                    self.video.set_window_title(f"PySNES - {self.rom_name} | {self.frame_fps:.1f} FPS")

                # Handle signal-triggered actions
                if self._screenshot_requested:
                    self._screenshot_requested = False
                    self._do_screenshot()
                if self._dump_requested:
                    self._dump_requested = False
                    self._do_memory_dump()

                if self.paused:
                    self.debugger.drain_commands()

                self.process_inputs()

        finally:
            if self._trace_file:
                self._trace_file.close()
            if self._trace_ref:
                self._trace_ref.close()
            self.video.teardown_sdl()

    def process_inputs(self):
        if not self.video.window:
            return
        while sdl.SDL_PollEvent(byref(self.event)) != 0:
            if self.event.type == sdl.SDL_QUIT:
                self.running = False
                return
            elif self.event.type == sdl.SDL_KEYUP:
                self.controllers[0].pressed_keys.discard(self.event.key.keysym.sym)
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
                elif self.event.key.keysym.sym == sdl.SDLK_F12:
                    self.debugger.open_window()


def print_python_info():
    print(f"Python: {sys.version}")
    print(f"Implementation: {platform.python_implementation()}")
    print()


def main():
    print_python_info()

    parser = argparse.ArgumentParser(description="PySNES - SNES emulator")
    parser.add_argument("rom", help="Path to ROM file (.smc/.sfc)")
    parser.add_argument("--trace", metavar="REF", help="Enable CPU trace comparison against reference log")
    args = parser.parse_args()

    pysnes = PySNES(args.rom)

    if args.trace:
        pysnes.start_trace(args.trace)

    pysnes.main()

    pysnes.video.teardown_sdl()


if __name__ == "__main__":
    main()
