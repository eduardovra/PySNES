"""
SDL2-based video renderer for PySNES
Replaces OpenGL with direct SDL2 2D rendering for better performance
"""
import array as _stdlib_array
import sdl2 as sdl
import numpy as np
import ctypes
from typing import Optional


class SDL2Renderer:
    """High-performance 2D renderer using SDL2 directly (no OpenGL)"""

    def __init__(self, width: int = 256, height: int = 224):
        self.width = width
        self.height = height
        self.renderer: Optional[sdl.SDL_Renderer] = None
        self.texture: Optional[sdl.SDL_Texture] = None
        self.window = None
        self._last_pixel_data: Optional[np.ndarray] = None
        self._pixel_data: Optional[np.ndarray] = None

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

    def draw_frame(self, texture_data) -> None:
        """Draw a frame using SDL2."""
        if not self.renderer or not self.texture:
            raise RuntimeError("SDL2 renderer not properly initialized!")

        # Fast path: array.array framebuffer — create a zero-copy uint8 view once
        # and reuse it every frame (np.frombuffer wraps the same buffer in-place).
        if isinstance(texture_data, _stdlib_array.array):
            if self._pixel_data is None:
                n = self.width * self.height
                self._pixel_data = np.frombuffer(texture_data, dtype=np.uint32, count=n).view(np.uint8)
            pixel_data = self._pixel_data
        elif hasattr(texture_data, 'dtype'):
            pixel_data = texture_data.view(np.uint8) if texture_data.dtype == np.uint32 else texture_data.astype(np.uint32).view(np.uint8)
            expected = self.width * self.height * 4
            if len(pixel_data) > expected:
                pixel_data = pixel_data[:expected]
        else:
            pixel_data = np.asarray(texture_data, dtype=np.uint32).view(np.uint8)
            expected = self.width * self.height * 4
            if len(pixel_data) > expected:
                pixel_data = pixel_data[:expected]

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

        # Stash a reference (no copy) so save_screenshot can write a BMP from
        # the in-flight buffer. Valid until the PPU rewrites it next frame —
        # save_screenshot is called in the same loop iteration before then.
        self._last_pixel_data = pixel_data

    def save_screenshot(self, path: str = "screenshot.bmp") -> None:
        """Save the most recently drawn frame to a BMP at native 256x224.

        Reads from the live buffer stashed by draw_frame — must be called in
        the same main-loop iteration as the draw, before the PPU rewrites it.
        """
        if self._last_pixel_data is None:
            return
        # Texture format is SDL_PIXELFORMAT_RGBA8888: R at MSB, so on
        # little-endian memory the bytes are A,B,G,R per pixel. The matching
        # surface masks place R in the high byte of the 32-bit pixel.
        buf = np.ascontiguousarray(self._last_pixel_data)
        surface = sdl.SDL_CreateRGBSurfaceFrom(
            buf.ctypes.data_as(ctypes.c_void_p),
            self.width, self.height, 32, self.width * 4,
            0xFF000000, 0x00FF0000, 0x0000FF00, 0x000000FF
        )
        if not surface:
            return
        sdl.SDL_SaveBMP(surface, path.encode())
        sdl.SDL_FreeSurface(surface)

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
