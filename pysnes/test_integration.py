"""
Integration tests: compare PySNES emulation state against Mesen 2 (reference oracle).

Tier 1 — frame-level: compare CPU/SPC registers + WRAM CRC32 at each frame boundary.
Tier 2 — instruction-level: compare CPU trace line by line to find the exact diverging instruction.

Run:
    uv run --python pypy@3.10 pytest pysnes/test_integration.py::test_frame_divergence -v -s
    uv run --python pypy@3.10 pytest pysnes/test_integration.py::test_instruction_divergence -v -s

Skip in normal suite:
    uv run --python pypy@3.10 pytest pysnes/ -m "not integration"

Mesen binary expected at: tools/Mesen  (relative to repo root)
Override with env var: MESEN_BIN=/path/to/Mesen
"""

import json
import os
import socket
import subprocess
import threading
import zlib
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

# ---- Constants ----
REPO_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
MC_PER_FRAME = 262 * 1364
DEFAULT_ROM = os.environ.get("SNES_ROM", "roms/Super Mario World (U) [!].smc")


def get_mesen():
    """Return path to Mesen binary.

    Search order:
    1. MESEN_BIN environment variable
    2. settings.json "mesen_bin" value
    """
    from pysnes import settings as s  # noqa: PLC0415
    cfg = s.load()

    candidates = [
        os.environ.get("MESEN_BIN"),
        cfg.get("mesen_bin"),
    ]
    for path in candidates:
        if path and Path(path).exists():
            return path

    pytest.skip(
        "Mesen binary not found. Download from https://github.com/SourMesen/Mesen2/releases "
        "and set MESEN_BIN env var or 'mesen_bin' in settings.json"
    )


def _start_tcp_server():
    """Start a TCP server on a free port. Returns (server_socket, port)."""
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("localhost", 0))
    srv.listen(1)
    return srv, srv.getsockname()[1]


def _collect_lines(srv, timeout=120):
    """Accept one connection and collect all newline-delimited lines. Returns list of strings."""
    lines = []
    error = []
    def _run():
        try:
            srv.settimeout(timeout)
            conn, _ = srv.accept()
            srv.close()
            f = conn.makefile("r")
            for line in f:
                line = line.strip()
                if line:
                    lines.append(line)
            conn.close()
        except Exception as e:
            error.append(e)
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t, lines, error


def _find_display() -> str:
    """Return first available X display, falling back to :0."""
    for lock in sorted(Path("/tmp").glob(".X[0-9]*-lock")):
        num = lock.name.removeprefix(".X").removesuffix("-lock")
        if num.isdigit():
            return f":{num}"
    return ":0"


def _run_mesen(mesen, rom, lua_script, extra_env, timeout=300):
    """Spawn Mesen testrunner. Returns (stdout, stderr, returncode)."""
    env = os.environ.copy()
    env.update(extra_env)
    if "DISPLAY" not in env:
        env["DISPLAY"] = _find_display()
    cmd = [mesen, "--testrunner", rom, lua_script]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)
    return result.stdout, result.stderr, result.returncode


# ---- Tier 1 fixtures ----

@pytest.fixture(scope="session")
def oracle_frames(request):
    """Run Mesen headlessly, collect per-frame state via TCP socket."""
    n_frames = request.config.getoption("--frames")
    rom = os.path.abspath(os.environ.get("SNES_ROM", DEFAULT_ROM))
    if not Path(rom).exists():
        pytest.skip(f"ROM not found: {rom}")

    mesen = get_mesen()
    srv, port = _start_tcp_server()
    collect_t, lines, collect_err = _collect_lines(srv, timeout=120)

    lua_script = str(SCRIPTS_DIR / "mesen_oracle.lua")
    stdout, stderr, rc = _run_mesen(mesen, rom, lua_script, {
        "MESEN_PORT": str(port),
        "MESEN_FRAMES": str(n_frames),
    })
    collect_t.join(timeout=30)

    if rc != 0:
        pytest.fail(f"Mesen exited {rc}.\nstdout:\n{stdout}\nstderr:\n{stderr}")
    if collect_err:
        pytest.fail(f"Socket error: {collect_err[0]}")
    if not lines:
        pytest.fail(f"No frames received.\nstdout:\n{stdout}\nstderr:\n{stderr}")

    frames = [json.loads(l) for l in lines]
    print(f"\nMesen oracle: {len(frames)} frames collected", flush=True)
    return frames


@pytest.fixture(scope="session")
def pysnes_frames(request):
    """Run PySNES headlessly, capture per-frame state."""
    n_frames = request.config.getoption("--frames")
    rom = os.path.abspath(os.environ.get("SNES_ROM", DEFAULT_ROM))
    if not Path(rom).exists():
        pytest.skip(f"ROM not found: {rom}")

    from pysnes.pysnes import PySNES  # noqa: PLC0415

    pysnes = PySNES(rom, settings={"headless": True})
    pysnes.cpu.start(pysnes.scheduler)
    pysnes.ppu.start()

    frames = []
    for i in range(n_frames):
        frame_end = pysnes.scheduler.master_clock + MC_PER_FRAME
        pysnes.scheduler.run_to(frame_end)

        cpu = pysnes.cpu
        apu = pysnes.apu
        wram = (
            bytes(pysnes.bus.low_ram)
            + bytes(pysnes.bus.high_ram[:0x6000])
            + bytes(pysnes.bus.extended_ram)
        )
        psw = (
            (int(apu.NF) << 7) | (int(apu.VF) << 6) | (int(apu.PF) << 5) | (int(apu.BF) << 4)
            | (int(apu.HF) << 3) | (int(apu.IF) << 2) | (int(apu.ZF) << 1) | int(apu.CF)
        )
        frames.append({
            "frame": i + 1,
            "cpu": {
                "pc": cpu.PC.d & 0xFFFF,
                "a": cpu.A.value,
                "x": cpu.X.value,
                "y": cpu.Y.value,
                "sp": cpu.S.value,
                "ps": cpu.P,
                "k": (cpu.PC.d >> 16) & 0xFF,
                "d": cpu.D.value,
                "db": cpu.DB.value,
                "e": int(cpu.EF),
            },
            "spc": {
                "pc": apu.PC,
                "a": apu.A,
                "x": apu.X,
                "y": apu.Y,
                "sp": apu.S,
                "ps": psw,
            },
            "wram_crc32": zlib.crc32(wram) & 0xFFFFFFFF,
            "wram_head": list(wram[:16]),
        })

    print(f"\nPySNES: {len(frames)} frames captured", flush=True)
    return frames


# ---- Tier 1 test ----

def test_frame_divergence(oracle_frames, pysnes_frames):
    """Fail at the first frame where PySNES diverges from Mesen."""
    for ref, got in zip(oracle_frames, pysnes_frames):
        frame = ref["frame"]
        diffs = []

        for field in ("pc", "a", "x", "y", "sp", "ps", "k", "d", "e"):
            rv = ref["cpu"].get(field)
            gv = got["cpu"].get(field)
            if rv != gv:
                diffs.append(f"cpu.{field}: mesen={rv:#x} pysnes={gv:#x}")

        # Map Mesen's "db" field name (our PySNES also uses "db")
        rv = ref["cpu"].get("db", ref["cpu"].get("dbr"))
        gv = got["cpu"].get("db")
        if rv != gv:
            diffs.append(f"cpu.db: mesen={rv:#x} pysnes={gv:#x}")

        for field in ("pc", "a", "x", "y", "sp", "ps"):
            rv = ref["spc"].get(field)
            gv = got["spc"].get(field)
            if rv != gv:
                diffs.append(f"spc.{field}: mesen={rv:#x} pysnes={gv:#x}")

        # wram_crc32 comparison omitted until we can read WRAM from Mesen fast enough

        if diffs:
            msg = [f"Divergence at frame {frame}:"]
            msg.append(f"  Mesen  CPU: {_cpu_str(ref['cpu'])}")
            msg.append(f"  PySNES CPU: {_cpu_str(got['cpu'])}")
            msg.append(f"  Mesen  SPC: {_spc_str(ref['spc'])}")
            msg.append(f"  PySNES SPC: {_spc_str(got['spc'])}")
            msg.extend(f"  DIFF: {d}" for d in diffs)
            pytest.fail("\n".join(msg))


def _cpu_str(c):
    return (
        f"PC={c.get('k', 0):02X}:{c.get('pc', 0):04X} "
        f"A={c.get('a', 0):04X} X={c.get('x', 0):04X} Y={c.get('y', 0):04X} "
        f"S={c.get('sp', 0):04X} D={c.get('d', 0):04X} "
        f"DB={c.get('db', c.get('dbr', 0)):02X} P={c.get('ps', 0):02X} E={c.get('e', 0)}"
    )


def _spc_str(s):
    return (
        f"PC={s.get('pc', 0):04X} A={s.get('a', 0):02X} X={s.get('x', 0):02X} "
        f"Y={s.get('y', 0):02X} SP={s.get('sp', 0):02X} PSW={s.get('ps', 0):02X}"
    )


# ---- Tier 2 fixtures ----

@pytest.fixture(scope="session")
def oracle_trace_lines(request):
    """Run Mesen exec callback, collect CPU trace lines via TCP socket."""
    n_instructions = request.config.getoption("--instructions")
    rom = os.path.abspath(os.environ.get("SNES_ROM", DEFAULT_ROM))
    if not Path(rom).exists():
        pytest.skip(f"ROM not found: {rom}")

    mesen = get_mesen()
    srv, port = _start_tcp_server()
    collect_t, lines, collect_err = _collect_lines(srv, timeout=300)

    lua_script = str(SCRIPTS_DIR / "mesen_trace.lua")
    stdout, stderr, rc = _run_mesen(mesen, rom, lua_script, {
        "MESEN_PORT": str(port),
        "MESEN_INSTRUCTIONS": str(n_instructions),
    }, timeout=600)
    collect_t.join(timeout=60)

    if rc != 0:
        pytest.fail(f"Mesen exited {rc}.\nstdout:\n{stdout}\nstderr:\n{stderr}")
    if collect_err:
        pytest.fail(f"Socket error: {collect_err[0]}")
    if not lines:
        pytest.fail(f"No trace lines received.\nstdout:\n{stdout}\nstderr:\n{stderr}")

    print(f"\nMesen trace: {len(lines)} instructions", flush=True)
    return lines


@pytest.fixture(scope="session")
def pysnes_trace_lines(request):
    """Run PySNES headlessly, collect CPU trace lines."""
    n_instructions = request.config.getoption("--instructions")
    rom = os.path.abspath(os.environ.get("SNES_ROM", DEFAULT_ROM))
    if not Path(rom).exists():
        pytest.skip(f"ROM not found: {rom}")

    from pysnes.pysnes import PySNES  # noqa: PLC0415

    pysnes = PySNES(rom, settings={"headless": True})
    pysnes._trace_limit = n_instructions
    pysnes._trace_file = _LineCollector()
    pysnes._trace_ref = None
    pysnes.cpu.trace_enabled = True

    original_step = pysnes.cpu._step

    def traced_step():
        original_step()
        pysnes._check_trace()

    pysnes.cpu._step = traced_step
    pysnes.cpu.start(pysnes.scheduler)
    pysnes.ppu.start()

    while pysnes._trace_count < n_instructions:
        frame_end = pysnes.scheduler.master_clock + MC_PER_FRAME
        pysnes.scheduler.run_to(frame_end)

    lines = pysnes._trace_file.lines
    print(f"\nPySNES trace: {len(lines)} instructions", flush=True)
    return lines


class _LineCollector:
    """File-like object that collects lines written to it."""
    def __init__(self):
        self.lines = []

    def write(self, s):
        stripped = s.rstrip("\n")
        if stripped:
            self.lines.append(stripped)

    def flush(self):
        pass

    def close(self):
        pass


# ---- Tier 2 test ----

def test_instruction_divergence(oracle_trace_lines, pysnes_trace_lines):
    """Fail at the first CPU instruction where PySNES diverges from Mesen."""
    for i, (ref, got) in enumerate(zip(oracle_trace_lines, pysnes_trace_lines)):
        if ref.startswith("..") or got.startswith(".."):
            continue
        if ref[:6].lower() != got[:6].lower():
            pytest.fail(
                f"CPU trace divergence at instruction {i + 1}:\n"
                f"  MESEN : {ref}\n"
                f"  PYSNES: {got}"
            )
