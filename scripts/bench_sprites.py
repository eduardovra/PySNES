"""Deterministic sprite-rendering micro-benchmark: fill OAM with many visible
sprites and time rendering a screenful of scanlines. Isolates obj_renderer cost
(no JIT/scene noise). Run on the clean tree and on the change to compare."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from pysnes.ppu.ppu import Ppu
from pysnes.ppu import obj_renderer

ppu = Ppu()
# 4bpp sprite tiles: write a non-trivial pattern into VRAM so pixels are opaque.
for a in range(0, 0x8000):
    ppu.vram[a] = (a * 37) & 0xFF
# palette
for i in range(512):
    ppu.cgram[i] = (i * 53) & 0xFF
ppu._cgram_dirty = True
ppu.oam_main_screen_enable = True
ppu.oam_base_size = 5  # 32x32 / 64x64
ppu.oam_tiledata_address = 0

# Fill all 128 sprites spread across the screen, all visible, 32x32.
for n in range(128):
    o = ppu.oam.objects[n]
    o.x = (n * 2) % 256
    o.y = (n % 100) + 1
    o.character = n & 0xFF
    o.palette = n & 7
    o.priority = n & 3
    o.size = 0
    o.h_flip = n & 1
    o.v_flip = (n >> 1) & 1
    o.name_select = 0

def render_frames(frames):
    for f in range(frames):
        ppu.frames = f
        for vc in range(1, 225):
            ppu.v_counter = vc
            for pr in range(4):
                obj_renderer.draw_objects(ppu, priority=pr)

# warmup JIT
render_frames(30)

best = 1e9
for trial in range(5):
    t0 = time.perf_counter()
    render_frames(60)
    dt = (time.perf_counter() - t0) / 60 * 1000
    best = min(best, dt)
print(f"sprite render: {best:.3f} ms/frame (best of 5, 128 sprites x 32x32)")
