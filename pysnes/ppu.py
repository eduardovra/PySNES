from ctypes import c_uint16, c_uint8
from typing import Optional


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
        self.cgadd = c_uint8(0x00)
        self.cgdata: Optional[c_uint8] = None
        self.cgdataread: Optional[c_uint8] = None

        # OAM
        self.oam = bytearray(512 + 32)  # Object Attribute Memory
        self.oamaddl = c_uint8(0x00)
        self.oamaddh = c_uint8(0x00)
        self._oamdata: Optional[c_uint8] = None

    @property
    def vmain(self) -> int:
        return self._vmain.value

    @vmain.setter
    def vmain(self, data: int) -> None:
        self._vmain = c_uint8(data)
        self.vmain_addr_increment_mode = data >> 7
        self.vmain_addr_increment_amount = data & 0x03
        self.vmain_addr_remapping = (data >> 2) & 0x03
        assert self.vmain_addr_increment_amount == 0
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
        amounts = (1, 32, 128, 128)
        increment_amount = amounts[self.vmain_addr_increment_amount]
        addr = (self.vmaddl.value | self.vmaddh.value << 8) + increment_amount
        self.vmaddl.value = (addr >> 0) & 0xFF
        self.vmaddh.value = (addr >> 8) & 0xFF

    @property
    def oamdata(self) -> int:
        return 0  # TODO

    @oamdata.setter
    def oamdata(self, data: int) -> None:
        # The highiest bit of oamaddh contains a priority that
        # I still don't know what to do with
        addr = self.oamaddl.value | (self.oamaddh.value << 8) & 0x7F
        if addr < 512:  # Low table
            # Write only after high byte is received
            if self._oamdata is None:
                self._oamdata = c_uint8(data)
                return
            self.oam[addr + 0] = self._oamdata.value
            self.oam[addr + 1] = data
            self._oamdata = None
            addr += 2
        else:  # High table
            # Write immediately
            self.oam[addr] = data
            addr += 1

        self.oamaddl.value = (addr >> 0) & 0xFF
        self.oamaddh.value = (addr >> 8) & 0xFF
