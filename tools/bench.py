#!/usr/bin/env python3
"""Enemy AI benchmark for forced large waves.

Run from anywhere:
    D:\\work kiro2\\.venv\\Scripts\\python.exe tools\\bench.py
    D:\\work kiro2\\.venv\\Scripts\\python.exe tools\\bench.py --wave 20 30 --frames 300 --repeats 5
    D:\\work kiro2\\.venv\\Scripts\\python.exe tools\\bench.py --out bench.json
  --out writes a JSON report: the medians for each count and the top 15 cProfile entries of one profiled pass.

Each sample builds a forced wave of mixed non-boss enemies (all nine regular behaviours,
round-robin) on a headless Game, then drives update_enemy() over the whole list once per
frame. That is the per-enemy loop states.py runs before its post-update pass (clamp,
obstacles, player contact). Hazard lists are cleared each frame so projectile and trap
counts stay flat between samples.

Timings are wall-clock perf_counter values for the AI update only. Rendering and the
post-update pass are excluded. Warmup frames are discarded. Reported values are medians
over the repeats, and every repeat uses the same seed so the workload is identical.

The parallel column is the wave-1 parallel.py batch steering path. While parallel.py is
not in the worktree the column prints [SKIP requires-wave1] instead of a number.
"""

import argparse
import cProfile
import importlib.util
import json
import math
import os
import pstats
import random
import statistics
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

FRAME_DT = 1.0 / 60.0
WARMUP_FRAMES = 15
WAVE_NUMBER = 12
FORCED_MIX = ["chaser", "swarm", "charger", "ranged", "tank", "spitter", "flyer", "engineer", "bomber"]


def parallel_available() -> bool:
    """True when wave 1's parallel.py is importable from this worktree."""
    return importlib.util.find_spec("parallel") is not None


def build_forced_wave(game, count: int, seed: int):
    """Start a PLAYING run and fill state.enemies with `count` mixed enemies on a ring around the player."""
    from enemy import Enemy
    from level import _TUNING_LOGIC
    from states import GameStateName
    from utils import Vec2

    game._init_game()
    game.fsm.set_state(GameStateName.PLAYING)
    s = game.state
    s.wave = WAVE_NUMBER
    s.init_rng(seed)
    s.enemies = []

    center = game.player.pos
    for i in range(count):
        behavior = FORCED_MIX[i % len(FORCED_MIX)]
        hp, speed, attack_mult = _TUNING_LOGIC.enemy_stats(behavior, s.wave, s.difficulty)
        ang = math.tau * i / float(count)
        dist = 300.0 + (i % 4) * 36.0
        pos = Vec2(center.x + math.cos(ang) * dist, center.y + math.sin(ang) * dist)
        lo, hi = _TUNING_LOGIC.spawn_attack_cd_range(behavior)
        e = Enemy(pos=pos, hp=hp, speed=speed, behavior=behavior, max_hp=hp)
        e.attack_cd = s.rng.uniform(lo, hi) / max(0.6, min(1.6, float(attack_mult)))
        e.ai["attack_mult"] = float(attack_mult)
        s.enemies.append(e)
    return s


def run_frames(game, count: int, frames: int, seed: int):
    """Run `frames` AI frames on a forced wave. Returns (state, per-frame seconds)."""
    from utils import Vec2
    from enemy import update_enemy

    s = build_forced_wave(game, count, seed)
    # Some behaviours draw from the module-level random; seed it after the build so each run repeats.
    random.seed(seed)
    player = game.player
    zero = Vec2(0.0, 0.0)
    frame_times = []
    for _ in range(frames):
        s.time += FRAME_DT
        s.projectiles.clear()
        s.traps.clear()
        s.lasers.clear()
        s.thunders.clear()
        t0 = time.perf_counter()
        for e in list(s.enemies):
            update_enemy(e, player.pos, s, FRAME_DT, game, player_vel=zero)
        frame_times.append(time.perf_counter() - t0)
    return s, frame_times


def snapshot(state) -> list:
    """Exact per-enemy kinematic and AI-timer state, for comparing two runs."""
    return [
        (e.pos.x, e.pos.y, e.vel.x, e.vel.y, e.hp, e.attack_cd, e.seed)
        for e in state.enemies
    ]


def run_snapshot(game, count: int, frames: int, seed: int) -> list:
    s, _ = run_frames(game, count, frames, seed)
    return snapshot(s)


def measure(game, count: int, frames: int = 300, repeats: int = 5, seed: int = 1) -> dict:
    """Median frame cost of the serial AI update for a forced wave of `count` enemies."""
    run_medians = []
    run_means = []
    for _ in range(repeats):
        _, times = run_frames(game, count, WARMUP_FRAMES + frames, seed)
        timed = [t * 1000.0 for t in times[WARMUP_FRAMES:]]
        run_medians.append(statistics.median(timed))
        run_means.append(statistics.fmean(timed))
    return {
        "count": int(count),
        "frames": int(frames),
        "repeats": int(repeats),
        "median_ms": float(statistics.median(run_medians)),
        "mean_ms": float(statistics.median(run_means)),
    }


PROFILE_TOP_N = 15


def top_cumulative(profiler, top_n: int = PROFILE_TOP_N) -> list:
    """The top ``top_n`` functions by cumulative time from a finished cProfile run, as plain dicts."""
    stats = pstats.Stats(profiler)
    rows = []
    for (path, line, name), (_cc, calls, own, cumulative, _callers) in stats.stats.items():
        rows.append({
            "function": f"{os.path.basename(path)}:{line}({name})",
            "calls": int(calls),
            "own_s": float(own),
            "cumulative_s": float(cumulative),
        })
    rows.sort(key=lambda row: row["cumulative_s"], reverse=True)
    return rows[:top_n]


def write_report(path: str, report: dict) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Forced large-wave enemy AI benchmark.")
    parser.add_argument("--wave", type=int, nargs="+", default=[20, 30], help="enemy counts to force (default: 20 30)")
    parser.add_argument("--frames", type=int, default=300, help="timed frames per repeat (default: 300)")
    parser.add_argument("--repeats", type=int, default=5, help="repeats; the median is reported (default: 5)")
    parser.add_argument("--out", default="", help="write a JSON report: the medians per count and the top 15 cProfile entries")
    args = parser.parse_args(argv)
    out_path = os.path.abspath(args.out) if args.out else ""  # resolved before the chdir below

    os.chdir(ROOT)
    from game import Game

    game = Game()
    game.set_visible(False)
    try:
        print(f"forced wave {WAVE_NUMBER}, enemy AI update per frame, {args.frames} timed frames x {args.repeats} repeats")
        print(f"{'enemies':>8} {'serial median ms':>17} {'serial mean ms':>15}  parallel")
        results = []
        for count in args.wave:
            r = measure(game, count, frames=args.frames, repeats=args.repeats)
            results.append(r)
            if parallel_available():
                par = "[SKIP requires-wave1] parallel path not wired into this bench revision"
            else:
                par = "[SKIP requires-wave1] parallel.py not in this worktree"
            print(f"{r['count']:>8} {r['median_ms']:>17.3f} {r['mean_ms']:>15.3f}  {par}")
        if out_path:
            # One profiled pass over the largest forced wave, so the report names where the AI time goes.
            profiler = cProfile.Profile()
            profiler.enable()
            run_frames(game, max(args.wave), args.frames, seed=1)
            profiler.disable()
            report = {
                "wave_number": WAVE_NUMBER,
                "frames": int(args.frames),
                "repeats": int(args.repeats),
                "results": results,
                "top_cumulative": top_cumulative(profiler, PROFILE_TOP_N),
            }
            write_report(out_path, report)
            print(f"wrote {out_path} ({len(report['top_cumulative'])} cProfile entries)")
    finally:
        game.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
