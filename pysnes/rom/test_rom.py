"""
ROM header parser unit tests.

Builds a synthetic 32 KB LoROM image entirely in-memory (no real ROM files
needed) and exercises the corner cases that the parser previously got wrong:
the native COP vector offset, 16-bit checksum width, region-vs-developer field
naming, byte=0 size handling, and unfamiliar mapping_mode bytes.
"""

import pathlib

import pytest

from .rom import (
    CartridgeType,
    HardwareVectors,
    InterruptVectors,
    MappingMode,
    Region,
    Rom,
    SnesHeader,
)


LOROM_BANK_SIZE = 0x8000
HEADER_BASE = 0x7FC0  # offset within bank 0 of the cartridge header


def _build_lorom(
    *,
    title: bytes = b"PYSNES TEST          ",  # 21 bytes
    mapping_mode: int = 0x20,
    cartridge_type: int = 0x02,
    rom_size_byte: int = 0x09,
    sram_size_byte: int = 0x05,
    destination_code: int = 0x01,
    version: int = 0x00,
    checksum_complement: int = 0xABCD,
    checksum: int = 0x5432,
    native_vectors: dict | None = None,
    emulation_vectors: dict | None = None,
) -> bytes:
    """Return a 32 KB LoROM image with the requested header fields."""
    assert len(title) == 21
    img = bytearray(LOROM_BANK_SIZE)

    img[HEADER_BASE : HEADER_BASE + 21] = title
    img[HEADER_BASE + 0x15] = mapping_mode      # $FFD5
    img[HEADER_BASE + 0x16] = cartridge_type    # $FFD6
    img[HEADER_BASE + 0x17] = rom_size_byte     # $FFD7
    img[HEADER_BASE + 0x18] = sram_size_byte    # $FFD8
    img[HEADER_BASE + 0x19] = destination_code  # $FFD9
    img[HEADER_BASE + 0x1B] = version           # $FFDB
    img[HEADER_BASE + 0x1C] = checksum_complement & 0xFF
    img[HEADER_BASE + 0x1D] = (checksum_complement >> 8) & 0xFF
    img[HEADER_BASE + 0x1E] = checksum & 0xFF
    img[HEADER_BASE + 0x1F] = (checksum >> 8) & 0xFF

    nv = {"cop": 0x1234, "brk": 0x2345, "abort": 0x3456,
          "nmi": 0x4567, "irq": 0x5678}
    nv.update(native_vectors or {})
    ev = {"cop": 0xA111, "abort": 0xA222, "nmi": 0xA333,
          "reset": 0x8000, "irq": 0xA444}
    ev.update(emulation_vectors or {})

    def write_word(offset: int, value: int) -> None:
        img[offset] = value & 0xFF
        img[offset + 1] = (value >> 8) & 0xFF

    write_word(0x7FE4, nv["cop"])
    write_word(0x7FE6, nv["brk"])
    write_word(0x7FE8, nv["abort"])
    write_word(0x7FEA, nv["nmi"])
    write_word(0x7FEE, nv["irq"])
    write_word(0x7FF4, ev["cop"])
    write_word(0x7FF8, ev["abort"])
    write_word(0x7FFA, ev["nmi"])
    write_word(0x7FFC, ev["reset"])
    write_word(0x7FFE, ev["irq"])

    return bytes(img)


@pytest.fixture
def make_rom(tmp_path):
    def _make(image: bytes, name: str = "test.sfc") -> Rom:
        path = tmp_path / name
        path.write_bytes(image)
        return Rom(str(path))
    return _make


def test_native_cop_vector_reads_from_FFE4(make_rom):
    """Regression: previously read $FFE5/$FFE6 (high byte of COP + low of BRK)."""
    img = _build_lorom(
        native_vectors={"cop": 0xCAFE, "brk": 0xDEAD},
    )
    rom = make_rom(img)
    assert rom.hardware_vectors.native.cop == 0xCAFE
    assert rom.hardware_vectors.native.brk == 0xDEAD


def test_native_vectors_full(make_rom):
    img = _build_lorom(
        native_vectors={"cop": 0x1111, "brk": 0x2222, "abort": 0x3333,
                        "nmi": 0x4444, "irq": 0x5555},
    )
    rom = make_rom(img)
    nv = rom.hardware_vectors.native
    assert (nv.cop, nv.brk, nv.abort, nv.nmi, nv.irq) == (
        0x1111, 0x2222, 0x3333, 0x4444, 0x5555,
    )
    assert nv.reset == 0  # reset is emulation-only


def test_emulation_vectors_full(make_rom):
    img = _build_lorom(
        emulation_vectors={"cop": 0xAAAA, "abort": 0xBBBB, "nmi": 0xCCCC,
                           "reset": 0x8123, "irq": 0xDDDD},
    )
    rom = make_rom(img)
    ev = rom.hardware_vectors.emulation
    assert (ev.cop, ev.abort, ev.nmi, ev.reset, ev.irq) == (
        0xAAAA, 0xBBBB, 0xCCCC, 0x8123, 0xDDDD,
    )
    assert ev.brk == 0  # 65C02 emulation has no separate BRK vector


def test_checksum_and_complement_are_16_bit(make_rom):
    """Regression: previously read 1 byte instead of 2."""
    img = _build_lorom(checksum=0xBEEF, checksum_complement=0x4110)
    rom = make_rom(img)
    assert rom.snes_header.checksum == 0xBEEF
    assert rom.snes_header.checksum_complement == 0x4110


def test_destination_code_field(make_rom):
    """$FFD9 holds the region byte; the field used to be misnamed developer_id."""
    img = _build_lorom(destination_code=0x07)
    rom = make_rom(img)
    assert rom.snes_header.destination_code == 0x07


def test_mapping_mode_is_enum_when_supported(make_rom):
    img = _build_lorom(mapping_mode=0x30)  # LoROM + FastROM
    rom = make_rom(img)
    assert rom.snes_header.mapping_mode is MappingMode.LOROM_FAST
    assert rom.snes_header.mapping_mode == 0x30  # IntEnum still compares as int


@pytest.mark.parametrize("mode", [
    0x21,  # HiROM — known but bus mapping not implemented
    0x22,  # ExLoROM
    0x23,  # SA-1 (coprocessor)
    0x25,  # ExHiROM
    0x31,  # HiROM + FastROM
    0x99,  # unknown byte
])
def test_unsupported_mapping_mode_raises(make_rom, mode):
    img = _build_lorom(mapping_mode=mode)
    with pytest.raises(AssertionError, match="unsupported mapping mode"):
        make_rom(img)


def test_region_enum(make_rom):
    img = _build_lorom(destination_code=0x01)
    rom = make_rom(img)
    assert rom.snes_header.destination_code is Region.NORTH_AMERICA


def test_region_falls_back_to_int_when_unknown(make_rom):
    img = _build_lorom(destination_code=0xEE)
    rom = make_rom(img)
    assert rom.snes_header.destination_code == 0xEE
    assert not isinstance(rom.snes_header.destination_code, Region)


def test_cartridge_type_enum(make_rom):
    img = _build_lorom(cartridge_type=0x02)
    rom = make_rom(img)
    assert rom.snes_header.cartridge_type is CartridgeType.ROM_RAM_BATTERY


def test_zero_sram_byte_means_no_sram(make_rom):
    img = _build_lorom(sram_size_byte=0)
    rom = make_rom(img)
    assert rom.snes_header.sram_size == 0
    assert rom.sram_size == 0


def test_zero_rom_size_byte_yields_zero(make_rom):
    img = _build_lorom(rom_size_byte=0)
    rom = make_rom(img)
    assert rom.snes_header.rom_size == 0


def test_sram_size_capped_at_128KB(make_rom):
    img = _build_lorom(sram_size_byte=0x0A)  # 0x400 << 10 = 1 MB → clamp
    rom = make_rom(img)
    assert rom.snes_header.sram_size == 0x20000


def test_game_title_decoded(make_rom):
    img = _build_lorom(title=b"SUPER MARIO WORLD    ")
    rom = make_rom(img)
    assert rom.snes_header.game_title == "SUPER MARIO WORLD"


def test_smc_header_is_stripped(make_rom):
    """A 512-byte SMC copier header at the front must not shift the parsed header."""
    raw = _build_lorom(checksum=0xFACE)
    img_with_header = b"\x00" * 0x200 + raw  # 512 SMC bytes + 32 KB ROM
    rom = make_rom(img_with_header, name="test.smc")
    assert rom.smc_header_length == 0x200
    assert rom.snes_header.checksum == 0xFACE


def test_header_dataclasses_are_typed():
    h = SnesHeader(
        game_title="X", mapping_mode=0x20, cartridge_type=0,
        rom_size=0, sram_size=0, destination_code=0, version=0,
        checksum_complement=0, checksum=0,
    )
    v = HardwareVectors(
        native=InterruptVectors(cop=0, brk=0, abort=0, nmi=0, reset=0, irq=0),
        emulation=InterruptVectors(cop=0, brk=0, abort=0, nmi=0, reset=0, irq=0),
    )
    # Field access uses attributes, not dict keys
    assert h.destination_code == 0
    assert v.native.cop == 0 and v.emulation.reset == 0
