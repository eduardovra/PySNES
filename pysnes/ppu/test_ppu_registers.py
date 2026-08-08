"""
Synthetic PPU register unit tests.

Tests round-trip set/get for registers that previously raised
NotImplementedError, and VRAM address remapping modes.

Run:
    uv run --python pypy3.10 pytest pysnes/ppu/test_ppu_registers.py -v
"""

from pysnes.ppu.ppu import Ppu


def _make_ppu() -> Ppu:
    return Ppu()


# ---------------------------------------------------------------------------
# Item 8: NotImplementedError getter fixes
# ---------------------------------------------------------------------------


class TestBgmodeGetter:
    def test_bgmode_returns_mode_bits(self):
        ppu = _make_ppu()
        ppu.bgmode = 0b00000001  # mode 1
        assert ppu.bgmode == 1

    def test_bgmode_mode3(self):
        ppu = _make_ppu()
        ppu.bgmode = 0b00000011  # mode 3
        assert ppu.bgmode == 3

    def test_bgmode_masks_to_3_bits(self):
        ppu = _make_ppu()
        ppu.bgmode = 0b11111000  # bits 0-2 = 0
        assert ppu.bgmode == 0

    def test_bgmode_default_is_0(self):
        ppu = _make_ppu()
        assert ppu.bgmode == 0


class TestOamaddGetters:
    def test_oamaddl_returns_low_byte(self):
        ppu = _make_ppu()
        ppu.oamaddl = 0xAB
        assert ppu.oamaddl == 0xAB

    def test_oamaddl_zero(self):
        ppu = _make_ppu()
        ppu.oamaddl = 0x00
        assert ppu.oamaddl == 0x00

    def test_oamaddl_max(self):
        ppu = _make_ppu()
        ppu.oamaddl = 0xFF
        assert ppu.oamaddl == 0xFF

    def test_oamaddh_high_bit_of_address(self):
        """Bit 0 of oamaddh is bit 8 of the OAM address."""
        ppu = _make_ppu()
        ppu.oamaddh = 0x01  # bit 0 set, bit 7 clear
        assert ppu.oamaddh == 0x01

    def test_oamaddh_priority_activation_bit(self):
        """Bit 7 of oamaddh is the priority activation flag."""
        ppu = _make_ppu()
        ppu.oamaddh = 0x80  # bit 7 set, bit 0 clear
        assert ppu.oamaddh == 0x80

    def test_oamaddh_both_bits(self):
        ppu = _make_ppu()
        ppu.oamaddh = 0x81  # bit 7 and bit 0
        assert ppu.oamaddh == 0x81

    def test_oamaddl_preserves_high_bit_across_oamaddh_write(self):
        """oamaddl getter only returns low 8 bits even after oamaddh sets bit
        8."""
        ppu = _make_ppu()
        ppu.oamaddl = 0x55
        ppu.oamaddh = 0x01  # set bit 8 of address
        assert ppu.oamaddl == 0x55  # low byte unchanged
        assert ppu.oamaddh == 0x01


# ---------------------------------------------------------------------------
# Item 9: VRAM address remapping
# ---------------------------------------------------------------------------


def _write_word(ppu: Ppu, word_addr: int, low: int, high: int) -> None:
    """Set the VRAM word address and write a word (low, high)."""
    ppu.vmaddl = word_addr & 0xFF
    ppu.vmaddh = (word_addr >> 8) & 0xFF
    ppu.vmdatal = low
    # The $2119 setter writes the high byte and, in increment mode 1
    # (the default), advances the VRAM address.
    ppu.vmdatah = high


class TestVramRemapping:
    def test_mode0_no_remapping(self):
        """Mode 0: address used as-is."""
        ppu = _make_ppu()
        ppu.vmain = 0b10000000  # increment on high byte write, no remapping
        _write_word(ppu, 0x0020, 0xAA, 0xBB)
        assert ppu.vram[0x0020 * 2 + 0] == 0xAA
        assert ppu.vram[0x0020 * 2 + 1] == 0xBB

    def test_mode1_swaps_lower_8_bits(self):
        """
        Mode 1: aaaaaaaaBBBccccc → aaaaaaaacccccBBB
        Word addr 0x00E0 (binary: 00000000_11100000):
          aaaaaaaa=0x00, BBB=111 (bits 7:5), ccccc=00000 (bits 4:0)
          Remapped: aaaaaaaa=0x00, ccccc=00000, BBB=111 → 0x0007
        """
        ppu = _make_ppu()
        ppu.vmain = (
            0b10000100  # mode 1 (bits 3:2 = 01), increment on high write
        )
        _write_word(ppu, 0x00E0, 0xCC, 0xDD)
        assert ppu.vram[0x0007 * 2 + 0] == 0xCC
        assert ppu.vram[0x0007 * 2 + 1] == 0xDD

    def test_mode1_another_address(self):
        """
        Mode 1: word addr 0x001F (binary: 00000000_00011111):
          BBB=000, ccccc=11111 → remapped: 0x00F8 (11111_000)
        """
        ppu = _make_ppu()
        ppu.vmain = 0b10000100  # mode 1
        _write_word(ppu, 0x001F, 0x11, 0x22)
        assert ppu.vram[0x00F8 * 2 + 0] == 0x11
        assert ppu.vram[0x00F8 * 2 + 1] == 0x22

    def test_mode2_swaps_lower_9_bits(self):
        """
        Mode 2: aaaaaaaBBBcccccc → aaaaaaaccccccBBB
        Word addr 0x01C0 (binary: 00000001_11000000):
          aaaaaaa=0x00, BBB=111 (bits 8:6), cccccc=000000 (bits 5:0)
          Remapped: aaaaaaa=0x00, cccccc=000000, BBB=111 → 0x0007
        """
        ppu = _make_ppu()
        ppu.vmain = (
            0b10001000  # mode 2 (bits 3:2 = 10), increment on high write
        )
        _write_word(ppu, 0x01C0, 0x33, 0x44)
        assert ppu.vram[0x0007 * 2 + 0] == 0x33
        assert ppu.vram[0x0007 * 2 + 1] == 0x44

    def test_mode3_swaps_lower_10_bits(self):
        """
        Mode 3: aaaaaaBBBccccccc → aaaaaacccccccBBB
        Word addr 0x0380 (binary: 00000011_10000000):
          aaaaaa=0x00, BBB=111 (bits 9:7), ccccccc=0000000 (bits 6:0)
          Remapped: aaaaaa=0x00, ccccccc=0000000, BBB=111 → 0x0007
        """
        ppu = _make_ppu()
        ppu.vmain = (
            0b10001100  # mode 3 (bits 3:2 = 11), increment on high write
        )
        _write_word(ppu, 0x0380, 0x55, 0x66)
        assert ppu.vram[0x0007 * 2 + 0] == 0x55
        assert ppu.vram[0x0007 * 2 + 1] == 0x66

    def test_remapping_does_not_affect_address_counter(self):
        """
        The VRAM address counter (vmaddl/vmaddh) increments the raw address,
        not the remapped one. After a write, the counter advances by 1 word.
        """
        ppu = _make_ppu()
        ppu.vmain = 0b10000100  # mode 1, increment by 1
        ppu.vmaddl = 0xE0
        ppu.vmaddh = 0x00
        ppu.vmdatal = 0x00
        ppu.vmdatah = 0xFF  # triggers write + increment

        # Counter must have advanced from 0x00E0 to 0x00E1
        assert ppu.vmaddl == 0xE1
        assert ppu.vmaddh == 0x00


# ---------------------------------------------------------------------------
# VRAM read port: RDVRAML ($2139) / RDVRAMH ($213A)
# ---------------------------------------------------------------------------


class TestVramReadPort:
    def _seed(self, ppu: Ppu, word_addr: int, low: int, high: int) -> None:
        base = word_addr * 2
        ppu.vram[base + 0] = low
        ppu.vram[base + 1] = high

    def test_first_read_returns_prefetch_from_vmadd_write(self):
        """Writing VMADDL/VMADDH fills the prefetch buffer; first $2139 read
        returns that pre-fetched byte."""
        ppu = _make_ppu()
        ppu.vmain = 0x00  # increment on low read, step +1
        self._seed(ppu, 0x0010, 0xAA, 0xBB)
        ppu.vmaddl = 0x10
        ppu.vmaddh = 0x00
        ppu.refill_vram_prefetch()
        assert ppu.rdvraml() == 0xAA

    def test_read_low_increments_when_vmain_bit7_clear(self):
        """VMAIN:7=0 increments after each low-byte read. The buffer is
        refilled from the PRE-increment address, so there's a one-read lag:
        read #1 returns the pre-fetched word's low byte, read #2 returns the
        same byte again (buffer was just refilled from the same address),
        read #3 returns the next word's low byte."""
        ppu = _make_ppu()
        ppu.vmain = 0x00  # increment on low read
        self._seed(ppu, 0x0020, 0x11, 0x22)
        self._seed(ppu, 0x0021, 0x33, 0x44)
        ppu.vmaddl = 0x20
        ppu.vmaddh = 0x00
        ppu.refill_vram_prefetch()
        assert ppu.rdvraml() == 0x11
        assert ppu.vmaddl == 0x21  # address advanced
        assert ppu.rdvraml() == 0x11  # still the previous buffer
        assert ppu.rdvraml() == 0x33  # now the value at $0021

    def test_read_high_increments_when_vmain_bit7_set(self):
        ppu = _make_ppu()
        ppu.vmain = 0x80  # increment on high read
        self._seed(ppu, 0x0030, 0xCC, 0xDD)
        self._seed(ppu, 0x0031, 0xEE, 0xFF)
        ppu.vmaddl = 0x30
        ppu.vmaddh = 0x00
        ppu.refill_vram_prefetch()
        assert ppu.rdvramh() == 0xDD
        assert ppu.vmaddl == 0x31
        assert ppu.rdvramh() == 0xDD  # one-read lag — buffer still holds $0030
        assert ppu.rdvramh() == 0xFF

    def test_read_low_does_not_increment_when_vmain_bit7_set(self):
        ppu = _make_ppu()
        ppu.vmain = 0x80  # increment on high only
        self._seed(ppu, 0x0040, 0x55, 0x66)
        ppu.vmaddl = 0x40
        ppu.vmaddh = 0x00
        ppu.refill_vram_prefetch()
        ppu.rdvraml()
        assert ppu.vmaddl == 0x40  # no increment on low read
