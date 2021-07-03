class Rom:
    rom: bytes

    def __init__(self, rom_file_path: str) -> None:
        self.rom_file_path = rom_file_path
        self.load_rom_file()

    def __getitem__(self, addr: int) -> int:
        return self.rom[addr]

    def load_rom_file(self):
        with open(self.rom_file_path, "rb") as f:
            self.rom = f.read()

        # Strip out potential header
        self.smc_header_length = len(self.rom) % 0x400
        self.rom = self.rom[self.smc_header_length :]

        rom_type = None

        # Look for the presence of ascii characters in the memory regions
        # to determine the right header offset

        # LoROM
        if all(31 < char < 127 for char in self.rom[0x7FC0 : 0x7FC0 + 21]):
            rom_type = "LoROM"
        # HiROM
        if all(31 < char < 127 for char in self.rom[0xFFC0 : 0xFFC0 + 21]):
            rom_type = "HiROM"

        assert rom_type == "LoROM"

        # SNES header is located in the last 64 bytes of the first bank: 0x7FC0 - 0xFFFF
        self.snes_header = {
            "game_title": self.rom[
                0x7FC0 : 0x7FC0 + 21
            ],  # 21 bytes, usually uppercase ASCII.
            "mapping_mode": self.rom[
                0x7FD5
            ],  # 001ABBBB; A==1 means FastROM ($10). If BBBB is the mapping mode.
            "rom_type": self.rom[
                0x7FD6
            ],  # Denotes that the cartridge contains expansion chips, SRAM, batteries, etc.
            "rom_size": 0x400 << self.rom[0x7FD7],
            "sram_size": 0x400 << self.rom[0x7FD8],
            "developer_id": self.rom[0x7FD9],
            "version": self.rom[0x7FDB],
            "checksum_complement": self.rom[0x7FDC],
            "checksum": self.rom[0x7FDE],
        }

        print(f"{self.snes_header=}")

        # The bitmask to use is 001A0BCD, the basic value is $20:
        # - A == 0 means SlowROM (+ $0), A == 1 means FastROM (+ $10).
        # - B == 1 means ExHiROM (+ $4)
        # - C == 1 means ExLoROM (+ $2)
        # - D == 0 means LoROM (+ $0), D == 1 means HiROM (+ $1)
        # For super mario world A == 0 and D == 0, so it's SlowROM + LoROM
        assert self.snes_header["mapping_mode"] == 0x20  # LoROM+SNES
