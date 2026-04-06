from ctypes import c_uint8
from typing import Optional, Union, Tuple, TYPE_CHECKING

import cython
from sdl2 import *

from .data_structures import Background, Object, Tilemap

if TYPE_CHECKING:
    from ..scheduler import Scheduler
    from ..bus import Bus

# NTSC scanline timing (master clocks)
_MC_PER_SCANLINE: int = 1364        # master clocks per scanline
_HBLANK_START_MC: int = 1096        # dot 274 * 4 mc/dot — when H-Blank begins
_VBLANK_START_LINE: int = 225       # first V-Blank scanline (after 224 visible lines)
_TOTAL_SCANLINES: int = 262         # total scanlines per frame (NTSC)

# SNES default resolution (NTSC)
SCREEN_WIDTH = 256
SCREEN_HEIGHT = 224
# For PAL mode:
# SCREEN_HEIGHT = 240


@cython.cclass
class Ppu:
    """
    Picture Processor Unit: 15-Bit
    """

    def __init__(
        self,
        *,
        vram_dump: Optional[bytes] = None,
        cgram_dump: Optional[bytes] = None,
        oam_dump: Optional[bytes] = None,
    ) -> None:
        # Scheduler and bus are attached after construction via attach()
        self.scheduler = None
        self.bus = None

        # VRAM - Video RAM
        if vram_dump is None:
            self.vram = bytearray(64 * 1024)
        else:
            self.vram = bytearray(vram_dump)
        self.vmain = 0x00
        self.vmaddl: cython.uchar = 0
        self.vmaddh: cython.uchar = 0
        self._vmdatal: cython.uchar = 0
        self._vmdatah: cython.uchar = 0

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
        self.bg1 = Background(number=1, color_offset_mode_0=0x00)
        self.bg2 = Background(number=2, color_offset_mode_0=0x20)
        self.bg3 = Background(number=3, color_offset_mode_0=0x40)
        self.bg4 = Background(number=4, color_offset_mode_0=0x60)

        self.latch_bgofs_ppu1 = 0
        self.latch_bgofs_ppu2 = 0

        # Mode 7 matrix registers (0x211B-0x2120), 2-write latched
        self._m7_latch: cython.uchar = 0
        self.m7a: cython.int = 0
        self.m7b: cython.int = 0
        self.m7c: cython.int = 0
        self.m7d: cython.int = 0
        self.m7x: cython.int = 0
        self.m7y: cython.int = 0

        # Window registers (0x2123-0x212B)
        self.w12sel: cython.uchar = 0
        self.w34sel: cython.uchar = 0
        self.wobjsel: cython.uchar = 0
        self.wh0: cython.uchar = 0   # Window 1 left
        self.wh1: cython.uchar = 0   # Window 1 right
        self.wh2: cython.uchar = 0   # Window 2 left
        self.wh3: cython.uchar = 0   # Window 2 right
        self.wbglog: cython.uchar = 0
        self.wobjlog: cython.uchar = 0

        # Window screen disable (0x212E-0x212F)
        self.tmw: cython.uchar = 0
        self.tsw: cython.uchar = 0

        # Color math registers (0x2130-0x2132)
        self.cgwsel: cython.uchar = 0
        self.cgadsub: cython.uchar = 0
        self.coldata_r: cython.uchar = 0
        self.coldata_g: cython.uchar = 0
        self.coldata_b: cython.uchar = 0

        # Mosaic
        self.mosaic_enabled = [False, False, False, False]
        self.mosaic_size = 0

        self.field = 0  # 0 for even frames, 1 for odd frames
        self.h_counter = 0  # current dot being drawn (updated at H-Blank / scanline start)
        self.v_counter = 0  # current scanline being drawn
        self.frames = 0  # total frames rendered

        self.main_bgs = [0x00] * 256 * 262  # 262 was 239 before

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
    def vmdatal(self) -> cython.uchar:
        return self._vmdatal

    @vmdatal.setter
    def vmdatal(self, data: cython.uchar) -> None:
        self._vmdatal = data
        if not self.vmain_addr_increment_mode:
            self.write_vram()

    @property
    def vmdatah(self) -> cython.uchar:
        return self._vmdatah

    @vmdatah.setter
    def vmdatah(self, data: cython.uchar) -> None:
        self._vmdatah = data
        if self.vmain_addr_increment_mode:
            self.write_vram()

    def write_vram(self) -> None:
        base_addr = (self.vmaddl | self.vmaddh << 8) * 2
        # base_addr &= 0xFFFF
        assert base_addr < len(self.vram), f"VRAM write out of bounds: 0x{base_addr:06X}"
        self.vram[base_addr + 0] = self._vmdatal
        self.vram[base_addr + 1] = self._vmdatah
        self.increment_vmadd()

    def increment_vmadd(self) -> None:
        addr = (
            self.vmaddl | self.vmaddh << 8
        ) + self.vmain_addr_increment_amount
        self.vmaddl = (addr >> 0) & 0xFF
        self.vmaddh = (addr >> 8) & 0xFF

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
        self.bg1.tiledata_addr = (data >> 0 & 15) << 13
        self.bg2.tiledata_addr = (data >> 4 & 15) << 13

    def bg34nba_set(self, data: int) -> None:
        self.bg3.tiledata_addr = (data >> 0 & 15) << 13
        self.bg4.tiledata_addr = (data >> 4 & 15) << 13

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

    def m7_write(self, reg: int, data: int) -> None:
        """Handle 2-write Mode 7 matrix registers (M7A-M7Y, 0x211B-0x2120)."""
        value: cython.int = (data << 8) | self._m7_latch
        self._m7_latch = data
        if reg == 0x211B:
            self.m7a = value
        elif reg == 0x211C:
            self.m7b = value
        elif reg == 0x211D:
            self.m7c = value
        elif reg == 0x211E:
            self.m7d = value
        elif reg == 0x211F:
            self.m7x = value & 0x1FFF  # 13-bit signed
            if self.m7x >= 0x1000:
                self.m7x -= 0x2000
        elif reg == 0x2120:
            self.m7y = value & 0x1FFF  # 13-bit signed
            if self.m7y >= 0x1000:
                self.m7y -= 0x2000

    def coldata_set(self, data: int) -> None:
        """COLDATA (0x2132) - Fixed color for color math."""
        intensity: cython.uchar = data & 0x1F
        if data & 0x20:
            self.coldata_r = intensity
        if data & 0x40:
            self.coldata_g = intensity
        if data & 0x80:
            self.coldata_b = intensity

    # ------------------------------------------------------------------
    # Scheduler integration
    # ------------------------------------------------------------------

    def attach(self, scheduler, bus) -> None:
        """Attach the scheduler and bus after construction."""
        self.scheduler = scheduler
        self.bus = bus

    def start(self) -> None:
        """Schedule the first H-Blank event. Call once before the main loop."""
        self.scheduler.add(_HBLANK_START_MC, self._hblank)

    def _hblank(self) -> None:
        """Fired at dot 274 of each scanline (H-Blank start)."""
        self.h_counter = 274
        self.bus.hblank = True

        # Render the current scanline first, then fire HDMA.
        # On real hardware, H-blank occurs after active display ends, so HDMA
        # updates registers for the NEXT scanline, not the current one.
        if 0 < self.v_counter < _VBLANK_START_LINE:
            self.render_scanline()

        # HDMA fires at H-blank for each active scanline (including scanline 0)
        if 0 <= self.v_counter < _VBLANK_START_LINE:
            self.bus.cpu.dma.hdma_scanline()

        # Schedule end of scanline / start of next
        self.scheduler.add(_MC_PER_SCANLINE - _HBLANK_START_MC, self._scanline_end)

    def _scanline_end(self) -> None:
        """Fired at the end of each scanline."""
        self.bus.hblank = False
        self.h_counter = 0
        self.v_counter += 1

        if self.v_counter == _VBLANK_START_LINE:
            self._vblank_start()
        elif self.v_counter == _TOTAL_SCANLINES:
            self._vblank_end()

        # Schedule H-Blank for the next scanline
        self.scheduler.add(_HBLANK_START_MC, self._hblank)

    def _vblank_start(self) -> None:
        self.bus.vblank = True
        self.bus.raise_nmi()

    def _vblank_end(self) -> None:
        self.bus.vblank = False
        self.bus.lower_nmi()
        # Reset counters for next frame
        self.v_counter = 0
        self.field ^= 1
        self.frames += 1
        # Initialize HDMA table pointers for the new frame
        self.bus.cpu.dma.hdma_init()

    def render_scanline(self):
        """
        Render current scanline in self.v_counter
        https://bin.smwcentral.net/u/4842/regs.txt
        """
        # Check F-Blank
        if self.display_disable:
            return

        # Draw picture
        if self._bgmode == 0:
            """
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
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg4, 2, False)
            self.draw_background_scanline(self.bg3, 2, False)
            self.draw_background_scanline(self.bg4, 2, True)
            self.draw_background_scanline(self.bg3, 2, True)
            self.draw_background_scanline(self.bg2, 2, False)
            self.draw_background_scanline(self.bg1, 2, False)
            self.draw_background_scanline(self.bg2, 2, True)
            self.draw_background_scanline(self.bg1, 2, True)
            self.draw_objects()
        elif self._bgmode == 1:
            """
            In Mode 1, you have 2 BGs of 16 colors and 1 BG of 4 colors. To calculate the
            starting palette entry, calculate:
            ppp*ncolors

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
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg3, 2, False)
            if self._bgpriority == 0:
                self.draw_background_scanline(self.bg3, 2, True)
            self.draw_background_scanline(self.bg2, 4, False)
            self.draw_background_scanline(self.bg1, 4, False)
            self.draw_background_scanline(self.bg2, 4, True)
            self.draw_background_scanline(self.bg1, 4, True)
            self.draw_objects()
            if self._bgpriority == 1:
                self.draw_background_scanline(self.bg3, 2, True)
        elif self._bgmode == 3:
            """
            In Mode 3, you have one 256-color BG and one 16-color BG. To calculate the
            starting palette index, calculate:
            BG1: 0
            BG2: ppp*16

            The priority is (from 'front' to 'back'):
            Sprites with priority 3
            BG1 tiles with priority 1
            Sprites with priority 2
            BG2 tiles with priority 1
            Sprites with priority 1
            BG1 tiles with priority 0
            Sprites with priority 0
            BG2 tiles with priority 0

            Note that register $2130 may enable Direct Color Mode on BG1.
            """
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg2, 4, False)
            self.draw_background_scanline(self.bg1, 8, False)
            self.draw_background_scanline(self.bg2, 4, True)
            self.draw_background_scanline(self.bg1, 8, True)
        else:
            raise NotImplementedError(f"BG Mode {self._bgmode} not implemented")

    def draw_scanline_backdrop(self) -> None:
        """Draw the backdrop color for the current scanline"""
        u32_color = self.get_u32_backdrop_color()
        y = self.v_counter - 1
        for x in range(SCREEN_WIDTH):
            self.main_bgs[y * SCREEN_WIDTH + x] = u32_color

    # @cython.nogil
    @cython.cfunc
    # @cython.noexcept
    def draw_background_scanline(self, bg: Background, bpp: cython.uchar, priority_selector: cython.bint):
        scanline = self.v_counter  # TODO move to method argument

        # assert bg.sub_screen_enable is False, "Sub screen not implemented"

        if not bg.main_screen_enable:
            return

        # Window masking setup for this BG.
        # $212E TMW bit (bg.number-1): window masking enabled for this BG on main screen.
        # $2123 W12SEL (for BG1/BG2) / $2124 W34SEL (for BG3/BG4):
        #   bit pairs per BG: (enable, invert) for Window 1 and Window 2.
        # For BG1: W12SEL bits 1:0 = (W1_enable, W1_invert).
        # invert=0: pixels INSIDE [WH0,WH1] are in the mask zone (not drawn).
        # invert=1: pixels OUTSIDE [WH0,WH1] are in the mask zone (not drawn).
        bg_idx: cython.uint = bg.number - 1
        window_active: cython.bint = bool(self.tmw & (1 << bg_idx))
        w1_enable: cython.bint = False
        w1_invert: cython.bint = False
        if window_active:
            if bg_idx == 0:
                w1_enable = bool(self.w12sel >> 1 & 1)
                w1_invert = bool(self.w12sel & 1)
            elif bg_idx == 1:
                w1_enable = bool(self.w12sel >> 5 & 1)
                w1_invert = bool(self.w12sel >> 4 & 1)
            elif bg_idx == 2:
                w1_enable = bool(self.w34sel >> 1 & 1)
                w1_invert = bool(self.w34sel & 1)
            elif bg_idx == 3:
                w1_enable = bool(self.w34sel >> 5 & 1)
                w1_invert = bool(self.w34sel >> 4 & 1)

        # Find the tilemap entry for the requested screen position

        # Assuming 256 dots per scanline
        for dot in range(256):
            # Calculate the tilemap entry address in VRAM
            # scrx, scry = dot, scanline
            scrx: cython.uint = dot
            scry: cython.uint = scanline

            # To find the tilemap word address for a particular tile (X and Y), you'd use a
            # formula something like this:
            # (Addr<<9) + ((Y&0x1f)<<5) + (X&0x1f) +
            #     (SY ? ((Y&0x20)<<(SX ? 6 : 5)) : 0) + (SX ? ((X&0x20)<<5) : 0)

            screen_size: cython.uint = bg.screen_size
            bg_size_w: cython.uint = 32 << (screen_size & 1)
            bg_size_h: cython.uint = 32 << (screen_size >> 1)
            scroll_x: cython.uint = bg.hoffset
            scroll_y: cython.uint = bg.voffset

            orgx: cython.uint = dot   # screen X of this pixel (= dot before scroll)
            orgy: cython.uint = scanline - 1   # screen Y (output row)

            # Apply window masking: skip this pixel if it falls in the masked zone.
            if window_active and w1_enable:
                inside: cython.bint = (self.wh0 <= orgx <= self.wh1)
                masked: cython.bint = inside ^ w1_invert  # invert=1 → outside is masked
                if masked:
                    continue

            scry: cython.uint = (scry + scroll_y) % (8 * bg_size_h)
            scrx: cython.uint = (scrx + scroll_x) % (8 * bg_size_w)

            offset: cython.uint = ((scry % 256 if bg_size_w == 64 else scry) // 8) * 32
            offset += ((scrx % 256) // 8)
            offset += (scrx // 256) * 0x400
            offset += (bg_size_w // 64) * ((scry // 256) * 0x800)

            screen_addr = bg.screen_addr & 0xFFFF
            tilemap_addr = (screen_addr + offset) * 2 & 0xFFFF

            # tilemap = Tilemap.from_buffer(self.vram, tilemap_addr)
            low: cython.uint = self.vram[tilemap_addr]
            high: cython.uint = self.vram[tilemap_addr + 1]
            tilemap_addr: cython.uint = (high & 3) << 8 | low
            tilemap_palette: cython.uint = (high >> 2) & 7
            tilemap_priority: cython.bint = (high >> 5) & 1
            tilemap_h_flip: cython.bint = (high >> 6) & 1
            tilemap_v_flip: cython.bint = (high >> 7) & 1

            if tilemap_priority == priority_selector:
                i: cython.uint = scry % 8
                j: cython.uint = scrx % 8
                v_shift: cython.uint = i + (-i + 7 - i) * tilemap_v_flip
                h_shift: cython.uint = (7 - j) + (2 * j - 7) * tilemap_h_flip
                if bpp == 2:
                    tile_address: cython.uint = bg.tiledata_addr + tilemap_addr * 16 + v_shift * 2
                    b_lo: cython.uint = self.vram[tile_address]
                    b_hi: cython.uint = self.vram[tile_address + 1]
                    v: cython.uint = ((b_lo >> h_shift) & 1) + (2 * ((b_hi >> h_shift) & 1))
                elif bpp == 4:
                    tile_address: cython.uint = bg.tiledata_addr + tilemap_addr * 32 + v_shift * 2
                    b_1: cython.uint = self.vram[tile_address]
                    b_2: cython.uint = self.vram[tile_address + 1]
                    b_3: cython.uint = self.vram[tile_address + 16]
                    b_4: cython.uint = self.vram[tile_address + 17]
                    v: cython.uint = ((b_1 >> h_shift) & 1) + (2 * ((b_2 >> h_shift) & 1)) + \
                        (4 * ((b_3 >> h_shift) & 1)) + (8 * ((b_4 >> h_shift) & 1))
                elif bpp == 8:
                    tile_address: cython.uint = bg.tiledata_addr + tilemap_addr * 64 + v_shift * 2
                    b_1: cython.uint = self.vram[tile_address]
                    b_2: cython.uint = self.vram[tile_address + 1]
                    b_3: cython.uint = self.vram[tile_address + 16]
                    b_4: cython.uint = self.vram[tile_address + 17]
                    b_5: cython.uint = self.vram[tile_address + 32]
                    b_6: cython.uint = self.vram[tile_address + 33]
                    b_7: cython.uint = self.vram[tile_address + 48]
                    b_8: cython.uint = self.vram[tile_address + 49]
                    v: cython.uint = ((b_1 >> h_shift) & 1) + \
                        (2 * ((b_2 >> h_shift) & 1)) + \
                        (4 * ((b_3 >> h_shift) & 1)) + \
                        (8 * ((b_4 >> h_shift) & 1)) + \
                        (16 * ((b_5 >> h_shift) & 1)) + \
                        (32 * ((b_6 >> h_shift) & 1)) + \
                        (64 * ((b_7 >> h_shift) & 1)) + \
                        (128 * ((b_8 >> h_shift) & 1))
                else:
                    raise NotImplementedError(f"Invalid bpp {bpp}")

                if v:
                    # Special case for BG2-BG4 in Mode 0
                    color_offset = bg.color_offset_mode_0 if self._bgmode == 0 else 0
                    # r, g, b = self.get_rbg_colors(bpp, tilemap_palette, v, color_offset)

                    # x_ndc = 2.0 * (scrx / SCREEN_WIDTH) - 1.0
                    # y_ndc = 1.0 - 2.0 * (scry / SCREEN_HEIGHT)

                    u32_color = self.get_u32_color(bpp, tilemap_palette, v, color_offset)
                    # x, y, width = orgx, orgy, SCREEN_WIDTH
                    self.main_bgs[orgy * SCREEN_WIDTH + orgx] = u32_color

                    if self.mosaic_enabled[bg.number - 1] and False:  # TODO implement mosaic
                        # for x in range(0, 256, size):
                        #     for y in range(0, 256, size):
                        #         pos = y * 256 + x
                        #         col = BG[pos]
                        #         for a in range(size):
                        #             for b in range(size):
                        #                 if x + a < 256 and y + b < 256:
                        #                     BG[min(y + b, 255) * 256 + min(x + a, 255)] = col
                        mosaic_size_pixels = self.mosaic_size
                        # pick color from the first pixel in the top left corner of the mosaic square size
                        if scrx % mosaic_size_pixels == 0 and scry % mosaic_size_pixels == 0:
                            # get the color of the first pixel in the mosaic square
                            bg.mosaic_start_x = scrx
                            bg.mosaic_start_y = scry
                            color_map = getattr(bg, "mosaic_color_map", {})
                            color_map[scrx] = u32_color
                            setattr(bg, "mosaic_color_map", color_map)
                            #print(f"{bg.number=} Setting mosaic color {u32_color} at ({scrx}, {scry}), {mosaic_size_pixels=}")
                        # replace the color of the current pixel with the color of the first pixel in the mosaic square
                        elif (scrx < (bg.mosaic_start_x + mosaic_size_pixels) and
                              scry < (bg.mosaic_start_y + mosaic_size_pixels)):
                            self.main_bgs[scry * SCREEN_WIDTH + scrx] = bg.mosaic_color_map[bg.mosaic_start_x]

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

        # color == 0 is transparent — do not overwrite existing pixel
        if color and 0 <= x < SCREEN_WIDTH:
            u32_color = self.get_u32_color(bpp, palette, color)
            self.main_bgs[(y - 1) * SCREEN_WIDTH + x] = u32_color

    def get_rbg_colors(self, bpp: int, palette: int, color: int, color_offset: int = 0) -> tuple:
        # 4 colors (2bpp palette) x 2 bytes each color
        palette_index = palette * (bpp ** 2)
        color_index = palette_index + color
        color_index += color_offset  # CGRAM offset for BG2, BG3, BG4 in mode 0
        color_index *= 2  # 2 bytes per color
        data = self.cgram[color_index] | self.cgram[color_index + 1] << 8

        r_5bit = data >> 0 & 0x1F
        g_5bit = data >> 5 & 0x1F
        b_5bit = data >> 10 & 0x1F

        r_8bit = (r_5bit << 3) | (r_5bit >> 2)
        g_8bit = (g_5bit << 3) | (g_5bit >> 2)
        b_8bit = (b_5bit << 3) | (b_5bit >> 2)

    # ...existing code...
        r = r_8bit / 255
        g = g_8bit / 255
        b = b_8bit / 255

        return r, g, b

    def get_u32_color(self, bpp: int, palette: int, color: int, color_offset: int = 0) -> int:
        palette_index = palette * (bpp ** 2)
        color_index = palette_index + color
        color_index += color_offset  # CGRAM offset for BG2, BG3, BG4 in mode 0
        color_index *= 2  # 2 bytes per color
        data = self.cgram[color_index] | self.cgram[color_index + 1] << 8

        r_5bit = data >> 0 & 0x1F
        g_5bit = data >> 5 & 0x1F
        b_5bit = data >> 10 & 0x1F

        r_8bit = (r_5bit << 3) | (r_5bit >> 2)
        g_8bit = (g_5bit << 3) | (g_5bit >> 2)
        b_8bit = (b_5bit << 3) | (b_5bit >> 2)
        a_8bit = 255 if color else 0  # 255 no transparency, 0 full transparency

        return (r_8bit << 24) | (g_8bit << 16) | (b_8bit << 8) | a_8bit

    def get_rbg_backdrop_color(self) -> tuple:
        """Return backdrop color for the main screen. It is always the first color in CGRAM"""
        data = self.cgram[0] | self.cgram[1] << 8
        r_5bit = data >> 0 & 0x1F
        g_5bit = data >> 5 & 0x1F
        b_5bit = data >> 10 & 0x1F

        r_8bit = (r_5bit << 3) | (r_5bit >> 2)
        g_8bit = (g_5bit << 3) | (g_5bit >> 2)
        b_8bit = (b_5bit << 3) | (b_5bit >> 2)

    # ...existing code...
        r = r_8bit / 255
        g = g_8bit / 255
        b = b_8bit / 255

        return r, g, b

    def get_u32_backdrop_color(self) -> int:
        data = self.cgram[0] | self.cgram[1] << 8
        r_5bit = data >> 0 & 0x1F
        g_5bit = data >> 5 & 0x1F
        b_5bit = data >> 10 & 0x1F

        r_8bit = (r_5bit << 3) | (r_5bit >> 2)
        g_8bit = (g_5bit << 3) | (g_5bit >> 2)
        b_8bit = (b_5bit << 3) | (b_5bit >> 2)
        a_8bit = 255  # 255 no transparency, 0 full transparency

        return (r_8bit << 24) | (g_8bit << 16) | (b_8bit << 8) | a_8bit

    def draw_objects(self) -> None:
        # objects are the building blocks for sprites
        # they can move independently from the background and always use 4bpp
        # they can be 8x8, 16x16, 32x32 or 64x64 pixels in size
        # oam is the memory region where the objects properties are stored. each obj uses 34 bits

        if not self.oam_main_screen_enable:
            return

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
    ppu = Ppu(vram_dump=vram_dump, cgram_dump=cgram_dump, oam_dump=oam_dump)

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
    # import cProfile

    # cProfile.run("main()", sort="cumulative")
    main()
