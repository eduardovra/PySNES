import csv

"""
Branch Instructions

BCC	Branch if Carry flag is clear (C=0)
BCS	Branch if Carry flag is set (C=1)
BNE	Branch if not equal (Z=0)
BEQ	Branch if equal (Z=1)
BPL	Branch if plus (N=0)
BMI	Branch if minus (N=1)
BVC	Branch if overflow flag is clear (V=0)
BVS	Branch if overflow flag is set (V=1)
BRA	Branch Always (unconditional)
BRL	Branch Always Long (unconditional)

Jump and call instructions

JMP	Jump
JML	Jump long
JSR	Jump and save return address
JSL	Jump long and save return address
RTS	Return from subroutine
RTL	Return long from subroutine
"""


class AddressingMode:
    MODES = {
        "": "nop",  # Reserved for Future Expansion
        "Implied": "implied",
        "Immediate": "immediate",
        "Immediate Single Byte": "immediate_single_byte",  # Added by me: always fetch just 1 operand byte (ignore M flag)
        "Absolute": "absolute",
        "Absolute Long": "absolute_long",
        "Absolute Indirect": "absolute_indirect",
        "Absolute Indirect Long": "absolute_indirect_long",
        "Absolute Indexed Indirect": "absolute_indexed_indirect",
        "Absolute Indexed,X": "absolute_indexed_x",
        "Absolute Indexed,Y": "absolute_indexed_y",
        "Absolute Long Indexed,X": "absolute_long_indexed_x",
        "Direct Page": "direct_page",
        "DP Indirect": "dp_indirect",
        "DP Indirect Long": "dp_indirect_long",
        "DP Indexed,X": "dp_indexed_x",
        "DP Indexed,Y": "dp_indexed_y",
        "DP Indexed Indirect,X": "dp_indexed_indirect_x",
        "DP Indirect Indexed, Y": "dp_indirect_indexed_y",
        "DP Indirect Long Indexed, Y": "dp_indirect_long_indexed_y",
        "Program Counter Relative": "program_counter_relative",
        "Program Counter Relative Long": "program_counter_relative_long",
        "SR Indirect Indexed,Y": "sr_indirect_indexed_y",
        "Stack Relative": "stack_relative",
        "Stack/Interrupt": "stack_interrupt",
        "Stack (Absolute)": "stack_absolute",
        "Stack (DP Indirect)": "stack_dp_indirect",
        "Stack (PC Relative Long)": "stack_pc_relative_long",
        "Stack (Push)": "implied",
        "Stack (Pull)": "implied",
        "Stack (RTI)": "stack_rti",
        "Stack (RTL)": "stack_rtl",
        "Stack (RTS)": "stack_rts",
        "Block Move": "block_move",
        "Accumulator": "accumulator",
    }

    def __init__(self, addressin_mode: str) -> None:
        self.mode_str = self.MODES[addressin_mode]

    def __call__(self, cpu) -> int:
        try:
            method = getattr(self, self.mode_str)
        except AttributeError:
            raise RuntimeError(f"Addressing mode not implemented: {self.mode_str}")

        return method(cpu)

    def implied(self, cpu) -> int:
        """
        SEI
        In implied addressing mode, the operands are specified implicitly in the definition of the instruction
        """
        return 0

    def accumulator(self, cpu) -> int:
        """
        Accumulator Addressing
        8-Bit Data (all processors): Data: Byte in accumulator A.
        16-Bit Data (65802/65816, native mode. 16-bit accumulator (m = 0):
            Data High: High byte in accumulator A.
            Data Low: Low byte in accumulator A.
        """
        return 0

    def immediate(self, cpu) -> int:
        """
        LDA const
        In immediate addressing mode, the operand is a part of the instruction.
        8-Bit Data (all processors): Data Operand byte
        16-Bit Data (65802/65816, native mode, applicable mode flag m or x = 0):
        """
        addr = cpu.PC
        cpu.PC += 1
        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.PC += 1
        return addr  # operand

    def immediate_single_byte(self, cpu) -> int:
        """
        I added this mode to use with instructions that disregard the M flag
        and always have fixed length one byte operands
        """
        addr = cpu.PC
        cpu.PC += 1
        return addr

    def absolute(self, cpu) -> int:
        """
        LDA addr
        In direct addressing mode, the address field contains the address of the operand.
        Effective Address:
        Bank: Data Bank Register (DBR) if locating data; Program Bank Register (PBR) if transferring control.
        High: Second operand byte.
        Low: First operand byte.
        """
        bank = 0  # TODO assuming bank 0 for now
        addr = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8 | bank << 16
        cpu.PC += 2
        return addr  # operand

    def absolute_long(self, cpu) -> int:
        """
        LDA addr
        Effective Address:
        Bank: Third operand byte.
        High: Second operand byte.
        Low: First operand byte.
        """
        addr = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8 | cpu.bus[cpu.PC + 2] << 16
        cpu.PC += 3
        return addr

    def absolute_long_indexed_x(self, cpu) -> int:
        """
        Effective Address: The 24-bit Operand is added to X
        (16 bits if 65802/65816 native mode, x = 0; else 8 bits)
        """
        operand = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8 | cpu.bus[cpu.PC + 2] << 16
        cpu.PC += 3
        addr = cpu.X + operand
        return addr

    def stack_interrupt(self, cpu) -> int:
        """
        Effective Address: After pushing the Program Bank (65802/816 native mode only),
        followed by the Program Counter and the Status Register, the Effective Address is
        loaded into the Program Counter and Program Bank Register, transferring control there.
        Bank: Zero
        High/Low: The contents of the instruction- and processor-specific interrupt vector.
        """
        assert cpu.emulation == 0
        return self.immediate(cpu)

    def program_counter_relative(self, cpu) -> int:
        """
        Bank: Program Bank Register (PBR).
        High/Low: The Operand byte, a two's complement signed value, is sign-extended to 16 bits,
        then added to the Program Counter (its value is the address of the opcode following this one).
        """
        operand = cpu.bus[cpu.PC]
        # Sign extension
        if operand & 0x80:  # Negative
            operand |= 0xFF00
        cpu.PC += 1  # TODO not sure...
        addr = (operand + cpu.PC) & 0xFFFF | cpu.PB << 16
        return addr

    def program_counter_relative_long(self, cpu) -> int:
        """
        Effective Address:
        Bank: Program Bank Register (PBR).
        High/Low: The Operand double byte, a two's complement signed value, is added
        to the Program Counter (its value is the address of the opcode following this one).
        """
        operand_tc = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8

        cpu.PC += 2  # TODO not sure if this should be done before or after

        # operand is in two's complement format, convert it to an int
        operand = (-1) * (0xFFFF + 1 + operand_tc)
        assert -32768 <= operand <= 32767
        addr = cpu.PC + operand

        return addr | cpu.PB << 16

    def dp_indirect_long_indexed_y(self, cpu) -> int:
        """
        Direct Page Indirect Long Indexed, Y Addressing
        Effective Address:Found by adding to the triple-byte indirect address Y (16 bits if 65802/65816 native mode, x = 0; else 8 bits).
        Indirect Address: Located in the Direct Page at the sum of the direct page register and the operand byte in bank zero.

        Direct Page Indirect Long Indexed Y       LDA [$77],Y
        This instruction in two bytes long and allows you to temporarily reach into any memory bank.
        The operand is a direct page (zero page) pointer. The address located at the direct page offset is
        three bytes long. First is the low byte, then high byte, followed by the bank byte of the base effect address.
        The Y index register is then added to this three byte destination address to form the effective address.
        Square brackets are used to denote that the address is a full 24 bit address and not a simple 16 bit address.
        """
        assert cpu.emulation == 0
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1

        offset = cpu.D + operand
        indirect_addr = (
            cpu.bus[offset] | cpu.bus[offset + 1] << 8 | cpu.bus[offset + 2] << 16
        )
        y = cpu.Y if cpu.P.X == 0 else cpu.Y & 0xFF
        addr = indirect_addr + y

        return addr


class Instruction:
    def __init__(self, raw_instruction: dict) -> None:
        self.example = raw_instruction["Assembler Example"]
        self.mnemonic = self.example[:3]
        self.alias = raw_instruction["Alias"]
        self.description = raw_instruction["Proper Name"]
        self.opcode = int(raw_instruction["HEX"], 16)
        self.addressing_mode = raw_instruction["Addressing Mode"]
        self.flags_set = set(f for f in raw_instruction["Flags Set"] if f != "-")
        self.bytes = raw_instruction["Bytes"]  # TODO parse
        self.cycles = raw_instruction["Cycles"]  # TODO parse

        # TODO load method here, once I get all of them implemented

    def __str__(self) -> str:
        opcode = "0x{:02X}".format(self.opcode)
        return f"{opcode} {self.mnemonic} {self.addressing_mode}"

    def __call__(self, cpu) -> int:
        # Decode phase: fetch additional information before execution

        # TODO for now I'm just returning the addr to the operand,
        # but it'll have to return the number of cycles used eventually
        addressing_mode = AddressingMode(self.addressing_mode)
        addr = addressing_mode(cpu)

        # Execute instruction phase
        try:
            instruction = getattr(self, self.mnemonic)
        except AttributeError:
            raise RuntimeError(f"Mnemonic not implemented: {self.mnemonic}")

        return instruction(cpu, addr)

    def BRK(self, cpu, addr):
        """Software Break"""
        assert cpu.emulation == 0
        # the program counter bank register is pushed onto stack.
        cpu.bus[cpu.S] = cpu.PB
        cpu.S -= 1
        # the program counter is incremented by two and pushed on the stack.
        cpu.PC += 2  # TODO verify - at this point was already incremented by 1
        cpu.bus[cpu.S] = (cpu.PC >> 8) & 0xFF
        cpu.S -= 1
        cpu.bus[cpu.S] = cpu.PC & 0xFF
        cpu.S -= 1
        # the status register is pushed onto the stack
        cpu.bus[cpu.S] = cpu.P
        cpu.S -= 1
        # the interrupt disable flag is set.
        cpu.I = 1
        # the decimal mode flag is cleared.
        cpu.D = 0
        # the program bank register is cleared to zero.
        cpu.PB = 0
        # the program counter is loaded from the break vector at $FFE6-$FFE7.
        cpu.PC = 0xFFFF  # TODO fix hardcoded

        return 7

    def CLC(self, cpu, addr):
        """Clear carry flag"""
        cpu.P.C = 0
        return 2

    def CLD(self, cpu, addr):
        """Clear decimal flag"""
        cpu.P.D = 0
        return 2

    def CLI(self, cpu, addr):
        """Clear interrupt flag"""
        cpu.P.I = 0
        return 2

    def CLV(self, cpu, addr):
        """Clear overflow flag"""
        cpu.P.V = 0
        return 2

    def SEC(self, cpu, addr) -> int:
        """Set carry flag"""
        cpu.P.C = 1
        return 2

    def SED(self, cpu, addr) -> int:
        """Set decimal flag"""
        cpu.P.D = 1
        return 2

    def SEI(self, cpu, addr) -> int:
        """Set interrupt flag"""
        cpu.P.I = 1
        return 2

    def XBA(self, cpu, addr) -> int:
        """Exchange B and A Accumulators"""
        temp_high = cpu.A >> 8
        temp_low = cpu.A & 0xFF
        cpu.A = temp_low << 8 | temp_high
        cpu.P.N = 1 if cpu.A & 0x80 else 0
        cpu.P.Z = 1 if (cpu.A & 0xFF) == 0 else 0
        return 3

    def XCE(self, cpu, addr) -> int:
        """Exchange Carry and Emulation Bits"""
        carry = cpu.P.C
        cpu.P.C = cpu.emulation
        cpu.emulation = carry
        # TODO need to replace the status register because flags are different in native mode
        if cpu.emulation == 0:
            cpu.P.M = 1
            cpu.P.X = 1

        return 2

    def REP(self, cpu, addr) -> int:
        """Reset Status Bits"""
        mask = cpu.bus[addr]
        status = cpu.P.get(cpu.emulation)
        cpu.P.set(status & ~mask, cpu.emulation)

        return 3

    def SEP(self, cpu, addr) -> int:
        """Set Status Bits"""
        mask = cpu.bus[addr]
        status = cpu.P.get(cpu.emulation)
        cpu.P.set(status | mask, cpu.emulation)

        return 3

    def STZ(self, cpu, addr) -> int:
        """Store Zero byte to Memory"""
        cpu.bus[addr] = 0
        if cpu.emulation == 0 and cpu.P.M == 0:  # 16 bit mode
            cpu.bus[addr + 1] = 0
        return 4

    def LDA(self, cpu, addr) -> int:
        """Load the Accumulator with Memory"""
        cycles = 2  # TODO it depends on addressing mode and processor flags
        cpu.A = cpu.bus[addr]
        n_mask = 0x80
        if cpu.emulation == 0 and cpu.P.M == 0:
            cycles += 1
            n_mask = 0x8000
            cpu.A |= cpu.bus[addr + 1] << 8

        cpu.P.Z = 1 if cpu.A == 0 else 0
        cpu.P.N = 1 if cpu.A & n_mask else 0

        return cycles

    def STA(self, cpu, addr) -> int:
        """Store Accumulator to Memory"""
        cpu.bus[addr] = cpu.A & 0xFF
        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.bus[addr + 1] = (cpu.A & 0xFF00) >> 8

        return 0

    def TCD(self, cpu, addr) -> int:
        """Transfer Accumulator to Direct Page Register"""
        cpu.D = cpu.A
        cpu.P.N = 1 if cpu.A & 0x8000 else 0
        cpu.P.Z = 1 if cpu.A == 0 else 1

        return 2

    def TDC(self, cpu, addr) -> int:
        """Transfer Direct Page Register to Accumulator"""
        cpu.A = cpu.D
        cpu.P.N = 1 if cpu.A & 0x8000 else 0
        cpu.P.Z = 1 if cpu.A == 0 else 1

        return 2

    def TCS(self, cpu, addr) -> int:
        """Transfer Accumulator to Stack Pointer"""
        if cpu.emulation == 0:
            cpu.S = cpu.A
        else:
            cpu.S = cpu.A & 0xFF

        return 2

    def LDX(self, cpu, addr) -> int:
        """Load X Register from Memory"""
        cpu.X = cpu.bus[addr]
        cpu.P.N = 1 if cpu.X & 0x80 else 0
        if cpu.emulation == 0 and cpu.P.M == 0 and cpu.P.X == 0:
            cpu.X |= cpu.bus[addr + 1] << 8
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
        cpu.P.Z = 1 if cpu.X == 0 else 0

        return 0

    def LDY(self, cpu, addr) -> int:
        """Load Y Register from Memory"""
        cpu.Y = cpu.bus[addr]
        cpu.P.N = 1 if cpu.Y & 0x80 else 0
        if cpu.emulation == 0 and cpu.P.M == 0 and cpu.P.X == 0:
            cpu.Y |= cpu.bus[addr + 1] << 8
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
        cpu.P.Z = 1 if cpu.Y == 0 else 0

        return 0

    def TAX(self, cpu, addr) -> int:
        """Transfer accumulator to X index register"""
        assert cpu.emulation == 0
        if cpu.P.X == 1:
            cpu.X = cpu.A & 0xFF
            cpu.P.N = 1 if cpu.X & 0x80 else 0
        else:
            cpu.X = cpu.A
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
        cpu.P.Z = 1 if cpu.X == 0 else 0

        return 2

    def TAY(self, cpu, addr) -> int:
        """Transfer accumulator to Y index register"""
        assert cpu.emulation == 0
        if cpu.P.X == 1:
            cpu.Y = cpu.A & 0xFF
            cpu.P.N = 1 if cpu.Y & 0x80 else 0
        else:
            cpu.Y = cpu.A
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
        cpu.P.Z = 1 if cpu.Y == 0 else 0

        return 2

    def TYA(self, cpu, addr) -> int:
        """Transfer Y index register to the accumulator"""
        assert cpu.emulation == 0
        if cpu.P.M == 1:
            if cpu.P.X == 0:
                # 16 bit index regs to 8 bit acc (m=1, x=0), 8 bits are transferred.
                # The hidden high order accumulator byte is not
                # affected and the previous values remain.
                cpu.A = (cpu.A & 0xFF00) | cpu.Y & 0xFF
            else:
                cpu.A = cpu.Y & 0xFF
            cpu.P.N = 1 if cpu.A & 0x80 else 0
        else:
            if cpu.P.X == 1:
                # 8 bit index regs to 16 bit acc (m=0, x=1), Two bytes
                # transferred with the high byte being zero.
                cpu.A = cpu.Y & 0xFF
            else:
                cpu.A = cpu.Y
            cpu.P.N = 1 if cpu.A & 0x8000 else 0

        cpu.P.Z = 1 if cpu.A == 0 else 0

        return 2

    def TXA(self, cpu, addr) -> int:
        """Transfer X index register to the accumulator"""
        assert cpu.emulation == 0
        if cpu.P.M == 1:
            if cpu.P.X == 0:
                # 16 bit index regs to 8 bit acc (m=1, x=0), 8 bits are transferred.
                # The hidden high order accumulator byte is not
                # affected and the previous values remain.
                cpu.A = (cpu.A & 0xFF00) | cpu.X & 0xFF
            else:
                cpu.A = cpu.X & 0xFF
            cpu.P.N = 1 if cpu.A & 0x80 else 0
        else:
            if cpu.P.X == 1:
                # 8 bit index regs to 16 bit acc (m=0, x=1), Two bytes
                # transferred with the high byte being zero.
                cpu.A = cpu.X & 0xFF
            else:
                cpu.A = cpu.X
            cpu.P.N = 1 if cpu.A & 0x8000 else 0

        cpu.P.Z = 1 if cpu.A == 0 else 0

        return 2

    def ADC(self, cpu, addr) -> int:
        """Add with carry"""
        assert cpu.emulation == 0
        # Value to be added to the accumulator
        value = cpu.bus[addr]
        if cpu.P.M == 0:
            value |= cpu.bus[addr + 1] << 8
        # Sum
        temp = cpu.A + value + (cpu.P.C & 0x1)
        # Set flags and accumulator
        if cpu.P.M == 0:
            cpu.P.Z = 1 if (temp & 0xFFFF) == 0 else 0
            cpu.P.C = 1 if temp > 0xFFFF else 0
            cpu.P.N = 1 if temp & 0x8000 else 0
            cpu.P.V = 1 if (~(cpu.A ^ value) & (cpu.A ^ temp)) & 0x8000 else 0
            cpu.A = temp & 0xFFFF
        else:
            cpu.P.Z = 1 if (temp & 0xFF) == 0 else 0
            cpu.P.C = 1 if temp > 0xFF else 0
            cpu.P.N = 1 if temp & 0x80 else 0
            cpu.P.V = 1 if (~(cpu.A ^ value) & (cpu.A ^ temp)) & 0x80 else 0
            cpu.A = temp & 0xFF

        return 0

    def SBC(self, cpu, addr) -> int:
        """Subtract from Accumulator"""
        assert cpu.emulation == 0
        # Value to be subtracted from the accumulator

        if cpu.P.M == 0:
            value = (cpu.bus[addr] | cpu.bus[addr + 1] << 8) ^ 0xFFFF
        else:
            value = cpu.bus[addr] ^ 0xFF
        # Subtract
        temp = cpu.A + value + (cpu.P.C & 0x1)
        # Set flags and accumulator
        if cpu.P.M == 0:
            cpu.P.Z = 1 if (temp & 0xFFFF) == 0 else 0
            cpu.P.C = 1 if temp > 0xFFFF else 0
            cpu.P.N = 1 if temp & 0x8000 else 0
            cpu.P.V = 1 if ((temp ^ cpu.A) & (temp ^ value)) & 0x8000 else 0
            cpu.A = temp & 0xFFFF
        else:
            cpu.P.Z = 1 if (temp & 0xFF) == 0 else 0
            cpu.P.C = 1 if temp > 0xFF else 0
            cpu.P.N = 1 if temp & 0x80 else 0
            cpu.P.V = 1 if ((temp ^ cpu.A) & (temp ^ value)) & 0x80 else 0
            cpu.A = temp & 0xFF

        return 0

    def DEX(self, cpu, addr) -> int:
        """Decrement Index Register X"""
        cpu.X -= 1
        if cpu.P.X == 0:
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
        else:
            cpu.P.N = 1 if cpu.X & 0x80 else 0
        cpu.P.Z = 1 if cpu.X == 0 else 0

        return 2

    def DEY(self, cpu, addr) -> int:
        """Decrement Index Register Y"""
        cpu.Y -= 1
        if cpu.P.X == 0:
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
        else:
            cpu.P.N = 1 if cpu.Y & 0x80 else 0
        cpu.P.Z = 1 if cpu.Y == 0 else 0

        return 2

    def BRA(self, cpu, addr) -> int:
        """Branch Always"""
        cpu.PC = addr
        return 0

    def BCC(self, cpu, addr) -> int:
        """Branch Carry Clear"""
        if cpu.P.C == 0:
            cpu.PC = addr
        return 0

    def BCS(self, cpu, addr) -> int:
        """Branch Carry Set"""
        if cpu.P.C == 1:
            cpu.PC = addr
        return 0

    def BEQ(self, cpu, addr) -> int:
        """Branch Equal"""
        if cpu.P.Z == 1:
            cpu.PC = addr
        return 0

    def BNE(self, cpu, addr) -> int:
        """Branch Not Equal"""
        if cpu.P.Z == 0:
            cpu.PC = addr
        return 0

    def BMI(self, cpu, addr) -> int:
        """Branch Result Minus"""
        if cpu.P.N == 1:
            cpu.PC = addr
        return 0

    def BPL(self, cpu, addr) -> int:
        """Branch Result Positive"""
        if cpu.P.N == 0:
            cpu.PC = addr
        return 0

    def BVC(self, cpu, addr) -> int:
        """Branch Overflow Clear"""
        if cpu.P.V == 0:
            cpu.PC = addr
        return 0

    def BVS(self, cpu, addr) -> int:
        """Branch Overflow Set"""
        if cpu.P.V == 1:
            cpu.PC = addr
        return 0

    def JSR(self, cpu, addr) -> int:
        """Jump to Subroutine"""
        pc = cpu.current_instruction_PC
        # Push program bank
        cpu.bus[cpu.S] = cpu.PB
        cpu.S -= 1
        # PC high byte
        cpu.bus[cpu.S] = (pc >> 8) & 0xFF
        cpu.S -= 1
        # PC low byte
        cpu.bus[cpu.S] = pc & 0xFF
        cpu.S -= 1
        # Jump to addr
        cpu.PC = addr

        return 0

    def PHA(self, cpu, addr) -> int:
        """Push Accumulator"""
        cpu.bus[cpu.S] = cpu.A
        cpu.S -= 1
        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.bus[cpu.S] = cpu.A >> 8
            cpu.S -= 1
        return 0

    def PLA(self, cpu, addr) -> int:
        """Pull Accumulator"""
        cpu.S += 1
        cpu.A = cpu.bus[cpu.S]
        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.S += 1
            cpu.A = cpu.A << 8 | cpu.bus[cpu.S]

        return 0

    def PHP(self, cpu, addr) -> int:
        """Push Processor Status Register"""
        cpu.bus[cpu.S] = cpu.P.get(cpu.emulation)
        cpu.S -= 1
        return 0

    def PLP(self, cpu, addr) -> int:
        """Pull Processor Status Register"""
        cpu.S += 1
        cpu.P.set(cpu.bus[cpu.S], cpu.emulation)
        return 0

    def CMP(self, cpu, addr) -> int:
        """Compare Accumulator with Memory"""
        if cpu.emulation == 0 and cpu.P.M == 0:
            value = cpu.bus[addr] | cpu.bus[addr + 1] << 8
            temp = cpu.A - value
            cpu.P.Z = 1 if (temp & 0xFFFF) == 0 else 0
            cpu.P.N = 1 if temp & 0x8000 else 0
        else:
            value = cpu.bus[addr]
            temp = (cpu.A & 0xFF) - value
            cpu.P.Z = 1 if (temp & 0xFF) == 0 else 0
            cpu.P.N = 1 if temp & 0x80 else 0

        cpu.P.C = 1 if cpu.A >= value else 0

        return 0

    def CPX(self, cpu, addr) -> int:
        """Compare X Index register with Memory"""
        value = cpu.bus[addr]
        if cpu.emulation == 0 and cpu.P.X == 0:
            value |= cpu.bus[addr + 1] << 8
            # TODO workaround: in this case X defines the 16bit mode instead of A
            cpu.PC += 1
        result = cpu.X - value

        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.P.N = 1 if result & 0x8000 else 0
            cpu.P.Z = 1 if (result & 0xFFFF) == 0 else 0
        else:
            cpu.P.N = 1 if result & 0x80 else 0
            cpu.P.Z = 1 if (result & 0xFF) == 0 else 0

        cpu.P.C = 1 if cpu.X >= value else 0

        return 0

    def CPY(self, cpu, addr) -> int:
        """Compare Y Index register with Memory"""
        value = cpu.bus[addr]
        if cpu.emulation == 0 and cpu.P.X == 0:
            value |= cpu.bus[addr + 1] << 8
            # TODO workaround: in this case X defines the 16bit mode instead of A
            cpu.PC += 1
        result = cpu.Y - value

        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.P.N = 1 if result & 0x8000 else 0
            cpu.P.Z = 1 if (result & 0xFFFF) == 0 else 0
        else:
            cpu.P.N = 1 if result & 0x80 else 0
            cpu.P.Z = 1 if (result & 0xFF) == 0 else 0

        cpu.P.C = 1 if cpu.Y >= value else 0

        return 0

    def INC(self, cpu, addr) -> int:
        """Increment Data"""
        opcode = cpu.bus[cpu.current_instruction_PC]
        assert opcode == 0x1A  # TODO other modes not implemented

        cpu.A += 1
        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.A &= 0xFFFF
            cpu.P.N = 1 if cpu.A & 0x8000 else 0
        else:
            cpu.A &= 0xFF
            cpu.P.N = 1 if cpu.A & 0x80 else 0
        cpu.P.Z = 1 if cpu.A == 0 else 0

        return 2

    def INX(self, cpu, addr) -> int:
        """Increment Index Register X"""
        cpu.X += 1
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.X &= 0xFFFF
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
        else:
            cpu.X &= 0xFF
            cpu.P.N = 1 if cpu.X & 0x80 else 0
        cpu.P.Z = 1 if cpu.X == 0 else 0

        return 2

    def INY(self, cpu, addr) -> int:
        """Increment Index Register Y"""
        cpu.Y += 1
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.Y &= 0xFFFF
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
        else:
            cpu.Y &= 0xFF
            cpu.P.N = 1 if cpu.Y & 0x80 else 0
        cpu.P.Z = 1 if cpu.Y == 0 else 0

        return 2

    def ROL(self, cpu, addr) -> int:
        """Rotate Memory or Accumulator Left"""
        opcode = cpu.bus[cpu.current_instruction_PC]
        if opcode == 0x2A:
            # Addressing mode == Accumulator
            value = cpu.A if cpu.P.M == 0 else cpu.A & 0xFF
            temp = (value << 1) | (cpu.P.C & 0x1)
            if cpu.emulation == 0 and cpu.P.M == 0:
                cpu.P.C = 1 if temp > 0xFFFF else 0
                cpu.P.Z = 1 if (temp & 0xFFFF) == 0 else 0
                cpu.P.N = 1 if temp & 0x8000 else 0
                cpu.A = temp & 0xFFFF
            else:
                cpu.P.C = 1 if temp > 0xFF else 0
                cpu.P.Z = 1 if (temp & 0xFF) == 0 else 0
                cpu.P.N = 1 if temp & 0x80 else 0
                cpu.A = temp & 0xFF
        else:
            value = cpu.bus[addr]
            if cpu.emulation == 0 and cpu.P.M == 0:
                value |= cpu.bus[addr + 1] << 8
            temp = (value << 1) | (cpu.P.C & 0x1)
            if cpu.emulation == 0 and cpu.P.M == 0:
                cpu.P.C = 1 if temp > 0xFFFF else 0
                cpu.P.Z = 1 if (temp & 0xFFFF) == 0 else 0
                cpu.P.N = 1 if temp & 0x8000 else 0
                cpu.bus[addr] = temp & 0xFF
                cpu.bus[addr + 1] = (temp >> 8) & 0xFF
            else:
                cpu.P.C = 1 if temp > 0xFF else 0
                cpu.P.Z = 1 if (temp & 0xFF) == 0 else 0
                cpu.P.N = 1 if temp & 0x80 else 0
                cpu.A = temp & 0xFF

        return 0

    def ROR(self, cpu, addr) -> int:
        """Rotate Memory or Accumulator Right"""
        raise


class InstructionSet:
    def __init__(self, cpu) -> None:
        self.instructions = {}
        self.cpu = cpu
        self.load_instructions()

    def load_instructions(self) -> None:
        with open("instructions.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                instruction = Instruction(row)
                self.instructions[instruction.opcode] = instruction

    def execute(self, opcode: int) -> int:
        instruction = self.instructions[opcode]
        print("\033[92mCPU 0x{:02X} {}\033[0m".format(self.cpu.PC - 1, instruction))
        self.cpu.current_instruction_PC = self.cpu.PC - 1
        cycles = instruction(self.cpu)
        return cycles
