from ctypes import (
    c_uint16,
    c_uint8,
    LittleEndianStructure,
)
from typing import Optional, Union
from dataclasses import dataclass

from sdl2 import *


@dataclass
class Background:
    screen_size = 0
    screen_addr = 0
    tiledata_addr = 0
    tile_size = 0
    main_screen_enable = True
    sub_screen_enable = True


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


class Tilemap(LittleEndianStructure):
    """
    palette = (high >> 2) & 7
    priotity = (high >> 5) & 1
    h_flip = (high >> 6) & 1
    v_flip = (high >> 7) & 1
    addr = high & 3 | low
    """

    _fields_ = [
        ("addr", c_uint16, 10),
        ("palette", c_uint16, 3),
        ("priority", c_uint16, 1),
        ("h_flip", c_uint16, 1),
        ("v_flip", c_uint16, 1),
    ]


class Ppu:
    """
    Picture Processor Unit: 15-Bit
    """

    def __init__(
        self,
        cpu,
        *,
        vram_dump: Optional[bytes] = None,
        cgram_dump: Optional[bytes] = None,
        oam_dump: Optional[bytes] = None,
    ) -> None:
        # CPU ref is used to control NMI line on V-Blank
        self.cpu = cpu

        # VRAM - Video RAM
        if vram_dump is None:
            self.vram = bytearray(64 * 1024)
        else:
            self.vram = bytearray(vram_dump)
        self.vmain = 0x00
        self.vmaddl = c_uint8(0x00)
        self.vmaddh = c_uint8(0x00)
        self._vmdatal = c_uint8(0x00)
        self._vmdatah = c_uint8(0x00)

        self.inidisp_set(0)

        # CGRAM - Palette Data
        if cgram_dump is None:
            self.cgram = bytearray(512)
        else:
            self.cgram = bytearray(cgram_dump)
        self._cgadd = c_uint8(0x00)
        self._cgdata: Optional[c_uint8] = None

        # OAM
        self.oam = OAM(oam_dump=oam_dump)
        self._oamadd = 0
        self._oamodd = 0
        self._oamdata = 0
        self.obsel_set(0)
        self.oam_main_screen_enable = True
        self.oam_sub_screen_enable = True

        # Background
        self._bgmode = 0x00
        self.bg1 = Background()
        self.bg2 = Background()
        self.bg3 = Background()
        self.bg4 = Background()

        # Clock
        self.ticks = 0
        self.master_cycles = 0

        self.field = 0  # 0 for even frames, 1 for odd frames
        self.h_counter = 0
        self.v_counter = 0

    def inidisp_set(self, data: int) -> None:
        # TODO reset OAM addr if writing while on first blank line
        self.display_brightness = data >> 0 & 15
        self.display_disable = data >> 7 & 1

    @property
    def bgmode(self) -> int:
        raise NotImplementedError

    @bgmode.setter
    def bgmode(self, data: int) -> None:
        self._bgmode = data >> 0 & 7
        self._bgpriority = data >> 3 & 1
        self.bg1.tile_size = data >> 4 & 1
        self.bg2.tile_size = data >> 5 & 1
        self.bg3.tile_size = data >> 6 & 1
        self.bg4.tile_size = data >> 7 & 1

    @property
    def vmain(self) -> int:
        return self._vmain.value

    @vmain.setter
    def vmain(self, data: int) -> None:
        amounts = (1, 32, 128, 128)
        self._vmain = c_uint8(data)
        self.vmain_addr_increment_mode = data >> 7
        self.vmain_addr_increment_amount = amounts[data & 0x03]
        self.vmain_addr_remapping = (data >> 2) & 0x03
        assert self.vmain_addr_remapping == 0

    @property
    def vmdatal(self) -> int:
        return self._vmdatal.value

    @vmdatal.setter
    def vmdatal(self, data: int) -> None:
        self._vmdatal = c_uint8(data)
        if not self.vmain_addr_increment_mode:
            self.write_vram(data)

    @property
    def vmdatah(self) -> int:
        return self._vmdatah.value

    @vmdatah.setter
    def vmdatah(self, data: int) -> None:
        self._vmdatah = c_uint8(data)
        if self.vmain_addr_increment_mode:
            self.write_vram(data)

    def write_vram(self, data: int) -> None:
        base_addr = (self.vmaddl.value | self.vmaddh.value << 8) * 2
        self.vram[base_addr + 0] = self._vmdatal.value
        self.vram[base_addr + 1] = self._vmdatah.value
        self.increment_vmadd()

    def increment_vmadd(self) -> None:
        addr = (
            self.vmaddl.value | self.vmaddh.value << 8
        ) + self.vmain_addr_increment_amount
        self.vmaddl.value = (addr >> 0) & 0xFF
        self.vmaddh.value = (addr >> 8) & 0xFF

    @property
    def cgadd(self) -> int:
        return self._cgadd.value

    @cgadd.setter
    def cgadd(self, data: int) -> None:
        self._cgadd = c_uint8(data)
        self._cgdata = None

    @property
    def cgdata(self) -> int:
        base_addr = self._cgadd.value * 2
        if self._cgdata is None:
            self._cgdata = c_uint8(self.cgram[base_addr])
            return self._cgdata.value
        data = self.cgram[base_addr + 1]
        self._cgadd.value += 1
        self._cgdata = None
        return data

    @cgdata.setter
    def cgdata(self, data: int) -> None:
        if self._cgdata is None:
            self._cgdata = c_uint8(data)
            return
        base_addr = self._cgadd.value * 2
        self.cgram[base_addr + 0] = self._cgdata.value
        self.cgram[base_addr + 1] = data & 0x7F
        self._cgadd.value += 1
        self._cgdata = None

    @property
    def stat78(self) -> int:
        # TODO implement the other fields
        return self.field << 7

    @property
    def slhv(self) -> int:
        """When read, the H/V counter (as read from $213C and $213D) will be latched to
        the current X and Y position if bit 7 of $4201 is set. The data actually read is open bus."""
        return 0  # TODO

    def obsel_set(self, data: int) -> None:
        """OBSEL - Object Size and Character Address"""
        self.oam_tiledata_address = (data & 7) << 13
        self.oam_nameselect = data >> 3 & 3
        self.oam_base_size = data >> 5 & 7

    @property
    def oamaddl(self) -> int:
        raise NotImplementedError

    @oamaddl.setter
    def oamaddl(self, data: int) -> None:
        self._oamadd = (self._oamadd & 0x100) | (data & 0xFF)
        self._oamodd = 0

    @property
    def oamaddh(self) -> int:
        raise NotImplementedError

    @oamaddh.setter
    def oamaddh(self, data: int) -> None:
        self._oam_priority_activation = bool(data & 0x80)
        self._oamadd = (self._oamadd & 0x0FF) | (data & 1) << 8
        self._oamodd = 0

    @property
    def oamdata(self) -> int:
        index = self.oam_index()
        data = self.oam[index]
        self.oam_next()
        return data

    @oamdata.setter
    def oamdata(self, data: int) -> None:
        # Buffer always set by even write
        if self._oamodd == 0:
            self._oamdata = data

        # High bank goes directly through
        if self._oamadd & 0x100:
            index = self.oam_index()
            self.oam[index] = data & 0xFF

        # Low bank does word only on odd writes
        elif self._oamodd == 1:
            index = self.oam_index()
            self.oam[index - 1] = self._oamdata
            self.oam[index - 0] = data & 0xFF

        self.oam_next()

    def oam_index(self) -> int:
        addr = (self._oamadd * 2) + self._oamodd
        if self._oamadd & 0x100:
            return 0x200 | addr & 0x1F
        return addr

    def oam_next(self) -> None:
        self._oamodd ^= 1
        if self._oamodd == 0:
            self._oamadd = (self._oamadd + 1) & 0x1FF

    def bg1sc_set(self, data: int) -> None:
        self.bg1.screen_size = data & 0x03
        self.bg1.screen_addr = data >> 2 << 10  # Copied from bsnes

    def bg2sc_set(self, data: int) -> None:
        self.bg2.screen_size = data & 0x03
        self.bg2.screen_addr = data >> 2 << 10  # Copied from bsnes

    def bg3sc_set(self, data: int) -> None:
        self.bg3.screen_size = data & 0x03
        self.bg3.screen_addr = data >> 2 << 10  # Copied from bsnes

    def bg4sc_set(self, data: int) -> None:
        self.bg4.screen_size = data & 0x03
        self.bg4.screen_addr = data >> 2 << 10  # Copied from bsnes

    def bg12nba_set(self, data: int) -> None:
        self.bg1.tiledata_addr = (data >> 0 & 15) << 12
        self.bg2.tiledata_addr = (data >> 4 & 15) << 12

    def bg34nba_set(self, data: int) -> None:
        self.bg3.tiledata_addr = (data >> 0 & 15) << 12
        self.bg4.tiledata_addr = (data >> 4 & 15) << 12

    def tm_set(self, data: int) -> None:
        self.bg1.main_screen_enable = bool(data >> 0 & 1)
        self.bg2.main_screen_enable = bool(data >> 1 & 1)
        self.bg3.main_screen_enable = bool(data >> 2 & 1)
        self.bg4.main_screen_enable = bool(data >> 3 & 1)
        self.oam_main_screen_enable = bool(data >> 4 & 1)

    def ts_set(self, data: int) -> None:
        self.bg1.sub_screen_enable = bool(data >> 0 & 1)
        self.bg2.sub_screen_enable = bool(data >> 1 & 1)
        self.bg3.sub_screen_enable = bool(data >> 2 & 1)
        self.bg4.sub_screen_enable = bool(data >> 3 & 1)
        self.oam_sub_screen_enable = bool(data >> 4 & 1)

    def tick(self, master_cycles: int, renderer) -> None:
        """
        The SNES master clock runs at about 21.477MHz NTSC
        The SNES runs 1 scanline every 1364 master cycles
        Frames are 262 scanlines in non-interlace mode
        There are always 340 dots ('pixels') per scanline

        For 60 frames/s:
        Each frame should be drawn every 16.6ms
        Each scanline should be drawn every 63.5us
        """
        self.ticks += 1
        self.master_cycles += master_cycles
        self.h_counter = self.master_cycles // 4  # Each dot takes ~4 master cycles

        # Wrap H counter
        if self.h_counter > 339:
            # H counter range is 0-339, but visible part is 22-277
            self.master_cycles = 0
            self.h_counter = 0
            self.v_counter += 1

        # Wrap V counter
        if self.v_counter == 262:
            # V counter range is 0-261, but visible part is 1-224
            self.v_counter = 0
            # Flip even/odd frame
            self.field ^= 1
            self.render(renderer)

        # H-Blank is 62 dots
        self.cpu.status.h_blank_on = not (22 <= self.h_counter <= 277)
        # V-Blank is 38 scanlines
        self.cpu.status.v_blank_on = not (1 <= self.v_counter <= 224)
        # NMI line
        self.cpu.status.nmi_line = self.cpu.status.v_blank_on

    def render(self, renderer) -> None:
        # Default background color
        self.set_color(renderer, 2, 0, 0)
        SDL_RenderClear(renderer)

        # Check F-Blank
        if self.display_disable:
            return

        # Draw picture
        assert self._bgmode in (0, 1)
        """
        https://bin.smwcentral.net/u/4842/regs.txt
        Mode 0
        ------

        In Mode 0, you have 4 BGs of 4 colors each. To calculate the starting palette
        entry for a particular tile, you calculate:
        ppp*4 + (BG#-1)*32

        The background priority is (from 'front' to 'back'):
        Sprites with priority 3
        BG1 tiles with priority 1
        BG2 tiles with priority 1
        Sprites with priority 2
        BG1 tiles with priority 0
        BG2 tiles with priority 0
        Sprites with priority 1
        BG3 tiles with priority 1
        BG4 tiles with priority 1
        Sprites with priority 0
        BG3 tiles with priority 0
        BG4 tiles with priority 0
        """
        if self._bgmode == 0:
            self.draw_background(renderer, self.bg4, 2, False)
            self.draw_background(renderer, self.bg3, 2, False)
            self.draw_background(renderer, self.bg4, 2, True)
            self.draw_background(renderer, self.bg3, 2, True)
            self.draw_background(renderer, self.bg2, 2, False)
            self.draw_background(renderer, self.bg1, 2, False)
            self.draw_background(renderer, self.bg2, 2, True)
            self.draw_background(renderer, self.bg1, 2, True)
            self.draw_objects(renderer)
        elif self._bgmode == 1:
            """
            BG3 tiles with priority 1 if bit 3 of $2105 is set
            Sprites with priority 3
            BG1 tiles with priority 1
            BG2 tiles with priority 1
            Sprites with priority 2
            BG1 tiles with priority 0
            BG2 tiles with priority 0
            Sprites with priority 1
            BG3 tiles with priority 1 if bit 3 of $2105 is clear
            Sprites with priority 0
            BG3 tiles with priority 0
            """
            # self.draw_background(renderer, self.bg3, 2, False)
            # if self._bgpriority == 0:
            #    self.draw_background(renderer, self.bg3, 2, True)
            # self.draw_background(renderer, self.bg2, 4, False)
            # self.draw_background(renderer, self.bg1, 4, False)
            # self.draw_background(renderer, self.bg2, 4, True)
            # self.draw_background(renderer, self.bg1, 4, True)
            self.draw_objects(renderer)
            # if self._bgpriority == 1:
            #    self.draw_background(renderer, self.bg3, 2, True)

        SDL_RenderPresent(renderer)

    def draw_background(
        self, renderer, bg: Background, bpp: int, priority_selector: bool
    ) -> None:
        if not bg.main_screen_enable:
            return

        x_offset, y_offset = 0, 0
        line_start = (
            bg.screen_addr * 2
        ) & 0xFFFF  # Each addr corresponds to 2 bytes in VRAM
        line_end = line_start + 0x800  # Total size of BG in memory
        line_step = 0x40
        # Each iteration will print a line of 32 tiles x 8x8 pixels
        for line in range(line_start, line_end, line_step):
            col_start = 0x00
            col_end = 0x40
            col_step = 0x02
            # Each iteration will print 1 tile of 8x8 pixels
            for col in range(col_start, col_end, col_step):
                # Parse Tilemap entry - 2 bytes
                entry_addr = line + col
                tile = Tilemap.from_buffer(self.vram, entry_addr)
                if tile.priority == priority_selector:
                    self.draw_tiles(
                        renderer=renderer,
                        bpp=bpp,
                        x_offset=x_offset,
                        y_offset=y_offset,
                        tile=tile,
                        tile_base_addr=bg.tiledata_addr * 2,
                        tile_width=8,
                        tile_height=8,
                        tile_addr=tile.addr,
                    )

                x_offset += 8
                if x_offset == 8 * 32:  # 32 tiles with 8 pixels width
                    x_offset = 0

            y_offset += 8

    def draw_tiles(
        self,
        renderer,
        bpp: int,
        x_offset: int,
        y_offset: int,
        tile: Union[Tilemap, Object],
        tile_base_addr: int,
        tile_width: int,
        tile_height: int,
        tile_addr: Optional[int] = None,
        tile_character: Optional[int] = None,
    ) -> None:
        """
        Determines the number of horizontal and vertical
        tiles to be drawn accordingly to width and height,
        then calls self.draw_tile to render them
        """
        tile_size = 8 * bpp  # TODO Why 8 ?

        for tile_v in range(tile_height // 8):
            for tile_h in range(tile_width // 8):
                if tile.h_flip:
                    x = x_offset + tile_width - 8 - tile_h * 8
                else:
                    x = x_offset + tile_h * 8

                if tile.v_flip:
                    y = y_offset + tile_height - 8 - tile_v * 8
                else:
                    y = y_offset + tile_v * 8

                if tile_character is not None:
                    tile_addr = tile_character + (tile_h | tile_v << 4)

                vram_index = tile_base_addr + tile_addr * tile_size  # type: ignore
                tile_data = self.vram[vram_index:]

                self.draw_tile(
                    renderer,
                    tile,
                    tile_data,
                    bpp,
                    x,
                    y,
                )

    def draw_tile(
        self,
        renderer,
        tile: Union[Tilemap, Object],
        tile_data: bytes,
        bpp: int,
        x_offset: int,
        y_offset: int,
    ) -> None:
        """Draw one 8x8 tile"""
        x_sequence = range(x_offset, x_offset + 8)
        if tile.h_flip:
            x_sequence = list(reversed(x_sequence))
        y_sequence = range(y_offset, y_offset + 8)
        if tile.v_flip:
            y_sequence = list(reversed(y_sequence))

        # Iterator for lines in the tile
        line_sequence = range(0, 16, 2)
        # Iterator for pixels in lines
        pixel_sequence = list(reversed(range(8)))
        # Each iteration will print a line of a tile
        for i, y in zip(line_sequence, y_sequence):
            # Each iteration will print a pixel from the line
            for pixel, x in zip(pixel_sequence, x_sequence):
                self.draw_point(renderer, i, tile_data, bpp, tile.palette, pixel, x, y)

    def draw_point(
        self,
        renderer,
        i: int,
        tile_data: bytes,
        bpp: int,
        palette: int,
        pixel: int,
        x: int,
        y: int,
    ) -> None:
        # Bitplane handling
        # The first byte is composed of the first
        # 8 least significant bits of the pixel
        # and the second byte if composed of the
        # 8 most significant bits
        mask = 1 << pixel
        # 2bpp
        l, h = tile_data[i + 0], tile_data[i + 1]
        color = (h & mask) >> pixel << 1 | (l & mask) >> pixel << 0
        if bpp >= 4:
            l, h = tile_data[i + 16], tile_data[i + 17]
            color |= (h & mask) >> pixel << 3 | (l & mask) >> pixel << 2
        # 00 is considered transparent in all palettes
        if color:
            self.set_color(renderer, bpp, palette, color)
            SDL_RenderDrawPoint(renderer, x, y)

    def set_color(self, renderer, bpp: int, palette: int, color: int) -> None:
        # 4 colors (2bpp palette) x 2 bytes each color
        palette_index = palette * (bpp ** 2) * 2
        color_index = palette_index + color * 2
        data = self.cgram[color_index] | self.cgram[color_index + 1] << 8
        r = data >> 0 & 0x1F
        g = data >> 5 & 0x1F
        b = data >> 10 & 0x1F
        # alpha = SDL_ALPHA_OPAQUE if color else SDL_ALPHA_TRANSPARENT
        # TODO Try to enable again when all background are being rendered
        alpha = SDL_ALPHA_OPAQUE
        # Multiply the colors to make them more vibrant
        brightness = self.display_brightness // 15
        color_multiplier = 8 * brightness
        SDL_SetRenderDrawColor(
            renderer,
            r * color_multiplier,
            g * color_multiplier,
            b * color_multiplier,
            alpha,
        )

    def draw_objects(self, renderer) -> None:
        for obj in self.oam.objects:
            # Draw object if it's within the visible area (256x224)
            # TODO handle wrapping
            # x_visible = obj.x > -8 and obj.x < 256 - 8  # TODO hardcoded tile size
            # y_visible = obj.y > -8 and obj.y < 224  # TODO probably wrong
            # if x_visible and y_visible:
            if obj.y != 240:  # Games seem to use this value to hide the objects
                tile_width, tile_height = self.get_obj_dimensions(obj.size)

                self.draw_tiles(
                    renderer=renderer,
                    bpp=4,  # Always 4bpp for objects
                    x_offset=obj.x,
                    y_offset=obj.y,
                    tile=obj,
                    tile_base_addr=self.oam_tiledata_address * 2,  # Indexed in words
                    tile_width=tile_width,
                    tile_height=tile_height,
                    tile_character=obj.character,
                )

    def get_obj_dimensions(self, obj_size: int) -> tuple[int, int]:
        """
        000 =  8x8  and 16x16 sprites
        001 =  8x8  and 32x32 sprites
        010 =  8x8  and 64x64 sprites
        011 = 16x16 and 32x32 sprites
        100 = 16x16 and 64x64 sprites
        101 = 32x32 and 64x64 sprites
        110 = 16x32 and 32x64 sprites (Not officially supported)
        111 = 16x32 and 32x32 sprites (Not officially supported)
        """
        table = (
            ((8, 8), (16, 16)),
            ((8, 8), (32, 32)),
            ((8, 8), (64, 64)),
            ((16, 16), (32, 32)),
            ((16, 16), (64, 64)),
            ((32, 32), (64, 64)),
            ((16, 32), (32, 64)),
            ((16, 32), (32, 32)),
        )

        return table[self.oam_base_size][obj_size]


class OAM:
    def __init__(self, *, oam_dump: Optional[bytes] = None) -> None:
        # Object Attribute Memory
        self.oam = bytearray(512 + 32)
        self.objects = [Object() for i in range(128)]

        # Load objects from dump file
        if oam_dump:
            for addr, data in enumerate(oam_dump):
                self[addr] = data

    def __getitem__(self, addr: int) -> int:
        return self.oam[addr]

    def __setitem__(self, addr: int, data: int) -> None:
        if self.oam[addr] != data:
            self.oam[addr] = data
            self.update_object(addr)

    def update_object(self, addr: int) -> None:
        if addr & 0x200:
            self.update_high_table(addr)
        else:
            self.update_low_table(addr)

    def update_high_table(self, addr: int) -> None:
        obj_base = (addr & 0x1F) * 4
        data = self.oam[addr]
        for obj_index in range(4):
            obj_num = obj_base + obj_index
            obj = self.objects[obj_num]
            sx = data >> (obj_index * 2)
            obj.x = (obj.x & 0xFF) | (sx & 0x01) << 8
            obj.size = bool(sx & 0x02)

    def update_low_table(self, addr: int) -> None:
        obj_num = addr // 4
        addr = obj_num * 4
        obj = self.objects[obj_num]

        data = self.oam[addr + 0]
        obj.x = obj.x & 0x100 | data & 0xFF

        data = self.oam[addr + 1]
        obj.y = data & 0xFF

        data = self.oam[addr + 2]
        obj.character = obj.character & 0x100 | data & 0xFF

        data = self.oam[addr + 3]
        obj.name_select = bool(data & 0x01)
        obj.palette = (
            (data >> 1) & 0x07
        ) + 8  # Objects use the palettes present in the second half of CGRAM
        obj.priority = (data >> 4) & 0x03
        obj.h_flip = bool(data & 0x40)
        obj.v_flip = bool(data & 0x80)


def main():
    # Memory dumps
    # vram_file = "roms/test_oam-vram.bin"
    # cgram_file = "roms/test_oam-cgram.bin"
    # oam_file = "roms/test_oam-oam.bin"
    vram_file = "roms/Super Mario World (U) [!]-vram.bin"
    cgram_file = "roms/Super Mario World (U) [!]-cgram.bin"
    oam_file = "roms/Super Mario World (U) [!]-oam.bin"
    with open(vram_file, "rb") as f:
        vram_dump = f.read()
    with open(cgram_file, "rb") as f:
        cgram_dump = f.read()
    with open(oam_file, "rb") as f:
        oam_dump = f.read()
    ppu = Ppu(None, vram_dump=vram_dump, cgram_dump=cgram_dump, oam_dump=oam_dump)

    SDL_Init(SDL_INIT_VIDEO)
    window = SDL_CreateWindow(b"PySNES", 0, 0, 768, 768, SDL_WINDOW_SHOWN)
    renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED)
    SDL_SetRenderDrawBlendMode(renderer, SDL_BLENDMODE_BLEND)
    SDL_RenderSetScale(renderer, 2, 2)

    # Setup registers
    # Draw BG1, Mode 0 - test_oam.smc
    # Bit Depth 2bpp
    # Map Size 32x32
    # Map Addr 0x0000 (comes from BG1SC)
    # Tile Size 8x8
    # Tile Addr 0x2000
    ppu.bgmode = 1
    ppu.bg1sc_set(0)
    ppu.bg2sc_set(0)
    ppu.bg12nba_set(0x01)
    ppu.bg34nba_set(0x00)

    # OAM base address 0xC000
    ppu.obsel_set(0x03)  # base size 0
    # ppu.obsel_set(0x23)  # base size 1
    # ppu.obsel_set(0x43)  # base size 2
    # ppu.obsel_set(0x63)  # base size 3

    # Main/Sub screen enable
    ppu.tm_set(0x11)
    ppu.ts_set(0x11)

    ppu.render(renderer)

    return


if __name__ == "__main__":
    import cProfile

    # cProfile.run("main()", sort="cumulative")
    main()
