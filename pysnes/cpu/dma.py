from typing import TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from ...bus import Bus

# Number of data bytes consumed per transfer unit for each HDMA/DMA mode.
_HDMA_UNIT_BYTES = [1, 2, 2, 4, 4, 4, 2, 4]

# Register offset written per byte within a unit for each transfer mode.
# Each sublist has one entry per byte in the unit.
_HDMA_TARGET_OFFSETS = [
    [0],          # mode 0: 1 byte → $21xx
    [0, 1],       # mode 1: 2 bytes → $21xx, $21xx+1
    [0, 0],       # mode 2: 2 bytes → $21xx, $21xx
    [0, 0, 1, 1], # mode 3: 4 bytes → $21xx×2, $21xx+1×2
    [0, 1, 2, 3], # mode 4: 4 bytes → $21xx, $21xx+1, $21xx+2, $21xx+3
    [0, 1, 0, 1], # mode 5: 4 bytes → $21xx, $21xx+1 ×2
    [0, 0],       # mode 6: same as 2
    [0, 0, 1, 1], # mode 7: same as 3
]


@dataclass
class Channel:
    bus: "Bus"
    transfer_mode: int = 0
    fixed_transfer: int = 0
    reverse_transfer: int = 0
    unused: int = 0
    indirect: int = 0
    direction: int = 0
    target_address: int = 0
    source_address: int = 0
    source_bank: int = 0
    transfer_size: int = 0
    indirect_bank: int = 0
    hdma_address: int = 0
    line_counter: int = 0
    unknown: int = 0
    hdma_enable: int = 0

    # HDMA execution state (reset each frame by hdma_init)
    _hdma_ptr: int = 0      # current byte offset (within bank) in the HDMA table
    _hdma_bank: int = 0     # bank of the HDMA table (= source_bank for non-indirect)
    _hdma_count: int = 0    # remaining scanlines for current table entry
    _hdma_repeat: bool = False  # True = reuse same data bytes; False = fresh per scanline
    _hdma_data: int = 0     # byte offset of the data bytes for the current entry
    _hdma_active: bool = False  # False once end-of-table (count=0) is reached

    def do_transfer(self) -> None:
        # Transfer byte count: register value, with 0 meaning 65536 (hardware quirk).
        count = self.transfer_size if self.transfer_size else 0x10000
        offsets = _HDMA_TARGET_OFFSETS[self.transfer_mode]
        unit_len = len(offsets)
        # A-bus step: +1, -1, or 0 depending on fixed/reverse flags.
        if self.fixed_transfer:
            step = 0
        else:
            step = -1 if self.reverse_transfer else 1

        for index in range(count):
            a_bus_addr = (self.source_bank << 16) | self.source_address
            b_bus_addr = 0x2100 | ((self.target_address + offsets[index % unit_len]) & 0xFF)

            if self.direction == 0:
                # A bus → B bus (CPU/ROM/RAM → PPU)
                self.bus.write(b_bus_addr, self.bus.read(a_bus_addr))
            else:
                # B bus → A bus (PPU → CPU/RAM)
                self.bus.write(a_bus_addr, self.bus.read(b_bus_addr))

            # A-bus address increments within the bank (16-bit wrap; does not
            # carry into source_bank on real hardware).
            self.source_address = (self.source_address + step) & 0xFFFF


class DMA:
    def __init__(self, bus: "Bus") -> None:
        # Create 8 DMA channels
        self.channels = [Channel(bus) for _ in range(8)]

    def __setitem__(self, abs_addr: int, data: int) -> None:
        channel = self.channels[abs_addr >> 4 & 7]
        addr = abs_addr & 0xFF8F

        if addr == 0x4300:  # DMAPx
            channel.transfer_mode = data >> 0 & 7
            channel.fixed_transfer = data >> 3 & 1
            channel.reverse_transfer = data >> 4 & 1
            channel.unused = data >> 5 & 1
            channel.indirect = data >> 6 & 1
            channel.direction = data >> 7 & 1
            return

        if addr == 0x4301:  # BBADx
            channel.target_address = data
            return

        if addr == 0x4302:  # A1TxL
            channel.source_address = channel.source_address & 0xFF00 | data << 0
            return

        if addr == 0x4303:  # A1TxH
            channel.source_address = channel.source_address & 0x00FF | data << 8
            return

        if addr == 0x4304:  # A1Bx
            channel.source_bank = data
            return

        if addr == 0x4305:  # DASxL
            channel.transfer_size = channel.transfer_size & 0xFF00 | data << 0
            return

        if addr == 0x4306:  # DASxH
            channel.transfer_size = channel.transfer_size & 0x00FF | data << 8
            return

        if addr == 0x4307:  # DASBx
            channel.indirect_bank = data
            return

        if addr == 0x4308:  # A2AxL
            channel.hdma_address = channel.hdma_address & 0xFF00 | data << 0
            return

        if addr == 0x4309:  # A2AxH
            channel.hdma_address = channel.hdma_address & 0x00FF | data << 8
            return

        if addr == 0x430A:  # NTRLx
            channel.line_counter = data
            return

        if addr == 0x430B:  # ???x
            channel.unknown = data
            return

        if addr == 0x430F:  # ???x ($43xb mirror)
            channel.unknown = data
            return

        # $43xC-$43xE are unused/open-bus on real hardware; writes are ignored.
        # Anything else in this mirrored range is treated the same way rather
        # than crashing the emulator on stray writes (e.g. when a game's stack
        # drifts into the DMA register page).
        return

    def mdmaen_set(self, data: int) -> None:
        for enable_bit, channel in enumerate(self.channels):
            if data & (1 << enable_bit):
                channel.do_transfer()

    def hdmaen_set(self, data: int) -> None:
        for enable_bit, channel in enumerate(self.channels):
            channel.hdma_enable = data & (1 << enable_bit)

    def hdma_init(self) -> None:
        """Initialize all HDMA-enabled channels at the start of each frame.

        Reads the first count byte from each channel's table and sets up the
        execution state for the frame.
        """
        for ch in self.channels:
            if not ch.hdma_enable:
                ch._hdma_active = False
                continue
            ch._hdma_ptr = ch.source_address
            ch._hdma_bank = ch.source_bank
            self._load_next_entry(ch)

    def _load_next_entry(self, ch: "Channel") -> None:
        """Read the next count byte from the table and update channel state.

        Bit 7 of the count byte is the "do-repeat" flag:
          bit 7 = 0 (do-not-repeat): the SAME data unit is reused every scanline.
          bit 7 = 1 (do-repeat):     FRESH data is read each scanline.

        In direct mode (DMAPx bit 6 = 0), the data bytes follow the count byte
        inline in the table. In indirect mode (bit 6 = 1), the 2 bytes after the
        count byte are a pointer into `indirect_bank:ptr` where the actual data
        lives. Either way, _hdma_ptr is advanced to the NEXT entry's count byte
        here; for direct+repeat, hdma_scanline() advances _hdma_data per
        scanline and re-syncs _hdma_ptr when the entry is exhausted.
        """
        count = ch.bus.read(ch._hdma_bank << 16 | ch._hdma_ptr)
        ch._hdma_ptr = (ch._hdma_ptr + 1) & 0xFFFF
        if count == 0:
            ch._hdma_active = False
            return
        ch._hdma_active = True
        ch._hdma_count = count & 0x7F
        ch._hdma_repeat = bool(count & 0x80)

        if ch.indirect:
            lo = ch.bus.read(ch._hdma_bank << 16 | ch._hdma_ptr)
            hi = ch.bus.read(ch._hdma_bank << 16 | ((ch._hdma_ptr + 1) & 0xFFFF))
            ch.transfer_size = (hi << 8) | lo
            ch._hdma_ptr = (ch._hdma_ptr + 2) & 0xFFFF
            ch._hdma_data = ch.transfer_size
        else:
            ch._hdma_data = ch._hdma_ptr
            unit_bytes = _HDMA_UNIT_BYTES[ch.transfer_mode & 7]
            if not ch._hdma_repeat:
                ch._hdma_ptr = (ch._hdma_ptr + unit_bytes) & 0xFFFF

    def hdma_scanline(self) -> None:
        """Execute HDMA for one H-blank (called once per active scanline)."""
        for ch in self.channels:
            if not ch.hdma_enable or not ch._hdma_active:
                continue

            mode = ch.transfer_mode & 7
            unit_bytes = _HDMA_UNIT_BYTES[mode]
            offsets = _HDMA_TARGET_OFFSETS[mode]

            data_bank = ch.indirect_bank if ch.indirect else ch._hdma_bank

            for i in range(unit_bytes):
                byte = ch.bus.read((data_bank << 16) | ((ch._hdma_data + i) & 0xFFFF))
                ch.bus.write(0x2100 | ((ch.target_address + offsets[i]) & 0xFF), byte)

            if ch._hdma_repeat:
                ch._hdma_data = (ch._hdma_data + unit_bytes) & 0xFFFF
                if ch.indirect:
                    ch.transfer_size = ch._hdma_data

            ch._hdma_count -= 1
            if ch._hdma_count == 0:
                if ch._hdma_repeat and not ch.indirect:
                    # Sync _hdma_ptr to where _hdma_data now sits (next entry)
                    ch._hdma_ptr = ch._hdma_data
                self._load_next_entry(ch)
