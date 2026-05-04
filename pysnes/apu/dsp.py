import numpy as np

ENV_ATTACK, ENV_DECAY, ENV_SUSTAIN, ENV_RELEASE = 0, 1, 2, 3

# DSP envelope rate table (32 entries): number of DSP ticks between envelope steps.
# Index 0 = never update. Attack maps AR*2+1, decay maps DR*2+16, sustain maps SR directly.
_RATE_TABLE = [
    0,
    2048, 1536, 1280, 1024, 768, 640, 512,
    384, 320, 256, 192, 160, 128, 96,
    80, 64, 48, 40, 32, 24, 20,
    16, 12, 10, 8, 6, 5, 4,
    3, 2, 1,
]


def _s8(v):
    v &= 0xFF
    return v - 256 if v >= 128 else v


class VoiceState:
    __slots__ = (
        'brr_addr',
        'brr_offset',
        'brr_header',
        'brr_buf',
        'loop_addr',
        'pitch_frac',
        'env_state',
        'env_level',
        'key_off',
        'active',
        'prev1',
        'prev2',
        'env_counter',
    )

    def __init__(self):
        self.brr_addr = 0
        self.brr_offset = 0
        self.brr_header = 0
        self.brr_buf = [0] * 16
        self.loop_addr = 0
        self.pitch_frac = 0
        self.env_state = ENV_ATTACK
        self.env_level = 0
        self.key_off = False
        self.active = False
        self.prev1 = 0
        self.prev2 = 0
        self.env_counter = 0


class Dsp:
    def __init__(self, ram_reader):
        # ram_reader: callable(addr: int) -> int, reads from APU RAM
        self.regs = bytearray(128)      # DSP registers $00-$7F
        self.voices = [VoiceState() for _ in range(8)]
        self._ram = ram_reader
        self._pending_kon = 0           # latched KON value

    def write_register(self, addr: int, value: int) -> None:
        addr &= 0x7F
        self.regs[addr] = value & 0xFF
        if addr == 0x4C:       # KON: latch, apply at next generate_samples call
            self._pending_kon = value & 0xFF
        elif addr == 0x5C:     # KOFF: immediately request key-off on matching voices
            for v in range(8):
                if value & (1 << v):
                    self.voices[v].key_off = True
        elif addr == 0x6C:     # FLG: bit5 = soft reset → silence all voices immediately
            if value & 0x20:
                for v in self.voices:
                    v.active = False
                    v.env_level = 0
                self._pending_kon = 0  # discard any pending key-on

    def read_register(self, addr: int) -> int:
        addr &= 0x7F
        voice = (addr >> 4) & 0x7
        reg = addr & 0x0F
        if reg == 0x08:                    # VxENVX: current envelope (0-127)
            return (self.voices[voice].env_level >> 4) & 0x7F
        elif addr == 0x7C:                 # ENDX: read and clear
            val = self.regs[0x7C]
            self.regs[0x7C] = 0
            return val

        return self.regs[addr]

    def _init_voice_for_test(self, voice_idx: int, brr_addr: int) -> None:
        """Test helper: reset all voice fields and set brr_addr."""
        v = self.voices[voice_idx]
        v.brr_addr = brr_addr
        v.brr_offset = 0
        v.brr_header = 0
        v.brr_buf = [0] * 16
        v.loop_addr = 0
        v.pitch_frac = 0
        v.env_state = ENV_ATTACK
        v.env_level = 0
        v.key_off = False
        v.active = False
        v.prev1 = 0
        v.prev2 = 0
        v.env_counter = 0

    def _apply_key_on(self) -> None:
        if not self._pending_kon:
            return

        for voice_idx in range(8):
            if not (self._pending_kon & (1 << voice_idx)):
                continue

            v = self.voices[voice_idx]
            dir_base = self.regs[0x5D] << 8
            srcn = self.regs[voice_idx << 4 | 0x04]
            entry_addr = dir_base + srcn * 4
            start_lo = self._ram(entry_addr)
            start_hi = self._ram(entry_addr + 1)
            loop_lo = self._ram(entry_addr + 2)
            loop_hi = self._ram(entry_addr + 3)
            v.brr_addr = start_lo | (start_hi << 8)
            v.loop_addr = loop_lo | (loop_hi << 8)
            v.brr_buf = [0] * 16
            v.brr_offset = 0
            v.pitch_frac = 0
            v.prev1 = 0
            v.prev2 = 0
            v.env_state = ENV_ATTACK
            v.env_level = 0
            v.env_counter = 0
            v.active = True
            v.key_off = False
            self._decode_brr_block(voice_idx)

        self._pending_kon = 0

    def _decode_brr_block(self, voice_idx: int) -> None:
        v = self.voices[voice_idx]
        header = self._ram(v.brr_addr)
        shift = (header >> 4) & 0xF
        filt = (header >> 2) & 3
        # loop and end flags stored for later use
        # prev1/prev2 start from current voice history
        prev1 = v.prev1
        prev2 = v.prev2

        i = 0
        for byte_idx in range(1, 9):
            byte = self._ram(v.brr_addr + byte_idx)
            for nibble_shift in (4, 0):
                nibble = (byte >> nibble_shift) & 0xF
                # Sign-extend 4-bit nibble
                s = nibble - 16 if nibble >= 8 else nibble
                # Scale
                s <<= 11
                # Apply filter
                if filt == 0:
                    pass
                elif filt == 1:
                    s += prev1 - (prev1 >> 4)
                elif filt == 2:
                    s += (prev1 << 1) - ((prev1 * 3) >> 5) - prev2 + (prev2 >> 4)
                elif filt == 3:
                    s += (prev1 << 1) - ((prev1 * 13) >> 6) - prev2 + ((prev2 * 3) >> 4)
                # Clamp to int16
                s = max(-32768, min(32767, s))
                # Apply BRR shift
                s >>= (12 - min(shift, 12))
                # Clamp again
                s = max(-32768, min(32767, s))
                v.brr_buf[i] = s
                prev2 = prev1
                prev1 = s
                i += 1

        v.prev1 = prev1
        v.prev2 = prev2
        v.brr_header = header

    def _step_envelope(self, voice_idx: int) -> None:
        v = self.voices[voice_idx]
        if not v.active:
            return

        if v.key_off:
            v.env_state = ENV_RELEASE
            v.env_counter = 0

        adsr1 = self.regs[voice_idx << 4 | 0x05]
        adsr2 = self.regs[voice_idx << 4 | 0x06]

        # GAIN direct mode: ADSR1 bit7=0, GAIN bit7=0 → fixed envelope level
        if not (adsr1 & 0x80):
            gain = self.regs[voice_idx << 4 | 0x07]
            if not (gain & 0x80):
                v.env_level = (gain & 0x7F) << 4
                return
            # Programmable GAIN (bit7=1) — treat as ADSR for now

        # ADSR mode
        sl = (adsr2 >> 5) & 7
        ar = adsr1 & 0x0F
        dr = (adsr1 >> 4) & 0x07
        sr = adsr2 & 0x1F

        if v.env_state == ENV_RELEASE:
            # Release always steps every tick, linear -8
            v.env_level = max(0, v.env_level - 8)
            if v.env_level == 0:
                v.active = False
            return

        if v.env_state == ENV_ATTACK:
            rate_idx = ar * 2 + 1
            period = _RATE_TABLE[rate_idx]
            v.env_counter += 1
            if period == 0 or v.env_counter < period:
                return
            v.env_counter = 0
            step = 1024 if rate_idx == 31 else 32
            v.env_level = min(0x7FF, v.env_level + step)
            if v.env_level >= 0x7E0:
                v.env_state = ENV_DECAY
                v.env_counter = 0

        elif v.env_state == ENV_DECAY:
            rate_idx = dr * 2 + 16
            period = _RATE_TABLE[rate_idx]
            v.env_counter += 1
            if period == 0 or v.env_counter < period:
                return
            v.env_counter = 0
            v.env_level -= max(1, v.env_level >> 8)
            threshold = (sl + 1) << 8
            if v.env_level <= threshold:
                v.env_level = threshold
                v.env_state = ENV_SUSTAIN
                v.env_counter = 0

        elif v.env_state == ENV_SUSTAIN:
            period = _RATE_TABLE[sr]
            if period == 0:
                return  # SR=0 → hold at sustain level forever
            v.env_counter += 1
            if v.env_counter < period:
                return
            v.env_counter = 0
            v.env_level = max(0, v.env_level - max(1, v.env_level >> 8))

    def generate_samples(self, n_samples: int):
        output = np.zeros((n_samples, 2), dtype=np.int32)
        self._apply_key_on()
        flags = self.regs[0x6C]
        muted = bool(flags & 0x80)
        mvoll = _s8(self.regs[0x0C])
        mvolr = _s8(self.regs[0x1C])

        for s in range(n_samples):
            left = right = 0
            for vi in range(8):
                v = self.voices[vi]
                if not v.active:
                    continue
                self._step_envelope(vi)
                pitch = (self.regs[vi << 4 | 0x02] | (self.regs[vi << 4 | 0x03] << 8)) & 0x3FFF
                v.pitch_frac += pitch
                # advance BRR position for each full sample step
                while v.pitch_frac >= 0x1000:
                    v.pitch_frac -= 0x1000
                    v.brr_offset += 1
                    if v.brr_offset >= 16:
                        v.brr_offset = 0
                        end_flag = v.brr_header & 0x01
                        loop_flag = v.brr_header & 0x02
                        if end_flag:
                            self.regs[0x7C] |= (1 << vi)
                            if loop_flag:
                                v.brr_addr = v.loop_addr
                            else:
                                v.active = False
                                break
                        else:
                            v.brr_addr += 9
                        if v.active:
                            self._decode_brr_block(vi)
                if not v.active:
                    continue
                sample = v.brr_buf[v.brr_offset]
                sample = (sample * v.env_level) >> 11
                voll = _s8(self.regs[vi << 4 | 0x00])
                volr = _s8(self.regs[vi << 4 | 0x01])
                left  += (sample * voll) >> 7
                right += (sample * volr) >> 7
            if not muted:
                output[s, 0] = (left  * mvoll) >> 7
                output[s, 1] = (right * mvolr) >> 7

        np.clip(output, -32768, 32767, out=output)

        return output.astype(np.int16)
