import pytest

from .apu_v2 import Apu


@pytest.fixture
def apu():
    yield Apu()


"""
    MOV   X, #i        CD    2     2   X = i                            N.....Z.
    MOV   X, A         5D    1     2   X = A                            N.....Z.
    MOV   X, SP        9D    1     2   X = SP                           N.....Z.
    MOV   X, d         F8    2     3   X = (d)                          N.....Z.
    MOV   X, d+Y       F9    2     4   X = (d+Y)                        N.....Z.
    MOV   X, !a        E9    3     4   X = (a)                          N.....Z.
    MOV   Y, #i        8D    2     2   Y = i                            N.....Z.
    MOV   Y, A         FD    1     2   Y = A                            N.....Z.
    MOV   Y, d         EB    2     3   Y = (d)                          N.....Z.
    MOV   Y, d+X       FB    2     4   Y = (d+X)                        N.....Z.
    MOV   Y, !a        EC    3     4   Y = (a)                          N.....Z.
"""


def test_cd(apu: Apu):
    apu.load_program([0xCD, 0xEF])
    apu.fetch_and_execute()

    assert apu.PC == 0xFFC2
    assert apu.A == 0x00
    assert apu.X == 0xEF
    assert apu.Y == 0x00
    assert apu.S == 0xEF
    assert apu.PSW == 0x80


def test_e8(apu: Apu):
    apu.load_program([0xE8, 0xFF])
    apu.fetch_and_execute()

    assert apu.PC == 0xFFC2
    assert apu.A == 0xFF
    assert apu.X == 0x00
    assert apu.Y == 0x00
    assert apu.S == 0xEF
    assert apu.PSW == 0x80


def test_bd(apu: Apu):
    apu.X = 0x50
    apu.load_program([0xBD])
    apu.fetch_and_execute()

    assert apu.PC == 0xFFC1
    assert apu.A == 0x00
    assert apu.X == 0x50
    assert apu.Y == 0x00
    assert apu.S == 0x50
    assert apu.PSW == 0x00


def test_c6(apu: Apu):
    """(X) = A"""
    apu.A = 0x55
    apu.X = 0xEF
    apu.load_program([0xC6])
    apu.fetch_and_execute()

    assert apu.PC == 0xFFC1
    assert apu.A == 0x55
    assert apu.X == 0xEF
    assert apu.Y == 0x00
    assert apu.S == 0xEF
    assert apu.PSW == 0x02
    assert apu[0xEF] == 0x55


def test_1d(apu: Apu):
    """X--"""
    apu.X = 0xEF
    apu.load_program([0x1D])
    apu.fetch_and_execute()

    assert apu.PC == 0xFFC1
    assert apu.A == 0x00
    assert apu.X == 0xEE
    assert apu.Y == 0x00
    assert apu.S == 0xEF
    assert apu.PSW == 0x80


def test_d0_take(apu: Apu):
    """PC+=r  if Z == 0"""
    apu.load_program([0xD0, 0xFC])
    apu.fetch_and_execute()

    assert apu.PC == 0xFFC2
    assert apu.A == 0x00
    assert apu.X == 0x00
    assert apu.Y == 0x00
    assert apu.S == 0xEF
    assert apu.PSW == 0x20

    apu.ZF = False
    apu.fetch_and_execute()


def test_d0_dont_take(apu: Apu):
    """PC+=r  if Z == 0"""
    apu.ZF = False
    apu.load_program([0xD0, 0xFC])
    apu.fetch_and_execute()

    assert apu.PC == 0xFFC2
    assert apu.A == 0x00
    assert apu.X == 0x00
    assert apu.Y == 0x00
    assert apu.S == 0xEF
    assert apu.PSW == 0x20
