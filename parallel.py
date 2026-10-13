"""Multi-core job layer for PLOUTO.

Two pieces, each used only where it helps:

- ``SteerBatcher`` runs one frame of enemy steering (``enemy_steer.steer_chunk``) inline or on a pool
  of persistent worker processes. The pool is opt-in (``config.PARALLEL_STEER_ENABLED``) and is
  gated by a live enemy count (``config.PARALLEL_STEER_MIN_ENEMIES``). Inline and pooled runs return
  identical lists. The pool starts its workers once and keeps them until the window closes. Each
  frame is written into shared float64 arrays (``enemy_steer.pack_batch``) and each worker gets one
  raw byte message, so no snapshot is pickled per frame.
- ``ThreadedLoader`` runs I/O-bound asset reads on threads. Decoding and pyglet object creation stay
  on the main thread.

Windows note: the pool uses the "spawn" start method. Spawned children import the entry script
again as ``__mp_main__``, so every script that starts a pool must guard its top level with
``if __name__ == "__main__":``. The worker entry point lives in ``enemy_steer`` (no pyglet), which
keeps worker start-up cheap.

The measurement behind the defaults is written next to them in config.py.
"""

import atexit
import multiprocessing
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from multiprocessing import shared_memory

import config
from enemy import steer_snapshot, update_enemy
from enemy_steer import (
    FIELDS,
    HEADER,
    MSG_ACK,
    MSG_QUIT,
    OUT_FIELDS,
    RANGE_MSG,
    pack_batch,
    packable,
    steer_chunk,
    steer_worker_main,
    unpack_results,
)
from utils import Vec2

# Longest a steering frame waits for one worker. A worker that does not answer in this time is
# treated as broken, so a hung process cannot freeze the game.
STEER_ACK_TIMEOUT_S = 10.0


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


class _SteerTicket:
    """One chunk ``[start, stop)`` sent to one worker. ``result()`` waits for that worker."""

    def __init__(self, pool, worker: int, start: int, stop: int) -> None:
        self._pool = pool
        self._worker = worker
        self._start = start
        self._stop = stop
        self._done = False

    def result(self) -> list:
        if not self._done:
            self._pool._collect(self._worker)
            self._done = True
        return unpack_results(self._pool._out, self._start, self._stop)


class _SharedSteerPool:
    """``workers`` persistent spawn-context processes that steer packed frames from shared memory.

    The processes start once and stay alive. A new frame is packed into the input array when the
    first chunk of that batch is submitted. Each chunk then costs one small raw message to a worker,
    and the worker answers with an ack after it has written its results into the output array.

    The methods match the part of ``ProcessPoolExecutor`` that ``SteerBatcher`` uses: ``submit`` and
    ``shutdown``. ``submit`` takes ``steer_chunk`` as its function, so the call reads the same as the
    executor version.
    """

    def __init__(self, workers: int, capacity: int) -> None:
        self.capacity = max(1, int(capacity))
        self._procs = []
        self._conns = []
        self._busy = []  # workers holding a chunk whose ack has not been read yet
        self._frame = None  # the batch currently packed into the input array
        self._next = 0  # round-robin cursor; a frame's chunks land on distinct workers
        self._in_shm = None
        self._out_shm = None
        self._inp = None
        self._out = None
        ctx = spawn_context()
        try:
            self._in_shm = shared_memory.SharedMemory(create=True, size=8 * (HEADER + self.capacity * FIELDS))
            self._out_shm = shared_memory.SharedMemory(create=True, size=8 * self.capacity * OUT_FIELDS)
            self._inp = memoryview(self._in_shm.buf).cast("d")
            self._out = memoryview(self._out_shm.buf).cast("d")
            for _ in range(max(1, int(workers))):
                parent_end, child_end = ctx.Pipe(duplex=True)
                proc = ctx.Process(
                    target=steer_worker_main,
                    args=(child_end, self._in_shm.name, self._out_shm.name),
                    daemon=True,
                )
                try:
                    proc.start()
                except BaseException:
                    parent_end.close()
                    child_end.close()
                    raise
                child_end.close()  # the child now holds its own copy
                self._procs.append(proc)
                self._conns.append(parent_end)
        except BaseException:
            self.shutdown()
            raise

    def submit(self, fn, batch, start: int, stop: int) -> _SteerTicket:
        if fn is not steer_chunk:
            raise TypeError("the steering pool runs steer_chunk only")
        if not self._procs:
            raise OSError("the steering pool is closed")
        if batch is not self._frame:
            self._drain()  # no worker may still be reading the input array while it is rewritten
            pack_batch(batch, self._inp)
            self._frame = batch
        worker = self._next
        self._next = (self._next + 1) % len(self._procs)
        self._conns[worker].send_bytes(RANGE_MSG.pack(int(start), int(stop)))
        self._busy.append(worker)
        return _SteerTicket(self, worker, int(start), int(stop))

    def shutdown(self, wait: bool = True, cancel_futures: bool = False) -> None:
        """Stop the workers and release the shared arrays. Safe to call more than once."""
        for conn in self._conns:
            try:
                conn.send_bytes(MSG_QUIT)
            except (OSError, ValueError):
                pass  # the worker is already gone
        for proc in self._procs:
            proc.join(timeout=5.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=5.0)
        for conn in self._conns:
            conn.close()
        self._procs = []
        self._conns = []
        self._busy = []
        self._frame = None
        for view in (self._inp, self._out):
            if view is not None:
                view.release()
        self._inp = None
        self._out = None
        for shm in (self._in_shm, self._out_shm):
            if shm is not None:
                shm.close()
                shm.unlink()
        self._in_shm = None
        self._out_shm = None

    def _collect(self, worker: int) -> None:
        """Read the ack of ``worker``. A dead or silent worker raises ``BrokenProcessPool``."""
        conn = self._conns[worker]
        try:
            if not conn.poll(STEER_ACK_TIMEOUT_S):
                raise BrokenProcessPool("steering worker %d did not answer" % worker)
            msg = conn.recv_bytes()
        except (EOFError, OSError) as exc:
            raise BrokenProcessPool("steering worker %d stopped: %s" % (worker, exc)) from exc
        if msg != MSG_ACK:
            raise BrokenProcessPool("steering worker %d sent an unexpected reply" % worker)
        if worker in self._busy:
            self._busy.remove(worker)

    def _drain(self) -> None:
        for worker in list(self._busy):
            self._collect(worker)


class SteerBatcher:
    """Runs ``steer_chunk`` over one frame's ``SteerBatch``.

    ``workers=0`` runs inline. Otherwise the batch is split into contiguous chunks, one per worker,
    and the chunks run on a persistent pool of spawn-context processes that is created on first use.
    Each result depends only on the batch, so inline and pooled runs return equal lists.

    A batch that is too large for the shared arrays (``capacity`` units) or that uses a behavior or
    role name with no code is steered inline, and counted in ``fallbacks``.

    ``verify=True`` also runs the inline reference on every frame and counts mismatches. Tests use
    it to check determinism on live game frames.
    """

    def __init__(self, workers: int = 0, min_enemies: int = 32, verify: bool = False, capacity: int = 256) -> None:
        self.workers = max(0, int(workers))
        self.min_enemies = max(0, int(min_enemies))
        self.verify = bool(verify)
        self.capacity = max(1, int(capacity))
        self.frames = 0
        self.mismatches = 0
        self.fallbacks = 0
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
        if n > self.capacity or not packable(batch):
            self.fallbacks += 1
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
        """Start the steering workers without waiting for them.

        A spawned worker takes seconds to start on Windows, so the first big fight would stall if the
        pool started then. Calling this on the first small frame lets the workers boot while the wave
        is still small. Later calls do nothing.
        """
        if self.workers <= 0 or self._warmed:
            return
        self._warmed = True
        try:
            self._ensure_pool()
        except OSError as exc:
            print("parallel: steering pool failed to start (%s); using the inline path for this run" % exc)
            self.close()
            self.workers = 0

    def close(self) -> None:
        """Stop the workers and unlink the shared arrays. Safe to call more than once."""
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=True, cancel_futures=True)

    def _ensure_pool(self):
        if self._pool is None:
            self._pool = _SharedSteerPool(self.workers, self.capacity)
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
