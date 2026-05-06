import array
import numpy as np

ENV_ATTACK, ENV_DECAY, ENV_SUSTAIN, ENV_RELEASE = 0, 1, 2, 3

# 512-entry Gaussian table from bsnes/Mesen.  Two halves of 256:
#   gauss[255-off], gauss[511-off], gauss[256+off], gauss[off]
# are the 4-tap weights for interpolation offset 0..255.
_GAUSS = (
       0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,   0,
       1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   1,   2,   2,   2,   2,   2,
       2,   2,   3,   3,   3,   3,   3,   4,   4,   4,   4,   4,   5,   5,   5,   5,
       6,   6,   6,   6,   7,   7,   7,   8,   8,   8,   9,   9,   9,  10,  10,  10,
      11,  11,  11,  12,  12,  13,  13,  14,  14,  15,  15,  15,  16,  16,  17,  17,
      18,  19,  19,  20,  20,  21,  21,  22,  23,  23,  24,  24,  25,  26,  27,  27,
      28,  29,  29,  30,  31,  32,  32,  33,  34,  35,  36,  36,  37,  38,  39,  40,
      41,  42,  43,  44,  45,  46,  47,  48,  49,  50,  51,  52,  53,  54,  55,  56,
      58,  59,  60,  61,  62,  64,  65,  66,  67,  69,  70,  71,  73,  74,  76,  77,
      78,  80,  81,  83,  84,  86,  87,  89,  90,  92,  94,  95,  97,  99, 100, 102,
     104, 106, 107, 109, 111, 113, 115, 117, 118, 120, 122, 124, 126, 128, 130, 132,
     134, 137, 139, 141, 143, 145, 147, 150, 152, 154, 156, 159, 161, 163, 166, 168,
     171, 173, 175, 178, 180, 183, 186, 188, 191, 193, 196, 199, 201, 204, 207, 210,
     212, 215, 218, 221, 224, 227, 230, 233, 236, 239, 242, 245, 248, 251, 254, 257,
     260, 263, 267, 270, 273, 276, 280, 283, 286, 290, 293, 297, 300, 304, 307, 311,
     314, 318, 321, 325, 328, 332, 336, 339, 343, 347, 351, 354, 358, 362, 366, 370,
     374, 378, 381, 385, 389, 393, 397, 401, 405, 410, 414, 418, 422, 426, 430, 434,
     439, 443, 447, 451, 456, 460, 464, 469, 473, 477, 482, 486, 491, 495, 499, 504,
     508, 513, 517, 522, 527, 531, 536, 540, 545, 550, 554, 559, 563, 568, 573, 577,
     582, 587, 592, 596, 601, 606, 611, 615, 620, 625, 630, 635, 640, 644, 649, 654,
     659, 664, 669, 674, 678, 683, 688, 693, 698, 703, 708, 713, 718, 723, 728, 732,
     737, 742, 747, 752, 757, 762, 767, 772, 777, 782, 787, 792, 797, 802, 806, 811,
     816, 821, 826, 831, 836, 841, 846, 851, 855, 860, 865, 870, 875, 880, 884, 889,
     894, 899, 904, 908, 913, 918, 923, 927, 932, 937, 941, 946, 951, 955, 960, 965,
     969, 974, 978, 983, 988, 992, 997,1001,1005,1010,1014,1019,1023,1027,1032,1036,
    1040,1045,1049,1053,1057,1061,1066,1070,1074,1078,1082,1086,1090,1094,1098,1102,
    1106,1109,1113,1117,1121,1125,1128,1132,1136,1139,1143,1146,1150,1153,1157,1160,
    1164,1167,1170,1174,1177,1180,1183,1186,1190,1193,1196,1199,1202,1205,1207,1210,
    1213,1216,1219,1221,1224,1227,1229,1232,1234,1237,1239,1241,1244,1246,1248,1251,
    1253,1255,1257,1259,1261,1263,1265,1267,1269,1270,1272,1274,1275,1277,1279,1280,
    1282,1283,1284,1286,1287,1288,1290,1291,1292,1293,1294,1295,1296,1297,1297,1298,
    1299,1300,1300,1301,1302,1302,1303,1303,1303,1304,1304,1304,1304,1304,1305,1305,
)

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
        'hist0', 'hist1', 'hist2', 'hist3',
    )

    def __init__(self):
        self.brr_addr = 0
        self.brr_offset = 0
        self.brr_header = 0
        self.brr_buf = array.array('h', [0] * 16)
        self.loop_addr = 0
        self.pitch_frac = 0
        self.env_state = ENV_ATTACK
        self.env_level = 0
        self.key_off = False
        self.active = False
        self.prev1 = 0
        self.prev2 = 0
        self.env_counter = 0
        self.hist0 = 0
        self.hist1 = 0
        self.hist2 = 0
        self.hist3 = 0


class Dsp:
    def __init__(self, ram_reader):
        # ram_reader: callable(addr: int) -> int, reads from APU RAM
        self.regs = bytearray(128)      # DSP registers $00-$7F
        self.voices = [VoiceState() for _ in range(8)]
        self._ram = ram_reader
        self._pending_kon = 0           # latched KON value
        self._echo_ready = False
        self._echo_buf = None
        self._echo_pos = 0
        self._echo_buf_addr = 0

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
        elif addr in (0x6D, 0x7D):  # ESA or EDL changed → reinit echo buffer
            self._echo_ready = False

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
        v.brr_buf = array.array('h', [0] * 16)
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
            v.brr_buf = array.array('h', [0] * 16)
            v.brr_offset = 0
            v.pitch_frac = 0
            v.prev1 = 0
            v.prev2 = 0
            v.env_state = ENV_ATTACK
            v.env_level = 0
            v.env_counter = 0
            v.active = True
            v.key_off = False
            v.hist0 = 0
            v.hist1 = 0
            v.hist2 = 0
            v.hist3 = 0
            self._decode_brr_block(voice_idx)

        self._pending_kon = 0

    def _decode_brr_block(self, voice_idx: int) -> None:
        v = self.voices[voice_idx]
        header = self._ram(v.brr_addr)
        shift = (header >> 4) & 0xF
        filt = (header >> 2) & 3
        prev1 = v.prev1
        prev2 = v.prev2

        i = 0
        for byte_idx in range(1, 9):
            byte = self._ram(v.brr_addr + byte_idx)
            for nibble_shift in (4, 0):
                nibble = (byte >> nibble_shift) & 0xF
                # Sign-extend 4-bit nibble to int (-8..+7)
                s = nibble - 16 if nibble >= 8 else nibble

                # Scale first: (s << shift) >> 1; shifts 13-15 force ±0x800
                if shift >= 13:
                    s = -0x800 if s < 0 else 0
                elif shift == 0:
                    s >>= 1
                else:
                    s <<= shift - 1  # == (s << shift) >> 1

                # Apply filter using 15-bit prev values (matching hardware)
                if filt == 1:
                    s += prev1 + (-prev1 >> 4)
                elif filt == 2:
                    s += (prev1 << 1) + (-((prev1 << 1) + prev1) >> 5) - prev2 + (prev2 >> 4)
                elif filt == 3:
                    s += (prev1 << 1) + (-(prev1 + (prev1 << 2) + (prev1 << 3)) >> 6) - prev2 + (((prev2 << 1) + prev2) >> 4)

                # Clamp to 16-bit signed
                s = max(-32768, min(32767, s))
                # Store ×2 (hardware buffer convention; prev stays at 1× = 15-bit)
                v.brr_buf[i] = max(-32768, min(32767, s * 2))
                prev2 = prev1
                prev1 = s   # 15-bit value used for next filter step
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
            v.env_level -= ((v.env_level - 1) >> 8) + 1
            if v.env_level < 0:
                v.env_level = 0
            # Transition when top 3 bits of env match SL (matching hardware)
            if (v.env_level >> 8) == sl:
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
            v.env_level -= ((v.env_level - 1) >> 8) + 1
            if v.env_level < 0:
                v.env_level = 0

    def _init_echo(self) -> None:
        """Initialise echo ring buffer from SPC RAM (called lazily on first generate)."""
        esa = self.regs[0x6D]
        edl = self.regs[0x7D] & 0x0F
        self._echo_buf_addr = esa << 8
        buf_len = max(edl, 1) * 0x800 // 4  # stereo samples (4 bytes each in RAM)
        self._echo_buf = np.zeros((buf_len, 2), dtype=np.int32)
        for i in range(buf_len):
            base = (self._echo_buf_addr + i * 4) & 0xFFFF
            l = self._ram(base) | (self._ram(base + 1) << 8)
            r = self._ram(base + 2) | (self._ram(base + 3) << 8)
            self._echo_buf[i, 0] = l if l < 32768 else l - 65536
            self._echo_buf[i, 1] = r if r < 32768 else r - 65536
        self._echo_pos = 0
        self._echo_ready = True

    def generate_samples(self, n_samples: int):
        output = np.zeros((n_samples, 2), dtype=np.int32)
        self._apply_key_on()
        flags = self.regs[0x6C]
        muted = bool(flags & 0x80)
        echo_disabled = bool(flags & 0x20)
        mvoll = _s8(self.regs[0x0C])
        mvolr = _s8(self.regs[0x1C])
        evoll = _s8(self.regs[0x2C])
        evolr = _s8(self.regs[0x3C])
        efb   = _s8(self.regs[0x0D])
        eon   = self.regs[0x4D]
        # FIR coefficients (8 taps, signed)
        fir = [_s8(self.regs[0x0F + i * 0x10]) for i in range(8)]

        if not self._echo_ready:
            self._init_echo()

        echo_buf = self._echo_buf
        echo_len = len(echo_buf)

        for s in range(n_samples):
            left = right = 0
            echo_left = echo_right = 0
            for vi in range(8):
                v = self.voices[vi]
                if not v.active:
                    continue
                self._step_envelope(vi)
                pitch = (self.regs[vi << 4 | 0x02] | (self.regs[vi << 4 | 0x03] << 8)) & 0x3FFF
                v.pitch_frac += pitch
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
                    if v.active:
                        # Shift history and push newest decoded sample
                        v.hist3 = v.hist2
                        v.hist2 = v.hist1
                        v.hist1 = v.hist0
                        v.hist0 = v.brr_buf[v.brr_offset]
                if not v.active:
                    continue
                # 4-tap Gaussian interpolation (matching SNES hardware)
                goff = v.pitch_frac >> 4  # 0..255
                sample = (
                    (_GAUSS[255 - goff] * v.hist3 +
                     _GAUSS[511 - goff] * v.hist2 +
                     _GAUSS[256 + goff] * v.hist1 +
                     _GAUSS[      goff] * v.hist0) >> 11
                )
                sample = max(-32768, min(32767, sample)) & ~1
                sample = (sample * v.env_level) >> 11
                voll = _s8(self.regs[vi << 4 | 0x00])
                volr = _s8(self.regs[vi << 4 | 0x01])
                voice_l = (sample * voll) >> 7
                voice_r = (sample * volr) >> 7
                left  += voice_l
                right += voice_r
                if eon & (1 << vi):
                    echo_left  += voice_l
                    echo_right += voice_r

            # Echo: 8-tap FIR.  Echo buffer stores 16-bit samples; each tap uses
            # coeff >> 7 to match Mesen's (15-bit history * coeff >> 6) convention.
            # FIR taps: tap 0 = newest echo sample, tap 7 = oldest.
            fir_l = fir_r = 0
            for tap in range(8):
                pos = (self._echo_pos - tap) % echo_len
                fir_l += (echo_buf[pos, 0] * fir[tap]) >> 7
                fir_r += (echo_buf[pos, 1] * fir[tap]) >> 7
            fir_l = max(-32768, min(32767, fir_l)) & ~1
            fir_r = max(-32768, min(32767, fir_r)) & ~1

            # Write to echo buffer (position always advances; write suppressed when disabled)
            if not echo_disabled:
                new_l = max(-32768, min(32767, echo_left + ((fir_l * efb) >> 7))) & ~1
                new_r = max(-32768, min(32767, echo_right + ((fir_r * efb) >> 7))) & ~1
                echo_buf[self._echo_pos, 0] = new_l
                echo_buf[self._echo_pos, 1] = new_r
            self._echo_pos = (self._echo_pos + 1) % echo_len

            if not muted:
                out_l = (left  * mvoll) >> 7
                out_r = (right * mvolr) >> 7
                out_l += (fir_l * evoll) >> 7
                out_r += (fir_r * evolr) >> 7
                output[s, 0] = max(-32768, min(32767, out_l))
                output[s, 1] = max(-32768, min(32767, out_r))

        return output.astype(np.int16)
