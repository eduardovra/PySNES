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
        if addr == 0x4C:       # KON: accumulate bits; DSP reads them asynchronously
            self._pending_kon |= value & 0xFF
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

        # GAIN mode (ADSR1 bit7=0)
        if not (adsr1 & 0x80):
            gain = self.regs[voice_idx << 4 | 0x07]
            if not (gain & 0x80):
                # Direct GAIN: fixed envelope level
                v.env_level = (gain & 0x7F) << 4
                return
            # Programmable GAIN (gain bit7=1): release always overrides
            if v.env_state == ENV_RELEASE:
                v.env_level = max(0, v.env_level - 8)
                if v.env_level == 0:
                    v.active = False
                return
            rate_idx = gain & 0x1F
            period = _RATE_TABLE[rate_idx]
            v.env_counter += 1
            if period == 0 or v.env_counter < period:
                return
            v.env_counter = 0
            mode = (gain >> 5) & 0x3
            if mode == 0:    # linear decrease
                v.env_level = max(0, v.env_level - 32)
            elif mode == 1:  # exponential decrease
                v.env_level -= ((v.env_level - 1) >> 8) + 1
                if v.env_level < 0:
                    v.env_level = 0
            elif mode == 2:  # linear increase
                v.env_level = min(0x7FF, v.env_level + 32)
            else:            # bent-line increase: +32 until 0x600, then +8
                step = 8 if v.env_level >= 0x600 else 32
                v.env_level = min(0x7FF, v.env_level + step)
            return

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

        # Pass 1: voice-outer loop — process all n_samples for each voice, then mix.
        # Register reads and voice state are cached as locals to minimise attribute
        # and array lookups inside the hot per-sample loop.
        left_arr  = np.zeros(n_samples, dtype=np.int32)
        right_arr = np.zeros(n_samples, dtype=np.int32)
        echo_in   = np.zeros((n_samples, 2), dtype=np.int32)

        regs = self.regs  # one local reference saves repeated self.regs lookups

        for vi in range(8):
            v = self.voices[vi]
            if not v.active:
                continue

            # --- cache per-voice registers once ---
            base     = vi << 4
            pitch    = (regs[base | 0x02] | (regs[base | 0x03] << 8)) & 0x3FFF
            # TODO: PMON (0x2D) — if bit vi is set, modulate pitch by previous voice's output sample
            voll     = _s8(regs[base | 0x00])
            volr     = _s8(regs[base | 0x01])
            adsr1    = regs[base | 0x05]
            adsr2    = regs[base | 0x06]
            gain_reg = regs[base | 0x07]
            in_echo  = bool(eon & (1 << vi))
            endx_bit = 1 << vi

            # --- cache voice state as locals ---
            pitch_frac  = v.pitch_frac
            brr_offset  = v.brr_offset
            brr_buf     = v.brr_buf
            brr_header  = v.brr_header
            loop_addr   = v.loop_addr
            env_level   = v.env_level
            env_state   = v.env_state
            env_counter = v.env_counter
            key_off     = v.key_off
            prev1       = v.prev1
            prev2       = v.prev2
            hist0       = v.hist0
            hist1       = v.hist1
            hist2       = v.hist2
            hist3       = v.hist3
            active      = True

            # pre-decode envelope mode so the inner loop avoids repeated branches
            adsr_on  = bool(adsr1 & 0x80)
            gain_dir = (not adsr_on) and (not (gain_reg & 0x80))
            if gain_dir:
                fixed_env = (gain_reg & 0x7F) << 4
            else:
                fixed_env = 0  # unused
            gain_mode = (gain_reg >> 5) & 0x3 if (not adsr_on and not gain_dir) else 0
            gain_rate = gain_reg & 0x1F if (not adsr_on and not gain_dir) else 0
            sl = (adsr2 >> 5) & 7
            ar = adsr1 & 0x0F
            dr = (adsr1 >> 4) & 0x07
            sr = adsr2 & 0x1F

            voice_out = [0] * n_samples

            for s in range(n_samples):
                # --- envelope step (inlined) ---
                if key_off:
                    env_state   = ENV_RELEASE
                    env_counter = 0

                if gain_dir:
                    env_level = fixed_env
                elif env_state == ENV_RELEASE:
                    env_level -= 8
                    if env_level <= 0:
                        env_level = 0
                        active = False
                elif adsr_on:
                    if env_state == ENV_ATTACK:
                        rate_idx = ar * 2 + 1
                        period = _RATE_TABLE[rate_idx]
                        env_counter += 1
                        if period == 0 or env_counter >= period:
                            env_counter = 0
                            env_level += 1024 if rate_idx == 31 else 32
                            if env_level >= 0x7FF:
                                env_level = 0x7FF
                            if env_level >= 0x7E0:
                                env_state   = ENV_DECAY
                                env_counter = 0
                    elif env_state == ENV_DECAY:
                        rate_idx = dr * 2 + 16
                        period = _RATE_TABLE[rate_idx]
                        env_counter += 1
                        if period == 0 or env_counter >= period:
                            env_counter = 0
                            env_level -= ((env_level - 1) >> 8) + 1
                            if env_level < 0:
                                env_level = 0
                            if (env_level >> 8) == sl:
                                env_state   = ENV_SUSTAIN
                                env_counter = 0
                    else:  # ENV_SUSTAIN
                        period = _RATE_TABLE[sr]
                        if period != 0:
                            env_counter += 1
                            if env_counter >= period:
                                env_counter = 0
                                env_level -= ((env_level - 1) >> 8) + 1
                                if env_level < 0:
                                    env_level = 0
                else:  # programmable GAIN
                    period = _RATE_TABLE[gain_rate]
                    env_counter += 1
                    if period == 0 or env_counter >= period:
                        env_counter = 0
                        if gain_mode == 0:
                            env_level -= 32
                            if env_level < 0:
                                env_level = 0
                        elif gain_mode == 1:
                            env_level -= ((env_level - 1) >> 8) + 1
                            if env_level < 0:
                                env_level = 0
                        elif gain_mode == 2:
                            env_level += 32
                            if env_level > 0x7FF:
                                env_level = 0x7FF
                        else:
                            env_level += 8 if env_level >= 0x600 else 32
                            if env_level > 0x7FF:
                                env_level = 0x7FF

                if not active:
                    break

                # --- pitch advance ---
                pitch_frac += pitch
                while pitch_frac >= 0x1000:
                    pitch_frac -= 0x1000
                    brr_offset += 1
                    if brr_offset >= 16:
                        brr_offset = 0
                        end_flag  = brr_header & 0x01
                        loop_flag = brr_header & 0x02
                        if end_flag:
                            regs[0x7C] |= endx_bit
                            if loop_flag:
                                v.brr_addr = loop_addr
                            else:
                                # Sample ended without a loop flag: hardware
                                # silences the voice and zeroes its envelope.
                                # ENVX must read 0 afterwards or drivers that
                                # poll VxENVX to detect a freed voice hang.
                                active = False
                                env_level = 0
                                break
                        else:
                            v.brr_addr += 9
                        if active:
                            v.brr_offset = brr_offset
                            v.prev1 = prev1
                            v.prev2 = prev2
                            self._decode_brr_block(vi)
                            brr_buf    = v.brr_buf
                            brr_header = v.brr_header
                            prev1      = v.prev1
                            prev2      = v.prev2
                    if active:
                        hist3 = hist2
                        hist2 = hist1
                        hist1 = hist0
                        hist0 = brr_buf[brr_offset]

                if not active:
                    break

                # TODO: NON (0x3D) — if bit vi is set, replace BRR sample with LFSR noise output
                # --- Gaussian interpolation ---
                goff = pitch_frac >> 4
                sample = (
                    (_GAUSS[255 - goff] * hist3 +
                     _GAUSS[511 - goff] * hist2 +
                     _GAUSS[256 + goff] * hist1 +
                     _GAUSS[      goff] * hist0) >> 11
                )
                if sample > 32767:
                    sample = 32767
                elif sample < -32768:
                    sample = -32768
                voice_out[s] = ((sample & ~1) * env_level) >> 11

            # --- write back voice state ---
            v.pitch_frac  = pitch_frac
            v.brr_offset  = brr_offset
            v.brr_header  = brr_header
            v.env_level   = env_level
            v.env_state   = env_state
            v.env_counter = env_counter
            v.key_off     = key_off
            v.hist0       = hist0
            v.hist1       = hist1
            v.hist2       = hist2
            v.hist3       = hist3
            v.active      = active

            # --- apply voice volumes with NumPy ---
            voice_np = np.array(voice_out, dtype=np.int32)
            voice_l = (voice_np * voll) >> 7
            voice_r = (voice_np * volr) >> 7
            left_arr  += voice_l
            right_arr += voice_r
            if in_echo:
                echo_in[:, 0] += voice_l
                echo_in[:, 1] += voice_r

        # Pass 2: echo FIR — batched with NumPy across all n_samples.
        # For sample s, tap t reads echo_buf[(ep + s - t) % echo_len].
        # Applying all taps in NumPy avoids a 8×n_samples Python loop.
        ep       = self._echo_pos
        fir_arr  = np.array(fir, dtype=np.int32)
        fir_out  = np.zeros((n_samples, 2), dtype=np.int32)
        s_idx    = np.arange(n_samples, dtype=np.int64)
        for tap in range(8):
            if fir_arr[tap] == 0:
                continue
            positions = (ep + s_idx - tap) % echo_len
            fir_out += echo_buf[positions] * fir_arr[tap]
        fir_out = np.clip(fir_out >> 7, -32768, 32767).astype(np.int32) & ~1

        # Pass 3: write echo buffer and advance position.
        if not echo_disabled:
            write_pos = (ep + s_idx) % echo_len
            new_echo  = np.clip(echo_in + (fir_out * efb >> 7), -32768, 32767).astype(np.int32) & ~1
            echo_buf[write_pos] = new_echo
        self._echo_pos = int((ep + n_samples) % echo_len)

        # Pass 4: master volume mix + echo volume.
        # TODO: stereo hard-clipping — SNES clips each voice's L+R independently before summing
        # into left_arr/right_arr; current code clips only the final master mix.
        if not muted:
            out_l = np.clip((left_arr  * mvoll) >> 7, -32768, 32767)
            out_r = np.clip((right_arr * mvolr) >> 7, -32768, 32767)
            out_l = np.clip(out_l + ((fir_out[:, 0] * evoll) >> 7), -32768, 32767)
            out_r = np.clip(out_r + ((fir_out[:, 1] * evolr) >> 7), -32768, 32767)
            output[:, 0] = out_l
            output[:, 1] = out_r

        return output.astype(np.int16)
