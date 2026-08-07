import sdl2


class Controller:
    def __init__(self, *, disabled: bool = False) -> None:
        self.pressed_keys = set()
        self.shift_register = []
        self.latched = 0
        self.joy_h = 0
        self.joy_l = 0
        # Only controller port 1 has mapped buttons,
        # so I created this to disable the other ports
        self.disabled = disabled

    def latch(self, state: int) -> None:
        if state and self.latched == 0:
            self.load_shift_register()
        self.latched = state

    def load_shift_register(self) -> None:
        if self.disabled:
            self.shift_register = [0] * 16
            return

        self.shift_register = [
            0,
            0,
            0,
            0,
            sdl2.SDLK_c in self.pressed_keys,  # R
            sdl2.SDLK_d in self.pressed_keys,  # L
            sdl2.SDLK_s in self.pressed_keys,  # X
            sdl2.SDLK_x in self.pressed_keys,  # A
            sdl2.SDLK_RIGHT in self.pressed_keys,  # Right
            sdl2.SDLK_LEFT in self.pressed_keys,  # Left
            sdl2.SDLK_DOWN in self.pressed_keys,  # Down
            sdl2.SDLK_UP in self.pressed_keys,  # Up
            sdl2.SDLK_RETURN in self.pressed_keys,  # Start
            sdl2.SDLK_QUOTE in self.pressed_keys,  # Select
            sdl2.SDLK_a in self.pressed_keys,  # Y
            sdl2.SDLK_z in self.pressed_keys,  # B
        ]

    def data(self) -> int:
        self.shift_register.insert(0, 1)  # Pad left with 1's
        return int(self.shift_register.pop())

    def dump_state(self) -> dict:
        return {
            "shift_register": list(self.shift_register),
            "latched": int(self.latched),
            "joy_h": int(self.joy_h),
            "joy_l": int(self.joy_l),
            "disabled": bool(self.disabled),
        }

    def load_state(self, d: dict) -> None:
        self.shift_register = list(d["shift_register"])
        self.latched = d["latched"]
        self.joy_h = d["joy_h"]
        self.joy_l = d["joy_l"]
        # pressed_keys is intentionally cleared on load — physical keys held
        # at save time shouldn't be replayed against the loaded state.
        self.pressed_keys = set()
