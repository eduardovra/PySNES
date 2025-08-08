import os
import sdl2 as sdl
import OpenGL.GL as gl
import numpy as np
from rich import print, inspect

# https://github.com/pygame/pygame/issues/3110#issuecomment-1997404749
os.environ["SDL_VIDEO_X11_FORCE_EGL"] = "1"

# Define vertex shader that supports both colors and textures
VERTEX_SHADER_SOURCE = """
#version 330 core
layout (location = 0) in vec3 aPos;      // Vertex position
layout (location = 1) in vec3 aColor;    // Vertex color
layout (location = 2) in vec2 aTexCoord; // Texture coordinate

out vec3 vertexColor;  // Output color to fragment shader
out vec2 texCoord;     // Output texture coordinate to fragment shader

void main() {
    gl_Position = vec4(aPos, 1.0);
    vertexColor = aColor;
    texCoord = aTexCoord;
}
"""

# Fragment shader that can handle both colored rendering and textured rendering
FRAGMENT_SHADER_SOURCE = """
#version 330 core
in vec3 vertexColor;  // Input from vertex shader
in vec2 texCoord;     // Input texture coordinate from vertex shader
out vec4 FragColor;

uniform bool useTexture;        // Whether to use texture or color
uniform sampler2D gameTexture;  // The game screen texture

void main() {
    if (useTexture) {
        FragColor = texture(gameTexture, texCoord);
    } else {
        FragColor = vec4(vertexColor, 1.0);
    }
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

        # Pre-create vertex data for textured quad to avoid recreation every frame
        self.quad_vertices = np.array([
            # Position (x,y,z)     Color (r,g,b)      TexCoord (u,v)
            [-0.8, -0.6, 0.0,     1.0, 1.0, 1.0,     0.0, 1.0],  # Bottom-left (flip V)
            [ 0.8, -0.6, 0.0,     1.0, 1.0, 1.0,     1.0, 1.0],  # Bottom-right (flip V)
            [ 0.8,  0.6, 0.0,     1.0, 1.0, 1.0,     1.0, 0.0],  # Top-right (flip V)
            [-0.8, -0.6, 0.0,     1.0, 1.0, 1.0,     0.0, 1.0],  # Bottom-left (flip V)
            [ 0.8,  0.6, 0.0,     1.0, 1.0, 1.0,     1.0, 0.0],  # Top-right (flip V)  
            [-0.8,  0.6, 0.0,     1.0, 1.0, 1.0,     0.0, 0.0],  # Top-left (flip V)
        ], dtype=np.float32)

        # Cache uniform locations to avoid expensive lookups every frame
        self.use_texture_location = gl.glGetUniformLocation(self.shader_program, "useTexture")
        self.texture_location = gl.glGetUniformLocation(self.shader_program, "gameTexture")

        # Pre-setup vertex attributes once during initialization
        self.setup_vertex_attributes()

    def teardown_sdl(self) -> None:
        sdl.SDL_GL_DeleteContext(self.gl_context)
        sdl.SDL_DestroyWindow(self.window)
        sdl.SDL_Quit()

    def update_screen(self) -> None:
        # Just swap buffers - screen clearing now happens in draw_textures
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

    def setup_vertex_attributes(self):
        """Setup vertex attributes once during initialization."""
        gl.glBindVertexArray(self.VAO)
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, self.VBO)
        
        # Upload the pre-created vertex data
        gl.glBufferData(gl.GL_ARRAY_BUFFER, self.quad_vertices.nbytes, self.quad_vertices, gl.GL_STATIC_DRAW)
        
        # Position attribute (location 0) - 3 floats
        gl.glVertexAttribPointer(0, 3, gl.GL_FLOAT, gl.GL_FALSE, 8 * 4, None)
        gl.glEnableVertexAttribArray(0)
        
        # Color attribute (location 1) - 3 floats, offset by 3*4 bytes
        gl.glVertexAttribPointer(1, 3, gl.GL_FLOAT, gl.GL_FALSE, 8 * 4, gl.ctypes.c_void_p(3 * 4))
        gl.glEnableVertexAttribArray(1)
        
        # Texture coordinate attribute (location 2) - 2 floats, offset by 6*4 bytes  
        gl.glVertexAttribPointer(2, 2, gl.GL_FLOAT, gl.GL_FALSE, 8 * 4, gl.ctypes.c_void_p(6 * 4))
        gl.glEnableVertexAttribArray(2)
        
        # Unbind for safety
        gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        gl.glBindVertexArray(0)

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
        """Draw the game screen texture directly to the window."""
        # Clear screen first
        gl.glClear(gl.GL_COLOR_BUFFER_BIT)
        
        # Update texture with game data
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        gl.glTexImage2D(
            gl.GL_TEXTURE_2D, 0, gl.GL_RGBA, 256, 224,
            0, gl.GL_RGBA, gl.GL_UNSIGNED_INT_8_8_8_8, main_bgs
        )
        
        # Use shader program
        gl.glUseProgram(self.shader_program)
        
        # Set uniforms using cached locations
        if self.use_texture_location >= 0:
            gl.glUniform1i(self.use_texture_location, 1)  # Enable texture mode
        
        if self.texture_location >= 0:
            gl.glUniform1i(self.texture_location, 0)  # Use texture unit 0
        
        # Bind texture to unit 0
        gl.glActiveTexture(gl.GL_TEXTURE0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, self.texture)
        
        # Use pre-configured VAO (vertex attributes already set up)
        gl.glBindVertexArray(self.VAO)
        
        # Draw the quad as triangles
        gl.glDrawArrays(gl.GL_TRIANGLES, 0, 6)
        
        # Cleanup
        gl.glBindVertexArray(0)
        gl.glBindTexture(gl.GL_TEXTURE_2D, 0)
