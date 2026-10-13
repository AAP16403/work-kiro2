"""Wave 8 multicore-frame tests: the fixed path of the frame-cost work, and the keep-alive steering pool.

Covers the two changes behind config.ENABLE_MULTICORE_FRAME:

    - enemy_behaviors.base.separation_steer, the one inverse-square separation that bomber, chase,
      engineer, ranged, spitter and tank now share. It must match separation_reference bit for bit.
    - enemy._update_kwarg_flags, which reads each behaviour's optional keywords once per function
      instead of calling inspect.signature for every unit on every step.

Plus the whole-step checks the acceptance rests on: with the switch on or off, serial and inline runs
hash the same; the pooled run ends in the same state as the inline run; the pool stays up across runs.

Plain functions that print [PASS] lines, run from run_all(). Run with the project venv:

    .venv\\Scripts\\python.exe test_w8_multicore-frame.py

Measured with tools/bench_frame_pool.py (keep-alive, 150 timed steps after 20 warm-up, player HP refilled,
seed 20261013, serial = batch steering off, pooled = 3 workers). The machine was shared with other agents,
so these are indicative, not a quiet-machine result. Ratios are only comparable inside one run.
  40 enemies, switch on, 3 repeats: serial step 22.4 ms (19.3 to 26.3), pooled 11.8 (10.6 to 12.8),
      pooled/serial per repeat 0.55, 0.57, 0.45.
  64 enemies, switch on, 3 repeats: serial step 33.3 ms (32.9 to 55.1), pooled 18.3 (16.6 to 19.6),
      pooled/serial per repeat 0.55, 0.36, 0.50.
  Switch off (the reference code), one run each in the same window: 40 enemies serial 19.8 / pooled 13.9
      (0.70); 64 enemies serial 51.3 / pooled 28.1 (0.55).
With the switch on, the 40-enemy hashes equal those of the switch-off reference, which matched main at 40
enemies; the 64-enemy inline hash equals the switch-off reference too. Inline equals pooled at 40 and 64
enemies over the full protocol. The switch changes speed only.
"""

import builtins
import inspect
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tools"))

import config  # noqa: E402
import enemy as E  # noqa: E402
import parallel  # noqa: E402
import progress  # noqa: E402
import score  # noqa: E402
from enemy import Enemy  # noqa: E402
from enemy_behaviors import base as behavior_base  # noqa: E402
from utils import Vec2  # noqa: E402

import bench_frame_pool as BFP  # noqa: E402


def _random_crowd(rng: random.Random, n: int, spread: float):
    """Enemies in a seeded cloud, with some coincident pairs and some pairs at exact radius distance."""
    units = []
    for i in range(n):
        key = ("chaser", "ranged", "tank", "bomber", "spitter", "engineer")[i % 6]
        pos = Vec2(rng.uniform(-spread, spread), rng.uniform(-spread, spread))
        units.append(Enemy(pos=pos, hp=10, speed=80.0, behavior=key))
    if n >= 4:
        units[1].pos = Vec2(units[0].pos.x, units[0].pos.y)  # d == 0: skipped by both paths
        units[3].pos = Vec2(units[2].pos.x + 44.0, units[2].pos.y)  # d == radius exactly: kept
    return units


def _same_vec(a: Vec2, b: Vec2) -> bool:
    return a.x == b.x and a.y == b.y


class _Switch:
    """Context manager that sets config.ENABLE_MULTICORE_FRAME and restores it."""

    def __init__(self, value: bool):
        self.value = bool(value)
        self.saved = None

    def __enter__(self):
        self.saved = config.ENABLE_MULTICORE_FRAME
        config.ENABLE_MULTICORE_FRAME = self.value
        return self

    def __exit__(self, *exc):
        config.ENABLE_MULTICORE_FRAME = self.saved
        return False


def test_separation_steer_matches_reference_exactly():
    rng = random.Random(8001)
    checked = 0
    for trial in range(60):
        n = 2 + trial % 37
        units = _random_crowd(rng, n, spread=260.0)
        for radius in (30.0, 44.0, 120.0, 260.0):
            for weight in (1.0, 1.1, 0.35):
                for enemy in units[: min(len(units), 12)]:
                    ref = behavior_base.separation_reference(enemy, units, radius, weight)
                    fast = behavior_base.separation_steer(enemy, units, radius, weight)
                    assert _same_vec(ref, fast), "separation differs: %r vs %r (n=%d r=%r w=%r)" % (ref, fast, n, radius, weight)
                    checked += 1
    alone = [Enemy(pos=Vec2(5.0, 5.0), hp=1, speed=1.0, behavior="tank")]
    assert _same_vec(behavior_base.separation_steer(alone[0], alone, 44.0, 1.1), Vec2(0.0, 0.0))
    assert _same_vec(behavior_base.separation_reference(alone[0], alone, 44.0, 1.1), Vec2(0.0, 0.0))
    print("[PASS] test_separation_steer_matches_reference_exactly passed (%d cases, bit-identical, incl. coincident and exact-radius pairs)" % checked)


def test_behaviour_separation_matches_reference_both_switch_positions():
    rng = random.Random(8002)
    units = _random_crowd(rng, 40, spread=240.0)
    names = ("chaser", "ranged", "tank", "bomber", "spitter", "engineer")
    for name in names:
        impl = E._BEHAVIOR_IMPLS[name]
        for radius, weight in ((44.0, 1.1), (44.0, 1.2), (60.0, 1.5)):  # the radii the call sites pass
            for enemy in units[:10]:
                ref = behavior_base.separation_reference(enemy, units, radius, weight)
                for on in (True, False):
                    with _Switch(on):
                        got = impl._separation(enemy, units, radius=radius, weight=weight)
                    assert _same_vec(ref, got), "%s._separation differs with ENABLE_MULTICORE_FRAME=%s" % (name, on)
    print("[PASS] test_behaviour_separation_matches_reference_both_switch_positions passed (6 behaviours, 10 units each, switch on and off)")


def test_switch_off_takes_the_reference_separation():
    calls = {"n": 0}
    real = behavior_base.separation_reference

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    rng = random.Random(8003)
    units = _random_crowd(rng, 12, spread=200.0)
    behavior_base.separation_reference = counting
    try:
        with _Switch(True):
            behavior_base.separation_steer(units[0], units, 44.0, 1.1)
        assert calls["n"] == 0, "switch on must not use the reference path"
        with _Switch(False):
            behavior_base.separation_steer(units[0], units, 44.0, 1.1)
        assert calls["n"] == 1, "switch off must use the reference path"
    finally:
        behavior_base.separation_reference = real
    print("[PASS] test_switch_off_takes_the_reference_separation passed (reference path runs only with the switch off)")


def test_update_kwarg_flags_match_inspect():
    seen = 0
    for name, impl in E._BEHAVIOR_IMPLS.items():
        upd = impl.update
        with _Switch(True):
            got = E._update_kwarg_flags(upd)
        want = E._probe_update_kwargs(upd)
        assert got == want, "%s: cached flags %r differ from inspect %r" % (name, got, want)
        seen += 1
    print("[PASS] test_update_kwarg_flags_match_inspect passed (%d behaviours, cached flags equal inspect)" % seen)


def test_inspect_runs_once_per_updater():
    class Probe:
        def update(self, enemy, player_pos, state, dt, game=None, player_vel=None):
            return None

    impl = Probe()
    real_signature = inspect.signature
    count = {"n": 0}

    def counting_signature(obj, *a, **k):
        count["n"] += 1
        return real_signature(obj, *a, **k)

    E._UPDATE_KWARG_FLAGS.pop(Probe.update, None)
    builtins_inspect = E.inspect
    saved = builtins_inspect.signature
    builtins_inspect.signature = counting_signature
    try:
        with _Switch(True):
            enemy = Enemy(pos=Vec2(0.0, 0.0), hp=1, speed=1.0, behavior="chaser")
            for _ in range(200):
                E._dispatch_behavior_update(impl, enemy, Vec2(1.0, 0.0), object(), 1.0 / 60.0, object(), Vec2(0.0, 0.0))
        assert count["n"] == 1, "inspect.signature ran %d times for 200 dispatches (want 1)" % count["n"]
        count["n"] = 0
        with _Switch(False):
            for _ in range(20):
                E._dispatch_behavior_update(impl, enemy, Vec2(1.0, 0.0), object(), 1.0 / 60.0, object(), Vec2(0.0, 0.0))
        assert count["n"] == 20, "switch off must read the signature on every call (got %d)" % count["n"]
    finally:
        builtins_inspect.signature = saved
        E._UPDATE_KWARG_FLAGS.pop(Probe.update, None)
    print("[PASS] test_inspect_runs_once_per_updater passed (200 dispatches: one signature read, switch off: one per call)")


def test_unhashable_updater_still_dispatches():
    class Unhashable:
        __hash__ = None

        def __call__(self, enemy, player_pos, state, dt, game=None):
            self.got_game = game

        def update(self, enemy, player_pos, state, dt, game=None):
            self.got_game = game

    impl = Unhashable()
    flags = E._update_kwarg_flags(impl)  # the instance itself is the updater: it is unhashable, so no cache key
    assert flags == (True, False), flags
    assert E._update_kwarg_flags(impl.update) == (True, False)  # the bound method takes the cached path
    marker = object()
    enemy = Enemy(pos=Vec2(0.0, 0.0), hp=1, speed=1.0, behavior="chaser")
    with _Switch(True):
        E._dispatch_behavior_update(impl, enemy, Vec2(0.0, 0.0), object(), 1.0 / 60.0, marker, Vec2(0.0, 0.0))
    assert impl.got_game is marker
    print("[PASS] test_unhashable_updater_still_dispatches passed (game keyword passed, no cache key needed)")


def test_dispatch_keywords_reach_the_update():
    got = {}

    class Recorder:
        def update(self, enemy, player_pos, state, dt, player_vel):
            got["vel"] = player_vel

    class Both:
        def update(self, enemy, player_pos, state, dt, game, player_vel):
            got["game"] = game
            got["vel"] = player_vel

    class GameOnly:
        def update(self, enemy, player_pos, state, dt, game=None):
            got["game"] = game

    class Neither:
        def update(self, enemy, player_pos, state, dt):
            got["called"] = True

    enemy = Enemy(pos=Vec2(0.0, 0.0), hp=1, speed=1.0, behavior="chaser")
    vel = Vec2(3.0, -4.0)
    marker = object()
    with _Switch(True):
        E._dispatch_behavior_update(Recorder(), enemy, Vec2(0.0, 0.0), object(), 0.1, marker, vel)
        assert got["vel"] is vel
        E._dispatch_behavior_update(Both(), enemy, Vec2(0.0, 0.0), object(), 0.1, marker, vel)
        assert got["game"] is marker and got["vel"] is vel
        E._dispatch_behavior_update(GameOnly(), enemy, Vec2(0.0, 0.0), object(), 0.1, marker, vel)
        assert got["game"] is marker
        E._dispatch_behavior_update(Neither(), enemy, Vec2(0.0, 0.0), object(), 0.1, marker, vel)
        assert got.get("called") is True
    print("[PASS] test_dispatch_keywords_reach_the_update passed (all four keyword shapes reach the update)")


def _fresh_game():
    from game import Game
    g = Game()
    g.set_visible(False)
    return g


def test_switch_on_and_off_give_the_same_serial_and_inline_runs(g):
    cases = []
    for on in (True, False):
        with _Switch(on):
            BFP.set_mode("serial")
            _, _, _, serial_final, _ = BFP.run_once(g, 40, steps=30, warmup=5, seed=8100)
            BFP.set_mode("inline")
            _, _, _, inline_final, _ = BFP.run_once(g, 40, steps=30, warmup=5, seed=8100)
            cases.append((on, serial_final, inline_final))
    (on_s, on_serial, on_inline), (off_s, off_serial, off_inline) = cases
    assert on_serial == off_serial, "serial run changed with the switch"
    assert on_inline == off_inline, "inline run changed with the switch"
    print("[PASS] test_switch_on_and_off_give_the_same_serial_and_inline_runs passed (40 units, 30 steps, state hashes equal with the switch on and off)")


def test_pooled_final_state_equals_inline(g):
    results = {}
    for count in (40, 64):
        with _Switch(True):
            BFP.set_mode("inline")
            _, _, _, inline_final, _ = BFP.run_once(g, count, steps=40, warmup=5, seed=8200)
            BFP.set_mode("pooled")
            _, _, _, pooled_final, _ = BFP.run_once(g, count, steps=40, warmup=5, seed=8200)
        assert pooled_final == inline_final, "pooled final state differs from inline at %d units" % count
        results[count] = True
    BFP.set_mode("serial")
    print("[PASS] test_pooled_final_state_equals_inline passed (40 and 64 units, 40 steps, pooled hash == inline hash)")


def test_pool_stays_warm_across_runs(g):
    with _Switch(True):
        BFP.set_mode("pooled")
        BFP.run_once(g, 40, steps=10, warmup=5, seed=8300)
        batcher = parallel.active_batcher()
        pool = batcher._pool
        assert pool is not None, "the pooled run must have started the steering pool"
        pids = [p.pid for p in pool._procs]
        names = (pool._in_shm.name, pool._out_shm.name)
        BFP.run_once(g, 40, steps=10, warmup=5, seed=8301)
        assert parallel.active_batcher() is batcher and batcher._pool is pool, "the pool was rebuilt between runs"
        assert [p.pid for p in pool._procs] == pids, "worker processes changed between runs"
        assert (pool._in_shm.name, pool._out_shm.name) == names, "shared arrays changed between runs"
        assert all(p.is_alive() for p in pool._procs), "a steering worker exited"
    BFP.set_mode("serial")
    print("[PASS] test_pool_stays_warm_across_runs passed (same %d workers and shared arrays across runs)" % len(pids))


def test_bench_tool_smoke():
    rc = BFP.main(["--counts", "40", "--steps", "3", "--warmup", "1", "--repeats", "1",
                   "--modes", "serial,inline,pooled", "--phases"])
    assert rc == 0, "tools/bench_frame_pool.py exited %r" % rc
    print("[PASS] test_bench_tool_smoke passed (tools/bench_frame_pool.py runs serial, inline and pooled)")


def run_all():
    tmp = tempfile.mkdtemp(prefix="ploto_w8_frame_")
    score.HIGH_SCORE_FILE = os.path.join(tmp, "high_scores.json")
    progress.PROGRESS_FILE = os.path.join(tmp, "progress.json")
    original_flag = bool(config.PARALLEL_STEER_ENABLED)
    g = _fresh_game()
    try:
        test_separation_steer_matches_reference_exactly()
        test_behaviour_separation_matches_reference_both_switch_positions()
        test_switch_off_takes_the_reference_separation()
        test_update_kwarg_flags_match_inspect()
        test_inspect_runs_once_per_updater()
        test_unhashable_updater_still_dispatches()
        test_dispatch_keywords_reach_the_update()
        test_switch_on_and_off_give_the_same_serial_and_inline_runs(g)
        test_pooled_final_state_equals_inline(g)
        test_pool_stays_warm_across_runs(g)
    finally:
        parallel.set_batcher(None)
        parallel.close_batcher()
        config.PARALLEL_STEER_ENABLED = original_flag
        g.close()
    test_bench_tool_smoke()
    print("\nALL W8 MULTICORE-FRAME TESTS PASSED")


if __name__ == "__main__":
    run_all()
