"""Regression tests for the wave-1 graphics pass: glow pool, parallax starfield, dash afterimage, rim pulse and switches."""

import random

import pyglet
from pyglet.gl import GL_ONE, GL_SRC_ALPHA

import config
import glow
import states
from enemy import Enemy
from game import Game
from glow import DashAfterimage, GlowPool, glow_texture, projectile_glow
from level import spawn_wave
from map import Room
from player import perform_dash
from projectile import Projectile
from starfield import LAYERS, Starfield
from states import GameStateName
from utils import Vec2
from visuals import _EYE_SLOTS, _GENERIC_EYE_SLOTS, _eye_slots

DT = 1.0 / 60.0
FX_FLAGS = ("ENABLE_GLOW", "ENABLE_PARALLAX_STARS", "ENABLE_DASH_AFTERIMAGE", "ENABLE_RIM_PULSE")


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Call update() directly: pyglet.clock.tick() would also fire the game's scheduled
    # update with real elapsed time and double-step the simulation.
    for _ in range(frames):
        g.dispatch_events()
        g.update(DT)


def _set_flags(**values):
    old = {name: getattr(config, name) for name in values}
    for name, value in values.items():
        setattr(config, name, value)
    return old


def _restore_flags(old):
    for name, value in old.items():
        setattr(config, name, value)


def _projectile(pos, kind="bullet", owner="player", crit=False):
    return Projectile(pos=pos, vel=Vec2(60.0, 0.0), damage=10, owner=owner, projectile_type=kind, is_crit=crit)


def test_glow_texture_is_built_once(g):
    first = glow_texture()
    assert glow_texture() is first, "glow texture must be generated once and reused"
    assert first.width == glow.GLOW_TEXTURE_SIZE and first.height == glow.GLOW_TEXTURE_SIZE
    print("[PASS] test_glow_texture_is_built_once passed (one shared %dpx texture)" % glow.GLOW_TEXTURE_SIZE)


def test_glow_pool_never_grows_past_cap(g):
    _new_run(g)  # a GL context and a batch are needed for the pool
    batch = pyglet.graphics.Batch()
    pool = GlowPool(batch, cap=8, order=14500)
    for frame in range(3):
        pool.begin_frame()
        accepted = sum(1 for i in range(20) if pool.emit(("k", frame, i), float(i), 0.0, 6.0, (255, 255, 255), 200))
        pool.end_frame()
        assert accepted == 8, f"frame {frame}: pool accepted {accepted} glows with cap 8"
        assert pool.sprite_count <= 8, f"pool grew to {pool.sprite_count} quads with cap 8"
    print("[PASS] test_glow_pool_never_grows_past_cap passed (8 quads max, extra glows skipped)")


def test_glow_pool_keeps_a_key_on_its_quad(g):
    _new_run(g)
    batch = pyglet.graphics.Batch()
    pool = GlowPool(batch, cap=4, order=14500)
    pool.begin_frame()
    assert pool.emit("owner", 10.0, 10.0, 6.0, (120, 200, 255), 150)
    slot_first = pool._current["owner"]
    pool.end_frame()
    pool.begin_frame()
    assert pool.emit("owner", 14.0, 9.0, 6.0, (120, 200, 255), 150)
    assert pool._current["owner"] == slot_first, "a glow that keeps its key must keep its quad"
    pool.end_frame()
    assert pool.sprite_count == 1, f"steady glow allocated {pool.sprite_count} quads"
    print("[PASS] test_glow_pool_keeps_a_key_on_its_quad passed (one quad for one live owner)")


def test_hidden_glows_do_not_draw(g):
    _new_run(g)
    batch = pyglet.graphics.Batch()
    pool = GlowPool(batch, cap=8, order=14500)
    bank = pool._bank

    pool.begin_frame()
    for i in range(3):
        pool.emit(("a", i), float(i * 20), 0.0, 6.0, (255, 255, 255), 200)
    pool.end_frame()
    assert pool.visible_count() == 3, f"expected 3 visible glows, got {pool.visible_count()}"

    pool.begin_frame()
    pool.emit(("a", 1), 20.0, 0.0, 6.0, (255, 255, 255), 200)
    pool.end_frame()
    assert pool.visible_count() == 1, f"unclaimed glows must be hidden, {pool.visible_count()} still shown"
    hidden = [slot for slot in range(pool.sprite_count) if slot != pool._shown[("a", 1)]]
    for slot in hidden:
        assert all(v == 0.0 for v in bank._scale[8 * slot:8 * slot + 8]), "a hidden glow must have zero scale"

    pool.begin_frame()
    pool.end_frame()
    assert pool.visible_count() == 0, "a frame with no glows must leave nothing visible"
    assert all(v == 0.0 for v in bank._scale[:8 * pool.sprite_count]), "every hidden quad must be degenerate"
    print("[PASS] test_hidden_glows_do_not_draw passed (unclaimed glows hidden with zero scale)")


def test_glow_pool_is_additive(g):
    _new_run(g)
    pool = GlowPool(pyglet.graphics.Batch(), cap=2, order=14500)
    assert pool._bank._group.blend_src == GL_SRC_ALPHA and pool._bank._group.blend_dest == GL_ONE
    print("[PASS] test_glow_pool_is_additive passed (src-alpha, one blend)")


def test_dash_afterimage_fades_out(g):
    _new_run(g)
    pool = GlowPool(pyglet.graphics.Batch(), cap=64, order=14500)
    after = DashAfterimage()
    t = 0.0
    for _ in range(12):  # 0.2 s of dash
        after.record(t, Vec2(0.0, 0.0), Vec2(1.0, -1.0), True, (150, 235, 255))
        t += DT
    dash_end = t
    assert after.sample_count > 0, "an active dash must leave samples"
    pool.begin_frame()
    live = after.emit(pool, dash_end, Vec2(0.0, 0.0))
    pool.end_frame()
    assert live > 0, "samples should draw while they fade"
    later = dash_end + DashAfterimage.FADE_S + 0.05
    after.record(later, Vec2(0.0, 0.0), Vec2(1.0, -1.0), False, (150, 235, 255))
    assert after.sample_count == 0, "samples must be dropped once they have faded"
    pool.begin_frame()
    gone = after.emit(pool, later, Vec2(0.0, 0.0))
    pool.end_frame()
    assert gone == 0 and pool.visible_count() == 0, "a faded afterimage must draw nothing"
    print("[PASS] test_dash_afterimage_fades_out passed (streak drawn, then gone after %.2fs)" % DashAfterimage.FADE_S)


def test_dash_afterimage_in_draw_path(g):
    s = _new_run(g)
    random.seed(7)
    s.enemies = []
    s.projectiles = []
    g.player.dash_charges = g.player.dash_max_charges
    perform_dash(g.player, s.time, g.balance, 1.0, 1.0, Vec2(1.0, -1.0), Vec2(0.0, 0.0))
    _tick(g, 3)
    g.on_draw()  # the normal draw path must emit the streak without error
    assert g.visuals._afterimage.sample_count > 0, "a dash in the draw path must record samples"
    assert g.visuals._glow_pool.visible_count() > 0, "a dash in the draw path must show glows"
    print("[PASS] test_dash_afterimage_in_draw_path passed (streak reaches the draw path)")


def test_rim_pulse_follows_combat_intensity(g):
    _new_run(g)
    batch = pyglet.graphics.Batch()

    def peak_opacity(flag, intensity):
        old = _set_flags(ENABLE_RIM_PULSE=flag)
        try:
            random.seed(5)  # the rim's phases come from the global RNG at build time; pin them
            room = Room(batch, 980, 620)
            room.set_combat_intensity(intensity)
            for _ in range(240):
                room.update(DT)
            return max(ln.opacity for ln, _phase in room._boundary)
        finally:
            _restore_flags(old)

    calm_on = peak_opacity(True, 0.0)
    calm_off = peak_opacity(False, 0.0)
    assert calm_on == calm_off, "with no combat the rim must look exactly as before"
    fight_on = peak_opacity(True, 1.0)
    fight_off = peak_opacity(False, 1.0)
    assert fight_on > fight_off, f"combat must brighten the rim ({fight_on} vs {fight_off})"
    assert fight_on <= 255
    print("[PASS] test_rim_pulse_follows_combat_intensity passed (peak %d calm, %d in combat)" % (calm_on, fight_on))


def test_starfield_layers_drift_at_different_speeds(g):
    _new_run(g)
    batch = pyglet.graphics.Batch()
    sf = Starfield(batch, order=-19980)
    speeds = sf.layer_speeds()
    assert sf.layer_count == len(LAYERS) == 3, "starfield should have three layers"
    assert speeds == sorted(speeds) and len(set(speeds)) == 3, f"layer speeds must differ: {speeds}"
    assert sf.star_count == sum(count for count, *_rest in LAYERS)
    print("[PASS] test_starfield_layers_drift_at_different_speeds passed (speeds %s)" % speeds)


def test_starfield_stays_on_screen_and_parallaxes(g):
    _new_run(g)
    batch = pyglet.graphics.Batch()
    sf = Starfield(batch, order=-19980)
    w, h = 980.0, 620.0

    def positions(t, cam):
        sf.sync(t, w, h, camera=cam)
        bank = sf._bank
        return [(bank._translate[12 * slot], bank._translate[12 * slot + 1]) for slot in range(sf.star_count)]

    for t in (0.0, 3.7, 91.2):
        for x, y in positions(t, Vec2(-200.0, 150.0)):
            assert 0.0 <= x < w and 0.0 <= y < h, f"star left the window at t={t}: {(x, y)}"

    base = positions(10.0, Vec2(0.0, 0.0))
    moved = positions(10.0, Vec2(40.0, 0.0))
    shifts = []
    for (x0, _y0), (x1, _y1) in zip(base, moved):
        dx = (x1 - x0 + w * 0.5) % w - w * 0.5  # undo the window wrap
        shifts.append(abs(dx))
    per_layer = []
    start = 0
    for count, *_rest in LAYERS:
        per_layer.append(sum(shifts[start:start + count]) / count)
        start += count
    assert per_layer[0] < per_layer[1] < per_layer[2], f"nearer layers must shift more with the camera: {per_layer}"

    later = positions(12.0, Vec2(0.0, 0.0))
    assert any(abs(a[0] - b[0]) > 1e-6 for a, b in zip(base, later)), "stars must drift over time"
    print("[PASS] test_starfield_stays_on_screen_and_parallaxes passed (camera shifts %s px)" % [round(v, 2) for v in per_layer])


def test_starfield_uses_its_own_rng(g):
    _new_run(g)
    random.seed(99)
    before = random.getstate()
    Starfield(pyglet.graphics.Batch(), order=-19980)
    assert random.getstate() == before, "building the starfield must not touch the run's global RNG"
    print("[PASS] test_starfield_uses_its_own_rng passed (global random state unchanged)")


def test_projectile_glow_styles(g):
    basic_col, _r, _o = projectile_glow(_projectile(Vec2(0.0, 0.0)))
    enemy_col, _r, _o = projectile_glow(_projectile(Vec2(0.0, 0.0), owner="enemy"))
    crit_col, _r, _o = projectile_glow(_projectile(Vec2(0.0, 0.0), crit=True))
    assert basic_col != enemy_col, "enemy shots must glow differently from the player's"
    assert crit_col == (255, 205, 50), "critical hits glow gold"
    for kind in ("bullet", "spread", "missile", "plasma", "railgun", "bomb", "flak"):
        col, radius, opacity = projectile_glow(_projectile(Vec2(0.0, 0.0), kind=kind))
        assert len(col) == 3 and radius > 0 and 0 < opacity <= 255, f"bad glow style for {kind}"
    print("[PASS] test_projectile_glow_styles passed (player, enemy, crit and every type)")


def test_eye_slots_point_at_eye_shapes(g):
    s = _new_run(g)
    behaviors = ["chaser", "flyer", "tank", "ranged", "charger", "swarm", "spitter", "boss_laser", "bomber", "engineer", "egg_sac", "generic_unknown"]
    for name in behaviors:
        slots = _eye_slots(name)
        enemy = Enemy(pos=Vec2(0.0, 0.0), hp=50, speed=0.0, behavior=name, seed=1.0)
        g.visuals.ensure_enemy(enemy)
        g.visuals.sync_enemy(enemy, Vec2(0.0, 0.0))
        objs = g.visuals._enemy_handles[id(enemy)].objs
        for idx in slots:
            assert idx < len(objs), f"{name}: eye slot {idx} past the {len(objs)} shapes"
            assert hasattr(objs[idx], "x") and hasattr(objs[idx], "opacity"), f"{name}: slot {idx} is not a shape"
        g.visuals.drop_enemy(enemy)
    assert _EYE_SLOTS and _GENERIC_EYE_SLOTS == (3, 4)
    print("[PASS] test_eye_slots_point_at_eye_shapes passed (eye slots index real shapes)")


def test_switches_default_on_and_disable_each_effect(g):
    for name in FX_FLAGS:
        assert getattr(config, name) is True, f"{name} must default to True"
    old = _set_flags(ENABLE_PARALLAX_STARS=False, ENABLE_GLOW=False, ENABLE_DASH_AFTERIMAGE=False)
    try:
        s = _new_run(g)
        assert g.visuals._starfield is None, "parallax stars must not be built when switched off"
        s.projectiles = [_projectile(Vec2(0.0, 0.0), kind="plasma")]
        perform_dash(g.player, s.time, g.balance, 1.0, 1.0, Vec2(1.0, 0.0), Vec2(0.0, 0.0))
        _tick(g, 2)
        g.on_draw()
        assert g.visuals._glow_pool.visible_count() == 0, "glows must stay hidden with ENABLE_GLOW off"
        assert g.visuals._afterimage.sample_count == 0, "no afterimage with ENABLE_DASH_AFTERIMAGE off"
    finally:
        _restore_flags(old)
    _new_run(g)
    print("[PASS] test_switches_default_on_and_disable_each_effect passed (flags default on, each switch silences its effect)")


def _sim_digest(g, flags_on: bool, frames: int = 90) -> tuple:
    old = _set_flags(ENABLE_GLOW=flags_on, ENABLE_PARALLAX_STARS=flags_on, ENABLE_DASH_AFTERIMAGE=flags_on, ENABLE_RIM_PULSE=flags_on)
    try:
        random.seed(2024)
        states._SHAKE_RNG.seed(2024)
        s = _new_run(g)
        s.init_rng(2024)
        s.wave = 13
        spawn_wave(s, Vec2(0.0, 0.0))
        perform_dash(g.player, s.time, g.balance, 1.0, 1.0, Vec2(1.0, -1.0), Vec2(0.0, 0.0))
        for _ in range(frames):
            g.player.hp = g.player.max_hp
            _tick(g)
            g.on_draw()  # exercise the draw path too: it must not feed back into the simulation
        enemies = tuple((round(e.pos.x, 6), round(e.pos.y, 6), int(e.hp)) for e in s.enemies)
        shots = tuple((round(p.pos.x, 6), round(p.pos.y, 6)) for p in s.projectiles)
        return (enemies, shots, round(g.player.pos.x, 6), round(g.player.pos.y, 6), round(s.time, 6))
    finally:
        _restore_flags(old)


def test_visual_effects_leave_simulation_unchanged(g):
    with_fx = _sim_digest(g, True)
    without_fx = _sim_digest(g, False)
    assert with_fx == without_fx, "graphics effects must not change any simulation state"
    print("[PASS] test_visual_effects_leave_simulation_unchanged passed (%d enemies, %d shots identical)" % (len(with_fx[0]), len(with_fx[1])))


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_glow_texture_is_built_once(g)
        test_glow_pool_never_grows_past_cap(g)
        test_glow_pool_keeps_a_key_on_its_quad(g)
        test_hidden_glows_do_not_draw(g)
        test_glow_pool_is_additive(g)
        test_dash_afterimage_fades_out(g)
        test_dash_afterimage_in_draw_path(g)
        test_rim_pulse_follows_combat_intensity(g)
        test_starfield_layers_drift_at_different_speeds(g)
        test_starfield_stays_on_screen_and_parallaxes(g)
        test_starfield_uses_its_own_rng(g)
        test_projectile_glow_styles(g)
        test_eye_slots_point_at_eye_shapes(g)
        test_switches_default_on_and_disable_each_effect(g)
        test_visual_effects_leave_simulation_unchanged(g)
    finally:
        g.close()
    print("\nALL WAVE 1 GRAPHICS TESTS PASSED")


if __name__ == "__main__":
    run_all()
