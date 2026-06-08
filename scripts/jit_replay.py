"""Quantify JIT vs real work: replay the SAME deterministic frames twice in one
warm process. Pass 2 sees identical content with the JIT fully warmed for it;
(pass1 - pass2) is the JIT/warmup contribution, the rest is real work."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import sdl2
from pysnes.pysnes import PySNES
from pysnes import savestate

ROM = "roms/Mega Man X (USA) (Rev 1).sfc"
STATE = "roms/Mega Man X (USA) (Rev 1).state"
MC = 262 * 1364
hdr = savestate.read_header(STATE)
savestate._compat_hash = lambda: hdr["compat_hash"]

s = PySNES(ROM, settings={"headless": True})
s.cpu.start(s.scheduler); s.ppu.start()

def run_pass(n):
    savestate.load(s, STATE)              # reset to identical start
    s.controllers[0].pressed_keys.clear()
    s.controllers[0].pressed_keys.add(sdl2.SDLK_RIGHT)
    times = []
    for _ in range(n):
        t0 = time.perf_counter()
        s.scheduler.run_to(s.scheduler.master_clock + MC)
        s.apu.sync_to(s.scheduler.master_clock)
        s.apu.generate_audio_frame(530)
        times.append((time.perf_counter() - t0) * 1000)
    return times

n = next((int(a) for a in sys.argv[1:] if a.isdigit()), 600)
# generic warmup first
run_pass(150)

a = run_pass(n)   # pass 1
b = run_pass(n)   # pass 2 (identical frames, warmer)
c = run_pass(n)   # pass 3

def summ(name, t):
    s_ = sorted(t)
    print(f"{name}: avg {sum(t)/len(t):6.2f}  p50 {s_[len(s_)//2]:6.2f}  p95 {s_[int(len(s_)*.95)]:6.2f}  max {max(t):7.2f}")

summ("pass1", a)
summ("pass2", b)
summ("pass3", c)
# per-frame: how much faster is pass2 vs pass1 on the SAME frame index?
deltas = [a[i] - b[i] for i in range(n)]
big = [(i, a[i], b[i]) for i in range(n) if a[i] - b[i] > 5]
print(f"avg per-frame (pass1-pass2) = {sum(deltas)/n:.2f}ms")
print(f"frames >5ms faster on replay: {len(big)}/{n}")
for i, av, bv in big[:12]:
    print(f"  frame {i}: pass1 {av:6.2f}  pass2 {bv:6.2f}  saved {av-bv:6.2f}")
