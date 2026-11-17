"""Wave 4 enemy animation: visuals.py enemy functions.

Covers: spawn-in eases the body from SPAWN_FROM_SCALE to exactly its rest radius over SPAWN_TIME_S, and is
skipped under reduced motion; the idle bob differs per enemy type, and freezes under reduced motion; the
attack windup is read from each type's own timers and swells and tints the body, and holds a static pose
under reduced motion; the hit squash still springs back to the exact rest geometry, including after a
radius change, and is off under reduced motion; an idle enemy writes no radius or colour; the death dissolve
uses a capped pool of motes that are reused, is skipped under reduced motion, and draws no gameplay random
numbers; and no animation write changes the enemy's own state.

Run with the venv python: ``python test_w4_enemies.py``. Also collectable by pytest.
"""

import copy
import math
import random
import sys
import traceback

import game  # noqa: F401  first project import: game.py sets pyglet's GL options before pyglet.gl loads

import pyglet  # noqa: E402
from pyglet import shapes  # noqa: E402

import config  # noqa: E402
from config import ENEMY_COLORS  # noqa: E402
from enemy import Enemy  # noqa: E402
from enemy_behaviors.chase import LUNGE_WINDUP_S  # noqa: E402
from juice import HIT_SQUASH_TIME  # noqa: E402
from utils import Vec2  # noqa: E402
from visuals import (  # noqa: E402
    BRUTE_TELEGRAPH_S,
    DISSOLVE_CAP,
    LASER_CHARGE_S,
    SPAWN_FROM_SCALE,
    SPAWN_TIME_S,
    GroupCache,
    Visuals,
    _BOB,
    _BOB_DEFAULT,
    _body_positions,
    _idle_bob,
    _windup_strength,
)

NO_SHAKE = Vec2(0.0, 0.0)
FRAME = 1.0 / 60.0
_MISSING = object()
_WINDOW = None


def _setup():
    """A hidden window gives shapes a GL context. Returns a fresh Visuals and its batch."""
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = pyglet.window.Window(width=980, height=620, visible=False)
    batch = pyglet.graphics.Batch()
    return Visuals(batch, GroupCache()), batch


class _reduced:
    """Set config.REDUCE_MOTION for a block and restore it afterwards."""

    def __init__(self, value: bool):
        self.value = value

    def __enter__(self):
        self.prev = getattr(config, "REDUCE_MOTION", _MISSING)
        config.REDUCE_MOTION = self.value
        return self

    def __exit__(self, *exc):
        if self.prev is _MISSING:
            del config.REDUCE_MOTION
        else:
            config.REDUCE_MOTION = self.prev
        return False


def _enemy(behavior: str, t: float = 1.0, x: float = 40.0, y: float = -15.0, **kw) -> Enemy:
    e = Enemy(pos=Vec2(x, y), hp=30, speed=0.0, behavior=behavior, seed=1.0, **kw)
    e.t = t
    return e


def _body(vis, enemy):
    h = vis._enemy_handles[id(enemy)]
    return h.objs[4 if enemy.behavior.startswith("boss_") else 1]


def _rest_radius(behavior: str) -> float:
    """The body radius each type is built with (read from a fresh build, not hard-coded)."""
    vis, _ = _setup()
    e = _enemy(behavior)
    vis.ensure_enemy(e)
    return float(_body(vis, e).radius)


def _count_writes(shape_list, method: str):
    """Count calls to one shape method (e.g. _update_vertices) by shadowing it on each instance."""
    cell = {"n": 0}
    originals = []
    for sh in shape_list:
        original = getattr(sh, method)
        originals.append((sh, original))

        def counting(*args, _orig=original, **kwargs):
            cell["n"] += 1
            return _orig(*args, **kwargs)

        setattr(sh, method, counting)

    def stop():
        for sh, _orig in originals:
            if method in vars(sh):
                delattr(sh, method)

    return cell, stop


def _snapshot(enemy):
    return (
        enemy.pos.x, enemy.pos.y, enemy.hp, enemy.speed, enemy.t, enemy.attack_cd, enemy.vel.x, enemy.vel.y,
        enemy.seed, enemy.hit_flash_timer, enemy.is_elite, copy.deepcopy(enemy.ai),
    )


# ---------------------------------------------------------------- spawn-in

def test_spawn_eases_from_small_to_exact_rest_radius():
    with _reduced(False):
        vis, _ = _setup()
        e = _enemy("chaser", t=0.0)
        vis.ensure_enemy(e)
        body = _body(vis, e)
        rest = float(body.radius)
        radii = []
        for step in range(0, 33):
            e.t = SPAWN_TIME_S * step / 32.0
            vis.sync_enemy(e, NO_SHAKE)
            radii.append(float(body.radius))
        assert radii[0] < rest * 0.5, f"a new enemy must start small, got {radii[0]} against rest {rest}"
        assert radii[0] >= rest * SPAWN_FROM_SCALE - 0.6, f"spawn must start near SPAWN_FROM_SCALE, got {radii[0]}"
        assert radii[-1] == rest, f"spawn must finish on the exact rest radius {rest}, got {radii[-1]}"
        assert max(radii) > rest * 0.9, "the out_back ease should reach nearly full size before settling"
    print(f"[PASS] test_spawn_eases_from_small_to_exact_rest_radius passed (start {radii[0]} -> rest {rest})")


def test_spawn_is_skipped_under_reduced_motion():
    with _reduced(True):
        vis, _ = _setup()
        e = _enemy("chaser", t=0.0)
        vis.ensure_enemy(e)
        vis.sync_enemy(e, NO_SHAKE)
        body = _body(vis, e)
        assert float(body.radius) == float(vis._enemy_handles[id(e)].pose.body_r), "reduced motion must skip the spawn ease"
    print("[PASS] test_spawn_is_skipped_under_reduced_motion passed (rest radius at once)")


# ---------------------------------------------------------------- idle bob

def test_idle_bob_is_distinct_per_type():
    names = ("chaser", "charger", "flyer", "tank", "swarm", "bomber", "spitter", "ranged", "engineer", "egg_sac", "boss_brute")
    amps = {}
    for name in names:
        samples = [_idle_bob(name, k * 0.01) for k in range(0, 800)]
        amps[name] = round((max(samples) - min(samples)) / 2.0, 2)
    pairs = {name: _BOB[name] for name in names}
    assert len(set(pairs.values())) == len(names), f"each type needs its own (speed, amplitude) bob: {pairs}"
    assert len(set(amps.values())) >= 6, f"the bobs should visibly differ in amplitude too: {amps}"
    assert _BOB_DEFAULT == (6.0, 1.5), "the default bob is the original single bob"
    assert abs(_idle_bob("not_a_type", 0.3) - math.sin(0.3 * 6.0) * 1.5) < 1e-12, "unknown types keep the original bob"
    for name, (freq, amp) in _BOB.items():
        assert freq > 0.0 and amp > 0.0, f"{name} needs a positive frequency and amplitude"
    print(f"[PASS] test_idle_bob_is_distinct_per_type passed ({len(names)} types, {len(set(amps.values()))} amplitudes)")


def test_idle_bob_moves_the_body_and_freezes_under_reduced_motion():
    with _reduced(False):
        vis, _ = _setup()
        e = _enemy("swarm", t=1.0)
        vis.ensure_enemy(e)
        ys = []
        for k in range(30):
            e.t = 1.0 + k * FRAME
            vis.sync_enemy(e, NO_SHAKE)
            ys.append(float(_body(vis, e).y))
        assert max(ys) - min(ys) > 1.0, "the idle bob must move the body"
    with _reduced(True):
        vis, _ = _setup()
        e = _enemy("swarm", t=1.0)
        vis.ensure_enemy(e)
        still = []
        for k in range(30):
            e.t = 1.0 + k * FRAME
            vis.sync_enemy(e, NO_SHAKE)
            still.append(float(_body(vis, e).y))
        assert max(still) - min(still) < 1e-9, "reduced motion must hold the body still"
    print("[PASS] test_idle_bob_moves_the_body_and_freezes_under_reduced_motion passed")


# ---------------------------------------------------------------- windup

def test_windup_strength_reads_each_types_own_timers():
    cases = [
        ("chaser", {"lunge_windup": LUNGE_WINDUP_S}, 0.0, "chaser just locked its lunge"),
        ("chaser", {"lunge_windup": LUNGE_WINDUP_S * 0.5}, 0.5, "chaser halfway through its windup"),
        ("chaser", {"lunge_windup": 0.0}, 0.0, "chaser not winding up"),
        ("charger", {"state": "WINDUP", "state_timer": 0.25}, 0.5, "charger halfway through its windup"),
        ("charger", {"state": "CHARGING", "state_timer": 0.25}, 0.0, "charger dashing is not a windup"),
        ("flyer", {"state": "WINDUP", "state_timer": 0.0}, 1.0, "flyer at release"),
        ("boss_brute", {"brute_state": "telegraph", "brute_timer": BRUTE_TELEGRAPH_S * 0.5}, 0.5, "brute telegraph"),
        ("boss_laser", {"laser_state": "charge", "laser_timer": LASER_CHARGE_S * 0.25}, 0.75, "laser charge"),
        ("bomber", {"bomber_exploding": True}, 1.0, "bomber about to blast"),
    ]
    for behavior, ai, expected, why in cases:
        e = _enemy(behavior, t=1.0)
        e.ai = dict(ai)
        got = _windup_strength(e, behavior, e.ai)
        assert abs(got - expected) < 1e-9, f"{why}: expected {expected}, got {got}"
    e = _enemy("ranged", t=1.0)
    e.attack_cd = 0.15
    assert abs(_windup_strength(e, "ranged", e.ai) - 0.5) < 1e-9, "ranged inside its attack window must be half wound"
    e.attack_cd = 1.2
    assert _windup_strength(e, "ranged", e.ai) == 0.0, "ranged far from its shot has no windup"
    e.attack_cd = 0.0
    assert _windup_strength(e, "ranged", e.ai) == 0.0, "a shot that just fired is not a windup"
    print(f"[PASS] test_windup_strength_reads_each_types_own_timers passed ({len(cases) + 3} checks)")


def test_windup_swells_and_tints_the_body_then_returns_to_rest():
    with _reduced(False):
        vis, _ = _setup()
        base = ENEMY_COLORS["chaser"]
        calm = _enemy("chaser", t=1.0)
        vis.ensure_enemy(calm)
        vis.sync_enemy(calm, NO_SHAKE)
        rest = float(_body(vis, calm).radius)
        assert tuple(_body(vis, calm).color[:3]) == tuple(base), "an idle chaser keeps its base colour"

        wind = _enemy("chaser", t=1.0)
        wind.ai = {"lunge_windup": LUNGE_WINDUP_S * 0.2}
        vis.ensure_enemy(wind)
        peaks = []
        for k in range(20):
            wind.t = 1.0 + k * FRAME
            vis.sync_enemy(wind, NO_SHAKE)
            peaks.append((float(_body(vis, wind).radius), tuple(_body(vis, wind).color[:3])))
        assert max(r for r, _c in peaks) > rest, "a windup must swell the body past its rest radius"
        assert max(r for r, _c in peaks) <= rest * 1.2, "the swell is capped so the telegraph stays readable"
        assert any(c != tuple(base) for _r, c in peaks), "a windup must tint the body"
        wind.ai = {"lunge_windup": 0.0}
        vis.sync_enemy(wind, NO_SHAKE)
        assert float(_body(vis, wind).radius) == rest, "a finished windup returns the body to its rest radius"
        assert tuple(_body(vis, wind).color[:3]) == tuple(base), "a finished windup returns the base colour"
    print("[PASS] test_windup_swells_and_tints_the_body_then_returns_to_rest passed")


def test_windup_pose_is_static_under_reduced_motion_but_still_shown():
    with _reduced(True):
        vis, _ = _setup()
        base = ENEMY_COLORS["chaser"]
        e = _enemy("chaser", t=1.0)
        e.ai = {"lunge_windup": LUNGE_WINDUP_S * 0.5}
        vis.ensure_enemy(e)
        seen = set()
        for k in range(12):
            e.t = 1.0 + k * 0.05
            vis.sync_enemy(e, NO_SHAKE)
            body = _body(vis, e)
            seen.add((float(body.radius), tuple(body.color[:3])))
        assert len(seen) == 1, f"reduced motion must hold one static windup pose, saw {seen}"
        radius, colour = next(iter(seen))
        assert radius > float(vis._enemy_handles[id(e)].pose.body_r), "the static windup must still show the swell"
        assert colour != tuple(base), "the static windup must still show the warning tint"
    print("[PASS] test_windup_pose_is_static_under_reduced_motion_but_still_shown passed")


# ---------------------------------------------------------------- hit squash

def test_hit_squash_springs_back_to_exact_rest_after_spawn_and_radius_change():
    with _reduced(False):
        vis, batch = _setup()
        e = _enemy("chaser", t=1.0)
        vis.ensure_enemy(e)
        vis.sync_enemy(e, NO_SHAKE)
        body = _body(vis, e)
        rest_positions = tuple(body._vertex_list.position[:])

        e.hit_flash_timer = HIT_SQUASH_TIME
        vis.sync_enemy(e, NO_SHAKE)
        assert tuple(body._vertex_list.position[:]) != rest_positions, "a hit must squash the body"

        # A windup starts mid-squash: the radius changes, and the squash must follow the new radius.
        e.ai = {"lunge_windup": LUNGE_WINDUP_S * 0.5}
        vis.sync_enemy(e, NO_SHAKE)
        e.ai = {"lunge_windup": 0.0}
        frames = 0
        while e.hit_flash_timer > 0.0 and frames < 200:
            e.hit_flash_timer = max(0.0, e.hit_flash_timer - FRAME)
            vis.sync_enemy(e, NO_SHAKE)
            frames += 1
        vis.sync_enemy(e, NO_SHAKE)

        reference = shapes.Circle(0.0, 0.0, float(body.radius), segments=body._segments, batch=pyglet.graphics.Batch())
        assert tuple(body._vertex_list.position[:]) == tuple(reference._vertex_list.position[:]), \
            "after the squash the body must match a freshly built circle of its rest radius"
    print(f"[PASS] test_hit_squash_springs_back_to_exact_rest_after_spawn_and_radius_change passed (settled in {frames} frames)")


def test_hit_squash_is_off_under_reduced_motion():
    with _reduced(True):
        vis, _ = _setup()
        e = _enemy("chaser", t=1.0)
        vis.ensure_enemy(e)
        vis.sync_enemy(e, NO_SHAKE)
        body = _body(vis, e)
        rest_positions = tuple(body._vertex_list.position[:])
        e.hit_flash_timer = HIT_SQUASH_TIME
        vis.sync_enemy(e, NO_SHAKE)
        assert tuple(body._vertex_list.position[:]) == rest_positions, "reduced motion must not squash the body"
        assert tuple(body.color[:3]) == (255, 255, 255), "the white hit flash must still show"
    print("[PASS] test_hit_squash_is_off_under_reduced_motion passed (white flash kept, no squash)")


# ---------------------------------------------------------------- idle writes and gameplay isolation

def _body_lookups() -> int:
    info = _body_positions.cache_info()
    return info.hits + info.misses


def test_idle_enemy_writes_no_radius_or_colour_each_frame():
    with _reduced(False):
        vis, _ = _setup()
        e = _enemy("tank", t=1.0)
        vis.ensure_enemy(e)
        vis.sync_enemy(e, NO_SHAKE)
        body = _body(vis, e)
        radius_before = float(body.radius)
        lookups = _body_lookups()
        colour, stop = _count_writes([body], "_update_color")
        try:
            for _ in range(4):
                vis.sync_enemy(e, NO_SHAKE)
        finally:
            stop()
        assert _body_lookups() == lookups, "a settled enemy must not rebuild its body geometry"
        assert colour["n"] == 0, f"a settled body rewrote its colour {colour['n']} times"
        assert float(body.radius) == radius_before
    print("[PASS] test_idle_enemy_writes_no_radius_or_colour_each_frame passed (settled body: no geometry lookups, no colour writes)")


def test_animation_never_changes_enemy_state():
    vis, _ = _setup()
    with _reduced(False):
        kinds = [
            _enemy("chaser", t=0.0),
            _enemy("charger", t=0.6),
            _enemy("flyer", t=2.0),
            _enemy("boss_brute", t=3.0),
            _enemy("egg_sac", t=0.2),
        ]
        kinds[0].ai = {"lunge_windup": 0.1}
        kinds[1].ai = {"state": "WINDUP", "state_timer": 0.2}
        kinds[2].ai = {"state": "WINDUP", "state_timer": 0.1}
        kinds[3].ai = {"brute_state": "telegraph", "brute_timer": 0.4, "charge_dir_x": 1.0, "charge_dir_y": 0.0}
        kinds[4].ai = {"hatch_timer": 0.5}
        for e in kinds:
            e.hit_flash_timer = 0.05
            e.attack_cd = 0.2
            vis.ensure_enemy(e)
            before = _snapshot(e)
            for k in range(6):
                vis.sync_enemy(e, Vec2(3.0, -2.0))
            assert _snapshot(e) == before, f"{e.behavior}: a visual sync changed enemy state"
    print("[PASS] test_animation_never_changes_enemy_state passed (5 types, state identical after syncs)")


def test_egg_sac_body_follows_its_pulse_and_stays_still_when_reduced():
    with _reduced(False):
        vis, _ = _setup()
        e = _enemy("egg_sac", t=0.0, ai={"hatch_timer": 5.0})
        vis.ensure_enemy(e)
        radii = set()
        for k in range(40):
            e.t = 1.0 + k * 0.05
            vis.sync_enemy(e, NO_SHAKE)
            radii.add(float(_body(vis, e).radius))
        assert len(radii) > 3, "the egg sac's body must breathe"
        expected = max(0.1, 15 * (0.8 + 0.2 * math.sin(e.t * 8.0)))
        assert abs(float(_body(vis, e).radius) - expected) <= 0.5, "the body must match the egg pulse formula"
    with _reduced(True):
        vis, _ = _setup()
        e = _enemy("egg_sac", t=0.0, ai={"hatch_timer": 5.0})
        vis.ensure_enemy(e)
        radii = set()
        for k in range(20):
            e.t = 1.0 + k * 0.05
            vis.sync_enemy(e, NO_SHAKE)
            radii.add(float(_body(vis, e).radius))
        assert len(radii) == 1, f"reduced motion must hold the egg sac still, saw {radii}"
    print("[PASS] test_egg_sac_body_follows_its_pulse_and_stays_still_when_reduced passed")


# ---------------------------------------------------------------- death dissolve

def test_death_dissolve_spawns_pooled_motes_and_clears_them():
    with _reduced(False):
        vis, _ = _setup()
        e = _enemy("chaser", t=1.0)
        vis.ensure_enemy(e)
        vis.sync_enemy(e, NO_SHAKE)
        fx = vis._dissolve
        vis.drop_enemy(e)
        assert fx.pool.in_use == 8 and fx.live_count == 8, "a normal death starts 8 motes"
        assert vis._enemy_handles.get(id(e)) is None, "the handle is removed on death"
        assert fx._armed, "motes must be scheduled while alive"
        for _ in range(60):  # one second: longer than any mote's lifetime
            fx.tick(FRAME)
        assert fx.live_count == 0 and fx.pool.in_use == 0, "every mote must finish within its lifetime"
        assert not fx._armed, "the clock must be released once the motes are gone"
        assert fx.pool.free_count == fx.pool.created == 8, "finished motes return to the pool"
    print("[PASS] test_death_dissolve_spawns_pooled_motes_and_clears_them passed (8 motes, all returned)")


def test_death_dissolve_is_capped_and_reuses_motes():
    with _reduced(False):
        vis, _ = _setup()
        fx = vis._dissolve
        enemies = [_enemy("tank", t=1.0, x=float(i) * 7.0, y=float(i % 9) * 5.0) for i in range(30)]
        for e in enemies:
            vis.ensure_enemy(e)
            vis.sync_enemy(e, NO_SHAKE)
        for e in enemies:
            vis.drop_enemy(e)
        assert fx.pool.in_use <= DISSOLVE_CAP, "motes must never exceed the cap"
        assert fx.pool.created == DISSOLVE_CAP, f"30 deaths should fill the pool to its cap, created {fx.pool.created}"
        for _ in range(60):
            fx.tick(FRAME)
        assert fx.pool.in_use == 0 and fx.pool.created == DISSOLVE_CAP

        again = [_enemy("chaser", t=1.0, x=float(i) * 11.0) for i in range(12)]
        for e in again:
            vis.ensure_enemy(e)
            vis.sync_enemy(e, NO_SHAKE)
            vis.drop_enemy(e)
        assert fx.pool.created == DISSOLVE_CAP, "a second wave must reuse motes, not create shapes"
        for _ in range(60):
            fx.tick(FRAME)
    print(f"[PASS] test_death_dissolve_is_capped_and_reuses_motes passed (cap {DISSOLVE_CAP}, no new shapes after warm-up)")


def test_death_dissolve_is_skipped_under_reduced_motion():
    with _reduced(True):
        vis, _ = _setup()
        e = _enemy("boss_brute", t=1.0)
        vis.ensure_enemy(e)
        vis.sync_enemy(e, NO_SHAKE)
        vis.drop_enemy(e)
        assert vis._dissolve.pool.created == 0 and vis._dissolve.live_count == 0, "reduced motion must not burst motes"
    print("[PASS] test_death_dissolve_is_skipped_under_reduced_motion passed")


def test_death_dissolve_does_not_touch_the_gameplay_random_stream():
    with _reduced(False):
        vis, _ = _setup()
        e = _enemy("boss_laser", t=1.0)
        vis.ensure_enemy(e)
        vis.sync_enemy(e, NO_SHAKE)
        random.seed(4242)
        before = random.getstate()
        vis.drop_enemy(e)
        for _ in range(5):
            vis._dissolve.tick(FRAME)
        after = random.getstate()
        assert before == after, "the dissolve must use its own RNG, never the global one the simulation reads"
    print("[PASS] test_death_dissolve_does_not_touch_the_gameplay_random_stream passed")


def test_death_motes_start_at_the_body_and_fade_out():
    with _reduced(False):
        vis, _ = _setup()
        e = _enemy("swarm", t=1.0, x=120.0, y=30.0)
        vis.ensure_enemy(e)
        vis.sync_enemy(e, NO_SHAKE)
        pose = vis._enemy_handles[id(e)].pose
        vis.drop_enemy(e)
        fx = vis._dissolve
        motes = list(fx._live)
        assert motes, "a death must produce motes"
        for m in motes:
            assert abs(m.x - pose.cx) <= pose.reach + 1.0 and abs(m.y - pose.cy) <= pose.reach + 1.0, "motes start within the body"
        fx.tick(0.02)
        first = int(motes[0].shape.opacity)
        for _ in range(8):
            fx.tick(FRAME)
        later = int(motes[0].shape.opacity) if motes[0] in fx._live else 0
        assert first > later, "motes must fade as they age"
    print("[PASS] test_death_motes_start_at_the_body_and_fade_out passed")


def test_drop_without_a_pose_or_handle_is_safe():
    vis, _ = _setup()
    e = _enemy("chaser", t=1.0)
    vis.drop_enemy(e)  # never built: no handle, no motes, no error
    assert vis._dissolve.live_count == 0
    print("[PASS] test_drop_without_a_pose_or_handle_is_safe passed")


def run_all():
    tests = [(name, fn) for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:
            failed += 1
            print("FAIL %s" % name)
            traceback.print_exc()
    print("%d passed, %d failed" % (len(tests) - failed, failed))
    return 1 if failed else 0


if __name__ == "__main__":
    code = run_all()
    if code == 0:
        print("ALL WAVE 4 ENEMY ANIMATION TESTS PASSED")
    sys.exit(code)
