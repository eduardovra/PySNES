from ctypes import c_uint8
from typing import List, Optional, Union, Tuple

from sdl2 import *
import OpenGL.GL as gl
import numpy as np

from .data_structures import *


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

        self.latch_bgofs_ppu1 = 0
        self.latch_bgofs_ppu2 = 0

        # Clock
        self.ticks = 0
        self.line_clocks = 0

        self.field = 0  # 0 for even frames, 1 for odd frames
        self.h_counter = 0  # current dot beign drawn
        self.v_counter = 0  # current scanline beign drawn
        self.frames = 0  # total frames rendered
        # self.vertices = np.array([], dtype=np.float32)
        self.vertices = []

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
        assert self.vmain_addr_remapping == 0, hex(self.vmain_addr_remapping)
        """
        mm     = Address remapping
                    00 = No remapping
                    01 = Remap addressing aaaaaaaaBBBccccc => aaaaaaaacccccBBB
                    10 = Remap addressing aaaaaaaBBBcccccc => aaaaaaaccccccBBB
                    11 = Remap addressing aaaaaaBBBccccccc => aaaaaacccccccBBB
        """

    @property
    def vmdatal(self) -> int:
        return self._vmdatal.value

    @vmdatal.setter
    def vmdatal(self, data: int) -> None:
        self._vmdatal = c_uint8(data)
        if not self.vmain_addr_increment_mode:
            self.write_vram()

    @property
    def vmdatah(self) -> int:
        return self._vmdatah.value

    @vmdatah.setter
    def vmdatah(self, data: int) -> None:
        self._vmdatah = c_uint8(data)
        if self.vmain_addr_increment_mode:
            self.write_vram()

    def write_vram(self) -> None:
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

    def tick(self, master_cycles: int = 2) -> None:
        """
        https://wiki.superfamicom.org/timing

        The SNES master clock runs at about 21.477MHz NTSC
        The SNES runs 1 scanline every 1364 master cycles
        Frames are 262 scanlines in non-interlace mode
        There are always 340 dots ('pixels') per scanline

        For 60 frames/s:
        Each frame should be drawn every 16.6ms
        Each scanline should be drawn every 63.5us
        """
        self.line_clocks += master_cycles
        self.h_counter = self.line_clocks // 4  # Each dot takes ~4 master cycles

        # Wrap H counter
        if self.h_counter > 339:
            self.render_scanline()
            # H counter range is 0-339, but visible part is 22-277
            self.line_clocks = 0
            self.h_counter = 0
            self.v_counter += 1

        # Wrap V counter
        if self.v_counter == 262:
            # V counter range is 0-261, but visible part is 1-224
            self.v_counter = 0
            # Flip even/odd frame
            self.field ^= 1
            # Increment frame counter
            self.frames += 1

        # H-Blank is 62 dots
        self.cpu.status.h_blank_on = not (22 <= self.h_counter <= 277)
        # V-Blank is 38 scanlines
        self.cpu.status.v_blank_on = not (1 <= self.v_counter <= 224)
        # NMI line
        self.cpu.status.nmi_line = self.cpu.status.v_blank_on

    def render_scanline(self):
        """Render current scanline in self.v_counter"""
        # Check F-Blank
        if self.display_disable:
            return

        # Draw picture
        assert self._bgmode in (0, 1), hex(self._bgmode)
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
            self.draw_background(self.bg4, 2, False)
            self.draw_background(self.bg3, 2, False)
            self.draw_background(self.bg4, 2, True)
            self.draw_background(self.bg3, 2, True)
            self.draw_background(self.bg2, 2, False)
            self.draw_background(self.bg1, 2, False)
            self.draw_background(self.bg2, 2, True)
            self.draw_background(self.bg1, 2, True)
            self.draw_objects()
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
            self.draw_background(self.bg3, 2, False)
            if self._bgpriority == 0:
                self.draw_background(self.bg3, 2, True)
            # it seems only bg3 and the sprints are being drawn correctely
            # I suppose its related to bg1 and bg2 being 4bpp (bg3 is 2bpp in this mode)

            # 18/06/2022
            # decided I'm gonna try fixing the bitplane parsing
            # the problem is I'm not sure the data is being copied to vram as it should
            # and that might be the problem as well
            # If I don't succeed, the next idea would be to implement support for
            # importing save state from bnes, so I could be sure the data in memory
            # is right and the problem is I'm interpreting it the wrong way...
            self.draw_background(self.bg2, 4, False)
            self.draw_background(self.bg1, 4, False)
            self.draw_background(self.bg2, 4, True)
            self.draw_background(self.bg1, 4, True)
            self.draw_objects()
            if self._bgpriority == 1:
                self.draw_background(self.bg3, 2, True)

    def draw_background(self, bg: Background, bpp: int, priority_selector: bool) -> None:
        """Draw all tiles from a background"""
        # each individual tile on a background is called a character
        # they can be 8x8, 16x16 or 16x8 pixels
        # the background can be 32 or 64 characters in width or heigth,
        # so it ranges from 256x256 up to 1024x1024 pixels

        # the tile map is a 16 bit chunk of memory configuring which characters
        # are part of the bg and also how they should be displayed. it's stored in vram
        # All tilemaps are 32x32 tiles

        # TODO leaving this commented as background 2 is not enabled for some reason...
        #if not bg.main_screen_enable:
        #    return

        # I came to the conclusion that voffset was a 9 bit
        # number stored in two's complement format (can be negative)
        # Posivite values mean scrolling upwards, so the sign
        # needs to be inverted to work with SDL screen coordinates
        # This was tested in BG mode 0, not sure if it will work with other modes
        screen_height = 448  # TODO 224 when non interlaced
        bg_voffset = bg.voffset
        if (bg_voffset & (1 << (9 - 1))) != 0:  # if sign bit is set e.g., 8bit: 128-255
            bg_voffset = bg_voffset - (1 << 9)  # compute negative value
            bg_voffset *= -1
        else:
            bg_voffset = screen_height - bg_voffset

        x_offset, y_offset = bg.hoffset, bg_voffset

        # ok so it seems the section bellow iterates over the tilemaps
        # which have fixed data lengths, hence the hardcoded sizes make sense
        line_start = (
            bg.screen_addr * 2
        ) & 0xFFFF  # Each addr corresponds to 2 bytes in VRAM

        tile_width, tile_height = 8 << bg.tile_size, 8 << bg.tile_size  # 8 or 16 when tile_size bit set

        x_y_positions = [(x, y) for x in range(32) for y in range(32)]
        tiles: List[Tile] = []

        if bg.screen_size == 0:
            # TODO do the same as screen_size 3
            for mem_index, (x_pos, y_pos) in enumerate(x_y_positions):
                entry_addr = line_start + mem_index * 2
                tile_map = Tilemap.from_buffer(self.vram, entry_addr)
                tile = Tile(
                    tile_map=tile_map,
                    map_num=0,
                    map_position_x=x_pos,
                    map_position_y=y_pos,
                )
                tiles.append(tile)

        elif bg.screen_size == 1:
            # TODO do the same as screen_size 3
            for map_num in range(2):
                map_offset = map_num * 0x800  # 0x800 is the size for a tilemap block
                for mem_index, (x_pos, y_pos) in enumerate(x_y_positions):
                    entry_addr = line_start + map_offset + mem_index * 2
                    tile_map = Tilemap.from_buffer(self.vram, entry_addr)
                    tile = Tile(
                        tile_map=tile_map,
                        map_num=map_num,
                        map_position_x=x_pos,
                        map_position_y=y_pos,
                    )
                    tiles.append(tile)

        elif bg.screen_size == 2:
            assert False, "Not sure if the second tilemap should be numbered 1 or 2"
        else:
            for map_num in range(4):
                map_offset = map_num * 0x800  # 0x800 is the size for a tilemap block
                for mem_index, (x_pos, y_pos) in enumerate(x_y_positions):
                    entry_addr = line_start + map_offset + mem_index * 2
                    tile_map = Tilemap.from_buffer(self.vram, entry_addr)
                    tile = Tile(
                        tile_map=tile_map,
                        map_num=map_num,
                        map_position_x=x_pos,
                        map_position_y=y_pos,
                    )
                    tiles.append(tile)

        tile_width, tile_height = 8 << bg.tile_size, 8 << bg.tile_size  # 8 or 16 when tile_size bit set

        for tile in tiles:
            if tile.tile_map.priority == priority_selector:
                # had to swap x with y for this to work. it's weird but all
                # I know is bnes do the same in the debugger view...
                xx_offset = x_offset + tile.map_position_y * tile_width
                yy_offset = y_offset + tile.map_position_x * tile_height
                if tile.map_num in (1, 3):
                    xx_offset += 32 * tile_width
                if tile.map_num in (2, 3):
                    yy_offset += 32 * tile_height

                self.draw_tiles(
                    bpp=bpp,
                    x_offset=xx_offset,
                    y_offset=yy_offset,
                    tile=tile.tile_map,
                    tile_base_addr=bg.tiledata_addr * 2,
                    tile_width=tile_width,
                    tile_height=tile_height,
                    tile_addr=tile.tile_map.addr,
                )

    def draw_tiles(
        self,
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

        Despite the name, this will generally render 1 tile only...
        """
        # TODO what this method should be doing is to draw all 32 tiles
        # in the tilemap (tilemaps always have 32x32 tiles)
        # tile width/height can be 8x8 or 16x16 pixels for backgrounds
        # objects can have larger sizes though

        for tile_pos_v in range(1):
            for tile_pos_h in range(1):
                # compute x, y positions
                if tile.h_flip:
                    x = x_offset + tile_width - 8 - tile_pos_h * 8
                else:
                    x = x_offset + tile_pos_h * tile_width
                if tile.v_flip:
                    y = y_offset + tile_height - 8 - tile_pos_v * 8
                else:
                    y = y_offset + tile_pos_v * tile_height

                # used when drawing objects...
                if tile_character is not None:
                    tile_size = 8 * bpp  # TODO Why 8 ?
                    tile_addr = tile_character + (tile_pos_h | tile_pos_v << 4)
                    # TODO this is wrong, need to copy the formula used by bsnes
                    vram_index = tile_base_addr + tile_addr * tile_size  # type: ignore
                else:
                    c = tile_addr
                    if bpp == 2:
                        vram_index = (tile_base_addr + c * 16) & 0x1fff0 & 0xFFFF
                    elif bpp == 4:
                        vram_index = (tile_base_addr + c * 32) & 0x1ffe0 & 0xFFFF
                    elif bpp == 8:
                        vram_index = (tile_base_addr + c * 16) & 0x1fff0 & 0xFFFF
                    else:
                        raise RuntimeError(f"Unsupported bpp {bpp}")

                self.draw_tile(
                    tile=tile,
                    tile_data=self.vram,
                    tile_data_index=vram_index,
                    bpp=bpp,
                    x_offset=x,
                    y_offset=y,
                )

    def draw_tile(
        self,
        tile: Union[Tilemap, Object],
        tile_data: bytes,
        tile_data_index: int,
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
            # Wrap y around
            screen_height = 448 # 224 when non interlaced
            if y >= screen_height:
                y = y % screen_height

            # ugly hack to only draw the current scanline
            if y != self.v_counter:
                continue

            # Each iteration will print a pixel from the line
            for pixel, x in zip(pixel_sequence, x_sequence):
                self.draw_point(i, tile_data, tile_data_index, bpp, tile.palette, pixel, x, y)

    def draw_point(
        self,
        i: int,
        tile_data: bytes,
        tile_data_index: int,
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
        assert bpp in (2, 4), bpp

        # offset to the correct vram byte
        i += tile_data_index

        # 2bpp
        l, h = tile_data[i + 0], tile_data[i + 1]
        color = (h & mask) >> pixel << 1 | (l & mask) >> pixel << 0
        if bpp >= 4:
            l, h = tile_data[i + 16], tile_data[i + 17]
            color |= (h & mask) >> pixel << 3 | (l & mask) >> pixel << 2

        # NOTE: I guess this is GL_RGB5?

        # SNES default resolution (NTSC)
        SCREEN_WIDTH = 256
        SCREEN_HEIGHT = 224
        # For PAL mode:
        # SCREEN_HEIGHT = 240

        x_ndc = 2.0 * (x / SCREEN_WIDTH) - 1.0
        y_ndc = 1.0 - 2.0 * (y / SCREEN_HEIGHT)

        """
        https://sneslab.net/wiki/Backdrop_Color
        A Backdrop Color is one that appears behind all other layers. The SNES has two backdrop colors:
        one for the Main Screen and one for the Sub Screen.

        The main screen's backdrop color is known as color 0 and is the very first entry of CGRAM.
        The sub screen's backdrop color is known as the fixed color and is set via the 8-bit COLDATA port (2132h).[1][2]
        """
        # TODO this is incorrect. the backdrop color should only be used when all layers above are transparent
        r, g, b = self.get_rbg_colors(bpp, 0, 0)

        # 00 is considered transparent in all palettes
        if color:
            r, g, b = self.get_rbg_colors(bpp, palette, color)

        # self.vertices = np.append(self.vertices, [x_ndc, y_ndc, 0.0, r, g, b])
        self.vertices.extend([x_ndc, y_ndc, 0.0, r, g, b])

    def get_rbg_colors(self, bpp: int, palette: int, color: int) -> tuple:
        # 4 colors (2bpp palette) x 2 bytes each color
        palette_index = palette * (bpp ** 2) * 2
        color_index = palette_index + color * 2
        data = self.cgram[color_index] | self.cgram[color_index + 1] << 8

        r_5bit = data >> 0 & 0x1F
        g_5bit = data >> 5 & 0x1F
        b_5bit = data >> 10 & 0x1F

        r_8bit = (r_5bit * 255) // 31
        g_8bit = (g_5bit * 255) // 31
        b_8bit = (b_5bit * 255) // 31

        # normalize to [0, 1] for OpenGL
        r = r_8bit / 255
        g = g_8bit / 255
        b = b_8bit / 255

        return r, g, b

    def draw_objects(self) -> None:
        # objects are the building blocks for sprites
        # they can move independently from the background and always use 4bpp
        # they can be 8x8, 16x16, 32x32 or 64x64 pixels in size
        # oam is the memory region where the objects properties are stored. each obj uses 34 bits

        for obj in self.oam.objects:
            # Draw object if it's within the visible area (256x224)
            # TODO handle wrapping
            # x_visible = obj.x > -8 and obj.x < 256 - 8  # TODO hardcoded tile size
            # y_visible = obj.y > -8 and obj.y < 224  # TODO probably wrong
            # if x_visible and y_visible:
            if obj.y != 240:  # Games seem to use this value to hide the objects
                tile_width, tile_height = self.get_obj_dimensions(obj.size)

                self.draw_tiles(
                    bpp=4,  # Always 4bpp for objects
                    x_offset=obj.x,
                    y_offset=obj.y,
                    tile=obj,
                    tile_base_addr=self.oam_tiledata_address * 2,  # Indexed in words
                    tile_width=tile_width,
                    tile_height=tile_height,
                    tile_character=obj.character,
                )

    def get_obj_dimensions(self, obj_size: int) -> Tuple[int, int]:
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
    #ppu.bgmode = 1
    #ppu.bg1sc_set(0)
    #ppu.bg2sc_set(0)
    #ppu.bg12nba_set(0x01)
    #ppu.bg34nba_set(0x00)

    # Draw BG1, Mode 1 - Super Mario World
    # Bit Depth 2bpp
    # Map Size 32x32
    # Map Addr 0x0000 (comes from BG1SC)
    # Tile Size 8x8
    # Tile Addr 0x2000
    ppu.bgmode = 1
    ppu.bg1sc_set(0x23)
    ppu.bg2sc_set(0x33)
    ppu.bg3sc_set(0x53)
    ppu.bg12nba_set(0x00)
    ppu.bg34nba_set(0x04)

    # OAM base address 0xC000
    ppu.obsel_set(0x03)  # base size 0
    # ppu.obsel_set(0x23)  # base size 1
    # ppu.obsel_set(0x43)  # base size 2
    # ppu.obsel_set(0x63)  # base size 3

    # Main/Sub screen enable
    ppu.tm_set(0x11)
    ppu.ts_set(0x11)

    ppu.render()

    SDL_Delay(5000)

    return


if __name__ == "__main__":
    import cProfile

    # cProfile.run("main()", sort="cumulative")
    main()
