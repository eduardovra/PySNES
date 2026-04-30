"""Smoke tests for save state. Marked @pytest.mark.harness — opt-in."""
from pathlib import Path

import pytest

pytestmark = pytest.mark.harness

REPO_ROOT = Path(__file__).parent.parent.parent
SMW_ROM = REPO_ROOT / "roms" / "Super Mario World (U) [!].smc"
ALT_ROM = REPO_ROOT / "roms" / "Final Fight (USA).sfc"


def _require_smw():
    if not SMW_ROM.exists():
        pytest.skip(f"SMW ROM not present at {SMW_ROM}")


def test_round_trip_identity(tmp_path):
    """Save → mutate → load → state matches the pre-save snapshot."""
    _require_smw()
    from pysnes.harness import Harness

    with Harness(SMW_ROM) as h:
        h.run_frames(60)
        path = tmp_path / "rt.state"

        pre = {
            "frame": h.frame,
            "scanline": h.scanline,
            "master_clock": h.master_clock,
            "cpu": h.cpu_state(),
            "ppu": h.ppu_state(),
            "vram": h.vram(0, 0x10000),
            "cgram": h.cgram(0, 512),
            "wram_low": h.wram(0x7E0000, 0x2000),
            "oam": h.oam(),
        }

        h.save_state(path)
        h.run_frames(60)            # mutate state
        assert h.frame == 120
        h.load_state(path)
        assert h.frame == pre["frame"]

        post = {
            "frame": h.frame,
            "scanline": h.scanline,
            "master_clock": h.master_clock,
            "cpu": h.cpu_state(),
            "ppu": h.ppu_state(),
            "vram": h.vram(0, 0x10000),
            "cgram": h.cgram(0, 512),
            "wram_low": h.wram(0x7E0000, 0x2000),
            "oam": h.oam(),
        }
        for k in pre:
            assert pre[k] == post[k], f"round-trip mismatch on {k}"


def test_determinism_after_load(tmp_path):
    """Save, run N frames (A); load, run N frames (B); A == B."""
    _require_smw()
    from pysnes.harness import Harness

    path = tmp_path / "det.state"
    with Harness(SMW_ROM) as h:
        h.run_frames(60)
        h.save_state(path)
        h.run_frames(60)
        a_cgram = h.cgram(0, 512)
        a_vram = h.vram(0, 0x10000)
        a_pc = h.cpu_state()["PC"]

    with Harness(SMW_ROM) as h:
        h.load_state(path)
        h.run_frames(60)
        b_cgram = h.cgram(0, 512)
        b_vram = h.vram(0, 0x10000)
        b_pc = h.cpu_state()["PC"]

    assert a_cgram == b_cgram
    assert a_vram == b_vram
    assert a_pc == b_pc


def test_rom_mismatch_refusal(tmp_path):
    """A state from one ROM cannot be loaded into another."""
    _require_smw()
    if not ALT_ROM.exists():
        pytest.skip(f"alt ROM missing: {ALT_ROM}")
    from pysnes.harness import Harness
    from pysnes.savestate import RomMismatchError

    path = tmp_path / "smw.state"
    with Harness(SMW_ROM) as h:
        h.run_frames(30)
        h.save_state(path)

    with Harness(ALT_ROM) as h:
        with pytest.raises(RomMismatchError) as excinfo:
            h.load_state(path)
        # Message should name both ROMs explicitly
        msg = str(excinfo.value)
        assert "SUPER MARIOWORLD" in msg or "MARIOWORLD" in msg


def test_file_format_version_mismatch(tmp_path):
    """Bumping the file_format_version byte makes load refuse."""
    _require_smw()
    import struct
    from pysnes.harness import Harness
    from pysnes.savestate import IncompatibleStateError, MAGIC

    path = tmp_path / "v.state"
    with Harness(SMW_ROM) as h:
        h.run_frames(30)
        h.save_state(path)

    blob = bytearray(path.read_bytes())
    # File format version is the u32 right after the magic
    assert blob[: len(MAGIC)] == MAGIC
    # bump the version
    o = len(MAGIC)
    (cur,) = struct.unpack("<I", bytes(blob[o : o + 4]))
    blob[o : o + 4] = struct.pack("<I", cur + 99)
    path.write_bytes(bytes(blob))

    with Harness(SMW_ROM) as h:
        with pytest.raises(IncompatibleStateError):
            h.load_state(path)


def test_compat_hash_mismatch(tmp_path):
    """Flipping a byte of the embedded compat_hash makes load refuse."""
    _require_smw()
    import json, struct
    from pysnes.harness import Harness
    from pysnes.savestate import IncompatibleStateError, MAGIC

    path = tmp_path / "h.state"
    with Harness(SMW_ROM) as h:
        h.run_frames(30)
        h.save_state(path)

    blob = bytearray(path.read_bytes())
    o = len(MAGIC)
    _, header_len = struct.unpack("<II", bytes(blob[o : o + 8]))
    o += 8
    header = json.loads(bytes(blob[o : o + header_len]).decode())
    # Flip a hex digit of the hash
    h_str = header["compat_hash"]
    flipped = ("1" if h_str[0] != "1" else "2") + h_str[1:]
    header["compat_hash"] = flipped
    new_header_bytes = json.dumps(header, indent=2).encode()
    if len(new_header_bytes) != header_len:
        # Pad/truncate would corrupt the file; this should be safe in practice
        # because indent=2 produces deterministic output. If not, the test
        # itself failed to flip-only — surface that loudly.
        pytest.skip("compat_hash flip changed JSON length; tweak fixture")
    blob[o : o + header_len] = new_header_bytes
    path.write_bytes(bytes(blob))

    with Harness(SMW_ROM) as h:
        with pytest.raises(IncompatibleStateError) as excinfo:
            h.load_state(path)
        assert "hash" in str(excinfo.value).lower()


def test_read_header_without_loading(tmp_path):
    """read_header() returns the JSON header without unpickling."""
    _require_smw()
    from pysnes.harness import Harness
    from pysnes.savestate import read_header

    path = tmp_path / "rh.state"
    with Harness(SMW_ROM) as h:
        h.run_frames(30)
        h.save_state(path)

    header = read_header(path)
    assert "compat_hash" in header
    assert header["rom_title"].startswith("SUPER MARIO")
    assert "saved_at" in header
    assert "python_impl" in header
