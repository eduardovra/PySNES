"""
ModernGL-based video renderer for PySNES
Replaces PyOpenGL ctypes calls with optimized ModernGL bindings
"""
import moderngl
import numpy as np
from typing import Optional
from rich import print

class ModernGLRenderer:
    """High-performance OpenGL renderer using ModernGL instead of PyOpenGL"""
    
    def __init__(self, width: int = 256, height: int = 224):
        self.width = width
        self.height = height
        self.ctx: Optional[moderngl.Context] = None
        self.texture: Optional[moderngl.Texture] = None
        self.vao: Optional[moderngl.VertexArray] = None
        self.program: Optional[moderngl.Program] = None
        self.vbo: Optional[moderngl.Buffer] = None
        
    def initialize(self, gl_context=None) -> None:
        """Initialize ModernGL context from existing OpenGL context"""
        try:
            # Create ModernGL context from existing SDL2/OpenGL context
            self.ctx = moderngl.create_context()
            
            # Create shader program
            self._create_shader_program()
            
            # Create texture for game screen
            self.texture = self.ctx.texture((self.width, self.height), 4)  # RGBA
            self.texture.filter = (moderngl.NEAREST, moderngl.NEAREST)
            self.texture.swizzle = 'RGBA'
            
            # Create vertex buffer for full-screen quad
            self._create_geometry()
            
        except Exception as e:
            print(f"[red]Failed to initialize ModernGL renderer: {e}[/red]")
            raise
    
    def _create_shader_program(self) -> None:
        """Create optimized shader program"""
        if not self.ctx:
            raise RuntimeError("ModernGL context not initialized")
            
        vertex_shader = """
        #version 330 core
        in vec2 in_position;
        in vec2 in_texcoord;
        out vec2 texcoord;
        
        void main() {
            gl_Position = vec4(in_position, 0.0, 1.0);
            texcoord = in_texcoord;
        }
        """
        
        fragment_shader = """
        #version 330 core
        uniform sampler2D gameTexture;
        in vec2 texcoord;
        out vec4 fragColor;
        
        void main() {
            fragColor = texture(gameTexture, texcoord);
        }
        """
        
        self.program = self.ctx.program(
            vertex_shader=vertex_shader,
            fragment_shader=fragment_shader
        )
        
    def _create_geometry(self) -> None:
        """Create vertex data for full-screen quad"""
        if not self.ctx:
            raise RuntimeError("ModernGL context not initialized")
            
        # Vertex data: position (x,y), texcoord (u,v)
        # Flip V coordinates because OpenGL texture origin is bottom-left
        vertices = np.array([
            # Triangle 1
            -0.8, -0.6,  0.0, 1.0,  # Bottom-left
             0.8, -0.6,  1.0, 1.0,  # Bottom-right  
             0.8,  0.6,  1.0, 0.0,  # Top-right
            
            # Triangle 2
            -0.8, -0.6,  0.0, 1.0,  # Bottom-left
             0.8,  0.6,  1.0, 0.0,  # Top-right
            -0.8,  0.6,  0.0, 0.0,  # Top-left
        ], dtype=np.float32)
        
        # Create buffer
        self.vbo = self.ctx.buffer(vertices.tobytes())
        
        # Create vertex array
        if not self.program:
            raise RuntimeError("Shader program not initialized")
            
        self.vao = self.ctx.vertex_array(
            self.program,
            [(self.vbo, '2f 2f', 'in_position', 'in_texcoord')]
        )
    
    def draw_frame(self, texture_data: np.ndarray) -> None:
        """
        Draw a frame using ModernGL (much faster than PyOpenGL)
        
        Args:
            texture_data: RGBA texture data as numpy array (height, width, 4) or flattened
        """
        # Ensure all components are initialized
        if not self.ctx or not self.texture or not self.vao:
            raise RuntimeError("ModernGL renderer not properly initialized!")
        
        # Convert texture data to proper format for ModernGL
        if hasattr(texture_data, 'tobytes'):
            # If it's a numpy array, handle different formats
            if hasattr(texture_data, 'dtype'):
                if texture_data.dtype == np.uint32:
                    # This is packed RGBA data - reinterpret as uint8 bytes
                    data_bytes = texture_data.view(np.uint8).tobytes()
                elif texture_data.dtype == np.uint8:
                    # Already in correct format
                    data_bytes = texture_data.tobytes()
                else:
                    # Other format - convert to uint32 first, then reinterpret
                    texture_data = texture_data.astype(np.uint32)
                    data_bytes = texture_data.view(np.uint8).tobytes()
            else:
                # No dtype info, assume it's already correct
                data_bytes = texture_data.tobytes()
        else:
            # Not a numpy array - convert to numpy uint32 first
            arr = np.asarray(texture_data, dtype=np.uint32)
            data_bytes = arr.view(np.uint8).tobytes()
            #data_bytes = texture_data
        
        # Update texture - this is much faster than PyOpenGL
        self.texture.write(data_bytes)
        
        # Clear and render
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)
        
        # Bind texture to unit 0 and render
        self.texture.use(0)
        self.vao.render()
    
    def cleanup(self) -> None:
        """Clean up ModernGL resources"""
        if self.vao:
            self.vao.release()
        if self.vbo:
            self.vbo.release()
        if self.texture:
            self.texture.release()
        if self.program:
            self.program.release()
        if self.ctx:
            self.ctx.release()
    
    def get_performance_info(self) -> dict:
        """Get performance-related information"""
        if not self.ctx:
            return {}
            
        return {
            'vendor': self.ctx.info.get('GL_VENDOR', 'Unknown'),
            'renderer': self.ctx.info.get('GL_RENDERER', 'Unknown'),
            'version': self.ctx.info.get('GL_VERSION', 'Unknown'),
            'texture_size': f"{self.width}x{self.height}",
            'backend': 'ModernGL'
        }
