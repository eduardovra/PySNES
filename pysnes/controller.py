from sdl2 import *


class Controller:
    def __init__(self) -> None:
        self.pressed_keys = set()
        self.shift_register = list()
        self.latched = 0

    def latch(self, state: int) -> None:
        if state and self.latched == 0:
            self.load_shift_register()
        self.latched = state

    def load_shift_register(self) -> None:
        self.shift_register = [
            0,
            0,
            0,
            0,
            SDLK_c in self.pressed_keys,  # R
            SDLK_d in self.pressed_keys,  # L
            SDLK_s in self.pressed_keys,  # X
            SDLK_x in self.pressed_keys,  # A
            SDLK_RIGHT in self.pressed_keys,  # Right
            SDLK_LEFT in self.pressed_keys,  # Left
            SDLK_DOWN in self.pressed_keys,  # Down
            SDLK_UP in self.pressed_keys,  # Up
            SDLK_RETURN in self.pressed_keys,  # Start
            SDLK_QUOTE in self.pressed_keys,  # Select
            SDLK_a in self.pressed_keys,  # Y
            SDLK_z in self.pressed_keys,  # B
        ]
        print(self.shift_register)

    def data(self) -> int:
        self.shift_register.insert(0, 1)  # Pad left with 1's
        return int(self.shift_register.pop())
