import time

import sdl2 as sdl

from .apu import Apu
from .apu.spc_file import SpcFile
from .audio import AudioSDL2

# APU runs at ~1.024 MHz; DSP generates one sample every 32 APU clocks → 32 kHz.
_APU_HZ   = 1_024_000
_DSP_DIV  = 32            # APU clocks per DSP (audio) sample
_AUDIO_HZ = _APU_HZ // _DSP_DIV  # 32 000 Hz

# Target 60 "frames" per second for audio chunking.
_FPS            = 60
_APU_PER_FRAME  = _APU_HZ // _FPS          # ~17 067 APU clocks per frame
_SAMPLES_PER_FRAME = _APU_PER_FRAME // _DSP_DIV  # ~533 samples per frame


class SpcPlayer:
    def __init__(self, spc_path: str) -> None:
        self.spc = SpcFile(spc_path)
        self.apu = Apu()
        self.apu.load_spc(self.spc)
        self.running = True

    def _init_sdl(self) -> None:
        result = sdl.SDL_Init(sdl.SDL_INIT_AUDIO | sdl.SDL_INIT_VIDEO)
        if result != 0:
            raise RuntimeError(f"SDL_Init failed: {sdl.SDL_GetError().decode()}")

        title = self.spc.song_name or "SPC Player"
        if self.spc.game_name:
            title = f"{self.spc.game_name} — {title}"
        self._window = sdl.SDL_CreateWindow(
            title.encode(),
            sdl.SDL_WINDOWPOS_CENTERED, sdl.SDL_WINDOWPOS_CENTERED,
            400, 100,
            sdl.SDL_WINDOW_SHOWN,
        )

    def _process_events(self) -> None:
        event = sdl.SDL_Event()
        while sdl.SDL_PollEvent(event):
            if event.type == sdl.SDL_QUIT:
                self.running = False
            elif event.type == sdl.SDL_KEYDOWN:
                if event.key.keysym.sym == sdl.SDLK_ESCAPE:
                    self.running = False

    def run(self) -> None:
        self._init_sdl()
        audio = AudioSDL2()
        audio.initialize()

        frame_deadline = time.perf_counter()
        _FRAME_TIME_S = 1.0 / _FPS
        _HEADROOM_S = 0.001

        try:
            while self.running:
                self._process_events()

                # Run APU for one frame's worth of clocks.
                clocks_left = _APU_PER_FRAME
                while clocks_left > 0:
                    self.apu.fetch_and_execute()
                    self.apu.step_timers(self.apu.cycles)
                    clocks_left -= self.apu.cycles

                samples = self.apu.generate_audio_frame(_SAMPLES_PER_FRAME)
                audio.queue_samples(samples)

                frame_deadline += _FRAME_TIME_S
                remaining = frame_deadline - time.perf_counter()
                if remaining > _HEADROOM_S:
                    time.sleep(remaining - _HEADROOM_S)
                while time.perf_counter() < frame_deadline:
                    pass
        finally:
            audio.close()
            sdl.SDL_DestroyWindow(self._window)
            sdl.SDL_Quit()
