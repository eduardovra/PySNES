from typing import TYPE_CHECKING
from dataclasses import dataclass

if TYPE_CHECKING:
    from .bus import Bus


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

    def do_transfer(self) -> None:
        # source_address == 0x8000
        # source_bank == 0x03
        # target_address == 0x18 --> $2118 --> VRAM Write
        # direction == 0 --> A to B
        # transfer_size == 0x1000 (4096)
        # transfer_mode == 0x1 --> 2 bytes to 2 registers (write once)
        # fixed_transfer == 0x0 --> increment/decrement dma source addr
        # reverse_transfer == 0 --> Increment
        assert self.transfer_mode == 1
        assert self.reverse_transfer == 0
        assert self.direction == 0

        target_addr = 0x2100 | self.target_address  # B bus
        for index in range(self.transfer_size):
            data = self.bus[self.source_bank << 16 | self.source_address]
            self.bus[target_addr + (index & 1)] = data
            if not self.fixed_transfer:
                self.source_address += 1


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

        raise RuntimeError("Address not mapped in DMA: 0x{:06X}".format(abs_addr))

    def mdmaen_set(self, data: int) -> None:
        for enable_bit, channel in enumerate(self.channels):
            if data & (1 << enable_bit):
                channel.do_transfer()
