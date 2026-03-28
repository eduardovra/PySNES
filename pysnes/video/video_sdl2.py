"""
SDL2-based video renderer for PySNES
Replaces OpenGL with direct SDL2 2D rendering for better performance
"""
import sdl2 as sdl
import numpy as np
import ctypes
from typing import Optional
from rich import print


class SDL2Renderer:
    """High-performance 2D renderer using SDL2 directly (no OpenGL)"""

    def __init__(self, width: int = 256, height: int = 224):
        self.width = width
        self.height = height
        self.renderer: Optional[sdl.SDL_Renderer] = None
        self.texture: Optional[sdl.SDL_Texture] = None
        self.window = None

    def initialize(self, window) -> None:
        """Initialize SDL2 renderer from existing window"""
        try:
            self.window = window

            # Create hardware-accelerated renderer
            self.renderer = sdl.SDL_CreateRenderer(
                window,
                -1,  # Use first available rendering driver
                sdl.SDL_RENDERER_ACCELERATED | sdl.SDL_RENDERER_PRESENTVSYNC
            )

            if not self.renderer:
                # Fallback to software renderer
                self.renderer = sdl.SDL_CreateRenderer(
                    window,
                    -1,
                    sdl.SDL_RENDERER_SOFTWARE
                )

            if not self.renderer:
                raise RuntimeError(f"Failed to create SDL2 renderer: {sdl.SDL_GetError().decode()}")

            # Get renderer info for debugging (stored, not printed)
            renderer_info = sdl.SDL_RendererInfo()
            sdl.SDL_GetRendererInfo(self.renderer, renderer_info)
            self.renderer_name = renderer_info.name.decode() if renderer_info.name else "Unknown"

            # Create streaming texture for game screen
            self.texture = sdl.SDL_CreateTexture(
                self.renderer,
                sdl.SDL_PIXELFORMAT_RGBA8888,  # 32-bit RGBA
                sdl.SDL_TEXTUREACCESS_STREAMING,
                self.width,
                self.height
            )

            if not self.texture:
                raise RuntimeError(f"Failed to create SDL2 texture: {sdl.SDL_GetError().decode()}")

            # Set texture blend mode for proper alpha blending
            sdl.SDL_SetTextureBlendMode(self.texture, sdl.SDL_BLENDMODE_BLEND)

            # Set renderer clear color (black)
            sdl.SDL_SetRenderDrawColor(self.renderer, 0, 0, 0, 255)

            # Disable VSync for maximum performance (can be re-enabled later)
            # Note: VSync control is renderer-specific in SDL2

        except Exception as e:
            raise RuntimeError(f"Failed to initialize SDL2 renderer: {e}")

    def draw_frame(self, texture_data: np.ndarray) -> None:
        """
        Draw a frame using SDL2 (much faster than OpenGL for 2D)

        Args:
            texture_data: RGBA texture data as numpy array
        """
        if not self.renderer or not self.texture:
            raise RuntimeError("SDL2 renderer not properly initialized!")

        # Convert texture data to proper format
        if hasattr(texture_data, 'dtype'):
            if texture_data.dtype == np.uint32:
                # Packed RGBA data - need to ensure correct byte order
                # SDL2 expects RGBA8888 format
                pixel_data = texture_data.view(np.uint8)
            elif texture_data.dtype == np.uint8:
                # Already in byte format
                pixel_data = texture_data
            else:
                # Convert other formats to uint32 first
                pixel_data = texture_data.astype(np.uint32).view(np.uint8)
        else:
            # Convert to numpy array
            pixel_data = np.asarray(texture_data, dtype=np.uint32).view(np.uint8)

        # Ensure we have the right amount of data
        expected_size = self.width * self.height * 4  # 4 bytes per pixel (RGBA)
        if len(pixel_data) != expected_size:
            # Try to reshape/truncate the data to fit
            if len(pixel_data) > expected_size:
                pixel_data = pixel_data[:expected_size]
            elif len(pixel_data) < expected_size:
                # Pad with zeros if too small
                padded = np.zeros(expected_size, dtype=np.uint8)
                padded[:len(pixel_data)] = pixel_data
                pixel_data = padded

        # Update texture with pixel data
        pitch = self.width * 4  # 4 bytes per pixel
        result = sdl.SDL_UpdateTexture(
            self.texture,
            None,  # Update entire texture
            pixel_data.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
            pitch
        )

        if result != 0:
            # Don't print error messages to avoid scrolling
            return

        # Clear screen
        sdl.SDL_RenderClear(self.renderer)

        # Copy texture to screen (this handles scaling automatically)
        sdl.SDL_RenderCopy(self.renderer, self.texture, None, None)

        # Present frame
        sdl.SDL_RenderPresent(self.renderer)

    def cleanup(self) -> None:
        """Clean up SDL2 resources"""
        if self.texture:
            sdl.SDL_DestroyTexture(self.texture)
            self.texture = None
        if self.renderer:
            sdl.SDL_DestroyRenderer(self.renderer)
            self.renderer = None

    def set_vsync(self, enabled: bool) -> None:
        """Enable/disable VSync (if supported by renderer)"""
        # Note: SDL2 VSync is set during renderer creation
        # This would require recreating the renderer to change
        pass

    def get_performance_info(self) -> dict:
        """Get performance-related information"""
        if not self.renderer:
            return {}

        renderer_info = sdl.SDL_RendererInfo()
        if sdl.SDL_GetRendererInfo(self.renderer, renderer_info) == 0:
            return {
                'name': getattr(self, 'renderer_name', 'Unknown'),
                'flags': renderer_info.flags,
                'accelerated': bool(renderer_info.flags & sdl.SDL_RENDERER_ACCELERATED),
                'vsync': bool(renderer_info.flags & sdl.SDL_RENDERER_PRESENTVSYNC),
                'texture_size': f"{self.width}x{self.height}",
                'backend': 'SDL2'
            }
        else:
            return {
                'backend': 'SDL2',
                'texture_size': f"{self.width}x{self.height}",
                'name': getattr(self, 'renderer_name', 'Unknown')
            }
