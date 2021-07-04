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
        "Stack (Push)": "stack_push",
        "Stack (Pull)": "stack_pull",
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
        print("0x{:02X} {}".format(self.cpu.PC - 1, instruction))
        cycles = instruction(self.cpu)
        return cycles
