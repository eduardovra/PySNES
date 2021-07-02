def main():
    with open("Super Mario World (U) [!].smc", "rb") as f:
        rom = f.read()

    # Strip out potential header
    smc_header_length = len(rom) % 0x400
    rom = rom[smc_header_length:]

    rom_type = None

    # LoROM
    if all(31 < char < 127 for char in rom[0x7FC0 : 0x7FC0 + 21]):
        rom_type = "LoROM"
    # HiROM
    if all(31 < char < 127 for char in rom[0xFFC0 : 0xFFC0 + 21]):
        rom_type = "HiROM"

    assert rom_type == "LoROM"

    # SNES header is located in the last 64 bytes of the first bank: 0x7FC0 - 0xFFFF
    snes_header = {
        "game_title": rom[0x7FC0 : 0x7FC0 + 21],  # 21 bytes, usually uppercase ASCII.
        "mapping_mode": rom[
            0x7FD5
        ],  # 001ABBBB; A==1 means FastROM ($10). If BBBB is the mapping mode.
        "rom_type": rom[
            0x7FD6
        ],  # Denotes that the cartridge contains expansion chips, SRAM, batteries, etc.
        "rom_size": 0x400 << rom[0x7FD7],
        "sram_size": 0x400 << rom[0x7FD8],
        "developer_id": rom[0x7FD9],
        "version": rom[0x7FDB],
        "checksum_complement": rom[0x7FDC],
        "checksum": rom[0x7FDE],
    }

    print(f"{snes_header=}")

    # The bitmask to use is 001A0BCD, the basic value is $20:
    # - A == 0 means SlowROM (+ $0), A == 1 means FastROM (+ $10).
    # - B == 1 means ExHiROM (+ $4)
    # - C == 1 means ExLoROM (+ $2)
    # - D == 0 means LoROM (+ $0), D == 1 means HiROM (+ $1)
    # For super mario world A == 0 and D == 0, so it's SlowROM + LoROM
    assert snes_header["mapping_mode"] == 0x20  # LoROM+SNES

    # FastROM's can execute at 3.58Mhz
    # SlowROM's can only execute 2.68Mhz

    # Interrupt vectors
    emulation_reset_vector = rom[0x7FFC] | (rom[0x7FFD] << 8)  # 0x8000

    # The address space has 24 bits
    # rom size is 0x080000, so the last address is 0x07FFFF
    # SNES 00:8000-FFFF <--- ROM 000000-007FFF
    # Addresses 0x008000 in SNES maps to 0x000000 in ROM
    # So the actual instructions are located in:
    pc = 0  # program counter

    # The status register bits 7,6,3,2,1,0 (nvdizc) function the same as the 6502 status register bits.

    # 7 n Negative flag
    # 6 v Overflow flag
    # 5 m Accumulator/Memory Select
    # 4 x Index Register Select
    # 3 d Decimal flag
    # 2 i Interrupt mask
    # 1 z Zero flag
    # 0 c Carry flag

    # Status Bit 4 X: Index Register Select
    #   When x=0 (16 bit), both the X and Y registers become 16 bits wide.
    #   All operations involving the X and Y registers act on all 16 bits of the index register.
    # Status Bit 5: Accumulator/Memory Select
    #   When in 16 bit mode (m=0) all operations involving the accumulator will act upon 16 bits of data.
    status_register = 0

    # 1=emulation. The processor powers up in default 6502 emulation mode.
    # The emulation status bit is a hidden or phantom bit that is not directly set, tested, or cleared.
    #   xce; exchange (swap) carry with the emulation bit.
    emulation_mode = 1

    accumulator = 0
    direct_page_register = 0
    stack_pointer = 0

    while True:
        opcode = rom[pc]
        print(f"PC={pc:#08X} opcode={opcode:#02X}")

        if opcode == 0x78:
            # Set interrupt flag
            # SEI
            # 1 byte, 2 cycles
            pc += 1
        elif opcode == 0x9C:
            # STZ Store Zero byte to Memory
            # STZ addr
            # 3 bytes, >= 4 cycles
            # 0x4200 NMI, V/H Count, and Joypad Enable
            # a0bc000d a = NMI b = V-Count c = H-Count d = Joypad
            addr = (
                rom[pc + 1] | rom[pc + 2] << 8
            )  # 0x4200, seems to be the PPU2 base address
            pc += 3
        elif opcode == 0xA9:
            # LDA Load the Accumulator with Memory
            # LDA #const
            # >= 2 bytes, >= 2 cycles
            if emulation_mode or not (status_register & 1 << 5):
                accumulator = rom[pc + 1]
                pc += 2
            else:
                accumulator = rom[pc + 1] | rom[pc + 2] << 8
                pc += 3
        elif opcode == 0x8D:
            # SEP Set Status Bits
            # STA addr
            # 3 bytes, >= 4 cycles
            # 0x2100 Screen Display Register
            # a000bbbb a: 0=screen on 1=screen off, b = brightness
            addr = rom[pc + 1] | rom[pc + 2] << 8
            value = 0  # TODO access ppu memory 0x2100, whats in there??
            # status_register |= addr  # TODO
            pc += 3
        elif opcode == 0x8F:
            # SEP Set Status Bits
            # STA long
            # 4 bytes, >= 5 cycles
            _long = rom[pc + 1] | rom[pc + 2] << 8
            value = 0  # TODO
            # status_register |= addr  # TODO
            pc += 3
        elif opcode == 0x18:
            # Status Register Setting and Clearing
            # CLC Clear carry flag
            # 1 byte, 2 cycles
            status_register &= ~(1 << 0)
            pc += 1
        elif opcode == 0xFB:
            # XCE Exchange Carry and Emulation Bits
            # XCE
            # 1 byte, 2 cycles
            previous_mode = emulation_mode
            emulation_mode = status_register & (1 << 0)
            if previous_mode:
                status_register |= 1 << 0
            else:
                status_register &= ~(1 << 0)
            pc += 1
        elif opcode == 0xC2:
            # REP Reset Status Bits
            # REP #const
            # 2 bytes, 3 cycles
            const = rom[pc + 1]
            status_register |= const
            pc += 2
        elif opcode == 0x5B:
            # Direct Page Instructions
            # TCD Transfer Accumulator to Direct Page Register.
            # TCD
            # 1 byte, 2 cycles
            """
            Flags Affected: n-----z-
                      n Set if most significant bit of transfer value
                        is set.
                      z Set if transferred value is zero.
            """
            direct_page_register = accumulator
            pc += 1  # TODO
        elif opcode == 0x1B:
            # TCS Transfer Accumulator to Stack Pointer
            # TCS transfers a full 16 bits to the stack pointer without regard for the setting of status bit m.
            # 1 byte, 2 cycles
            stack_pointer = accumulator
            pc += 1
        else:
            raise Exception(f"Unknown opcode = {opcode:#02X}")


if __name__ == "__main__":
    main()
