from ctypes import (
    c_uint16,
    LittleEndianStructure,
)
from dataclasses import dataclass


@dataclass
class Background:
    screen_size = 0
    """
    All tilemaps are 32x32 tiles. This controls the number of tilemaps in memory
    * 00=32x32
    * 01=64x32
    * 10=32x64
    * 11=64x64

    If the map has a dimension greater than 32 (e.g. 64x32), array doesn't have 64 tile indexes per row,
    instead it will store two 32x32 maps right after each other in VRAM.
    The first map (32x32 tiles = 2*32*32 bytes) will represent the
    left part of the map and the second one (same size as the first one) will represent the right side of the map.
    """

    screen_addr = 0
    tiledata_addr = 0
    tile_size = 0
    """
    If the BG character size for BG1/BG2/BG3/BG4 bit is set,
    then the BG is made of 16x16 tiles. Otherwise, 8x8 tiles are used.
    """

    main_screen_enable = True
    sub_screen_enable = True
    hoffset = 0
    voffset = 0


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


# DEPRECATED in favor of the faster version of this class below
class Tilemap_(LittleEndianStructure):
    """
    palette = (high >> 2) & 7
    priotity = (high >> 5) & 1
    h_flip = (high >> 6) & 1
    v_flip = (high >> 7) & 1
    addr = high & 3 | low           More like a tile id, it's an index selecting which character to draw
    """

    _fields_ = [
        ("addr", c_uint16, 10),
        ("palette", c_uint16, 3),
        ("priority", c_uint16, 1),
        ("h_flip", c_uint16, 1),
        ("v_flip", c_uint16, 1),
    ]


@dataclass
class Tilemap:
    addr: int
    palette: int
    priority: int
    h_flip: int
    v_flip: int

    @classmethod
    def from_buffer(cls, data: bytearray, addr: int) -> "Tilemap":
        low = data[addr]
        high = data[addr + 1]
        return cls(
            addr=(high & 3) << 8 | low,
            palette=(high >> 2) & 7,
            priority=(high >> 5) & 1,
            h_flip=(high >> 6) & 1,
            v_flip=(high >> 7) & 1,
        )


@dataclass
class Tile:
    tile_map: Tilemap
    map_num: int  # map number 0-3
    map_position_x: int  # x index inside de map 0-31
    map_position_y: int  # y index inside de map 0-31
