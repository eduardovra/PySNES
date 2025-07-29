import os
import sdl2 as sdl
import imgui
from imgui.integrations.sdl2 import SDL2Renderer
import OpenGL.GL as gl
import numpy as np
from rich import print, inspect

# https://github.com/pygame/pygame/issues/3110#issuecomment-1997404749
os.environ["SDL_VIDEO_X11_FORCE_EGL"] = "1"

# Define the vertex shader and fragment shader (OpenGL 3.3 compatible)
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


class Video:

    WINDOW_WIDTH = 1400
    WINDOW_HEIGHT = 1400

    def initialize(self) -> None:
        result = sdl.SDL_Init(sdl.SDL_INIT_EVERYTHING)
        if result != 0:
            raise RuntimeError(f"Failed to initialize SDL: {sdl.SDL_GetError().decode()}")

        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_DOUBLEBUFFER, 1)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_DEPTH_SIZE, 24)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_STENCIL_SIZE, 8)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_ACCELERATED_VISUAL, 1)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_MULTISAMPLEBUFFERS, 1)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_MULTISAMPLESAMPLES, 8)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_CONTEXT_FLAGS, sdl.SDL_GL_CONTEXT_FORWARD_COMPATIBLE_FLAG)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_CONTEXT_MAJOR_VERSION, 3)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_CONTEXT_MINOR_VERSION, 3)
        sdl.SDL_GL_SetAttribute(sdl.SDL_GL_CONTEXT_PROFILE_MASK, sdl.SDL_GL_CONTEXT_PROFILE_CORE)
        sdl.SDL_SetHint(sdl.SDL_HINT_MAC_CTRL_CLICK_EMULATE_RIGHT_CLICK, b"1")
        sdl.SDL_SetHint(sdl.SDL_HINT_VIDEO_HIGHDPI_DISABLED, b"1")

        self.window = sdl.SDL_CreateWindow(
            b"PySNES",
            0, 0, self.WINDOW_WIDTH, self.WINDOW_HEIGHT,
            sdl.SDL_WINDOW_SHOWN | sdl.SDL_WINDOW_OPENGL,
        )

        if not self.window:
            raise RuntimeError(f"Failed to create SDL window: {sdl.SDL_GetError().decode()}")

        self.gl_context = sdl.SDL_GL_CreateContext(self.window)
        if not self.gl_context:
            raise RuntimeError(f"Failed to create OpenGL context: {sdl.SDL_GetError().decode()}")

        result = sdl.SDL_GL_MakeCurrent(self.window, self.gl_context)
        if result != 0:
            raise RuntimeError(f"Failed to make OpenGL context current: {sdl.SDL_GetError().decode()}")

        # Verify OpenGL context is working
        try:
            version = gl.glGetString(gl.GL_VERSION)
            vendor = gl.glGetString(gl.GL_VENDOR)
            renderer = gl.glGetString(gl.GL_RENDERER)
            print(f"OpenGL Version: {version.decode() if version else 'Unknown'}")
            print(f"OpenGL Vendor: {vendor.decode() if vendor else 'Unknown'}")
            print(f"OpenGL Renderer: {renderer.decode() if renderer else 'Unknown'}")

            # Test basic OpenGL functionality
            gl.glClearColor(0.0, 0.0, 0.0, 1.0)
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        except Exception as e:
            raise RuntimeError(f"OpenGL context validation failed: {e}")

        assert sdl.SDL_GL_SetSwapInterval(1) == 0, sdl.SDL_GetError()

        # IMGUI_CHECKVERSION

        self.imgui_context = imgui.create_context()

        # Initialize the SDL2 renderer for ImGui
        self.impl = SDL2Renderer(self.window)

        # Create texture for game screen rendering
        try:
            texture = gl.glGenTextures(1)
            if texture == 0:
                raise RuntimeError("Failed to generate OpenGL texture")

            gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_S, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_WRAP_T, gl.GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MIN_FILTER, gl.GL_NEAREST)  # GL_LINEAR
            gl.glTexParameteri(gl.GL_TEXTURE_2D, gl.GL_TEXTURE_MAG_FILTER, gl.GL_NEAREST)  # GL_LINEAR
            gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
            self.texture = texture
        except Exception as e:
            raise RuntimeError(f"Failed to create OpenGL texture: {e}")

        # This will unlock framerate since opengl won't wait until vsync each frame anymore
        # 0 for immediate updates, 1 for updates synchronized with the vertical retrace, -1 for adaptive vsync.
        assert sdl.SDL_GL_SetSwapInterval(0) == 0, sdl.SDL_GetError()

        try:
            self.shader_program = self.create_shader_program()
        except Exception as e:
            raise RuntimeError(f"Failed to create shader program: {e}")

        # Generate VAO and VBO
        try:
            self.VAO = gl.glGenVertexArrays(1)
            if self.VAO == 0:
                raise RuntimeError("Failed to generate VAO")

            self.VBO = gl.glGenBuffers(1)
            if self.VBO == 0:
                raise RuntimeError("Failed to generate VBO")
        except Exception as e:
            raise RuntimeError(f"Failed to create OpenGL buffers: {e}")

    def teardown_sdl(self) -> None:
        self.impl.shutdown()
        sdl.SDL_GL_DeleteContext(self.gl_context)
        sdl.SDL_DestroyWindow(self.window)
        sdl.SDL_Quit()

    def update_screen(self) -> None:
        # Clear the screen
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        imgui.render()
        self.impl.render(imgui.get_draw_data())

        sdl.SDL_GL_SwapWindow(self.window)

    def set_window_title(self, title: str) -> None:
        sdl.SDL_SetWindowTitle(self.window, title.encode())

    def compile_shader(self, source, shader_type):
        shader = gl.glCreateShader(shader_type)
        if shader == 0:
            raise RuntimeError("Failed to create shader object")

        gl.glShaderSource(shader, source)
        gl.glCompileShader(shader)

        if not gl.glGetShaderiv(shader, gl.GL_COMPILE_STATUS):
            log = gl.glGetShaderInfoLog(shader)
            gl.glDeleteShader(shader)
            shader_type_name = "vertex" if shader_type == gl.GL_VERTEX_SHADER else "fragment"
            raise RuntimeError(f"Failed to compile {shader_type_name} shader: {log}")

        return shader

    def create_shader_program(self):
        vertex_shader = self.compile_shader(VERTEX_SHADER_SOURCE, gl.GL_VERTEX_SHADER)
        fragment_shader = self.compile_shader(FRAGMENT_SHADER_SOURCE, gl.GL_FRAGMENT_SHADER)

        program = gl.glCreateProgram()
        if program == 0:
            raise RuntimeError("Failed to create shader program")

        gl.glAttachShader(program, vertex_shader)
        gl.glAttachShader(program, fragment_shader)
        gl.glLinkProgram(program)

        if not gl.glGetProgramiv(program, gl.GL_LINK_STATUS):
            log = gl.glGetProgramInfoLog(program)
            gl.glDeleteProgram(program)
            gl.glDeleteShader(vertex_shader)
            gl.glDeleteShader(fragment_shader)
            raise RuntimeError(f"Failed to link shader program: {log}")

        # Clean up shaders since they are now linked into the program
        gl.glDeleteShader(vertex_shader)
        gl.glDeleteShader(fragment_shader)

        return program

    def draw_vertices(self, vertices, x, y, width, height):
        length = len(vertices) // 6  # assuming 6 floats per vertex: 3 for position, 3 for color

        # Clear the screen
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)

        # Set the viewport
        # TODO couldn't figure this out yet - with the viewport the game window is drawn at the
        # left bottom corner and without the game is drawn stretched over the whole window
        gl.glViewport(x, y, width, height)

        # Bind VAO (stores the vertex attribute configuration)
        gl.glBindVertexArray(self.VAO)

        # Bind VBO and upload the vertex data
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.VBO)
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

        gl.glUseProgram(self.shader_program)
        gl.glBindVertexArray(self.VAO)

        # Draw the points
        gl.glDrawArrays(gl.GL_POINTS, 0, length)

    def draw_textures(self, main_bgs):
        """Draw the main background and backdrop textures."""
        texture = self.texture
        array = np.array(main_bgs, dtype=np.uint32)
        gl.glBindTexture(gl.GL_TEXTURE_2D, texture)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 256, 224,
            0, gl.GL_RGBA, gl.GL_UNSIGNED_INT_8_8_8_8, array
        )
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
