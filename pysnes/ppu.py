from ctypes import c_uint8, byref
from typing import Optional
from dataclasses import dataclass

from sdl2 import (
    SDL_CreateWindow,
    SDL_CreateRenderer,
    SDL_INIT_VIDEO,
    SDL_WINDOW_SHOWN,
    SDL_RENDERER_ACCELERATED,
    SDL_Event,
    SDL_PollEvent,
    SDL_QUIT,
    SDL_Init,
    SDL_Quit,
    SDL_DestroyRenderer,
    SDL_RenderClear,
    SDL_SetRenderDrawColor,
    SDL_DestroyWindow,
    SDL_RenderDrawPoint,
    SDL_RenderPresent,
)


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
        # VRAM - Video RAM
        if vram_dump is None:
            self.vram = bytearray(64 * 1024)
        else:
            self.vram = bytearray(vram_dump)
        self.vmain = 0x00
        self.vmaddl = c_uint8(0x00)
        self.vmaddh = c_uint8(0x00)

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

        # Background
        self.bgmode = 0x00
        self.bgnsc = [Background()] * 4

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
        if self.vmain_addr_increment_mode:
            self.write_vram(data)

    @property
    def vmdatah(self) -> int:
        return self._vmdatah.value

    @vmdatah.setter
    def vmdatah(self, data: int) -> None:
        self._vmdatah = c_uint8(data)
        if not self.vmain_addr_increment_mode:
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
        if self._oamadd & 0x100:
            return 0x200 | self._oamadd & 0x1F
        else:
            return (self._oamadd * 2) + self._oamodd

    def oam_next(self) -> None:
        self._oamodd ^= 1
        if self._oamodd == 0:
            self._oamadd = (self._oamadd + 1) & 0x1FF

    def bgnsc_set(self, n: int, data: int) -> None:
        self.bgnsc[n - 1].screen_size = data & 0x03
        self.bgnsc[n - 1].screen_addr = data >> 2 << 10  # Copied from bsnes

    def bg12nba_set(self, data: int) -> None:
        self.bgnsc[0].tiledata_addr = (data >> 0 & 15) << 12
        self.bgnsc[1].tiledata_addr = (data >> 4 & 15) << 12

    def bg34nba_set(self, data: int) -> None:
        self.bgnsc[2].tiledata_addr = (data >> 0 & 15) << 12
        self.bgnsc[3].tiledata_addr = (data >> 4 & 15) << 12

    def render(self) -> None:
        # Initialization
        SDL_Init(SDL_INIT_VIDEO)
        window = SDL_CreateWindow(b"PPU", 0, 0, 1024, 1024, SDL_WINDOW_SHOWN)
        renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED)
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 0)
        SDL_RenderClear(renderer)

        # Draw picture
        SDL_SetRenderDrawColor(renderer, 255, 0, 0, 255)
        # Draw BG1, Mode 0 - test_oam.smc
        # Bit Depth 2bpp
        # Map Size 32x32
        # Map Addr 0x0000 (comes from BG1SC)
        # Tile Size 8x8
        # Tile Addr 0x2000
        x_offset, y_offset = 0, 0
        for line in range(0x0000, 0x0800, 0x10):
            for col in range(0x00, 0x10, 0x02):
                # print(f"MAP Line: {hex(line)} Column: {hex(col)}")
                # Parse Tilemap entry - 2 bytes
                entry_addr = line + col
                low = self.vram[entry_addr + 0]
                high = self.vram[entry_addr + 1]
                palette = (high >> 2) & 7
                priotity = (high >> 5) & 1
                h_flip = (high >> 6) & 1
                v_flip = (high >> 7) & 1
                addr = high & 3 | low
                print(
                    f"[{hex(entry_addr)}] ADDR {hex(addr)} PALETTE {palette} "
                    f"PRIO {priotity} H_FLIP {h_flip} V_FLIP {v_flip}"
                )

                # Fetch Tile (character) - 16 bytes
                # bg = self.bgnsc[0]
                # tile_addr = bg.tiledata_addr + (addr * 16)
                tiledata_addr = 0x2000
                tile_addr = tiledata_addr + (addr * 16)
                # 16 bytes --> 8x8 pixels * 2bpp
                tile_data = self.vram[tile_addr : tile_addr + 16]
                print(" ".join(hex(t) for t in tile_data))

                x, y = x_offset, y_offset
                for i in range(0, 16, 2):
                    # Each byte is 4 pixels
                    # Each line is 8 pixels

                    # Bitplane handling
                    # The first byte is composed of the first
                    # 8 least significant bits of the pixel
                    # and the second byte if composed of the
                    # 8 most significant bits
                    color = 0
                    a = tile_data[i + 0]
                    b = tile_data[i + 1]
                    # a = 0x7C
                    # b = 0x00

                    pixel0 = (b & 0x80) >> 7 << 1 | (a & 0x80) >> 7 << 0
                    if pixel0:
                        SDL_RenderDrawPoint(renderer, x, y)
                    x += 1
                    pixel1 = (b & 0x40) >> 6 << 1 | (a & 0x40) >> 6 << 0
                    if pixel1:
                        SDL_RenderDrawPoint(renderer, x, y)
                    x += 1
                    pixel2 = (b & 0x20) >> 5 << 1 | (a & 0x20) >> 5 << 0
                    if pixel2:
                        SDL_RenderDrawPoint(renderer, x, y)
                    x += 1
                    pixel3 = (b & 0x10) >> 4 << 1 | (a & 0x10) >> 4 << 0
                    if pixel3:
                        SDL_RenderDrawPoint(renderer, x, y)
                    x += 1
                    pixel4 = (b & 0x08) >> 3 << 1 | (a & 0x08) >> 3 << 0
                    if pixel4:
                        SDL_RenderDrawPoint(renderer, x, y)
                    x += 1
                    pixel5 = (b & 0x04) >> 2 << 1 | (a & 0x04) >> 2 << 0
                    if pixel5:
                        SDL_RenderDrawPoint(renderer, x, y)
                    x += 1
                    pixel6 = (b & 0x02) >> 1 << 1 | (a & 0x02) >> 1 << 0
                    if pixel6:
                        SDL_RenderDrawPoint(renderer, x, y)
                    x += 1
                    pixel7 = (b & 0x01) >> 0 << 1 | (a & 0x01) >> 0 << 0
                    if pixel7:
                        SDL_RenderDrawPoint(renderer, x, y)
                    x += 1

                    x = x_offset
                    y += 1

                # break  # col loop
                x_offset += 8
                if x_offset == 8 * 32:  # 32 tiles with 8 pixels width
                    x_offset = 0
            # break  # line loop
            y_offset += 8

        SDL_RenderPresent(renderer)

        # Loop
        running = True
        event = SDL_Event()
        while running:
            while SDL_PollEvent(byref(event)) != 0:
                if event.type == SDL_QUIT:
                    running = False
                    break

        # Housekeeping
        SDL_DestroyRenderer(renderer)
        SDL_DestroyWindow(window)
        SDL_Quit()


@dataclass
class Background:
    screen_size = 0
    screen_addr = 0
    tiledata_addr = 0


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


class OAM:
    def __init__(self, *, oam_dump: Optional[bytes] = None) -> None:
        # Object Attribute Memory
        if oam_dump is None:
            self.oam = bytearray(512 + 32)
        else:
            self.oam = bytearray(oam_dump)
        self.objects = [Object()] * 128

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
            sx = data >> obj_index
            obj.x = (obj.x & 0xFF) | (sx & 0x01) << 8
            obj.size = bool(sx & 0x02)

    def update_low_table(self, addr: int) -> None:
        obj_num = addr // 4
        obj = self.objects[obj_num]

        data = self.oam[addr + 0]
        obj.x = obj.x & 0x100 | data & 0xFF

        data = self.oam[addr + 1]
        obj.y = data & 0xFF

        data = self.oam[addr + 2]
        obj.character = data & 0xFF

        data = self.oam[addr + 3]
        obj.name_select = bool(data & 0x01)
        obj.palette = (data >> 1) & 0x07
        obj.priority = (data >> 4) & 0x03
        obj.h_flip = bool(data & 0x40)
        obj.v_flip = bool(data & 0x80)


def main():
    # Memory dumps
    vram_file = "roms/test_oam-vram.bin"
    cgram_file = "roms/test_oam-cgram.bin"
    oam_file = "roms/test_oam-oam.bin"
    with open(vram_file, "rb") as f:
        vram_dump = f.read()
    with open(cgram_file, "rb") as f:
        cgram_dump = f.read()
    with open(oam_file, "rb") as f:
        oam_dump = f.read()
    ppu = Ppu(vram_dump=vram_dump, cgram_dump=cgram_dump, oam_dump=oam_dump)
    ppu.render()


if __name__ == "__main__":
    import cProfile

    # cProfile.run("main()", sort="cumulative")
    main()
