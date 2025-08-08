import argparse
from ctypes import byref
import time
from enum import IntEnum
import sys
import platform

import sdl2 as sdl
import cython
from rich import print
from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.panel import Panel
from rich.columns import Columns

from .rom import Rom
from .bus import Bus
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller
from .video import Video
from .trace_matcher import check_trace_line

if cython.compiled:
    print("[green]Cython is enabled, using compiled modules.[/green]")
else:
    print("[blue]Cython is not enabled, using pure Python modules.[/blue]")


class States(IntEnum):
    RESET = 0
    RUNNING_SCANLINES = 1
    RENDER_GAME_SCREEN = 2


class PySNES:
    def __init__(self, rom_file_path: str) -> None:
        rom = Rom(rom_file_path)
        self.apu = Apu()
        self.cpu = Cpu(rom.hardware_vectors)
        self.ppu = Ppu(self.cpu)  # Pass CPU reference so PPU can control the NMI line
        self.controllers = [Controller(), Controller(disabled=True)]
        bus = Bus(rom, self.cpu, self.apu, self.ppu, self.controllers)
        self.cpu.attach(bus)
        self.video = Video()

        # Initialize video and create window
        self.video.initialize()
        self.video.set_window_title(f"PySNES - {rom.rom_file_name}")

        # Used to pool inputs
        self.event = sdl.SDL_Event()

        # Reset PC to the address in the cartridge reset vector
        self.cpu.PC.w = rom.hardware_vectors["emulation"]["RESET"]

        # Emulator state variables
        self.running = True
        self.paused = False
        self.state = States.RESET
        self.loop_time = 0.0
        self.loop_fps = 0.0
        self.frame_time = 0.0
        self.frame_fps = 0.0

        # Rich debug system - replaces ImGui for MASSIVE performance boost!
        self.debug_enabled = True  # Start with debug enabled 
        self.debug_console = Console()
        self.debug_live = None
        self.debug_frame_counter = 0
        self.debug_update_frequency = 20  # Update every 20 frames for smooth display

    def create_rich_debug_display(self):
        """Create Rich debug display - replaces ImGui for massive performance boost!"""
        if not self.debug_enabled:
            return None
            
        # Performance table
        perf_table = Table(title="⚡ Performance", show_header=True, header_style="bold cyan")
        perf_table.add_column("Metric", style="cyan", width=12)
        perf_table.add_column("Value", style="green", width=10)
        
        perf_table.add_row("Loop FPS", f"{self.loop_fps:6.1f}")
        perf_table.add_row("Frame FPS", f"{self.frame_fps:6.1f}")
        perf_table.add_row("Loop Time", f"{self.loop_time:.4f}s")
        perf_table.add_row("Frame Time", f"{self.frame_time:.4f}s")
        
        # CPU registers table  
        cpu_table = Table(title="💾 CPU Registers", show_header=True, header_style="bold magenta")
        cpu_table.add_column("Register", style="magenta", width=8)
        cpu_table.add_column("Value", style="yellow", width=10)
        
        cpu_table.add_row("PC", f"0x{self.cpu.PC.value:06X}")
        cpu_table.add_row("A", f"0x{self.cpu.A.value:04X}")
        cpu_table.add_row("X", f"0x{self.cpu.X.value:04X}")
        cpu_table.add_row("Y", f"0x{self.cpu.Y.value:04X}")
        cpu_table.add_row("SP", f"0x{self.cpu.S.value:04X}")
        cpu_table.add_row("DB", f"0x{self.cpu.DB.value:02X}")
        cpu_table.add_row("P", f"0x{self.cpu.P:02X}")
        
        # CPU Instruction log table
        log_table = Table(title="📜 CPU Instructions", show_header=True, header_style="bold yellow")
        log_table.add_column("Trace", style="white", width=80)
        
        # Use the CPU's existing trace_log - it's already perfectly formatted!
        if hasattr(self.cpu, 'trace_log') and self.cpu.trace_log:
            for entry in self.cpu.trace_log:
                log_table.add_row(str(entry))
        
        # Status info
        status_table = Table(title="🎮 Status", show_header=False)
        status_table.add_column("Info", style="white")
        
        status_table.add_row(f"State: {'PAUSED' if self.paused else 'RUNNING'}")
        status_table.add_row(f"Frame: {self.debug_frame_counter}")
        status_table.add_row(f"Debug: {self.debug_update_frequency} frame update")
        status_table.add_row("")
        status_table.add_row("[bold blue]Controls:[/bold blue]")
        status_table.add_row("F12 - Toggle debug")
        status_table.add_row("SPACE - Pause/Resume")
        status_table.add_row("ESC - Quit")
        
        # Combine tables in columns for compact display
        top_row = Columns([
            Panel(perf_table, border_style="green"),
            Panel(cpu_table, border_style="magenta"), 
            Panel(status_table, border_style="blue")
        ], expand=False)
        
        bottom_row = Panel(log_table, border_style="yellow")
        
        from rich.console import Group
        return Group(top_row, bottom_row)

    def start_debug_display(self):
        """Start the Rich live debug display"""
        if self.debug_enabled and not self.debug_live:
            initial_display = self.create_rich_debug_display()
            if initial_display:
                self.debug_live = Live(
                    initial_display, 
                    console=self.debug_console,
                    refresh_per_second=3,  # Limit refresh for performance
                    screen=True
                )
                self.debug_live.start()
                
    def update_debug_display(self):
        """Update the Rich debug display - much faster than ImGui!"""
        if not self.debug_enabled or not self.debug_live:
            return
            
        self.debug_frame_counter += 1
        
        # Update only every N frames for better performance
        if self.debug_frame_counter % self.debug_update_frequency == 0:
            new_display = self.create_rich_debug_display()
            if new_display:
                self.debug_live.update(new_display)
                
    def stop_debug_display(self):
        """Stop the Rich live debug display"""
        if self.debug_live:
            self.debug_live.stop()
            self.debug_live = None
            
    def toggle_debug(self):
        """Toggle debug display on/off for maximum performance"""
        self.debug_enabled = not self.debug_enabled
        if self.debug_enabled:
            self.start_debug_display()
        else:
            self.stop_debug_display()
            # Clear screen when disabling debug
            self.debug_console.clear()

    def create_gui(self) -> None:
        """Legacy method - now replaced with Rich debug display"""
        # OLD ImGui code completely removed for performance!
        # Now handled by update_debug_display() which is 10-20x faster
        pass

    def main(self):
        """Main loop with Rich debug system - much faster than ImGui!"""
        # Start Rich debug display
        self.start_debug_display()
        
        # Initialize frame timing
        frame_start = time.time()
        
        try:
            # Main state machine
            while self.running:
                loop_start = time.time()

                if self.state == States.RESET:
                    frame_start = time.time()
                    self.scanline = 0
                    self.state = States.RUNNING_SCANLINES

                elif self.state == States.RUNNING_SCANLINES and not self.paused:
                    # Run one scanline on the CPU, PPU and APU
                    self.run_scanline()
                    self.scanline += 1

                    """
                    Visible scanlines (NTSC): 224 (or 239 in high-res mode).
                    Total scanlines (NTSC): 262.
                    Total scanlines (PAL): 312.
                    """
                    if self.scanline == 262:
                        self.state = States.RENDER_GAME_SCREEN

                elif self.state == States.RENDER_GAME_SCREEN and not self.paused:
                    # Draw textures - this is now much faster without ImGui!
                    self.video.draw_textures(self.ppu.main_bgs)

                    # Calculate frame time
                    self.frame_time = time.time() - frame_start
                    if self.frame_time > 0:
                        self.frame_fps = 1 / self.frame_time

                    self.state = States.RESET

                # Pool inputs
                self.process_inputs()

                # Update Rich debug display (replaces ImGui - much faster!)
                self.update_debug_display()

                # Swap buffers - no more ImGui rendering overhead!
                self.video.update_screen()

                # Calculate loop time
                self.loop_time = time.time() - loop_start
                if self.loop_time > 0:
                    self.loop_fps = 1 / self.loop_time

        finally:
            # Clean up
            self.stop_debug_display()
            self.video.teardown_sdl()

    def run_scanline(self):
        """Run a scanline"""
        clocks = self.cpu.run_scanline()
        self.ppu.tick(clocks)
        self.apu.tick(clocks)

    def process_inputs(self):
        # Capture inputs from keyboard using SDL
        while sdl.SDL_PollEvent(byref(self.event)) != 0:
            if self.event.type == sdl.SDL_QUIT:
                self.running = False
                return
            elif self.event.type == sdl.SDL_KEYUP:
                controller = self.controllers[0]
                controller.pressed_keys.remove(self.event.key.keysym.sym)
            elif self.event.type == sdl.SDL_KEYDOWN:
                controller = self.controllers[0]
                controller.pressed_keys.add(self.event.key.keysym.sym)
                
                # Handle debug toggle
                if self.event.key.keysym.sym == sdl.SDLK_F12:
                    self.toggle_debug()
                elif self.event.key.keysym.sym == sdl.SDLK_SPACE:
                    self.paused = not self.paused

        # No more ImGui event processing - performance boost!


def print_python_info():
    """Print information about the Python interpreter being used"""
    print(f"[blue]Python Information:[/blue]")
    print(f"  Version: {sys.version}")
    print(f"  Executable: {sys.executable}")
    print(f"  Implementation: {platform.python_implementation()}")
    print(f"  Compiler: {platform.python_compiler()}")
    print(f"  Build: {platform.python_build()}")
    print(f"  Platform: {platform.platform()}")
    print()


def main():
    # Print Python interpreter information
    print_python_info()

    rom = "roms/test_oam.smc"
    # rom = "roms/snes_oam_test/1-random.smc"
    # rom = "roms/snes_oam_test/2-low.smc"
    # rom = "roms/snes_oam_test/3-high.smc"
    # rom = "roms/snes_adc_sbc/test_adc.smc"
    rom = "roms/SNES Test Program .smc"  # Lots of ppu tests
    rom = "roms/SNES Test Program.sfc"
    # rom = "submodules/snes-test-roms/jonasquinn-test-roms/test_oam/test_oam.smc"
    # rom = "submodules/snes-test-roms/jonasquinn-test-roms/snes_adc_sbc/test_adc.smc"
    # rom = "submodules/snes-test-roms/jonasquinn-test-roms/test_hdma/test_hdmasync.smc"
    # rom = "submodules/snes-test-roms/jonasquinn-test-roms/test_dmatiming/demo.smc"

    rom = "submodules/SNES/CPUTest/CPU/ADC/CPUADC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/AND/CPUAND.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/ASL/CPUASL.sfc"
    rom = "submodules/SNES/CPUTest/CPU/BIT/CPUBIT.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/BRA/CPUBRA.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/CMP/CPUCMP.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/DEC/CPUDEC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/EOR/CPUEOR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/INC/CPUINC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/JMP/CPUJMP.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/LDR/CPULDR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/LSR/CPULSR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/MOV/CPUMOV.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/MSC/CPUMSC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/ORA/CPUORA.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/PHL/CPUPHL.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/PSR/CPUPSR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/RET/CPURET.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/ROL/CPUROL.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/ROR/CPUROR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/SBC/CPUSBC.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/STR/CPUSTR.sfc"
    # rom = "submodules/SNES/CPUTest/CPU/TRN/CPUTRN.sfc"

    # rom = "submodules/SNES/CPUTest/SPC700/ADC/SPC700ADC.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/AND/SPC700AND.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/DEC/SPC700DEC.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/EOR/SPC700EOR.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/INC/SPC700INC.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/ORA/SPC700ORA.sfc"
    # rom = "submodules/SNES/CPUTest/SPC700/SBC/SPC700SBC.sfc"

    # PeterLemon PPU tests
    # rom = "submodules/SNES/PPU/BGMAP/8x8/2BPP/8x8BG1Map2BPP32x328PAL/8x8BG1Map2BPP32x328PAL.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/2BPP/8x8BG2Map2BPP32x328PAL/8x8BG2Map2BPP32x328PAL.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/2BPP/8x8BG3Map2BPP32x328PAL/8x8BG3Map2BPP32x328PAL.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/2BPP/8x8BG4Map2BPP32x328PAL/8x8BG4Map2BPP32x328PAL.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/4BPP/8x8BGMap4BPP32x328PAL/8x8BGMap4BPP32x328PAL.sfc"
    rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/32x32/8x8BGMap8BPP32x32.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/32x64/8x8BGMap8BPP32x64.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/64x32/8x8BGMap8BPP64x32.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/64x64/8x8BGMap8BPP64x64.sfc"
    # rom = "submodules/SNES/PPU/BGMAP/8x8/8BPP/TileFlip/8x8BGMapTileFlip.sfc"
    rom = "submodules/SNES/PPU/Mosaic/Mode3/MosaicMode3.sfc"

    # rom = "roms/Super Mario World (U) [!].smc"
    # rom = "roms/Donkey Kong Country (U) (V1.2) [!].smc"
    # rom = "roms/Legend of Zelda, The - A Link to the Past (USA).sfc"
    # rom = "roms/Super Bomberman 5 Gold Cartridge (J) [!].smc"
    # rom = "roms/Final Fight (USA).sfc"
    # rom = "roms/SimCity (USA).sfc"
    # rom = "roms/Magical Quest Starring Mickey Mouse, The (USA).sfc"

    pysnes = PySNES(rom)

    # add trace crosscheck
    # trace_file = "submodules/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ADC/CPUADC-trace.log"
    # with open(trace_file, "r") as f:
    #     while line := f.readline():
    #         check_trace_line(line, pysnes.cpu)
    #         pysnes.tick()

    # while pysnes.tick():
    #     pass

    pysnes.main()

    pysnes.video.teardown_sdl()
