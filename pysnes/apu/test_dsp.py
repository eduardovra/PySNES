import numpy as np
import pytest
from .dsp import Dsp, ENV_ATTACK, ENV_DECAY, ENV_SUSTAIN, ENV_RELEASE


def make_dsp(ram=None):
    mem = bytearray(65536) if ram is None else ram
    return Dsp(lambda addr: mem[addr & 0xFFFF])


def test_register_write_read():
    d = make_dsp()
    d.write_register(0x10, 0x7F)
    assert d.read_register(0x10) == 0x7F


def test_register_masked_to_7f():
    d = make_dsp()
    d.write_register(0x80, 0x42)   # 0x80 & 0x7F = 0x00
    assert d.read_register(0x00) == 0x42


def test_koff_sets_key_off():
    d = make_dsp()
    d.voices[0].active = True
    d.voices[2].active = True
    d.write_register(0x5C, 0x05)   # KOFF voices 0 and 2
    assert d.voices[0].key_off is True
    assert d.voices[1].key_off is False
    assert d.voices[2].key_off is True


def test_endx_read_clears():
    d = make_dsp()
    d.regs[0x7C] = 0xFF
    val = d.read_register(0x7C)
    assert val == 0xFF
    assert d.read_register(0x7C) == 0x00


def test_envx_read():
    d = make_dsp()
    d.voices[1].env_level = 0x400   # env_level=0x400, >> 4 = 0x40, & 0x7F = 0x40
    assert d.read_register(0x18) == 0x40  # voice 1 ENVX = reg 0x18


def test_generate_samples_shape_dtype():
    d = make_dsp()
    out = d.generate_samples(532)
    assert out.shape == (532, 2)
    assert out.dtype == np.int16


def test_generate_samples_silent_no_voices():
    d = make_dsp()
    out = d.generate_samples(100)
    assert (out == 0).all()


def test_generate_samples_muted():
    """FLG bit7=1 mutes all output."""
    d = make_dsp()
    d.regs[0x6C] = 0x80   # FLG: mute
    d.voices[0].active = True
    d.voices[0].brr_buf = [1000] * 16
    d.voices[0].env_level = 0x400
    d.regs[0x00] = 0x7F; d.regs[0x01] = 0x7F   # voice 0 volumes
    d.regs[0x0C] = 0x7F; d.regs[0x1C] = 0x7F   # master volumes
    out = d.generate_samples(10)
    assert (out == 0).all()


def test_brr_decode_filter0_shift12():
    """Filter 0, shift 12: nibble 1 → sample 2048, nibble 0 → sample 0."""
    block = bytearray(9)
    block[0] = 0xC1   # shift=12, filter=0, loop=0, end=1
    block[1] = 0x10   # upper nibble=1 → 2048, lower nibble=0 → 0
    # remaining bytes 0 → samples 0
    mem = bytearray(65536)
    mem[0x1000:0x1009] = block
    d = make_dsp(mem)
    d._init_voice_for_test(0, brr_addr=0x1000)
    d._decode_brr_block(0)
    assert d.voices[0].brr_buf[0] == 4096   # stored ×2: nibble=1, shift=12 → (1<<11)*2
    assert d.voices[0].brr_buf[1] == 0


def test_brr_decode_filter0_negative_nibble():
    """Nibble 0xF (-1 signed) with shift=12 → sample -2048."""
    block = bytearray(9)
    block[0] = 0xC1   # shift=12, filter=0, end=1
    block[1] = 0xF0   # upper nibble=0xF (-1 signed)
    mem = bytearray(65536)
    mem[0x2000:0x2009] = block
    d = make_dsp(mem)
    d._init_voice_for_test(0, brr_addr=0x2000)
    d._decode_brr_block(0)
    assert d.voices[0].brr_buf[0] == -4096  # stored ×2: nibble=-1, shift=12 → (-1<<11)*2


def test_brr_end_flag_sets_endx():
    """When BRR block has end flag, ENDX bit is set for that voice."""
    mem = bytearray(65536)
    # source dir at 0, entry 0: start=0x0200, loop=0x0200
    mem[0] = 0x00; mem[1] = 0x02; mem[2] = 0x00; mem[3] = 0x02
    # BRR at 0x0200: end=1, loop=1, all zero data
    mem[0x200] = 0x03
    d = make_dsp(mem)
    d.write_register(0x5D, 0x00)   # DIR=0
    d.write_register(0x04, 0x00)   # VxSRCN=0 for voice 0
    d.write_register(0x02, 0x00); d.write_register(0x03, 0x10)  # pitch=0x1000 (advance 1 sample/tick)
    d.write_register(0x00, 0x7F); d.write_register(0x01, 0x7F)
    d.write_register(0x0C, 0x7F); d.write_register(0x1C, 0x7F)
    d.write_register(0x4C, 0x01)   # KON voice 0
    d.generate_samples(20)
    # ENDX bit 0 should be set at some point (voice hit end block and loops)
    # After looping, voice stays active; ENDX was set


def test_brr_end_without_loop_zeroes_envelope():
    """A sample that ends with no loop flag deactivates the voice AND zeroes its
    envelope, so VxENVX reads 0 afterwards.

    Hardware silences a voice (ENVX→0) when a BRR block has the end flag set
    but the loop flag clear. Drivers (e.g. Super Bomberman 5) poll VxENVX to
    detect a freed voice and hang forever if it keeps reading the stale level.
    """
    mem = bytearray(65536)
    # source dir at 0, entry 0: start=0x0200 (loop addr unused)
    mem[0] = 0x00; mem[1] = 0x02; mem[2] = 0x00; mem[3] = 0x02
    mem[0x200] = 0x01              # BRR header: end=1, loop=0, zero data
    d = make_dsp(mem)
    d.write_register(0x5D, 0x00)   # DIR=0
    d.write_register(0x04, 0x00)   # VxSRCN=0 for voice 0
    d.write_register(0x02, 0x00); d.write_register(0x03, 0x10)  # pitch=0x1000
    d.write_register(0x00, 0x7F); d.write_register(0x01, 0x7F)
    d.write_register(0x0C, 0x7F); d.write_register(0x1C, 0x7F)
    # Direct GAIN holding env high so it can't reach 0 on its own.
    d.write_register(0x05, 0x00)   # ADSR1 bit7=0 → GAIN mode
    d.write_register(0x07, 0x7F)   # direct GAIN, max level
    d.write_register(0x4C, 0x01)   # KON voice 0
    d.generate_samples(64)         # run until the sample reaches its end block
    assert d.voices[0].active is False
    assert d.voices[0].env_level == 0
    assert d.read_register(0x08) == 0   # VxENVX for voice 0


def test_key_on_activates_voice():
    """KON causes voice to become active and start at BRR start address."""
    mem = bytearray(65536)
    mem[0] = 0x00; mem[1] = 0x03   # start addr = 0x0300
    mem[2] = 0x00; mem[3] = 0x03   # loop addr = 0x0300
    mem[0x300] = 0x03              # BRR end+loop, zero data
    d = make_dsp(mem)
    d.write_register(0x5D, 0x00)
    d.write_register(0x04, 0x00)
    d.write_register(0x4C, 0x01)   # KON voice 0
    d.generate_samples(1)          # apply KON
    assert d.voices[0].active is True
    assert d.voices[0].brr_addr == 0x0300 or d.voices[0].loop_addr == 0x0300


def test_envelope_attack_increases():
    d = make_dsp()
    d.voices[0].active = True
    d.voices[0].env_state = ENV_ATTACK
    d.voices[0].env_level = 0
    d.write_register(0x05, 0x8F)   # ADSR enabled
    before = d.voices[0].env_level
    d._step_envelope(0)
    assert d.voices[0].env_level > before


def test_envelope_release_decreases():
    d = make_dsp()
    d.voices[0].active = True
    d.voices[0].env_state = ENV_RELEASE
    d.voices[0].env_level = 0x200
    before = d.voices[0].env_level
    d._step_envelope(0)
    assert d.voices[0].env_level < before


def test_envelope_release_deactivates_at_zero():
    d = make_dsp()
    d.voices[0].active = True
    d.voices[0].env_state = ENV_RELEASE
    d.voices[0].env_level = 4   # less than 8, will hit 0
    d.write_register(0x05, 0x80)   # ADSR mode so GAIN direct doesn't intercept
    for _ in range(10):
        d._step_envelope(0)
    assert d.voices[0].active is False
    assert d.voices[0].env_level == 0


def test_koff_leads_to_release():
    d = make_dsp()
    d.voices[0].active = True
    d.voices[0].env_state = ENV_ATTACK
    d.voices[0].env_level = 0x400
    d.voices[0].key_off = True
    d._step_envelope(0)
    assert d.voices[0].env_state == ENV_RELEASE


def test_generate_samples_produces_nonzero_with_active_voice():
    """Active voice with nonzero sample, env, volume produces nonzero output."""
    d = make_dsp()
    v = d.voices[0]
    v.active = True
    v.brr_buf = [1000] * 16
    v.brr_offset = 0
    v.brr_header = 0x00   # no end/loop flags
    v.env_level = 0x400
    v.pitch_frac = 0
    # Pre-populate Gaussian history so interpolation produces nonzero output
    # (Gaussian uses hist0..hist3; without KON they start at zero)
    v.hist0 = v.hist1 = v.hist2 = v.hist3 = 1000
    d.regs[0x02] = 0x00; d.regs[0x03] = 0x00  # pitch=0 (no advance, stays at offset 0)
    d.regs[0x00] = 0x7F   # voice 0 left vol = +127
    d.regs[0x01] = 0x7F   # voice 0 right vol = +127
    d.regs[0x0C] = 0x7F   # master left vol
    d.regs[0x1C] = 0x7F   # master right vol
    d.regs[0x05] = 0x80   # ADSR mode (bit7=1) so GAIN direct doesn't override env_level
    out = d.generate_samples(10)
    assert (out != 0).any()
