#!/usr/bin/env python3
"""Measure enemy steering: the default serial loop against batch steering inline and in a process pool.

Run from the project root:

    .venv\\Scripts\\python.exe tools\\bench_steer.py --out steer_bench.json

Method. For each enemy count, the same seeded crowd and the same player path are used in every mode.
The steering stage of each frame is timed with perf_counter. Frames before --warmup are not timed,
which lets process pools start up. Only the steering stage is timed. Behaviors, clamps and
collisions are the same work in every mode, so they are left out. Between frames every enemy
advances by vel * dt, the same integration in every mode.

Modes:
  serial     the default interleaved path: enemy._apply_type_coordination for each enemy
  inline     the batch path with no pool: snapshot, steer_chunk, apply
  pool<W>    the batch path with a spawn-context process pool of W workers

Every mode's final velocities are checksummed. Equal checksums show the modes computed the same
steering here, because positions do not change during the steering stage.

The pool is only worth using if it beats the serial path. The crossover is the smallest enemy count
where the best pooled mode is faster than serial.
"""

import argparse
import json
import math
import os
import platform
import random
import statistics
import sys
import time
from types import SimpleNamespace

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import config  # noqa: E402
import enemy as E  # noqa: E402
from enemy_steer import steer_chunk  # noqa: E402
from parallel import SteerBatcher, apply_steering  # noqa: E402
from utils import Vec2  # noqa: E402

KEYS = ["chaser", "ranged", "swarm", "charger", "tank", "spitter", "flyer", "engineer", "bomber"]
DT = 1.0 / 60.0
CROWD_RADIUS = 480.0


def make_crowd(n: int, seed: int):
    """A seeded crowd of ``n`` non-boss enemies spread over the arena, cycling through the behaviours."""
    rng = random.Random(seed)
    st = SimpleNamespace(enemies=[], time=0.0, difficulty="normal", rng=rng, wave=15)
    for i in range(n):
        key = KEYS[i % len(KEYS)]
        a = rng.uniform(0.0, math.tau)
        r = CROWD_RADIUS * math.sqrt(rng.random())
        e = E.Enemy(
            pos=Vec2(r * math.cos(a), r * math.sin(a)),
            hp=20,
            speed=rng.uniform(60.0, 130.0),
            behavior=key,
            seed=rng.uniform(0.0, math.tau),
        )
        e.vel = Vec2(rng.uniform(-90.0, 90.0), rng.uniform(-90.0, 90.0))
        # The live formation bias comes from id(enemy), which differs between runs. Pin it here so
        # every mode sees the same inputs and the checksums can be compared.
        e.ai["formation_bias"] = ((i * 7919) % 997) / 997.0
        st.enemies.append(e)
    return st


def player_at(frame: int):
    """Player position and velocity on a slow orbit, identical in every mode."""
    t = frame * DT
    w = 0.6
    pos = Vec2(140.0 * math.cos(w * t), 140.0 * math.sin(w * t))
    vel = Vec2(-140.0 * w * math.sin(w * t), 140.0 * w * math.cos(w * t))
    return pos, vel


def steer_serial(st, pp, pv):
    for e in st.enemies:
        E._apply_type_coordination(e, pp, st, DT, pv)


def steer_batch(st, pp, pv, steered, batcher):
    batch, owners = E.steer_snapshot(st, pp, pv, DT, steered)
    if batcher is None:
        results = steer_chunk(batch, 0, len(batch.snaps))
    else:
        results = batcher.steer(batch)
    apply_steering(owners, results)


def run_mode(mode: str, n: int, frames: int, warmup: int, seed: int, workers: int = 0):
    st = make_crowd(n, seed)
    batcher = SteerBatcher(workers=workers) if mode == "pool" else None
    times_ms = []
    try:
        for f in range(frames + warmup):
            st.time = f * DT
            pp, pv = player_at(f)
            steered = {id(e) for e in st.enemies}
            t0 = time.perf_counter()
            if mode == "serial":
                steer_serial(st, pp, pv)
            else:
                steer_batch(st, pp, pv, steered, batcher)
            t1 = time.perf_counter()
            if f >= warmup:
                times_ms.append((t1 - t0) * 1000.0)
            for e in st.enemies:
                e.pos = e.pos + e.vel * DT
    finally:
        if batcher is not None:
            batcher.close()
    checksum = 0.0
    for e in st.enemies:
        checksum += e.vel.x * 1.0 + e.vel.y * 3.0
    return {
        "median_ms": statistics.median(times_ms),
        "p90_ms": sorted(times_ms)[int(0.9 * (len(times_ms) - 1))],
        "mean_ms": statistics.fmean(times_ms),
        "checksum": repr(checksum),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--counts", default="4,8,12,16,20,24,32,48,64", help="comma-separated enemy counts")
    ap.add_argument("--workers", default="2,3,4", help="comma-separated pool sizes to try")
    ap.add_argument("--frames", type=int, default=300, help="timed frames per mode")
    ap.add_argument("--warmup", type=int, default=30, help="untimed frames per mode")
    ap.add_argument("--seed", type=int, default=20261012)
    ap.add_argument("--out", default="", help="write the JSON report here")
    args = ap.parse_args(argv)

    counts = [int(x) for x in args.counts.split(",") if x.strip()]
    pool_sizes = [int(x) for x in args.workers.split(",") if x.strip()]
    report = {
        "method": {
            "timed_stage": "steering only (serial interleaved loop, or steer_snapshot + steer + apply)",
            "frames_timed": args.frames,
            "frames_warmup": args.warmup,
            "seed": args.seed,
            "dt": DT,
            "start_method": "spawn",
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "platform": platform.platform(),
            "config_PARALLEL_STEER_ENABLED": config.PARALLEL_STEER_ENABLED,
            "config_PARALLEL_STEER_MIN_ENEMIES": config.PARALLEL_STEER_MIN_ENEMIES,
        },
        "rows": [],
    }

    print("%6s %10s %10s %10s" % ("enemies", "serial_ms", "inline_ms", "best_pool"))
    for n in counts:
        serial = run_mode("serial", n, args.frames, args.warmup, args.seed)
        inline = run_mode("inline", n, args.frames, args.warmup, args.seed)
        pools = {}
        for w in pool_sizes:
            pools[str(w)] = run_mode("pool", n, args.frames, args.warmup, args.seed, workers=w)
        best_w = min(pools, key=lambda k: pools[k]["median_ms"])
        best = pools[best_w]
        same = all(p["checksum"] == serial["checksum"] for p in pools.values()) and inline["checksum"] == serial["checksum"]
        row = {
            "enemies": n,
            "serial": serial,
            "inline": inline,
            "pools": pools,
            "best_pool_workers": int(best_w),
            "speedup_best_pool_vs_serial": serial["median_ms"] / best["median_ms"],
            "checksums_equal": same,
        }
        report["rows"].append(row)
        print("%6d %10.3f %10.3f %6.3f(w%s)  checksums_equal=%s" % (
            n, serial["median_ms"], inline["median_ms"], best["median_ms"], best_w, same))

    crossover = None
    for row in report["rows"]:
        if row["speedup_best_pool_vs_serial"] > 1.0:
            crossover = row["enemies"]
            break
    report["crossover_enemies"] = crossover
    print("crossover (best pool faster than serial): %s" % (crossover if crossover is not None else "none in tested range"))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
        print("wrote %s" % args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
