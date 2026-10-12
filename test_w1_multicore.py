"""Regression tests for the multicore job layer (wave 1, item "multicore").

Covers: the steering kernel against the live serial coordination path, serial against pooled
steering on the same snapshots, pool determinism on live game frames, threshold gating and the
default-off setting, the coordinate flag on update_enemy, the threaded loader, and byte identity of
--jobs output in the synth tools.

Pool workers are started with spawn, which re-imports this file as __mp_main__. Every entry point
that starts a pool therefore stays behind the __main__ guard at the bottom.
"""

import hashlib
import math
import os
import random
import subprocess
import sys
import tempfile
from types import SimpleNamespace

import config
import enemy as E
import parallel
from enemy import Enemy
from enemy_steer import steer_chunk
from utils import Vec2

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable
KEYS = ["chaser", "ranged", "swarm", "charger", "tank", "spitter", "flyer", "engineer", "bomber"]
DT = 1.0 / 60.0


def make_crowd(rng, n, difficulty="normal", t=0.0):
    """A seeded crowd: mixed behaviours, some holding a telegraph, one egg sac and one boss."""
    st = SimpleNamespace(enemies=[], time=t, difficulty=difficulty, rng=rng, wave=12)
    for i in range(n):
        key = rng.choice(KEYS)
        a = rng.uniform(0.0, math.tau)
        r = 700.0 * math.sqrt(rng.random())
        e = Enemy(pos=Vec2(r * math.cos(a), r * math.sin(a)), hp=20, speed=rng.uniform(50.0, 140.0),
                  behavior=key, seed=rng.uniform(0.0, math.tau))
        e.vel = Vec2(rng.uniform(-150.0, 150.0), rng.uniform(-150.0, 150.0))
        e.ai["forward_lock_t"] = rng.choice([0.0, rng.uniform(0.0, 0.35)])
        roll = rng.random()
        if key in ("charger", "flyer") and roll < 0.2:
            e.ai["state"] = "WINDUP"
        elif key == "chaser" and roll < 0.2:
            e.ai["lunge_windup"] = 0.1
        st.enemies.append(e)
    st.enemies.append(Enemy(pos=Vec2(40.0, -30.0), hp=30, speed=0.0, behavior="egg_sac"))
    st.enemies.append(Enemy(pos=Vec2(-200.0, 120.0), hp=500, speed=40.0, behavior="boss_brute"))
    return st


def _steerable(e):
    """True when the game coordinates this unit: a non-boss str behaviour with an impl, not holding."""
    key = E._behavior_key(e)
    if key.startswith("boss_") or not isinstance(e.behavior, str) or e.behavior not in E._BEHAVIOR_IMPLS:
        return False
    return not E._holding_telegraph(e, key)


def _save(enemies):
    return [(e.vel.x, e.vel.y, dict(e.ai)) for e in enemies]


def _restore(enemies, saved):
    for e, (vx, vy, ai) in zip(enemies, saved):
        e.vel = Vec2(vx, vy)
        e.ai.clear()
        e.ai.update(ai)


def test_kernel_matches_serial_coordination():
    """The batch kernel gives the same velocity and forward lock as the live serial path, bit for bit."""
    rng = random.Random(7)
    units = 0
    for trial in range(40):
        st = make_crowd(rng, rng.randint(2, 26), rng.choice(["easy", "normal", "hard"]), trial * 0.31)
        enemies = st.enemies
        pp = Vec2(rng.uniform(-300.0, 300.0), rng.uniform(-300.0, 300.0))
        pv = Vec2(rng.uniform(-300.0, 300.0), rng.uniform(-300.0, 300.0))
        dt = rng.choice([DT, 0.03])
        saved = _save(enemies)

        st.__dict__.pop("_role_formation", None)
        batch, owners = E.steer_snapshot(st, pp, pv, dt, {id(e) for e in enemies})
        kernel = {id(o): r for o, r in zip(owners, steer_chunk(batch, 0, len(batch.snaps)))}
        _restore(enemies, saved)

        st.__dict__.pop("_role_formation", None)
        serial = {}
        for e in enemies:
            E._apply_type_coordination(e, pp, st, dt, pv)
            serial[id(e)] = (e.vel.x, e.vel.y, float(e.ai.get("forward_lock_t", 0.0)))
        _restore(enemies, saved)

        for e in enemies:
            if _steerable(e):
                units += 1
                assert kernel.get(id(e)) == serial[id(e)], f"trial {trial}: {e.behavior} differs"
            else:
                assert kernel.get(id(e)) is None, f"trial {trial}: {e.behavior} should not be steered"
    assert units > 300, units
    print(f"[PASS] test_kernel_matches_serial_coordination passed ({units} steered units, exact)")


def test_chunking_and_pool_match_inline_on_snapshots():
    """Serial and process-pool steering return exactly the same list for the same snapshots."""
    rng = random.Random(11)
    st = make_crowd(rng, 40, "hard", 2.5)
    pp = Vec2(35.0, -60.0)
    pv = Vec2(90.0, 45.0)
    batch, _owners = E.steer_snapshot(st, pp, pv, DT, {id(e) for e in st.enemies})
    n = len(batch.snaps)
    inline = steer_chunk(batch, 0, n)
    assert sum(1 for r in inline if r is not None) > 20
    split = []
    for a, b in parallel.chunk_ranges(n, 5):
        split.extend(steer_chunk(batch, a, b))
    assert split == inline, "chunked serial run differs from one-shot run"

    pool = parallel.SteerBatcher(workers=3)
    try:
        pooled = pool.steer(batch)
        assert pooled == inline, "pooled steering differs from serial steering"
        # Same pool, next frame with moved units and a different player position.
        st2 = make_crowd(random.Random(12), 40, "hard", 2.5 + DT)
        batch2, _ = E.steer_snapshot(st2, Vec2(-80.0, 20.0), Vec2(-30.0, 60.0), DT, {id(e) for e in st2.enemies})
        assert pool.steer(batch2) == steer_chunk(batch2, 0, len(batch2.snaps))
        assert pool.frames == 2
    finally:
        pool.close()
    assert pool._pool is None
    pool.close()  # idempotent
    print(f"[PASS] test_chunking_and_pool_match_inline_on_snapshots passed ({n} snapshots, 3 workers, exact)")


def test_pool_failure_falls_back_to_inline():
    """If the pool cannot run a frame, that frame is steered inline and the batcher stays serial."""

    class DeadPool:
        def submit(self, *args, **kwargs):
            raise OSError("worker could not start")

        def shutdown(self, **kwargs):
            pass

    st = make_crowd(random.Random(5), 20)
    batch, _ = E.steer_snapshot(st, Vec2(20.0, -10.0), Vec2(5.0, 5.0), DT, {id(e) for e in st.enemies})
    b = parallel.SteerBatcher(workers=2)
    b._pool = DeadPool()
    out = b.steer(batch)
    assert out == steer_chunk(batch, 0, len(batch.snaps))
    assert b.workers == 0 and b._pool is None
    assert b.steer(batch) == out
    print("[PASS] test_pool_failure_falls_back_to_inline passed (frame finished inline, pool disabled)")


def test_chunk_ranges_cover_in_order():
    assert parallel.chunk_ranges(0, 3) == [(0, 0)]
    assert parallel.chunk_ranges(5, 8) == [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5)]
    assert parallel.chunk_ranges(10, 3) == [(0, 4), (4, 7), (7, 10)]
    rng = random.Random(3)
    for _ in range(200):
        n = rng.randint(1, 90)
        parts = rng.randint(1, 9)
        ranges = parallel.chunk_ranges(n, parts)
        assert ranges[0][0] == 0 and ranges[-1][1] == n
        assert all(ranges[i][1] == ranges[i + 1][0] for i in range(len(ranges) - 1))
        sizes = [b - a for a, b in ranges]
        assert max(sizes) - min(sizes) <= 1 and len(ranges) <= parts
    print("[PASS] test_chunk_ranges_cover_in_order passed (contiguous, near-equal, ordered)")


def _start_run(g, seed, enemy_count):
    """Start a fresh playing run with a seeded RNG and a crowd kept clear of the player."""
    from states import GameStateName  # imported here: spawned pool workers re-import this file

    random.seed(seed)
    g._init_game()
    g.state.init_rng(seed)
    g.fsm.set_state(GameStateName.PLAYING)
    s = g.state
    place = random.Random(seed)
    s.enemies = []
    behaviors = KEYS + ["egg_sac"]
    for i in range(enemy_count):
        a = place.uniform(0.0, math.tau)
        r = place.uniform(420.0, 560.0)
        key = behaviors[i % len(behaviors)]
        e = Enemy(pos=Vec2(r * math.cos(a), r * math.sin(a)), hp=18, speed=place.uniform(60.0, 120.0),
                  behavior=key, seed=place.uniform(0.0, math.tau))
        s.enemies.append(e)
    return s


def _play(g, frames):
    for _ in range(frames):
        g.player.invincibility_timer = 1e9
        g.dispatch_events()
        g.update(DT)


def test_pool_frames_match_inline_on_live_game(g):
    """On live game frames, every pooled steering result equals the inline reference (verify=True)."""
    s = _start_run(g, 2024, 36)
    start = [(e.pos.x, e.pos.y) for e in s.enemies]
    checker = parallel.SteerBatcher(workers=2, min_enemies=0, verify=True)
    parallel.set_batcher(checker)
    try:
        _play(g, 120)
    finally:
        parallel.set_batcher(None)
        checker.close()
    assert checker.frames >= 60, checker.frames
    assert checker.mismatches == 0, checker.mismatches
    moved = sum(1 for e, p in zip(s.enemies, start) if (e.pos.x, e.pos.y) != p)
    assert moved > 20, moved
    print(f"[PASS] test_pool_frames_match_inline_on_live_game passed ({checker.frames} pooled frames, 0 mismatches)")


def test_inline_batch_runs_the_game_without_a_pool(g):
    """The batch path with workers=0 runs real frames and never starts a pool."""
    s = _start_run(g, 99, 34)
    b = parallel.SteerBatcher(workers=0, min_enemies=0)
    parallel.set_batcher(b)
    try:
        _play(g, 60)
    finally:
        parallel.set_batcher(None)
    assert b.frames >= 40 and b._pool is None
    assert all(math.isfinite(e.pos.x) and math.isfinite(e.pos.y) for e in s.enemies)
    print("[PASS] test_inline_batch_runs_the_game_without_a_pool passed")


def test_default_is_off_and_serial_path_is_used(g):
    """With the shipped config the batch hook does nothing, so the default loop runs unchanged."""
    assert config.PARALLEL_STEER_ENABLED is False
    parallel.set_batcher(None)
    assert parallel.active_batcher() is None
    s = _start_run(g, 5, 40)
    assert parallel.maybe_update_enemies(s, g, DT, g.player.pos, Vec2(0.0, 0.0)) is None
    print("[PASS] test_default_is_off_and_serial_path_is_used passed (shipped config keeps the serial path)")


def test_threshold_gates_batch_path(g):
    """Below the live-count threshold the default path runs; at or above it the batch path runs."""
    b = parallel.SteerBatcher(workers=0, min_enemies=32)
    assert not b.wants(31) and b.wants(32) and b.wants(60)

    saved = (config.PARALLEL_STEER_ENABLED, config.PARALLEL_STEER_MIN_ENEMIES, config.PARALLEL_STEER_WORKERS)
    config.PARALLEL_STEER_ENABLED = True
    config.PARALLEL_STEER_MIN_ENEMIES = 32
    config.PARALLEL_STEER_WORKERS = 0
    parallel.set_batcher(None)
    parallel._configured = None
    try:
        assert parallel.active_batcher().min_enemies == 32
        s = _start_run(g, 17, 31)
        assert parallel.maybe_update_enemies(s, g, DT, g.player.pos, Vec2(0.0, 0.0)) is None
        s = _start_run(g, 17, 32)
        live_ids = {id(e) for e in s.enemies if e.hp > 0}
        done = parallel.maybe_update_enemies(s, g, DT, g.player.pos, Vec2(0.0, 0.0))
        assert done == live_ids and len(done) == 32
        # Dead enemies do not count toward the threshold.
        s = _start_run(g, 17, 33)
        for e in s.enemies[:3]:
            e.hp = 0
        assert parallel.maybe_update_enemies(s, g, DT, g.player.pos, Vec2(0.0, 0.0)) is None
    finally:
        config.PARALLEL_STEER_ENABLED, config.PARALLEL_STEER_MIN_ENEMIES, config.PARALLEL_STEER_WORKERS = saved
        parallel._configured = None
    print("[PASS] test_threshold_gates_batch_path passed (31 serial, 32 batched, dead units not counted)")


def test_coordinate_flag_controls_steering_pass(g):
    """update_enemy(coordinate=False) skips the formation pass; the default still runs it."""
    s = _start_run(g, 21, 0)
    e = Enemy(pos=Vec2(200.0, 40.0), hp=20, speed=90.0, behavior="chaser", seed=1.0)
    s.enemies.append(e)
    calls = []
    original = E._apply_type_coordination

    def spy(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    E._apply_type_coordination = spy
    try:
        random.seed(4)
        E.update_enemy(e, g.player.pos, s, DT, g, player_vel=Vec2(0.0, 0.0), coordinate=False)
        assert calls == []
        random.seed(4)
        E.update_enemy(e, g.player.pos, s, DT, g, player_vel=Vec2(0.0, 0.0))
        assert calls == [1]
    finally:
        E._apply_type_coordination = original
    print("[PASS] test_coordinate_flag_controls_steering_pass passed")


def test_threaded_loader_order_and_missing_files():
    """Threaded reads return contents in input order; a missing file gives None instead of raising."""
    with tempfile.TemporaryDirectory() as tmp:
        paths, contents = [], []
        for i in range(6):
            p = os.path.join(tmp, f"asset_{i}.bin")
            data = bytes([i]) * (1000 + 37 * i)
            with open(p, "wb") as fh:
                fh.write(data)
            paths.append(p)
            contents.append(data)
        missing = os.path.join(tmp, "nope.bin")
        for workers in (4, 1):
            loader = parallel.ThreadedLoader(workers=workers)
            try:
                got = loader.read_bytes(paths + [missing])
            finally:
                loader.close()
            assert got[:6] == contents and got[6] is None, workers
        loader = parallel.ThreadedLoader(workers=4)
        try:
            assert loader.map(lambda x: x * 2, range(25)) == [x * 2 for x in range(25)]
        finally:
            loader.close()
    print("[PASS] test_threaded_loader_order_and_missing_files passed")


def _sha_tree(folder):
    out = {}
    for name in sorted(os.listdir(folder)):
        if name.endswith(".wav"):
            with open(os.path.join(folder, name), "rb") as fh:
                out[name] = hashlib.sha256(fh.read()).hexdigest()
    return out


def _run_tool(script, jobs, out_dir):
    subprocess.run([PY, os.path.join(ROOT, "tools", script), "--jobs", str(jobs), "--out-dir", out_dir],
                   check=True, capture_output=True, text=True, cwd=ROOT)
    return _sha_tree(out_dir)


def test_synth_jobs_are_byte_identical():
    """--jobs N writes WAVs whose SHA-256 matches the serial run, for both synth tools."""
    with tempfile.TemporaryDirectory() as tmp:
        sfx_serial = _run_tool("synth_sfx.py", 1, os.path.join(tmp, "sfx1"))
        sfx_par = _run_tool("synth_sfx.py", 4, os.path.join(tmp, "sfx4"))
        assert len(sfx_serial) >= 30 and sfx_serial == sfx_par, "sfx --jobs 4 differs from serial"
        mus_serial = _run_tool("synth_music.py", 1, os.path.join(tmp, "mus1"))
        mus_par = _run_tool("synth_music.py", 2, os.path.join(tmp, "mus2"))
        assert len(mus_serial) == 2 and mus_serial == mus_par, "music --jobs 2 differs from serial"
    print(f"[PASS] test_synth_jobs_are_byte_identical passed ({len(sfx_serial)} sfx + {len(mus_serial)} music WAVs match)")


def run_all():
    from game import Game  # imported here: spawned pool workers re-import this file

    g = Game()
    g.set_visible(False)
    try:
        test_kernel_matches_serial_coordination()
        test_chunk_ranges_cover_in_order()
        test_pool_failure_falls_back_to_inline()
        test_chunking_and_pool_match_inline_on_snapshots()
        test_default_is_off_and_serial_path_is_used(g)
        test_threshold_gates_batch_path(g)
        test_coordinate_flag_controls_steering_pass(g)
        test_inline_batch_runs_the_game_without_a_pool(g)
        test_pool_frames_match_inline_on_live_game(g)
        test_threaded_loader_order_and_missing_files()
        test_synth_jobs_are_byte_identical()
    finally:
        parallel.set_batcher(None)
        g.close()
    print("\nALL W1 MULTICORE TESTS PASSED")


if __name__ == "__main__":
    run_all()
