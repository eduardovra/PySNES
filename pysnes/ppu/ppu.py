from array import array
from ctypes import c_uint8
from typing import Optional, TYPE_CHECKING


from . import bg_renderer, color_math, obj_renderer
from .constants import (
    _MC_PER_SCANLINE, _HBLANK_START_MC, _VBLANK_START_LINE, _TOTAL_SCANLINES,
    SCREEN_WIDTH, SCREEN_HEIGHT,
)
from .data_structures import Background
from .oam import OAM

if TYPE_CHECKING:
    from ..scheduler import Scheduler
    from ..bus import Bus


class Ppu:
    """Picture Processor Unit: 15-Bit"""

    _OBJ_DIM_TABLE = (
        ((8, 8), (16, 16)),
        ((8, 8), (32, 32)),
        ((8, 8), (64, 64)),
        ((16, 16), (32, 32)),
        ((16, 16), (64, 64)),
        ((32, 32), (64, 64)),
        ((16, 32), (32, 64)),
        ((16, 32), (32, 32)),
    )

    def __init__(
        self,
        *,
        vram_dump: Optional[bytes] = None,
        cgram_dump: Optional[bytes] = None,
        oam_dump: Optional[bytes] = None,
    ) -> None:
        # Scheduler and bus are attached after construction via attach()
        self.scheduler: Optional[Scheduler] = None
        self.bus: Optional[Bus] = None

        # VRAM - Video RAM
        if vram_dump is None:
            self.vram = bytearray(64 * 1024)
        else:
            self.vram = bytearray(vram_dump)
        self.vmain = 0x00
        self.vmaddl = 0
        self.vmaddh = 0
        self._vmdatal = 0
        self._vmdatah = 0
        # VRAM read port has a 16-bit prefetch buffer; $2116/$2117 writes
        # refill it (no increment), $2139/$213A reads return the buffered byte
        # and refill + increment depending on VMAIN bit 7.
        self._vram_prefetch = 0

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
        self._bgpriority = 0
        self.bg1 = Background(number=1, color_offset_mode_0=0x00)
        self.bg2 = Background(number=2, color_offset_mode_0=0x20)
        self.bg3 = Background(number=3, color_offset_mode_0=0x40)
        self.bg4 = Background(number=4, color_offset_mode_0=0x60)

        self.latch_bgofs_ppu1 = 0
        self.latch_bgofs_ppu2 = 0

        # Mode 7 matrix registers (0x211B-0x2120), 2-write latched
        self._m7_latch = 0
        self.m7a = 0
        self.m7b = 0
        self.m7c = 0
        self.m7d = 0
        self.m7x = 0
        self.m7y = 0
        self.m7sel = 0
        self.m7_extbg = False   # SETINI ($2133) bit 6
        # Hardware multiplier: product of signed16(m7a) × signed8(m7b_lo).
        # Updated on every write to $211C (M7B). Read via $2134-$2136.
        self._mpy_result = 0

        # Window registers (0x2123-0x212B)
        self.w12sel = 0
        self.w34sel = 0
        self.wobjsel = 0
        self.wh0 = 0   # Window 1 left
        self.wh1 = 0   # Window 1 right
        self.wh2 = 0   # Window 2 left
        self.wh3 = 0   # Window 2 right
        self.wbglog = 0
        self.wobjlog = 0

        # Window screen disable (0x212E-0x212F)
        self.tmw = 0
        self.tsw = 0

        # Color math registers (0x2130-0x2132)
        self.cgwsel = 0
        self.cgadsub = 0
        self.coldata_r = 0
        self.coldata_g = 0
        self.coldata_b = 0

        # Mosaic
        self.mosaic_enabled = [False, False, False, False]
        self.mosaic_size = 0

        self.field = 0  # 0 for even frames, 1 for odd frames
        self.h_counter = 0  # current dot being drawn (updated at H-Blank / scanline start)
        self.v_counter = 0  # current scanline being drawn
        self.frames = 0  # total frames rendered

        self.main_bgs = array('I', [0] * 256 * 262)  # 262 was 239 before
        self.sub_bgs = array('I', [0] * 256 * 262)
        # Per-pixel main-screen layer tag: 0=backdrop, 1-4=BG1-BG4, 5=OBJ.
        # Used by the color-math composite pass to know which pixels participate.
        self.main_layer = bytearray(256 * 262)

        # CGRAM u32-color cache: 256 entries (one per CGRAM slot), pre-converted
        # from 15-bit SNES RGB to 32-bit RGBA. Rebuilt lazily when _cgram_dirty.
        # array.array('I') gives PyPy direct unboxed 32-bit integer access.
        self._cgram_cache = array('I', [0] * 256)
        self._cgram_dirty: bool = True

        # Reusable 256-byte window mask buffer — avoids per-scanline allocation.
        self._window_mask_buf = bytearray(256)

        # 4bpp sprite tile decode cache. One entry per 32-byte VRAM slot (2048 total).
        # Each entry stores 64 pre-decoded color indices: 8 rows × 8 pixels (0-15).
        # Invalidated on VRAM writes; rebuilt lazily in draw_tiles().
        _N_OBJ_TILE_SLOTS = 2048  # 65536 VRAM bytes / 32 bytes per 4bpp tile
        self._obj_tile_cache = bytearray(_N_OBJ_TILE_SLOTS * 64)
        self._obj_tile_dirty = bytearray([1] * _N_OBJ_TILE_SLOTS)

    _SCALAR_STATE = (
        "vmain", "vmaddl", "vmaddh", "_vmdatal", "_vmdatah", "_vram_prefetch",
        "display_brightness", "display_disable",
        "_oamadd", "_oamodd", "_oamdata",
        "oam_main_screen_enable", "oam_sub_screen_enable",
        "oam_tiledata_address", "oam_nameselect", "oam_base_size",
        "_bgmode", "_bgpriority",
        "latch_bgofs_ppu1", "latch_bgofs_ppu2",
        "_m7_latch", "m7a", "m7b", "m7c", "m7d", "m7x", "m7y", "m7sel", "m7_extbg", "_mpy_result",
        "w12sel", "w34sel", "wobjsel", "wh0", "wh1", "wh2", "wh3",
        "wbglog", "wobjlog", "tmw", "tsw",
        "cgwsel", "cgadsub", "coldata_r", "coldata_g", "coldata_b",
        "mosaic_size",
        "field", "h_counter", "v_counter", "frames",
    )

    def dump_state(self) -> dict:
        return {
            "vram": bytes(self.vram),
            "cgram": bytes(self.cgram),
            "oam": self.oam.dump_state(),
            "scalars": {f: getattr(self, f) for f in self._SCALAR_STATE},
            "_cgadd": self._cgadd.value,
            "_cgdata": self._cgdata.value if self._cgdata is not None else None,
            "bg1": self.bg1.dump_state(),
            "bg2": self.bg2.dump_state(),
            "bg3": self.bg3.dump_state(),
            "bg4": self.bg4.dump_state(),
            "mosaic_enabled": list(self.mosaic_enabled),
        }

    def load_state(self, d: dict) -> None:
        self.vram[:] = d["vram"]
        self.cgram[:] = d["cgram"]
        self._cgram_dirty = True
        for i in range(len(self._obj_tile_dirty)):
            self._obj_tile_dirty[i] = 1
        self.oam.load_state(d["oam"])
        for f, v in d["scalars"].items():
            setattr(self, f, v)
        self._cgadd = c_uint8(d["_cgadd"])
        self._cgdata = c_uint8(d["_cgdata"]) if d["_cgdata"] is not None else None
        self.bg1.load_state(d["bg1"])
        self.bg2.load_state(d["bg2"])
        self.bg3.load_state(d["bg3"])
        self.bg4.load_state(d["bg4"])
        self.mosaic_enabled = list(d["mosaic_enabled"])

    def inidisp_set(self, data: int) -> None:
        # Missing: when clearing forced-blank (bit 7 → 0) during V-Blank, the
        # internal OAM address must be reloaded from OAMADDL/OAMADDH. The reload
        # also fires at V-Blank entry when forced-blank is off. Not yet wired —
        # belongs in the V-Blank transition in _vblank_start, not here.
        new_disable = (data >> 7) & 1
        if new_disable and not self.display_disable and 0 < self.v_counter < _VBLANK_START_LINE:
            # Forced blank just asserted during active display. Rows 0..v_counter-1
            # have already been rendered with display enabled; retroactively clear
            # them so stale pixels don't appear at the top of the frame.
            black = 0x000000FF
            limit = self.v_counter * SCREEN_WIDTH
            for i in range(limit):
                self.main_bgs[i] = black
                self.sub_bgs[i] = black
                self.main_layer[i] = 0
        self.display_brightness = data & 0xF
        self.display_disable = new_disable

    @property
    def bgmode(self) -> int:
        return self._bgmode

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
        """
        mm     = Address remapping
                    00 = No remapping
                    01 = Remap addressing aaaaaaaaBBBccccc => aaaaaaaacccccBBB
                    10 = Remap addressing aaaaaaaBBBcccccc => aaaaaaaccccccBBB
                    11 = Remap addressing aaaaaaBBBccccccc => aaaaaacccccccBBB
        """

    @property
    def vmdatal(self) -> int:
        return self._vmdatal

    @vmdatal.setter
    def vmdatal(self, data: int) -> None:
        self._vmdatal = data
        # $2118 writes ONLY the low byte at vram[addr*2+0]. The high byte
        # is preserved (this is the whole point of having separate L/H
        # registers — games like SMW do mode-0 DMA into $2118 alone to
        # update tilemap chars while keeping their attribute bytes).
        word_addr = (self.vmaddl | self.vmaddh << 8) & 0x7FFF
        base_addr = self._remap_vram_addr(word_addr) * 2
        self.vram[base_addr] = data
        self._obj_tile_dirty[base_addr >> 5] = 1
        if not self.vmain_addr_increment_mode:
            self.increment_vmadd()

    @property
    def vmdatah(self) -> int:
        return self._vmdatah

    @vmdatah.setter
    def vmdatah(self, data: int) -> None:
        self._vmdatah = data
        word_addr = (self.vmaddl | self.vmaddh << 8) & 0x7FFF
        base_addr = self._remap_vram_addr(word_addr) * 2
        self.vram[base_addr + 1] = data
        self._obj_tile_dirty[base_addr >> 5] = 1
        if self.vmain_addr_increment_mode:
            self.increment_vmadd()

    def _remap_vram_addr(self, addr: int) -> int:
        """Apply $2115 VRAM address remapping to a 16-bit word address."""
        m = self.vmain_addr_remapping
        if m == 0:
            return addr
        elif m == 1:   # aaaaaaaaBBBccccc → aaaaaaaacccccBBB
            return (addr & 0xFF00) | ((addr & 0x001F) << 3) | ((addr & 0x00E0) >> 5)
        elif m == 2:   # aaaaaaaBBBcccccc → aaaaaaaccccccBBB
            return (addr & 0xFE00) | ((addr & 0x003F) << 3) | ((addr & 0x01C0) >> 6)
        else:          # aaaaaaBBBccccccc → aaaaaacccccccBBB
            return (addr & 0xFC00) | ((addr & 0x007F) << 3) | ((addr & 0x0380) >> 7)

    def write_vram(self) -> None:
        word_addr = (self.vmaddl | self.vmaddh << 8) & 0x7FFF
        base_addr = self._remap_vram_addr(word_addr) * 2
        assert base_addr < len(self.vram), f"VRAM write out of bounds: 0x{base_addr:06X}"
        self.vram[base_addr + 0] = self._vmdatal
        self.vram[base_addr + 1] = self._vmdatah
        self._obj_tile_dirty[base_addr >> 5] = 1
        self.increment_vmadd()

    def increment_vmadd(self) -> None:
        addr = (
            self.vmaddl | self.vmaddh << 8
        ) + self.vmain_addr_increment_amount
        self.vmaddl = (addr >> 0) & 0xFF
        self.vmaddh = (addr >> 8) & 0xFF

    def refill_vram_prefetch(self) -> None:
        word_addr = (self.vmaddl | self.vmaddh << 8) & 0x7FFF
        base_addr = self._remap_vram_addr(word_addr) * 2
        self._vram_prefetch = self.vram[base_addr] | (self.vram[base_addr + 1] << 8)

    def rdvraml(self) -> int:
        data = self._vram_prefetch & 0xFF
        if not self.vmain_addr_increment_mode:
            self.refill_vram_prefetch()
            self.increment_vmadd()
        return data

    def rdvramh(self) -> int:
        data = (self._vram_prefetch >> 8) & 0xFF
        if self.vmain_addr_increment_mode:
            self.refill_vram_prefetch()
            self.increment_vmadd()
        return data

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
        self._cgram_dirty = True

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
        return self._oamadd & 0xFF

    @oamaddl.setter
    def oamaddl(self, data: int) -> None:
        self._oamadd = (self._oamadd & 0x100) | (data & 0xFF)
        self._oamodd = 0

    @property
    def oamaddh(self) -> int:
        return (self._oam_priority_activation << 7) | ((self._oamadd >> 8) & 1)

    @oamaddh.setter
    def oamaddh(self, data: int) -> None:
        self._oam_priority_activation = (data >> 7) & 1
        self._oamadd = (self._oamadd & 0x0FF) | (data & 1) << 8
        self._oamodd = 0

    @property
    def oamdata(self) -> int:
        index = self.oam_index()
        data = self.oam.read(index)
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
            self.oam.write(index, data & 0xFF)

        # Low bank does word only on odd writes
        elif self._oamodd == 1:
            index = self.oam_index()
            self.oam.write(index - 1, self._oamdata)
            self.oam.write(index - 0, data & 0xFF)

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
        self.bg1.main_screen_enable = data >> 0 & 1
        self.bg2.main_screen_enable = data >> 1 & 1
        self.bg3.main_screen_enable = data >> 2 & 1
        self.bg4.main_screen_enable = data >> 3 & 1
        self.oam_main_screen_enable = data >> 4 & 1

    def ts_set(self, data: int) -> None:
        self.bg1.sub_screen_enable = data >> 0 & 1
        self.bg2.sub_screen_enable = data >> 1 & 1
        self.bg3.sub_screen_enable = data >> 2 & 1
        self.bg4.sub_screen_enable = data >> 3 & 1
        self.oam_sub_screen_enable = data >> 4 & 1

    def m7_write(self, reg: int, data: int) -> None:
        """Handle 2-write Mode 7 matrix registers (M7A-M7Y, 0x211B-0x2120)."""
        value = (data << 8) | self._m7_latch
        self._m7_latch = data
        if reg == 0x211B:
            self.m7a = value
        elif reg == 0x211C:
            self.m7b = value
            m7a_s = self.m7a if self.m7a < 0x8000 else self.m7a - 0x10000
            data_s = data if data < 128 else data - 256
            self._mpy_result = m7a_s * data_s
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
        intensity = data & 0x1F
        if data & 0x20:
            self.coldata_r = intensity
        if data & 0x40:
            self.coldata_g = intensity
        if data & 0x80:
            self.coldata_b = intensity

    # ------------------------------------------------------------------
    # Scheduler integration
    # ------------------------------------------------------------------

    def reset_registers(self) -> None:
        """Reset all PPU I/O registers to power-on state. Preserves VRAM/CGRAM/OAM."""
        self.vmain = 0x00
        self.vmaddl = 0
        self.vmaddh = 0
        self._vmdatal = 0
        self._vmdatah = 0
        self._vram_prefetch = 0

        self.inidisp_set(0)

        self._cgadd = c_uint8(0x00)
        self._cgdata = None

        self._oamadd = 0
        self._oamodd = 0
        self._oamdata = 0
        self.obsel_set(0)
        self.oam_main_screen_enable = True
        self.oam_sub_screen_enable = True

        self._bgmode = 0x00
        self._bgpriority = 0
        self.bg1 = Background(number=1, color_offset_mode_0=0x00)
        self.bg2 = Background(number=2, color_offset_mode_0=0x20)
        self.bg3 = Background(number=3, color_offset_mode_0=0x40)
        self.bg4 = Background(number=4, color_offset_mode_0=0x60)

        self.latch_bgofs_ppu1 = 0
        self.latch_bgofs_ppu2 = 0

        self._m7_latch = 0
        self.m7a = 0
        self.m7b = 0
        self.m7c = 0
        self.m7d = 0
        self.m7x = 0
        self.m7y = 0
        self.m7sel = 0
        self.m7_extbg = False

        self.w12sel = 0
        self.w34sel = 0
        self.wobjsel = 0
        self.wh0 = 0
        self.wh1 = 0
        self.wh2 = 0
        self.wh3 = 0
        self.wbglog = 0
        self.wobjlog = 0

        self.tmw = 0
        self.tsw = 0

        self.cgwsel = 0
        self.cgadsub = 0
        self.coldata_r = 0
        self.coldata_g = 0
        self.coldata_b = 0

        self.mosaic_enabled = [False, False, False, False]
        self.mosaic_size = 0

    def attach(self, scheduler: "Scheduler", bus: "Bus") -> None:
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

        # H/V-IRQ timer match check (once per scanline at H-blank entry).
        # Real hardware fires at dot HTIME within the scanline; we approximate
        # at H-blank start since the CPU runs in scanline-granularity bursts.
        self._irq_check()

        # Schedule end of scanline / start of next
        self.scheduler.add(_MC_PER_SCANLINE - _HBLANK_START_MC, self._scanline_end)

    def _irq_check(self) -> None:
        """Raise CPU IRQ line if the H/V timer match condition is satisfied.

        $4200 bits 5:4 select the mode:
          00 — IRQ disabled
          01 — H-only:  fire every scanline at dot HTIME
          10 — V-only:  fire at scanline VTIME, dot 0
          11 — H+V:     fire at scanline VTIME, dot HTIME

        The raised IRQ line stays high until $4211 is read (or IRQ is disabled
        via $4200). Retrigger is natural: the next matching scanline will
        re-raise the line if the CPU has already cleared it.
        """
        st = self.bus.cpu.status
        h_en = st.hirq_enable
        v_en = st.virq_enable
        if not (h_en or v_en):
            return
        if v_en and self.v_counter != st.vtime:
            return
        # When V-IRQ is set without H-IRQ, the target scanline is enough.
        # When H-IRQ is set (with or without V-IRQ), we also require scanline
        # match (if V too) and fire on every qualifying scanline.
        st.irq_line = True

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
        # Forced blank outputs black, not the previous framebuffer contents.
        if self.display_disable:
            color_math.draw_scanline_forced_blank(self)
            return

        if self._cgram_dirty:
            self._rebuild_cgram_cache()
        self._render_layers()
        color_math.composite_scanline(self)
        if self.display_brightness < 15:
            color_math.apply_brightness_scanline(self)

    def _render_layers(self):
        # Draw picture
        if self._bgmode == 0:
            # Mode 0: 4 BGs × 4 colors; palette = ppp*4 + (BG#-1)*32.
            # Back → front painter order.
            # Each layer writes only where pixels are non-transparent, so the
            # last write at a pixel wins (= "in front").
            bg_renderer.draw_scanline_backdrop(self)
            bg_renderer.draw_background_scanline(self, self.bg4, 2, False)     # BG4 pri 0
            obj_renderer.draw_objects(self, priority=0)                        # OBJ pri 0
            bg_renderer.draw_background_scanline(self, self.bg3, 2, False)     # BG3 pri 0
            obj_renderer.draw_objects(self, priority=1)                        # OBJ pri 1
            bg_renderer.draw_background_scanline(self, self.bg4, 2, True)      # BG4 pri 1
            bg_renderer.draw_background_scanline(self, self.bg3, 2, True)      # BG3 pri 1
            obj_renderer.draw_objects(self, priority=2)                        # OBJ pri 2
            bg_renderer.draw_background_scanline(self, self.bg2, 2, False)     # BG2 pri 0
            bg_renderer.draw_background_scanline(self, self.bg1, 2, False)     # BG1 pri 0
            obj_renderer.draw_objects(self, priority=3)                        # OBJ pri 3
            bg_renderer.draw_background_scanline(self, self.bg2, 2, True)      # BG2 pri 1
            bg_renderer.draw_background_scanline(self, self.bg1, 2, True)      # BG1 pri 1
        elif self._bgmode == 1:
            # Mode 1: BG1+BG2 (4bpp), BG3 (2bpp); $2105 bit 3 moves BG3 pri-1
            # BG3 pri-1 either to the very top or behind OBJ pri-0/1.
            bg_renderer.draw_scanline_backdrop(self)
            bg_renderer.draw_background_scanline(self, self.bg3, 2, False)     # BG3 pri 0
            obj_renderer.draw_objects(self, priority=0)                        # OBJ pri 0
            if self._bgpriority == 0:
                bg_renderer.draw_background_scanline(self, self.bg3, 2, True)  # BG3 pri 1 (low)
            obj_renderer.draw_objects(self, priority=1)                        # OBJ pri 1
            bg_renderer.draw_background_scanline(self, self.bg2, 4, False)     # BG2 pri 0
            bg_renderer.draw_background_scanline(self, self.bg1, 4, False)     # BG1 pri 0
            obj_renderer.draw_objects(self, priority=2)                        # OBJ pri 2
            bg_renderer.draw_background_scanline(self, self.bg2, 4, True)      # BG2 pri 1
            bg_renderer.draw_background_scanline(self, self.bg1, 4, True)      # BG1 pri 1
            obj_renderer.draw_objects(self, priority=3)                        # OBJ pri 3
            if self._bgpriority == 1:
                bg_renderer.draw_background_scanline(self, self.bg3, 2, True)  # BG3 pri 1 (high)
        elif self._bgmode == 2:
            # Mode 2: BG1 (4bpp) + BG2 (4bpp) with offset-per-tile via BG3.
            # OPT is not implemented; we render without per-column offsets,
            # which gets the layout approximately right (enough to boot games
            # that probe their own title/menu screens).
            bg_renderer.draw_scanline_backdrop(self)
            bg_renderer.draw_background_scanline(self, self.bg2, 4, False)   # BG2 pri 0
            obj_renderer.draw_objects(self, priority=0)                      # OBJ pri 0
            bg_renderer.draw_background_scanline(self, self.bg1, 4, False)   # BG1 pri 0
            obj_renderer.draw_objects(self, priority=1)                      # OBJ pri 1
            bg_renderer.draw_background_scanline(self, self.bg2, 4, True)    # BG2 pri 1
            obj_renderer.draw_objects(self, priority=2)                      # OBJ pri 2
            bg_renderer.draw_background_scanline(self, self.bg1, 4, True)    # BG1 pri 1
            obj_renderer.draw_objects(self, priority=3)                      # OBJ pri 3
        elif self._bgmode == 3:
            # Mode 3: BG1 (8bpp/256-color), BG2 (4bpp); $2130 may enable Direct Color on BG1.
            bg_renderer.draw_scanline_backdrop(self)
            bg_renderer.draw_background_scanline(self, self.bg2, 4, False)   # BG2 pri 0
            obj_renderer.draw_objects(self, priority=0)                      # OBJ pri 0
            bg_renderer.draw_background_scanline(self, self.bg1, 8, False)   # BG1 pri 0
            obj_renderer.draw_objects(self, priority=1)                      # OBJ pri 1
            bg_renderer.draw_background_scanline(self, self.bg2, 4, True)    # BG2 pri 1
            obj_renderer.draw_objects(self, priority=2)                      # OBJ pri 2
            bg_renderer.draw_background_scanline(self, self.bg1, 8, True)    # BG1 pri 1
            obj_renderer.draw_objects(self, priority=3)                      # OBJ pri 3
        elif self._bgmode == 4:
            # Mode 4: BG1 (4bpp) + BG2 (2bpp) with OPT (offset-per-tile, not
            # implemented — same simplification as Mode 2).
            bg_renderer.draw_scanline_backdrop(self)
            bg_renderer.draw_background_scanline(self, self.bg2, 2, False)   # BG2 pri 0
            obj_renderer.draw_objects(self, priority=0)                      # OBJ pri 0
            bg_renderer.draw_background_scanline(self, self.bg1, 4, False)   # BG1 pri 0
            obj_renderer.draw_objects(self, priority=1)                      # OBJ pri 1
            bg_renderer.draw_background_scanline(self, self.bg2, 2, True)    # BG2 pri 1
            obj_renderer.draw_objects(self, priority=2)                      # OBJ pri 2
            bg_renderer.draw_background_scanline(self, self.bg1, 4, True)    # BG1 pri 1
            obj_renderer.draw_objects(self, priority=3)                      # OBJ pri 3
        elif self._bgmode == 5:
            # Mode 5: BG1 (4bpp) + BG2 (2bpp), hi-res.
            # Natively 512px/scanline (main screen = odd dots, sub = even dots).
            # We render the main screen downsampled to the 256px framebuffer;
            # each tilemap entry is a 16-dot cell of two adjacent tiles (T, T+1).
            # See bg_renderer.draw_hires_background_scanline.
            bg_renderer.draw_scanline_backdrop(self)
            bg_renderer.draw_hires_background_scanline(self, self.bg2, 2, False)  # BG2 pri 0
            obj_renderer.draw_objects(self, priority=0)                           # OBJ pri 0
            bg_renderer.draw_hires_background_scanline(self, self.bg1, 4, False)  # BG1 pri 0
            obj_renderer.draw_objects(self, priority=1)                           # OBJ pri 1
            bg_renderer.draw_hires_background_scanline(self, self.bg2, 2, True)   # BG2 pri 1
            obj_renderer.draw_objects(self, priority=2)                           # OBJ pri 2
            bg_renderer.draw_hires_background_scanline(self, self.bg1, 4, True)   # BG1 pri 1
            obj_renderer.draw_objects(self, priority=3)                           # OBJ pri 3
        elif self._bgmode == 6:
            # Mode 6: BG1 (4bpp) only, hi-res + OPT (OPT not implemented).
            # Same hi-res handling as Mode 5, main screen only.
            bg_renderer.draw_scanline_backdrop(self)
            obj_renderer.draw_objects(self, priority=0)                           # OBJ pri 0
            bg_renderer.draw_hires_background_scanline(self, self.bg1, 4, False)  # BG1 pri 0
            obj_renderer.draw_objects(self, priority=1)                           # OBJ pri 1
            obj_renderer.draw_objects(self, priority=2)                           # OBJ pri 2
            bg_renderer.draw_hires_background_scanline(self, self.bg1, 4, True)   # BG1 pri 1
            obj_renderer.draw_objects(self, priority=3)                           # OBJ pri 3
        else:
            # Mode 7: affine-transformed BG1 (8bpp). EXTBG BG2 written by same pass.
            # Priority (back→front): backdrop, OBJ0, OBJ1, BG1, BG2(EXTBG), OBJ2, OBJ3
            bg_renderer.draw_scanline_backdrop(self)
            obj_renderer.draw_objects(self, priority=0)
            obj_renderer.draw_objects(self, priority=1)
            bg_renderer.draw_mode7_scanline(self)
            obj_renderer.draw_objects(self, priority=2)
            obj_renderer.draw_objects(self, priority=3)

    def _build_window_mask(
        self,
        buf: bytearray,
        w1_enable: bool,
        w1_invert: bool,
        w2_enable: bool,
        w2_invert: bool,
        combine_logic: int,
    ) -> None:
        """Fill buf[0..255] with 1 where the pixel is inside the combined window, 0 elsewhere."""
        wh0 = self.wh0
        wh1 = self.wh1
        wh2 = self.wh2
        wh3 = self.wh3
        for _x in range(SCREEN_WIDTH):
            _w1 = False
            if w1_enable:
                _w1 = bool((wh0 <= _x <= wh1) ^ w1_invert)
            _w2 = False
            if w2_enable:
                _w2 = bool((wh2 <= _x <= wh3) ^ w2_invert)
            if w1_enable and w2_enable:
                if combine_logic == 0:
                    buf[_x] = _w1 or _w2
                elif combine_logic == 1:
                    buf[_x] = _w1 and _w2
                elif combine_logic == 2:
                    buf[_x] = _w1 != _w2
                else:
                    buf[_x] = _w1 == _w2
            elif w1_enable:
                buf[_x] = _w1
            else:
                buf[_x] = _w2

    def _rebuild_cgram_cache(self) -> None:
        cgram = self.cgram
        cache = self._cgram_cache
        for i in range(256):
            ci = i * 2
            d = cgram[ci] | cgram[ci + 1] << 8
            r5 = d & 0x1F
            g5 = (d >> 5) & 0x1F
            b5 = (d >> 10) & 0x1F
            r8 = (r5 << 3) | (r5 >> 2)
            g8 = (g5 << 3) | (g5 >> 2)
            b8 = (b5 << 3) | (b5 >> 2)
            cache[i] = (r8 << 24) | (g8 << 16) | (b8 << 8) | 0xFF
        self._cgram_dirty = False
