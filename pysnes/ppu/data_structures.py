from dataclasses import dataclass


class Background:
    def __init__(
        self,
        number: int = 0,
        screen_size: int = 0,
        screen_addr: int = 0,
        tiledata_addr: int = 0,
        tile_size: int = 0,
        main_screen_enable: bool = True,
        subscreen_enable: bool = True,
        hoffset: int = 0,
        voffset: int = 0,
        color_offset_mode_0: int = 0,
    ) -> None:
        """Background number 1-4"""
        self.number = number

        self.screen_size = screen_size
        self.screen_addr = screen_addr
        self.tiledata_addr = tiledata_addr
        self.tile_size = tile_size
        self.main_screen_enable = main_screen_enable
        self.sub_screen_enable = subscreen_enable
        self.hoffset = hoffset
        self.voffset = voffset
        self.color_offset_mode_0 = color_offset_mode_0

    _STATE_FIELDS = (
        "screen_size",
        "screen_addr",
        "tiledata_addr",
        "tile_size",
        "main_screen_enable",
        "sub_screen_enable",
        "hoffset",
        "voffset",
    )

    def dump_state(self) -> dict:
        return {f: getattr(self, f) for f in self._STATE_FIELDS}

    def load_state(self, d: dict) -> None:
        for f in self._STATE_FIELDS:
            setattr(self, f, d[f])


@dataclass
class Object:
    x = 0
    y = 0
    character = 0
    h_flip = False
    v_flip = False
    name_select = False
    priority = 0
    palette = 0
    size = False
