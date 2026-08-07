from typing import TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from ..bus import Bus

# Number of data bytes consumed per transfer unit for each HDMA/DMA mode.
_HDMA_UNIT_BYTES = [1, 2, 2, 4, 4, 4, 2, 4]

# Register offset written per byte within a unit for each transfer mode.
# Each sublist has one entry per byte in the unit.
_HDMA_TARGET_OFFSETS = [
    [0],  # mode 0: 1 byte → $21xx
    [0, 1],  # mode 1: 2 bytes → $21xx, $21xx+1
    [0, 0],  # mode 2: 2 bytes → $21xx, $21xx
    [0, 0, 1, 1],  # mode 3: 4 bytes → $21xx×2, $21xx+1×2
    [0, 1, 2, 3],  # mode 4: 4 bytes → $21xx, $21xx+1, $21xx+2, $21xx+3
    [0, 1, 0, 1],  # mode 5: 4 bytes → $21xx, $21xx+1 ×2
    [0, 0],  # mode 6: same as 2
    [0, 0, 1, 1],  # mode 7: same as 3
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

    # HDMA execution state — matches Mesen's HdmaLineCounterAndRepeat model.
    #
    # _hdma_ptr: unified table address (HdmaTableAddress in Mesen).
    #   In direct mode this pointer advances through both the data bytes and
    #   the count bytes; after the last transfer of an entry it points at the
    #   NEXT entry's count byte.  In indirect mode it tracks the count/address
    #   bytes; the actual data is accessed via transfer_size in indirect_bank.
    #
    # _hdma_line_counter_repeat: the raw count byte currently loaded.
    #   bits 6:0 = line counter (0 → 128 scanlines).
    #   bit  7   = "do-transfer" flag for each scanline while it remains set.
    #   The byte is decremented as a whole unit each scanline; DoTransfer for
    #   the NEXT scanline is taken from bit7 of the result.  The entry ends
    #   when bits 6:0 reach zero.
    #
    # _hdma_do_transfer: whether to transfer data on the CURRENT scanline.
    #   Set True at the start of every entry (including frame init).
    #   Updated to (decremented_counter & 0x80) != 0 after each scanline.
    _hdma_ptr: int = 0
    _hdma_bank: int = 0
    _hdma_line_counter_repeat: int = 0
    _hdma_do_transfer: bool = False
    _hdma_active: bool = False

    _STATE_FIELDS = (
        "transfer_mode",
        "fixed_transfer",
        "reverse_transfer",
        "unused",
        "indirect",
        "direction",
        "target_address",
        "source_address",
        "source_bank",
        "transfer_size",
        "indirect_bank",
        "hdma_address",
        "line_counter",
        "unknown",
        "hdma_enable",
        "_hdma_ptr",
        "_hdma_bank",
        "_hdma_line_counter_repeat",
        "_hdma_do_transfer",
        "_hdma_active",
    )

    def dump_state(self) -> dict:
        return {f: getattr(self, f) for f in self._STATE_FIELDS}

    def load_state(self, d: dict) -> None:
        for f in self._STATE_FIELDS:
            setattr(self, f, d[f])

    def do_transfer(self) -> None:
        # On real hardware each GDMA byte costs 8 master-clock cycles and the
        # CPU is halted for the duration.  Per-channel overhead (8 MC bus-lock +
        # 8 MC arbitration + 8 MC bus-unlock) is included via the +24 constant.
        count = self.transfer_size if self.transfer_size else 0x10000
        offsets = _HDMA_TARGET_OFFSETS[self.transfer_mode]
        unit_len = len(offsets)
        if self.fixed_transfer:
            step = 0
        else:
            step = -1 if self.reverse_transfer else 1

        for index in range(count):
            a_bus_addr = (self.source_bank << 16) | self.source_address
            b_bus_addr = 0x2100 | (
                (self.target_address + offsets[index % unit_len]) & 0xFF
            )

            if self.direction == 0:
                self.bus.write(b_bus_addr, self.bus.read(a_bus_addr))
            else:
                self.bus.write(a_bus_addr, self.bus.read(b_bus_addr))

            self.source_address = (self.source_address + step) & 0xFFFF

        # Advance master_clock by the DMA cost: 8 MC/byte + 24 MC per-channel
        # overhead.  Also sync _last_refresh_scanline so the CPU's post-DMA
        # DRAM refresh check doesn't add a spurious 40 MC penalty.
        self.bus.scheduler.master_clock += count * 8 + 24
        self.bus.cpu._last_refresh_scanline = (
            self.bus.scheduler.master_clock // 1364
        )


class DMA:
    def __init__(self, bus: "Bus") -> None:
        self.channels = [Channel(bus) for _ in range(8)]

    def dump_state(self) -> dict:
        return {"channels": [ch.dump_state() for ch in self.channels]}

    def load_state(self, d: dict) -> None:
        for ch, cs in zip(self.channels, d["channels"]):
            ch.load_state(cs)

    def write(self, abs_addr: int, data: int) -> None:
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
        return

    def read(self, abs_addr: int) -> int:
        channel = self.channels[abs_addr >> 4 & 7]
        addr = abs_addr & 0xFF8F

        if addr == 0x4300:  # DMAPx
            return (
                (channel.transfer_mode & 7)
                | ((channel.fixed_transfer & 1) << 3)
                | ((channel.reverse_transfer & 1) << 4)
                | ((channel.unused & 1) << 5)
                | ((channel.indirect & 1) << 6)
                | ((channel.direction & 1) << 7)
            )
        if addr == 0x4301:
            return channel.target_address & 0xFF
        if addr == 0x4302:
            return channel.source_address & 0xFF
        if addr == 0x4303:
            return (channel.source_address >> 8) & 0xFF
        if addr == 0x4304:
            return channel.source_bank & 0xFF
        if addr == 0x4305:
            return channel.transfer_size & 0xFF
        if addr == 0x4306:
            return (channel.transfer_size >> 8) & 0xFF
        if addr == 0x4307:
            return channel.indirect_bank & 0xFF
        if addr == 0x4308:
            return channel.hdma_address & 0xFF
        if addr == 0x4309:
            return (channel.hdma_address >> 8) & 0xFF
        if addr == 0x430A:
            return channel.line_counter & 0xFF
        if addr == 0x430B or addr == 0x430F:
            return channel.unknown & 0xFF
        return 0

    def mdmaen_set(self, data: int) -> None:
        for enable_bit, channel in enumerate(self.channels):
            if data & (1 << enable_bit):
                channel.do_transfer()

    def hdmaen_set(self, data: int) -> None:
        for enable_bit, channel in enumerate(self.channels):
            channel.hdma_enable = data & (1 << enable_bit)

    def hdma_init(self) -> None:
        """Initialize all HDMA-enabled channels at the start of each frame.

        TODO: DMA/HDMA timing — cycle counts for DMA transfers and HDMA setup are
        not deducted from the CPU cycle budget; games that rely on precise DMA
        timing (e.g. mid-frame HDMA effects that depend on cycle-accurate firing)
        may render incorrectly.
        """
        for ch in self.channels:
            if not ch.hdma_enable:
                ch._hdma_active = False
                continue
            ch._hdma_do_transfer = True
            ch._hdma_ptr = ch.source_address
            ch._hdma_bank = ch.source_bank
            self._load_entry(ch)

    def _load_entry(self, ch: "Channel") -> None:
        """Read the count byte at _hdma_ptr and set up channel state for the entry."""
        count = ch.bus.read(ch._hdma_bank << 16 | ch._hdma_ptr)
        ch._hdma_ptr = (ch._hdma_ptr + 1) & 0xFFFF
        if count == 0:
            ch._hdma_active = False
            return
        ch._hdma_active = True
        ch._hdma_line_counter_repeat = count
        ch._hdma_do_transfer = True

        if ch.indirect:
            lo = ch.bus.read(ch._hdma_bank << 16 | ch._hdma_ptr)
            hi = ch.bus.read(
                ch._hdma_bank << 16 | ((ch._hdma_ptr + 1) & 0xFFFF)
            )
            ch.transfer_size = (hi << 8) | lo
            ch._hdma_ptr = (ch._hdma_ptr + 2) & 0xFFFF

    def hdma_scanline(self) -> None:
        """Execute HDMA for one H-blank (called once per active scanline).

        Matches Mesen's SnesDmaController::RunHdma algorithm:
          1. Transfer data if _hdma_do_transfer is set.
             In direct mode the table pointer (_hdma_ptr) advances past the
             data bytes on each transfer, so it always points at the next
             count byte when the line counter expires.
          2. Decrement _hdma_line_counter_repeat as a whole byte.
          3. Set _hdma_do_transfer from bit 7 of the decremented counter.
          4. When bits 6:0 reach zero, load the next table entry.
        """
        for ch in self.channels:
            if not ch.hdma_enable or not ch._hdma_active:
                continue

            mode = ch.transfer_mode & 7
            unit_bytes = _HDMA_UNIT_BYTES[mode]
            offsets = _HDMA_TARGET_OFFSETS[mode]
            data_bank = ch.indirect_bank if ch.indirect else ch._hdma_bank

            # Step 1: transfer data for this scanline.
            if ch._hdma_do_transfer:
                if ch.indirect:
                    for i in range(unit_bytes):
                        byte = ch.bus.read(
                            (data_bank << 16)
                            | ((ch.transfer_size + i) & 0xFFFF)
                        )
                        ch.bus.write(
                            0x2100 | ((ch.target_address + offsets[i]) & 0xFF),
                            byte,
                        )
                    ch.transfer_size = (ch.transfer_size + unit_bytes) & 0xFFFF
                else:
                    for i in range(unit_bytes):
                        byte = ch.bus.read(
                            (data_bank << 16) | ((ch._hdma_ptr + i) & 0xFFFF)
                        )
                        ch.bus.write(
                            0x2100 | ((ch.target_address + offsets[i]) & 0xFF),
                            byte,
                        )
                    ch._hdma_ptr = (ch._hdma_ptr + unit_bytes) & 0xFFFF

            # Step 2: decrement the full counter byte.
            ch._hdma_line_counter_repeat = (
                ch._hdma_line_counter_repeat - 1
            ) & 0xFF

            # Step 3: DoTransfer for next scanline = bit 7 of decremented counter.
            ch._hdma_do_transfer = bool(ch._hdma_line_counter_repeat & 0x80)

            # Step 4: if bits 6:0 reached zero, load next entry.
            if (ch._hdma_line_counter_repeat & 0x7F) == 0:
                self._load_entry(ch)
