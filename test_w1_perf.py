"""Deterministic regression tests for the perf item: write-count guards, GL option, and the bench harness."""

import importlib.util
import json
import os
import sys
import tempfile

from game import Game  # first project import: game.py sets pyglet's GL options before pyglet.gl loads

import pyglet  # noqa: E402

from config import PYGLET_DEBUG_GL  # noqa: E402
from enemy import Enemy  # noqa: E402
from map import Room  # noqa: E402
from particles import ParticleSystem  # noqa: E402
from utils import Vec2  # noqa: E402
from visuals import GroupCache, Visuals  # noqa: E402

ROOT = os.path.dirname(os.path.abspath(__file__))


def _count_writes(shapes, method: str):
    """Count calls to one shape method (e.g. _update_color) by shadowing it on each instance.

    Returns (cell, stop). cell["n"] is the count. Call stop() to remove the shadows.
    """
    cell = {"n": 0}
    originals = {}
    for sh in shapes:
        original = getattr(sh, method)
        originals[id(sh)] = (sh, original)

        def counting(*args, _orig=original, **kwargs):
            cell["n"] += 1
            return _orig(*args, **kwargs)

        setattr(sh, method, counting)

    def stop():
        for sh, _orig in originals.values():
            if method in vars(sh):
                delattr(sh, method)

    return cell, stop


def test_gl_debug_option_is_off_by_default():
    assert PYGLET_DEBUG_GL is False, "config.PYGLET_DEBUG_GL should default to False"
    assert pyglet.options["debug_gl"] is False, "game.py must apply config.PYGLET_DEBUG_GL"
    lib = sys.modules.get("pyglet.gl.lib")
    assert lib is not None and lib._debug_gl is False, "pyglet.gl loaded before the option was applied"
    print("[PASS] test_gl_debug_option_is_off_by_default passed (debug_gl off before pyglet.gl loads)")


def test_particle_dots_write_only_what_changed():
    batch = pyglet.graphics.Batch()
    ps = ParticleSystem(batch)
    ps.emit(Vec2(10.0, -4.0), (255, 120, 40), count=12, speed=90.0, life=0.6, size=3.0)
    ps.emit(Vec2(-30.0, 22.0), (90, 200, 255), count=8, speed=60.0, life=0.4, size=2.0)
    ps.render(Vec2(0.0, 0.0))  # creates the pooled circles
    shapes = list(ps._shapes[: len(ps.particles)])
    assert len(shapes) == len(ps.particles) == 20

    # Colour and alpha must match what the particle asks for: RGB from the particle, alpha from its life.
    for sh, p in zip(shapes, ps.particles):
        expected_alpha = max(0, min(255, int(255 * max(0.0, p.life / p.max_life))))
        assert tuple(sh.color[:3]) == tuple(p.color), "dot colour drifted from the particle colour"
        assert sh.opacity == expected_alpha, "dot opacity drifted from the particle life"

    # Same state again: no colour or opacity write may happen, only one translation write per dot.
    colour, stop_colour = _count_writes(shapes, "_update_color")
    trans, stop_trans = _count_writes(shapes, "_update_translation")
    try:
        ps.render(Vec2(0.0, 0.0))
    finally:
        stop_colour()
        stop_trans()
    assert colour["n"] == 0, f"unchanged dots rewrote their colour buffer {colour['n']} times"
    assert trans["n"] == len(shapes), f"expected one translation write per dot, got {trans['n']}"

    # After one life step, each dot writes its colour buffer once, and only when its opacity moved.
    ps.update(0.05)
    colour, stop_colour = _count_writes(shapes, "_update_color")
    try:
        ps.render(Vec2(0.0, 0.0))
    finally:
        stop_colour()
    assert 0 < colour["n"] <= len(shapes), f"unexpected colour writes after a life step: {colour['n']}"
    print(f"[PASS] test_particle_dots_write_only_what_changed passed (idle frame: 0 colour writes; "
          f"after a life step: {colour['n']} of {len(shapes)} dots rewritten)")


def test_room_opacity_is_not_rewritten_when_static():
    batch = pyglet.graphics.Batch()
    room = Room(batch, 980, 620)
    room.update(0.0)
    room.update(0.0)  # settle: the decor tick alternates, so two calls cover both phases
    shapes = [ln for ln, _phase in room._boundary] + [o for o, *_ in room._ambient]
    shapes += [ln for ln, _b, _p in room._scanlines]
    shapes += [ln for ln, _b, _p in room._bg_grid]
    colour, stop = _count_writes(shapes, "_update_color")
    try:
        room.update(0.0)
        room.update(0.0)
        room.update(0.0)
        room.update(0.0)
    finally:
        stop()
    assert colour["n"] == 0, f"static room rewrote {colour['n']} shape colour buffers"

    # A moving clock must still change opacity (the guard must not freeze the animation).
    colour, stop = _count_writes(shapes, "_update_color")
    try:
        room.update(0.25)
        room.update(0.25)
    finally:
        stop()
    assert colour["n"] > 0, "animated room wrote no opacity at all"
    print(f"[PASS] test_room_opacity_is_not_rewritten_when_static passed (static: 0 writes; animated: {colour['n']} writes)")


def test_enemy_body_colour_is_not_rewritten_each_frame():
    batch = pyglet.graphics.Batch()
    vis = Visuals(batch, GroupCache())
    enemy = Enemy(pos=Vec2(40.0, -15.0), hp=30, speed=0.0, behavior="chaser")
    vis.ensure_enemy(enemy)
    vis.sync_enemy(enemy, Vec2(0.0, 0.0))
    body = vis._enemy_handles[id(enemy)].objs[1]
    colour, stop = _count_writes([body], "_update_color")
    try:
        vis.sync_enemy(enemy, Vec2(0.0, 0.0))
        vis.sync_enemy(enemy, Vec2(0.0, 0.0))
    finally:
        stop()
    assert colour["n"] == 0, f"an unchanged enemy body was rewritten {colour['n']} times"

    # Hit flash must still recolour the body to white, and clear back to the base colour.
    enemy.hit_flash_timer = 0.1
    vis.sync_enemy(enemy, Vec2(0.0, 0.0))
    assert tuple(body.color[:3]) == (255, 255, 255), "hit flash no longer whitens the body"
    enemy.hit_flash_timer = 0.0
    vis.sync_enemy(enemy, Vec2(0.0, 0.0))
    assert tuple(body.color[:3]) != (255, 255, 255), "body stayed white after the flash"
    print("[PASS] test_enemy_body_colour_is_not_rewritten_each_frame passed (idle body: 0 writes; flash still applies)")


def test_scripted_bot_is_deterministic():
    bench = _load_bench()
    g = Game()
    g.set_visible(False)
    try:
        bench._start_run(g, 1, 777)
        bot_a = bench.ScriptedBot(g)
        seq_a = []
        for f in range(200):
            bot_a.step(f)
            seq_a.append((tuple(sorted((k, bool(v)) for k, v in g.keys.data.items())), g.mouse_xy))
        bench._start_run(g, 1, 777)
        bot_b = bench.ScriptedBot(g)
        seq_b = []
        for f in range(200):
            bot_b.step(f)
            seq_b.append((tuple(sorted((k, bool(v)) for k, v in g.keys.data.items())), g.mouse_xy))
        assert seq_a == seq_b, "the scripted bot produced different inputs on the same frames"
    finally:
        g.close()
    print("[PASS] test_scripted_bot_is_deterministic passed (200 frames of identical bot input)")


def test_same_seed_replays_identically():
    bench = _load_bench()
    bench._install_sequence_ids()
    g = None
    try:
        g = bench._make_game(980, 620)
        first = bench._play(g, [15], 90, 5, 4242)
        second = bench._play(g, [15], 90, 5, 4242)
    finally:
        if g is not None:
            g.close()
        bench._uninstall_sequence_ids()
    assert first[15]["sim_sha256"] == second[15]["sim_sha256"], "same seed produced a different simulation"
    assert len(first[15]["update_ms"]) == 85, "warm-up frames leaked into the measured series"
    print("[PASS] test_same_seed_replays_identically passed (wave 15, 90 frames, identical simulation twice)")


def test_bench_writes_report_with_profile():
    bench = _load_bench()
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "report.json")
        rc = bench.main(["--out", out, "--waves", "1,8", "--frames", "40", "--warmup", "5", "--image-frames", "20"])
        assert rc == 0
        with open(out, "r", encoding="utf-8") as fh:
            report = json.load(fh)
    assert set(report["waves"].keys()) == {"1", "8"}
    for wave in ("1", "8"):
        w = report["waves"][wave]
        assert w["frames"] == 35
        assert w["update_ms"]["median"] > 0.0 and w["draw_ms"]["median"] > 0.0
        assert len(w["series_ms"]["update"]) == 35 and len(w["series_ms"]["draw"]) == 35
    assert len(report["profile_top15_cumulative"]) == 15, "profile must list the top 15 functions"
    assert report["determinism"]["profiled_replay_matches"] is True
    assert report["environment"]["pyglet_debug_gl"] is False
    assert all(len(d["sha256"]) == 64 for d in report["frame_digests"])
    print("[PASS] test_bench_writes_report_with_profile passed (JSON keys, 15 profiled functions, replay matched)")


_BENCH = None


def _load_bench():
    global _BENCH
    if _BENCH is None:
        spec = importlib.util.spec_from_file_location("bench_module", os.path.join(ROOT, "tools", "bench.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _BENCH = module
    return _BENCH


def run_all():
    # Shapes need a current GL context, so open a hidden window first, as the other test files do.
    g = Game()
    g.set_visible(False)
    try:
        test_gl_debug_option_is_off_by_default()
        test_particle_dots_write_only_what_changed()
        test_room_opacity_is_not_rewritten_when_static()
        test_enemy_body_colour_is_not_rewritten_each_frame()
        test_scripted_bot_is_deterministic()
        test_same_seed_replays_identically()
        test_bench_writes_report_with_profile()
    finally:
        g.close()
    print("\nALL WAVE 1 PERF TESTS PASSED")


if __name__ == "__main__":
    run_all()
