"""Wave 6 wiring tests: Chain Lightning and Repulsor work in a real run, not only as units.

The unit files (test_w6_chain, test_w6_repulsor) test the modules on their own. These drive the real Game:

    - both kinds can spawn (the pool weights) and draw (the pickup art and glyph);
    - a player's bullet kill throws a chain arc that damages the neighbour, and the arc fades on the next draws;
    - a Repulsor pickup fires on the next fixed step and holds an enemy in range still for the stun, then releases it;
    - a stunned enemy is neither updated nor steered by the batched path.

Plain functions that print [PASS] lines, run from run_all().
"""

import random

import parallel
import chain
import config
import repulsor
from enemy import Enemy
from game import Game
from level import GameState as LevelGameState, POWERUP_POOL_WEIGHTS, _pick_powerup_kind_for_wave
from powerup import PowerUp, apply_powerup
from powerup_art import PICKUP_ART_KINDS, make_pickup_art
from projectile import Projectile
from states import GameStateName
from utils import Vec2

import pyglet

FRAME = 1.0 / 60.0


def _new_run(g):
    """A fresh run in the PLAYING state with no auto-fire and no wave spawns, so each test controls the enemies."""
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.state.wave_active = True
    g.player.pos = Vec2(0.0, 0.0)
    return g.state


def _steps(g, n):
    for _ in range(n):
        g._fixed_step()


def test_both_kinds_spawn_and_draw():
    weights = dict(POWERUP_POOL_WEIGHTS)
    assert weights.get("chain", 0.0) > 0.0 and weights.get("repulsor", 0.0) > 0.0, weights
    assert "chain" in PICKUP_ART_KINDS and "repulsor" not in PICKUP_ART_KINDS

    rng = random.Random(6)
    st = LevelGameState(difficulty="normal")
    st.rng = rng
    seen = set()
    for _ in range(4000):
        seen.add(_pick_powerup_kind_for_wave(st, "wiring-test"))
    assert "chain" in seen and "repulsor" in seen, sorted(seen)

    batch = pyglet.graphics.Batch()
    arc_shapes, offsets = make_pickup_art("chain", batch, config.CHAIN_COLOR, 14)
    assert len(arc_shapes) == 6 and len(offsets) == 6, (len(arc_shapes), len(offsets))
    none_shapes, none_offsets = make_pickup_art("repulsor", batch, config.REPULSOR_COLOR, 14)
    assert none_shapes == [] and none_offsets == [], "Repulsor draws the shared orb only"

    g = Game()
    g.set_visible(False)
    try:
        _new_run(g)
        for kind in ("chain", "repulsor"):
            pu = PowerUp(pos=Vec2(40.0, 0.0), kind=kind)
            g.visuals.ensure_powerup(pu)
            g.visuals.sync_powerup(pu, Vec2(0.0, 0.0))
            assert id(pu) in g.visuals._power_handles, kind
    finally:
        g.close()
    print("[PASS] test_both_kinds_spawn_and_draw passed (both kinds spawn, the arc has six dots, both draw)")


def test_chain_kill_in_play_throws_an_arc_that_fades():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        assert g.chain_pool is not None and g.chain_pool.size == config.CHAIN_ARC_POOL
        apply_powerup(g.player, PowerUp(pos=Vec2(0.0, 0.0), kind="chain"), s.time)
        assert chain.chain_active(g.player, s.time)

        victim = Enemy(pos=Vec2(200.0, 0.0), hp=1, speed=0.0, behavior="chaser")
        neighbour = Enemy(pos=Vec2(260.0, 0.0), hp=100, speed=0.0, behavior="chaser")
        s.enemies[:] = [victim, neighbour]
        # A player bullet travelling into the victim. Its damage is what the arc scales from.
        s.projectiles.append(Projectile(
            pos=Vec2(150.0, 0.0), vel=Vec2(900.0, 0.0), damage=int(g.player.damage), ttl=2.0, owner="player",
        ))
        expected = chain.chain_damage(g.player.damage)

        killed = False
        for _ in range(30):
            g._fixed_step()
            if victim not in s.enemies:
                killed = True
                break
        assert killed, "the player's bullet should kill the one-hp victim within 30 steps"
        assert neighbour.hp == 100 - expected, (neighbour.hp, expected)
        assert g.chain_pool.live_count == 1, "one kill throws one arc"

        g.on_draw()  # PlayingState.draw places the arc through the pool
        assert g.chain_pool.live_count == 1, "a young arc is still live"

        _steps(g, 18)  # 0.3 s of run time, longer than CHAIN_ARC_SECONDS
        g.on_draw()
        assert g.chain_pool.live_count == 0, "the arc has faded out and was hidden"
    finally:
        g.close()
    print(f"[PASS] test_chain_kill_in_play_throws_an_arc_that_fades passed (neighbour -{expected} hp, arc fades)")


def test_repulsor_pickup_fires_and_holds_enemy_in_range():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        near = Enemy(pos=Vec2(120.0, 0.0), hp=50, speed=60.0, behavior="chaser")
        s.enemies[:] = [near]
        apply_powerup(g.player, PowerUp(pos=Vec2(0.0, 0.0), kind="repulsor"), s.time)

        _steps(g, 1)  # the pending shockwave fires on this step, before enemies move
        assert repulsor_stunned(near, s.time), "the enemy in range is stunned by the shockwave"
        held = (near.pos.x, near.pos.y)

        # 80 steps is 1.33 s, inside the 1.5 s stun. The enemy must not move at all.
        for _ in range(80):
            _steps(g, 1)
            assert (near.pos.x, near.pos.y) == held, "a stunned enemy moved in play"

        # Past the stun the same enemy moves again.
        _steps(g, 60)
        assert not repulsor_stunned(near, s.time), "the stun has ended"
        assert (near.pos.x, near.pos.y) != held, "the enemy moves again after the stun"
    finally:
        g.close()
    print("[PASS] test_repulsor_pickup_fires_and_holds_enemy_in_range passed (stunned 1.33 s in play, then moves)")


def repulsor_stunned(enemy, now):
    return repulsor.is_stunned(enemy, now)


def test_stunned_enemy_is_not_steered_in_batch():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        stunned = Enemy(pos=Vec2(100.0, 0.0), hp=50, speed=60.0, behavior="chaser")
        free = Enemy(pos=Vec2(-100.0, 0.0), hp=50, speed=60.0, behavior="chaser")
        stunned.stun_until = s.time + 5.0
        s.enemies[:] = [stunned, free]
        batcher = parallel.SteerBatcher(workers=0, min_enemies=0)
        try:
            updated = parallel.update_enemies_batched(s, g, FRAME, g.player.pos, Vec2(0.0, 0.0), batcher)
        finally:
            batcher.close()
        assert id(free) in updated, "the free enemy is updated through the batch"
        assert id(stunned) not in updated, "the stunned enemy is neither updated nor steered"
    finally:
        g.close()
    print("[PASS] test_stunned_enemy_is_not_steered_in_batch passed (stunned excluded from the batch)")


def test_settings_backdrop_follows_the_window():
    """The Settings backdrop covers the window at every size, not only the size it was built at."""
    g = Game()
    g.set_visible(False)
    try:
        menu = g.settings_menu
        for w, h in ((1920, 1080), (980, 620)):
            menu.resize(w, h)
            for rect in (menu._bg_a, menu._bg_b):
                assert (rect.width, rect.height) == (w, h), (w, h, rect.width, rect.height)
    finally:
        g.close()
    print("[PASS] test_settings_backdrop_follows_the_window passed (both backdrop layers at 1920x1080 and 980x620)")


def test_ultra_flash_holds_full_size_under_reduce_motion():
    """Reduced motion: the Ultra flash opens at full size and only fades. Full motion still swells it."""
    g = Game()
    g.set_visible(False)
    prev = config.REDUCE_MOTION
    try:
        _new_run(g)  # the visuals, and so the juice overlay, exist once a run is set up
        juice = g.visuals._juice
        scales = {}
        for reduced in (True, False):
            config.REDUCE_MOTION = reduced
            juice.trigger_ultra_flash(Vec2(0.0, 0.0), (255, 240, 180), 200.0, 0.0)
            juice.sync(0.03, Vec2(0.0, 0.0), 1.0, 980, 620)
            early = juice._flash.scale
            juice.sync(0.15, Vec2(0.0, 0.0), 1.0, 980, 620)
            scales[reduced] = (early, juice._flash.scale)
        assert scales[True][0] == scales[True][1], f"reduced motion swelled the flash: {scales[True]}"
        assert scales[False][1] > scales[False][0], f"full motion should swell the flash: {scales[False]}"
    finally:
        config.REDUCE_MOTION = prev
        g.close()
    print("[PASS] test_ultra_flash_holds_full_size_under_reduce_motion passed (reduced: no swell; full: swells)")


def run_all():
    test_both_kinds_spawn_and_draw()
    test_ultra_flash_holds_full_size_under_reduce_motion()
    test_chain_kill_in_play_throws_an_arc_that_fades()
    test_repulsor_pickup_fires_and_holds_enemy_in_range()
    test_stunned_enemy_is_not_steered_in_batch()
    test_settings_backdrop_follows_the_window()


if __name__ == "__main__":
    run_all()
