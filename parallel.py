"""Multi-core job layer for PLOUTO.

Two pieces, each used only where it helps:

- ``SteerBatcher`` runs one frame of enemy steering (``enemy_steer.steer_chunk``) inline or in a
  process pool. The pool is opt-in (``config.PARALLEL_STEER_ENABLED``) and is gated by a live enemy
  count (``config.PARALLEL_STEER_MIN_ENEMIES``). Inline and pooled runs give identical results.
- ``ThreadedLoader`` runs I/O-bound asset reads on threads. Decoding and pyglet object creation stay
  on the main thread.

Windows note: the pool uses the "spawn" start method. Spawned children import the entry script
again as ``__mp_main__``, so every script that starts a pool must guard its top level with
``if __name__ == "__main__":``. Worker entry points live in importable modules that do not import
pyglet (``enemy_steer.steer_chunk``), which keeps worker start-up cheap.

Measurements behind these defaults: see tools/bench_steer.py and the wave 1 report.
"""

import atexit
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool

import config
from enemy import steer_snapshot, update_enemy
from enemy_steer import SteerBatch, steer_chunk
from utils import Vec2

# A batch with no units. Submitting it wakes a worker without doing any work.
_EMPTY_BATCH = SteerBatch(snaps=(), px=0.0, py=0.0, dt=0.0, pressure_mult=1.0, steer_mult=1.0)


def chunk_ranges(n: int, parts: int) -> list:
    """Split ``range(n)`` into at most ``parts`` contiguous, near-equal, ordered chunks."""
    if n <= 0:
        return [(0, 0)]
    parts = max(1, min(int(parts), int(n)))
    base, extra = divmod(int(n), parts)
    out = []
    start = 0
    for i in range(parts):
        size = base + (1 if i < extra else 0)
        out.append((start, start + size))
        start += size
    return out


def spawn_context():
    """Start method used for every pool. Spawn is the Windows-safe choice (no fork)."""
    return multiprocessing.get_context("spawn")


class SteerBatcher:
    """Runs ``steer_chunk`` over one frame's ``SteerBatch``.

    ``workers=0`` runs inline. Otherwise the batch is split into contiguous chunks and each chunk
    runs in a spawn-context process pool, created on first use. Each result depends only on the
    batch, so inline and pooled runs return equal lists.

    ``verify=True`` also runs the inline reference on every frame and counts mismatches. Tests use
    it to check determinism on live game frames.
    """

    def __init__(self, workers: int = 0, min_enemies: int = 32, verify: bool = False) -> None:
        self.workers = max(0, int(workers))
        self.min_enemies = max(0, int(min_enemies))
        self.verify = bool(verify)
        self.frames = 0
        self.mismatches = 0
        self._pool = None
        self._warmed = False
        self._atexit_registered = False

    def wants(self, live_count: int) -> bool:
        """True when a frame with this many live enemies should take the batch path."""
        return int(live_count) >= self.min_enemies

    def steer(self, batch) -> list:
        """Steering results for every snapshot in ``batch``, in snapshot order."""
        n = len(batch.snaps)
        self.frames += 1
        if self.workers <= 0 or n == 0:
            return steer_chunk(batch, 0, n)
        try:
            pool = self._ensure_pool()
            futures = [pool.submit(steer_chunk, batch, a, b) for a, b in chunk_ranges(n, self.workers)]
            results = []
            for fut in futures:
                results.extend(fut.result())
        except (BrokenProcessPool, OSError) as exc:
            # A worker died or could not start. Finish this frame inline and stay serial from now on.
            print("parallel: steering pool failed (%s); using the inline path for this run" % exc)
            self.close()
            self.workers = 0
            return steer_chunk(batch, 0, n)
        if self.verify and steer_chunk(batch, 0, n) != results:
            self.mismatches += 1
        return results

    def warm(self) -> None:
        """Start the pool's workers without waiting for them.

        A spawned worker takes seconds to start on Windows, so the first big fight would stall if the
        pool started then. Calling this on the first small frame lets the workers boot while the wave
        is still small. Later calls do nothing.
        """
        if self.workers <= 0 or self._warmed:
            return
        self._warmed = True
        pool = self._ensure_pool()
        for _ in range(self.workers):
            pool.submit(steer_chunk, _EMPTY_BATCH, 0, 0)

    def close(self) -> None:
        """Shut the pool down. Safe to call more than once."""
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    def _ensure_pool(self):
        if self._pool is None:
            self._pool = ProcessPoolExecutor(max_workers=self.workers, mp_context=spawn_context())
            if not self._atexit_registered:
                atexit.register(self.close)
                self._atexit_registered = True
        return self._pool


def update_enemies_batched(state, game, dt: float, player_pos: Vec2, player_vel: Vec2, batcher: SteerBatcher) -> set:
    """Batch-path enemy update for one frame. Returns the ``id``s of the enemies it updated.

    Phase 1 runs every live enemy's behavior serially, without coordination. Phase 2 snapshots all
    non-boss enemies once and steers them through ``batcher``. Steering therefore reads positions
    after every behavior has moved, which differs slightly from the interleaved default path.
    Inline and pooled batch runs are identical to each other.
    """
    live = [e for e in state.enemies if e.hp > 0 and not getattr(e, "_is_dead", False)]
    for e in live:
        update_enemy(e, player_pos, state, dt, game, player_vel=player_vel, coordinate=False)
    steered = {id(e) for e in live}
    batch, owners = steer_snapshot(state, player_pos, player_vel, dt, steered)
    apply_steering(owners, batcher.steer(batch))
    return steered


def apply_steering(owners, results) -> None:
    """Write steering results back onto their enemies. ``None`` means the unit was not steered."""
    for owner, res in zip(owners, results):
        if res is None:
            continue
        owner.vel = Vec2(res[0], res[1])
        owner.ai["forward_lock_t"] = res[2]


_override = None
_configured = None


def set_batcher(batcher) -> None:
    """Test hook: use ``batcher`` for every frame (None restores the config-driven choice)."""
    global _override
    _override = batcher


def active_batcher():
    """The batcher the game should use, or None when batch steering is off."""
    global _configured
    if _override is not None:
        return _override
    if not config.PARALLEL_STEER_ENABLED:
        return None
    key = (int(config.PARALLEL_STEER_WORKERS), int(config.PARALLEL_STEER_MIN_ENEMIES))
    if _configured is None or _configured[0] != key:
        if _configured is not None:
            _configured[1].close()
        _configured = (key, SteerBatcher(workers=key[0], min_enemies=key[1]))
    return _configured[1]


def close_batcher() -> None:
    """Shut down the steering pool (and any test override). Called on window close; safe to repeat."""
    global _configured
    for batcher in (_override, None if _configured is None else _configured[1]):
        if batcher is not None:
            batcher.close()
    _configured = None


def maybe_update_enemies(state, game, dt: float, player_pos: Vec2, player_vel: Vec2):
    """Hook for the playing state. Returns the batch-updated enemy ids, or None to use the default loop.

    None is returned (and nothing is changed) unless batch steering is enabled and the live enemy
    count reaches the threshold, so the default path stays exactly as it was.
    """
    batcher = active_batcher()
    if batcher is None:
        return None
    live = sum(1 for e in state.enemies if e.hp > 0 and not getattr(e, "_is_dead", False))
    if not batcher.wants(live):
        batcher.warm()  # no-op after the first call; hides the spawn cost behind the early waves
        return None
    return update_enemies_batched(state, game, dt, player_pos, player_vel, batcher)


def _read_bytes(path: str):
    try:
        with open(path, "rb") as fh:
            return fh.read()
    except OSError:
        return None


class ThreadedLoader:
    """Runs I/O-bound callables on a thread pool and returns results in input order.

    Threads, not processes: the work is file reads, which release the GIL, and pyglet objects must
    be created on the main thread anyway. With one worker or one item the calls run inline.
    """

    def __init__(self, workers: int | None = None) -> None:
        if workers is None:
            workers = config.PARALLEL_LOADER_WORKERS
        self.workers = max(1, int(workers))
        self._pool = None

    def map(self, fn, items) -> list:
        items = list(items)
        if self.workers <= 1 or len(items) <= 1:
            return [fn(item) for item in items]
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="ploto-load")
        return list(self._pool.map(fn, items))

    def read_bytes(self, paths) -> list:
        """File contents for each path, in order. A missing or unreadable file gives None."""
        return self.map(_read_bytes, paths)

    def close(self) -> None:
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True)
