"""Wave 2 multicorewire tests: forced large-wave bench harness and the parallel steering seam.

Cross-wave checks need wave-1 modules (parallel.py, PARALLEL_MIN_ENEMIES in config.py). While
those are missing from the worktree they print [SKIP requires-wave1] and do not fail.
"""

import contextlib
import builtins
import itertools
import multiprocessing
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if os.path.join(ROOT, "tools") not in sys.path:
    sys.path.insert(0, os.path.join(ROOT, "tools"))

import bench  # noqa: E402
import config  # noqa: E402
import enemy as enemy_mod  # noqa: E402
from game import Game  # noqa: E402


_real_id = builtins.id
_orig_enemy_init = enemy_mod.Enemy.__init__


@contextlib.contextmanager
def pinned_identities():
    """Give Enemy objects creation-order ids while the block runs.

    enemy.py and several behaviours key AI choices on id(enemy), which depends on memory
    addresses, so two identical seeded runs can diverge. Pinning the ids makes one seeded run
    repeatable inside a test. Both patches are reverted on exit.
    """
    counter = itertools.count(1)

    def _init(self, *a, **k):
        _orig_enemy_init(self, *a, **k)
        object.__setattr__(self, "_pinned_uid", next(counter))

    def _pinned_id(o):
        uid = getattr(o, "_pinned_uid", None) if isinstance(o, enemy_mod.Enemy) else None
        return uid if uid is not None else _real_id(o)

    enemy_mod.Enemy.__init__ = _init
    builtins.id = _pinned_id
    try:
        yield
    finally:
        builtins.id = _real_id
        enemy_mod.Enemy.__init__ = _orig_enemy_init


def _skip_requires_wave1(name: str, reason: str) -> None:
    print(f"[SKIP requires-wave1] {name}: {reason}")


def _parallel_module_present() -> bool:
    return importlib.util.find_spec("parallel") is not None


def test_forced_wave_builds_requested_count(g):
    for n in (20, 30):
        s = bench.build_forced_wave(g, n, seed=7)
        assert len(s.enemies) == n, f"forced wave has {len(s.enemies)} enemies, wanted {n}"
    print("[PASS] test_forced_wave_builds_requested_count passed (20 and 30 enemies built exactly)")


def test_forced_wave_mixes_every_regular_behaviour(g):
    s = bench.build_forced_wave(g, 30, seed=7)
    kinds = {e.behavior for e in s.enemies}
    assert kinds == set(bench.FORCED_MIX), f"behaviour mix is {sorted(kinds)}"
    assert not any(str(k).startswith("boss_") for k in kinds), "forced wave must not include bosses"
    print(f"[PASS] test_forced_wave_mixes_every_regular_behaviour passed ({len(kinds)} behaviours, no bosses)")


def test_seeded_serial_run_repeats_with_pinned_identities(g):
    for n in (20, 30):
        with pinned_identities():
            first = bench.run_snapshot(g, n, frames=40, seed=5)
        with pinned_identities():
            second = bench.run_snapshot(g, n, frames=40, seed=5)
        assert len(first) == n, "snapshot must cover every enemy"
        assert first == second, f"same-seed serial run diverged at {n} enemies"
    print("[PASS] test_seeded_serial_run_repeats_with_pinned_identities passed (20 and 30 enemies, 40 frames, exact match)")


def test_different_seed_changes_the_run(g):
    with pinned_identities():
        a = bench.run_snapshot(g, 20, frames=40, seed=5)
    with pinned_identities():
        b = bench.run_snapshot(g, 20, frames=40, seed=6)
    assert a != b, "different seeds produced the same run, so the snapshot cannot detect divergence"
    print("[PASS] test_different_seed_changes_the_run passed (seed 5 and seed 6 differ)")


def test_bench_measure_reports_both_sizes(g):
    for n in (20, 30):
        r = bench.measure(g, n, frames=10, repeats=1)
        assert r["count"] == n and r["frames"] == 10 and r["repeats"] == 1
        assert r["median_ms"] > 0.0 and r["mean_ms"] > 0.0, f"bad timing for {n} enemies: {r}"
    print("[PASS] test_bench_measure_reports_both_sizes passed (20 and 30 enemies timed)")


def test_no_multiprocessing_children_left_after_bench(g):
    bench.measure(g, 20, frames=5, repeats=1)
    leftover = multiprocessing.active_children()
    assert not leftover, f"{len(leftover)} worker process(es) left after the bench run"
    print("[PASS] test_no_multiprocessing_children_left_after_bench passed (0 child processes after bench)")


def test_parallel_threshold_is_a_named_config_value(g):
    if not hasattr(config, "PARALLEL_MIN_ENEMIES"):
        _skip_requires_wave1("test_parallel_threshold_is_a_named_config_value", "config.PARALLEL_MIN_ENEMIES is wave 1's measured value and is not in this worktree")
        return
    value = config.PARALLEL_MIN_ENEMIES
    assert isinstance(value, int) and value >= 1, f"PARALLEL_MIN_ENEMIES must be a positive int, got {value!r}"
    print(f"[PASS] test_parallel_threshold_is_a_named_config_value passed (PARALLEL_MIN_ENEMIES={value})")


def test_parallel_on_matches_parallel_off_final_state(g):
    if not _parallel_module_present():
        _skip_requires_wave1("test_parallel_on_matches_parallel_off_final_state", "parallel.py is not in this worktree")
        return
    _skip_requires_wave1("test_parallel_on_matches_parallel_off_final_state", "the enemy-update hook that selects the batch path is not wired in this worktree")


def test_pool_closed_on_window_close_and_exit(g):
    if not _parallel_module_present():
        _skip_requires_wave1("test_pool_closed_on_window_close_and_exit", "parallel.py WorkerPool is not in this worktree")
        return
    _skip_requires_wave1("test_pool_closed_on_window_close_and_exit", "the game shutdown hook for WorkerPool is not wired in this worktree")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_forced_wave_builds_requested_count(g)
        test_forced_wave_mixes_every_regular_behaviour(g)
        test_seeded_serial_run_repeats_with_pinned_identities(g)
        test_different_seed_changes_the_run(g)
        test_bench_measure_reports_both_sizes(g)
        test_no_multiprocessing_children_left_after_bench(g)
        test_parallel_threshold_is_a_named_config_value(g)
        test_parallel_on_matches_parallel_off_final_state(g)
        test_pool_closed_on_window_close_and_exit(g)
    finally:
        g.close()
    print("\nALL W2 MULTICOREWIRE TESTS PASSED (requires-wave1 checks skipped where noted)")


if __name__ == "__main__":
    run_all()
