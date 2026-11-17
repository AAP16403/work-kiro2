#!/usr/bin/env python3
"""Keep-alive frame bench: one whole game step (fixed step plus on_draw) on a forced wave.

Run from the project root with the project venv:

    .venv\\Scripts\\python.exe tools\\bench_frame_pool.py --counts 40,64 --steps 150 --repeats 3
    .venv\\Scripts\\python.exe tools\\bench_frame_pool.py --counts 40 --profile --out frame_pool.json

Protocol (the same in every mode):

* One Game lives for the whole process (keep-alive), so a steering pool started in one run is still
  warm in the next one. A run is a fresh forced wave of N mixed enemies (bench.build_forced_wave),
  seeded, with identities pinned (test_w2_multicorewire.pinned_identities) so repeats match.
* A run is --warmup untimed steps and then --steps timed steps. A step is: refill the player's HP,
  then Game._fixed_step() (timed), then Game.on_draw() plus glFinish() (timed). Buffer swap is skipped.
* Modes: serial (batch steering off), inline (batch path, no worker processes), pooled (batch path,
  the config-driven pool of PARALLEL_STEER_WORKERS workers). Modes rotate inside each repeat, so
  machine drift does not favour one mode.
* Per run the final enemy and player state is hashed. inline and pooled must hash equal; serial
  differs by design (phase 1 moves every unit before coordination).

--profile adds one cProfile pass per mode (largest count only). --phases adds a per-phase split of the
batch path (phase 1 behaviours, snapshot build, pack, pool round trip, apply) from wall-clock wrappers.

Config flags are only changed at run time, inside this process. The defaults in config.py are not
edited. Save files are redirected to a temporary folder.
"""

import argparse
import builtins
import contextlib
import cProfile
import gc
import hashlib
import itertools
import json
import os
import platform
import pstats
import random
import statistics
import sys
import tempfile
import time
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
TOOLS = os.path.join(ROOT, "tools")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)

from game import Game  # noqa: E402  (game.py sets the pyglet GL options before pyglet.gl loads)
import pyglet  # noqa: E402
from pyglet.gl import glFinish  # noqa: E402

import bench  # noqa: E402  (tools/bench.py: forced wave builder and the snapshot format)
import config  # noqa: E402
import enemy as enemy_mod  # noqa: E402
import parallel  # noqa: E402
import progress  # noqa: E402
import score  # noqa: E402

MODES = ("serial", "inline", "pooled")
DEFAULT_SEED = 20261013
TOP_N = 25


@contextlib.contextmanager
def pinned_identities():
    """Creation-order ids for Enemy objects while the block runs. Same idea as test_w2_multicorewire."""
    _real_id = builtins.id
    _orig_init = enemy_mod.Enemy.__init__
    counter = itertools.count(1)

    def _init(self, *a, **k):
        _orig_init(self, *a, **k)
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
        enemy_mod.Enemy.__init__ = _orig_init


class PhaseClock:
    """Wall-clock totals for the stages of one step, collected through wrappers on module globals.

    Batch mode wraps the names parallel.py looks up at call time. Serial mode wraps the names
    states.py and enemy.py look up at call time. Counts start at reset(), so warm-up frames are left out.
    """

    def __init__(self, mode: str):
        self.mode = mode
        self.total = defaultdict(float)
        self.calls = defaultdict(int)
        self._saved = []

    def _wrap(self, owner, name, label):
        orig = getattr(owner, name)
        clock = self

        def wrapped(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return orig(*args, **kwargs)
            finally:
                clock.total[label] += time.perf_counter() - t0
                clock.calls[label] += 1

        setattr(owner, name, wrapped)
        self._saved.append((owner, name, orig))

    def _wrap_by_behaviour(self, owner, name):
        """Phase 1 timing split by the unit's behaviour name, so the cost of each behaviour shows."""
        orig = getattr(owner, name)
        clock = self

        def wrapped(enemy, *args, **kwargs):
            t0 = time.perf_counter()
            try:
                return orig(enemy, *args, **kwargs)
            finally:
                label = "phase1_" + str(enemy.behavior if isinstance(enemy.behavior, str) else type(enemy.behavior).__name__)
                clock.total[label] += time.perf_counter() - t0
                clock.calls[label] += 1

        setattr(owner, name, wrapped)
        self._saved.append((owner, name, orig))

    def _gc_callback(self, phase, info):
        if phase == "start":
            self._gc_t0 = time.perf_counter()
        elif phase == "stop":
            self.total["gc"] += time.perf_counter() - self._gc_t0
            self.calls["gc"] += 1

    def install(self):
        import enemy as enemy_module
        import states as states_module
        gc.callbacks.append(self._gc_callback)
        if self.mode == "serial":
            self._wrap(states_module, "update_enemy", "serial_update_enemy")
            self._wrap(enemy_module, "_apply_type_coordination", "serial_coordination")
        else:
            self._wrap_by_behaviour(parallel, "update_enemy")
            self._wrap(parallel, "update_enemy", "phase1_behaviours")
            self._wrap(parallel, "steer_snapshot", "snapshot_build")
            self._wrap(parallel, "pack_batch", "pack")
            self._wrap(parallel, "unpack_results", "unpack")
            self._wrap(parallel, "apply_steering", "apply")
            self._wrap(parallel.SteerBatcher, "steer", "steer_total")

    def uninstall(self):
        if self._gc_callback in gc.callbacks:
            gc.callbacks.remove(self._gc_callback)
        for owner, name, orig in reversed(self._saved):
            setattr(owner, name, orig)
        self._saved = []

    def reset(self):
        self.total.clear()
        self.calls.clear()

    def split(self, frames: int) -> dict:
        """Milliseconds per timed step for each stage. The pool round trip is the steer residual."""
        frames = max(1, int(frames))
        ms = {k: 1000.0 * v / frames for k, v in self.total.items()}
        if self.mode == "serial":
            return {
                "gc_ms_per_step": ms.get("gc", 0.0),
                "serial_update_enemy_ms_per_step": ms.get("serial_update_enemy", 0.0),
                "serial_coordination_ms_per_step": ms.get("serial_coordination", 0.0),
                "serial_behaviours_ms_per_step": ms.get("serial_update_enemy", 0.0) - ms.get("serial_coordination", 0.0),
            }
        steer_total = ms.get("steer_total", 0.0)
        pack = ms.get("pack", 0.0)
        unpack = ms.get("unpack", 0.0)
        per_behaviour = {
            k.replace("phase1_", "behaviour_") + "_ms_per_step": v
            for k, v in ms.items() if k.startswith("phase1_") and k != "phase1_behaviours"
        }
        return {
            "gc_ms_per_step": ms.get("gc", 0.0),
            **dict(sorted(per_behaviour.items())),
            "phase1_behaviours_ms_per_step": ms.get("phase1_behaviours", 0.0),
            "snapshot_build_ms_per_step": ms.get("snapshot_build", 0.0),
            "pack_ms_per_step": pack,
            "pool_round_trip_ms_per_step": max(0.0, steer_total - pack - unpack),
            "unpack_ms_per_step": unpack,
            "apply_ms_per_step": ms.get("apply", 0.0),
            "steer_call_ms_per_step": steer_total,
        }


def set_mode(mode: str):
    """Pick the steering path for the next run. The caller restores config.PARALLEL_STEER_ENABLED on exit."""
    parallel.set_batcher(None)
    if mode == "serial":
        config.PARALLEL_STEER_ENABLED = False
    elif mode == "inline":
        config.PARALLEL_STEER_ENABLED = True
        parallel.set_batcher(parallel.SteerBatcher(workers=0, min_enemies=int(config.PARALLEL_STEER_MIN_ENEMIES)))
    elif mode == "pooled":
        config.PARALLEL_STEER_ENABLED = True
    else:
        raise ValueError(mode)


def state_hash(state, player) -> str:
    parts = [repr((player.pos.x, player.pos.y, player.hp))]
    parts += [repr((e.pos.x, e.pos.y, e.vel.x, e.vel.y, e.hp, e.attack_cd)) for e in state.enemies]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def run_once(game: Game, count: int, steps: int, warmup: int, seed: int, profiler=None, clock=None):
    """One keep-alive run. Returns (step_ms, draw_ms, load, final_hash, timed_steps).

    ``load`` is a dict of per-step means: live enemies, projectiles and particles. Draw cost follows these
    counts, so the modes are compared with the counts next to them.
    """
    step_ms, draw_ms, alive, shots, parts = [], [], [], [], []
    with pinned_identities():
        random.seed(seed)
        state = bench.build_forced_wave(game, count, seed)
        game.auto_shoot = False
        state.wave_active = True
        player = game.player
        for frame in range(warmup + steps):
            player.hp = max(int(player.hp), int(player.max_hp))  # keep the run alive
            if clock is not None and frame == warmup:
                clock.reset()
            if profiler is not None and frame >= warmup:
                profiler.enable()
            t0 = time.perf_counter()
            game._fixed_step()
            t1 = time.perf_counter()
            game.on_draw()
            glFinish()
            t2 = time.perf_counter()
            if profiler is not None and frame >= warmup:
                profiler.disable()
            if frame >= warmup:
                step_ms.append((t1 - t0) * 1000.0)
                draw_ms.append((t2 - t1) * 1000.0)
                alive.append(len(game.state.enemies))
                shots.append(len(game.state.projectiles))
                parts.append(len(game.particle_system.particles))
            if not game.state.enemies:
                break  # every unit is gone; no further steps measure anything
        final = state_hash(game.state, player)
    load = {
        "enemies_mean": statistics.fmean(alive) if alive else 0.0,
        "projectiles_mean": statistics.fmean(shots) if shots else 0.0,
        "particles_mean": statistics.fmean(parts) if parts else 0.0,
    }
    return step_ms, draw_ms, load, final, len(step_ms)


def summary(values):
    if not values:
        return {"median": 0.0, "mean": 0.0, "p90": 0.0, "n": 0}
    ordered = sorted(values)
    p90 = ordered[int(round(0.9 * (len(ordered) - 1)))]
    return {"median": statistics.median(values), "mean": statistics.fmean(values), "p90": p90, "n": len(values)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--counts", default="40,64", help="comma-separated forced-wave sizes")
    ap.add_argument("--steps", type=int, default=150, help="timed steps per run")
    ap.add_argument("--warmup", type=int, default=20, help="untimed steps per run (lets the pool boot)")
    ap.add_argument("--repeats", type=int, default=3, help="runs per mode per count")
    ap.add_argument("--modes", default=",".join(MODES), help="subset of serial,inline,pooled")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument("--profile", action="store_true", help="cProfile one run per mode at the largest count")
    ap.add_argument("--phases", action="store_true", help="split the batch path into stages")
    ap.add_argument("--out", default="", help="write a JSON report here")
    ap.add_argument("--frame-opt", choices=("on", "off"), default="on",
                    help="config.ENABLE_MULTICORE_FRAME for this process (off = the reference code paths)")
    args = ap.parse_args(argv)

    counts = [int(c) for c in args.counts.split(",") if c.strip()]
    modes = [m.strip() for m in args.modes.split(",") if m.strip()]
    for m in modes:
        if m not in MODES:
            raise SystemExit("unknown mode %r" % m)

    tmp = tempfile.mkdtemp(prefix="ploto_frame_bench_")
    score.HIGH_SCORE_FILE = os.path.join(tmp, "high_scores.json")
    progress.PROGRESS_FILE = os.path.join(tmp, "progress.json")

    original_flag = bool(config.PARALLEL_STEER_ENABLED)
    original_frame_opt = bool(config.ENABLE_MULTICORE_FRAME)
    config.ENABLE_MULTICORE_FRAME = args.frame_opt == "on"
    game = Game()
    game.set_visible(False)
    rows = []
    finals = {}
    profiles = {}
    phase_split = {}
    try:
        # Keep-alive: the game and the steering pool stay up for every run in this process.
        for count in counts:
            per_mode = {m: {"step": [], "draw": [], "alive": [], "finals": []} for m in modes}
            for rep in range(args.repeats):
                order = modes[rep % len(modes):] + modes[:rep % len(modes)]  # rotate the order each repeat
                for mode in order:
                    set_mode(mode)
                    clock = None
                    if args.phases:
                        clock = PhaseClock(mode)
                        clock.install()
                    try:
                        step_ms, draw_ms, load, final, timed = run_once(
                            game, count, args.steps, args.warmup, args.seed, clock=clock)
                    finally:
                        if clock is not None:
                            clock.uninstall()
                    if clock is not None:
                        phase_split.setdefault(str(count), {}).setdefault(mode, []).append(clock.split(timed))
                    bucket = per_mode[mode]
                    bucket["step"].append(statistics.median(step_ms))
                    bucket["draw"].append(statistics.median(draw_ms))
                    bucket["alive"].append(load["enemies_mean"])
                    bucket.setdefault("shots", []).append(load["projectiles_mean"])
                    bucket.setdefault("parts", []).append(load["particles_mean"])
                    bucket["finals"].append(final)
                    print("  count=%d rep=%d mode=%-6s step_med=%.3f draw_med=%.3f alive=%.1f shots=%.1f parts=%.1f"
                          % (count, rep, mode, bucket["step"][-1], bucket["draw"][-1], bucket["alive"][-1],
                             bucket["shots"][-1], bucket["parts"][-1]), flush=True)
            if args.profile:
                for mode in modes:
                    if count != max(counts):
                        continue
                    set_mode(mode)
                    prof = cProfile.Profile()
                    run_once(game, count, args.steps, args.warmup, args.seed, profiler=prof)
                    stats = pstats.Stats(prof)
                    top = sorted(stats.stats.items(), key=lambda kv: kv[1][3], reverse=True)[:TOP_N]
                    profiles.setdefault(str(count), {})[mode] = [
                        {
                            "function": "%s:%d(%s)" % (os.path.basename(k[0]), k[1], k[2]),
                            "calls": int(v[1]),
                            "own_s": round(float(v[2]), 4),
                            "cumulative_s": round(float(v[3]), 4),
                        }
                        for k, v in top
                    ]
            rows.append({
                "enemies": count,
                "modes": {
                    m: {
                        "step_ms_run_medians": per_mode[m]["step"],
                        "draw_ms_run_medians": per_mode[m]["draw"],
                        "step_ms_median": statistics.median(per_mode[m]["step"]),
                        "step_ms_spread": [min(per_mode[m]["step"]), max(per_mode[m]["step"])],
                        "draw_ms_median": statistics.median(per_mode[m]["draw"]),
                        "total_ms_median": statistics.median(per_mode[m]["step"]) + statistics.median(per_mode[m]["draw"]),
                        "enemies_alive_mean": statistics.fmean(per_mode[m]["alive"]),
                        "projectiles_mean": statistics.fmean(per_mode[m].get("shots", [0.0])),
                        "particles_mean": statistics.fmean(per_mode[m].get("parts", [0.0])),
                        "final_hashes_distinct": len(set(per_mode[m]["finals"])),
                    }
                    for m in modes
                },
            })
            finals[str(count)] = {m: sorted(set(per_mode[m]["finals"])) for m in modes}
    finally:
        parallel.set_batcher(None)
        parallel.close_batcher()
        config.PARALLEL_STEER_ENABLED = original_flag
        config.ENABLE_MULTICORE_FRAME = original_frame_opt
        game.close()

    print("\nenemies  mode     step med  step spread        draw med  total med  alive  shots  parts  step vs serial")
    for row in rows:
        base = row["modes"].get("serial", {}).get("step_ms_median")
        for m in modes:
            r = row["modes"][m]
            ratio = (r["step_ms_median"] / base) if base else float("nan")
            print("%7d  %-7s %9.3f  [%7.3f, %7.3f]  %9.3f  %9.3f  %5.1f  %5.1f  %5.1f  %6.3f"
                  % (row["enemies"], m, r["step_ms_median"], r["step_ms_spread"][0], r["step_ms_spread"][1],
                     r["draw_ms_median"], r["total_ms_median"], r["enemies_alive_mean"],
                     r["projectiles_mean"], r["particles_mean"], ratio))
    for count, per_mode_split in phase_split.items():
        for m, splits in per_mode_split.items():
            keys = list(splits[0].keys())
            avg = {k: statistics.median(s[k] for s in splits) for k in keys}
            print("phases at %s, %s (median over runs, ms per step): %s"
                  % (count, m, ", ".join("%s=%.3f" % (k.replace("_ms_per_step", ""), v) for k, v in avg.items())))
    for count, per in finals.items():
        if "inline" in per and "pooled" in per:
            same = per["inline"] == per["pooled"] and len(per["inline"]) == 1
            print("finals at %s: inline == pooled (every repeat, one distinct hash per mode): %s" % (count, same))
        for m, hashes in per.items():
            if len(hashes) > 1:
                print("finals at %s: mode %s gave %d distinct hashes across repeats (not repeatable)" % (count, m, len(hashes)))

    report = {
        "bench": "tools/bench_frame_pool.py",
        "settings": {"counts": counts, "steps": args.steps, "warmup": args.warmup, "repeats": args.repeats,
                     "modes": modes, "seed": args.seed, "frame_opt": args.frame_opt,
                     "pool_workers": int(config.PARALLEL_STEER_WORKERS),
                     "pool_min_enemies": int(config.PARALLEL_STEER_MIN_ENEMIES)},
        "environment": {"python": platform.python_version(), "platform": platform.platform(),
                        "cpu_count": os.cpu_count(), "pyglet": pyglet.version},
        "rows": rows,
        "final_hashes": finals,
        "phases": phase_split,
        "profiles": profiles,
    }
    if args.out:
        with open(os.path.abspath(args.out), "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print("wrote %s" % os.path.abspath(args.out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
