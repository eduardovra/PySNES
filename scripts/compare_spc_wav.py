"""
Compare PySNES SPC audio output against a reference WAV (e.g. from Mesen).

Usage:
    uv run python scripts/compare_spc_wav.py <spc_file> <reference.wav> [--seconds N]

Dumps our SPC player's output to a temp WAV at 32 kHz, resamples the
reference to the same rate, then prints per-second RMS error and
writes a difference WAV for further inspection.
"""
import argparse
import sys
import wave
import pathlib
import struct
import tempfile

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from pysnes.apu.spc_file import SpcFile
from pysnes.apu.apu import Apu

_APU_HZ  = 1_024_000
_DSP_DIV = 32
_AUDIO_HZ = _APU_HZ // _DSP_DIV  # 32 000 Hz


def dump_pysnes(spc_path: str, duration_s: float) -> np.ndarray:
    """Run the SPC non-real-time and return int16 stereo samples at 32 kHz."""
    spc = SpcFile(spc_path)
    apu = Apu()
    apu.load_spc(spc)

    total_samples = int(duration_s * _AUDIO_HZ)
    # Run APU one "frame" at a time (~533 samples each), collect all output
    samples_per_chunk = 533
    apu_per_chunk = samples_per_chunk * _DSP_DIV  # 17 056 APU clocks

    chunks = []
    collected = 0
    print(f"Dumping PySNES: {duration_s:.1f}s ({total_samples} samples @ {_AUDIO_HZ} Hz)...")
    while collected < total_samples:
        clocks_left = apu_per_chunk
        while clocks_left > 0:
            apu.fetch_and_execute()
            apu.step_timers(apu.cycles)
            clocks_left -= apu.cycles
        chunk = apu.generate_audio_frame(samples_per_chunk)
        chunks.append(chunk)
        collected += samples_per_chunk

    all_samples = np.concatenate(chunks, axis=0)[:total_samples]
    print(f"  done: {len(all_samples)} samples")
    return all_samples.astype(np.int16)


def load_reference(wav_path: str, duration_s: float, target_rate: int) -> np.ndarray:
    """Load reference WAV, trim to duration, resample to target_rate."""
    with wave.open(wav_path) as w:
        src_rate = w.getframerate()
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        n_frames = w.getnframes()
        want_frames = min(n_frames, int(duration_s * src_rate))
        raw = w.readframes(want_frames)

    print(f"Reference: {wav_path} — {src_rate} Hz, {n_channels}ch, {n_frames} frames ({n_frames/src_rate:.1f}s)")

    dtype = np.int16 if sampwidth == 2 else np.int32
    data = np.frombuffer(raw, dtype=dtype).reshape(-1, n_channels).astype(np.float32)

    if n_channels == 1:
        data = np.column_stack([data, data])

    # Resample with linear interpolation
    if src_rate != target_rate:
        n_in = len(data)
        n_out = int(n_in * target_rate / src_rate)
        t_in = np.arange(n_in, dtype=np.float32)
        t_out = np.linspace(0, n_in - 1, n_out, dtype=np.float32)
        left  = np.interp(t_out, t_in, data[:, 0])
        right = np.interp(t_out, t_in, data[:, 1])
        data = np.column_stack([left, right])
        print(f"  resampled {src_rate} → {target_rate} Hz: {n_out} frames")

    return data.astype(np.int16)


def write_wav(path: str, samples: np.ndarray, rate: int) -> None:
    with wave.open(path, "w") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.astype(np.int16).tobytes())


def compare(ours: np.ndarray, ref: np.ndarray, rate: int) -> None:
    n = min(len(ours), len(ref))
    ours = ours[:n].astype(np.float32)
    ref  = ref[:n].astype(np.float32)
    diff = ours - ref

    print(f"\n=== Comparison ({n} samples = {n/rate:.2f}s) ===")
    print(f"Our   RMS: {np.sqrt(np.mean(ours**2)):.1f}")
    print(f"Ref   RMS: {np.sqrt(np.mean(ref**2)):.1f}")
    print(f"Diff  RMS: {np.sqrt(np.mean(diff**2)):.1f}")
    print(f"Max abs diff: {np.max(np.abs(diff)):.0f}")

    # Per-second breakdown
    print(f"\nPer-second RMS diff (left channel):")
    for sec in range(int(n / rate)):
        sl = slice(sec * rate, (sec + 1) * rate)
        rms = np.sqrt(np.mean(diff[sl, 0] ** 2))
        bar = "#" * int(rms / 500)
        print(f"  {sec:3d}s  {rms:7.1f}  {bar}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("spc", help="SPC file path")
    parser.add_argument("wav", help="Reference WAV path")
    parser.add_argument("--seconds", type=float, default=10.0, help="Duration to compare")
    parser.add_argument("--dump-ours", metavar="OUT.wav", help="Write our output to this WAV file")
    args = parser.parse_args()

    ours = dump_pysnes(args.spc, args.seconds)
    ref  = load_reference(args.wav, args.seconds, _AUDIO_HZ)

    if args.dump_ours:
        write_wav(args.dump_ours, ours, _AUDIO_HZ)
        print(f"Our output written to {args.dump_ours}")

    compare(ours, ref, _AUDIO_HZ)


if __name__ == "__main__":
    main()
