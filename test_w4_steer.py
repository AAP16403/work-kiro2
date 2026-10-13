"""Wave 4 steering tests: the persistent shared-memory pool for batched enemy steering.

Covers: the packed worker kernel against steer_chunk on random snapshots (exact), pooled frames
against inline steering across frame sizes, two seeded runs repeating exactly, fallback for batches
that cannot be packed, a worker that dies mid-run, warm-up, the shipped threshold and default-off
flag, shutdown leaving no worker process and no shared-memory segment, and the same cleanup when the
process exits without calling close().

Pool workers start with spawn and re-import this file as __mp_main__, so every test that starts a
pool runs from run_all() behind the __main__ guard.
"""

import dataclasses
import math
import multiprocessing
import os
import random
import subprocess
import sys
import tempfile
from multiprocessing import shared_memory
from types import SimpleNamespace

import config
import enemy as E
import enemy_steer as ES
import parallel
from enemy import Enemy
from enemy_steer import Snapshot, SteerBatch, steer_chunk
from utils import Vec2

ROOT = os.path.dirname(os.path.abspath(__file__))
DT = 1.0 / 60.0
KEYS = ["chaser", "ranged", "swarm", "charger", "tank", "spitter", "flyer", "engineer", "bomber"]
ROLES = list(ES.ROLE_NAMES)


def random_batch(rng, n, dt=None, scale=300.0):
    """A batch of ``n`` random snapshots. Includes names the game uses rarely (chase, egg_sac, empty)."""
    snaps = []
    names = KEYS + ["chase", "egg_sac", ""]
    for _ in range(n):
        snaps.append(
            Snapshot(
                x=rng.uniform(-scale, scale),
                y=rng.uniform(-scale, scale),
                vx=rng.uniform(-150.0, 150.0),
                vy=rng.uniform(-150.0, 150.0),
                key=rng.choice(names),
                speed=rng.uniform(40.0, 140.0),
                seed=rng.uniform(0.0, math.tau),
                lock_t=rng.choice([0.0, rng.uniform(0.0, 0.35)]),
                tx=rng.uniform(-scale, scale),
                ty=rng.uniform(-scale, scale),
                role=rng.choice(ROLES),
                steer=rng.random() < 0.8,
            )
        )
    return SteerBatch(
        snaps=tuple(snaps),
        px=rng.uniform(-200.0, 200.0),
        py=rng.uniform(-200.0, 200.0),
        dt=dt if dt is not None else rng.choice([DT, 0.03, 0.0]),
        pressure_mult=rng.uniform(0.9, 1.3),
        steer_mult=rng.uniform(0.8, 1.2),
    )


def _crowd(seed, n):
    """A seeded crowd of live enemies plus one egg sac (never steered), with pinned formation biases."""
    rng = random.Random(seed)
    st = SimpleNamespace(enemies=[], time=0.0, difficulty="normal", rng=rng, wave=15)
    for i in range(n):
        a = rng.uniform(0.0, math.tau)
        r = 480.0 * math.sqrt(rng.random())
        e = Enemy(
            pos=Vec2(r * math.cos(a), r * math.sin(a)),
            hp=20,
            speed=rng.uniform(60.0, 130.0),
            behavior=KEYS[i % len(KEYS)],
            seed=rng.uniform(0.0, math.tau),
        )
        e.vel = Vec2(rng.uniform(-90.0, 90.0), rng.uniform(-90.0, 90.0))
        # The formation bias is keyed on id(enemy), which differs between runs. Pin it.
        e.ai["formation_bias"] = ((i * 7919) % 997) / 997.0
        st.enemies.append(e)
    # An egg sac has the default "front" role, so it takes part in the arc ordering too. Pin it as well,
    # or its bias falls back to id(enemy) and the front group's slots change between runs.
    egg = Enemy(pos=Vec2(40.0, -30.0), hp=30, speed=0.0, behavior="egg_sac")
    egg.ai["formation_bias"] = 0.5
    st.enemies.append(egg)
    return st


def _player(frame):
    t = frame * DT
    w = 0.6
    pos = Vec2(140.0 * math.cos(w * t), 140.0 * math.sin(w * t))
    vel = Vec2(-140.0 * w * math.sin(w * t), 140.0 * w * math.cos(w * t))
    return pos, vel


def _seeded_run(seed, frames, workers, inline=False):
    """Per-frame steering results and the final unit state of one seeded run of batched steering."""
    st = _crowd(seed, 30)
    batcher = None if inline else parallel.SteerBatcher(workers=workers)
    history = []
    try:
        for f in range(frames):
            st.time = f * DT
            pp, pv = _player(f)
            steered = {id(e) for e in st.enemies}
            batch, owners = E.steer_snapshot(st, pp, pv, DT, steered)
            if batcher is None:
                res = steer_chunk(batch, 0, len(batch.snaps))
            else:
                res = batcher.steer(batch)
            parallel.apply_steering(owners, res)
            history.append(tuple(res))
            for e in st.enemies:
                e.pos = e.pos + e.vel * DT
    finally:
        if batcher is not None:
            batcher.close()
    final = [(e.pos.x, e.pos.y, e.vel.x, e.vel.y, float(e.ai.get("forward_lock_t", 0.0))) for e in st.enemies]
    return history, final


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", "PID eq %d" % pid, "/NH"], capture_output=True, text=True, timeout=60
        ).stdout
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[1] == str(pid):
                return True
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _segment_gone(name: str) -> bool:
    try:
        seg = shared_memory.SharedMemory(name=name)
    except FileNotFoundError:
        return True
    seg.close()
    return False


def _packed_results(batch, ranges):
    """Run the worker kernel over ``ranges`` on a packed copy of ``batch``, the way one pool frame does."""
    cap = max(1, len(batch.snaps))
    inp = memoryview(bytearray(8 * (ES.HEADER + cap * ES.FIELDS))).cast("d")
    out = memoryview(bytearray(8 * cap * ES.OUT_FIELDS)).cast("d")
    ES.pack_batch(batch, inp)
    res = []
    for a, b in ranges:
        ES.steer_packed(inp, out, a, b)
        res.extend(ES.unpack_results(out, a, b))
    return res


def test_packed_kernel_matches_steer_chunk():
    """The worker kernel returns exactly the floats steer_chunk returns, for any split into chunks."""
    rng = random.Random(3)
    steered = 0
    for trial in range(120):
        n = rng.randint(1, 40)
        batch = random_batch(rng, n, scale=rng.choice([120.0, 400.0]))
        ref = steer_chunk(batch, 0, n)
        got = _packed_results(batch, parallel.chunk_ranges(n, rng.randint(1, 5)))
        assert got == ref, "trial %d differs" % trial
        steered += sum(1 for r in ref if r is not None)
    assert steered > 800, steered
    print("[PASS] test_packed_kernel_matches_steer_chunk passed (120 random batches, %d steered units, exact)" % steered)


def test_pack_rejects_a_batch_that_does_not_fit():
    rng = random.Random(6)
    inp = memoryview(bytearray(8 * (ES.HEADER + 3 * ES.FIELDS))).cast("d")
    try:
        ES.pack_batch(random_batch(rng, 5, dt=DT), inp)
    except ValueError:
        pass
    else:
        raise AssertionError("pack_batch must refuse a batch larger than the array")
    print("[PASS] test_pack_rejects_a_batch_that_does_not_fit passed")


def test_pool_frames_match_inline_across_sizes():
    """Pooled frames equal inline frames for changing batch sizes, including an empty frame and a reused batch."""
    rng = random.Random(21)
    b = parallel.SteerBatcher(workers=3)
    try:
        for n in (3, 40, 1, 17, 0, 40):
            batch = random_batch(rng, n, dt=DT, scale=260.0)
            assert b.steer(batch) == steer_chunk(batch, 0, n), "size %d differs" % n
        again = random_batch(rng, 25, dt=DT)
        first = b.steer(again)
        assert first == steer_chunk(again, 0, 25)
        assert b.steer(again) == first
        assert b.fallbacks == 0, b.fallbacks
        assert b.frames == 8, b.frames  # six sizes, then the reused batch twice
    finally:
        b.close()
    print("[PASS] test_pool_frames_match_inline_across_sizes passed (sizes 3, 40, 1, 17, 0, 40, reused batch)")


def test_two_seeded_pooled_runs_repeat_exactly():
    """Batched steering with the pool repeats exactly across two runs, and equals the inline run."""
    first, first_final = _seeded_run(seed=41, frames=60, workers=3)
    second, second_final = _seeded_run(seed=41, frames=60, workers=3)
    assert first == second, "two pooled runs with the same seed differ"
    assert first_final == second_final, "final unit state differs between two pooled runs"
    inline, inline_final = _seeded_run(seed=41, frames=60, workers=0, inline=True)
    assert first == inline, "pooled run differs from its inline reference"
    assert first_final == inline_final
    steered = sum(1 for frame in first for r in frame if r is not None)
    assert steered > 1500, steered
    other, _ = _seeded_run(seed=42, frames=60, workers=3)
    assert other != first, "a different seed should change the run"
    print("[PASS] test_two_seeded_pooled_runs_repeat_exactly passed (60 frames, 30 units, %d steered results, repeat exact)" % steered)


def test_unpackable_and_oversized_batches_run_inline():
    rng = random.Random(4)
    b = parallel.SteerBatcher(workers=2, capacity=16)
    try:
        base = random_batch(rng, 6, dt=DT)
        odd = dataclasses.replace(base, snaps=(dataclasses.replace(base.snaps[0], key="mystery"),) + base.snaps[1:])
        assert b.steer(odd) == steer_chunk(odd, 0, 6)
        assert b.fallbacks == 1 and b._pool is None, (b.fallbacks, b._pool)

        big = random_batch(rng, 20, dt=DT)
        assert b.steer(big) == steer_chunk(big, 0, 20)
        assert b.fallbacks == 2 and b._pool is None

        small = random_batch(rng, 10, dt=DT)
        assert b.steer(small) == steer_chunk(small, 0, 10)
        assert b._pool is not None and b.fallbacks == 2
    finally:
        b.close()
    print("[PASS] test_unpackable_and_oversized_batches_run_inline passed (unknown name and over-capacity run inline, counted)")


def test_warm_starts_workers_without_changing_results():
    rng = random.Random(15)
    b = parallel.SteerBatcher(workers=2)
    try:
        b.warm()
        assert b._pool is not None and len(b._pool._procs) == 2
        assert all(p.is_alive() for p in b._pool._procs)
        batch = random_batch(rng, 15, dt=DT)
        assert b.steer(batch) == steer_chunk(batch, 0, 15)
        b.warm()  # no-op once started
        assert len(b._pool._procs) == 2
    finally:
        b.close()
    print("[PASS] test_warm_starts_workers_without_changing_results passed")


def test_dead_worker_falls_back_and_releases_everything():
    """A worker that dies mid-run finishes the frame inline, and the pool and its segments are released."""
    rng = random.Random(8)
    b = parallel.SteerBatcher(workers=2)
    batch = random_batch(rng, 18, dt=DT)
    assert b.steer(batch) == steer_chunk(batch, 0, 18)
    pool = b._pool
    procs = list(pool._procs)
    names = [pool._in_shm.name, pool._out_shm.name]
    victim = procs[1]
    victim.kill()
    victim.join(timeout=10)
    assert not victim.is_alive()
    batch2 = random_batch(rng, 18, dt=DT)
    assert b.steer(batch2) == steer_chunk(batch2, 0, 18), "the frame with a dead worker must still match inline"
    assert b.workers == 0 and b._pool is None
    assert not any(p.is_alive() for p in procs)
    assert all(_segment_gone(n) for n in names), "segments survived the failed pool"
    batch3 = random_batch(rng, 12, dt=DT)
    assert b.steer(batch3) == steer_chunk(batch3, 0, 12)
    b.close()
    print("[PASS] test_dead_worker_falls_back_and_releases_everything passed (frame finished inline, pool released)")


def test_default_is_off_and_threshold_is_measured():
    # The batch path ships off (config.py: quiet bench, no clear win). The threshold is still the measured
    # crossover. The pool itself starts lazily, so asking for the batcher starts no worker.
    assert config.PARALLEL_STEER_ENABLED is False, "the batch path ships off until a quiet bench shows a win"
    assert config.PARALLEL_MIN_ENEMIES == 16 == config.PARALLEL_STEER_MIN_ENEMIES
    parallel.set_batcher(None)
    assert parallel.active_batcher() is None, "with the flag off the game must not get a batcher"
    config.PARALLEL_STEER_ENABLED = True
    try:
        parallel.set_batcher(None)
        assert parallel.active_batcher() is not None, "with the flag on the batcher is created lazily"
    finally:
        config.PARALLEL_STEER_ENABLED = False
        parallel.close_batcher()
    print("[PASS] test_default_is_off_and_threshold_is_measured passed (flag off, threshold 16, batcher on demand)")


def test_shutdown_leaves_no_worker_or_segment():
    """close() stops every worker process and unlinks both shared-memory segments."""
    rng = random.Random(9)
    b = parallel.SteerBatcher(workers=3)
    batch = random_batch(rng, 24, dt=DT)
    assert b.steer(batch) == steer_chunk(batch, 0, 24)
    pool = b._pool
    procs = list(pool._procs)
    pids = [p.pid for p in procs]
    names = [pool._in_shm.name, pool._out_shm.name]
    assert len(procs) == 3 and all(p.is_alive() for p in procs)
    assert all(_pid_alive(pid) for pid in pids)
    b.close()
    b.close()  # safe to repeat
    assert b._pool is None
    for p in procs:
        assert not p.is_alive(), "worker %d still running after close" % p.pid
        assert p.exitcode == 0, "worker %d did not exit cleanly (exit %r)" % (p.pid, p.exitcode)
    assert not any(_pid_alive(pid) for pid in pids), "a worker process survived close"
    live = {c.pid for c in multiprocessing.active_children()}
    assert not (live & set(pids)), "multiprocessing still lists a closed worker"
    assert all(_segment_gone(n) for n in names), "a shared-memory segment survived close"
    print("[PASS] test_shutdown_leaves_no_worker_or_segment passed (3 workers exited cleanly, 2 segments unlinked)")


def test_close_batcher_releases_pool():
    """The window-close hook (parallel.close_batcher) releases a running pool."""
    rng = random.Random(10)
    b = parallel.SteerBatcher(workers=2)
    parallel.set_batcher(b)
    try:
        batch = random_batch(rng, 10, dt=DT)
        assert b.steer(batch) == steer_chunk(batch, 0, 10)
        pool = b._pool
        names = [pool._in_shm.name, pool._out_shm.name]
        procs = list(pool._procs)
        parallel.close_batcher()
    finally:
        parallel.set_batcher(None)
    assert b._pool is None and not any(p.is_alive() for p in procs)
    assert all(_segment_gone(n) for n in names)
    print("[PASS] test_close_batcher_releases_pool passed")


_EXIT_SCRIPT = '''import sys
sys.path.insert(0, {root!r})
import random


def main():
    import parallel
    from test_w4_steer import random_batch
    b = parallel.SteerBatcher(workers=2)
    batch = random_batch(random.Random(2), 12, dt=1.0 / 60.0)
    b.steer(batch)
    pool = b._pool
    print("PIDS " + " ".join(str(p.pid) for p in pool._procs))
    print("SEGS " + pool._in_shm.name + " " + pool._out_shm.name)
    # No close(): the atexit hook must stop the workers and unlink the segments.


if __name__ == "__main__":
    main()
'''


def test_pool_stopped_at_exit_without_close():
    """A process that exits without closing its batcher leaves no worker process and no segment."""
    fd, path = tempfile.mkstemp(suffix=".py", prefix="w4_exit_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(_EXIT_SCRIPT.format(root=ROOT))
    try:
        res = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=240, cwd=ROOT)
    finally:
        os.remove(path)
    assert res.returncode == 0, res.stderr[-2000:]
    pids, segs = [], []
    for line in res.stdout.splitlines():
        if line.startswith("PIDS "):
            pids = [int(x) for x in line.split()[1:]]
        elif line.startswith("SEGS "):
            segs = line.split()[1:]
    assert len(pids) == 2 and len(segs) == 2, res.stdout
    assert not any(_pid_alive(pid) for pid in pids), "a worker outlived the process"
    assert all(_segment_gone(n) for n in segs), "a segment outlived the process"
    print("[PASS] test_pool_stopped_at_exit_without_close passed (2 workers and 2 segments gone after exit)")


def run_all():
    test_packed_kernel_matches_steer_chunk()
    test_pack_rejects_a_batch_that_does_not_fit()
    test_pool_frames_match_inline_across_sizes()
    test_two_seeded_pooled_runs_repeat_exactly()
    test_unpackable_and_oversized_batches_run_inline()
    test_warm_starts_workers_without_changing_results()
    test_dead_worker_falls_back_and_releases_everything()
    test_default_is_off_and_threshold_is_measured()
    test_shutdown_leaves_no_worker_or_segment()
    test_close_batcher_releases_pool()
    test_pool_stopped_at_exit_without_close()
    leftover = multiprocessing.active_children()
    assert not leftover, "worker processes left after the run: %r" % (leftover,)
    print("\nALL W4 STEER TESTS PASSED (no worker processes left)")


if __name__ == "__main__":
    run_all()
