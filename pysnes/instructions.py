from collections import deque
import csv
from ctypes import c_int16, c_int8

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
    BRANCH_INSTRUCTIONS = (
        "BCC",
        "BCS",
        "BNE",
        "BEQ",
        "BPL",
        "BMI",
        "BVC",
        "BVS",
        "BRA",
        "BRL",
        "JMP",
        "JML",
        "JSR",
        "JSL",
        "RTS",
        "RTL",
    )

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
        "Stack (RTI)": "implied",
        "Stack (RTL)": "implied",
        "Stack (RTS)": "implied",
        "Block Move": "implied",
        "Accumulator": "accumulator",
    }

    def __init__(self, addressin_mode: str) -> None:
        self.mode_str = self.MODES[addressin_mode]
        try:
            self.addr_mode_cb = getattr(self, self.mode_str)
        except AttributeError:
            self.addr_mode_cb = self.not_implemented

    def __call__(self, cpu) -> int:
        return self.addr_mode_cb(cpu)

    def not_implemented(self, cpu) -> int:
        raise RuntimeError(f"Addressing mode not implemented: {self.mode_str}")

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
        if cpu.current_instruction_mnemonic in self.BRANCH_INSTRUCTIONS:
            # bank = cpu.PB
            # Workaround, PB is not being updated where it should, so it can't be used
            bank = (cpu.PC >> 16) & 0xFF
        else:
            bank = cpu.DB
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

    def absolute_indirect(self, cpu) -> int:
        """
        Effective Address:
        Bank: Program Bank Register (PBR).
        High/Low: The Indirect Address.
        Indirect Address: Located in Bank Zero, at the Operand double byte.
        """
        i_addr = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8
        cpu.PC += 2
        addr = cpu.bus[i_addr] | cpu.bus[i_addr + 1] << 8 | cpu.PC & 0xFF0000
        return addr

    def absolute_indirect_long(self, cpu) -> int:
        """
        Effective Address:
        Bank/High/Low: The 24-bit Indirect Address.
        Indirect Address: Located in Bank Zero, at the Operand double byte.
        """
        i_addr = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8
        cpu.PC += 2
        addr = cpu.bus[i_addr] | cpu.bus[i_addr + 1] << 8 | cpu.bus[i_addr + 2] << 16
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

    def absolute_indexed_indirect(self, cpu) -> int:
        """
        Effective Address:
        Bank: Program Bank Register (PBR).
        High/Low: The Indirect Address.
        Indirect Address: Located in the Program Bank at the sum of the Operand
        double byte and X (16 bits if 65802/65816 native mode, x = 0 ; else 8 bits).
        """
        bank = cpu.PC & 0xFF0000
        operand = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8
        cpu.PC += 2

        # TODO I'm not sure if X is to be masked. Confirm in bsnes
        if cpu.emulation == 0 and cpu.P.X == 0:
            indirect_addr = bank | operand + cpu.X
        else:
            indirect_addr = bank | operand + (cpu.X & 0xFF)

        addr = cpu.bus[indirect_addr] | cpu.bus[indirect_addr + 1] << 8 | bank

        return addr

    def absolute_indexed_x(self, cpu) -> int:
        """
        Absolute Indexed, X Addressing
        Effective Address: The Data Bank Register is concatenated to the 16-bit Operand:
        the 24-bit result is added to X (16 bits if 65802/65816 native mode, x = 0; else 8).
        """
        indirect_addr = (cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8) + cpu.X
        cpu.PC += 2
        addr = (indirect_addr & 0xFFFF) | cpu.DB << 16
        # if cpu.emulation == 0 and cpu.P.X == 0:
        #    addr = indirect_addr + (cpu.X & 0xFFFF)
        # else:
        #    addr = indirect_addr + (cpu.X & 0xFF)
        return addr

    def absolute_indexed_y(self, cpu) -> int:
        """
        Absolute Indexed, Y Addressing
        Effective Address: The Data Bank Register is concatenated to the 16-bit Operand:
        the 24-bit result is added to Y (16 bits if 65802/65816 native mode, x = 0; else 8).
        """
        indirect_addr = (cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8) + cpu.Y
        cpu.PC += 2
        addr = (indirect_addr & 0xFFFF) | cpu.DB << 16
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
        addr = cpu.PC
        # BRK is one byte, but program counter value pushed onto stack is
        # incremented by 2 allowing for optional signature byte.
        cpu.PC += 1
        return addr

    def stack_absolute(self, cpu) -> int:
        """
        Stack (Absolute) Addressing
        Source of data to be pushed: The 16-bit operand, which can be either an absolute address or immediate data.
        Destination effective address: Provided by Stack Pointer.
        """
        addr = cpu.PC
        cpu.PC += 2
        return addr

    def stack_dp_indirect(self, cpu) -> int:
        """
        Stack (Direct Page Indirect) Addressing

        Source of data to be pushed: The 16-bit indirect address (or double-byte data) located at the sum of the Operand
        byte plus the Direct Page Register, in Bank Zero.
        Destination effective address: Provided by Stack Pointer.
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1
        addr = (operand + cpu.D) & 0xFFFF
        return addr

    def stack_pc_relative_long(self, cpu) -> int:
        """
        Stack (Program Counter Relative) Addressing

        Source of data to be pushed: The 16-bit sum of the 16-bit Operand plus the 16-bit Program Counter.
        (Note that the 16-bit Operand which is added is the object code operand; the operand used in the
        instruction's syntax required by most assemblers is a label which is converted to the object operand.)
        Destination Effective Address: Provided by Stack Pointer.
        """
        offset = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8
        cpu.PC += 2
        addr = cpu.PC + c_int16(offset).value
        return addr & 0xFFFF

    def program_counter_relative(self, cpu) -> int:
        """
        Bank: Program Bank Register (PBR).
        High/Low: The Operand byte, a two's complement signed value, is sign-extended to 16 bits,
        then added to the Program Counter (its value is the address of the opcode following this one).
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1  # TODO not sure...
        # Sign extension
        # if operand & 0x80:  # Negative
        #    operand |= 0xFF00
        # addr = (operand + cpu.PC) & 0xFFFF | cpu.PB << 16
        operand = c_int8(operand)
        addr = operand.value + cpu.PC
        return addr

    def program_counter_relative_long(self, cpu) -> int:
        """
        Effective Address:
        Bank: Program Bank Register (PBR).
        High/Low: The Operand double byte, a two's complement signed value, is added
        to the Program Counter (its value is the address of the opcode following this one).
        """
        # operand_tc = cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8
        operand = c_int16(cpu.bus[cpu.PC] | cpu.bus[cpu.PC + 1] << 8)

        cpu.PC += 2  # TODO not sure if this should be done before or after

        # operand is in two's complement format, convert it to an int
        # operand = (-1) * (0xFFFF + 1 + operand_tc)
        # assert -32768 <= operand <= 32767
        # addr = cpu.PC + operand

        # return addr | cpu.PB << 16

        addr = operand.value + cpu.PC
        return addr

    def direct_page(self, cpu) -> int:
        """
        Direct Page Addressing

        Effective Address:
        Bank: Zero
        High/Low: Direct Page Register plus Operand byte.
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1
        addr = cpu.D + operand
        return addr

    def dp_indirect(self, cpu) -> int:
        """
        Effective Address:

        Bank: Data Bank Register (DBR)
        High/Low: The 16-bit Indirect Address
        Indirect Address: The Operand byte plus the Direct Page Register, in Bank Zero
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1
        indirect_address = operand + cpu.D
        addr = cpu.bus[indirect_address] | cpu.bus[indirect_address + 1] << 8
        return addr | cpu.DB << 16

    def dp_indexed_x(self, cpu) -> int:
        """
        Direct Page Indexed, X Addressing

        Effective Address:
        Bank: Zero
        High/Low: Direct Page Register plus Operand byte plus X (16 bits if 65802/65816 native mode, x = 0; else 8 bits).
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1
        if cpu.emulation == 0 and cpu.P.X == 0:
            addr = cpu.D + operand + cpu.X
        else:
            addr = cpu.D + operand + (cpu.X & 0xFF)
        return addr

    def dp_indexed_y(self, cpu) -> int:
        """
        Direct Page Indexed, Y Addressing

        Effective Address:
        Bank: Zero
        High/Low: Direct Page Register plus Operand byte plus Y (16 bits if 65802/65816 native mode, x = 0; else 8 bits).
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1
        if cpu.emulation == 0 and cpu.P.X == 0:
            addr = cpu.D + operand + cpu.Y
        else:
            addr = cpu.D + operand + (cpu.Y & 0xFF)
        return addr

    def dp_indexed_indirect_x(self, cpu) -> int:
        """
        Direct Page Indexed Indirect, X Addressing

        Bank: Data bank register
        High/Low: The indirect address
        Indirect Address: Located in the direct page at the sum of the direct page register, the operand byte,
        and X (16 bits if 65802/65816 native mode, x = 0; else 8), in bank 0.
        """
        assert cpu.emulation == 0
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1

        x = cpu.X if cpu.P.X == 0 else cpu.X & 0xFF
        indirect_addr = cpu.D + operand + x

        addr = cpu.bus[indirect_addr] | cpu.bus[indirect_addr + 1] << 8 | cpu.DB << 16

        return addr

    def dp_indirect_indexed_y(self, cpu) -> int:
        """
        Direct Page Indirect Indexed, Y Addressing

        Effective Address: Found by concatenating the data bank to the double-byte indirect address,
        then adding Y (16 bits if 65802/65816 native mode, x = 0; else 8).
        Indirect Address: Located in the Direct Page at the sum of the
        direct page register and the operand byte, in bank zero.
        """
        assert cpu.emulation == 0
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1

        indirect_addr = cpu.D + operand
        addr = cpu.bus[indirect_addr] | cpu.bus[indirect_addr + 1] << 8 | cpu.DB << 16
        y = cpu.Y if cpu.P.X == 0 else cpu.Y & 0xFF

        return addr + y

    def dp_indirect_long(self, cpu) -> int:
        """
        Effective Address:
        Bank/High/Low: The 24-bit Indirect Address
        Indirect Address: The Operand byte plus the Direct Page Register, in Bank Zero
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1
        indirect_addr = cpu.D + operand
        addr = (
            cpu.bus[indirect_addr]
            | cpu.bus[indirect_addr + 1] << 8
            | cpu.bus[indirect_addr + 2] << 16
        )
        return addr

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
        # y = cpu.Y if cpu.P.X == 0 else cpu.Y & 0xFF
        addr = indirect_addr + cpu.Y

        return addr

    def stack_relative(self, cpu) -> int:
        """
        Stack Relative Addressing

        Bank: Zero
        High:Low: The 16-bit sum of the 8-bit Operand and the 16-bit Stack Pointer.
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1
        addr = (operand + cpu.S) & 0xFFFF
        return addr

    def sr_indirect_indexed_y(self, cpu) -> int:
        """
        Stack Relative Indirected Indexed, Y Addressing

        Effective Address: The Data Bank Register is concatenated to the Indirect Address: the 24-bit
        result is added to Y (16 bits if 65802/65816 native mode, x = 0; else 8 bits).
        Indirect Address: Located at the 16-bit sum of the 8-bit Operand and the 16-bit Stack Pointer.
        """
        operand = cpu.bus[cpu.PC]
        cpu.PC += 1

        offset = (operand + cpu.S) & 0xFFFF
        indirect_addr = (
            cpu.bus[offset] | cpu.bus[offset + 1] << 8  # | cpu.bus[offset + 2] << 16
        )
        addr = (indirect_addr | cpu.DB << 16) + cpu.Y
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

        # Hook up addressing mode and mnemonic methods
        self.setup()

    def __str__(self) -> str:
        opcode = "0x{:02X}".format(self.opcode)
        return f"{opcode} {self.mnemonic} {self.addressing_mode}"

    def __call__(self, cpu) -> int:
        # Saved to be used in the addressing mode
        cpu.current_instruction_mnemonic = self.mnemonic

        # Decode phase: fetch additional information before execution

        # TODO for now I'm just returning the addr to the operand,
        # but it'll have to return the number of cycles used eventually
        addr = self.addressing_mode_cb(cpu)

        # Execute instruction phase
        return self.instruction_cb(cpu, addr)

    def setup(self) -> None:
        """Load addessing mode and Mnemonic methods"""
        self.addressing_mode_cb = AddressingMode(self.addressing_mode)
        try:
            self.instruction_cb = getattr(self, self.mnemonic)
        except AttributeError:
            self.instruction_cb = self.mnemonic_not_implemented

    def mnemonic_not_implemented(self, cpu, addr):
        cpu.instruction_set.print_trace()
        raise RuntimeError(f"Mnemonic not implemented: {self.mnemonic}")

    def NOP(self, cpu, addr):
        """No Operation"""
        return 2

    def MVP(self, cpu, addr):
        """Move Positive destination > source"""
        dest_bank = cpu.bus[cpu.PC]
        cpu.PC += 1
        source_bank = cpu.bus[cpu.PC]
        cpu.PC += 1
        cycles = (cpu.A + 1) * 7

        while cpu.A >= 0:
            cpu.bus[cpu.Y | dest_bank << 16] = cpu.bus[cpu.X | source_bank << 16]
            if cpu.emulation == 0 and cpu.P.X == 0:
                cpu.X = (cpu.X - 1) & 0xFFFF
                cpu.Y = (cpu.Y - 1) & 0xFFFF
            else:
                cpu.X = (cpu.X & 0xFF00) | ((cpu.X - 1) & 0xFF)
                cpu.Y = (cpu.Y & 0xFF00) | ((cpu.Y - 1) & 0xFF)

            cpu.A -= 1  # Let it wrap to negative

        cpu.A = 0xFFFF

        return cycles

    def MVN(self, cpu, addr):
        """Move Negative destination < source"""
        dest_bank = cpu.bus[addr + 0]
        source_bank = cpu.bus[addr + 1]
        cpu.PC += 2
        cycles = (cpu.A + 1) * 7

        while cpu.A >= 0:
            cpu.bus[cpu.Y | dest_bank << 16] = cpu.bus[cpu.X | source_bank << 16]
            if cpu.emulation == 0 and cpu.P.X == 0:
                cpu.X = (cpu.X + 1) & 0xFFFF
                cpu.Y = (cpu.Y + 1) & 0xFFFF
            else:
                cpu.X = (cpu.X & 0xFF00) | ((cpu.X + 1) & 0xFF)
                cpu.Y = (cpu.Y & 0xFF00) | ((cpu.Y + 1) & 0xFF)

            cpu.A -= 1  # Let it wrap to negative

        cpu.A = 0xFFFF

        return cycles

    def BRK(self, cpu, addr):
        """Software Break"""
        assert cpu.emulation == 0
        # the program counter bank register is pushed onto stack.
        cpu.bus[cpu.S] = cpu.PB
        cpu.S -= 1
        # the program counter is incremented by two and pushed on the stack.
        cpu.PC += 2  # TODO verify - at this point was already incremented by 1
        cpu.bus[cpu.S] = cpu.PC >> 8
        cpu.S -= 1
        cpu.bus[cpu.S] = cpu.PC & 0xFF
        cpu.S -= 1
        # the status register is pushed onto the stack
        cpu.bus[cpu.S] = cpu.P.get(cpu.emulation)
        cpu.S -= 1
        # the interrupt disable flag is set.
        cpu.P.I = 1
        # the decimal mode flag is cleared.
        cpu.P.D = 0
        # the program bank register is cleared to zero.
        cpu.PB = 0
        # the program counter is loaded from the break vector at $FFE6-$FFE7.
        cpu.PC = cpu.hardware_vectors["native"]["BRK"]

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

    def BIT(self, cpu, addr) -> int:
        """Test Memory Bits against Accumulator"""
        if cpu.emulation == 0 and cpu.P.M == 0:
            data = cpu.bus[addr] | cpu.bus[addr + 1] << 8
            cpu.P.Z = 1 if (data & cpu.A) == 0 else 0
            if cpu.opcode != 0x89:  # Immediate
                cpu.P.V = 1 if data & 0x4000 else 0
                cpu.P.N = 1 if data & 0x8000 else 0
        else:
            data = cpu.bus[addr]
            cpu.P.Z = 1 if (data & (cpu.A & 0xFF)) == 0 else 0
            if cpu.opcode != 0x89:  # Immediate
                cpu.P.V = 1 if data & 0x40 else 0
                cpu.P.N = 1 if data & 0x80 else 0

        return 0

    def TRB(self, cpu, addr) -> int:
        """Test and Reset Memory Bits"""
        if cpu.emulation == 0 and cpu.P.M == 0:
            data = cpu.bus[addr] | cpu.bus[addr + 1] << 8
            A = cpu.A & 0xFFFF
            cpu.P.Z = int(data & A == 0)
            data &= ~A
            cpu.bus[addr + 0] = (data >> 0) & 0xFF
            cpu.bus[addr + 1] = (data >> 8) & 0xFF
        else:
            data = cpu.bus[addr]
            A = cpu.A & 0xFF
            cpu.P.Z = int(data & A == 0)
            data &= ~A
            cpu.bus[addr + 0] = (data >> 0) & 0xFF

        return 0

    def TSB(self, cpu, addr) -> int:
        """Test and Set Memory Bits"""
        if cpu.emulation == 0 and cpu.P.M == 0:
            data = cpu.bus[addr] | cpu.bus[addr + 1] << 8
            A = cpu.A & 0xFFFF
            cpu.P.Z = int(data & A == 0)
            data |= A
            cpu.bus[addr + 0] = (data >> 0) & 0xFF
            cpu.bus[addr + 1] = (data >> 8) & 0xFF
        else:
            data = cpu.bus[addr]
            A = cpu.A & 0xFF
            cpu.P.Z = int(data & A == 0)
            data |= A
            cpu.bus[addr + 0] = (data >> 0) & 0xFF

        return 0

    def AND(self, cpu, addr) -> int:
        """And Accumulator with Memory"""
        if cpu.emulation == 0 and cpu.P.M == 0:
            low = cpu.bus[addr + 0] & 0xFF
            high = cpu.bus[addr + 1] & 0xFF
            value = low | high << 8
            cpu.A &= value
            cpu.P.N = 1 if cpu.A & 0x8000 else 0
            cpu.P.Z = 1 if (cpu.A & 0xFFFF) == 0 else 0
        else:
            value = cpu.bus[addr] & 0xFF
            cpu.A = (cpu.A & 0xFF00) | (cpu.A & value)
            cpu.P.N = 1 if cpu.A & 0x80 else 0
            cpu.P.Z = 1 if (cpu.A & 0xFF) == 0 else 0

        return 0

    def EOR(self, cpu, addr) -> int:
        """Exclusive-OR Accumulator with Memory"""
        if cpu.emulation == 0 and cpu.P.M == 0:
            data = cpu.bus[addr] | cpu.bus[addr + 1] << 8
            cpu.A ^= data
            cpu.P.N = 1 if cpu.A & 0x8000 else 0
            cpu.P.Z = 1 if (cpu.A & 0xFFFF) == 0 else 0
        else:
            data = cpu.bus[addr]
            cpu.A = (cpu.A & 0xFF00) | (cpu.A ^ data)
            cpu.P.N = 1 if cpu.A & 0x80 else 0
            cpu.P.Z = 1 if (cpu.A & 0xFF) == 0 else 0

        return 0

    def LSR(self, cpu, addr) -> int:
        """Logical Shift Right"""
        opcode = cpu.bus[cpu.current_instruction_PC]
        if opcode == 0x4A:  # Accumulator
            value = cpu.A
        else:
            if cpu.emulation == 0 and cpu.P.M == 0:
                value = cpu.bus[addr] | cpu.bus[addr + 1] << 8
            else:
                value = cpu.bus[addr]

        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.P.C = 1 if value & 0x0001 else 0
            value = (value >> 1) & 0xFFFF
            cpu.P.Z = 1 if value == 0 else 0
            cpu.P.N = 1 if value & 0x8000 else 0
        else:
            cpu.P.C = 1 if value & 0x01 else 0
            value = (value & 0xFF00) | (value >> 1) & 0xFF
            cpu.P.Z = 1 if value == 0 else 0
            cpu.P.N = 1 if value & 0x80 else 0

        if opcode == 0x4A:  # Accumulator
            cpu.A = value
        else:
            if cpu.emulation == 0 and cpu.P.M == 0:
                cpu.bus[addr + 0] = (value >> 0) & 0xFF
                cpu.bus[addr + 1] = (value >> 8) & 0xFF
            else:
                cpu.bus[addr] = value & 0xFF

        return 0

    def ASL(self, cpu, addr) -> int:
        """Arithmetic Shift Left"""
        if self.opcode == 0x0A:  # Accumulator
            value = cpu.A
        else:
            if cpu.emulation == 0 and cpu.P.M == 0:
                value = cpu.bus[addr] | cpu.bus[addr + 1] << 8
            else:
                value = cpu.bus[addr]

        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.P.C = 1 if value & 0x8000 else 0
            value = (value << 1) & 0xFFFF
            cpu.P.Z = 1 if value == 0 else 0
            cpu.P.N = 1 if value & 0x8000 else 0
        else:
            cpu.P.C = 1 if value & 0x80 else 0
            value = (value & 0xFF00) | (value << 1) & 0xFF
            cpu.P.Z = 1 if value == 0 else 0
            cpu.P.N = 1 if value & 0x80 else 0

        if self.opcode == 0x0A:  # Accumulator
            cpu.A = value
        else:
            if cpu.emulation == 0 and cpu.P.M == 0:
                cpu.bus[addr + 0] = (value >> 0) & 0xFF
                cpu.bus[addr + 1] = (value >> 8) & 0xFF
            else:
                cpu.bus[addr] = value & 0xFF

        return 0

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
        if cpu.emulation:
            cpu.P.X = 1
            cpu.P.M = 1
            cpu.X &= 0xFF
            cpu.Y &= 0xFF
            cpu.S = cpu.S & 0xFF | 0x0100

        return 2

    def REP(self, cpu, addr) -> int:
        """Reset Status Bits"""
        mask = cpu.bus[addr]
        status = cpu.P.get(cpu.emulation)
        cpu.P.set(status & ~mask, cpu.emulation)

        if cpu.emulation:
            cpu.P.M = 1
            cpu.P.X = 1

        if cpu.P.X:
            # Clear high byte
            cpu.X &= 0xFF
            cpu.Y &= 0xFF

        return 3

    def SEP(self, cpu, addr) -> int:
        """Set Status Bits"""
        mask = cpu.bus[addr]
        status = cpu.P.get(cpu.emulation)
        cpu.P.set(status | mask, cpu.emulation)

        if cpu.emulation:
            cpu.P.M = 1
            cpu.P.X = 1

        if cpu.P.X:
            # Clear high byte
            cpu.X &= 0xFF
            cpu.Y &= 0xFF

        return 3

    def STX(self, cpu, addr) -> int:
        """Store X Register to Memory"""
        cpu.bus[addr] = cpu.X & 0xFF
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.bus[addr + 1] = (cpu.X >> 8) & 0xFF

        return 0

    def STY(self, cpu, addr) -> int:
        """Store Y Register to Memory"""
        cpu.bus[addr] = cpu.Y & 0xFF
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.bus[addr + 1] = (cpu.Y >> 8) & 0xFF

        return 0

    def STZ(self, cpu, addr) -> int:
        """Store Zero byte to Memory"""
        cpu.bus[addr] = 0
        if cpu.emulation == 0 and cpu.P.M == 0:  # 16 bit mode
            cpu.bus[addr + 1] = 0
        return 4

    def LDA(self, cpu, addr) -> int:
        """Load the Accumulator with Memory"""
        cycles = 2  # TODO it depends on addressing mode and processor flags

        if cpu.emulation == 0 and cpu.P.M == 0:
            cycles += 1
            cpu.A = (cpu.bus[addr] & 0xFF) | cpu.bus[addr + 1] << 8
            cpu.P.Z = 1 if cpu.A & 0xFFFF == 0 else 0
            cpu.P.N = 1 if cpu.A & 0x8000 else 0
        else:
            cpu.A = (cpu.A & 0xFF00) | (cpu.bus[addr] & 0xFF)  # Preserve high byte
            cpu.P.Z = 1 if cpu.A & 0xFF == 0 else 0
            cpu.P.N = 1 if cpu.A & 0x80 else 0

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
        cpu.P.N = 1 if cpu.D & 0x8000 else 0
        cpu.P.Z = 1 if cpu.D & 0xFFFF == 0 else 0

        return 2

    def TDC(self, cpu, addr) -> int:
        """Transfer Direct Page Register to Accumulator"""
        cpu.A = cpu.D
        cpu.P.N = 1 if cpu.A & 0x8000 else 0
        cpu.P.Z = 1 if cpu.A & 0xFFFF == 0 else 0

        return 2

    def TCS(self, cpu, addr) -> int:
        """Transfer Accumulator to Stack Pointer"""
        if cpu.emulation == 0:
            cpu.S = cpu.A
        else:
            cpu.S = (cpu.A & 0xFF) | (0x01 << 8)

        return 2

    def TSC(self, cpu, addr) -> int:
        """Transfer Stack Pointer to Accumulator"""
        if cpu.emulation == 0:
            cpu.A = cpu.S
        else:
            cpu.A = (cpu.S & 0xFF) | (0x01 << 8)

        cpu.P.N = 1 if cpu.A & 0x8000 else 0
        cpu.P.Z = 1 if cpu.A & 0xFFFF == 0 else 0

        return 2

    def LDX(self, cpu, addr) -> int:
        """Load X Register from Memory"""
        cpu.X = cpu.bus[addr]
        cpu.P.N = 1 if cpu.X & 0x80 else 0
        cpu.P.Z = 1 if (cpu.X & 0xFF) == 0 else 0
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.X |= cpu.bus[addr + 1] << 8
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
            cpu.P.Z = 1 if (cpu.X & 0xFFFF) == 0 else 0

        # Workaround
        if self.opcode == 0xA2:  # Immediate
            if cpu.P.M == 0 and cpu.P.X == 1:
                cpu.PC -= 1
            elif cpu.P.M == 1 and cpu.P.X == 0:
                cpu.PC += 1

        return 0

    def LDY(self, cpu, addr) -> int:
        """Load Y Register from Memory"""
        cpu.Y = cpu.bus[addr]
        cpu.P.N = 1 if cpu.Y & 0x80 else 0
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.Y |= cpu.bus[addr + 1] << 8
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
        cpu.P.Z = 1 if cpu.Y == 0 else 0

        # Workaround
        if self.opcode == 0xA0:  # Immediate
            if cpu.P.M == 0 and cpu.P.X == 1:
                cpu.PC -= 1
            elif cpu.P.M == 1 and cpu.P.X == 0:
                cpu.PC += 1

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

    def TXY(self, cpu, addr) -> int:
        """Transfer X to Y"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.Y = cpu.X
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
            cpu.P.Z = 1 if cpu.Y & 0xFFFF == 0 else 0
        else:
            cpu.Y = (cpu.Y & 0xFF00) | (cpu.X & 0xFF)
            cpu.P.N = 1 if cpu.Y & 0x80 else 0
            cpu.P.Z = 1 if cpu.Y & 0xFF == 0 else 0

        return 2

    def TYX(self, cpu, addr) -> int:
        """Transfer Y to X"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.X = cpu.Y
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
            cpu.P.Z = 1 if cpu.X & 0xFFFF == 0 else 0
        else:
            cpu.X = (cpu.X & 0xFF00) | (cpu.Y & 0xFF)
            cpu.P.N = 1 if cpu.X & 0x80 else 0
            cpu.P.Z = 1 if cpu.X & 0xFF == 0 else 0

        return 2

    def TXS(self, cpu, addr) -> int:
        """Transfer X index register to the Stack pointer"""
        if cpu.emulation:
            cpu.S = cpu.S & 0xFF00 | cpu.X & 0xFF
        else:
            cpu.S = cpu.X

        return 2

    def TSX(self, cpu, addr) -> int:
        """Transfer Stack pointer to the X index register"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.X = cpu.S
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
            cpu.P.Z = 1 if cpu.X & 0xFFFF == 0 else 0
        else:
            cpu.X = (cpu.X & 0xFF00) | (cpu.S & 0xFF)
            cpu.P.N = 1 if cpu.X & 0x80 else 0
            cpu.P.Z = 1 if cpu.X & 0xFF == 0 else 0

        return 2

    def ADC(self, cpu, addr) -> int:
        """Add with carry - Tested with CPUADC.sfc"""
        if cpu.emulation == 0 and cpu.P.M == 0:  # 16 bit
            A = cpu.A & 0xFFFF
            data = cpu.bus[addr] | cpu.bus[addr + 1] << 8

            if cpu.P.D == 0:
                result = A + data + cpu.P.C
            else:
                result = (A & 0x000F) + (data & 0x000F) + (cpu.P.C << 0)
                if result > 0x0009:
                    result += 0x0006
                cpu.P.C = 1 if result > 0x000F else 0
                result = (
                    (A & 0x00F0) + (data & 0x00F0) + (cpu.P.C << 4) + (result & 0x000F)
                )
                if result > 0x009F:
                    result += 0x0060
                cpu.P.C = 1 if result > 0x00FF else 0
                result = (
                    (A & 0x0F00) + (data & 0x0F00) + (cpu.P.C << 8) + (result & 0x00FF)
                )
                if result > 0x09FF:
                    result += 0x0600
                cpu.P.C = result > 0x0FFF
                result = (
                    (A & 0xF000) + (data & 0xF000) + (cpu.P.C << 12) + (result & 0x0FFF)
                )

            cpu.P.V = 1 if ~(A ^ data) & (A ^ result) & 0x8000 else 0
            if cpu.P.D and result > 0x9FFF:
                result += 0x6000
            cpu.P.C = 1 if result > 0xFFFF else 0
            cpu.P.Z = 1 if (result & 0xFFFF) == 0 else 0
            cpu.P.N = 1 if result & 0x8000 else 0

            cpu.A = result & 0xFFFF
        else:  # 8 bit
            A = cpu.A & 0xFF
            data = cpu.bus[addr]

            if cpu.P.D == 0:
                result = A + data + cpu.P.C
            else:
                result = (A & 0x0F) + (data & 0x0F) + (cpu.P.C << 0)
                if result > 0x09:
                    result += 0x06
                cpu.P.C = 1 if result > 0x0F else 0
                result = (A & 0xF0) + (data & 0xF0) + (cpu.P.C << 4) + (result & 0x0F)

            cpu.P.V = 1 if ~(A ^ data) & (A ^ result) & 0x80 else 0
            if cpu.P.D and result > 0x9F:
                result += 0x60
            cpu.P.C = 1 if result > 0xFF else 0
            cpu.P.Z = 1 if (result & 0xFF) == 0 else 0
            cpu.P.N = 1 if result & 0x80 else 0

            cpu.A = cpu.A & 0xFF00 | result & 0xFF

        return 0

    def SBC(self, cpu, addr) -> int:
        """Subtract from Accumulator"""
        if cpu.emulation == 0 and cpu.P.M == 0:  # 16 bit
            A = cpu.A & 0xFFFF
            data = ~(cpu.bus[addr] | cpu.bus[addr + 1] << 8) & 0xFFFF

            if cpu.P.D == 0:
                result = A + data + cpu.P.C
            else:
                result = (A & 0x000F) + (data & 0x000F) + (cpu.P.C << 0)
                if result <= 0x000F:
                    result -= 0x0006
                cpu.P.C = 1 if result > 0x000F else 0
                result = (
                    (A & 0x00F0) + (data & 0x00F0) + (cpu.P.C << 4) + (result & 0x000F)
                )
                if result <= 0x00FF:
                    result -= 0x0060
                cpu.P.C = 1 if result > 0x00FF else 0
                result = (
                    (A & 0x0F00) + (data & 0x0F00) + (cpu.P.C << 8) + (result & 0x00FF)
                )
                if result <= 0x0FFF:
                    result -= 0x0600
                cpu.P.C = result > 0x0FFF
                result = (
                    (A & 0xF000) + (data & 0xF000) + (cpu.P.C << 12) + (result & 0x0FFF)
                )

            cpu.P.V = 1 if ~(A ^ data) & (A ^ result) & 0x8000 else 0
            if cpu.P.D and result <= 0xFFFF:
                result -= 0x6000
            cpu.P.C = 1 if result > 0xFFFF else 0
            cpu.P.Z = 1 if (result & 0xFFFF) == 0 else 0
            cpu.P.N = 1 if result & 0x8000 else 0

            cpu.A = result & 0xFFFF
        else:  # 8 bit
            A = cpu.A & 0xFF
            data = ~(cpu.bus[addr]) & 0xFF

            if cpu.P.D == 0:
                result = A + data + cpu.P.C
            else:
                result = (A & 0x0F) + (data & 0x0F) + (cpu.P.C << 0)
                if result <= 0x0F:
                    result -= 0x06
                cpu.P.C = 1 if result > 0x0F else 0
                result = (A & 0xF0) + (data & 0xF0) + (cpu.P.C << 4) + (result & 0x0F)

            cpu.P.V = 1 if ~(A ^ data) & (A ^ result) & 0x80 else 0
            if cpu.P.D and result <= 0xFF:
                result -= 0x60
            cpu.P.C = 1 if result > 0xFF else 0
            cpu.P.Z = 1 if (result & 0xFF) == 0 else 0
            cpu.P.N = 1 if result & 0x80 else 0

            cpu.A = cpu.A & 0xFF00 | result & 0xFF

        return 0

    def DEX(self, cpu, addr) -> int:
        """Decrement Index Register X"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.X = (cpu.X - 1) & 0xFFFF
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
        else:
            cpu.X = (cpu.X & 0xFF00) | ((cpu.X & 0xFF) - 1) & 0xFF
            cpu.P.N = 1 if cpu.X & 0x80 else 0
        cpu.P.Z = 1 if cpu.X == 0 else 0

        return 2

    def DEY(self, cpu, addr) -> int:
        """Decrement Index Register Y"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.Y = (cpu.Y - 1) & 0xFFFF
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
        else:
            cpu.Y = (cpu.Y & 0xFF00) | ((cpu.Y & 0xFF) - 1) & 0xFF
            cpu.P.N = 1 if cpu.Y & 0x80 else 0
        cpu.P.Z = 1 if cpu.Y == 0 else 0

        return 2

    def BRA(self, cpu, addr) -> int:
        """Branch Always"""
        cpu.PC = addr
        return 0

    def BRL(self, cpu, addr) -> int:
        """Branch Always Long"""
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

    def JMP(self, cpu, addr) -> int:
        """Jump to New Location"""
        cpu.PC = addr
        return 0

    def JSR(self, cpu, addr) -> int:
        """Jump to Subroutine"""
        pc = cpu.PC - 1

        if self.opcode == 0x20:  # Absolute
            # PC high byte
            cpu.bus[cpu.S] = (pc >> 8) & 0xFF
            cpu.S -= 1
            # PC low byte
            cpu.bus[cpu.S] = pc & 0xFF
            cpu.S -= 1
            # Jump to addr
            cpu.PC = addr
        elif self.opcode == 0x22:  # Absolute long
            # Program bank
            cpu.bus[cpu.S] = (pc >> 16) & 0xFF  # cpu.PB
            cpu.S -= 1
            # PC high byte
            cpu.bus[cpu.S] = (pc >> 8) & 0xFF
            cpu.S -= 1
            # PC low byte
            cpu.bus[cpu.S] = pc & 0xFF
            cpu.S -= 1
            # Jump to addr
            cpu.PC = addr
            # Copied this from bsnes
            if cpu.emulation:
                cpu.S = 0x0100 | cpu.S & 0xFF
        elif self.opcode == 0xFC:  # Absolute Indexed Indirect
            # PC high byte
            cpu.bus[cpu.S] = (pc >> 8) & 0xFF
            cpu.S -= 1
            # PC low byte
            cpu.bus[cpu.S] = pc & 0xFF
            cpu.S -= 1
            # Jump to addr
            cpu.PC = addr
            # Copied this from bsnes
            if cpu.emulation:
                cpu.S = 0x0100 | cpu.S & 0xFF

        return 0

    def RTS(self, cpu, addr) -> int:
        """Return from Subroutine"""
        cpu.S += 1
        low = cpu.bus[cpu.S]
        cpu.S += 1
        high = cpu.bus[cpu.S]
        cpu.PC = (low | high << 8) + 1
        return 6

    def RTL(self, cpu, addr) -> int:
        """Return from Subroutine Long"""
        cpu.S += 1
        low = cpu.bus[cpu.S]
        cpu.S += 1
        high = cpu.bus[cpu.S]
        cpu.S += 1
        bank = cpu.bus[cpu.S]
        addr = (low | high << 8) + 1
        cpu.PC = addr | bank << 16
        return 6

    def RTI(self, cpu, addr) -> int:
        """Return from Interrupt"""
        # P register
        cpu.S += 1
        cpu.P.set(cpu.bus[cpu.S], cpu.emulation)
        if cpu.emulation:
            cpu.P.X = 1
            cpu.P.M = 1
        if cpu.P.X:
            cpu.X &= 0xFF
            cpu.Y &= 0xFF
        # Low byte
        cpu.S += 1
        low = cpu.bus[cpu.S]
        if cpu.emulation:
            # High byte
            cpu.S += 1
            high = cpu.bus[cpu.S]
            bank = 0
        else:
            # High byte and bank
            cpu.S += 1
            high = cpu.bus[cpu.S]
            cpu.S += 1
            bank = cpu.bus[cpu.S]
        addr = low | high << 8  # + 1
        cpu.PC = addr | bank << 16
        return 0

    def PHA(self, cpu, addr) -> int:
        """Push Accumulator"""
        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.bus[cpu.S] = cpu.A >> 8
            cpu.S -= 1
        cpu.bus[cpu.S] = cpu.A & 0xFF
        cpu.S -= 1
        return 0

    def PLA(self, cpu, addr) -> int:
        """Pull Accumulator"""
        cpu.S += 1
        cpu.A = (cpu.A & 0xFF00) | (cpu.bus[cpu.S] & 0xFF)  # Dont change high byte
        cpu.P.N = 1 if cpu.A & 0x80 else 0
        cpu.P.Z = 1 if (cpu.A & 0xFF) == 0 else 0
        if cpu.emulation == 0 and cpu.P.M == 0:
            cpu.S += 1
            cpu.A = (cpu.A & 0xFF) | (cpu.bus[cpu.S] << 8)
            cpu.P.N = 1 if cpu.A & 0x8000 else 0
            cpu.P.Z = 1 if (cpu.A & 0xFFFF) == 0 else 0

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

        if cpu.emulation:
            cpu.P.M = 1
            cpu.P.X = 1

        if cpu.P.X:
            # Clear high byte
            cpu.X &= 0xFF
            cpu.Y &= 0xFF

        return 0

    def PEA(self, cpu, addr) -> int:
        """Push Effective Absolute Address"""
        low = cpu.bus[addr + 0]
        high = cpu.bus[addr + 1]
        cpu.bus[cpu.S] = high
        cpu.S -= 1
        cpu.bus[cpu.S] = low
        cpu.S -= 1
        if cpu.emulation:
            cpu.S = 0x0100 | cpu.S & 0xFF
        return 5

    def PEI(self, cpu, addr) -> int:
        """Push Effective Indirect Address"""
        low = cpu.bus[addr + 0]
        high = cpu.bus[addr + 1]
        cpu.bus[cpu.S] = high
        cpu.S -= 1
        cpu.bus[cpu.S] = low
        cpu.S -= 1
        if cpu.emulation:
            cpu.S = 0x0100 | cpu.S & 0xFF
        return 0

    def PER(self, cpu, addr) -> int:
        """Push effective PC Relative Indirect Address"""
        low = (addr >> 0) & 0xFF
        high = (addr >> 8) & 0xFF
        cpu.bus[cpu.S] = high
        cpu.S -= 1
        cpu.bus[cpu.S] = low
        cpu.S -= 1
        if cpu.emulation:
            cpu.S = 0x0100 | cpu.S & 0xFF
        return 6

    def PHB(self, cpu, addr) -> int:
        """Push Data Bank register"""
        cpu.bus[cpu.S] = cpu.DB
        cpu.S -= 1
        return 3

    def PLB(self, cpu, addr) -> int:
        """Pulls a byte off the stack into the data bank register"""
        cpu.S += 1
        cpu.DB = cpu.bus[cpu.S]
        cpu.P.N = 1 if cpu.DB & 0x80 else 0
        cpu.P.Z = 1 if (cpu.DB & 0xFF) == 0 else 0
        return 0

    def PHD(self, cpu, addr) -> int:
        """Pushes the 16 bit contents of the direct page register on stack"""
        cpu.bus[cpu.S] = (cpu.D >> 8) & 0xFF
        cpu.S -= 1
        cpu.bus[cpu.S] = (cpu.D >> 0) & 0xFF
        cpu.S -= 1
        return 4

    def PLD(self, cpu, addr) -> int:
        """Pulls a sixteen bit value off stack into the direct page register"""
        cpu.S += 1
        low = cpu.bus[cpu.S]
        cpu.S += 1
        high = cpu.bus[cpu.S]
        cpu.D = low | high << 8
        cpu.P.N = 1 if cpu.D & 0x8000 else 0
        cpu.P.Z = 1 if (cpu.D & 0xFFFF) == 0 else 0
        return 0

    def PHK(self, cpu, addr) -> int:
        """Pushes the 8 bit contents of the program bank register on stack"""
        cpu.bus[cpu.S] = (cpu.PC >> 16) & 0xFF
        cpu.S -= 1
        return 3

    def PHX(self, cpu, addr) -> int:
        """Push X"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.bus[cpu.S] = (cpu.X >> 8) & 0xFF
            cpu.S -= 1
            cpu.bus[cpu.S] = (cpu.X >> 0) & 0xFF
            cpu.S -= 1
        else:
            cpu.bus[cpu.S] = (cpu.X >> 0) & 0xFF
            cpu.S -= 1

        return 0

    def PLX(self, cpu, addr) -> int:
        """Pull X"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.S += 1
            low = cpu.bus[cpu.S]
            cpu.S += 1
            high = cpu.bus[cpu.S]
            cpu.X = low | high << 8
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
            cpu.P.Z = 1 if (cpu.X & 0xFFFF) == 0 else 0
        else:
            cpu.S += 1
            low = cpu.bus[cpu.S]
            cpu.X = (cpu.X & 0xFF00) | (low & 0x00FF)
            cpu.P.N = 1 if cpu.X & 0x80 else 0
            cpu.P.Z = 1 if (cpu.X & 0xFF) == 0 else 0

        return 0

    def PHY(self, cpu, addr) -> int:
        """Push Y"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.bus[cpu.S] = (cpu.Y >> 8) & 0xFF
            cpu.S -= 1
            cpu.bus[cpu.S] = (cpu.Y >> 0) & 0xFF
            cpu.S -= 1
        else:
            cpu.bus[cpu.S] = (cpu.Y >> 0) & 0xFF
            cpu.S -= 1

        return 0

    def PLY(self, cpu, addr) -> int:
        """Pull Y"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.S += 1
            low = cpu.bus[cpu.S]
            cpu.S += 1
            high = cpu.bus[cpu.S]
            cpu.Y = low | high << 8
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
            cpu.P.Z = 1 if (cpu.Y & 0xFFFF) == 0 else 0
        else:
            cpu.S += 1
            low = cpu.bus[cpu.S]
            cpu.Y = (cpu.Y & 0xFF00) | (low & 0x00FF)
            cpu.P.N = 1 if cpu.Y & 0x80 else 0
            cpu.P.Z = 1 if (cpu.Y & 0xFF) == 0 else 0

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
        result = cpu.X - value

        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.P.N = 1 if result & 0x8000 else 0
            cpu.P.Z = 1 if (result & 0xFFFF) == 0 else 0
        else:
            cpu.P.N = 1 if result & 0x80 else 0
            cpu.P.Z = 1 if (result & 0xFF) == 0 else 0

        cpu.P.C = 1 if cpu.X >= value else 0

        # Workaround
        opcode = cpu.bus[cpu.current_instruction_PC]
        if opcode == 0xE0:  # Immediate
            if cpu.P.M == 0 and cpu.P.X == 1:
                cpu.PC -= 1
            elif cpu.P.M == 1 and cpu.P.X == 0:
                cpu.PC += 1

        return 0

    def CPY(self, cpu, addr) -> int:
        """Compare Y Index register with Memory"""
        value = cpu.bus[addr]
        if cpu.emulation == 0 and cpu.P.X == 0:
            value |= cpu.bus[addr + 1] << 8
        result = cpu.Y - value

        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.P.N = 1 if result & 0x8000 else 0
            cpu.P.Z = 1 if (result & 0xFFFF) == 0 else 0
        else:
            cpu.P.N = 1 if result & 0x80 else 0
            cpu.P.Z = 1 if (result & 0xFF) == 0 else 0

        cpu.P.C = 1 if cpu.Y >= value else 0

        # Workaround
        opcode = cpu.bus[cpu.current_instruction_PC]
        if opcode == 0xC0:  # Immediate
            if cpu.P.M == 0 and cpu.P.X == 1:
                cpu.PC -= 1
            elif cpu.P.M == 1 and cpu.P.X == 0:
                cpu.PC += 1

        return 0

    def INC(self, cpu, addr) -> int:
        """Increment Data"""
        opcode = cpu.bus[cpu.current_instruction_PC]

        if opcode == 0x1A:
            data = cpu.A
        else:
            data = cpu.bus[addr]
            if cpu.emulation == 0 and cpu.P.M == 0:
                data |= cpu.bus[addr + 1] << 8

        if cpu.emulation == 0 and cpu.P.M == 0:
            data = (data + 1) & 0xFFFF
            cpu.P.N = 1 if data & 0x8000 else 0
            cpu.P.Z = 1 if data & 0xFFFF == 0 else 0
        else:
            data = ((data + 1) & 0xFF) | (data & 0xFF00)
            cpu.P.N = 1 if data & 0x80 else 0
            cpu.P.Z = 1 if data & 0xFF == 0 else 0

        if opcode == 0x1A:
            cpu.A = data
        else:
            cpu.bus[addr + 0] = (data >> 0) & 0xFF
            if cpu.emulation == 0 and cpu.P.M == 0:
                cpu.bus[addr + 1] = (data >> 8) & 0xFF

        return 2

    def DEC(self, cpu, addr) -> int:
        """Decrement Data"""
        opcode = cpu.bus[cpu.current_instruction_PC]

        if opcode == 0x3A:
            data = cpu.A
        else:
            data = cpu.bus[addr]
            if cpu.emulation == 0 and cpu.P.M == 0:
                data |= cpu.bus[addr + 1] << 8

        if cpu.emulation == 0 and cpu.P.M == 0:
            data = (data - 1) & 0xFFFF
            cpu.P.N = 1 if data & 0x8000 else 0
            cpu.P.Z = 1 if data & 0xFFFF == 0 else 0
        else:
            data = ((data - 1) & 0xFF) | (data & 0xFF00)
            cpu.P.N = 1 if data & 0x80 else 0
            cpu.P.Z = 1 if data & 0xFF == 0 else 0

        if opcode == 0x3A:
            cpu.A = data
        else:
            cpu.bus[addr + 0] = (data >> 0) & 0xFF
            if cpu.emulation == 0 and cpu.P.M == 0:
                cpu.bus[addr + 1] = (data >> 8) & 0xFF

        return 2

    def INX(self, cpu, addr) -> int:
        """Increment Index Register X"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.X = (cpu.X + 1) & 0xFFFF
            cpu.P.N = 1 if cpu.X & 0x8000 else 0
            cpu.P.Z = 1 if cpu.X & 0xFFFF == 0 else 0
        else:
            cpu.X = (cpu.X & 0xFF00) | (cpu.X + 1) & 0xFF
            cpu.P.N = 1 if cpu.X & 0x80 else 0
            cpu.P.Z = 1 if cpu.X & 0xFF == 0 else 0

        return 2

    def INY(self, cpu, addr) -> int:
        """Increment Index Register Y"""
        if cpu.emulation == 0 and cpu.P.X == 0:
            cpu.Y = (cpu.Y + 1) & 0xFFFF
            cpu.P.N = 1 if cpu.Y & 0x8000 else 0
            cpu.P.Z = 1 if cpu.Y & 0xFFFF == 0 else 0
        else:
            cpu.Y = (cpu.Y & 0xFF00) | (cpu.Y + 1) & 0xFF
            cpu.P.N = 1 if cpu.Y & 0x80 else 0
            cpu.P.Z = 1 if cpu.Y & 0xFF == 0 else 0

        return 2

    def ROL(self, cpu, addr) -> int:
        """Rotate Memory or Accumulator Left"""
        if self.opcode == 0x2A:  # Addressing mode == Accumulator
            value = cpu.A if cpu.P.M == 0 else cpu.A & 0xFF
            temp = (value << 1) | (cpu.P.C & 0x1)
            if cpu.emulation == 0 and cpu.P.M == 0:
                cpu.P.C = 1 if value & 0x8000 else 0
                cpu.P.Z = 1 if (temp & 0xFFFF) == 0 else 0
                cpu.P.N = 1 if temp & 0x8000 else 0
                cpu.A = temp & 0xFFFF
            else:
                cpu.P.C = 1 if value & 0x80 else 0
                cpu.P.Z = 1 if (temp & 0xFF) == 0 else 0
                cpu.P.N = 1 if temp & 0x80 else 0
                cpu.A = (cpu.A & 0xFF00) | temp & 0xFF
        else:
            value = cpu.bus[addr]
            if cpu.emulation == 0 and cpu.P.M == 0:
                value |= cpu.bus[addr + 1] << 8
            temp = (value << 1) | (cpu.P.C & 0x1)
            if cpu.emulation == 0 and cpu.P.M == 0:
                cpu.P.C = 1 if value & 0x8000 else 0
                cpu.P.Z = 1 if (temp & 0xFFFF) == 0 else 0
                cpu.P.N = 1 if temp & 0x8000 else 0
                cpu.bus[addr] = temp & 0xFF
                cpu.bus[addr + 1] = (temp >> 8) & 0xFF
            else:
                cpu.P.C = 1 if value & 0x80 else 0
                cpu.P.Z = 1 if (temp & 0xFF) == 0 else 0
                cpu.P.N = 1 if temp & 0x80 else 0
                cpu.bus[addr] = temp & 0xFF

        return 0

    def ROR(self, cpu, addr) -> int:
        """Rotate Memory or Accumulator Right"""
        carry = cpu.P.C
        if self.opcode == 0x6A:  # Addressing mode == Accumulator
            if cpu.emulation == 0 and cpu.P.M == 0:
                data = cpu.A
                cpu.P.C = 1 if data & 1 else 0
                data = carry << 15 | data >> 1
                cpu.P.Z = 1 if (data & 0xFFFF) == 0 else 0
                cpu.P.N = 1 if data & 0x8000 else 0
                cpu.A = data
            else:
                data = cpu.A & 0xFF
                cpu.P.C = 1 if data & 1 else 0
                data = carry << 7 | data >> 1
                cpu.P.Z = 1 if (data & 0xFF) == 0 else 0
                cpu.P.N = 1 if data & 0x80 else 0
                cpu.A = (cpu.A & 0xFF00) | data & 0xFF
        else:
            if cpu.emulation == 0 and cpu.P.M == 0:
                data = cpu.bus[addr] | cpu.bus[addr + 1] << 8
                cpu.P.C = 1 if data & 1 else 0
                data = carry << 15 | data >> 1
                cpu.P.Z = 1 if (data & 0xFFFF) == 0 else 0
                cpu.P.N = 1 if data & 0x8000 else 0
                cpu.bus[addr] = data & 0xFF
                cpu.bus[addr + 1] = (data >> 8) & 0xFF
            else:
                data = cpu.bus[addr]
                cpu.P.C = 1 if data & 1 else 0
                data = carry << 7 | data >> 1
                cpu.P.Z = 1 if (data & 0xFF) == 0 else 0
                cpu.P.N = 1 if data & 0x80 else 0
                cpu.bus[addr] = data & 0xFF

        return 0

    def ORA(self, cpu, addr) -> int:
        """OR Accumulator with Memory"""
        if cpu.emulation == 0 and cpu.P.M == 0:
            value = cpu.bus[addr] | cpu.bus[addr + 1] << 8
            cpu.A = cpu.A | value
            cpu.P.N = 1 if cpu.A & 0x8000 else 0
            cpu.P.Z = 1 if (cpu.A & 0xFFFF) == 0 else 0
        else:
            value = cpu.bus[addr]
            cpu.A = (cpu.A & 0xFF00) | (cpu.A | value)
            cpu.P.N = 1 if cpu.A & 0x80 else 0
            cpu.P.Z = 1 if (cpu.A & 0xFF) == 0 else 0

        return 0


class InstructionSet:
    def __init__(self, cpu) -> None:
        self.cpu = cpu
        self.load_instructions()
        self.print_instructions = True
        self.trace = deque(maxlen=100)

    def load_instructions(self) -> None:
        self.instructions = {}
        with open("instructions.csv", "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                instruction = Instruction(row)
                self.instructions[instruction.opcode] = instruction

    def print_trace(self, entries: int = 20) -> None:
        if self.print_instructions:
            return  # No need

        for _ in range(entries):
            try:
                print(self.trace.pop())
            except IndexError:
                pass  # Empty

    def execute(self, opcode: int) -> int:
        instruction = self.instructions[opcode]
        self.cpu.current_instruction_PC = self.cpu.PC - 1
        # p_debug = instruction.mnemonic in ("JSR", "RTS")
        # p_debug = False
        debug_str = "\033[92mCPU 0x{:06X} {} {}\033[0m".format(
            self.cpu.current_instruction_PC,
            str(instruction).ljust(40),
            self.cpu,
        )
        self.trace.append(debug_str)

        # if self.cpu.current_instruction_PC == 0x05D9A5:
        # if self.cpu.current_instruction_PC == 0x05D8B7:
        # if self.cpu.current_instruction_PC == 0x05D8C2:
        # if self.cpu.current_instruction_PC == 0x9FA5:
        #    self.print_instructions = True

        if self.print_instructions:
            print(debug_str)

        cycles = instruction(self.cpu)
        return cycles
