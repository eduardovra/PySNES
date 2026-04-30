"""Save state save/load for PySNES.

File format:

    13 bytes              magic = b"PYSNES_STATE\0"
    u32 little-endian     file_format_version  (FILE_FORMAT_VERSION)
    u32 little-endian     header_length (length in bytes of the JSON header)
    N bytes               JSON header (UTF-8) — Python-version-independent
    pickle payload        remaining bytes (state dict)

The JSON header carries a SHA-256 compat_hash computed from the running
Python build and the source bytes of every state-bearing module. The loader
recomputes the hash and refuses to load if it differs — this catches both
"saved on a different Python build" and "saved before a schema-changing
edit landed". ROM identity is checked against the JSON header too, so a
state file from one ROM cannot be loaded into another.

Save can only be taken at frame boundaries (see pysnes.savestate.save). The
caller (pysnes.PySNES) services F5/F9 requests after `scheduler.run_to(end)`
returns, when the scheduler queue is in a quiescent state.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import pickle
import struct
import subprocess
import sys
from pathlib import Path
from typing import Any

MAGIC = b"PYSNES_STATE\0"
FILE_FORMAT_VERSION = 1
SCHEMA_VERSION = 1

# Module sources that contribute to compat_hash. Adding a new state surface
# means adding the file here so a schema change automatically invalidates
# old states.
_HASHED_SOURCES = [
    "pysnes/cpu/cpu.py",
    "pysnes/cpu/dma.py",
    "pysnes/bus/bus.py",
    "pysnes/ppu/ppu.py",
    "pysnes/apu/apu.py",
    "pysnes/scheduler/scheduler.py",
    "pysnes/controller/controller.py",
    "pysnes/savestate/__init__.py",
]


class IncompatibleStateError(Exception):
    """Raised when a state file's format/version/compat hash doesn't match."""


class RomMismatchError(Exception):
    """Raised when a state file was saved for a different ROM."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _compat_hash() -> str:
    """SHA-256 fingerprint of (Python build) ⊕ (state-bearing source code).

    Two states with the same hash can interoperate. Two with different
    hashes cannot, regardless of the reason — easier to surface "load
    refused" than to debug a half-restored emulator.
    """
    h = hashlib.sha256()
    h.update(sys.version.encode())
    h.update(sys.implementation.name.encode())
    h.update(struct.pack("<I", pickle.HIGHEST_PROTOCOL))
    root = _repo_root()
    for rel in _HASHED_SOURCES:
        h.update(rel.encode())
        h.update(b"\0")
        h.update((root / rel).read_bytes())
    return h.hexdigest()


def _git_commit() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(_repo_root()),
            capture_output=True,
            text=True,
            timeout=2,
        )
        if out.returncode == 0:
            return out.stdout.strip()
    except (FileNotFoundError, subprocess.SubprocessError):
        pass
    return None


def _python_impl() -> str:
    impl = sys.implementation
    ver = ".".join(str(x) for x in impl.version[:3])
    return f"{impl.name} {ver}"


# ---------------------------------------------------------------------------
# Save / load
# ---------------------------------------------------------------------------

def save(pysnes, path) -> None:
    """Snapshot the running emulator to `path`.

    Must be called at a frame boundary (after scheduler.run_to(frame_end)
    returns). Mid-instruction saves can produce inconsistent CPU/PPU state.
    """
    rom_header = pysnes.bus.rom.snes_header
    state = {
        "rom": {"title": rom_header.game_title, "checksum": rom_header.checksum},
        "cpu": pysnes.cpu.dump_state(),
        "bus": pysnes.bus.dump_state(),
        "ppu": pysnes.ppu.dump_state(),
        "apu": pysnes.apu.dump_state(),
        "dma": pysnes.cpu.dma.dump_state(),
        "controllers": [c.dump_state() for c in pysnes.controllers],
        "scheduler": pysnes.scheduler.dump_state(),
    }
    payload = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)

    header = {
        "compat_hash": _compat_hash(),
        "schema_version": SCHEMA_VERSION,
        "python_version": sys.version,
        "python_impl": _python_impl(),
        "pysnes_commit": _git_commit(),
        "saved_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rom_title": rom_header.game_title,
        "rom_checksum": rom_header.checksum,
        "rom_path": str(getattr(pysnes.bus.rom, "rom_file_path", "")),
    }
    header_bytes = json.dumps(header, indent=2).encode("utf-8")

    out = bytearray()
    out += MAGIC
    out += struct.pack("<I", FILE_FORMAT_VERSION)
    out += struct.pack("<I", len(header_bytes))
    out += header_bytes
    out += payload

    Path(path).write_bytes(bytes(out))


def load(pysnes, path) -> None:
    """Restore emulator state from `path`. Mutates `pysnes` in place.

    Raises:
      - FileNotFoundError if `path` does not exist.
      - IncompatibleStateError on bad magic, file_format mismatch, or
        compat_hash mismatch.
      - RomMismatchError if the state was saved for a different ROM.
    """
    blob = Path(path).read_bytes()
    if len(blob) < len(MAGIC) + 8 or blob[: len(MAGIC)] != MAGIC:
        raise IncompatibleStateError(
            f"{path}: not a PySNES state file (bad magic)"
        )
    o = len(MAGIC)
    file_format_version, header_len = struct.unpack("<II", blob[o : o + 8])
    o += 8
    if file_format_version != FILE_FORMAT_VERSION:
        raise IncompatibleStateError(
            f"{path}: file format v{file_format_version} cannot be loaded by "
            f"v{FILE_FORMAT_VERSION}"
        )
    header_bytes = blob[o : o + header_len]
    o += header_len
    try:
        header = json.loads(header_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise IncompatibleStateError(f"{path}: corrupt header — {e}")

    expected_hash = _compat_hash()
    saved_hash = header.get("compat_hash", "")
    if saved_hash != expected_hash:
        raise IncompatibleStateError(
            f"{path}: compatibility hash mismatch — refusing to load.\n"
            f"  saved on:   {header.get('python_impl', '?')} "
            f"(commit {header.get('pysnes_commit') or '?'}, hash {saved_hash[:12]}...)\n"
            f"  current:    {_python_impl()} "
            f"(commit {_git_commit() or '?'}, hash {expected_hash[:12]}...)\n"
            f"State files are tied to the exact Python build and source code "
            f"that produced them."
        )
    if header.get("schema_version") != SCHEMA_VERSION:
        raise IncompatibleStateError(
            f"{path}: schema v{header.get('schema_version')} != current "
            f"v{SCHEMA_VERSION}"
        )

    rom_header = pysnes.bus.rom.snes_header
    if header.get("rom_checksum") != rom_header.checksum:
        raise RomMismatchError(
            f"{path}: state was made for "
            f"{header.get('rom_title','?')!r} (checksum 0x{header.get('rom_checksum',0):04X}), "
            f"but loaded ROM is {rom_header.game_title!r} "
            f"(checksum 0x{rom_header.checksum:04X}). Refusing to load."
        )

    state = pickle.loads(blob[o:])

    # Mutate the running pysnes in place. Order matters: bus & PPU memories
    # first (the CPU may be paused but its registers reference DB/PC into
    # ROM/RAM addresses — restoring RAM before regs is safer), then CPU,
    # APU, DMA, controllers, scheduler last (so the queue references
    # already-restored objects).
    pysnes.bus.load_state(state["bus"])
    pysnes.ppu.load_state(state["ppu"])
    pysnes.apu.load_state(state["apu"])
    pysnes.cpu.load_state(state["cpu"])
    pysnes.cpu.dma.load_state(state["dma"])
    for c, cs in zip(pysnes.controllers, state["controllers"]):
        c.load_state(cs)
    registry = {
        "cpu": pysnes.cpu,
        "ppu": pysnes.ppu,
        "apu": pysnes.apu,
    }
    pysnes.scheduler.load_state(state["scheduler"], registry)


def read_header(path) -> dict:
    """Return the JSON header from a state file without loading the payload.

    Useful for tools that want to inspect "what is this .state file?" without
    risking pickle execution.
    """
    blob = Path(path).read_bytes()
    if blob[: len(MAGIC)] != MAGIC:
        raise IncompatibleStateError(f"{path}: not a PySNES state file")
    o = len(MAGIC)
    _, header_len = struct.unpack("<II", blob[o : o + 8])
    o += 8
    return json.loads(blob[o : o + header_len].decode("utf-8"))
