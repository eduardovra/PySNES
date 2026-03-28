import pathlib

from rich import print

# Scripts to convert SNES ROMs to SNES Classic (.sfrom) format and to read .sfrom headers
# https://gist.github.com/anpage/4834433944a2875ee6d4cbb5786c6bf7


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
            #self.rom = bytes(f.read())  # altered just for tests..

        # Strip out potential header
        self.smc_header_length = len(self.rom_file_contents) % 0x400
        self.rom = self.rom[self.smc_header_length :]
        rom_type = "LoROM"
        page_offset = 0x7F00

        # Look for the presence of ascii characters in the memory regions
        # to determine the right header offset

        # LoROM
        if len(self.rom) >= 0x7FFF and all(
            31 < char < 127 for char in self.rom[0x7FC0 : 0x7FC0 + 21]
        ):
            rom_type = "LoROM"
            page_offset = 0x7F00
        # HiROM
        if len(self.rom) >= 0xFFFF and all(
            31 < char < 127 for char in self.rom[0xFFC0 : 0xFFC0 + 21]
        ):
            rom_type = "HiROM"
            page_offset = 0xFF00

        # rom_type = "HiROM"
        # page_offset = 0xFF00

        # assert rom_type == "LoROM"
        #assert rom_type is not None

        # SNES header is located in the last 64 bytes of the first bank: 0x7FC0 - 0xFFFF
        self.snes_header = {
            "game_title": self.rom[
                page_offset + 0xC0 : page_offset + 0xC0 + 21
            ],  # 21 bytes, usually uppercase ASCII.
            "mapping_mode": self.rom[
                page_offset + 0xD5
            ],  # 001ABBBB; A==1 means FastROM ($10). If BBBB is the mapping mode.
            "rom_type": self.rom[
                page_offset + 0xD6
            ],  # Denotes that the cartridge contains expansion chips, SRAM, batteries, etc.
            "rom_size": 0x400 << self.rom[page_offset + 0xD7],
            "sram_size": 0x400 << self.rom[page_offset + 0xD8],
            "developer_id": self.rom[page_offset + 0xD9],
            "version": self.rom[page_offset + 0xDB],
            "checksum_complement": self.rom[page_offset + 0xDC],
            "checksum": self.rom[page_offset + 0xDE],
        }
        print(self.snes_header)

        # The bitmask to use is 001A0BCD, the basic value is $20:
        # - A == 0 means SlowROM (+ $0), A == 1 means FastROM (+ $10).
        # - B == 1 means ExHiROM (+ $4)
        # - C == 1 means ExLoROM (+ $2)
        # - D == 0 means LoROM (+ $0), D == 1 means HiROM (+ $1)
        # For super mario world A == 0 and D == 0, so it's SlowROM + LoROM
        assert self.snes_header["mapping_mode"] in (
            0x00,  # LoROM + SlowROM - SNES Test Program
            0x20,  # LoROM+SNES - For SMW
            0x30,  # LoROM + FastROM+SNES - For the test ROM
            0x31,  # HiROM + FastROM
        )

        """
        7.10 Hardware Vectors:
        ----------------------
            Native Mode           6502 Emulation Mode
            -----------------------------------------
            IRQ   $FFEE-$FFEF     IRQ/BRK $FFFE-$FFFF
                                  RESET   $FFFC-$FFFD
            NMI   $FFEA-$FFEB     NMI     $FFFA-$FFFB
            ABORT $FFE8-$FFE9     ABORT   $FFF8-$FFF9
            BRK   $FFE6-$FFE7
            COP   $FFE5-$FFE6     COP     $FFF4-$FFF5
        """

        # Interrupt vectors
        self.hardware_vectors = {
            "native": {
                "IRQ": self.rom[page_offset | 0xEE] | self.rom[page_offset | 0xEF] << 8,
                "NMI": self.rom[page_offset | 0xEA] | self.rom[page_offset | 0xEB] << 8,
                "ABORT": self.rom[page_offset | 0xE8]
                | self.rom[page_offset | 0xE9] << 8,
                "BRK": self.rom[page_offset | 0xE6] | self.rom[page_offset | 0xE7] << 8,
                "COP": self.rom[page_offset | 0xE5] | self.rom[page_offset | 0xE6] << 8,
            },
            "emulation": {
                "IRQ/BRK": self.rom[page_offset | 0xEE]
                | self.rom[page_offset | 0xEF] << 8,
                "RESET": self.rom[page_offset | 0xFC]
                | self.rom[page_offset | 0xFD] << 8,
                "NMI": self.rom[page_offset | 0xFA] | self.rom[page_offset | 0xFB] << 8,
                "ABORT": self.rom[page_offset | 0xF8]
                | self.rom[page_offset | 0xF9] << 8,
                "COP": self.rom[page_offset | 0xF4] | self.rom[page_offset | 0xF5] << 8,
            },
        }

        hardware_vectors_str = {
            "emulation": {k: hex(v) for k, v in self.hardware_vectors["emulation"].items()},
            "native": {k: hex(v) for k, v in self.hardware_vectors["native"].items()},
        }
        print(hardware_vectors_str)
