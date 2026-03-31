import heapq

import cython


@cython.cclass
class Scheduler:
    """
    Discrete Event Scheduler (DES) — the single source of time for all components.

    All components schedule future callbacks here instead of polling in a loop.
    The master_clock counter is in SNES master clock units (~21.477 MHz NTSC).

    Timing reference:
        - 1 CPU memory access (fast)  =  6 master clocks
        - 1 CPU memory access (slow)  =  8 master clocks
        - 1 CPU memory access (xslow) = 12 master clocks
        - 1 scanline                  = 1364 master clocks
        - 1 frame (NTSC, 262 lines)   = 357,368 master clocks
        - 1 APU clock                 ≈ 21 master clocks  (exact: 21477272/1024000)
    """

    master_clock = cython.declare(cython.ulonglong, visibility="public")

    def __init__(self) -> None:
        self._queue: list = []
        self._seq: int = 0
        self.master_clock: int = 0

    def add(self, delay: int, handler) -> None:
        """Schedule handler to run delay master clocks from now."""
        t = self.master_clock + delay
        heapq.heappush(self._queue, (t, self._seq, handler))
        self._seq += 1

    def run_to(self, target: int) -> None:
        """Fire all events whose time <= target, advancing master_clock to each."""
        q = self._queue
        while q and q[0][0] <= target:
            t, _, fn = heapq.heappop(q)
            self.master_clock = t
            fn()

    def run_one(self) -> None:
        """Fire the single earliest event."""
        t, _, fn = heapq.heappop(self._queue)
        self.master_clock = t
        fn()

    def peek(self) -> int:
        """Return the time of the next scheduled event without firing it."""
        return self._queue[0][0] if self._queue else 0xFFFFFFFFFFFFFFFF
