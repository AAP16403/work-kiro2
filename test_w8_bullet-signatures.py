"""Wave 8 bullet signatures: an enemy shot's look names the behaviour that fired it.

Covers: the config block and its switch; each signed behaviour (spitter blob, ranged needle, bomber pulse ring, boss
magenta ring) maps to its own look, and every other behaviour keeps the red-orange shot; the source is recorded where
each enemy shot is created (the live behaviours, the boss firing helpers in enemy.py, and the bullet-hell copies),
and the damage, speed and ttl of those shots are unchanged; player shots keep their looks and carry no source; the
four looks differ from the arena floor; REDUCE_MOTION holds the pulse and keeps the shape; the switch off restores the
old look; steady frames build no objects; and a signed shot reaches the screen in a real run.

Plain functions that print [PASS] lines, run from run_all().
"""

import ast
import math
import os
import random
import tracemalloc
from types import SimpleNamespace

import pyglet

import config
import mutators
import projectile_art as pa
import score as score_mod
from enemy import Enemy
from enemy_behaviors.bomber import Bomber
from enemy_behaviors.ranged import Ranged
from enemy_behaviors.spitter import Spitter
from enemy_behaviors.tank import Tank
from game import Game
from projectile import Projectile, spawn_projectiles
from states import GameStateName
from utils import Vec2
from weapons import WEAPONS

ROOT = os.path.dirname(os.path.abspath(__file__))
SIGNED = ("spitter", "ranged", "bomber")
BOSSES = ("boss_thunder", "boss_laser", "boss_trapmaster", "boss_swarmqueen", "boss_brute", "boss_abyss_gaze", "boss_womb_core")
UNSIGNED = ("tank", "chaser", "swarm", "charger", "flyer", "engineer", "egg_sac")
DT = 1.0 / 60.0
_WINDOW = None


def _read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


def _shot(source="", owner="enemy", projectile_type="bullet", ttl=2.0, vel=(200.0, 0.0)):
    return Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(*vel), damage=6, ttl=ttl, owner=owner,
                      projectile_type=projectile_type, source=source)


def _batch_bank():
    """A shot bank on a hidden window, so the pooled quads have a GL context."""
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = pyglet.window.Window(width=64, height=64, visible=False)
    return pa.ShotBank(pyglet.graphics.Batch())


def _visual(bank, proj):
    return pa.ProjectileVisual(bank, pyglet.graphics.Group(order=14000), proj)


class _State:
    """The few fields the enemy behaviours read from a run."""

    def __init__(self, wave=3, obstacles=()):
        self.projectiles = []
        self.enemies = []
        self.obstacles = list(obstacles)
        self.wave = wave
        self.rng = random.Random(3)


def _new_run(g: Game):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.state.wave_active = True
    g.player.pos = Vec2(0.0, 0.0)
    return g.state


def _quiet_game():
    """A Game whose high-score save points at a temp file, so a run can end without touching the real one."""
    import tempfile
    g = Game()
    g.set_visible(False)
    scratch = tempfile.mkdtemp(prefix="w8_sig_")
    score_mod.HIGH_SCORE_FILE = os.path.join(scratch, "high_scores.json")
    g.progress_path = os.path.join(scratch, "progress.json")
    return g


def test_config_block_and_switch():
    text = _read("config.py")
    head = "# wave8 bullet-signatures"
    assert head in text, "config.py has no wave8 bullet-signatures block"
    names = []
    for line in text.split(head, 1)[1].splitlines():
        stripped = line.strip()
        if stripped.startswith("# wave8 "):
            break  # the next feature's block starts here
        if not stripped or stripped.startswith("#"):
            continue
        name = stripped.split("=", 1)[0].strip()
        assert name.startswith(("ENABLE_", "SIG_")), f"not a wave8 constant: {line!r}"
        names.append(name)
    assert "ENABLE_BULLET_SIGNATURES" in names, names
    for name in names:
        assert hasattr(config, name), name
    assert config.ENABLE_BULLET_SIGNATURES is True
    print(f"[PASS] test_config_block_and_switch passed ({len(names)} wave8 constants, switch on)")


def test_each_behaviour_maps_to_a_distinct_signature():
    keys = {src: pa.signature_key(src) for src in SIGNED + BOSSES}
    assert keys["spitter"] == "spitter" and keys["ranged"] == "ranged" and keys["bomber"] == "bomber", keys
    assert {keys[b] for b in BOSSES} == {"boss"}, keys
    styles = {}
    for src in SIGNED + ("boss_thunder",):
        style = pa.signature_style(_shot(src))
        assert style is not None, src
        styles[src] = style
    for boss in BOSSES:
        assert pa.signature_style(_shot(boss)) is styles["boss_thunder"], boss
    shapes = {src: (st.trail, st.ring > 0.0, st.head) for src, st in styles.items()}
    assert len(set(shapes.values())) == 4, shapes
    assert styles["spitter"].trail == "blob" and styles["spitter"].ring == 0.0
    assert styles["ranged"].trail == "needle" and styles["ranged"].ring == 0.0
    assert styles["bomber"].ring > 0.0 and styles["boss_thunder"].ring > styles["bomber"].ring, "boss ring is larger"
    print("[PASS] test_each_behaviour_maps_to_a_distinct_signature passed (spitter blob, ranged needle, bomber ring, boss ring)")


def test_other_behaviours_keep_the_red_orange_shot():
    assert pa.signature_key("mystery") == "" and pa.signature_key("") == ""
    for src in UNSIGNED + ("",):
        shot = _shot(src)
        assert pa.signature_style(shot) is None, src
        assert pa.signature_glow(shot) is None, src
        assert pa.style_for_projectile(shot).head == pa.ENEMY_HEAD, src
    print(f"[PASS] test_other_behaviours_keep_the_red_orange_shot passed ({len(UNSIGNED)} behaviours and unsourced shots unchanged)")


def test_live_behaviours_record_their_source_and_keep_their_numbers():
    st = _State(wave=3)
    sp = Enemy(pos=Vec2(200.0, 0.0), hp=30, speed=60.0, behavior="spitter", seed=1.0)
    sp.attack_cd = 0.0
    Spitter().update(sp, Vec2(0.0, 0.0), st, DT, Vec2(0.0, 0.0))
    assert len(st.projectiles) == 3, len(st.projectiles)
    for p in st.projectiles:
        assert p.source == "spitter" and p.owner == "enemy" and p.projectile_type == "spread", p.source
        assert p.damage == 6 and p.ttl == 2.5 and abs(p.vel.length() - 210.0) < 1e-6

    st = _State(wave=3)
    rg = Enemy(pos=Vec2(200.0, 0.0), hp=30, speed=60.0, behavior="ranged", seed=2.0)
    rg.attack_cd = 0.0
    Ranged().update(rg, Vec2(0.0, 0.0), st, DT, Vec2(0.0, 0.0))
    assert len(st.projectiles) == 1, len(st.projectiles)
    p = st.projectiles[0]
    assert p.source == "ranged" and p.damage == 6 + 3 // 3 and p.ttl == 2.4, (p.source, p.damage, p.ttl)

    obstacle = SimpleNamespace(pos=Vec2(100.0, 0.0), radius=30.0)
    st = _State(wave=3, obstacles=[obstacle])
    rg = Enemy(pos=Vec2(150.0, 0.0), hp=30, speed=60.0, behavior="ranged", seed=2.0)
    rg.attack_cd = 0.0
    Ranged().update(rg, Vec2(0.0, 0.0), st, DT, Vec2(0.0, 0.0))
    assert len(st.projectiles) == 1, len(st.projectiles)
    p = st.projectiles[0]
    assert p.source == "ranged" and p.damage == 8 + 3 // 2 and p.ttl == 2.6, (p.source, p.damage, p.ttl)

    st = _State(wave=3)
    bm = Enemy(pos=Vec2(300.0, 0.0), hp=30, speed=60.0, behavior="bomber", seed=3.0)
    bm.attack_cd = 0.0
    Bomber().update(bm, Vec2(0.0, 0.0), st, DT, Vec2(0.0, 0.0))
    assert len(st.projectiles) == 1, len(st.projectiles)
    p = st.projectiles[0]
    assert p.source == "bomber" and p.projectile_type == "bomb" and p.damage == 14 + 3 // 3, (p.source, p.damage)
    assert 1.1 <= p.ttl <= 1.45, p.ttl

    st = _State(wave=3)
    tk = Enemy(pos=Vec2(100.0, 0.0), hp=30, speed=60.0, behavior="tank", seed=4.0)
    tk.attack_cd = 0.0
    Tank().update(tk, Vec2(0.0, 0.0), st, DT, Vec2(0.0, 0.0))
    assert len(st.projectiles) == 1, len(st.projectiles)
    p = st.projectiles[0]
    assert p.source == "tank" and p.damage == 12 and p.ttl == 2.8 and abs(p.vel.length() - 185.0) < 1e-6
    print("[PASS] test_live_behaviours_record_their_source_and_keep_their_numbers passed (spitter, ranged x2, bomber, tank: source set, damage, speed and ttl unchanged)")


def test_boss_shots_record_their_boss_source_in_play():
    g = _quiet_game()
    try:
        s = _new_run(g)
        # The boss teleports on this rng. An unseeded run sometimes lands out of range and never fires in 600 steps.
        s.rng = random.Random(4)
        s.enemies[:] = [Enemy(pos=Vec2(230.0, 60.0), hp=900, speed=30.0, behavior="boss_thunder", seed=4.0, max_hp=900)]
        seen = set()
        for _ in range(600):
            g._fixed_step()
            for p in s.projectiles:
                if p.owner == "enemy":
                    seen.add(p.source)
    finally:
        g.close()
    assert seen == {"boss_thunder"}, seen
    print(f"[PASS] test_boss_shots_record_their_boss_source_in_play passed (boss shots carry {sorted(seen)})")


def _calls(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == name:
            yield node


def test_every_enemy_shot_site_passes_a_source():
    checked = 0
    for rel in ("enemy.py", "enemy_behaviors/ranged.py", "enemy_behaviors/spitter.py",
                "enemy_behaviors/bomber.py", "enemy_behaviors/tank.py", "mutators.py"):
        tree = ast.parse(_read(rel))
        for call in _calls(tree, "Projectile"):
            kws = {k.arg for k in call.keywords}
            assert "source" in kws, f"{rel}:{call.lineno} creates a Projectile without a source"
            checked += 1
    enemy_tree = ast.parse(_read("enemy.py"))
    for helper in ("_fire_fan", "_fire_ring", "_spawn_shockwave"):
        for call in _calls(enemy_tree, helper):
            kws = {k.arg for k in call.keywords}
            assert "source" in kws, f"enemy.py:{call.lineno} calls {helper} without a source"
            checked += 1
    assert checked >= 25, checked
    print(f"[PASS] test_every_enemy_shot_site_passes_a_source passed ({checked} spawn sites name their source)")


def test_player_shots_keep_their_looks_and_carry_no_source():
    rng = random.Random(9)
    checked = 0
    for weapon in WEAPONS.values():
        shots = spawn_projectiles(Vec2(0.0, 0.0), Vec2(1.0, 0.0), weapon, 1.0, config.PLAYER_DAMAGE, rng=rng)
        assert shots, weapon.name
        base = pa.WEAPON_STYLES[weapon.name]
        for p in shots:
            assert p.owner == "player" and p.source == "", weapon.name
            assert pa.signature_style(p) is None and pa.signature_glow(p) is None, weapon.name
            st = pa.style_for_projectile(p)
            if p.is_crit:
                assert st.head == base.head, weapon.name
            else:
                assert st is base, weapon.name
            checked += 1
    forced = _shot("spitter", owner="player")
    assert pa.signature_style(forced) is None, "a player shot never takes a signature"
    assert pa.style_for_projectile(forced) is pa.BASIC_STYLE, "a player shot with a stray source keeps its look"
    print(f"[PASS] test_player_shots_keep_their_looks_and_carry_no_source passed ({checked} player shots unchanged)")


def test_each_signature_differs_from_the_arena_floor():
    floors = (config.FLOOR_MAIN, config.FLOOR_EDGE, config.FLOOR_GRID)
    worst = {}
    for key in SIGNED + ("boss",):
        head = pa.SIGNATURE_STYLES[key].head
        nearest = min(math.dist(head, floor) for floor in floors)
        worst[key] = round(nearest)
        assert nearest >= 150.0, (key, head, nearest)
    print(f"[PASS] test_each_signature_differs_from_the_arena_floor passed (nearest floor colour distance {worst})")


def test_reduce_motion_holds_the_pulse_and_keeps_the_shape():
    bank = _batch_bank()
    saved = config.REDUCE_MOTION
    visuals = []
    try:
        config.REDUCE_MOTION = True
        for src, ptype, key in (("boss_thunder", "bullet", "boss"), ("bomber", "bomb", "bomber")):
            shot = _shot(src, projectile_type=ptype, ttl=0.17453)
            vis = _visual(bank, shot)
            visuals.append(vis)
            assert vis._ring is not None, src
            vis.sync(shot, Vec2(0.0, 0.0))
            r1, o1 = vis._ring.radius, vis._ring.opacity
            shot.ttl = 0.5236
            vis.sync(shot, Vec2(0.0, 0.0))
            r2, o2 = vis._ring.radius, vis._ring.opacity
            assert r1 == r2 and o1 == o2, (src, r1, r2, o1, o2)
            assert abs(r1 - pa.SIGNATURE_STYLES[key].ring) < 1e-9, (src, r1)

        config.REDUCE_MOTION = False
        shot = _shot("boss_thunder", ttl=0.17453)
        vis = _visual(bank, shot)
        visuals.append(vis)
        vis.sync(shot, Vec2(0.0, 0.0))
        swollen = vis._ring.radius
        shot.ttl = 0.5236
        vis.sync(shot, Vec2(0.0, 0.0))
        shrunk = vis._ring.radius
        amp = config.SIG_RING_PULSE
        assert swollen > shrunk + 2.0, (swollen, shrunk)
        assert abs(swollen - config.SIG_BOSS_RING * (1.0 + amp)) < 1e-6, swollen
        assert abs(shrunk - config.SIG_BOSS_RING * (1.0 - amp)) < 1e-6, shrunk

        for src in ("spitter", "ranged"):
            shot = _shot(src, projectile_type="spread" if src == "spitter" else "bullet", ttl=0.17453)
            vis = _visual(bank, shot)
            visuals.append(vis)
            assert vis._ring is None, f"{src} has no pulse ring"
    finally:
        config.REDUCE_MOTION = saved
        for vis in visuals:
            vis.delete()
    print(f"[PASS] test_reduce_motion_holds_the_pulse_and_keeps_the_shape passed (rest radius {config.SIG_BOSS_RING:g} px still, pulse {swollen:.1f} to {shrunk:.1f} px when moving)")


def test_switch_off_restores_the_old_look():
    saved = config.ENABLE_BULLET_SIGNATURES
    config.ENABLE_BULLET_SIGNATURES = False
    try:
        for src in SIGNED + ("boss_thunder",):
            shot = _shot(src, projectile_type="spread" if src == "spitter" else "bullet")
            assert pa.signature_style(shot) is None and pa.signature_glow(shot) is None, src
            st = pa.style_for_projectile(shot)
            assert st.head == pa.ENEMY_HEAD and st.ring == 0.0, src
    finally:
        config.ENABLE_BULLET_SIGNATURES = saved
    print("[PASS] test_switch_off_restores_the_old_look passed (every enemy shot back to the red-orange look)")


def test_steady_frames_build_no_new_objects():
    bank = _batch_bank()
    saved = config.REDUCE_MOTION
    config.REDUCE_MOTION = False
    shots = [_shot("boss_thunder", ttl=2.4), _shot("spitter", ttl=2.5), _shot("bomber", projectile_type="bomb", ttl=1.2)]
    visuals = [_visual(bank, p) for p in shots]
    try:
        for vis, p in zip(visuals, shots):
            vis.sync(p, Vec2(0.0, 0.0))
        tracemalloc.start()
        try:
            base, _ = tracemalloc.get_traced_memory()
            for _ in range(600):
                for vis, p in zip(visuals, shots):
                    p.ttl = max(0.05, p.ttl - DT)
                    vis.sync(p, Vec2(0.0, 0.0))
                    pa.signature_glow(p)
            net, _ = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
    finally:
        config.REDUCE_MOTION = saved
        for vis in visuals:
            vis.delete()
    assert net - base < 16384, f"net growth {net - base} bytes over 600 frames"
    print(f"[PASS] test_steady_frames_build_no_new_objects passed (net {net - base} bytes over 600 frames of three signed shots)")


def test_bullet_hell_copies_keep_the_source():
    rules = SimpleNamespace(enemy_projectile_speed_mult=1.0, enemy_volley_extra=2)
    shots = []
    for deg in (-22.0, 0.0, 22.0):
        a = math.radians(deg)
        shots.append(_shot("spitter", vel=(210.0 * math.cos(a), 210.0 * math.sin(a))))
    added = mutators.shape_enemy_volley(shots, 0, rules)
    assert added == 2 and len(shots) == 5, (added, len(shots))
    assert all(p.source == "spitter" for p in shots), [p.source for p in shots]
    print("[PASS] test_bullet_hell_copies_keep_the_source passed (extra volley shots keep the spitter signature)")


def test_signed_shots_reach_the_screen_in_play():
    g = _quiet_game()
    try:
        s = _new_run(g)
        s.enemies[:] = [
            Enemy(pos=Vec2(200.0, 0.0), hp=500, speed=60.0, behavior="spitter", seed=1.0),
            Enemy(pos=Vec2(-190.0, 120.0), hp=500, speed=60.0, behavior="ranged", seed=2.0),
            Enemy(pos=Vec2(0.0, -260.0), hp=500, speed=60.0, behavior="bomber", seed=3.0),
        ]
        found = {}
        for _ in range(240):
            g._fixed_step()
            g.on_draw()
            for p in s.projectiles:
                if p.owner != "enemy" or p.source not in SIGNED or p.source in found:
                    continue
                vis = g.visuals._proj_handles.get(id(p))
                if vis is None:
                    continue
                found[p.source] = (vis.style.label, vis._body.color[:3], vis._ring is not None, pa.signature_glow(p)[0])
            if len(found) == len(SIGNED):
                break
    finally:
        g.close()
    assert set(found) == set(SIGNED), sorted(found)
    assert found["spitter"][0] == "Spitter Blob" and found["spitter"][1] == config.SIG_SPITTER_COLOR, found["spitter"]
    assert found["ranged"][0] == "Ranged Needle" and found["ranged"][1] == config.SIG_RANGED_COLOR and not found["ranged"][2], found["ranged"]
    assert found["bomber"][0] == "Bomber Pulse" and found["bomber"][2], found["bomber"]
    assert found["spitter"][3] == config.SIG_SPITTER_COLOR, "the spitter's head glow matches its signature"
    print("[PASS] test_signed_shots_reach_the_screen_in_play passed (spitter blob, ranged needle and bomber ring drawn in a real run)")


def run_all():
    test_config_block_and_switch()
    test_each_behaviour_maps_to_a_distinct_signature()
    test_other_behaviours_keep_the_red_orange_shot()
    test_live_behaviours_record_their_source_and_keep_their_numbers()
    test_boss_shots_record_their_boss_source_in_play()
    test_every_enemy_shot_site_passes_a_source()
    test_player_shots_keep_their_looks_and_carry_no_source()
    test_each_signature_differs_from_the_arena_floor()
    test_reduce_motion_holds_the_pulse_and_keeps_the_shape()
    test_switch_off_restores_the_old_look()
    test_steady_frames_build_no_new_objects()
    test_bullet_hell_copies_keep_the_source()
    test_signed_shots_reach_the_screen_in_play()
    print("ALL W8 BULLET SIGNATURE TESTS PASSED")


if __name__ == "__main__":
    run_all()
