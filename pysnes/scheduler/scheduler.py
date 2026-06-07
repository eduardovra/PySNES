import heapq



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

    def dump_state(self) -> dict:
        """Serialize the queue. Handlers are bound methods; persist them as
        ("owner_kind", "method_name") pairs so they can be re-resolved against
        a freshly booted PySNES instance on load.
        """
        entries = []
        for t, seq, fn in self._queue:
            owner = getattr(fn, "__self__", None)
            method = getattr(fn, "__func__", None)
            if owner is None or method is None:
                raise ValueError(
                    f"Cannot serialize scheduler entry with non-bound-method handler: {fn!r}"
                )
            owner_kind = owner.__class__.__name__.lower()  # "cpu", "ppu", "apu"
            entries.append((int(t), int(seq), owner_kind, method.__name__))
        return {
            "master_clock": int(self.master_clock),
            "seq": int(self._seq),
            "queue": entries,
        }

    def load_state(self, d: dict, registry: dict) -> None:
        """Rebuild the queue from a dump. `registry` maps owner_kind → object
        instance (e.g. {"cpu": pysnes.cpu, "ppu": pysnes.ppu, "apu": pysnes.apu}).
        """
        self.master_clock = d["master_clock"]
        self._seq = d["seq"]
        self._queue = []
        for t, seq, owner_kind, method_name in d["queue"]:
            if owner_kind not in registry:
                raise ValueError(
                    f"Scheduler load: unknown owner kind {owner_kind!r} "
                    f"(registry keys: {sorted(registry)})"
                )
            owner = registry[owner_kind]
            fn = getattr(owner, method_name, None)
            if not callable(fn):
                raise ValueError(
                    f"Scheduler load: {owner_kind}.{method_name} is not callable"
                )
            self._queue.append((t, seq, fn))
        heapq.heapify(self._queue)
