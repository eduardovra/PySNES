"""Diagnose content-driven slowdowns: correlate per-frame time with
brightness pass, color-math pass, and sprite tile draws. Hold RIGHT."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import sdl2
from pysnes.pysnes import PySNES
from pysnes import savestate
from pysnes.ppu import obj_renderer, color_math

ROM = "roms/Mega Man X (USA) (Rev 1).sfc"
STATE = "roms/Mega Man X (USA) (Rev 1).state"
MC = 262 * 1364
hdr = savestate.read_header(STATE)
savestate._compat_hash = lambda: hdr["compat_hash"]

C = {"draw_tiles": 0, "brightness": 0, "composite": 0}
_dt = obj_renderer.draw_tiles
def draw_tiles(*a, **k):
    C["draw_tiles"] += 1
    return _dt(*a, **k)
obj_renderer.draw_tiles = draw_tiles
_b = color_math.apply_brightness_scanline
def bright(ppu):
    C["brightness"] += 1
    return _b(ppu)
color_math.apply_brightness_scanline = bright
_c = color_math.composite_scanline
def comp(ppu):
    C["composite"] += 1
    return _c(ppu)
color_math.composite_scanline = comp

s = PySNES(ROM, settings={"headless": True})
s.cpu.start(s.scheduler); s.ppu.start()
savestate.load(s, STATE)
s.controllers[0].pressed_keys.add(sdl2.SDLK_RIGHT)

def frame():
    s.scheduler.run_to(s.scheduler.master_clock + MC)
    s.apu.sync_to(s.scheduler.master_clock)
    s.apu.generate_audio_frame(530)

for _ in range(120):
    frame()

n = int(sys.argv[1]) if len(sys.argv) > 1 else 900
rows = []
for _ in range(n):
    for k in C: C[k] = 0
    t0 = time.perf_counter()
    frame()
    ms = (time.perf_counter() - t0) * 1000
    rows.append((ms, C["draw_tiles"], C["brightness"], C["composite"], s.ppu.display_brightness))

def corr(a, b):
    ma, mb = sum(a)/len(a), sum(b)/len(b)
    num = sum((x-ma)*(y-mb) for x, y in zip(a, b))
    da = sum((x-ma)**2 for x in a)**.5; db = sum((y-mb)**2 for y in b)**.5
    return num/(da*db) if da and db else 0.0

t = [r[0] for r in rows]
dt = [r[1] for r in rows]
br = [r[2] for r in rows]
co = [r[3] for r in rows]
print(f"frames={n}  avg={sum(t)/n:.2f}ms  max={max(t):.2f}ms")
print(f"avg draw_tiles/frame   = {sum(dt)/n:.0f}  (range {min(dt)}..{max(dt)})")
print(f"avg brightness-pass/fr = {sum(br)/n:.0f}  (frames with it: {sum(1 for x in br if x)}/{n})")
print(f"avg composite-pass/fr  = {sum(co)/n:.0f}  (frames with it: {sum(1 for x in co if x)}/{n})")
print(f"corr(time, draw_tiles)  = {corr(t, dt):.3f}")
print(f"corr(time, brightness)  = {corr(t, br):.3f}")
print(f"corr(time, composite)   = {corr(t, co):.3f}")
# windows of 1s: show how time tracks with draw_tiles & brightness
print("\nsec | avg_ms | draw_tiles | bright_lines | composite | brightness_val")
for w in range(0, n, 60):
    chunk = rows[w:w+60]
    if not chunk: break
    a = sum(c[0] for c in chunk)/len(chunk)
    d = sum(c[1] for c in chunk)//len(chunk)
    b = sum(c[2] for c in chunk)//len(chunk)
    cc = sum(c[3] for c in chunk)//len(chunk)
    bv = chunk[-1][4]
    print(f"{w//60:3d} | {a:6.2f} | {d:10d} | {b:12d} | {cc:9d} | {bv}")
