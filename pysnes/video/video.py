import sdl2 as sdl

try:
    from .video_sdl2 import SDL2Renderer

    SDL2_AVAILABLE = True
except ImportError as e:
    SDL2Renderer = None
    SDL2_AVAILABLE = False
    print(f"SDL2 renderer not available: {e}")


class Video:
    WINDOW_WIDTH = 768
    WINDOW_HEIGHT = 672

    def __init__(self):
        self.use_sdl2 = SDL2_AVAILABLE
        self.window = None
        self.sdl2_renderer = None
        self.sdl2_calls = 0

    def initialize(self, headless: bool = False) -> None:
        if headless:
            self.window = None
            self.sdl2_renderer = None
            return

        result = sdl.SDL_Init(sdl.SDL_INIT_EVERYTHING)
        if result != 0:
            raise RuntimeError(
                f"Failed to initialize SDL: {sdl.SDL_GetError().decode()}"
            )

        self.window = sdl.SDL_CreateWindow(
            b"PySNES",
            0,
            0,
            self.WINDOW_WIDTH,
            self.WINDOW_HEIGHT,
            sdl.SDL_WINDOW_SHOWN | sdl.SDL_WINDOW_RESIZABLE,
        )

        if not self.window:
            raise RuntimeError(
                f"Failed to create SDL window: {sdl.SDL_GetError().decode()}"
            )

        if self.use_sdl2 and SDL2Renderer:
            try:
                self.sdl2_renderer = SDL2Renderer(256, 224)
                self.sdl2_renderer.initialize(self.window)
                print("SDL2 renderer successfully initialized!")
            except Exception as e:
                print(f"Failed to initialize SDL2 renderer: {e}")
                self.sdl2_renderer = None

    def teardown_sdl(self) -> None:
        if self.window is None:
            return
        if self.sdl2_renderer:
            self.sdl2_renderer.cleanup()
        sdl.SDL_DestroyWindow(self.window)
        sdl.SDL_Quit()

    def update_screen(self) -> None:
        # SDL2 renderer handles screen updates internally
        pass

    def set_window_title(self, title: str) -> None:
        if self.window is None:
            return
        sdl.SDL_SetWindowTitle(self.window, title.encode())

    def save_screenshot(self, path: str = "screenshot.bmp") -> None:
        if self.sdl2_renderer:
            self.sdl2_renderer.save_screenshot(path)

    def draw_textures(self, main_bgs):
        if self.window is None:
            return
        if self.use_sdl2 and self.sdl2_renderer:
            self.sdl2_renderer.draw_frame(main_bgs)
            self.sdl2_calls += 1
            return
        raise RuntimeError("No valid renderer available!")

    def get_renderer_info(self) -> dict:
        info = {
            "active_renderer": "SDL2" if self.use_sdl2 else "None",
            "sdl2_available": SDL2_AVAILABLE,
            "sdl2_calls": getattr(self, "sdl2_calls", 0),
        }
        if self.sdl2_renderer:
            info.update(self.sdl2_renderer.get_performance_info())
        return info

    def toggle_renderer(self) -> bool:
        print("No other renderers available to toggle to")
        return False
