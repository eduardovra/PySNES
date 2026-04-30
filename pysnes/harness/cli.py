"""NDJSON stdin/stdout RPC for the harness.

Run as:

    uv run python -m pysnes.harness.cli --rom ROM.smc

Each line of stdin is a JSON object: {"method": "run_frames", "args": {"n": 60}}.
Each line of stdout is: {"ok": true, "result": ...} or {"ok": false, "error": "..."}.

Methods mirror the `Harness` class. Binary blobs (cgram, vram, oam, wram) come
back base64-encoded.

Bus-write hooks are surfaced via a poll/drain pattern — `watch_writes(lo, hi)`
appends to an internal log; `drain_writes()` returns and clears it. This keeps
the protocol strictly request/response, no async events.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path
from typing import Any

from pysnes.harness import Harness


class _CLI:
    def __init__(self, harness: Harness):
        self.h = harness
        self._write_log: list[dict[str, int]] = []
        self._watching = False

    # Each method here returns a JSON-serializable value (or None).
    def run_frames(self, n: int) -> dict[str, int]:
        self.h.run_frames(int(n))
        return self._state()

    def run_until_break(self, max_frames: int = 600) -> dict[str, Any]:
        hit = self.h.run_until_break(int(max_frames))
        return {"hit": hit, **self._state()}

    def run_to_scanline(self, v: int) -> dict[str, int]:
        self.h.run_to_scanline(int(v))
        return self._state()

    def press(self, buttons: Any) -> None:
        self.h.press(buttons)

    def release(self, buttons: Any) -> None:
        self.h.release(buttons)

    def clear_input(self) -> None:
        self.h.clear_input()

    def tap(self, buttons: Any, hold_frames: int = 2, gap_frames: int = 1) -> dict[str, int]:
        self.h.tap(buttons, hold_frames=int(hold_frames), gap_frames=int(gap_frames))
        return self._state()

    def play(self, macro: list) -> dict[str, int]:
        # macro is a JSON list of [frames, buttons] pairs
        self.h.play([(int(frames), buttons) for frames, buttons in macro])
        return self._state()

    def screenshot(self, path: str) -> dict[str, str]:
        self.h.screenshot(path)
        return {"path": str(Path(path).resolve())}

    def cgram(self, start: int = 0, end: int = 512) -> dict[str, Any]:
        return _b64_blob(self.h.cgram(int(start), int(end)))

    def vram(self, start: int = 0, length: int = 0x10000) -> dict[str, Any]:
        return _b64_blob(self.h.vram(int(start), int(length)))

    def oam(self) -> dict[str, Any]:
        return _b64_blob(self.h.oam())

    def wram(self, addr: int, length: int) -> dict[str, Any]:
        return _b64_blob(self.h.wram(int(addr, 0) if isinstance(addr, str) else int(addr), int(length)))

    def cpu_state(self) -> dict[str, Any]:
        return self.h.cpu_state()

    def ppu_state(self) -> dict[str, Any]:
        return self.h.ppu_state()

    def state(self) -> dict[str, Any]:
        return {**self._state(), "cpu": self.h.cpu_state(), "ppu": self.h.ppu_state()}

    def set_breakpoint(self, addr: int) -> None:
        self.h.set_breakpoint(int(addr, 0) if isinstance(addr, str) else int(addr))

    def clear_breakpoint(self, addr: int) -> None:
        self.h.clear_breakpoint(int(addr, 0) if isinstance(addr, str) else int(addr))

    def watch_writes(self, lo: int, hi: int) -> None:
        """Install a write-watch on the [lo, hi] address range. Captured writes
        accumulate until drained via `drain_writes`.
        """
        lo_i = int(lo, 0) if isinstance(lo, str) else int(lo)
        hi_i = int(hi, 0) if isinstance(hi, str) else int(hi)

        def hook(harness, addr, value):
            self._write_log.append(
                {
                    "frame": harness.frame,
                    "scanline": harness.scanline,
                    "addr": addr,
                    "value": value,
                }
            )

        self.h.on_write_range(lo_i, hi_i, hook)
        self._watching = True

    def drain_writes(self) -> list[dict[str, int]]:
        out, self._write_log = self._write_log, []
        return out

    def save_state(self, path: str) -> dict[str, str]:
        self.h.save_state(path)
        return {"path": str(Path(path).resolve())}

    def load_state(self, path: str) -> dict[str, Any]:
        self.h.load_state(path)
        return self._state()

    def quit(self) -> None:
        # Sentinel — handled in main()
        raise SystemExit(0)

    # internal
    def _state(self) -> dict[str, int]:
        return {
            "frame": self.h.frame,
            "scanline": self.h.scanline,
            "master_clock": self.h.master_clock,
            "paused": self.h.paused,
        }


def _b64_blob(data: bytes) -> dict[str, Any]:
    return {"length": len(data), "b64": base64.b64encode(data).decode()}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PySNES harness RPC over NDJSON.")
    parser.add_argument("--rom", required=True, help="Path to ROM file.")
    parser.add_argument("--sram", help="Optional SRAM path.", default=None)
    args = parser.parse_args(argv)

    harness = Harness(args.rom, sram_path=args.sram)
    cli = _CLI(harness)

    # Greet so the caller knows we're ready.
    sys.stdout.write(json.dumps({"ok": True, "ready": True, **cli._state()}) + "\n")
    sys.stdout.flush()

    try:
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError as e:
                _reply(False, error=f"bad JSON: {e}")
                continue

            method = req.get("method")
            kwargs = req.get("args", {}) or {}
            if not isinstance(method, str):
                _reply(False, error="missing 'method' field")
                continue
            fn = getattr(cli, method, None)
            if not callable(fn):
                _reply(False, error=f"unknown method {method!r}")
                continue
            try:
                result = fn(**kwargs)
                _reply(True, result=result)
            except SystemExit:
                _reply(True, result={"quit": True})
                return 0
            except Exception as e:
                _reply(False, error=f"{type(e).__name__}: {e}")
    finally:
        harness.close()
    return 0


def _reply(ok: bool, *, result: Any = None, error: str | None = None) -> None:
    payload: dict[str, Any] = {"ok": ok}
    if ok:
        payload["result"] = result
    else:
        payload["error"] = error
    sys.stdout.write(json.dumps(payload, default=str) + "\n")
    sys.stdout.flush()


if __name__ == "__main__":
    sys.exit(main())
