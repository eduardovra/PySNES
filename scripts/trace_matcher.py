from pysnes.cpu import Cpu


def check_trace_line(line: str, cpu: Cpu):
    """Compare current state with bsnes trace log"""
    disassembled = cpu.disassembler.disassemble(cpu.PC.value)
    line = line.strip()

    # compare instruction and operand
    actual = disassembled[:20].lower()
    expected = line[:20].lower()
    assert actual == expected, f"{actual!r} != {expected!r}"

    PC = int(line[:6], 16)
    assert cpu.PC.value == PC, f"{PC:06X} != {cpu.PC.value:06X}"
    A = int(line[33:37], 16)
    assert cpu.A.value == A, f"{A:04X} != {cpu.A.value:04X}"
    X = int(line[40:44], 16)
    assert cpu.X.value == X, f"{X:04X} != {cpu.X.value:04X}"
    Y = int(line[47:51], 16)
    assert cpu.Y.value == Y, f"{Y:04X} != {cpu.Y.value:04X}"
    S = int(line[54:59], 16)
    assert cpu.S.value == S, f"{S:04X} != {cpu.S.value:04X}"

    NF = line[72] == "N"
    assert cpu.NFlag == NF, f"{NF} != {cpu.NFlag} {line=} {disassembled=}"
    VF = line[73] == "V"
    assert cpu.VFlag == VF, f"{VF} != {cpu.VFlag} {line=} {disassembled=}"
    IF = line[77] == "I"
    assert cpu.IFlag == IF, f"{IF} != {cpu.IFlag} {line=} {disassembled=}"
    ZF = line[78] == "Z"
    assert cpu.ZFlag == ZF, f"{ZF} != {cpu.ZFlag} {line=} {disassembled=}"
    CF = line[79] == "C"
    assert cpu.CFlag == CF, f"{CF} != {cpu.CFlag} {line=} {disassembled=}"

    EF = line[74] == "1"
    assert EF == cpu.EF, f"{EF} != {cpu.EF}"

    # TODO: in emulation mode (cpu.EF), assert the B flag too:
    # BF = line[75] == "B"
    # assert BF == bool(cpu.status.), f"{BF} != {cpu.P.B}"
    if not cpu.EF:
        MF = line[74] == "M"
        assert cpu.MFlag == MF, f"{MF} != {cpu.MFlag}"
        XF = line[75] == "X"
        assert cpu.XFlag == XF, f"{XF} != {cpu.XFlag}"
