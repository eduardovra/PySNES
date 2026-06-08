"""A/B test PyPy JIT params on the held-RIGHT MMX workload.

Usage:
    uv run scripts/jit_test.py [n] [key=val ...]
e.g.
    uv run scripts/jit_test.py 1200
    uv run scripts/jit_test.py 1200 trace_limit=20000
    uv run scripts/jit_test.py 1200 trace_limit=30000 trace_eagerness=400
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Apply JIT params BEFORE importing/running emulator code so traces compile
# under the new settings.
import pypyjit
params = {}
for a in sys.argv[1:]:
    if "=" in a:
        k, v = a.split("=")
        params[k] = int(v)
if params:
    pypyjit.set_param(**params)

import sdl2
from pysnes.pysnes import PySNES
from pysnes import savestate

ROM = "roms/Mega Man X (USA) (Rev 1).sfc"
STATE = "roms/Mega Man X (USA) (Rev 1).state"
MC = 262 * 1364
hdr = savestate.read_header(STATE)
savestate._compat_hash = lambda: hdr["compat_hash"]

n = next((int(a) for a in sys.argv[1:] if a.isdigit()), 1200)

s = PySNES(ROM, settings={"headless": True})
s.cpu.start(s.scheduler); s.ppu.start()
savestate.load(s, STATE)
s.controllers[0].pressed_keys.add(sdl2.SDLK_RIGHT)

def frame():
    s.scheduler.run_to(s.scheduler.master_clock + MC)
    s.apu.sync_to(s.scheduler.master_clock)
    s.apu.generate_audio_frame(530)

for _ in range(150):
    frame()

times = []
for _ in range(n):
    t0 = time.perf_counter()
    frame()
    times.append((time.perf_counter() - t0) * 1000)

s_ = sorted(times)
BUDGET = MC / 21_477_272.0 * 1000.0
over = sum(1 for t in times if t > BUDGET)
print(f"params={params or 'DEFAULT'}")
print(f"  avg {sum(times)/n:6.2f}ms  p50 {s_[n//2]:6.2f}  p95 {s_[int(n*.95)]:6.2f}  max {max(times):7.2f}  over {100*over/n:4.1f}%")
