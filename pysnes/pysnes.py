import argparse
from ctypes import byref

from sdl2 import *
import imgui
from imgui.integrations.sdl2 import SDL2Renderer
import OpenGL.GL as gl
import numpy as np
from rich import print

from .rom import Rom
from .bus import Bus
from .cpu import Cpu
from .apu import Apu
from .ppu import Ppu
from .controller import Controller
from .trace_matcher import check_trace_line
# from .cpu.v2.wdc65816.disassembler import Disassembler

class PySNES:
    def __init__(self, rom_file_path: str) -> None:
        rom = Rom(rom_file_path)
        self.apu = Apu()
        self.cpu = Cpu(rom.hardware_vectors)
        self.ppu = Ppu(self.cpu)  # Pass CPU reference so PPU can control the NMI line
        self.controllers = [Controller(), Controller(disabled=True)]
        bus = Bus(rom, self.cpu, self.apu, self.ppu, self.controllers)
        self.cpu.attach(bus)
        # self.disassembler = Disassembler(self.cpu)
        self.frames = 0
        self.setup_sdl()

        # Reset PC to the address in the cartridge reset vector
        self.cpu.PC.w = rom.hardware_vectors["emulation"]["RESET"]

        self.paused = False

    def setup_sdl(self) -> None:
        SDL_Init(SDL_INIT_VIDEO)

        SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1)
        SDL_GL_SetAttribute(SDL_GL_DEPTH_SIZE, 24)
        SDL_GL_SetAttribute(SDL_GL_STENCIL_SIZE, 8)
        SDL_GL_SetAttribute(SDL_GL_ACCELERATED_VISUAL, 1)
        SDL_GL_SetAttribute(SDL_GL_MULTISAMPLEBUFFERS, 1)
        SDL_GL_SetAttribute(SDL_GL_MULTISAMPLESAMPLES, 8)
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_FLAGS, SDL_GL_CONTEXT_FORWARD_COMPATIBLE_FLAG)
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MAJOR_VERSION, 4)
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_MINOR_VERSION, 1)
        SDL_GL_SetAttribute(SDL_GL_CONTEXT_PROFILE_MASK, SDL_GL_CONTEXT_PROFILE_CORE)

        SDL_SetHint(SDL_HINT_MAC_CTRL_CLICK_EMULATE_RIGHT_CLICK, b"1")
        SDL_SetHint(SDL_HINT_VIDEO_HIGHDPI_DISABLED, b"1")

        self.window = SDL_CreateWindow(b"PySNES", 0, 0, 1024, 1024, SDL_WINDOW_SHOWN | SDL_WINDOW_OPENGL)

        # window, gl_context = impl_pysdl2_init()
        self.gl_context = SDL_GL_CreateContext(self.window)
        SDL_GL_MakeCurrent(self.window, self.gl_context)
        assert SDL_GL_SetSwapInterval(1) == 0
        self.imgui_context = imgui.create_context()
        self.impl = SDL2Renderer(self.window)

        # Set the point size
        # gl.glPointSize(10.0)

        # imgui.get_io().display_size = 200, 200
        # imgui.get_io().fonts.get_tex_data_as_rgba32()

        # self.renderer = SDL_CreateRenderer(self.window, -1, SDL_RENDERER_ACCELERATED)
        # SDL_SetRenderDrawBlendMode(self.renderer, SDL_BLENDMODE_BLEND)
        # SDL_RenderSetScale(self.renderer, 2, 2)
        self.event = SDL_Event()

    def teardown_sdl(self) -> None:
        self.impl.shutdown()
        SDL_GL_DeleteContext(self.gl_context)
        # SDL_DestroyRenderer(self.renderer)
        SDL_DestroyWindow(self.window)
        SDL_Quit()

    def draw_gui(self) -> None:

        # possible way to render game to imgui window
        # https://www.codingwiththomas.com/blog/rendering-an-opengl-framebuffer-into-a-dear-imgui-window

        imgui.new_frame()

        is_expand, show_custom_window = imgui.begin("Current instruction", True)
        if is_expand:
            debug_str = self.cpu.disassembler.disassemble(self.cpu.PC.w)
            debug_str += f" V:{self.ppu.v_counter:03} H:{self.ppu.h_counter:03} F:{self.ppu.frames}"
            if not self.paused:
                print(f"[green]{debug_str}[/green]")  # trace log
            imgui.text_colored(debug_str, 0, 255, 0)
        imgui.end()
        is_expand, show_custom_window = imgui.begin("CPU Registers", True)
        if is_expand:
            imgui.text(f"Frames: {self.frames}")
            imgui.text(f"PC: 0x{self.cpu.PC.value:06X}")
            imgui.text(f"A: 0x{self.cpu.A.value:04X}")
            imgui.text(f"X: 0x{self.cpu.X.value:04X}")
            imgui.text(f"Y: 0x{self.cpu.Y.value:04X}")
            imgui.text(f"SP: 0x{self.cpu.S.value:04X}")
            imgui.text(f"DB: 0x{self.cpu.DB.value:02X}")
            imgui.text(f"P: 0x{self.cpu.P:02X}")
            if imgui.button("Continue" if self.paused else "Pause"):
                self.paused = not self.paused
        imgui.end()

    def test_draw(self):
        # Define the vertex shader and fragment shader
        VERTEX_SHADER_SOURCE = """
        #version 330 core
        layout (location = 0) in vec3 aPos;  // Vertex position
        layout (location = 1) in vec3 aColor;  // Vertex color

        out vec3 vertexColor;  // Output to fragment shader

        void main() {
            gl_Position = vec4(aPos, 1.0);  // Set the position of the point
            vertexColor = aColor;  // Pass the color to the fragment shader
        }
        """

        # Updated fragment shader that uses the passed-in color for rendering
        FRAGMENT_SHADER_SOURCE = """
        #version 330 core
        in vec3 vertexColor;  // Input from vertex shader
        out vec4 FragColor;

        void main() {
            FragColor = vec4(vertexColor, 1.0);  // Set the pixel color using the passed-in color
        }
        """

        def compile_shader(source, shader_type):
            shader = gl.glCreateShader(shader_type)
            gl.glShaderSource(shader, source)
            gl.glCompileShader(shader)
            if not gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS):
                raise RuntimeError(gl.glGetShaderInfoLog(shader))
            return shader

        def create_shader_program():
            vertex_shader = compile_shader(VERTEX_SHADER_SOURCE, gl.GL_VERTEX_SHADER)
            fragment_shader = compile_shader(FRAGMENT_SHADER_SOURCE, gl.GL_FRAGMENT_SHADER)

            program = gl.glCreateProgram()
            gl.glAttachShader(program, vertex_shader)
            gl.glAttachShader(program, fragment_shader)
            gl.glLinkProgram(program)

            if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
                raise RuntimeError(gl.glGetProgramInfoLog(program))

            # Clean up shaders since they are now linked into the program
            gl.glDeleteShader(vertex_shader)
            gl.glDeleteShader(fragment_shader)

            return program

        def generate_line():
            # Window width in pixels
            window_width = 1024

            # OpenGL range is -1.0 to 1.0, total range = 2.0
            opengl_range = 2.0

            # Calculate the point spacing in OpenGL coordinates
            point_spacing = opengl_range / window_width

            vertices = []
            for i in range(window_width):
                # x, y, z, r, g, b
                point = [i * point_spacing - 1.0, 0.0, 0.0, 0.0, 1.0, 0.0]
                vertices.extend(point)

            return np.array(vertices, dtype=np.float32)

        shader_program = create_shader_program()

        # Define positions and colors for 1024 points
        vertices = generate_line()

        # Generate VAO and VBO
        VAO = gl.glGenVertexArrays(1)
        VBO = gl.glGenBuffers(1)

        # Bind VAO (stores the vertex attribute configuration)
        gl.glBindVertexArray(VAO)

        # Bind VBO and upload the vertex data
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, VBO)
        gl.glBufferData(gl.GL_ARRAY_BUFFER, vertices.nbytes, vertices, gl.GL_STATIC_DRAW)

        # Specify the layout of the position data (3 floats per position)
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 6 * vertices.itemsize, None)
        gl.glEnableVertexAttribArray(0)

        # Specify the layout of the color data (3 floats per color, offset by the position data)
        gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, 6 * vertices.itemsize, gl.ctypes.c_void_p(3 * vertices.itemsize))
        gl.glEnableVertexAttribArray(1)

        # Unbind the VBO and VAO
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

        gl.glUseProgram(shader_program)
        gl.glBindVertexArray(VAO)

        # Draw the points
        gl.glDrawArrays(gl.GL_POINTS, 0, 1024)  # 1024 points

    def tick(self):
        """Process one frame"""
        # Capture inputs from keyboard using SDL
        while SDL_PollEvent(byref(self.event)) != 0:
            if self.event.type == SDL_QUIT:
                return False
            elif self.event.type == SDL_KEYUP:
                controller = self.controllers[0]
                controller.pressed_keys.remove(self.event.key.keysym.sym)
            elif self.event.type == SDL_KEYDOWN:
                controller = self.controllers[0]
                controller.pressed_keys.add(self.event.key.keysym.sym)

            self.impl.process_event(self.event)

        self.impl.process_inputs()

        self.draw_gui()

        # To determine the exact length of any CPU instruction,
        # you must examine its behavior for each cycle,
        # and count 6, 8, or 12 master cycles as appropriate.
        if not self.paused:
            master_cycles = self.cpu.tick()

        # Tick PPU with the number of master cycles used by the CPU
        # as it runs on the same clock source

        # Clear the screen
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        # TEST DRAWING
        self.test_draw()
        # SDL_RenderDrawPoint(renderer, x, y)

        # self.ppu.tick(master_cycles)

        # self.apu.tick(master_cycles)

        imgui.render()
        self.impl.render(imgui.get_draw_data())
        SDL_GL_SwapWindow(self.window)

        # TODO Sleep to limit frequency on 60Hz
        # SDL_Delay(5)

        self.frames += 1

        return True  # keep running


def main():
    rom = "roms/test_oam.smc"
    # rom = "roms/snes_oam_test/1-random.smc"
    # rom = "roms/snes_oam_test/2-low.smc"
    # rom = "roms/snes_oam_test/3-high.smc"
    # rom = "roms/snes_adc_sbc/test_adc.smc"
    rom = "roms/SNES Test Program .smc"  # Lots of ppu tests
    rom = "roms/SNES Test Program.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/test_oam/test_oam.smc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/snes_adc_sbc/test_adc.smc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/test_hdma/test_hdmasync.smc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/jonasquinn-test-roms/test_dmatiming/demo.smc"

    rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ADC/CPUADC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/AND/CPUAND.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ASL/CPUASL.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/BIT/CPUBIT.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/BRA/CPUBRA.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/CMP/CPUCMP.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/DEC/CPUDEC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/EOR/CPUEOR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/INC/CPUINC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/JMP/CPUJMP.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/LDR/CPULDR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/LSR/CPULSR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/MOV/CPUMOV.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/MSC/CPUMSC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ORA/CPUORA.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/PHL/CPUPHL.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/PSR/CPUPSR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/RET/CPURET.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ROL/CPUROL.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ROR/CPUROR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/SBC/CPUSBC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/STR/CPUSTR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/TRN/CPUTRN.sfc"

    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/ADC/SPC700ADC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/AND/SPC700AND.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/DEC/SPC700DEC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/EOR/SPC700EOR.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/INC/SPC700INC.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/ORA/SPC700ORA.sfc"
    # rom = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-SPC700/SBC/SPC700SBC.sfc"

    # rom = "roms/Super Mario World (U) [!].smc"
    # rom = "roms/Donkey Kong Country (U) (V1.2) [!].smc"
    # rom = "roms/Legend of Zelda, The - A Link to the Past (USA).sfc"
    # rom = "roms/Super Bomberman 5 Gold Cartridge (J) [!].smc"
    # rom = "roms/Final Fight (USA).sfc"
    # rom = "roms/SimCity (USA).sfc"
    # rom = "roms/Magical Quest Starring Mickey Mouse, The (USA).sfc"

    pysnes = PySNES(rom)

    # add trace crosscheck
    # trace_file = "/home/eduardovra/workspace/snes-test-roms/PeterLemon/SNES-CPUTest-CPU/ADC/CPUADC-trace.log"
    # with open(trace_file, "r") as f:
    #     while line := f.readline():
    #         check_trace_line(line, pysnes.cpu)
    #         pysnes.tick()

    while pysnes.tick():
        pass

    pysnes.teardown_sdl()

    return

    trace = "roms/Super Mario World (U) [!]-trace.log"
    with open(trace, "r") as f:
        line_number = 0
        error_count_apu = 0
        error_count_cpu = 0

        while True:
            line_number += 1
            line = f.readline()
            print(line.rstrip())

            if line[0] == ".":
                pysnes.apu.fetch_and_execute(trace_line=line)
            else:
                pysnes.cpu.fetch_and_execute(trace_line=line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Python SNES emulator.")
    parser.add_argument('-p', '--profile', action='store_true', help='Enable profiler mode')
    parser.add_argument('-l', '--load', action='store_true', help='Load memory dumps from bsnes to test rendering')
    args = parser.parse_args()

    if args.profile:
        import cProfile
        # from line_profiler import LineProfiler

        # lp = LineProfiler()
        # lp_wrapper = lp(main)
        # lp_wrapper()
        # lp.print_stats()

        cProfile.run("main()", sort="cumulative")
    elif args.load:
        rom = "roms/Super Mario World (U) [!].smc"
        #rom = "roms/test_oam.smc"

        pysnes = PySNES(rom)

        rom_file_name, rom_extension = rom.split(".")

        with open(f"{rom_file_name}-vram.bin", "rb") as f:
            vram_dump = f.read()
            for i, b in enumerate(vram_dump):
                pysnes.ppu.vram[i] = b
        with open(f"{rom_file_name}-cgram.bin", "rb") as f:
            cgram_dump = f.read()
            for i, b in enumerate(cgram_dump):
                pysnes.ppu.cgram[i] = b
        with open(f"{rom_file_name}-oam.bin", "rb") as f:
            oam_dump = f.read()
            for i, b in enumerate(oam_dump):
                pysnes.ppu.oam.oam[i] = b

        # TODO load -apuram.bin -sram.bin -wram.bin
        # apuram is SPC700
        # sram is static ram, for save games. located in the cartridge

        with open(f"{rom_file_name}-wram.bin", "rb") as f:
            wram_dump = f.read()
            for i, b in enumerate(wram_dump):
                try:
                    pysnes.cpu.bus[i] = b
                except Exception as e:
                    # writing to some addresses will trigger operations
                    # that might fail but I don't care
                    print(e)

        pysnes.ppu.render(pysnes.renderer)
        SDL_Delay(5000)
    else:
        main()
