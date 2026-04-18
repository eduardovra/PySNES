import pathlib
from dataclasses import dataclass
from enum import IntEnum
from typing import Union

import cython
from rich import print


class MappingMode(IntEnum):
    TEST_PROGRAM = 0x00
    LOROM = 0x20
    HIROM = 0x21
    EXLOROM = 0x22
    SA1 = 0x23
    EXHIROM = 0x25
    LOROM_FAST = 0x30
    HIROM_FAST = 0x31
    EXLOROM_FAST = 0x32
    EXHIROM_FAST = 0x35


SUPPORTED_MAPPING_MODES = frozenset({
    MappingMode.TEST_PROGRAM,
    MappingMode.LOROM,
    MappingMode.LOROM_FAST,
})


class CartridgeType(IntEnum):
    ROM_ONLY = 0x00
    ROM_RAM = 0x01
    ROM_RAM_BATTERY = 0x02
    ROM_COPROCESSOR = 0x03
    ROM_COPROCESSOR_RAM = 0x04
    ROM_COPROCESSOR_RAM_BATTERY = 0x05
    ROM_SUPERFX = 0x13
    ROM_SUPERFX_RAM = 0x14
    ROM_SUPERFX_RAM_BATTERY = 0x15
    ROM_SA1_RAM = 0x34
    ROM_SA1_RAM_BATTERY = 0x35
    ROM_SDD1 = 0x43
    ROM_SDD1_RAM_BATTERY = 0x45


class Region(IntEnum):
    JAPAN = 0x00
    NORTH_AMERICA = 0x01
    EUROPE = 0x02
    SWEDEN = 0x03
    FINLAND = 0x04
    DENMARK = 0x05
    FRANCE = 0x06
    NETHERLANDS = 0x07
    SPAIN = 0x08
    GERMANY = 0x09
    ITALY = 0x0A
    CHINA = 0x0B
    INDONESIA = 0x0C
    SOUTH_KOREA = 0x0D
    CANADA = 0x0F
    BRAZIL = 0x10
    AUSTRALIA = 0x11


def _enum_or_int(cls: type[IntEnum], value: int) -> Union[IntEnum, int]:
    try:
        return cls(value)
    except ValueError:
        return value

# Scripts to convert SNES ROMs to SNES Classic (.sfrom) format and to read .sfrom headers
# https://gist.github.com/anpage/4834433944a2875ee6d4cbb5786c6bf7


@dataclass
@cython.cclass
class InterruptVectors:
    cop: int
    brk: int      # native-only; 0 in emulation
    abort: int
    nmi: int
    reset: int    # emulation-only; 0 in native
    irq: int      # in emulation this is IRQ/BRK


@dataclass
@cython.cclass
class HardwareVectors:
    native: InterruptVectors
    emulation: InterruptVectors


@dataclass
@cython.cclass
class SnesHeader:
    game_title: str
    mapping_mode: Union[MappingMode, int]
    cartridge_type: Union[CartridgeType, int]
    rom_size: int           # bytes; 0 if header byte is 0
    sram_size: int          # bytes; 0 if header byte is 0
    destination_code: Union[Region, int]   # $FFD9 — region, NOT developer ID
    version: int
    checksum_complement: int  # 16-bit LE
    checksum: int             # 16-bit LE


def _looks_like_title(buf) -> bool:
    return all(31 < b < 127 for b in buf)


def _looks_like_map_mode(byte: int, want_hirom: bool) -> bool:
    """Map mode bytes always have the top three bits = 001 ($20 base) and the
    low bit selects HiROM (1) vs LoROM (0)."""
    if (byte & 0xE0) != 0x20:
        return False
    return bool(byte & 0x01) == want_hirom


class Rom:
    rom: bytes

    def __init__(self, rom_file_path: str) -> None:
        self.rom_file_path = rom_file_path
        self.rom_file_name = pathlib.Path(rom_file_path).name
        self.load_rom_file()

    def __getitem__(self, addr: int) -> int:
        return self.rom[addr]

    def load_rom_file(self):
        """
        SFC and SMC files are usually identical. It's just a different choice in file extension.
        “SMC” comes from Super MagiCom, a floppy-based cart copying device for backup/piracy.
        The original .smc files produced by the device contained a 512 byte header.
        """
        self.rom = bytearray(0x400000)  # https://en.wikibooks.org/wiki/Super_NES_Programming/SNES_memory_map

        print(f"Loading ROM file: {self.rom_file_path!r}")
        with open(self.rom_file_path, "rb") as f:
            self.rom_file_contents = f.read()
            for i, b in enumerate(self.rom_file_contents):
                self.rom[i] = b

        # Strip out potential 512-byte SMC copier header
        self.smc_header_length = len(self.rom_file_contents) % 0x400
        self.rom = self.rom[self.smc_header_length :]

        page_offset = self._detect_page_offset()
        self.snes_header = self._parse_header(page_offset)
        self.sram_size = self.snes_header.sram_size

        assert self.snes_header.mapping_mode in SUPPORTED_MAPPING_MODES, (
            f"unsupported mapping mode {self.snes_header.mapping_mode:#04x} — "
            f"only LoROM ({MappingMode.LOROM:#04x}) and LoROM+FastROM "
            f"({MappingMode.LOROM_FAST:#04x}) are implemented"
        )

        print(self.snes_header)

        self.hardware_vectors = self._parse_vectors(page_offset)
        print(self.hardware_vectors)

    def _detect_page_offset(self) -> int:
        """Return $7F00 for LoROM or $FF00 for HiROM. Prefers a candidate whose
        $xxD5 map-mode byte is well-formed; falls back to ASCII-printability of
        the title; defaults to LoROM."""
        lo_title_ok = _looks_like_title(self.rom[0x7FC0 : 0x7FC0 + 21])
        hi_title_ok = _looks_like_title(self.rom[0xFFC0 : 0xFFC0 + 21])
        lo_mode_ok = _looks_like_map_mode(self.rom[0x7FD5], want_hirom=False)
        hi_mode_ok = _looks_like_map_mode(self.rom[0xFFD5], want_hirom=True)

        if hi_title_ok and hi_mode_ok and not lo_mode_ok:
            return 0xFF00
        if lo_title_ok and lo_mode_ok:
            return 0x7F00
        if hi_title_ok and hi_mode_ok:
            return 0xFF00
        if lo_title_ok:
            return 0x7F00
        if hi_title_ok:
            return 0xFF00
        return 0x7F00

    def _parse_header(self, page_offset: int) -> SnesHeader:
        rom = self.rom
        title_bytes = bytes(rom[page_offset + 0xC0 : page_offset + 0xC0 + 21])
        try:
            game_title = title_bytes.decode("ascii").rstrip()
        except UnicodeDecodeError:
            game_title = title_bytes.decode("ascii", errors="replace").rstrip()

        rom_size_byte = rom[page_offset + 0xD7]
        sram_size_byte = rom[page_offset + 0xD8]

        return SnesHeader(
            game_title=game_title,
            mapping_mode=_enum_or_int(MappingMode, rom[page_offset + 0xD5]),
            cartridge_type=_enum_or_int(CartridgeType, rom[page_offset + 0xD6]),
            rom_size=(0x400 << rom_size_byte) if rom_size_byte else 0,
            sram_size=min(0x400 << sram_size_byte, 0x20000) if sram_size_byte else 0,
            destination_code=_enum_or_int(Region, rom[page_offset + 0xD9]),
            version=rom[page_offset + 0xDB],
            checksum_complement=rom[page_offset + 0xDC] | rom[page_offset + 0xDD] << 8,
            checksum=rom[page_offset + 0xDE] | rom[page_offset + 0xDF] << 8,
        )

    def _parse_vectors(self, page_offset: int) -> HardwareVectors:
        """
        Hardware vectors (last 32 bytes of bank 0):

            Native Mode           6502 Emulation Mode
            -----------------------------------------
            COP   $FFE4-$FFE5     COP     $FFF4-$FFF5
            BRK   $FFE6-$FFE7
            ABORT $FFE8-$FFE9     ABORT   $FFF8-$FFF9
            NMI   $FFEA-$FFEB     NMI     $FFFA-$FFFB
                                  RESET   $FFFC-$FFFD
            IRQ   $FFEE-$FFEF     IRQ/BRK $FFFE-$FFFF
        """
        rom = self.rom
        word = lambda lo: rom[page_offset | lo] | rom[page_offset | (lo + 1)] << 8
        return HardwareVectors(
            native=InterruptVectors(
                cop=word(0xE4),
                brk=word(0xE6),
                abort=word(0xE8),
                nmi=word(0xEA),
                reset=0,
                irq=word(0xEE),
            ),
            emulation=InterruptVectors(
                cop=word(0xF4),
                brk=0,
                abort=word(0xF8),
                nmi=word(0xFA),
                reset=word(0xFC),
                irq=word(0xFE),
            ),
        )
