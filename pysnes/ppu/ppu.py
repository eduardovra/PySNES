from array import array
from ctypes import c_uint8
from typing import Optional, Tuple, TYPE_CHECKING

import cython

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
# TODO: overscan — PAL uses 239/240 visible lines; SETINI $2133 bit 2 enables NTSC pseudo-overscan to 239 lines
# SCREEN_HEIGHT = 240


@cython.cclass
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
        self.vmaddl: cython.uchar = 0
        self.vmaddh: cython.uchar = 0
        self._vmdatal: cython.uchar = 0
        self._vmdatah: cython.uchar = 0
        # VRAM read port has a 16-bit prefetch buffer; $2116/$2117 writes
        # refill it (no increment), $2139/$213A reads return the buffered byte
        # and refill + increment depending on VMAIN bit 7.
        self._vram_prefetch: cython.uint = 0

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
        self._m7_latch: cython.uchar = 0
        self.m7a: cython.int = 0
        self.m7b: cython.int = 0
        self.m7c: cython.int = 0
        self.m7d: cython.int = 0
        self.m7x: cython.int = 0
        self.m7y: cython.int = 0
        self.m7sel: cython.uchar = 0
        self.m7_extbg: cython.bint = False   # SETINI ($2133) bit 6
        # Hardware multiplier: product of signed16(m7a) × signed8(m7b_lo).
        # Updated on every write to $211C (M7B). Read via $2134-$2136.
        self._mpy_result: cython.int = 0

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

        # Deferred rendering: per-scanline register snapshots captured at HBlank,
        # consumed in a single render burst at VBlank start.
        self._scanline_snapshots: list = [None] * _TOTAL_SCANLINES
        # Dirty flags for copy-on-change optimisation — True forces a fresh
        # capture on the next snapshot; initialised True so the first frame
        # gets a valid baseline even before any writes occur.
        self._cgram_written_since_snapshot: bool = True
        self._last_snapshot_cgram: bytes = bytes(512)
        self._oam_written_since_snapshot: bool = True
        self._last_snapshot_oam = None

    # Render-relevant registers that can change per-scanline via HDMA.
    # mosaic_enabled is excluded (it's a list — handled explicitly in _capture_snapshot).
    _RENDER_SNAPSHOT_FIELDS = (
        "display_disable", "display_brightness",
        "_bgmode", "_bgpriority",
        "oam_main_screen_enable", "oam_sub_screen_enable",
        "oam_tiledata_address", "oam_nameselect", "oam_base_size",
        "w12sel", "w34sel", "wobjsel",
        "wh0", "wh1", "wh2", "wh3",
        "wbglog", "wobjlog", "tmw", "tsw",
        "cgwsel", "cgadsub",
        "coldata_r", "coldata_g", "coldata_b",
        "m7a", "m7b", "m7c", "m7d", "m7x", "m7y", "m7sel", "m7_extbg",
        "mosaic_size",
    )

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
        # With deferred rendering the framebuffer is written at VBlank, not
        # scanline-by-scanline, so retroactive clearing is no longer needed.
        # Forced blank is captured in each scanline's snapshot; the render pass
        # naturally outputs black for those scanlines via draw_scanline_forced_blank.
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
    def vmdatal(self) -> cython.uchar:
        return self._vmdatal

    @vmdatal.setter
    def vmdatal(self, data: cython.uchar) -> None:
        self._vmdatal = data
        # $2118 writes ONLY the low byte at vram[addr*2+0]. The high byte
        # is preserved (this is the whole point of having separate L/H
        # registers — games like SMW do mode-0 DMA into $2118 alone to
        # update tilemap chars while keeping their attribute bytes).
        word_addr = (self.vmaddl | self.vmaddh << 8) & 0x7FFF
        base_addr = self._remap_vram_addr(word_addr) * 2
        self.vram[base_addr] = data
        if not self.vmain_addr_increment_mode:
            self.increment_vmadd()

    @property
    def vmdatah(self) -> cython.uchar:
        return self._vmdatah

    @vmdatah.setter
    def vmdatah(self, data: cython.uchar) -> None:
        self._vmdatah = data
        word_addr = (self.vmaddl | self.vmaddh << 8) & 0x7FFF
        base_addr = self._remap_vram_addr(word_addr) * 2
        self.vram[base_addr + 1] = data
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

    def rdvraml(self) -> cython.uchar:
        data = self._vram_prefetch & 0xFF
        if not self.vmain_addr_increment_mode:
            self.refill_vram_prefetch()
            self.increment_vmadd()
        return data

    def rdvramh(self) -> cython.uchar:
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
        self._cgram_written_since_snapshot = True

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
        self._oam_written_since_snapshot = True

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
        value: cython.int = (data << 8) | self._m7_latch
        self._m7_latch = data
        if reg == 0x211B:
            self.m7a = value
        elif reg == 0x211C:
            self.m7b = value
            m7a_s: cython.int = self.m7a if self.m7a < 0x8000 else self.m7a - 0x10000
            data_s: cython.int = data if data < 128 else data - 256
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

        # Snapshot register state for deferred rendering (render pass runs at VBlank).
        # HDMA fires after the snapshot so its register updates apply to the next
        # scanline's snapshot, matching real hardware behaviour.
        if 0 < self.v_counter < _VBLANK_START_LINE:
            self._capture_snapshot(self.v_counter)

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
        h_en: cython.bint = st.hirq_enable
        v_en: cython.bint = st.virq_enable
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
        self._render_frame()
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

    def _capture_snapshot(self, y: int) -> None:
        """Capture the current PPU register state for scanline y.

        Stored as a flat tuple to avoid per-scanline dict allocation.
        Layout: 34 scalars | 4 mosaic flags | 8×BG1 | 8×BG2 | 8×BG3 | 8×BG4 | cgram | oam
        (BG fields match Background._STATE_FIELDS order)
        """
        if self._cgram_written_since_snapshot:
            cgram_snap = bytes(self.cgram)
            self._last_snapshot_cgram = cgram_snap
            self._cgram_written_since_snapshot = False
        else:
            cgram_snap = self._last_snapshot_cgram
        if self._oam_written_since_snapshot:
            oam_snap = self.oam.dump_state()
            self._last_snapshot_oam = oam_snap
            self._oam_written_since_snapshot = False
        else:
            oam_snap = self._last_snapshot_oam
        bg1 = self.bg1;  bg2 = self.bg2;  bg3 = self.bg3;  bg4 = self.bg4
        me = self.mosaic_enabled
        self._scanline_snapshots[y] = (
            self.display_disable,    self.display_brightness,
            self._bgmode,            self._bgpriority,
            self.oam_main_screen_enable, self.oam_sub_screen_enable,
            self.oam_tiledata_address,   self.oam_nameselect, self.oam_base_size,
            self.w12sel, self.w34sel, self.wobjsel,
            self.wh0, self.wh1, self.wh2, self.wh3,
            self.wbglog, self.wobjlog, self.tmw, self.tsw,
            self.cgwsel, self.cgadsub,
            self.coldata_r, self.coldata_g, self.coldata_b,
            self.m7a, self.m7b, self.m7c, self.m7d, self.m7x, self.m7y, self.m7sel, self.m7_extbg,
            self.mosaic_size,
            me[0], me[1], me[2], me[3],
            bg1.screen_size, bg1.screen_addr, bg1.tiledata_addr, bg1.tile_size,
            bg1.main_screen_enable, bg1.sub_screen_enable, bg1.hoffset, bg1.voffset,
            bg2.screen_size, bg2.screen_addr, bg2.tiledata_addr, bg2.tile_size,
            bg2.main_screen_enable, bg2.sub_screen_enable, bg2.hoffset, bg2.voffset,
            bg3.screen_size, bg3.screen_addr, bg3.tiledata_addr, bg3.tile_size,
            bg3.main_screen_enable, bg3.sub_screen_enable, bg3.hoffset, bg3.voffset,
            bg4.screen_size, bg4.screen_addr, bg4.tiledata_addr, bg4.tile_size,
            bg4.main_screen_enable, bg4.sub_screen_enable, bg4.hoffset, bg4.voffset,
            cgram_snap, oam_snap,
        )

    def _render_frame(self) -> None:
        """Render all active scanlines using their captured register snapshots."""
        saved_v = self.v_counter
        last_cgram = None
        last_oam = None
        for y in range(1, _VBLANK_START_LINE):
            snap = self._scanline_snapshots[y]
            if snap is None:
                continue
            (display_disable,    display_brightness,
             bgmode_val,         bgpriority,
             oam_mse,            oam_sse,
             oam_tda,            oam_ns,  oam_bs,
             w12sel, w34sel, wobjsel,
             wh0, wh1, wh2, wh3,
             wbglog, wobjlog, tmw, tsw,
             cgwsel, cgadsub,
             coldata_r, coldata_g, coldata_b,
             m7a, m7b, m7c, m7d, m7x, m7y, m7sel, m7_extbg,
             mosaic_size,
             me0, me1, me2, me3,
             b1_ss, b1_sa, b1_ta, b1_ts, b1_me, b1_se, b1_ho, b1_vo,
             b2_ss, b2_sa, b2_ta, b2_ts, b2_me, b2_se, b2_ho, b2_vo,
             b3_ss, b3_sa, b3_ta, b3_ts, b3_me, b3_se, b3_ho, b3_vo,
             b4_ss, b4_sa, b4_ta, b4_ts, b4_me, b4_se, b4_ho, b4_vo,
             cgram_snap, oam_snap,
            ) = snap
            self.display_disable = display_disable
            self.display_brightness = display_brightness
            self._bgmode = bgmode_val
            self._bgpriority = bgpriority
            self.oam_main_screen_enable = oam_mse
            self.oam_sub_screen_enable = oam_sse
            self.oam_tiledata_address = oam_tda
            self.oam_nameselect = oam_ns
            self.oam_base_size = oam_bs
            self.w12sel = w12sel;  self.w34sel = w34sel;  self.wobjsel = wobjsel
            self.wh0 = wh0;  self.wh1 = wh1;  self.wh2 = wh2;  self.wh3 = wh3
            self.wbglog = wbglog;  self.wobjlog = wobjlog
            self.tmw = tmw;  self.tsw = tsw
            self.cgwsel = cgwsel;  self.cgadsub = cgadsub
            self.coldata_r = coldata_r;  self.coldata_g = coldata_g;  self.coldata_b = coldata_b
            self.m7a = m7a;  self.m7b = m7b;  self.m7c = m7c;  self.m7d = m7d
            self.m7x = m7x;  self.m7y = m7y;  self.m7sel = m7sel;  self.m7_extbg = m7_extbg
            self.mosaic_size = mosaic_size
            self.mosaic_enabled[0] = me0;  self.mosaic_enabled[1] = me1
            self.mosaic_enabled[2] = me2;  self.mosaic_enabled[3] = me3
            bg1 = self.bg1
            bg1.screen_size = b1_ss;  bg1.screen_addr = b1_sa
            bg1.tiledata_addr = b1_ta; bg1.tile_size = b1_ts
            bg1.main_screen_enable = b1_me;  bg1.sub_screen_enable = b1_se
            bg1.hoffset = b1_ho;  bg1.voffset = b1_vo
            bg2 = self.bg2
            bg2.screen_size = b2_ss;  bg2.screen_addr = b2_sa
            bg2.tiledata_addr = b2_ta; bg2.tile_size = b2_ts
            bg2.main_screen_enable = b2_me;  bg2.sub_screen_enable = b2_se
            bg2.hoffset = b2_ho;  bg2.voffset = b2_vo
            bg3 = self.bg3
            bg3.screen_size = b3_ss;  bg3.screen_addr = b3_sa
            bg3.tiledata_addr = b3_ta; bg3.tile_size = b3_ts
            bg3.main_screen_enable = b3_me;  bg3.sub_screen_enable = b3_se
            bg3.hoffset = b3_ho;  bg3.voffset = b3_vo
            bg4 = self.bg4
            bg4.screen_size = b4_ss;  bg4.screen_addr = b4_sa
            bg4.tiledata_addr = b4_ta; bg4.tile_size = b4_ts
            bg4.main_screen_enable = b4_me;  bg4.sub_screen_enable = b4_se
            bg4.hoffset = b4_ho;  bg4.voffset = b4_vo
            if cgram_snap is not last_cgram:
                self.cgram[:] = cgram_snap
                self._cgram_dirty = True
                last_cgram = cgram_snap
            if oam_snap is not last_oam:
                self.oam.load_state(oam_snap)
                last_oam = oam_snap
            self.v_counter = y
            self.render_scanline()
            self._scanline_snapshots[y] = None
        self.v_counter = saved_v

    def render_scanline(self):
        """
        Render current scanline in self.v_counter
        https://bin.smwcentral.net/u/4842/regs.txt
        """
        # Forced blank outputs black, not the previous framebuffer contents.
        if self.display_disable:
            self.draw_scanline_forced_blank()
            return

        self._render_layers()
        self.composite_scanline()
        if self.display_brightness < 15:
            self.apply_brightness_scanline()

    def draw_scanline_forced_blank(self) -> None:
        y = self.v_counter - 1
        row = y * SCREEN_WIDTH
        black_u32 = 0x000000FF
        for x in range(SCREEN_WIDTH):
            self.main_bgs[row + x] = black_u32
            self.sub_bgs[row + x] = black_u32
            self.main_layer[row + x] = 0

    def apply_brightness_scanline(self) -> None:
        """Scale the rendered scanline by the master brightness (0–15).

        Brightness 15 = full; brightness 0 = black.  Called only when
        display_brightness < 15 to avoid the overhead on the common case.
        """
        brightness: cython.uint = self.display_brightness
        y: cython.int = self.v_counter - 1
        row: cython.uint = y * SCREEN_WIDTH
        if brightness == 0:
            black: cython.uint = 0x000000FF
            for x in range(SCREEN_WIDTH):
                self.main_bgs[row + x] = black
            return
        for x in range(SCREEN_WIDTH):
            idx: cython.uint = row + x
            p: cython.uint = self.main_bgs[idx]
            r: cython.uint = ((p >> 24) & 0xFF) * brightness // 15
            g: cython.uint = ((p >> 16) & 0xFF) * brightness // 15
            b: cython.uint = ((p >> 8) & 0xFF) * brightness // 15
            self.main_bgs[idx] = (r << 24) | (g << 16) | (b << 8) | (p & 0xFF)

    def _render_layers(self):
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
            # Mode 0: back → front painter order.
            # Each layer writes only where pixels are non-transparent, so the
            # last write at a pixel wins (= "in front").
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg4, 2, False)     # BG4 pri 0
            self.draw_objects(priority=0)                         # OBJ pri 0
            self.draw_background_scanline(self.bg3, 2, False)     # BG3 pri 0
            self.draw_objects(priority=1)                         # OBJ pri 1
            self.draw_background_scanline(self.bg4, 2, True)      # BG4 pri 1
            self.draw_background_scanline(self.bg3, 2, True)      # BG3 pri 1
            self.draw_objects(priority=2)                         # OBJ pri 2
            self.draw_background_scanline(self.bg2, 2, False)     # BG2 pri 0
            self.draw_background_scanline(self.bg1, 2, False)     # BG1 pri 0
            self.draw_objects(priority=3)                         # OBJ pri 3
            self.draw_background_scanline(self.bg2, 2, True)      # BG2 pri 1
            self.draw_background_scanline(self.bg1, 2, True)      # BG1 pri 1
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
            # Mode 1: back → front painter order, with $2105 bit 3 moving
            # BG3 pri-1 either to the very top or behind OBJ pri-0/1.
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg3, 2, False)     # BG3 pri 0
            self.draw_objects(priority=0)                         # OBJ pri 0
            if self._bgpriority == 0:
                self.draw_background_scanline(self.bg3, 2, True)  # BG3 pri 1 (low)
            self.draw_objects(priority=1)                         # OBJ pri 1
            self.draw_background_scanline(self.bg2, 4, False)     # BG2 pri 0
            self.draw_background_scanline(self.bg1, 4, False)     # BG1 pri 0
            self.draw_objects(priority=2)                         # OBJ pri 2
            self.draw_background_scanline(self.bg2, 4, True)      # BG2 pri 1
            self.draw_background_scanline(self.bg1, 4, True)      # BG1 pri 1
            self.draw_objects(priority=3)                         # OBJ pri 3
            if self._bgpriority == 1:
                self.draw_background_scanline(self.bg3, 2, True)  # BG3 pri 1 (high)
        elif self._bgmode == 2:
            # Mode 2: BG1 (4bpp) + BG2 (4bpp) with offset-per-tile via BG3.
            # OPT is not implemented; we render without per-column offsets,
            # which gets the layout approximately right (enough to boot games
            # that probe their own title/menu screens).
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg2, 4, False)   # BG2 pri 0
            self.draw_objects(priority=0)                       # OBJ pri 0
            self.draw_background_scanline(self.bg1, 4, False)   # BG1 pri 0
            self.draw_objects(priority=1)                       # OBJ pri 1
            self.draw_background_scanline(self.bg2, 4, True)    # BG2 pri 1
            self.draw_objects(priority=2)                       # OBJ pri 2
            self.draw_background_scanline(self.bg1, 4, True)    # BG1 pri 1
            self.draw_objects(priority=3)                       # OBJ pri 3
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
            # Mode 3: back → front painter order with sprites interleaved.
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg2, 4, False)   # BG2 pri 0
            self.draw_objects(priority=0)                       # OBJ pri 0
            self.draw_background_scanline(self.bg1, 8, False)   # BG1 pri 0
            self.draw_objects(priority=1)                       # OBJ pri 1
            self.draw_background_scanline(self.bg2, 4, True)    # BG2 pri 1
            self.draw_objects(priority=2)                       # OBJ pri 2
            self.draw_background_scanline(self.bg1, 8, True)    # BG1 pri 1
            self.draw_objects(priority=3)                       # OBJ pri 3
        elif self._bgmode == 4:
            # Mode 4: BG1 (4bpp) + BG2 (2bpp) with OPT (offset-per-tile, not
            # implemented — same simplification as Mode 2).
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg2, 2, False)   # BG2 pri 0
            self.draw_objects(priority=0)                       # OBJ pri 0
            self.draw_background_scanline(self.bg1, 4, False)   # BG1 pri 0
            self.draw_objects(priority=1)                       # OBJ pri 1
            self.draw_background_scanline(self.bg2, 2, True)    # BG2 pri 1
            self.draw_objects(priority=2)                       # OBJ pri 2
            self.draw_background_scanline(self.bg1, 4, True)    # BG1 pri 1
            self.draw_objects(priority=3)                       # OBJ pri 3
        elif self._bgmode == 5:
            # Mode 5: BG1 (4bpp) + BG2 (2bpp).
            # APPROXIMATION: Mode 5 is natively hi-res — the SNES PPU outputs
            # 512 pixels/scanline by interleaving main screen (even cols) and
            # sub screen (odd cols). We render at 256px (main screen only)
            # because the framebuffer is 256px wide; sub-screen interleaving
            # is not implemented. hoffset is in hi-res (512px) coordinates,
            # so we halve it to approximate correct scroll speed at 256px.
            orig_hoff1 = self.bg1.hoffset
            orig_hoff2 = self.bg2.hoffset
            self.bg1.hoffset = self.bg1.hoffset >> 1
            self.bg2.hoffset = self.bg2.hoffset >> 1
            self.draw_scanline_backdrop()
            self.draw_background_scanline(self.bg2, 2, False)   # BG2 pri 0
            self.draw_objects(priority=0)                       # OBJ pri 0
            self.draw_background_scanline(self.bg1, 4, False)   # BG1 pri 0
            self.draw_objects(priority=1)                       # OBJ pri 1
            self.draw_background_scanline(self.bg2, 2, True)    # BG2 pri 1
            self.draw_objects(priority=2)                       # OBJ pri 2
            self.draw_background_scanline(self.bg1, 4, True)    # BG1 pri 1
            self.draw_objects(priority=3)                       # OBJ pri 3
            self.bg1.hoffset = orig_hoff1
            self.bg2.hoffset = orig_hoff2
        elif self._bgmode == 6:
            # Mode 6: BG1 (4bpp) only, hi-res + OPT (OPT not implemented).
            # APPROXIMATION: same hi-res handling as Mode 5 — rendered at
            # 256px (main screen only); hoffset halved from hi-res coordinates.
            orig_hoff1 = self.bg1.hoffset
            self.bg1.hoffset = self.bg1.hoffset >> 1
            self.draw_scanline_backdrop()
            self.draw_objects(priority=0)                       # OBJ pri 0
            self.draw_background_scanline(self.bg1, 4, False)   # BG1 pri 0
            self.draw_objects(priority=1)                       # OBJ pri 1
            self.draw_objects(priority=2)                       # OBJ pri 2
            self.draw_background_scanline(self.bg1, 4, True)    # BG1 pri 1
            self.draw_objects(priority=3)                       # OBJ pri 3
            self.bg1.hoffset = orig_hoff1
        else:
            # Mode 7: affine-transformed BG1 (8bpp). EXTBG BG2 written by same pass.
            # Priority (back→front): backdrop, OBJ0, OBJ1, BG1, BG2(EXTBG), OBJ2, OBJ3
            self.draw_scanline_backdrop()
            self.draw_objects(priority=0)
            self.draw_objects(priority=1)
            self.draw_mode7_scanline()
            self.draw_objects(priority=2)
            self.draw_objects(priority=3)

    def composite_scanline(self) -> None:
        """Apply CGADSUB color math, blending sub_bgs into main_bgs.

        CGADSUB ($2131) layout:
          bit 7: 0 = add, 1 = subtract (main minus sub)
          bit 6: 0 = full,  1 = half-intensity (divide result by 2)
          bit 5: backdrop participates
          bit 4: OBJ palettes 4-7 participate
          bit 3..0: BG4..BG1 participate

        CGWSEL ($2130) bits 5-4 gate WHEN color math applies per pixel:
          00 = always, 01 = inside color window, 10 = outside, 11 = never.
        The color window uses W1/W2 with WOBJSEL bits 4-7 for enable/invert
        and WOBJLOG bits 2-3 for combining W1+W2 (OR/AND/XOR/XNOR).

        Not yet implemented: CGWSEL bits 7-6 clip-to-black, bit 1 sub-source
        select (we always use sub_bgs, which already holds COLDATA where no
        sub layer covered the pixel).
        """
        cgadsub: cython.uint = self.cgadsub
        cgwsel: cython.uint = self.cgwsel
        cmath_mode: cython.uint = (cgwsel >> 4) & 0x3  # 00..11
        if cgadsub == 0 or cmath_mode == 0x3:
            return
        subtract: cython.bint = cgadsub & 0x80
        half: cython.bint = cgadsub & 0x40
        enable_bg1: cython.bint = cgadsub & 0x01
        enable_bg2: cython.bint = cgadsub & 0x02
        enable_bg3: cython.bint = cgadsub & 0x04
        enable_bg4: cython.bint = cgadsub & 0x08
        enable_obj: cython.bint = cgadsub & 0x10
        enable_back: cython.bint = cgadsub & 0x20

        # Color-window (math window) setup: WOBJSEL bits 4-7, WOBJLOG bits 2-3.
        # Per $2125 spec (matching $2123 W12SEL convention): bit 0=invert, bit 1=enable.
        # Pairs: bits 0-1 OBJ W1, 2-3 OBJ W2, 4-5 MATH W1, 6-7 MATH W2.
        math_w1_invert: cython.bint = (self.wobjsel >> 4) & 1
        math_w1_enable: cython.bint = (self.wobjsel >> 5) & 1
        math_w2_invert: cython.bint = (self.wobjsel >> 6) & 1
        math_w2_enable: cython.bint = (self.wobjsel >> 7) & 1
        math_logic: cython.uint = (self.wobjlog >> 2) & 0x3  # 0=OR,1=AND,2=XOR,3=XNOR

        y: cython.int = self.v_counter - 1
        row: cython.uint = y * SCREEN_WIDTH
        for x in range(SCREEN_WIDTH):
            idx: cython.uint = row + x
            layer: cython.uchar = self.main_layer[idx]
            participate: cython.bint = False
            if layer == 0:
                participate = enable_back
            elif layer == 1:
                participate = enable_bg1
            elif layer == 2:
                participate = enable_bg2
            elif layer == 3:
                participate = enable_bg3
            elif layer == 4:
                participate = enable_bg4
            elif layer == 5:
                participate = enable_obj
            if not participate:
                continue

            # Color-window gating (CGWSEL bits 5-4).
            if cmath_mode != 0:
                # Compute the color window value at this x.
                in_w1: cython.bint = False
                if math_w1_enable:
                    in_range1: cython.bint = (self.wh0 <= x <= self.wh1)
                    in_w1 = in_range1 ^ math_w1_invert
                in_w2: cython.bint = False
                if math_w2_enable:
                    in_range2: cython.bint = (self.wh2 <= x <= self.wh3)
                    in_w2 = in_range2 ^ math_w2_invert
                if math_w1_enable and math_w2_enable:
                    if math_logic == 0:
                        in_window: cython.bint = in_w1 or in_w2
                    elif math_logic == 1:
                        in_window = in_w1 and in_w2
                    elif math_logic == 2:
                        in_window = in_w1 != in_w2  # XOR
                    else:
                        in_window = in_w1 == in_w2  # XNOR
                elif math_w1_enable:
                    in_window = in_w1
                elif math_w2_enable:
                    in_window = in_w2
                else:
                    # No window active; treat as "always inside" (all pixels
                    # qualify as inside, none qualify as outside). This matches
                    # the observed Mesen semantic where a disabled window acts
                    # as if inside-of-nothing = full-screen inside.
                    in_window = True
                if cmath_mode == 1 and not in_window:
                    continue  # inside only → skip outside
                if cmath_mode == 2 and in_window:
                    continue  # outside only → skip inside
            m: cython.uint = self.main_bgs[idx]
            s: cython.uint = self.sub_bgs[idx]
            mr: cython.int = (m >> 24) & 0xFF
            mg: cython.int = (m >> 16) & 0xFF
            mb: cython.int = (m >> 8) & 0xFF
            sr: cython.int = (s >> 24) & 0xFF
            sg: cython.int = (s >> 16) & 0xFF
            sb: cython.int = (s >> 8) & 0xFF
            r: cython.int
            g: cython.int
            b: cython.int
            if subtract:
                r = mr - sr
                g = mg - sg
                b = mb - sb
                if r < 0:
                    r = 0
                if g < 0:
                    g = 0
                if b < 0:
                    b = 0
                if half:
                    r >>= 1
                    g >>= 1
                    b >>= 1
            else:
                r = mr + sr
                g = mg + sg
                b = mb + sb
                # Half applies before saturation: the 9-bit adder's overflow
                # bit becomes the high bit of the halved result.
                if half:
                    r >>= 1
                    g >>= 1
                    b >>= 1
                if r > 255:
                    r = 255
                if g > 255:
                    g = 255
                if b > 255:
                    b = 255
            self.main_bgs[idx] = (r << 24) | (g << 16) | (b << 8) | (m & 0xFF)

    def draw_scanline_backdrop(self) -> None:
        """Draw the backdrop color for the current scanline.

        Main-screen backdrop = CGRAM[0]. Sub-screen backdrop = COLDATA fixed
        color ($2132), per SNES PPU behavior — sub-screen doesn't use CGRAM[0]."""
        main_u32 = self.get_u32_backdrop_color()
        sub_u32 = self.get_u32_coldata_color()
        y = self.v_counter - 1
        row = y * SCREEN_WIDTH
        for x in range(SCREEN_WIDTH):
            self.main_bgs[row + x] = main_u32
            self.sub_bgs[row + x] = sub_u32
            self.main_layer[row + x] = 0

    def draw_mode7_scanline(self) -> None:
        """Render BG1 (and EXTBG BG2) for Mode 7 using affine transformation.

        VRAM layout: each word at address N has low byte = tilemap tile number
        (128×128 grid) and high byte = 8bpp pixel data for tile/pixel lookups.

        TODO: EXTBG — M7SEL bit 6 enables a second BG layer from the high byte of
        the VRAM word; priority split between BG1 and BG2(EXTBG) not yet wired.
        TODO: repeat/wrap — M7SEL bits 0-1 control out-of-bounds behavior
        (0=wrap, 1=transparent, 2=fill with tile 0); currently always wraps.
        TODO: border fill — M7SEL bit 7 selects between transparent and tile-0
        fill for pixels that map outside the 1024×1024 mode-7 plane.
        """
        # v_counter is the hardware scanline (1 = first visible line).
        # The affine transform uses the hardware scanline directly; the output
        # row is 0-indexed so we subtract 1 only for the buffer write.
        scan_y: cython.int = self.v_counter       # hardware scanline (1-based) for transform
        row_y: cython.int = self.v_counter - 1    # 0-based index into main_bgs / sub_bgs

        # Sign-extend 16-bit matrix coefficients (m7_write stores them unsigned)
        a: cython.int = self.m7a if self.m7a < 0x8000 else self.m7a - 0x10000
        b: cython.int = self.m7b if self.m7b < 0x8000 else self.m7b - 0x10000
        c: cython.int = self.m7c if self.m7c < 0x8000 else self.m7c - 0x10000
        d: cython.int = self.m7d if self.m7d < 0x8000 else self.m7d - 0x10000

        # Center of rotation (already 13-bit signed from m7_write)
        cx: cython.int = self.m7x
        cy: cython.int = self.m7y

        # Scroll offsets: BG1HOFS/VOFS are reused as M7HOFS/VOFS; sign-extend 13-bit
        hofs: cython.int = self.bg1.hoffset & 0x1FFF
        if hofs >= 0x1000:
            hofs -= 0x2000
        vofs: cython.int = self.bg1.voffset & 0x1FFF
        if vofs >= 0x1000:
            vofs -= 0x2000

        # M7SEL flags
        h_flip: cython.bint = (self.m7sel >> 0) & 1
        v_flip: cython.bint = (self.m7sel >> 1) & 1
        # bits 7-6: 0/1=wrap, 2=transparent outside 1024×1024, 3=fill with tile 0
        screen_over: cython.uchar = (self.m7sel >> 6) & 3

        # Apply V-flip to scanline (Mode 7 "screen" height = 256)
        fy: cython.int = (255 - scan_y) if v_flip else scan_y
        dy: cython.int = fy + vofs - cy

        # Precompute y-column of the matrix (constant for this scanline)
        b_dy: cython.int = b * dy
        d_dy: cython.int = d * dy

        row: cython.int = row_y * SCREEN_WIDTH
        write_main_bg1: cython.bint = self.bg1.main_screen_enable
        write_sub_bg1: cython.bint = self.bg1.sub_screen_enable
        write_main_bg2: cython.bint = self.bg2.main_screen_enable
        write_sub_bg2: cython.bint = self.bg2.sub_screen_enable
        extbg: cython.bint = self.m7_extbg

        # Window masking for BG1 (same logic as draw_background_scanline, bg_idx=0)
        window_active: cython.bint = bool(self.tmw & 0x01)
        w1_enable: cython.bint = bool((self.w12sel >> 1) & 1)
        w1_invert: cython.bint = bool(self.w12sel & 1)
        w2_enable: cython.bint = bool((self.w12sel >> 3) & 1)
        w2_invert: cython.bint = bool((self.w12sel >> 2) & 1)
        combine_logic: cython.uint = self.wbglog & 0x3

        for px in range(SCREEN_WIDTH):
            # Window masking: skip pixel if it falls in the masked zone
            if window_active and (w1_enable or w2_enable):
                w1_val: cython.bint = False
                if w1_enable:
                    in_range1: cython.bint = (self.wh0 <= px <= self.wh1)
                    w1_val = in_range1 ^ w1_invert
                w2_val: cython.bint = False
                if w2_enable:
                    in_range2: cython.bint = (self.wh2 <= px <= self.wh3)
                    w2_val = in_range2 ^ w2_invert
                masked: cython.bint
                if w1_enable and w2_enable:
                    if combine_logic == 0:
                        masked = w1_val or w2_val
                    elif combine_logic == 1:
                        masked = w1_val and w2_val
                    elif combine_logic == 2:
                        masked = w1_val != w2_val
                    else:
                        masked = w1_val == w2_val
                elif w1_enable:
                    masked = w1_val
                else:
                    masked = w2_val
                if masked:
                    continue

            fx: cython.int = (255 - px) if h_flip else px
            dx: cython.int = fx + hofs - cx

            # Affine transform → VRAM coordinate (fixed-point 8.8 → integer)
            vx: cython.int = ((a * dx + b_dy) >> 8) + cx
            vy: cython.int = ((c * dx + d_dy) >> 8) + cy

            outside: cython.bint = vx < 0 or vx >= 1024 or vy < 0 or vy >= 1024
            if outside:
                if screen_over == 2:
                    continue  # transparent
                elif screen_over != 3:
                    vx &= 0x3FF  # wrap to 1024×1024
                    vy &= 0x3FF
                    outside = False

            # Tilemap: low byte of VRAM word at (ty*128+tx) = tile number
            if outside:  # screen_over == 3: force tile 0
                tile_num: cython.int = 0
            else:
                tile_num = self.vram[2 * ((vy >> 3) * 128 + (vx >> 3))]

            # Pixel: high byte of VRAM word at tile data offset (8bpp)
            tile_px: cython.int = vx & 7
            tile_py: cython.int = vy & 7
            pixel: cython.uchar = self.vram[2 * (tile_num * 64 + tile_py * 8 + tile_px) + 1]

            if pixel == 0:
                continue  # transparent

            idx: cython.int = row + px

            if extbg and pixel & 0x80:
                # EXTBG: high bit selects BG2 layer
                if not (write_main_bg2 or write_sub_bg2):
                    continue
                color: cython.uint = self.get_u32_color(8, 0, pixel)
                if write_main_bg2:
                    self.main_bgs[idx] = color
                    self.main_layer[idx] = 2  # BG2
                if write_sub_bg2:
                    self.sub_bgs[idx] = color
            else:
                if not (write_main_bg1 or write_sub_bg1):
                    continue
                color = self.get_u32_color(8, 0, pixel)
                if write_main_bg1:
                    self.main_bgs[idx] = color
                    self.main_layer[idx] = 1  # BG1
                if write_sub_bg1:
                    self.sub_bgs[idx] = color

    @cython.ccall
    def draw_background_scanline(self, bg: Background, bpp: cython.uchar, priority_selector: cython.bint):
        # If neither main nor sub is enabled, nothing to do at all.
        if not bg.main_screen_enable and not bg.sub_screen_enable:
            return

        write_main: cython.bint = bg.main_screen_enable
        write_sub: cython.bint = bg.sub_screen_enable
        layer_tag: cython.uchar = bg.number

        # Window masking setup for this BG.
        # $212E TMW bit (bg.number-1): window masking enabled for this BG on main screen.
        # $2123 W12SEL (for BG1/BG2) / $2124 W34SEL (for BG3/BG4):
        #   bit pairs per BG: (W1 invert, W1 enable, W2 invert, W2 enable).
        # For BG1: W12SEL bits 3:2:1:0 = (W2_enable, W2_invert, W1_enable, W1_invert).
        # invert=0: pixels INSIDE [WHx_L,WHx_R] are in the mask zone.
        # invert=1: pixels OUTSIDE [WHx_L,WHx_R] are in the mask zone.
        # $212A WBGLOG combines the two window outputs per BG:
        #   bits 2n..2n+1 for BGn: 0=OR, 1=AND, 2=XOR, 3=XNOR.
        bg_idx: cython.uint = bg.number - 1
        window_active: cython.bint = self.tmw & (1 << bg_idx)
        w1_enable: cython.bint = False
        w1_invert: cython.bint = False
        w2_enable: cython.bint = False
        w2_invert: cython.bint = False
        combine_logic: cython.uint = 0
        if window_active:
            if bg_idx == 0:
                w1_enable = (self.w12sel >> 1) & 1
                w1_invert = self.w12sel & 1
                w2_enable = (self.w12sel >> 3) & 1
                w2_invert = (self.w12sel >> 2) & 1
            elif bg_idx == 1:
                w1_enable = (self.w12sel >> 5) & 1
                w1_invert = (self.w12sel >> 4) & 1
                w2_enable = (self.w12sel >> 7) & 1
                w2_invert = (self.w12sel >> 6) & 1
            elif bg_idx == 2:
                w1_enable = (self.w34sel >> 1) & 1
                w1_invert = self.w34sel & 1
                w2_enable = (self.w34sel >> 3) & 1
                w2_invert = (self.w34sel >> 2) & 1
            elif bg_idx == 3:
                w1_enable = (self.w34sel >> 5) & 1
                w1_invert = (self.w34sel >> 4) & 1
                w2_enable = (self.w34sel >> 7) & 1
                w2_invert = (self.w34sel >> 6) & 1
            combine_logic = (self.wbglog >> (bg_idx * 2)) & 0x3

        # Mosaic: when enabled for this BG with size > 1, every S×S block of
        # screen pixels shows the color sampled from the block's top-left
        # pixel. We apply mosaic by rounding the effective scrx/scry down to
        # the nearest S multiple (in screen-space) before doing the tilemap/
        # tile fetch. The OUTPUT position (orgx, orgy) is unchanged.
        mosaic_on: cython.bint = self.mosaic_enabled[bg_idx]
        mosaic_size: cython.uint = self.mosaic_size

        # Find the tilemap entry for the requested screen position

        # Hoist scanline-invariant values out of the 256-pixel loop.
        screen_size: cython.uint = bg.screen_size
        bg_size_w: cython.uint = 32 << (screen_size & 1)
        bg_size_h: cython.uint = 32 << (screen_size >> 1)
        scroll_x: cython.uint = bg.hoffset
        scroll_y: cython.uint = bg.voffset
        tiledata_addr: cython.uint = bg.tiledata_addr
        screen_addr: cython.uint = bg.screen_addr & 0xFFFF
        color_offset: cython.uint = bg.color_offset_mode_0 if self._bgmode == 0 else 0
        bpp_mult: cython.uint = 1 << bpp
        if self._cgram_dirty:
            self._rebuild_cgram_cache()
        cgram_cache = self._cgram_cache
        orgy: cython.uint = self.v_counter - 1
        scry_base: cython.uint = self.v_counter
        row_base: cython.uint = orgy * SCREEN_WIDTH
        wh0: cython.uint = self.wh0
        wh1: cython.uint = self.wh1
        wh2: cython.uint = self.wh2
        wh3: cython.uint = self.wh3
        vram = self.vram
        main_bgs = self.main_bgs
        main_layer = self.main_layer
        sub_bgs = self.sub_bgs

        # Precompute per-dot window mask once for the scanline (constant window boundaries).
        window_masked = None
        if window_active and (w1_enable or w2_enable):
            window_masked = bytearray(256)
            for _x in range(256):
                _w1: cython.bint = False
                if w1_enable:
                    _w1 = bool((wh0 <= _x <= wh1) ^ w1_invert)
                _w2: cython.bint = False
                if w2_enable:
                    _w2 = bool((wh2 <= _x <= wh3) ^ w2_invert)
                if w1_enable and w2_enable:
                    if combine_logic == 0:
                        window_masked[_x] = _w1 or _w2
                    elif combine_logic == 1:
                        window_masked[_x] = _w1 and _w2
                    elif combine_logic == 2:
                        window_masked[_x] = _w1 != _w2
                    else:
                        window_masked[_x] = _w1 == _w2
                elif w1_enable:
                    window_masked[_x] = _w1
                else:
                    window_masked[_x] = _w2

        if mosaic_on and mosaic_size > 1:
            # Slow path: mosaic snaps scry per pixel — cannot batch by tile column.
            for dot in range(256):
                if window_masked is not None and window_masked[dot]:
                    continue
                scrx: cython.uint = dot - (dot % mosaic_size)
                anchor_orgy: cython.uint = orgy - (orgy % mosaic_size)
                scry: cython.uint = (anchor_orgy + 1 + scroll_y) % (8 * bg_size_h)
                scrx = (scrx + scroll_x) % (8 * bg_size_w)

                offset: cython.uint = ((scry % 256 if bg_size_w == 64 else scry) // 8) * 32
                offset += ((scrx % 256) // 8)
                offset += (scrx // 256) * 0x400
                offset += (bg_size_w // 64) * ((scry // 256) * 0x800)
                tilemap_word_addr: cython.uint = (screen_addr + offset) * 2 & 0xFFFF

                low: cython.uint = vram[tilemap_word_addr]
                high: cython.uint = vram[tilemap_word_addr + 1]
                tile_num: cython.uint = (high & 3) << 8 | low
                tilemap_palette: cython.uint = (high >> 2) & 7
                tilemap_priority: cython.bint = (high >> 5) & 1
                tilemap_h_flip: cython.bint = (high >> 6) & 1
                tilemap_v_flip: cython.bint = (high >> 7) & 1

                if tilemap_priority == priority_selector:
                    i: cython.uint = scry & 7
                    j: cython.uint = scrx & 7
                    v_shift: cython.uint = i if not tilemap_v_flip else (7 - i)
                    h_shift: cython.uint = (7 - j) if not tilemap_h_flip else j
                    if bpp == 2:
                        tile_address: cython.uint = (tiledata_addr + tile_num * 16 + v_shift * 2) & 0xFFFF
                        b_lo: cython.uint = vram[tile_address]
                        b_hi: cython.uint = vram[(tile_address + 1) & 0xFFFF]
                        v: cython.uint = ((b_lo >> h_shift) & 1) | (((b_hi >> h_shift) & 1) << 1)
                    elif bpp == 4:
                        tile_address: cython.uint = (tiledata_addr + tile_num * 32 + v_shift * 2) & 0xFFFF
                        b_1: cython.uint = vram[tile_address]
                        b_2: cython.uint = vram[(tile_address + 1) & 0xFFFF]
                        b_3: cython.uint = vram[(tile_address + 16) & 0xFFFF]
                        b_4: cython.uint = vram[(tile_address + 17) & 0xFFFF]
                        v: cython.uint = ((b_1 >> h_shift) & 1) | (((b_2 >> h_shift) & 1) << 1) | \
                            (((b_3 >> h_shift) & 1) << 2) | (((b_4 >> h_shift) & 1) << 3)
                    elif bpp == 8:
                        tile_address: cython.uint = (tiledata_addr + tile_num * 64 + v_shift * 2) & 0xFFFF
                        b_1: cython.uint = vram[tile_address]
                        b_2: cython.uint = vram[(tile_address + 1) & 0xFFFF]
                        b_3: cython.uint = vram[(tile_address + 16) & 0xFFFF]
                        b_4: cython.uint = vram[(tile_address + 17) & 0xFFFF]
                        b_5: cython.uint = vram[(tile_address + 32) & 0xFFFF]
                        b_6: cython.uint = vram[(tile_address + 33) & 0xFFFF]
                        b_7: cython.uint = vram[(tile_address + 48) & 0xFFFF]
                        b_8: cython.uint = vram[(tile_address + 49) & 0xFFFF]
                        v: cython.uint = ((b_1 >> h_shift) & 1) | (((b_2 >> h_shift) & 1) << 1) | \
                            (((b_3 >> h_shift) & 1) << 2) | (((b_4 >> h_shift) & 1) << 3) | \
                            (((b_5 >> h_shift) & 1) << 4) | (((b_6 >> h_shift) & 1) << 5) | \
                            (((b_7 >> h_shift) & 1) << 6) | (((b_8 >> h_shift) & 1) << 7)
                    else:
                        raise NotImplementedError(f"Invalid bpp {bpp}")
                    if v:
                        u32_color = cgram_cache[tilemap_palette * bpp_mult + v + color_offset]
                        pix_idx: cython.uint = row_base + dot
                        if write_main:
                            main_bgs[pix_idx] = u32_color
                            main_layer[pix_idx] = layer_tag
                        if write_sub:
                            sub_bgs[pix_idx] = u32_color
        else:
            # Fast path: scry is constant for the whole scanline.
            # Process pixels in tile-column batches (up to 8 pixels at a time) so
            # each tilemap fetch and tile-data read is amortised across 8 pixels
            # instead of being repeated once per pixel.
            eff_scry: cython.uint = (scry_base + scroll_y) % (8 * bg_size_h)
            i: cython.uint = eff_scry & 7
            # Precompute the scry-dependent part of the tilemap word offset.
            # (bg_size_w >> 6) == bg_size_w // 64: 0 for 32-tile-wide, 1 for 64-tile-wide.
            scry_for_row: cython.uint = eff_scry % 256 if bg_size_w == 64 else eff_scry
            scry_page: cython.uint = eff_scry >> 8
            scry_offset: cython.uint = (scry_for_row >> 3) * 32 + (bg_size_w >> 6) * (scry_page * 0x800)

            eff_scrx: cython.uint = scroll_x % (8 * bg_size_w)
            scrx_wrap: cython.uint = 8 * bg_size_w
            dot: cython.uint = 0
            while dot < 256:
                pixel_in_tile: cython.uint = eff_scrx & 7
                n_pixels: cython.uint = 8 - pixel_in_tile
                if dot + n_pixels > 256:
                    n_pixels = 256 - dot

                # Tilemap fetch — once per tile column.
                scrx_page: cython.uint = eff_scrx >> 8
                col_offset: cython.uint = ((eff_scrx & 0xFF) >> 3) + scrx_page * 0x400
                tilemap_word_addr: cython.uint = (screen_addr + scry_offset + col_offset) * 2 & 0xFFFF
                low: cython.uint = vram[tilemap_word_addr]
                high: cython.uint = vram[tilemap_word_addr + 1]
                tile_num: cython.uint = (high & 3) << 8 | low
                tilemap_palette: cython.uint = (high >> 2) & 7
                tilemap_priority: cython.bint = (high >> 5) & 1
                tilemap_h_flip: cython.bint = (high >> 6) & 1
                tilemap_v_flip: cython.bint = (high >> 7) & 1

                if tilemap_priority == priority_selector:
                    v_shift: cython.uint = i if not tilemap_v_flip else (7 - i)

                    # Tile-data fetch — once per tile column, shared across all 8 pixels.
                    if bpp == 2:
                        tile_address: cython.uint = (tiledata_addr + tile_num * 16 + v_shift * 2) & 0xFFFF
                        b_lo: cython.uint = vram[tile_address]
                        b_hi: cython.uint = vram[(tile_address + 1) & 0xFFFF]
                        for k in range(n_pixels):
                            current_dot: cython.uint = dot + k
                            if window_masked is not None and window_masked[current_dot]:
                                continue
                            jj: cython.uint = pixel_in_tile + k
                            h_shift: cython.uint = (7 - jj) if not tilemap_h_flip else jj
                            v: cython.uint = ((b_lo >> h_shift) & 1) | (((b_hi >> h_shift) & 1) << 1)
                            if v:
                                u32_color = cgram_cache[tilemap_palette * bpp_mult + v + color_offset]
                                pix_idx: cython.uint = row_base + current_dot
                                if write_main:
                                    main_bgs[pix_idx] = u32_color
                                    main_layer[pix_idx] = layer_tag
                                if write_sub:
                                    sub_bgs[pix_idx] = u32_color
                    elif bpp == 4:
                        tile_address: cython.uint = (tiledata_addr + tile_num * 32 + v_shift * 2) & 0xFFFF
                        b_1: cython.uint = vram[tile_address]
                        b_2: cython.uint = vram[(tile_address + 1) & 0xFFFF]
                        b_3: cython.uint = vram[(tile_address + 16) & 0xFFFF]
                        b_4: cython.uint = vram[(tile_address + 17) & 0xFFFF]
                        for k in range(n_pixels):
                            current_dot: cython.uint = dot + k
                            if window_masked is not None and window_masked[current_dot]:
                                continue
                            jj: cython.uint = pixel_in_tile + k
                            h_shift: cython.uint = (7 - jj) if not tilemap_h_flip else jj
                            v: cython.uint = ((b_1 >> h_shift) & 1) | (((b_2 >> h_shift) & 1) << 1) | \
                                (((b_3 >> h_shift) & 1) << 2) | (((b_4 >> h_shift) & 1) << 3)
                            if v:
                                u32_color = cgram_cache[tilemap_palette * bpp_mult + v + color_offset]
                                pix_idx: cython.uint = row_base + current_dot
                                if write_main:
                                    main_bgs[pix_idx] = u32_color
                                    main_layer[pix_idx] = layer_tag
                                if write_sub:
                                    sub_bgs[pix_idx] = u32_color
                    elif bpp == 8:
                        tile_address: cython.uint = (tiledata_addr + tile_num * 64 + v_shift * 2) & 0xFFFF
                        b_1: cython.uint = vram[tile_address]
                        b_2: cython.uint = vram[(tile_address + 1) & 0xFFFF]
                        b_3: cython.uint = vram[(tile_address + 16) & 0xFFFF]
                        b_4: cython.uint = vram[(tile_address + 17) & 0xFFFF]
                        b_5: cython.uint = vram[(tile_address + 32) & 0xFFFF]
                        b_6: cython.uint = vram[(tile_address + 33) & 0xFFFF]
                        b_7: cython.uint = vram[(tile_address + 48) & 0xFFFF]
                        b_8: cython.uint = vram[(tile_address + 49) & 0xFFFF]
                        for k in range(n_pixels):
                            current_dot: cython.uint = dot + k
                            if window_masked is not None and window_masked[current_dot]:
                                continue
                            jj: cython.uint = pixel_in_tile + k
                            h_shift: cython.uint = (7 - jj) if not tilemap_h_flip else jj
                            v: cython.uint = ((b_1 >> h_shift) & 1) | (((b_2 >> h_shift) & 1) << 1) | \
                                (((b_3 >> h_shift) & 1) << 2) | (((b_4 >> h_shift) & 1) << 3) | \
                                (((b_5 >> h_shift) & 1) << 4) | (((b_6 >> h_shift) & 1) << 5) | \
                                (((b_7 >> h_shift) & 1) << 6) | (((b_8 >> h_shift) & 1) << 7)
                            if v:
                                u32_color = cgram_cache[tilemap_palette * bpp_mult + v + color_offset]
                                pix_idx: cython.uint = row_base + current_dot
                                if write_main:
                                    main_bgs[pix_idx] = u32_color
                                    main_layer[pix_idx] = layer_tag
                                if write_sub:
                                    sub_bgs[pix_idx] = u32_color
                    else:
                        raise NotImplementedError(f"Invalid bpp {bpp}")

                dot += n_pixels
                eff_scrx += n_pixels
                if eff_scrx >= scrx_wrap:
                    eff_scrx -= scrx_wrap

    def draw_tiles(
        self,
        bpp: int,
        x_offset: int,
        y_offset: int,
        tile: Tilemap | Object,
        tile_base_addr: int,
        tile_width: int,
        tile_height: int,
        tile_character: int,
    ) -> None:
        """
        Determines the number of horizontal and vertical
        tiles to be drawn accordingly to width and height,
        then calls self.draw_tile to render them
        """
        h_tiles = tile_width // 8
        v_tiles = tile_height // 8
        vc = self.v_counter

        for tile_pos_v in range(v_tiles):
            # Compute the screen-Y of the top of this tile row (before flip).
            if tile.v_flip:
                tile_row_y = y_offset + (v_tiles - 1 - tile_pos_v) * 8
            else:
                tile_row_y = y_offset + tile_pos_v * 8
            # Skip the entire row if v_counter isn't within its 8-pixel span.
            if not (tile_row_y <= vc < tile_row_y + 8):
                continue

            for tile_pos_h in range(h_tiles):
                # compute x, y positions
                if tile.h_flip:
                    x = x_offset + (h_tiles - 1 - tile_pos_h) * 8
                else:
                    x = x_offset + tile_pos_h * 8
                y = tile_row_y

                # bytes per 8×8 tile: 8 rows × bpp bytes/row (32 for 4BPP)
                tile_size = 8 * bpp
                tile_addr = tile_character + tile_pos_h + tile_pos_v * 16
                vram_index = (tile_base_addr + tile_addr * tile_size) & 0xFFFF

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
        tile: Tilemap | Object,
        tile_data,
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
        tile_data,
        tile_data_index: int,
        bpp: int,
        palette: int,
        pixel: int,
        x: int,
        y: int,
    ) -> None:
        mask = 1 << pixel
        assert bpp in (2, 4), bpp

        # offset to the correct vram byte. VRAM is 64KB and wraps on real
        # hardware, so mask each byte index to 16 bits to avoid IndexError
        # when a sprite's tile data sits near the top of VRAM.
        i += tile_data_index
        tlen = len(tile_data)

        l = tile_data[(i + 0) % tlen]
        h = tile_data[(i + 1) % tlen]
        color = (h & mask) >> pixel << 1 | (l & mask) >> pixel << 0
        if bpp >= 4:
            l = tile_data[(i + 16) % tlen]
            h = tile_data[(i + 17) % tlen]
            color |= (h & mask) >> pixel << 3 | (l & mask) >> pixel << 2

        # color == 0 is transparent — do not overwrite existing pixel
        if color and 0 <= x < SCREEN_WIDTH:
            u32_color = self.get_u32_color(bpp, palette, color)
            idx: cython.uint = (y - 1) * SCREEN_WIDTH + x
            self.main_bgs[idx] = u32_color
            # OBJ palettes 4-7 (stored as 12-15 in the global palette space) participate
            # in color math (layer 5). Palettes 0-3 are immune (layer 6, never matched).
            self.main_layer[idx] = 5 if palette >= 12 else 6

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

    def get_u32_color(self, bpp: int, palette: int, color: int, color_offset: int = 0) -> int:
        if self._cgram_dirty:
            self._rebuild_cgram_cache()
        if bpp == 8:
            color_index = color
        else:
            color_index = palette * (1 << bpp) + color + color_offset
        return self._cgram_cache[color_index]

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

    def get_u32_coldata_color(self) -> int:
        r_8bit = (self.coldata_r << 3) | (self.coldata_r >> 2)
        g_8bit = (self.coldata_g << 3) | (self.coldata_g >> 2)
        b_8bit = (self.coldata_b << 3) | (self.coldata_b >> 2)
        return (r_8bit << 24) | (g_8bit << 16) | (b_8bit << 8) | 255

    def draw_objects(self, priority: int = -1) -> None:
        # objects are the building blocks for sprites
        # they can move independently from the background and always use 4bpp
        # they can be 8x8, 16x16, 32x32 or 64x64 pixels in size
        # oam is the memory region where the objects properties are stored. each obj uses 34 bits
        #
        # priority: when >= 0, only objects with obj.priority == priority are
        # drawn. This lets the mode dispatcher interleave sprite layers with
        # BG layers in the correct front-to-back order per SNES spec.

        if not self.oam_main_screen_enable:
            return

        vc = self.v_counter
        for obj in self.oam.objects:
            if priority >= 0 and obj.priority != priority:
                continue
            if obj.y == 240:  # TODO: replace with proper Y-bounds check; y=240 is the common hide convention but not the hardware rule
                continue

            tile_width, tile_height = self.get_obj_dimensions(obj.size)
            # Skip sprites whose Y range doesn't include the current scanline,
            # avoiding draw_tiles call overhead for the majority of objects.
            if not (obj.y <= vc < obj.y + tile_height):
                continue

            # OBJ X is 9-bit signed (Anomie/fullsnes): values 256..511 represent
            # -256..-1, letting sprites straddle the left edge. draw_point's
            # 0 ≤ x < 256 guard clips the off-screen pixels.
            x_screen = obj.x - 512 if obj.x >= 256 else obj.x
            # Apply name_select: OAM byte 3 bit 0 selects the second sprite name
            # table, offset from the first by (oam_nameselect+1)*0x1000 VRAM words.
            tile_base_word = self.oam_tiledata_address
            if obj.name_select:
                tile_base_word = (tile_base_word + (self.oam_nameselect + 1) * 0x1000) & 0x7FFF

            self.draw_tiles(
                bpp=4,  # Always 4bpp for objects
                x_offset=x_screen,
                y_offset=obj.y,
                tile=obj,
                tile_base_addr=tile_base_word * 2,
                tile_width=tile_width,
                tile_height=tile_height,
                tile_character=obj.character,
            )

    def get_obj_dimensions(self, obj_size: cython.bint) -> Tuple[int, int]:
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
        return self._OBJ_DIM_TABLE[self.oam_base_size][obj_size]


class OAM:
    def __init__(self, *, oam_dump: Optional[bytes] = None) -> None:
        # Object Attribute Memory
        self.oam = bytearray(512 + 32)
        self.objects = [Object() for i in range(128)]

        # Load objects from dump file
        if oam_dump:
            for addr, data in enumerate(oam_dump):
                self.write(addr, data)

    def read(self, addr: int) -> int:
        return self.oam[addr]

    def write(self, addr: int, data: int) -> None:
        if self.oam[addr] != data:
            self.oam[addr] = data
            self.update_object(addr)

    def dump_state(self) -> dict:
        return {"oam": bytes(self.oam)}

    def load_state(self, d: dict) -> None:
        self.oam[:] = d["oam"]
        # Rebuild parsed objects[] from raw bytes — cheaper than persisting
        # the parsed view, and update_object covers both low and high tables.
        for addr in range(len(self.oam)):
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
            obj.size = (sx >> 1) & 1

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
        obj.name_select = data & 0x01
        obj.palette = (
            (data >> 1) & 0x07
        ) + 8  # Objects use the palettes present in the second half of CGRAM
        obj.priority = (data >> 4) & 0x03
        obj.h_flip = data & 0x40
        obj.v_flip = data & 0x80
