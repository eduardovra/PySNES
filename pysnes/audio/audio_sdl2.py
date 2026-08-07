import ctypes
import time

import numpy as np
import sdl2 as sdl

# The SNES DSP always generates at this rate. Pitch registers are calibrated for
# it.
DSP_RATE = 32000
CHANNELS = 2
BUFFER_SAMPLES = 1024
BYTES_PER_SAMPLE = CHANNELS * 2  # stereo int16 = 4 bytes per sample
_BUSY_WAIT_HEADROOM_S = 0.001  # busy-wait the last 1 ms for precision


class AudioSDL2:
    def __init__(self):
        self._dev_id = None
        self._device_rate = DSP_RATE
        self._drain_rate = float(DSP_RATE * BYTES_PER_SAMPLE)
        self._max_queue_bytes = round(DSP_RATE / 60 + 1) * BYTES_PER_SAMPLE * 4

    def initialize(self) -> None:
        """Open SDL2 audio device in queue mode (SDL_Init already called by
        video)."""
        spec = sdl.SDL_AudioSpec(
            DSP_RATE,
            sdl.AUDIO_S16SYS,
            CHANNELS,
            BUFFER_SAMPLES,
            ctypes.cast(0, sdl.SDL_AudioCallback),
        )

        obtained = sdl.SDL_AudioSpec(0, 0, 0, 0)
        dev_id = sdl.SDL_OpenAudioDevice(
            None,  # default device
            0,  # playback (not capture)
            ctypes.byref(spec),
            ctypes.byref(obtained),
            sdl.SDL_AUDIO_ALLOW_FREQUENCY_CHANGE,
        )
        if dev_id == 0:
            err = sdl.SDL_GetError()
            raise RuntimeError(f"SDL_OpenAudioDevice failed: {err.decode()}")
        self._dev_id = dev_id
        self._device_rate = obtained.freq if obtained.freq > 0 else DSP_RATE
        self._drain_rate = float(self._device_rate * BYTES_PER_SAMPLE)
        self._max_queue_bytes = (
            round(self._device_rate / 60 + 1) * BYTES_PER_SAMPLE * 4
        )
        # Unpause to start playback
        sdl.SDL_PauseAudioDevice(dev_id, 0)
        print(
            f"Audio: {obtained.freq} Hz, {obtained.channels}ch, "
            f"{obtained.samples} sample buffer",
            flush=True,
        )

    def _resample(self, samples: np.ndarray) -> np.ndarray:
        """Linear interpolation from DSP_RATE to device rate when they
        differ."""
        if self._device_rate == DSP_RATE:
            return samples
        n_in = len(samples)
        n_out = round(n_in * self._device_rate / DSP_RATE)
        t_in = np.arange(n_in, dtype=np.float32)
        t_out = np.linspace(0, n_in - 1, n_out, dtype=np.float32)
        left = np.interp(t_out, t_in, samples[:, 0].astype(np.float32))
        right = np.interp(t_out, t_in, samples[:, 1].astype(np.float32))
        return np.column_stack([left, right]).astype(np.int16)

    def queue_samples(self, samples: np.ndarray) -> None:
        """Queue int16 stereo samples, blocking until there is room.

        Blocking on the audio queue makes it the master clock: the emulator
        naturally runs at ~60 FPS regardless of monitor refresh rate.

        Sleeps for most of the wait using time.sleep (fractional seconds, more
        precise than SDL_Delay's integer milliseconds), then busy-waits the last
        1 ms so we don't overshoot.
        """
        if self._dev_id is None:
            return
        data = np.ascontiguousarray(self._resample(samples), dtype=np.int16)
        queued = sdl.SDL_GetQueuedAudioSize(self._dev_id)
        if queued > self._max_queue_bytes:
            sleep_s = (
                queued - self._max_queue_bytes
            ) / self._drain_rate - _BUSY_WAIT_HEADROOM_S
            if sleep_s > 0:
                time.sleep(sleep_s)
            while (
                sdl.SDL_GetQueuedAudioSize(self._dev_id) > self._max_queue_bytes
            ):
                pass  # busy-wait the last ~1 ms
        ptr = data.ctypes.data_as(ctypes.c_void_p)
        sdl.SDL_QueueAudio(self._dev_id, ptr, data.nbytes)

    def close(self) -> None:
        if self._dev_id is not None:
            sdl.SDL_PauseAudioDevice(self._dev_id, 1)
            sdl.SDL_CloseAudioDevice(self._dev_id)
            self._dev_id = None
