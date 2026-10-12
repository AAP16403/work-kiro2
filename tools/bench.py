#!/usr/bin/env python3
"""Enemy AI benchmark for forced large waves.

Run from anywhere:
    D:\\work kiro2\\.venv\\Scripts\\python.exe tools\\bench.py
    D:\\work kiro2\\.venv\\Scripts\\python.exe tools\\bench.py --wave 20 30 --frames 300 --repeats 5

Each sample builds a forced wave of mixed non-boss enemies (all nine regular behaviours,
round-robin) on a headless Game, then drives update_enemy() over the whole list once per
frame. That is the per-enemy loop states.py runs before its post-update pass (clamp,
obstacles, player contact). Hazard lists are cleared each frame so projectile and trap
counts stay flat between samples.

Timings are wall-clock perf_counter values for the AI update only. Rendering and the
post-update pass are excluded. Warmup frames are discarded. Reported values are medians
over the repeats, and every repeat uses the same seed so the workload is identical.

Two batch columns come from the wave-1 parallel.py path: "inline batch" runs the batch steering with
no worker processes, and "pooled batch" runs it in a process pool of config.PARALLEL_STEER_WORKERS.
Both route each frame through parallel.maybe_update_enemies, as PlayingState does. The pool is
closed after its column is measured.
"""

import argparse
import math
import os
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


def run_frames(game, count: int, frames: int, seed: int, batcher=None):
    """Run `frames` AI frames on a forced wave. Returns (state, per-frame seconds).

    batcher=None is the serial loop. A batcher (parallel.SteerBatcher) is installed for the run, and each
    frame goes through parallel.maybe_update_enemies first, in the order PlayingState.update uses: the
    enemies it returns are skipped by the serial loop.
    """
    from utils import Vec2
    from enemy import update_enemy
    import parallel

    s = build_forced_wave(game, count, seed)
    # Some behaviours draw from the module-level random; seed it after the build so each run repeats.
    random.seed(seed)
    player = game.player
    zero = Vec2(0.0, 0.0)
    frame_times = []
    parallel.set_batcher(batcher)
    try:
        for _ in range(frames):
            s.time += FRAME_DT
            s.projectiles.clear()
            s.traps.clear()
            s.lasers.clear()
            s.thunders.clear()
            t0 = time.perf_counter()
            batched = None
            if batcher is not None:
                batched = parallel.maybe_update_enemies(s, game, FRAME_DT, player.pos, zero)
            for e in list(s.enemies):
                if batched is not None and id(e) in batched:
                    continue
                update_enemy(e, player.pos, s, FRAME_DT, game, player_vel=zero)
            frame_times.append(time.perf_counter() - t0)
    finally:
        parallel.set_batcher(None)
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


def measure(game, count: int, frames: int = 300, repeats: int = 5, seed: int = 1, batcher=None) -> dict:
    """Median frame cost of the AI update for a forced wave of `count` enemies (serial, or with `batcher`)."""
    run_medians = []
    run_means = []
    for _ in range(repeats):
        _, times = run_frames(game, count, WARMUP_FRAMES + frames, seed, batcher=batcher)
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


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Forced large-wave enemy AI benchmark.")
    parser.add_argument("--wave", type=int, nargs="+", default=[20, 30], help="enemy counts to force (default: 20 30)")
    parser.add_argument("--frames", type=int, default=300, help="timed frames per repeat (default: 300)")
    parser.add_argument("--repeats", type=int, default=5, help="repeats; the median is reported (default: 5)")
    args = parser.parse_args(argv)

    os.chdir(ROOT)
    from game import Game

    game = Game()
    game.set_visible(False)
    try:
        import config
        import parallel

        print(f"forced wave {WAVE_NUMBER}, enemy AI update per frame, {args.frames} timed frames x {args.repeats} repeats")
        print(f"{'enemies':>8} {'serial median ms':>17} {'inline batch ms':>16} {'pooled batch ms':>16}  (median of repeats)")
        for count in args.wave:
            serial = measure(game, count, frames=args.frames, repeats=args.repeats)
            inline = measure(game, count, frames=args.frames, repeats=args.repeats,
                             batcher=parallel.SteerBatcher(workers=0, min_enemies=1))
            pooled_batcher = parallel.SteerBatcher(workers=int(config.PARALLEL_STEER_WORKERS), min_enemies=1)
            try:
                pooled = measure(game, count, frames=args.frames, repeats=args.repeats, batcher=pooled_batcher)
            finally:
                pooled_batcher.close()
            print(f"{serial['count']:>8} {serial['median_ms']:>17.3f} {inline['median_ms']:>16.3f} {pooled['median_ms']:>16.3f}")
    finally:
        game.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
