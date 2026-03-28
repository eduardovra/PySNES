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
    assert PC == cpu.PC.value, "{:06X} != {:06X}".format(PC, cpu.PC.value)
    A = int(line[33:37], 16)
    assert A == cpu.A.value, "{:04X} != {:04X}".format(A, cpu.A.value)
    X = int(line[40:44], 16)
    assert X == cpu.X.value, "{:04X} != {:04X}".format(X, cpu.X.value)
    Y = int(line[47:51], 16)
    assert Y == cpu.Y.value, "{:04X} != {:04X}".format(Y, cpu.Y.value)
    S = int(line[54:59], 16)
    assert S == cpu.S.value, "{:04X} != {:04X}".format(S, cpu.S.value)

    NF = line[72] == "N"
    assert NF == cpu.NFlag, f"{NF} != {cpu.NFlag} {line=} {disassembled=}"
    VF = line[73] == "V"
    assert VF == cpu.VFlag, f"{VF} != {cpu.VFlag} {line=} {disassembled=}"
    IF = line[77] == "I"
    assert IF == cpu.IFlag, f"{IF} != {cpu.IFlag} {line=} {disassembled=}"
    ZF = line[78] == "Z"
    assert ZF == cpu.ZFlag, f"{ZF} != {cpu.ZFlag} {line=} {disassembled=}"
    CF = line[79] == "C"
    assert CF == cpu.CFlag, f"{CF} != {cpu.CFlag} {line=} {disassembled=}"

    EF = line[74] == "1"
    assert EF == cpu.EF, f"{EF} != {cpu.EF}"

    if cpu.EF:
        BF = line[75] == "B"
        # TODO: Fix this assertion
        # assert BF == bool(cpu.status.), f"{BF} != {cpu.P.B}"
    else:
        MF = line[74] == "M"
        assert MF == cpu.MFlag, f"{MF} != {cpu.MFlag}"
        XF = line[75] == "X"
        assert XF == cpu.XFlag, f"{XF} != {cpu.XFlag}"
