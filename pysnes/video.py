import os
import sdl2 as sdl
import OpenGL.GL as gl
import numpy as np
from rich import print, inspect

# Try to import SDL2 renderer for optimized rendering
try:
    from .video_sdl2 import SDL2Renderer
    SDL2_AVAILABLE = True
except ImportError as e:
    SDL2Renderer = None
    SDL2_AVAILABLE = False
    print(f"[yellow]SDL2 renderer not available: {e}[/yellow]")

# Try to import ModernGL for fallback rendering
try:
    from .video_moderngl import ModernGLRenderer
    MODERNGL_AVAILABLE = True
except ImportError as e:
    ModernGLRenderer = None
    MODERNGL_AVAILABLE = False

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

    def __init__(self):
        # Choose renderer based on availability and preference
        self.use_sdl2 = SDL2_AVAILABLE and not os.environ.get('PYSNES_FORCE_OPENGL', False)
        self.use_moderngl = MODERNGL_AVAILABLE and not self.use_sdl2 and not os.environ.get('PYSNES_FORCE_PYOPENGL', False)
        self.sdl2_renderer = None
        self.moderngl_renderer = None
        # Debug counters
        self.sdl2_calls = 0
        self.moderngl_calls = 0
        self.pyopengl_calls = 0

    def initialize(self) -> None:
        result = sdl.SDL_Init(sdl.SDL_INIT_EVERYTHING)
        if result != 0:
            raise RuntimeError(f"Failed to initialize SDL: {sdl.SDL_GetError().decode()}")

        # Create window first
        self.window = sdl.SDL_CreateWindow(
            b"PySNES",
            0, 0, self.WINDOW_WIDTH, self.WINDOW_HEIGHT,
            sdl.SDL_WINDOW_SHOWN | (sdl.SDL_WINDOW_OPENGL if not self.use_sdl2 else 0),
        )

        if not self.window:
            raise RuntimeError(f"Failed to create SDL window: {sdl.SDL_GetError().decode()}")

        # Initialize SDL2 direct renderer if available
        if self.use_sdl2 and SDL2Renderer:
            try:
                self.sdl2_renderer = SDL2Renderer(256, 224)
                self.sdl2_renderer.initialize(self.window)
                print(f"[green]SDL2 renderer successfully initialized![/green]")
                return  # Skip OpenGL initialization
            except Exception as e:
                print(f"[red]Failed to initialize SDL2 renderer: {e}[/red]")
                print(f"[yellow]Falling back to OpenGL rendering...[/yellow]")
                self.use_sdl2 = False
                self.sdl2_renderer = None

        # Continue with OpenGL initialization for ModernGL/PyOpenGL
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

        if not self.window:
            raise RuntimeError(f"Failed to create SDL window: {sdl.SDL_GetError().decode()}")

        # If we're using SDL2 direct rendering, skip OpenGL setup
        if self.use_sdl2:
            return

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

        # Initialize ModernGL renderer if available and not using SDL2
        if not self.use_sdl2 and self.use_moderngl and ModernGLRenderer:
            self.moderngl_renderer = ModernGLRenderer(256, 224)
            self.moderngl_renderer.initialize()
            print(f"[green]ModernGL renderer successfully initialized![/green]")
        elif not self.use_sdl2:
            if not MODERNGL_AVAILABLE:
                raise RuntimeError("No rendering backend available - need either SDL2 or ModernGL!")
            else:
                raise RuntimeError("ModernGL should be available but failed to create renderer!")

    def teardown_sdl(self) -> None:
        # Clean up SDL2 renderer first
        if self.sdl2_renderer:
            self.sdl2_renderer.cleanup()
            
        # Clean up ModernGL resources
        if self.moderngl_renderer:
            self.moderngl_renderer.cleanup()
            
        # Clean up OpenGL context (only if we created one)
        if hasattr(self, 'gl_context') and self.gl_context:
            sdl.SDL_GL_DeleteContext(self.gl_context)
            
        sdl.SDL_DestroyWindow(self.window)
        sdl.SDL_Quit()

    def update_screen(self) -> None:
        # SDL2 renderer handles screen updates internally
        if self.use_sdl2:
            return
        
        # For OpenGL-based renderers, swap buffers
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
        if self.use_sdl2 and self.sdl2_renderer:
            # Use SDL2 for direct 2D rendering (fastest option)
            self.sdl2_renderer.draw_frame(main_bgs)
            self.sdl2_calls += 1
            return
        
        if self.use_moderngl and self.moderngl_renderer:
            # Use ModernGL for optimized rendering (bypasses PyOpenGL ctypes overhead)
            self.moderngl_renderer.draw_frame(main_bgs)
            self.moderngl_calls += 1
            return
        
        # If no renderer is available, raise an error
        raise RuntimeError("No valid renderer available!")
    
    def get_renderer_info(self) -> dict:
        """Get information about the current renderer"""
        info = {
            'active_renderer': 'SDL2' if self.use_sdl2 else ('ModernGL' if self.use_moderngl else 'PyOpenGL'),
            'sdl2_available': SDL2_AVAILABLE,
            'moderngl_available': MODERNGL_AVAILABLE,
            'sdl2_calls': getattr(self, 'sdl2_calls', 0),
            'moderngl_calls': getattr(self, 'moderngl_calls', 0),
            'pyopengl_calls': getattr(self, 'pyopengl_calls', 0),
        }
        
        if self.sdl2_renderer:
            info.update(self.sdl2_renderer.get_performance_info())
        elif self.moderngl_renderer:
            info.update(self.moderngl_renderer.get_performance_info())
            
        return info
    
    def toggle_renderer(self) -> bool:
        """Toggle between available renderers (for testing/comparison)"""
        if SDL2_AVAILABLE and not self.use_sdl2:
            # Switch to SDL2
            self.use_sdl2 = True
            self.use_moderngl = False
            print(f"[blue]Switched to SDL2 renderer[/blue]")
            return True
        elif MODERNGL_AVAILABLE and not self.use_moderngl and self.use_sdl2:
            # Switch to ModernGL
            self.use_sdl2 = False
            self.use_moderngl = True
            print(f"[blue]Switched to ModernGL renderer[/blue]")
            return True
        else:
            print("[yellow]No other renderers available to toggle to[/yellow]")
            return False
