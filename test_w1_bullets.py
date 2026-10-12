"""Wave 1 bullets: per-weapon projectile looks, trails, impacts, and the enemy and crit variants.

Deterministic checks. The style table is checked directly, the visuals are checked through the real
Visuals object, and the hit effects run on a real ParticleSystem. Physics and hit results are covered
by test_mechanics.py, and one test here proves the weapon tag does not change a hit.
"""

import math
import random

import config
from enemy import Enemy
from game import Game
from particles import ParticleSystem
from projectile import Projectile, spawn_projectiles
from projectile_art import (
    BASIC_STYLE,
    ENEMY_HEAD,
    ENEMY_TRAIL,
    GOLD_TRAIL,
    WEAPON_STYLES,
    ProjectileVisual,
    _IMPACTS,
    _TRAILS,
    flak_detonation,
    spawn_impact,
    style_for,
    style_for_projectile,
    trail_length,
)
from states import GameStateName
from utils import Vec2, to_iso
from weapons import WEAPONS


ENEMY_TYPES = ("bullet", "spread", "plasma", "bomb")


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Same stepping as test_polish.py: call update() directly so real clock time never double-steps.
    for _ in range(frames):
        g.dispatch_events()
        g.update(1.0 / 60.0)


def _is_red_orange(rgb) -> bool:
    r, gc, b = rgb[0], rgb[1], rgb[2]
    return r >= 200 and 40 <= gc <= 120 and b <= 80


def _piece_xy(shape):
    """Far end of a line, or the centre of a disc or arc."""
    if hasattr(shape, "x2"):
        return shape.x2, shape.y2
    return shape.x, shape.y


def _trail_first(vis, proj):
    """First trail piece of a projectile, or None for a trail-less style."""
    h = vis._proj_handles[id(proj)]
    return h.objs[0] if len(h.objs) > 3 else None


def _rgb(shape):
    return tuple(int(c) for c in shape.color[:3])


# ---- style table ------------------------------------------------------------------------------

def test_style_table_covers_every_weapon():
    assert set(WEAPON_STYLES) == {w.name for w in WEAPONS.values()}, "style table must name every weapon exactly"
    heads, trails, impacts = set(), set(), set()
    for name, st in WEAPON_STYLES.items():
        assert st.label == name, f"{name}: label mismatch"
        assert st.radius > 0.0 and st.length > 0.0, f"{name}: size and trail length must be positive"
        assert st.trail in _TRAILS, f"{name}: unknown trail painter {st.trail!r}"
        assert st.impact in _IMPACTS, f"{name}: unknown impact recipe {st.impact!r}"
        for rgb in (st.head, st.core, st.trail_color):
            assert len(rgb) == 3 and all(0 <= c <= 255 for c in rgb), f"{name}: colour out of range {rgb}"
        heads.add(st.head)
        trails.add(st.trail)
        impacts.add(st.impact)
    assert len(heads) == 7, "every weapon needs its own body colour"
    assert len(trails) == 7, "every weapon needs its own trail shape"
    assert len(impacts) == 7, "every weapon needs its own hit effect"
    print("[PASS] test_style_table_covers_every_weapon passed (7 weapons, 7 distinct heads, trails and impacts)")


def test_style_lookup_by_weapon_name():
    for weapon in WEAPONS.values():
        assert style_for(weapon.name, weapon.projectile_type) is WEAPON_STYLES[weapon.name], f"{weapon.name} lookup"
        assert style_for(weapon.name, "bullet") is WEAPON_STYLES[weapon.name], "the weapon name wins over the type"
    assert style_for("Basic Gun") is BASIC_STYLE
    assert style_for("Rapid Fire", "bullet") is WEAPON_STYLES["Rapid Fire"], "basic and rapid share a type, so the name must decide"
    print("[PASS] test_style_lookup_by_weapon_name passed (every weapon name resolves to its own style)")


def test_unknown_weapon_falls_back_to_basic():
    assert style_for("Mystery Gun") is BASIC_STYLE, "unknown weapon name must fall back to the basic style"
    assert style_for("") is BASIC_STYLE, "empty name with the default type must be basic"
    assert style_for(None) is BASIC_STYLE, "a missing name must be basic"
    assert style_for("Mystery Gun", "bullet") is BASIC_STYLE, "unknown name with bullet type must be basic"
    assert style_for("Mystery Gun", "laser") is BASIC_STYLE, "unknown type must be basic"
    print("[PASS] test_unknown_weapon_falls_back_to_basic passed (unknown name and unknown type give the basic style)")


def test_untagged_shots_use_projectile_type():
    assert style_for("", "plasma") is WEAPON_STYLES["Plasma Rifle"], "enemy plasma shots use the plasma look"
    assert style_for("", "spread") is WEAPON_STYLES["Spread Shot"]
    assert style_for("", "railgun") is WEAPON_STYLES["Hyper Railgun"]
    assert style_for("", "flak") is WEAPON_STYLES["Flak Battery"], "flak shrapnel and shells share the flak look by type"
    assert style_for("", "missile") is WEAPON_STYLES["Heavy Cannon"]
    assert style_for("", "bomb").trail == "none", "the enemy bomb keeps its trail-less casing"
    print("[PASS] test_untagged_shots_use_projectile_type passed (no name: the projectile type picks the style)")


def test_spawn_tags_weapon_name_and_is_deterministic():
    for key, weapon in WEAPONS.items():
        first = spawn_projectiles(Vec2(10.0, 4.0), Vec2(1.0, 0.0), weapon, 0.0, 10, recoil_deg=2.0, rng=random.Random(7))
        second = spawn_projectiles(Vec2(10.0, 4.0), Vec2(1.0, 0.0), weapon, 0.0, 10, recoil_deg=2.0, rng=random.Random(7))
        assert first, f"{key} fired nothing"
        assert len(first) == len(second), f"{key} shot count changed between identical seeds"
        for a, b in zip(first, second):
            assert all(getattr(a, f) == getattr(b, f) for f in ("pos", "vel", "damage", "ttl", "owner", "projectile_type", "pierce", "is_crit")), f"{key} physics changed"
            assert a.weapon_name == weapon.name, f"{key} shot is not tagged with its weapon name"
    print("[PASS] test_spawn_tags_weapon_name_and_is_deterministic passed (every shot tagged, physics identical for one seed)")


def test_crit_and_enemy_variants_in_style_table():
    for name, st in WEAPON_STYLES.items():
        gap = math.sqrt(sum((st.trail_color[i] - GOLD_TRAIL[i]) ** 2 for i in range(3)))
        assert gap >= 60.0, f"{name}: normal trail is too close to the crit gold to read as a variant ({gap:.0f})"
    for weapon in WEAPONS.values():
        crit = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, weapon_name=weapon.name,
                          projectile_type=weapon.projectile_type, is_crit=True)
        st = style_for_projectile(crit)
        assert st.trail_color == GOLD_TRAIL, f"{weapon.name} crit must trail gold"
        plain = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, weapon_name=weapon.name,
                           projectile_type=weapon.projectile_type)
        assert style_for_projectile(plain) is WEAPON_STYLES[weapon.name], "a plain shot keeps its own style"
        assert not _is_red_orange(WEAPON_STYLES[weapon.name].head), f"{weapon.name} body must not read as an enemy shot"
        assert not _is_red_orange(WEAPON_STYLES[weapon.name].trail_color), f"{weapon.name} trail must not read as an enemy shot"
    for ptype in ENEMY_TYPES:
        shot = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(200.0, 0.0), damage=8, owner="enemy", projectile_type=ptype)
        st = style_for_projectile(shot)
        assert st.head == ENEMY_HEAD and st.trail_color == ENEMY_TRAIL, f"enemy {ptype} must be red-orange"
        assert _is_red_orange(st.head) and _is_red_orange(st.trail_color), f"enemy {ptype} colours are not red-orange"
    print("[PASS] test_crit_and_enemy_variants_in_style_table passed (gold crit trail, red-orange enemy shots, player shots stay off red-orange)")


# ---- visuals ----------------------------------------------------------------------------------

def _sample_shots():
    shots = []
    for weapon in WEAPONS.values():
        shots.append(Projectile(pos=Vec2(30.0, -12.0), vel=Vec2(300.0, 40.0), damage=12, ttl=3.0,
                                weapon_name=weapon.name, projectile_type=weapon.projectile_type))
        shots.append(Projectile(pos=Vec2(30.0, -12.0), vel=Vec2(300.0, 40.0), damage=12, ttl=3.0,
                                weapon_name=weapon.name, projectile_type=weapon.projectile_type, is_crit=True))
    for ptype in ENEMY_TYPES:
        shots.append(Projectile(pos=Vec2(-40.0, 20.0), vel=Vec2(-160.0, 60.0), damage=8, ttl=3.0,
                                owner="enemy", projectile_type=ptype))
    shots.append(Projectile(pos=Vec2(5.0, 5.0), vel=Vec2(0.0, 0.0), damage=6, ttl=2.0, projectile_type="bullet"))
    return shots


def test_every_style_builds_in_projectile_group(g):
    _new_run(g)
    vis = g.visuals
    shots = _sample_shots()
    for p in shots:
        vis.ensure_projectile(p)
    total = 0
    for p in shots:
        h = vis._proj_handles[id(p)]
        assert isinstance(h, ProjectileVisual), "ensure_projectile must build a ProjectileVisual"
        assert len(h.objs) >= 3, "a shot needs at least body, core and flare"
        assert h.objs[-3] is h._body, "body disc must stay third from the end"
        for o in h.objs:
            total += 1
            assert o.group is vis._projectile_group, f"{p.weapon_name or p.projectile_type} piece not in the projectile group"
    print(f"[PASS] test_every_style_builds_in_projectile_group passed ({len(shots)} shots, {total} pieces, all in the projectile group)")


def test_visuals_animate_for_every_style(g):
    _new_run(g)
    vis = g.visuals
    shake = Vec2(4.0, -6.0)
    shots = _sample_shots()
    for p in shots:
        vis.ensure_projectile(p)
    for frame in range(120):
        for p in shots:
            p.update(1.0 / 60.0)
            vis.sync_projectile(p, shake)
            h = vis._proj_handles[id(p)]
            sx, sy = to_iso(p.pos, shake)
            assert abs(h._body.x - sx) < 1e-6 and abs(h._body.y - sy) < 1e-6, f"frame {frame}: body drawn off its shaken position"
            for o in h.objs:
                assert 0 <= int(o.opacity) <= 255, f"frame {frame}: opacity out of range"
    print(f"[PASS] test_visuals_animate_for_every_style passed (120 frames, {len(shots)} shots, positions follow shake, opacity in range)")


def test_visuals_are_visual_only(g):
    _new_run(g)
    vis = g.visuals
    for p in _sample_shots():
        vis.ensure_projectile(p)
        h = vis._proj_handles[id(p)]
        before = (p.pos.x, p.pos.y, p.vel.x, p.vel.y, p.ttl, p.damage, p.pierce, p.is_crit, p.owner)
        radii = [float(o.radius) for o in h.objs if hasattr(o, "radius")]
        for frame in range(30):
            vis.sync_projectile(p, Vec2(0.0, 0.0))
        after = (p.pos.x, p.pos.y, p.vel.x, p.vel.y, p.ttl, p.damage, p.pierce, p.is_crit, p.owner)
        assert before == after, "sync must not change projectile state"
        assert radii == [float(o.radius) for o in h.objs if hasattr(o, "radius")], "sync must not rebuild geometry"
    print("[PASS] test_visuals_are_visual_only passed (sync leaves physics, damage and hit flags alone, radii never change)")


def test_trail_points_back_along_flight(g):
    _new_run(g)
    vis = g.visuals
    # World +x is screen (0.7, 0.35) under the iso projection, so the back direction is its negative.
    fx, fy = config.ISO_SCALE_X, config.ISO_SCALE_Y
    n = math.hypot(fx, fy)
    bx, by = -fx / n, -fy / n
    for name in ("Basic Gun", "Spread Shot", "Rapid Fire", "Heavy Cannon", "Plasma Rifle", "Hyper Railgun", "Flak Battery"):
        weapon = next(w for w in WEAPONS.values() if w.name == name)
        p = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, ttl=3.0,
                       weapon_name=name, projectile_type=weapon.projectile_type)
        vis.ensure_projectile(p)
        vis.sync_projectile(p, Vec2(0.0, 0.0))
        h = vis._proj_handles[id(p)]
        hx, hy = to_iso(p.pos, Vec2(0.0, 0.0))
        checked = 0
        for piece in h.objs[:-3]:
            px, py = _piece_xy(piece)
            d = math.hypot(px - hx, py - hy)
            if d <= 8.0:
                continue  # pieces at the head (halo) or a few px from it carry no direction
            cos = ((px - hx) * bx + (py - hy) * by) / d
            assert cos > 0.85, f"{name}: trail piece sits off the flight path (cos={cos:.2f})"
            checked += 1
        assert checked > 0, f"{name}: no trail piece lies behind the head"
    print("[PASS] test_trail_points_back_along_flight passed (every trail piece lies behind the head along the iso flight path)")


def test_crit_trail_is_gold_and_enemy_is_red_orange(g):
    _new_run(g)
    vis = g.visuals
    for weapon in WEAPONS.values():
        crit = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, ttl=3.0,
                          weapon_name=weapon.name, projectile_type=weapon.projectile_type, is_crit=True)
        vis.ensure_projectile(crit)
        trail = _trail_first(vis, crit)
        assert trail is not None, f"{weapon.name} crit must keep a trail"
        assert _rgb(trail) == GOLD_TRAIL, f"{weapon.name} crit trail is {_rgb(trail)}, expected gold"
    for ptype in ("bullet", "spread", "plasma"):
        shot = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(200.0, 0.0), damage=8, ttl=3.0, owner="enemy", projectile_type=ptype)
        vis.ensure_projectile(shot)
        h = vis._proj_handles[id(shot)]
        assert _rgb(h._body) == ENEMY_HEAD, f"enemy {ptype} body is not red-orange"
    print("[PASS] test_crit_trail_is_gold_and_enemy_is_red_orange passed (crit trails are gold, enemy bodies are red-orange)")


def test_flak_detonation_bursts_visibly(g):
    ps = ParticleSystem()
    before = len(ps.particles)
    flak_detonation(ps, Vec2(0.0, 0.0))
    added = ps.particles[before:]
    assert len(added) > 0, "flak detonation must spawn particles"
    assert any(p.kind == "ring" for p in added), "flak detonation must include the amber ring"
    assert len(added) >= 18, "flak detonation keeps the existing shrapnel burst"
    print(f"[PASS] test_flak_detonation_bursts_visibly passed ({len(added)} new particles, ring included)")


def test_impacts_spawn_existing_particle_kinds(g):
    basic = ParticleSystem()
    spawn_impact(basic, Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, weapon_name="Basic Gun"),
                 Vec2(0.0, 0.0), (255, 0, 0))
    assert len(basic.particles) == 4, "the basic impact must be exactly the existing hit burst"
    for name, st in WEAPON_STYLES.items():
        ps = ParticleSystem()
        proj = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, weapon_name=name)
        spawn_impact(ps, proj, Vec2(0.0, 0.0), (120, 200, 90))
        assert len(ps.particles) > 0, f"{name} impact spawned nothing"
        assert all(p.kind in ("dot", "ring", "glow") for p in ps.particles), f"{name} impact used an unknown particle kind"
    print("[PASS] test_impacts_spawn_existing_particle_kinds passed (basic impact equals the hit burst, every weapon has an effect)")


def test_impacts_respect_particle_cap(g):
    ps = ParticleSystem()
    proj = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, weapon_name="Heavy Cannon")
    for _ in range(400):
        spawn_impact(ps, proj, Vec2(0.0, 0.0), (120, 200, 90))
    assert len(ps.particles) <= int(config.PARTICLE_HARD_CAP), "impacts must respect the particle hard cap"
    print(f"[PASS] test_impacts_respect_particle_cap passed ({len(ps.particles)} particles after 400 heavy impacts)")


def test_trail_length_grows_only_slightly_with_speed():
    st = WEAPON_STYLES["Basic Gun"]
    assert trail_length(st, 0.0) == st.length
    assert st.length < trail_length(st, 360.0) <= st.length + 8.0, "speed bonus must stay small"
    assert trail_length(st, 1e6) == st.length + 8.0, "speed bonus must be capped"
    print("[PASS] test_trail_length_grows_only_slightly_with_speed passed (speed bonus is small and capped)")


def test_weapon_tag_does_not_change_the_hit(g):
    def outcome(weapon_name, projectile_type):
        random.seed(20260612)
        s = _new_run(g)
        enemy = Enemy(pos=Vec2(120.0, 0.0), hp=60, speed=0.0, behavior="chaser")
        s.enemies = [enemy]
        s.wave_active = True
        shot = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(340.0, 0.0), damage=12, ttl=2.0,
                          owner="player", projectile_type=projectile_type, weapon_name=weapon_name)
        s.projectiles = [shot]
        _tick(g, 40)
        return (enemy.hp, len(s.enemies), len(s.projectiles), round(shot.pos.x, 6), round(shot.ttl, 6))

    for ptype in ("bullet", "railgun"):
        untagged = outcome("", ptype)
        tagged = outcome("Hyper Railgun" if ptype == "railgun" else "Rapid Fire", ptype)
        assert untagged[0] < 60, f"the {ptype} scenario must actually hit the enemy (hp {untagged[0]})"
        assert untagged == tagged, f"weapon tag changed the {ptype} hit: {untagged} vs {tagged}"
    print("[PASS] test_weapon_tag_does_not_change_the_hit passed (hit, hp and motion identical with and without the tag)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_every_style_builds_in_projectile_group(g)
        test_visuals_animate_for_every_style(g)
        test_visuals_are_visual_only(g)
        test_trail_points_back_along_flight(g)
        test_crit_trail_is_gold_and_enemy_is_red_orange(g)
        test_flak_detonation_bursts_visibly(g)
        test_impacts_spawn_existing_particle_kinds(g)
        test_impacts_respect_particle_cap(g)
        test_weapon_tag_does_not_change_the_hit(g)
    finally:
        g.close()
    test_style_table_covers_every_weapon()
    test_style_lookup_by_weapon_name()
    test_unknown_weapon_falls_back_to_basic()
    test_untagged_shots_use_projectile_type()
    test_spawn_tags_weapon_name_and_is_deterministic()
    test_crit_and_enemy_variants_in_style_table()
    test_trail_length_grows_only_slightly_with_speed()
    print("\nALL WAVE 1 BULLETS TESTS PASSED")


if __name__ == "__main__":
    run_all()
