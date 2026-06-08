"""Windowed end-to-end FPS benchmark: replicates PySNES.main()'s frame loop
(compute + video present + frame limiter) so we can measure ACHIEVED fps with
a real SDL window — the only way to see the VSync interaction.

Loads the MMX save state and holds RIGHT. Reports achieved fps over wall clock.

    uv run scripts/bench_windowed.py [n_frames]
"""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sdl2
from pysnes.pysnes import PySNES
from pysnes import savestate

ROM = "roms/Mega Man X (USA) (Rev 1).sfc"
STATE = "roms/Mega Man X (USA) (Rev 1).state"
MC_PER_FRAME = 262 * 1364
FRAME_TIME_S = MC_PER_FRAME / 21_477_272.0
_HEADROOM_S = 0.003


def _bypass():
    hdr = savestate.read_header(STATE)
    savestate._compat_hash = lambda: hdr["compat_hash"]


def main():
    n = int([a for a in sys.argv[1:] if a.isdigit()][0]) if any(a.isdigit() for a in sys.argv[1:]) else 1000
    _bypass()
    snes = PySNES(ROM, settings={"headless": False})
    snes.cpu.start(snes.scheduler)
    snes.ppu.start()
    savestate.load(snes, STATE)
    snes.controllers[0].pressed_keys.add(sdl2.SDLK_RIGHT)

    # report what the renderer negotiated
    r = snes.video.sdl2_renderer
    if r:
        info = r.get_performance_info()
        print(f"renderer: {info.get('name')} accel={info.get('accelerated')} vsync={info.get('vsync')}", flush=True)

    present_times = []

    def frame():
        frame_end = snes.scheduler.master_clock + MC_PER_FRAME
        snes.scheduler.run_to(frame_end)
        if snes.audio is not None:
            snes.apu.sync_to(snes.scheduler.master_clock)
            snes._audio_frac += MC_PER_FRAME * snes.apu._APU_MC_DEN
            ns = snes._audio_frac // (snes.apu._APU_MC_NUM * 32)
            snes._audio_frac %= (snes.apu._APU_MC_NUM * 32)
            snes.audio.queue_samples(snes.apu.generate_audio_frame(ns))
        else:
            snes.apu.sync_to(snes.scheduler.master_clock)
        _p = time.perf_counter()
        snes.video.draw_textures(snes.ppu.main_bgs)
        present_times.append((time.perf_counter() - _p) * 1000)
        snes.video.update_screen()

    # warmup
    deadline = time.perf_counter()
    for _ in range(120):
        frame()
        deadline += FRAME_TIME_S
        rem = deadline - time.perf_counter()
        if rem > _HEADROOM_S:
            time.sleep(rem - _HEADROOM_S)
        while time.perf_counter() < deadline:
            pass

    # measured run
    times = []
    deadline = time.perf_counter()
    tick = deadline
    start = deadline
    for _ in range(n):
        frame()
        deadline += FRAME_TIME_S
        rem = deadline - time.perf_counter()
        if rem > _HEADROOM_S:
            time.sleep(rem - _HEADROOM_S)
        while time.perf_counter() < deadline:
            pass
        now = time.perf_counter()
        times.append((now - tick) * 1000)
        tick = now
        # drain events so the WM doesn't think we hung
        ev = sdl2.SDL_Event()
        while sdl2.SDL_PollEvent(ev):
            pass

    wall = time.perf_counter() - start
    s = sorted(times)
    achieved = n / wall
    under60 = sum(1 for t in times if t > 17.0)
    print(f"frames={n} wall={wall:.2f}s")
    print(f"  ACHIEVED fps = {achieved:.2f}")
    print(f"  per-frame ms: avg {sum(times)/len(times):.2f}  p50 {s[len(s)//2]:.2f}  p95 {s[int(len(s)*.95)]:.2f}  max {max(s):.2f}")
    print(f"  frames slower than 17ms (<59fps): {under60}/{n} ({100*under60/n:.1f}%)")
    pt = sorted(present_times)
    blocked = sum(1 for t in present_times if t > 5.0)
    print(f"  draw_textures(present) ms: avg {sum(present_times)/len(present_times):.2f}  p50 {pt[len(pt)//2]:.2f}  p95 {pt[int(len(pt)*.95)]:.2f}  max {max(pt):.2f}")
    print(f"  present() blocked >5ms (vsync stall): {blocked}/{len(present_times)} ({100*blocked/len(present_times):.1f}%)")
    snes.video.teardown_sdl()
    if snes.audio is not None:
        snes.audio.close()


if __name__ == "__main__":
    main()
