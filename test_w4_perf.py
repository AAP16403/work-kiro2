"""Wave 4 draw-path performance: visuals.py pooling, the scene-ring geometry cache and sync_scene's skipped writes.

Covers: the quantised radius rule; the scene-ring vertex cache writing exactly what pyglet's radius setter
writes; sync_scene leaving the same shape state as the original per-frame writes over a few hundred frames of
varied time, shake and combat intensity; an enemy or pickup handle taken from its pool matching a freshly built
one after the shape was used and released; a released handle drawing nothing; double release being rejected;
the pool cap falling back to an unpooled handle; steady-state spawns building no new shapes; and reduced motion
freezing the scene's drift.

Run with the venv python: ``python test_w4_perf.py``. Also collectable by pytest. Needs a GL context (a hidden
window is created).
"""

import os
import random
import sys
import traceback
from types import SimpleNamespace

import pyglet
from pyglet import shapes
from pyglet.graphics import Batch

import config
import motion
import visuals as V
from enemy import Enemy
from utils import Vec2, to_iso

ROOT = os.path.dirname(os.path.abspath(__file__))

_WINDOW = None


def _window():
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = pyglet.window.Window(width=320, height=240, visible=False)
    return _WINDOW


def _new_visuals(seed: int = 7):
    """A Visuals on its own batch. The seed fixes the star field, which Visuals draws from the module random."""
    _window()
    random.seed(seed)
    batch = Batch()
    return V.Visuals(batch, V.GroupCache())


def _verts(shape, name: str) -> list:
    return [float(v) for v in getattr(shape._vertex_list, name)[:]]


def _shape_state(shape) -> tuple:
    """Everything the GPU sees for one shape, plus the public attributes the sync code reads back.
    A text label keeps its glyphs in a layout rather than one vertex list, so it is compared by its public state."""
    if not hasattr(shape, "_vertex_list"):
        return (type(shape).__name__, round(float(shape.x), 9), round(float(shape.y), 9),
                shape.opacity, tuple(shape.color), bool(shape.visible), shape.text)
    radius = getattr(shape, "radius", None)
    return (
        type(shape).__name__,
        round(float(shape.x), 9), round(float(shape.y), 9),
        shape.opacity, tuple(shape.color),
        None if radius is None else round(float(radius), 9),
        bool(shape.visible),
        tuple(round(v, 6) for v in _verts(shape, "position")),
        tuple(_verts(shape, "colors")),
        tuple(round(v, 6) for v in _verts(shape, "translation")),
    )


# -------------------------------------------------------------------------------------------------
# Reference: the sync_scene of wave 4 base, written against the original per-frame setters.
# -------------------------------------------------------------------------------------------------

def _ref_set_radius(shape, value: float) -> None:
    value = float(value)
    quantised = round(value / V.RADIUS_STEP) * V.RADIUS_STEP
    if quantised <= 0.0 < value:
        quantised = V.RADIUS_STEP
    if getattr(shape, "_written_radius", None) == quantised:
        return
    shape._written_radius = quantised
    shape.radius = quantised


def _reference_sync_scene(vis, t: float, shake: Vec2, combat_intensity: float = 0.0) -> None:
    ta = motion.clock(t)
    drift = motion.factor()
    center_x, center_y = to_iso(Vec2(0.0, 0.0), shake)
    ci = max(0.0, min(1.0, float(combat_intensity)))
    offsets = ((-220.0, 120.0), (210.0, -60.0), (30.0, 190.0))
    import math
    for i, glow in enumerate(vis._scene_glows):
        ox, oy = offsets[i]
        glow.x = center_x + ox + math.sin(ta * (0.25 + i * 0.07)) * 30.0
        glow.y = center_y + oy + math.cos(ta * (0.22 + i * 0.09)) * 24.0
        glow.opacity = int((14 + i * 6) + (16 + i * 4) * (0.5 + 0.5 * math.sin(ta * (0.7 + i * 0.2))))
    for i, ring in enumerate(vis._scene_rings):
        ring.x = center_x
        ring.y = center_y
        _ref_set_radius(ring, (180 + i * 42) + 6.0 * math.sin(ta * (0.8 + i * 0.3)))
        ring.opacity = int(16 + 10 * i + (8 + 10 * ci) * (0.5 + 0.5 * math.sin(ta * (1.1 + i * 0.15))))
    for star, vx, vy, phase in vis._scene_stars:
        star.x += vx * (0.22 + ci * 0.6) * drift
        star.y += vy * (0.22 + ci * 0.6) * drift
        if star.x < -24:
            star.x = 1944
        elif star.x > 1944:
            star.x = -24
        if star.y < -24:
            star.y = 1104
        elif star.y > 1104:
            star.y = -24
        star.opacity = int(14 + 64 * (0.5 + 0.5 * math.sin(ta * 1.4 + phase)))
    top, bot, left, right = vis._vignette
    top.x, top.y, top.width, top.height = 0, 1048, 1920, 32
    bot.x, bot.y, bot.width, bot.height = 0, 0, 1920, 32
    left.x, left.y, left.width, left.height = 0, 0, 38, 1080
    right.x, right.y, right.width, right.height = 1882, 0, 38, 1080
    v_op = int(22 + 18 * ci)
    top.opacity = v_op
    bot.opacity = v_op
    left.opacity = int(v_op * 0.8)
    right.opacity = int(v_op * 0.8)


def _scene_state(vis) -> list:
    shapes_here = list(vis._scene_glows) + list(vis._scene_rings) + [s[0] for s in vis._scene_stars] + list(vis._vignette)
    return [_shape_state(s) for s in shapes_here]


# -------------------------------------------------------------------------------------------------
# Tests
# -------------------------------------------------------------------------------------------------

def test_quantise_radius_matches_the_original_rule():
    for value in (-3.0, -0.2, 0.0, 0.1, 0.24, 0.26, 1.0, 17.3, 180.0, 186.7, 221.25):
        q = V._quantise_radius(value)
        v = float(value)
        expect = round(v / V.RADIUS_STEP) * V.RADIUS_STEP
        if expect <= 0.0 < v:
            expect = V.RADIUS_STEP
        assert q == expect, (value, q, expect)


def test_scene_ring_cache_writes_what_the_radius_setter_writes():
    _window()
    ring_ref = shapes.Arc(0, 0, 180, segments=128, thickness=2, color=(130, 185, 245), batch=Batch())
    ring_new = shapes.Arc(0, 0, 180, segments=128, thickness=2, color=(130, 185, 245), batch=Batch())
    V._SCENE_RING_VERTS.clear()
    radii = [180.0, 186.2, 181.7, 180.3, 186.2, 174.0, 180.0, 179.9, 186.2, 180.0]
    for step, r in enumerate(radii * 2):
        _ref_set_radius(ring_ref, r)
        V._set_scene_ring_radius(ring_new, 0, r)
        assert _verts(ring_new, "position") == _verts(ring_ref, "position"), ("radius", r, step)
        assert ring_new.radius == ring_ref.radius
    # The cache holds one entry per distinct quantised radius for this ring index.
    assert len([k for k in V._SCENE_RING_VERTS if k[0] == 0]) == len({V._quantise_radius(r) for r in radii})


def test_sync_scene_matches_reference_over_frames():
    ref = _new_visuals(seed=11)
    new = _new_visuals(seed=11)
    shake_cases = [Vec2(0.0, 0.0), Vec2(3.0, -2.0), Vec2(0.0, 0.0), Vec2(-5.5, 1.25)]
    for frame in range(300):
        t = 2.0 + frame / 60.0
        shake = shake_cases[(frame // 60) % len(shake_cases)]
        ci = 0.0 if frame < 100 else (0.35 if frame < 200 else 1.0)
        _reference_sync_scene(ref, t, shake, ci)
        new.sync_scene(t, shake, combat_intensity=ci)
        if frame % 37 == 0 or frame == 299:
            assert _scene_state(new) == _scene_state(ref), f"scene state differs at frame {frame}"
    assert _scene_state(new) == _scene_state(ref)


def test_sync_scene_reduced_motion_freezes_drift():
    vis = _new_visuals(seed=3)
    old = config.REDUCE_MOTION
    try:
        config.REDUCE_MOTION = True
        vis.sync_scene(1.0, Vec2(0.0, 0.0), 0.5)
        before = [(s[0].x, s[0].y) for s in vis._scene_stars]
        rings = [r.radius for r in vis._scene_rings]
        vis.sync_scene(9.0, Vec2(0.0, 0.0), 0.5)
        assert before == [(s[0].x, s[0].y) for s in vis._scene_stars]
        assert rings == [r.radius for r in vis._scene_rings]
    finally:
        config.REDUCE_MOTION = old


def _with_pool(flag: str):
    """Run a test with one of visuals.POOL_*_HANDLES switched on (both are off by default, see visuals.py)."""
    def decorate(fn):
        def wrapper():
            old = getattr(V, flag)
            setattr(V, flag, True)
            try:
                fn()
            finally:
                setattr(V, flag, old)
        wrapper.__name__ = fn.__name__
        return wrapper
    return decorate


_with_enemy_pool = _with_pool("POOL_ENEMY_HANDLES")
_with_powerup_pool = _with_pool("POOL_POWERUP_HANDLES")


def test_pools_are_off_by_default_and_handles_are_deleted_on_drop():
    assert V.POOL_ENEMY_HANDLES is False and V.POOL_POWERUP_HANDLES is False
    vis = _new_visuals(seed=13)
    p = SimpleNamespace(pos=Vec2(0.0, 0.0), kind="heal")
    vis.ensure_powerup(p)
    assert vis._power_handles[id(p)].pool is None and not vis._handle_pools
    vis.drop_powerup(p)
    assert id(p) not in vis._power_handles
    vis = _new_visuals(seed=12)
    e = Enemy(pos=Vec2(0.0, 0.0), hp=10, speed=1.0, behavior="chaser", max_hp=10)
    vis.ensure_enemy(e)
    h = vis._enemy_handles[id(e)]
    assert h.pool is None and "enemy:chaser" not in vis._handle_pools
    vis.drop_enemy(e)
    assert id(e) not in vis._enemy_handles


def _enemy_state(vis, enemy) -> list:
    h = vis._enemy_handles[id(enemy)]
    return [_shape_state(o) for o in h.objs]


@_with_enemy_pool
def test_pooled_enemy_matches_fresh_handle():
    for behavior in ("chaser", "swarm", "charger", "ranged", "tank", "spitter", "flyer", "engineer", "bomber",
                     "egg_sac", "boss_thunder", "boss_laser", "boss_trapmaster", "boss_swarmqueen", "boss_brute",
                     "unlisted_kind"):
        pooled = _new_visuals(seed=5)
        fresh = _new_visuals(seed=5)
        first = Enemy(pos=Vec2(40.0, 10.0), hp=10, speed=1.0, behavior=behavior, max_hp=10)
        pooled.ensure_enemy(first)
        first.hit_flash_timer = 0.12  # a hit squash on the body, which the release must undo
        pooled.sync_enemy(first, Vec2(0.0, 0.0))
        pooled.drop_enemy(first)

        second_p = Enemy(pos=Vec2(-120.0, 75.0), hp=10, speed=1.0, behavior=behavior, max_hp=10)
        pooled.ensure_enemy(second_p)
        pooled.sync_enemy(second_p, Vec2(2.0, -1.0))
        assert pooled._handle_pools["enemy:" + behavior].created == 1, behavior

        second_f = Enemy(pos=Vec2(-120.0, 75.0), hp=10, speed=1.0, behavior=behavior, max_hp=10)
        fresh.ensure_enemy(second_f)
        fresh.sync_enemy(second_f, Vec2(2.0, -1.0))
        assert _enemy_state(pooled, second_p) == _enemy_state(fresh, second_f), behavior


@_with_powerup_pool
def test_pooled_powerup_matches_fresh_handle():
    for kind in ("heal", "laser", "drone", "unknown_kind"):
        pooled = _new_visuals(seed=9)
        fresh = _new_visuals(seed=9)
        first = SimpleNamespace(pos=Vec2(10.0, 4.0), kind=kind)
        pooled.ensure_powerup(first)
        pooled.sync_powerup(first, Vec2(0.0, 0.0))
        pooled.drop_powerup(first)

        p_pool = SimpleNamespace(pos=Vec2(-30.0, 22.0), kind=kind)
        p_fresh = SimpleNamespace(pos=Vec2(-30.0, 22.0), kind=kind)
        pooled.ensure_powerup(p_pool)
        pooled.sync_powerup(p_pool, Vec2(0.0, 0.0))
        fresh.ensure_powerup(p_fresh)
        fresh.sync_powerup(p_fresh, Vec2(0.0, 0.0))
        assert pooled._handle_pools["power:" + kind].created == 1
        hp = pooled._power_handles[id(p_pool)]
        hf = fresh._power_handles[id(p_fresh)]
        assert [_shape_state(o) for o in hp.objs[:5]] == [_shape_state(o) for o in hf.objs[:5]], kind
        assert [_shape_state(o) for o in hp.objs[5:]] == [_shape_state(o) for o in hf.objs[5:]], kind


@_with_enemy_pool
def test_released_handle_draws_nothing_and_double_release_is_rejected():
    vis = _new_visuals(seed=2)
    e = Enemy(pos=Vec2(0.0, 0.0), hp=10, speed=1.0, behavior="chaser", max_hp=10)
    vis.ensure_enemy(e)
    vis.sync_enemy(e, Vec2(0.0, 0.0))
    h = vis._enemy_handles[id(e)]
    vis.drop_enemy(e)
    assert all(o.opacity == 0 for o in h.objs), "a released handle must not draw"
    try:
        vis._give_back(h)
    except ValueError:
        pass
    else:
        raise AssertionError("second release of the same handle was accepted")


@_with_enemy_pool
def test_pool_cap_falls_back_to_an_unpooled_handle():
    vis = _new_visuals(seed=4)
    old_cap = V._POOL_CAP
    try:
        V._POOL_CAP = 1
        a = Enemy(pos=Vec2(0.0, 0.0), hp=10, speed=1.0, behavior="swarm", max_hp=10)
        b = Enemy(pos=Vec2(30.0, 0.0), hp=10, speed=1.0, behavior="swarm", max_hp=10)
        vis.ensure_enemy(a)
        vis.ensure_enemy(b)
        assert vis._enemy_handles[id(a)].pool is not None
        assert vis._enemy_handles[id(b)].pool is None
        vis.drop_enemy(b)  # unpooled: deleted, not released
        vis.drop_enemy(a)
        assert vis._handle_pools["enemy:swarm"].free_count == 1
    finally:
        V._POOL_CAP = old_cap


@_with_enemy_pool
def test_steady_spawns_build_no_new_shapes():
    vis = _new_visuals(seed=6)
    for behavior in ("tank", "boss_brute"):
        for _ in range(3):
            e = Enemy(pos=Vec2(0.0, 0.0), hp=10, speed=1.0, behavior=behavior, max_hp=10)
            vis.ensure_enemy(e)
            vis.sync_enemy(e, Vec2(0.0, 0.0))
            vis.drop_enemy(e)
        made = vis._handle_pools["enemy:" + behavior].created
        for _ in range(200):
            e = Enemy(pos=Vec2(0.0, 0.0), hp=10, speed=1.0, behavior=behavior, max_hp=10)
            vis.ensure_enemy(e)
            vis.sync_enemy(e, Vec2(0.0, 0.0))
            vis.drop_enemy(e)
        assert vis._handle_pools["enemy:" + behavior].created == made == 1, behavior


def test_visuals_adds_no_threads_or_parallel_imports():
    # The pool and cache are plain Python: no thread, no multiprocessing, no import of the parallel layer.
    src = open(os.path.join(ROOT, "visuals.py"), encoding="utf-8").read()
    for banned in ("import threading", "import multiprocessing", "import parallel", "from parallel"):
        assert banned not in src, banned


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for fn in tests:
        try:
            fn()
            print(f"PASS {fn.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {fn.__name__}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_run_all())
