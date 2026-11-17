"""Wave 8 shards tests: a critical hit splits the player's bullet into three shards at its impact point.

Covers: the config block and its switch; a crit splitting into three shards at the impact point, 35 degrees either side
of the bullet's own direction and straight on, at 60 percent of its speed; the shard damage at 35 percent rounded half
up; only critical player bullets splitting (not enemy shots, not flak shrapnel); a shard's hit never splitting; the cap of
24 with the oldest dropped first; expiry at 0.35 s; a shard never hitting the enemy that made it; nothing happening with
ENABLE_SHARDS off; the shot colour; the pool's draw (placement, fade, hide) and the reduced-motion rule; steady frames
building no objects; the frame cost with live shards; and two scripted runs in play. The first run checks one real crit
bullet's split at its entry point. The second forces crits through the crit bonus path and reports shard hits and kills.
Affixes: a shard meets a Reflector under the same rules as the shot that made it (sent back in its cooldown, hurts it
otherwise), a reflected crit does not split, and a tank that a shard kills blasts the player as a direct kill does.
Plain functions that print [PASS] lines, run from run_all().
"""

import gc
import math
import os
import time
import tracemalloc

import pyglet

import config
import glow
import shards
from enemy import Enemy
from game import Game
from projectile import Projectile
from shards import ShardPool, can_split, impact_point, shard_colour, shard_damage, split_crit
from states import GameStateName
from utils import Vec2, to_iso

FRAME = 1.0 / 60.0
_WINDOW = None
_KEYS = (
    "ENABLE_SHARDS", "SHARD_SECONDS", "SHARD_CAP", "SHARD_SPREAD_DEG", "SHARD_SPEED_FRACTION",
    "SHARD_DAMAGE_PERCENT", "SHARD_HIT_RADIUS", "REDUCE_MOTION",
)


def _save():
    return {k: getattr(config, k) for k in _KEYS}


def _restore(saved):
    for k, v in saved.items():
        setattr(config, k, v)


def _batch():
    """A batch on a hidden window, so the pool's quad bank has a GL context."""
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = pyglet.window.Window(width=64, height=64, visible=False)
    return pyglet.graphics.Batch()


def _crit(x=0.0, y=0.0, vx=900.0, vy=0.0, damage=30, weapon_name="Basic Gun"):
    """A critical player bullet, the kind a crit hit splits."""
    return Projectile(
        pos=Vec2(float(x), float(y)), vel=Vec2(float(vx), float(vy)), damage=int(damage), ttl=2.0,
        owner="player", projectile_type="bullet", is_crit=True, weapon_name=weapon_name,
    )


def _enemy(x, y, hp=100):
    return Enemy(pos=Vec2(float(x), float(y)), hp=int(hp), speed=0.0, behavior="chaser")


def _const_radius(e):
    return 12.0


def _recorder():
    """A deal_damage stand-in: records (enemy, amount), takes the hp off and reports a kill at zero hp."""
    log = []

    def deal(e, amount):
        log.append((e, amount))
        e.hp -= amount
        return e.hp <= 0

    return log, deal


def _own_growth(snap0, snap1) -> int:
    """Net bytes allocated between two tracemalloc snapshots by the shard and glow code only.

    pyglet's silent audio driver runs a thread that appends to a list while a test runs, so the whole-process figure
    picks up its noise. A stack filter keeps the allocations whose stack passes through shards.py or glow.py.
    """
    keep = [
        tracemalloc.Filter(True, os.path.abspath(shards.__file__), all_frames=True),
        tracemalloc.Filter(True, os.path.abspath(glow.__file__), all_frames=True),
    ]
    diff = snap1.filter_traces(keep).compare_to(snap0.filter_traces(keep), "filename")
    return sum(stat.size_diff for stat in diff)


def _new_run(g):
    """A fresh run in PLAYING with no auto-fire and no wave spawns, so each test controls the enemies."""
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.state.wave_active = True
    g.player.pos = Vec2(0.0, 0.0)
    return g.state


def test_config_block_and_switch():
    assert config.ENABLE_SHARDS is True, config.ENABLE_SHARDS
    assert config.SHARD_SPREAD_DEG == 35.0, config.SHARD_SPREAD_DEG
    assert config.SHARD_SPEED_FRACTION == 0.6, config.SHARD_SPEED_FRACTION
    assert config.SHARD_SECONDS == 0.35, config.SHARD_SECONDS
    assert config.SHARD_DAMAGE_PERCENT == 35, config.SHARD_DAMAGE_PERCENT
    assert config.SHARD_CAP == 24, config.SHARD_CAP
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.py")
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    head = text.find("# wave8 shards")
    assert head > text.find("COLORBLIND_ENEMY_COLORS = {"), "the wave8 block sits at the end of config.py"
    assert "ENABLE_SHARDS = True" in text[head:], "the switch is in the wave8 block"
    print("[PASS] test_config_block_and_switch passed (the wave8 shards block is at the end of config.py, switch on)")


def test_crit_splits_into_three_at_the_impact_point():
    pool = ShardPool(size=24)
    origin = _enemy(200, 0)
    n = split_crit(pool, _crit(vx=900.0, vy=0.0, damage=30), 150.0, 4.0, origin, tint=None)
    assert n == 3 and pool.spawned == 3 and pool.live_count == 3, (n, pool.spawned, pool.live_count)
    live = pool.live_shards()
    for sh in live:
        assert (sh.x, sh.y) == (150.0, 4.0), (sh.x, sh.y)
        assert abs(math.hypot(sh.vx, sh.vy) - 0.6 * 900.0) < 1e-6, math.hypot(sh.vx, sh.vy)
        assert sh.origin is origin
    angles = sorted(math.degrees(math.atan2(sh.vy, sh.vx)) for sh in live)
    for got, want in zip(angles, (-35.0, 0.0, 35.0)):
        assert abs(got - want) < 1e-6, angles

    # The spread turns with the bullet: a bullet flying along +y gives 55, 90 and 125 degrees.
    pool2 = ShardPool(size=24)
    split_crit(pool2, _crit(vx=0.0, vy=600.0, damage=30), 0.0, 0.0, origin)
    angles2 = sorted(math.degrees(math.atan2(sh.vy, sh.vx)) for sh in pool2.live_shards())
    for got, want in zip(angles2, (55.0, 90.0, 125.0)):
        assert abs(got - want) < 1e-6, angles2
    for sh in pool2.live_shards():
        assert abs(math.hypot(sh.vx, sh.vy) - 0.6 * 600.0) < 1e-6
    print("[PASS] test_crit_splits_into_three_at_the_impact_point passed "
          "(three shards at the impact, -35/0/+35 degrees of the bullet, 60% speed)")


def test_only_critical_player_bullets_split():
    pool = ShardPool(size=24)
    origin = _enemy(200, 0)
    plain = _crit()
    plain.is_crit = False
    assert split_crit(pool, plain, 0.0, 0.0, origin) == 0
    enemy_crit = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=30, owner="enemy", is_crit=True)
    assert split_crit(pool, enemy_crit, 0.0, 0.0, origin) == 0
    shrapnel = Projectile(
        pos=Vec2(0.0, 0.0), vel=Vec2(400.0, 0.0), damage=13, ttl=0.3, owner="player",
        projectile_type="bullet", is_crit=True, weapon_name="",
    )
    assert not can_split(shrapnel), "flak shrapnel is already a burst; it does not split"
    assert split_crit(pool, shrapnel, 0.0, 0.0, origin) == 0
    assert can_split(_crit()), "a critical player bullet splits"
    assert pool.spawned == 0 and pool.live_count == 0
    print("[PASS] test_only_critical_player_bullets_split passed "
          "(plain, enemy and flak shrapnel shots do not split; a crit player bullet does)")


def test_shard_damage_is_35_percent_rounded_half_up():
    cases = {1: 0, 3: 1, 10: 4, 13: 5, 15: 5, 20: 7, 30: 11, 70: 25, 100: 35}
    for dmg, want in cases.items():
        got = shard_damage(dmg)
        assert got == want, (dmg, got, want)
    pool = ShardPool(size=24)
    split_crit(pool, _crit(damage=30), 0.0, 0.0, _enemy(200, 0))
    assert all(sh.dmg == 11 for sh in pool.live_shards()), [sh.dmg for sh in pool.live_shards()]
    print("[PASS] test_shard_damage_is_35_percent_rounded_half_up passed "
          "(10 -> 4, 15 -> 5, 30 -> 11 (10.5 up), 70 -> 25 (24.5 up); the shards carry it)")


def test_a_shard_does_not_split():
    pool = ShardPool(size=24)
    split_crit(pool, _crit(damage=30), 0.0, 0.0, _enemy(-300, 0))  # the origin is far away, off every path
    assert pool.spawned == 3
    target = _enemy(60, 0, hp=100)
    log, deal = _recorder()
    for _ in range(40):
        pool.step([target], FRAME, deal, _const_radius)
    assert pool.hits >= 1, "the straight shard reaches the target"
    assert pool.spawned == 3, f"a shard's hit spawned new shards ({pool.spawned})"
    assert pool.hits + pool.expired == 3, (pool.hits, pool.expired)
    assert log and all(amount == 11 for _, amount in log), log
    print(f"[PASS] test_a_shard_does_not_split passed (a shard hit spawned nothing; {pool.hits} hit, "
          f"{pool.expired} expired)")


def test_cap_holds_and_the_oldest_drops_first():
    pool = ShardPool(size=config.SHARD_CAP)
    assert pool.size == 24 == config.SHARD_CAP
    origin = _enemy(0, 500)
    for i in range(10):
        split_crit(pool, _crit(), 10.0 * i, 0.0, origin)
        assert pool.live_count <= 24, pool.live_count
    assert pool.live_count == 24, pool.live_count
    assert pool.spawned == 30 and pool.evicted == 6, (pool.spawned, pool.evicted)
    live = pool.live_shards()
    seqs = [sh.seq for sh in live]
    assert seqs == list(range(7, 31)), seqs
    xs = sorted({sh.x for sh in live})
    assert xs == [20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0], xs
    print("[PASS] test_cap_holds_and_the_oldest_drops_first passed "
          "(30 shards spawned, 24 live, the 6 oldest dropped first)")


def test_shards_expire_at_035_seconds():
    pool = ShardPool(size=24)
    pool.spawn(0.0, 0.0, 0.0, 0.0, 5, None, (255, 255, 255))  # stationary, so it hits nothing
    enemies = []
    deal = _recorder()[1]
    for _ in range(13):
        pool.step(enemies, 0.025, deal, _const_radius)
    assert pool.live_count == 1, "alive at 0.325 s"
    pool.step(enemies, 0.025, deal, _const_radius)
    assert pool.live_count == 0 and pool.expired == 1, "gone at 0.35 s"

    pool.spawn(0.0, 0.0, 0.0, 0.0, 5, None, (255, 255, 255))
    for _ in range(20):
        pool.step(enemies, FRAME, deal, _const_radius)
    assert pool.live_count == 1, "alive at 20 frames (0.333 s)"
    pool.step(enemies, FRAME, deal, _const_radius)
    assert pool.live_count == 0 and pool.expired == 2, "gone at 21 frames (0.35 s)"
    print("[PASS] test_shards_expire_at_035_seconds passed (alive at 0.325 s and 0.333 s, gone at 0.35 s)")


def test_no_shard_hits_the_enemy_that_made_it():
    origin = _enemy(100, 0, hp=100)
    other = _enemy(200, 0, hp=100)
    enemies = [origin, other]
    pool = ShardPool(size=24)
    split_crit(pool, _crit(x=60.0, damage=30), 100.0, 0.0, origin)  # the impact sits inside the origin
    log, deal = _recorder()
    for _ in range(40):
        pool.step(enemies, FRAME, deal, _const_radius)
    targets = [e for e, _ in log]
    assert all(t is not origin for t in targets), "a shard hit its origin"
    assert origin.hp == 100, origin.hp
    assert len(targets) == 1 and targets[0] is other, "only the straight shard reaches the other enemy"
    assert pool.hits == 1 and pool.expired == 2, (pool.hits, pool.expired)

    lone = ShardPool(size=24)
    lone_origin = _enemy(100, 0, hp=100)
    split_crit(lone, _crit(x=60.0, damage=30), 100.0, 0.0, lone_origin)
    log2, deal2 = _recorder()
    for _ in range(40):
        lone.step([lone_origin], FRAME, deal2, _const_radius)
    assert log2 == [] and lone.hits == 0 and lone.expired == 3, (log2, lone.hits, lone.expired)
    assert lone_origin.hp == 100
    print("[PASS] test_no_shard_hits_the_enemy_that_made_it passed "
          "(the origin is never hit, even on its own impact point; the straight shard hits the other enemy)")


def test_impact_point_is_where_the_path_enters_the_body():
    enemy = Vec2(130.0, 0.0)
    # The path runs 100 -> 115 along +x. A body of reach 18 at x=130 is entered at x=112.
    x, y = impact_point(Vec2(100.0, 0.0), Vec2(115.0, 0.0), enemy, 18.0)
    assert abs(x - 112.0) < 1e-9 and abs(y) < 1e-9, (x, y)
    # A path that starts inside the body gives its own start.
    x2, y2 = impact_point(Vec2(120.0, 0.0), Vec2(135.0, 0.0), enemy, 18.0)
    assert abs(x2 - 120.0) < 1e-9, x2
    # A path with no length gives its end point.
    assert impact_point(Vec2(5.0, 5.0), Vec2(5.0, 5.0), enemy, 18.0) == (5.0, 5.0)
    print("[PASS] test_impact_point_is_where_the_path_enters_the_body passed (entry at 112, a start inside at 120)")


def test_nothing_happens_when_shards_are_disabled():
    saved = _save()
    try:
        config.ENABLE_SHARDS = False
        pool = ShardPool(size=24)
        origin = _enemy(200, 0)
        assert split_crit(pool, _crit(), 150.0, 0.0, origin) == 0
        assert pool.spawned == 0 and pool.live_count == 0
        log, deal = _recorder()
        assert pool.step([origin], FRAME, deal, _const_radius) == 0 and log == []

        g = Game()
        g.set_visible(False)
        try:
            s = _new_run(g)
            assert g.shard_pool is None, "no pool is built when the switch is off"
            enemy = Enemy(pos=Vec2(130.0, 0.0), hp=100, speed=0.0, behavior="chaser")
            s.enemies[:] = [enemy]
            s.projectiles.append(_crit(x=100.0, damage=30))
            for _ in range(30):
                g._fixed_step()
                if enemy.hp < 100:
                    break
            assert enemy.hp == 70, enemy.hp  # the bullet's own 30, and nothing from shards
            g.on_draw()
        finally:
            g.close()
    finally:
        _restore(saved)
    print("[PASS] test_nothing_happens_when_shards_are_disabled passed "
          "(no spawn, no pool, the crit bullet deals only its own damage)")


def test_shards_draw_in_the_shot_colour():
    railgun = _crit(weapon_name="Hyper Railgun")
    assert shard_colour(railgun, None) == (120, 245, 255), shard_colour(railgun, None)
    assert shard_colour(railgun, (10, 200, 255)) == (10, 200, 255)
    pool = ShardPool(size=24)
    split_crit(pool, railgun, 0.0, 0.0, _enemy(200, 0), tint=None)
    assert all((sh.r, sh.g, sh.b) == (120, 245, 255) for sh in pool.live_shards())
    pool2 = ShardPool(size=24)
    split_crit(pool2, railgun, 0.0, 0.0, _enemy(200, 0), tint=(10, 200, 255))
    assert all((sh.r, sh.g, sh.b) == (10, 200, 255) for sh in pool2.live_shards())
    print("[PASS] test_shards_draw_in_the_shot_colour passed "
          "(the skin's bullet tint wins; with no tint, the weapon colour)")


def test_draw_places_fades_hides_and_reduce_motion_holds_the_shimmer():
    batch = _batch()
    saved = _save()
    try:
        config.REDUCE_MOTION = True
        pool = ShardPool(batch, size=24)
        assert pool._bank is not None
        pool.spawn(10.0, 20.0, 540.0, 0.0, 11, None, (200, 100, 50))
        pool.draw(0.0, 0.0, 0.0)
        bank = pool._bank
        ix, iy = to_iso(Vec2(10.0, 20.0), Vec2(0.0, 0.0))
        assert abs(bank._translate[0] - ix) < 1e-3 and abs(bank._translate[1] - iy) < 1e-3, (bank._translate[0], ix)
        assert bank._sc[3] == 255, bank._sc[3]

        pool.draw(0.37, 0.0, 0.0)  # reduced motion: the same time-based pose at another time
        assert bank._sc[3] == 255, "no shimmer under reduced motion"
        pool.step([], 0.175, _recorder()[1], _const_radius)  # the shard has moved, and half its life is gone
        pool.draw(0.5, 0.0, 0.0)
        assert 120 <= bank._sc[3] <= 135, bank._sc[3]
        assert abs(pool.live_shards()[0].x - (10.0 + 540.0 * 0.175)) < 1e-6, "reduced motion keeps the movement"

        pool.step([], 0.2, _recorder()[1], _const_radius)  # past 0.35 s
        pool.draw(0.6, 0.0, 0.0)
        assert bank._sc[3] == 0 and pool.live_count == 0, "an ended shard is hidden"

        config.REDUCE_MOTION = False
        full = ShardPool(batch, size=4)
        full.spawn(0.0, 0.0, 0.0, 0.0, 5, None, (255, 255, 255))
        seen = set()
        for k in range(40):
            full.draw(k * 0.05, 0.0, 0.0)
            seen.add(full._bank._sc[3])
        assert len(seen) > 1, "full motion shimmers"
    finally:
        _restore(saved)
    print("[PASS] test_draw_places_fades_hides_and_reduce_motion_holds_the_shimmer passed "
          "(placed at to_iso, fades to 0 and hides; reduced motion holds the pose, full motion shimmers)")


def test_steady_frames_build_no_new_objects():
    saved = _save()
    try:
        config.SHARD_SECONDS = 1000.0  # the shards live through the measurement
        config.REDUCE_MOTION = False   # the shimmer runs too
        batch = _batch()
        pool = ShardPool(batch, size=24)
        far = [_enemy(-400.0, -1000.0 + 40.0 * i) for i in range(10)]  # off every path
        for i in range(24):
            pool.spawn(float(i), 0.0, 20.0, 0.0, 3, None, (255, 255, 255))
        log, deal = _recorder()
        radius = _const_radius
        t = 0.0
        for _ in range(30):
            t += FRAME
            pool.step(far, FRAME, deal, radius)
            pool.draw(t, 0.0, 0.0)
        gc.collect()
        tracemalloc.start(10)
        try:
            snap0 = tracemalloc.take_snapshot()
            for _ in range(3000):
                t += FRAME
                pool.step(far, FRAME, deal, radius)
                pool.draw(t, 0.0, 0.0)
            snap1 = tracemalloc.take_snapshot()
        finally:
            tracemalloc.stop()
        net = _own_growth(snap0, snap1)
        assert pool.live_count == 24 and pool.hits == 0, (pool.live_count, pool.hits)
        assert net < 16384, f"net growth {net} bytes over 3000 frames"
    finally:
        _restore(saved)
    print(f"[PASS] test_steady_frames_build_no_new_objects passed (net {net} bytes over 3000 frames in shards and glow)")


def test_frame_cost_with_live_shards_is_reported():
    saved = _save()
    try:
        config.SHARD_SECONDS = 1000.0
        config.REDUCE_MOTION = False
        batch = _batch()
        pool = ShardPool(batch, size=24)
        far = [_enemy(-400.0, -1000.0 + 40.0 * i) for i in range(12)]
        deal = _recorder()[1]
        frames = 2000

        def run(n, t0):
            t = t0
            start = time.perf_counter()
            for _ in range(n):
                t += FRAME
                pool.step(far, FRAME, deal, _const_radius)
                pool.draw(t, 0.0, 0.0)
            return (time.perf_counter() - start) * 1000.0 / n, t

        idle_ms, _ = run(frames, 0.0)  # an empty pool: the frame pays only the early returns
        for i in range(24):
            pool.spawn(float(i), 0.0, 20.0, 0.0, 3, None, (255, 255, 255))
        busy_ms, _ = run(frames, 0.0)
        spawn_start = time.perf_counter()
        for _ in range(1000):
            pool.spawn(0.0, 0.0, 20.0, 0.0, 3, None, (255, 255, 255))  # every spawn evicts the oldest
        spawn_us = (time.perf_counter() - spawn_start) * 1e6 / 1000.0
        assert pool.live_count == 24
    finally:
        _restore(saved)
    print(f"[PASS] test_frame_cost_with_live_shards_is_reported passed (step+draw: {busy_ms:.4f} ms per frame with "
          f"24 live shards, {idle_ms:.4f} ms idle; spawn with eviction {spawn_us:.2f} us)")
    assert busy_ms < 2.0, f"24 shards cost {busy_ms:.3f} ms a frame"


def test_a_crit_splits_where_it_enters_an_enemy_in_play():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        assert g.shard_pool is not None, "the pool is built with the run"
        enemy = Enemy(pos=Vec2(130.0, 0.0), hp=100, speed=0.0, behavior="chaser")
        s.enemies[:] = [enemy]
        bullet = _crit(x=100.0, damage=30)
        s.projectiles.append(bullet)
        entry = g._enemy_radius(enemy) + g._projectile_radius(bullet)
        for _ in range(30):
            g._fixed_step()
            if enemy.hp < 100:
                break
        pool = g.shard_pool
        assert enemy.hp == 70, enemy.hp  # the bullet's own 30 damage; no shard has moved yet
        assert pool.spawned == 3 and pool.live_count == 3, (pool.spawned, pool.live_count)
        for sh in pool.live_shards():
            assert sh.origin is enemy, "the struck enemy is the origin"
            assert sh.dmg == 11, sh.dmg
            d = math.hypot(sh.x - enemy.pos.x, sh.y - enemy.pos.y)
            assert abs(d - entry) < 1e-3, (d, entry)  # placed where the bullet's path entered the body
        g.on_draw()
    finally:
        g.close()
    print(f"[PASS] test_a_crit_splits_where_it_enters_an_enemy_in_play passed "
          f"(three shards of 11 at the entry point, {entry:.2f} px from the enemy centre, origin kept at 70 hp)")


def test_a_shard_kill_removes_and_scores_the_enemy_in_play():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        origin = Enemy(pos=Vec2(-200.0, 0.0), hp=100, speed=0.0, behavior="chaser")
        weak = Enemy(pos=Vec2(120.0, 0.0), hp=5, speed=0.0, behavior="chaser")  # one shard's 11 is enough
        s.enemies[:] = [origin, weak]
        split_crit(g.shard_pool, _crit(x=0.0, damage=30), 60.0, 0.0, origin, tint=None)
        kills_before = g.shard_pool.kills
        for _ in range(30):
            g._fixed_step()
            if weak not in s.enemies:
                break
        assert weak not in s.enemies and getattr(weak, "_is_dead", False), "the shard's hit killed the weak enemy"
        assert g.shard_pool.kills == kills_before + 1, (g.shard_pool.kills, kills_before)
        assert origin.hp == 100, "the origin was not hit"
    finally:
        g.close()
    print("[PASS] test_a_shard_kill_removes_and_scores_the_enemy_in_play passed "
          "(a shard hit took a 5 hp enemy out of the run, counted as a shard kill; the origin stayed at 100 hp)")


def test_a_shard_meets_the_reflector_like_the_shot_that_made_it():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        pool = g.shard_pool
        reflector = Enemy(pos=Vec2(130.0, 0.0), hp=100, speed=0.0, behavior="chaser",
                          is_elite=True, elite_affix="reflector", attack_cd=99.0)
        s.enemies[:] = [reflector]
        far_origin = _enemy(-300.0, 0.0)  # a shard's origin, off every path
        # The cooldown is ready, so the first shard is sent back at the player and does no damage.
        pool.spawn(100.0, 0.0, 600.0, 0.0, 11, far_origin, (255, 255, 255))
        for _ in range(30):
            g._fixed_step()
            if pool.hits:
                break
        assert pool.hits == 1 and pool.live_count == 0, (pool.hits, pool.live_count)
        assert reflector.hp == 100, f"a reflected shard must not hurt the reflector ({reflector.hp})"
        back = [p for p in s.projectiles if p.owner == "enemy" and p.damage == 11 and p.vel.x < 0]
        assert len(back) == 1, f"the reflected shard is fired back at the player ({len(back)})"
        assert reflector.ai["reflect_ready_at"] > s.time, "the reflector's cooldown starts"
        # A second shard inside the cooldown hurts the reflector, as a second shot would.
        pool.spawn(100.0, 0.0, 600.0, 0.0, 11, far_origin, (255, 255, 255))
        for _ in range(30):
            g._fixed_step()
            if reflector.hp < 100:
                break
        assert reflector.hp == 89, f"a shard inside the cooldown hurts the reflector ({reflector.hp})"
        g.on_draw()
    finally:
        g.close()
    print("[PASS] test_a_shard_meets_the_reflector_like_the_shot_that_made_it passed "
          "(a shard into a ready reflector is sent back and does no damage; one inside the cooldown does 11)")


def test_a_reflected_crit_does_not_split_and_a_crit_into_the_cooldown_does():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        pool = g.shard_pool
        reflector = Enemy(pos=Vec2(130.0, 0.0), hp=100, speed=0.0, behavior="chaser",
                          is_elite=True, elite_affix="reflector", attack_cd=99.0)
        s.enemies[:] = [reflector]
        bullet = _crit(x=100.0, damage=30)
        s.projectiles.append(bullet)
        for _ in range(30):
            g._fixed_step()
            if bullet not in s.projectiles:
                break
        assert reflector.hp == 100, f"the reflected crit must not hurt the reflector ({reflector.hp})"
        assert pool.spawned == 0 and pool.live_count == 0, f"a reflected crit never splits ({pool.spawned})"
        # A crit inside the cooldown hurts the reflector and splits, with the reflector as the shards' origin.
        second = _crit(x=100.0, damage=30)
        s.projectiles.append(second)
        for _ in range(30):
            g._fixed_step()
            if pool.spawned:
                break
        assert reflector.hp == 70, f"a crit inside the cooldown hurts the reflector ({reflector.hp})"
        assert pool.spawned == 3 and pool.live_count == 3, (pool.spawned, pool.live_count)
        assert all(sh.origin is reflector for sh in pool.live_shards()), "the reflector is the shards' origin"
    finally:
        g.close()
    print("[PASS] test_a_reflected_crit_does_not_split_and_a_crit_into_the_cooldown_does passed "
          "(a reflected crit spawns no shards; one inside the cooldown hurts the reflector and splits)")


def _tank_kill(by_shard: bool, tank_x: float):
    """Kill a 5 hp tank at tank_x with one shard or with one plain bullet. Returns (player hp lost, the blast damage)."""
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        g.player.hp = 500
        g.player.shield = 0
        g.player.invincibility_timer = 0.0
        tank = Enemy(pos=Vec2(tank_x, 0.0), hp=5, speed=0.0, behavior="tank", attack_cd=99.0)
        s.enemies[:] = [tank]
        before = g.player.hp
        if by_shard:
            g.shard_pool.spawn(tank_x - 20.0, 0.0, 600.0, 0.0, 11, _enemy(-300.0, 0.0), (255, 255, 255))
        else:
            bullet = _crit(x=tank_x - 20.0, damage=30)
            bullet.is_crit = False  # a plain bullet: a direct kill with no shards
            s.projectiles.append(bullet)
        for _ in range(30):
            g._fixed_step()
            if tank not in s.enemies:
                break
        assert tank not in s.enemies and getattr(tank, "_is_dead", False), "the tank died"
        return before - g.player.hp, g.balance.tank_death_blast_damage
    finally:
        g.close()


def test_a_shard_kill_of_a_tank_fires_the_death_blast_like_a_direct_kill():
    shard_lost, blast = _tank_kill(True, 50.0)     # 50 px from the player, inside the blast radius
    direct_lost, _ = _tank_kill(False, 50.0)
    far_lost, _ = _tank_kill(True, 100.0)           # 100 px out, past the blast radius
    assert blast > 0, blast
    assert shard_lost == direct_lost == blast, (shard_lost, direct_lost, blast)
    assert far_lost == 0, f"a tank killed outside the blast radius blasts nothing ({far_lost})"
    print(f"[PASS] test_a_shard_kill_of_a_tank_fires_the_death_blast_like_a_direct_kill passed "
          f"(a shard kill and a direct kill both cost the player {blast} hp; outside the radius, none)")


def test_scripted_run_with_forced_crits_reports_shard_hits_and_kills():
    g = Game()
    g.set_visible(False)
    orig_first_hit = ShardPool._first_hit
    try:
        s = _new_run(g)
        g.player.max_hp = 10 ** 6
        g.player.hp = 10 ** 6
        g.auto_shoot = True
        g._temp_crit_chance_bonus = 1.0  # the crit bonus path; spawn_projectiles caps the chance at 85%
        g.mouse_xy = to_iso(Vec2(400.0, 0.0), Vec2(0.0, 0.0))  # aim straight down +x
        enemies = []
        for x in (110, 150, 190, 230, 270):
            for y in (-40, -20, 0, 20, 40):
                enemies.append(Enemy(pos=Vec2(float(x), float(y)), hp=200, speed=0.0, behavior="chaser"))
        s.enemies[:] = enemies

        origin_hits = 0

        def checked(sh, targets, px, py, shard_r, radius_of):
            nonlocal origin_hits
            hit = orig_first_hit(sh, targets, px, py, shard_r, radius_of)
            if hit is not None and hit is sh.origin:
                origin_hits += 1
            return hit

        ShardPool._first_hit = staticmethod(checked)
        try:
            pool = g.shard_pool
            assert pool is not None
            for f in range(900):
                g._fixed_step()
                if f % 5 == 0:
                    g.on_draw()
        finally:
            ShardPool._first_hit = staticmethod(orig_first_hit)

        crit_splits = pool.spawned // 3
        down = sum(1 for e in enemies if e.hp <= 0)
        assert pool.spawned % 3 == 0, pool.spawned
        assert pool.spawned == pool.hits + pool.expired + pool.evicted + pool.live_count, "every shard ends once"
        assert origin_hits == 0, origin_hits
        assert pool.hits > 0, pool.hits
        assert crit_splits > 0
        print(f"[REPORT] forced-crit run, 900 steps (15 s): crit splits {crit_splits} "
              f"({pool.spawned} shards); shard hits {pool.hits}; shard kills {pool.kills}; "
              f"shards expired {pool.expired}, evicted {pool.evicted}, live {pool.live_count}; "
              f"enemies down {down} of {len(enemies)}; hits on their origin {origin_hits}")
    finally:
        g.close()
    print(f"[PASS] test_scripted_run_with_forced_crits_reports_shard_hits_and_kills passed "
          f"({pool.hits} shard hits, {pool.kills} shard kills, {crit_splits} crit splits)")


def run_all():
    test_config_block_and_switch()
    test_crit_splits_into_three_at_the_impact_point()
    test_only_critical_player_bullets_split()
    test_shard_damage_is_35_percent_rounded_half_up()
    test_a_shard_does_not_split()
    test_cap_holds_and_the_oldest_drops_first()
    test_shards_expire_at_035_seconds()
    test_no_shard_hits_the_enemy_that_made_it()
    test_impact_point_is_where_the_path_enters_the_body()
    test_nothing_happens_when_shards_are_disabled()
    test_shards_draw_in_the_shot_colour()
    test_draw_places_fades_hides_and_reduce_motion_holds_the_shimmer()
    test_steady_frames_build_no_new_objects()
    test_frame_cost_with_live_shards_is_reported()
    test_a_crit_splits_where_it_enters_an_enemy_in_play()
    test_a_shard_kill_removes_and_scores_the_enemy_in_play()
    test_a_shard_meets_the_reflector_like_the_shot_that_made_it()
    test_a_reflected_crit_does_not_split_and_a_crit_into_the_cooldown_does()
    test_a_shard_kill_of_a_tank_fires_the_death_blast_like_a_direct_kill()
    test_scripted_run_with_forced_crits_reports_shard_hits_and_kills()
    print("ALL W8 SHARDS TESTS PASSED")


if __name__ == "__main__":
    run_all()
