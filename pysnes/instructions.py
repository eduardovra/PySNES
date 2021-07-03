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
        "Accumulator": "accumulator",
        "Implied": "implied",
        "DP Indirect": "dp_indirect",
        "DP Indexed,X": "dp_indexed_x",
        "DP Indexed,Y": "dp_indexed_y",
        "DP Indexed Indirect,X": "dp_indexed_indirect_x",
        "DP Indirect Indexed, Y": "dp_indirect_indexed_y",
        "DP Indirect Long Indexed, Y": "dp_indirect_long_indexed_y",
        "SR Indirect Indexed,Y": "sr_indirect_indexed_y",
        "Stack Relative": "stack_relative",
        "Direct Page": "direct_page",
        "DP Indirect Long": "dp_indirect_long",
        "Immediate": "immediate",
        "Absolute": "absolute",
        "Absolute Indirect": "absolute_indirect",
        "Absolute Indirect Long": "absolute_indirect_long",
        "Absolute Indexed Indirect": "absolute_indexed_indirect",
        "Absolute Indexed,X": "absolute_indexed_x",
        "Absolute Indexed,Y": "absolute_indexed_y",
        "Absolute Long Indexed,X": "absolute_long_indexed_x",
        "Absolute Long": "absolute_long",
        "Program Counter Relative": "program_counter_relative",
        "Program Counter Relative Long": "program_counter_relative_long",
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
        "": "nop",  # Reserved for Future Expansion
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
        In implied addressing mode, the operands are specified implicitly in the definition of the instruction
        """
        return 0

    def absolute(self, cpu) -> int:
        """
        Effective Address:
        Bank: Data Bank Register (DBR) if locating data; Program Bank Register (PBR) if transferring control.
        High: Second operand byte.
        Low: First operand byte.
        """
        bank = 0  # TODO assuming bank 0 for now
        addr = cpu.bus[cpu.PC + 1] | cpu.bus[cpu.PC + 2] << 8 | bank << 16
        cpu.PC += 2
        return addr


class Instruction:
    def __init__(self, raw_instruction: dict) -> None:
        self.example = raw_instruction["Assembler Example"]
        self.mnemonic = self.example[:4]
        self.alias = raw_instruction["Alias"]
        self.description = raw_instruction["Proper Name"]
        self.opcode = int(raw_instruction["HEX"], 16)
        self.addressing_mode = AddressingMode(raw_instruction["Addressing Mode"])
        self.flags_set = set(f for f in raw_instruction["Flags Set"] if f != "-")
        self.bytes = raw_instruction["Bytes"]  # TODO parse
        self.cycles = raw_instruction["Cycles"]  # TODO parse

        # TODO load method here, once I get all of them implemented

    def __call__(self, cpu) -> int:
        # Decode phase: fetch additional information before execution

        # TODO for now I'm just returning the operand,
        # but it'll have to return the number of cycles used eventually
        data = self.addressing_mode(cpu)

        # Execute instruction phase
        try:
            method = getattr(self, self.mnemonic)
        except AttributeError:
            raise RuntimeError(f"Mnemonic not implemented: {self.mnemonic}")

        return method(cpu, data)

    def SEI(self, cpu, *args) -> int:
        cpu.PC += 1
        cpu.P.I = 1
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
        cycles = instruction(self.cpu)
        return cycles
