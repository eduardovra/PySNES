from ctypes import c_uint8, byref
from typing import Optional

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

    def __init__(self) -> None:
        # VRAM
        self.vram = bytearray(64 * 1024)  # Video RAM
        self.vmain = c_uint8(0x00).value
        self.vmaddl = c_uint8(0x00)
        self.vmaddh = c_uint8(0x00)
        # self.vmdatal = c_uint8(0x00).value
        # self.vmdatah = c_uint8(0x00).value

        # CGRAM
        self.cgram = bytearray(512)  # Palette Data
        self._cgadd = c_uint8(0x00)
        self._cgdata: Optional[c_uint8] = None
        # self._cgdataread: Optional[c_uint8] = None

        # OAM
        self.oam = bytearray(512 + 32)  # Object Attribute Memory
        # self.oamaddl = c_uint8(0x00)
        # self.oamaddh = c_uint8(0x00)
        self._oamadd = 0
        self._oamodd = 0
        self._oamdata = 0

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
        # self._oamdata = None

    @property
    def oamaddh(self) -> int:
        raise NotImplementedError

    @oamaddh.setter
    def oamaddh(self, data: int) -> None:
        self._oam_priority_activation = bool(data & 0x80)
        self._oamadd = (self._oamadd & 0x0FF) | (data & 1) << 8
        self._oamodd = 0
        # self._oamdata = None

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

    def render(self) -> None:
        # Initialization
        SDL_Init(SDL_INIT_VIDEO)
        window = SDL_CreateWindow(b"Eduardo", 0, 0, 320, 240, SDL_WINDOW_SHOWN)
        renderer = SDL_CreateRenderer(window, -1, SDL_RENDERER_ACCELERATED)
        SDL_SetRenderDrawColor(renderer, 0, 0, 0, 0)
        SDL_RenderClear(renderer)

        # Draw picture
        SDL_SetRenderDrawColor(renderer, 255, 0, 0, 255)
        for i in range(240):
            SDL_RenderDrawPoint(renderer, i, i)
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
