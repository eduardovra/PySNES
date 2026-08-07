HEADER_MAGIC = b"SNES-SPC700 Sound File Data v0.30\x1a\x1a"

_HAS_ID666 = 0x1A
_NO_ID666 = 0x1B


class SpcFile:
    """Parse a .spc file (v0.30 format) and expose its state fields."""

    def __init__(self, path: str) -> None:
        with open(path, "rb") as f:
            data = f.read()

        if len(data) < 0x10200:
            raise ValueError(
                f"SPC file too short: {len(data)} bytes (expected >= 0x10200)"
            )
        if not data.startswith(HEADER_MAGIC):
            raise ValueError("Not a valid SPC file (bad magic bytes)")

        self.has_id666 = data[0x23] == _HAS_ID666

        self.pc = data[0x25] | (data[0x26] << 8)
        self.a = data[0x27]
        self.x = data[0x28]
        self.y = data[0x29]
        self.psw = data[0x2A]
        self.sp = data[0x2B]

        if self.has_id666:
            # Text-format ID666 tag: 0x2E-0xAD
            def _str(b):
                return (
                    b.split(b"\x00", 1)[0]
                    .decode("ascii", errors="replace")
                    .strip()
                )

            self.song_name = _str(data[0x2E:0x4E])  # 32 bytes
            self.game_name = _str(data[0x4E:0x6E])  # 32 bytes
            self.artist_name = _str(data[0x6E:0x8E])  # 32 bytes
        else:
            self.song_name = self.game_name = self.artist_name = ""

        self.ram = data[0x100:0x10100]  # 64 KB SPC700 RAM
        self.dsp_regs = data[0x10100:0x10180]  # 128 DSP registers
        # Extra RAM overlays the IPL ROM area 0xFFC0-0xFFFF
        self.extra_ram = data[0x101C0:0x10200]  # 64 bytes
