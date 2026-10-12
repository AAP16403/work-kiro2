"""Headless, seeded benchmark for the PLOUTO frame loop.

Run it with the project venv from anywhere:

    D:\\work kiro2\\.venv\\Scripts\\python.exe tools\\bench.py --out bench_report.json

What it does:

* Builds a real Game in a hidden window at a fixed windowed size (default 980x620).
* For each wave in --waves (default 1,8,15,22,29) it starts a fresh run at a fixed seed in its
  own Python process, forces the wave number, and plays --frames fixed 1/60 s steps. A scripted bot drives the
  player: a fixed movement cycle, aim at the nearest enemy, a dash on a fixed cadence, and
  full HP at every frame so the run never ends. Nothing in the bot reads the wall clock.
* Each frame times Game.update (one fixed simulation step) and Game.on_draw, followed by
  glFinish so GPU work is counted. The buffer swap is skipped, so vsync never blocks.
* The same seeded script is replayed under cProfile. The top 15 functions by cumulative time
  go into the report. Timings come from the un-profiled pass, so profiler overhead does not
  inflate them.
* A SHA-256 over the simulation state of each pass shows that both passes ran the same game.
  Framebuffer SHA-256 digests at sampled frames show whether a rendering change altered the
  picture; --frame-dir also saves those frames as PNG files for a visual check.
* --compare OLD.json prints the median deltas against an earlier report.

Report keys: settings, environment, method, waves (median/mean/p95/max per wave plus the raw
per-frame series), determinism, frame_digests, profile_top15_cumulative and, with --compare,
compare.
"""

import argparse
import builtins
import cProfile
import hashlib
import json
import os
import platform
import pstats
import random
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import pyglet  # noqa: E402

import config  # noqa: E402
from game import Game  # noqa: E402  (game.py sets the pyglet GL options before pyglet.gl loads)
from pyglet.gl import glFinish  # noqa: E402
import states as game_states  # noqa: E402
import visuals  # noqa: E402
from states import GameStateName, PlayingState  # noqa: E402
from utils import Vec2, set_view_size, to_iso  # noqa: E402

DEFAULT_WAVES = (1, 8, 15, 22, 29)
DEFAULT_SEED = 20260612
DEFAULT_FRAMES = 600
DEFAULT_WARMUP = 60
DEFAULT_IMAGE_FRAMES = (240, 480)
DEFAULT_SIZE = (config.SCREEN_W, config.SCREEN_H)
FIXED_DT = 1.0 / float(config.FPS)
TOP_N = 15


class NullAudio:
    """Silent stand-in for AudioManager so the bench never opens the sound device."""

    def play(self, *args, **kwargs):
        pass

    def play_music(self, *args, **kwargs):
        pass

    def duck(self, *args, **kwargs):
        pass

    def set_volumes(self, *args, **kwargs):
        pass

    def update(self, dt):
        pass


class ScriptedBot:
    """Deterministic player. Each decision depends only on the frame index and the game state."""

    # Each leg holds a set of movement keys (iso moves: W=NE, D=SE, S=SW, A=NW).
    LEGS = (("W",), ("W", "D"), ("D",), ("S", "D"), ("S",), ("S", "A"), ("A",), ("A", "W"))
    FRAMES_PER_LEG = 90
    DASH_EVERY = 240

    def __init__(self, game):
        self.game = game
        self._key = pyglet.window.key
        self._codes = {"W": self._key.W, "A": self._key.A, "S": self._key.S, "D": self._key.D}

    def step(self, frame: int) -> None:
        g = self.game
        leg = self.LEGS[(frame // self.FRAMES_PER_LEG) % len(self.LEGS)]
        for name, code in self._codes.items():
            g.keys.data[code] = name in leg  # KeyStateHandler keeps its state in .data

        p = g.player
        p.hp = max(int(p.hp), int(p.max_hp))  # god mode: the run never ends

        target = None
        best = float("inf")
        for e in g.state.enemies:
            d2 = (e.pos.x - p.pos.x) ** 2 + (e.pos.y - p.pos.y) ** 2
            if d2 < best:
                best = d2
                target = e
        if target is not None:
            g.mouse_xy = to_iso(target.pos, Vec2(0.0, 0.0))
        else:
            # Fixed idle aim, so no frame inherits the mouse position of the run before it.
            g.mouse_xy = (g.width * 0.5 + 120.0, g.height * 0.5)

        if frame % self.DASH_EVERY == self.DASH_EVERY - 1:
            g._dash()


def _percentile(values, pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * pct / 100.0
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def _summary(values) -> dict:
    if not values:
        return {"n": 0, "median": 0.0, "mean": 0.0, "p95": 0.0, "max": 0.0}
    return {
        "n": len(values),
        "median": round(statistics.median(values), 4),
        "mean": round(statistics.fmean(values), 4),
        "p95": round(_percentile(values, 95.0), 4),
        "max": round(max(values), 4),
    }


def _make_game(width: int, height: int) -> Game:
    """A real Game in a hidden window, pinned to a windowed size and the Full shake setting."""
    game = Game()
    game.set_visible(False)
    game._on_settings_change({"fullscreen": False, "window_size": (int(width), int(height))})
    game.dispatch_events()
    if (game.width, game.height) != (int(width), int(height)):
        game.set_size(int(width), int(height))
        game.dispatch_events()
    if (game.width, game.height) != (int(width), int(height)):
        raise RuntimeError(f"window is {game.width}x{game.height}, expected {width}x{height}")
    set_view_size(game.width, game.height)
    game._update_room_radius_from_view()
    config.SHAKE_SCALE = float(config.SHAKE_FULL_SCALE)
    game.audio = NullAudio()
    return game


class _SequenceIds:
    """Replaces id() inside the enemy and state modules, for this process only.

    enemy.py seeds formation_bias from id(enemy) % 997, and states.py keys projectile hit sets
    by id(enemy). CPython ids are heap addresses, so the same seed would play differently from
    one run to the next. Each object gets a sequence number on first use, reset per wave, which
    keeps the simulation reproducible. Game code is untouched.
    """

    def __init__(self):
        self._next = 1

    def reset(self) -> None:
        self._next = 1

    def __call__(self, obj) -> int:
        uid = getattr(obj, "_bench_uid", None)
        if uid is None:
            uid = self._next * 16
            self._next += 1
            try:
                obj._bench_uid = uid
            except (AttributeError, TypeError):
                return builtins.id(obj)
        return uid


_SEQ_IDS = _SequenceIds()


_SHIMMED_MODULES = []


def _project_modules():
    """Loaded game modules under ROOT, excluding tools, tests and the browser build."""
    skip_dirs = (os.path.join(ROOT, "tools"), os.path.join(ROOT, "vercel_site"))
    for mod in list(sys.modules.values()):
        path = getattr(mod, "__file__", None)
        if not path:
            continue
        path = os.path.abspath(path)
        if not path.startswith(ROOT) or path.startswith(skip_dirs):
            continue
        if os.path.basename(path).startswith("test_"):
            continue
        yield mod


def _install_sequence_ids() -> None:
    """Route id() through the sequence shim in every game module.

    Several enemy behaviours pick a side or a speed with id(enemy) % N (bomber, chase, swarm,
    spitter, engineer, ranged), so the bench must cover all of them, not only enemy.py.
    """
    import importlib
    import pkgutil

    import enemy_behaviors

    for info in pkgutil.walk_packages(enemy_behaviors.__path__, prefix="enemy_behaviors."):
        importlib.import_module(info.name)
    for mod in _project_modules():
        mod.id = _SEQ_IDS
        _SHIMMED_MODULES.append(mod)


def _uninstall_sequence_ids() -> None:
    """Remove the shim so later code in the same process sees the builtin id again."""
    for mod in _SHIMMED_MODULES:
        if "id" in vars(mod):
            del mod.id
    _SHIMMED_MODULES.clear()


def _start_run(game: Game, wave: int, seed: int) -> None:
    """Fresh run with every random source reseeded, the wave forced, and a spawn due right away."""
    seg_seed = int(seed) + int(wave)
    random.seed(seg_seed)
    game_states._SHAKE_RNG.seed(seg_seed)
    _SEQ_IDS.reset()
    game._init_game()
    game.state.init_rng(seg_seed)
    game.state.wave = int(wave)
    game.state.last_wave_clear = -10.0
    game.fsm.set_state(GameStateName.PLAYING)


def _sim_fingerprint(game: Game) -> bytes:
    s = game.state
    p = game.player
    parts = [repr(s.time), repr(s.wave), repr(s.shake), repr((p.pos.x, p.pos.y, p.hp))]
    parts += [repr((e.pos.x, e.pos.y, e.hp, getattr(e, "shield", 0))) for e in s.enemies]
    parts += [repr((q.pos.x, q.pos.y, q.ttl)) for q in s.projectiles]
    parts += [repr((pu.pos.x, pu.pos.y, pu.kind)) for pu in s.powerups]
    return "|".join(parts).encode("utf-8")


def _framebuffer(game: Game):
    buf = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
    return buf, buf.get_data("RGBA", buf.width * 4)


def _play(game: Game, waves, frames: int, warmup: int, seed: int, *, image_frames=(), frame_dir=None,
          profiler=None) -> dict:
    """Play every wave segment once. Returns per-wave series, sim digests and frame digests."""
    out = {}
    for wave in waves:
        _start_run(game, wave, seed)
        bot = ScriptedBot(game)
        sim = hashlib.sha256()
        update_ms, draw_ms, enemies, particles, digests = [], [], [], [], []
        for frame in range(frames):
            game.state.wave = int(wave)
            bot.step(frame)

            if profiler is not None:
                profiler.enable()
            t0 = time.perf_counter()
            game.update(FIXED_DT)
            t1 = time.perf_counter()
            game.on_draw()
            glFinish()
            t2 = time.perf_counter()
            if profiler is not None:
                profiler.disable()

            if not isinstance(game.fsm.current_state, PlayingState):
                game.fsm.set_state(GameStateName.PLAYING)  # boss reward screens are skipped

            sim.update(_sim_fingerprint(game))
            if frame >= warmup:
                update_ms.append((t1 - t0) * 1000.0)
                draw_ms.append((t2 - t1) * 1000.0)
                enemies.append(len(game.state.enemies))
                particles.append(len(game.particle_system.particles))
            if frame in image_frames:
                buf, data = _framebuffer(game)
                digests.append({"frame": frame, "sha256": hashlib.sha256(data).hexdigest()})
                if frame_dir:
                    os.makedirs(frame_dir, exist_ok=True)
                    buf.save(os.path.join(frame_dir, f"wave{int(wave):02d}_frame{frame:04d}.png"))
        out[int(wave)] = {
            "update_ms": update_ms,
            "draw_ms": draw_ms,
            "enemies": enemies,
            "particles": particles,
            "sim_sha256": sim.hexdigest(),
            "frame_digests": digests,
        }
    return out


def _top_cumulative(profile, top_n: int) -> list:
    """Top functions by cumulative time. Accepts a cProfile.Profile or a pstats.Stats."""
    stats = profile if isinstance(profile, pstats.Stats) else pstats.Stats(profile)
    rows = []
    for (filename, line, name), (_cc, ncalls, tottime, cumtime, _callers) in stats.stats.items():
        if filename == "~":
            where = "<builtin>"
        elif filename.startswith(ROOT):
            where = os.path.relpath(filename, ROOT).replace("\\", "/")
        else:
            where = os.path.basename(filename)
        rows.append({
            "function": name,
            "file": where,
            "line": int(line),
            "ncalls": int(ncalls),
            "tottime_s": round(float(tottime), 6),
            "cumtime_s": round(float(cumtime), 6),
        })
    rows.sort(key=lambda r: (-r["cumtime_s"], r["file"], r["line"], r["function"]))
    return rows[:top_n]


def _wave_stats(series: dict) -> dict:
    out = {}
    for wave, data in series.items():
        upd = _summary(data["update_ms"])
        drw = _summary(data["draw_ms"])
        out[str(wave)] = {
            "frames": len(data["update_ms"]),
            "update_ms": upd,
            "draw_ms": drw,
            "total_median_ms": round(upd["median"] + drw["median"], 4),
            "enemies_mean": round(statistics.fmean(data["enemies"]), 2) if data["enemies"] else 0.0,
            "particles_mean": round(statistics.fmean(data["particles"]), 2) if data["particles"] else 0.0,
            "series_ms": {
                "update": [round(v, 4) for v in data["update_ms"]],
                "draw": [round(v, 4) for v in data["draw_ms"]],
            },
        }
    return out


def _print_table(waves: dict) -> None:
    head = f"{'wave':>5} {'frames':>6} {'upd med':>9} {'upd p95':>9} {'draw med':>9} {'draw p95':>9} {'tot med':>9} {'enemies':>8} {'parts':>7}"
    print(head)
    print("-" * len(head))
    for wave, w in waves.items():
        print(f"{wave:>5} {w['frames']:>6} {w['update_ms']['median']:>9.3f} {w['update_ms']['p95']:>9.3f} "
              f"{w['draw_ms']['median']:>9.3f} {w['draw_ms']['p95']:>9.3f} {w['total_median_ms']:>9.3f} "
              f"{w['enemies_mean']:>8.1f} {w['particles_mean']:>7.1f}")
    print("(all times in ms; medians over measured frames, warm-up frames excluded)")


def _compare(current: dict, baseline_path: str) -> dict:
    with open(baseline_path, "r", encoding="utf-8") as fh:
        base = json.load(fh)
    rows = {}
    print(f"\nDelta against {os.path.basename(baseline_path)} (negative = faster):")
    print(f"{'wave':>5} {'upd base':>9} {'upd now':>9} {'upd delta':>10} {'draw base':>10} {'draw now':>9} {'draw delta':>11}")
    for wave, now in current["waves"].items():
        old = base.get("waves", {}).get(wave)
        if not old:
            continue
        ub, un = old["update_ms"]["median"], now["update_ms"]["median"]
        db, dn = old["draw_ms"]["median"], now["draw_ms"]["median"]
        rows[wave] = {"update_ms_median_before": ub, "update_ms_median_after": un,
                      "draw_ms_median_before": db, "draw_ms_median_after": dn}
        print(f"{wave:>5} {ub:>9.3f} {un:>9.3f} {un - ub:>+10.3f} {db:>10.3f} {dn:>9.3f} {dn - db:>+11.3f}")
    return rows


def _parse_int_list(text: str):
    return tuple(int(part) for part in str(text).split(",") if part.strip())


def _parse_size(text: str):
    w, h = str(text).lower().split("x")
    return int(w), int(h)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Seeded headless benchmark for PLOUTO's update and draw paths.")
    ap.add_argument("--out", default="bench_report.json", help="path of the JSON report to write")
    ap.add_argument("--waves", default=",".join(str(w) for w in DEFAULT_WAVES), help="comma list of wave numbers to force")
    ap.add_argument("--frames", type=int, default=DEFAULT_FRAMES, help="fixed 1/60 s frames per wave")
    ap.add_argument("--warmup", type=int, default=DEFAULT_WARMUP, help="leading frames per wave left out of the statistics")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="base seed; each wave uses seed + wave")
    ap.add_argument("--size", default=f"{DEFAULT_SIZE[0]}x{DEFAULT_SIZE[1]}", help="windowed size WxH")
    ap.add_argument("--image-frames", default=",".join(str(f) for f in DEFAULT_IMAGE_FRAMES),
                    help="frame indices whose framebuffer is hashed (and saved with --frame-dir)")
    ap.add_argument("--frame-dir", default=None, help="if set, save the sampled frames as PNG files here")
    ap.add_argument("--no-profile", action="store_true", help="skip the cProfile replay pass")
    ap.add_argument("--compare", default=None, help="earlier bench JSON to diff medians against")
    # Internal: a child process plays one wave (see _run_wave_process).
    ap.add_argument("--child-wave", type=int, default=None, help=argparse.SUPPRESS)
    ap.add_argument("--child-result", default=None, help=argparse.SUPPRESS)
    ap.add_argument("--child-profile", default=None, help=argparse.SUPPRESS)
    return ap


def _child_entry(args) -> int:
    """Play one wave in this fresh process: the timed pass, or the cProfile pass when --child-profile is set."""
    wave = int(args.child_wave)
    width, height = _parse_size(args.size)
    profiling = bool(args.child_profile)
    image_frames = set() if profiling else set(_parse_int_list(args.image_frames))
    frame_dir = os.path.abspath(args.frame_dir) if (args.frame_dir and not profiling) else None
    os.chdir(ROOT)
    _install_sequence_ids()
    game = None
    profiler = cProfile.Profile() if profiling else None
    try:
        game = _make_game(width, height)
        series = _play(game, [wave], args.frames, args.warmup, args.seed,
                       image_frames=image_frames, frame_dir=frame_dir, profiler=profiler)
    finally:
        if game is not None:
            game.close()
        _uninstall_sequence_ids()
    if profiler is not None:
        profiler.dump_stats(os.path.abspath(args.child_profile))
    with open(os.path.abspath(args.child_result), "w", encoding="utf-8") as fh:
        json.dump(series[wave], fh)
    return 0


def _run_wave_process(args, wave: int, tmp_dir: str, profiling: bool) -> dict:
    """Run one wave in a fresh interpreter, so no game state or RNG carries over from other waves.

    Returns the child's result dict. For a profiling run, the result also carries "profile_path".
    """
    tag = "profile" if profiling else "timed"
    result_path = os.path.join(tmp_dir, f"wave{wave:02d}_{tag}.json")
    cmd = [sys.executable, os.path.abspath(__file__),
           "--child-wave", str(wave), "--child-result", result_path,
           "--frames", str(args.frames), "--warmup", str(args.warmup), "--seed", str(args.seed),
           "--size", args.size]
    profile_path = None
    if profiling:
        profile_path = os.path.join(tmp_dir, f"wave{wave:02d}_profile.pstats")
        cmd += ["--child-profile", profile_path, "--image-frames", ""]
    else:
        cmd += ["--image-frames", args.image_frames]
        if args.frame_dir:
            cmd += ["--frame-dir", os.path.abspath(args.frame_dir)]
    env = dict(os.environ)
    env.setdefault("PYTHONHASHSEED", "0")
    subprocess.run(cmd, check=True, cwd=ROOT, env=env)
    with open(result_path, "r", encoding="utf-8") as fh:
        result = json.load(fh)
    result["profile_path"] = profile_path
    return result


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.child_wave is not None:
        return _child_entry(args)
    if args.frames <= args.warmup:
        raise SystemExit("--frames must be larger than --warmup")
    out_path = os.path.abspath(args.out)
    compare_path = os.path.abspath(args.compare) if args.compare else None
    waves = _parse_int_list(args.waves)
    width, height = _parse_size(args.size)
    os.chdir(ROOT)
    timed = {}
    profile_rows = None
    replay_equal = None
    with tempfile.TemporaryDirectory() as tmp_dir:
        for wave in waves:
            timed[int(wave)] = _run_wave_process(args, int(wave), tmp_dir, profiling=False)
        if not args.no_profile:
            profile_sims = {}
            profile_paths = []
            for wave in waves:
                res = _run_wave_process(args, int(wave), tmp_dir, profiling=True)
                profile_sims[int(wave)] = res["sim_sha256"]
                profile_paths.append(res["profile_path"])
            profile_rows = _top_cumulative(pstats.Stats(*profile_paths), TOP_N)
            replay_equal = all(timed[int(w)]["sim_sha256"] == profile_sims[int(w)] for w in waves)

    wave_stats = _wave_stats(timed)
    report = {
        "bench": "tools/bench.py",
        "settings": {
            "seed": args.seed,
            "waves": list(waves),
            "frames_per_wave": args.frames,
            "warmup_frames": args.warmup,
            "window": [width, height],
            "fixed_dt_s": FIXED_DT,
            "fps": int(config.FPS),
            "shake_scale": float(config.SHAKE_SCALE),
            "particle_soft_cap": int(getattr(config, "PARTICLE_SOFT_CAP", 450)),
            "particle_hard_cap": int(getattr(config, "PARTICLE_HARD_CAP", 650)),
            "depth_bucket": int(visuals.DEPTH_BUCKET),
        },
        "environment": {
            "python": platform.python_version(),
            "pyglet": pyglet.version,
            "pyglet_debug_gl": bool(pyglet.options["debug_gl"]),
            "pythonhashseed": os.environ.get("PYTHONHASHSEED", "unset"),
            "platform": platform.platform(),
            "processor": platform.processor(),
        },
        "method": [
            "Real Game in a hidden window, windowed to settings.window. Each wave runs in its own fresh Python process (timed pass, then profile pass), seeded with seed + wave, so no state carries between waves.",
            "Wave forced to the listed number at run start and kept there (wave clears re-spawn the same wave).",
            "Scripted bot: fixed movement legs every FRAMES_PER_LEG frames, aim at nearest enemy, dash every DASH_EVERY frames, HP held at max.",
            "Per frame: time Game.update(1/60) then Game.on_draw() + glFinish(); no buffer swap. Bot and hashing run outside the timed spans.",
            "Statistics use frames at or after warmup_frames. Median is the headline number; p95 and max show spikes.",
            "Profile: an identical seeded run per wave in a separate process, with cProfile enabled only around update and draw; the per-wave profiles are merged and the top 15 functions by cumulative time are kept.",
            "Determinism: each wave's simulation SHA-256 from the timed process must equal the one from its profile process.",
            "Sequence ids: enemy/state modules use a per-run sequence id in place of id(), because enemy.py seeds formation_bias from id(enemy). Only the bench process is affected.",
            "Frame digests are SHA-256 of the RGBA framebuffer at the listed frames (same seed means identical pixels when nothing drawn changed).",
        ],
        "waves": wave_stats,
        "determinism": {
            "sim_sha256": {str(w): timed[w]["sim_sha256"] for w in waves},
            "profiled_replay_matches": replay_equal,
        },
        "frame_digests": [dict(d, wave=int(w)) for w in waves for d in timed[w]["frame_digests"]],
        "profile_top15_cumulative": profile_rows,
    }
    if compare_path:
        report["compare"] = _compare(report, compare_path)

    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
    print(f"Wrote {out_path}")
    _print_table(wave_stats)
    if replay_equal is not None:
        print(f"Profiled replay simulation matches timed pass: {replay_equal}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
