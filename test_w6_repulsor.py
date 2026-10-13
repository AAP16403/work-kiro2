"""Wave 6 Repulsor tests: a pickup fires a shockwave, then the Repulsor cools down.

Covers: the config keys and the common tier; enemy bullets inside range pushed outward, slow ones removed, fast
ones kept, and player bullets and out-of-range bullets untouched; enemies in range stunned for 1.5 s and not moving
while stunned (the caller's gate, around the real update_enemy); the cooldown blocking a second fire; a pickup
during the cooldown storing one charge, capped at 2, and firing when the cooldown ends; the HUD countdown; the
ring and dust on the particle system, the ring holding its size under reduced motion, and no dust under reduced
motion; idle frames allocating nothing; and the Guide Powerups entry reading its numbers from config.

Plain functions that print [PASS] lines, run from run_all().
"""

import math
import tracemalloc
from types import SimpleNamespace

import config
import motion
import powerup
import repulsor
from enemy import Enemy, update_enemy
from game import Game
from menu import GuideMenu
from powerup import PowerUp, apply_powerup, format_timed_powerups_hud
from player import Player
from projectile import Projectile
from states import GameStateName
from utils import Vec2

import guide_info

RANGE = float(config.REPULSOR_RANGE)
STUN = float(config.REPULSOR_STUN_SECONDS)
COOL = float(config.REPULSOR_COOLDOWN_SECONDS)
CLEAR = float(config.REPULSOR_CLEAR_SPEED)
PUSH = float(config.REPULSOR_PUSH_SPEED)


def _player():
    return Player(pos=Vec2(0.0, 0.0))


def _run_state():
    return SimpleNamespace(projectiles=[], enemies=[])


def _bullet(x, y, vx, vy, owner="enemy"):
    return Projectile(pos=Vec2(x, y), vel=Vec2(vx, vy), damage=8, ttl=3.0, owner=owner)


def _pickup(player, now):
    apply_powerup(player, PowerUp(pos=Vec2(0.0, 0.0), kind="repulsor"), now)


def _radial(p, origin=Vec2(0.0, 0.0)):
    """Outward speed of a bullet, measured from the shockwave origin."""
    d = p.pos - origin
    n = d.length()
    return (p.vel.x * d.x + p.vel.y * d.y) / n if n > 1e-9 else 0.0


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _ring_particles(ps):
    return [p for p in ps.particles if p.kind == "ring"]


def _dot_particles(ps):
    return [p for p in ps.particles if p.kind == "dot"]


def test_config_and_common_tier():
    assert RANGE == 220.0 and STUN == 1.5 and COOL == 12.0, (RANGE, STUN, COOL)
    assert config.REPULSOR_MAX_CHARGES == 2
    assert "repulsor" not in powerup.RARE_POWERUP_KINDS, "Repulsor is the common tier"
    assert not powerup.is_rare_powerup("repulsor")
    print("[PASS] test_config_and_common_tier passed (220 px, 1.5 s, 12 s, 2 charges, common tier)")


def test_bullets_pushed_outward_slow_removed_fast_kept():
    player = _player()
    s = _run_state()
    inward = _bullet(100.0, 0.0, -210.0, 0.0)        # inside, flying straight at the player, fast
    slow = _bullet(0.0, 150.0, 0.0, 40.0)            # inside, slower than CLEAR_SPEED
    outward_fast = _bullet(-180.0, 0.0, -300.0, 0.0)  # inside, already leaving faster than PUSH
    outside = _bullet(300.0, 0.0, -40.0, 0.0)        # outside the range, slow: must not be touched
    mine = _bullet(50.0, 50.0, 0.0, 10.0, owner="player")  # a player shot in range, slow: never touched
    s.projectiles.extend([inward, slow, outward_fast, outside, mine])
    radial_before = _radial(inward)
    assert radial_before < 0.0 and inward.vel.length() > CLEAR

    removed, kept_in_range, stunned = repulsor.fire(player, s, 10.0)
    assert (removed, kept_in_range, stunned) == (1, 2, 0), (removed, kept_in_range, stunned)
    assert slow not in s.projectiles, "a slow enemy bullet in range must be removed"
    assert inward in s.projectiles and outward_fast in s.projectiles, "fast enemy bullets in range are kept"
    assert outside in s.projectiles and mine in s.projectiles, "out-of-range and player bullets are kept"
    # Every kept enemy bullet in range now leaves the player at least PUSH_SPEED outward.
    assert _radial(inward) >= PUSH - 1e-6, f"inward shot not pushed outward: {_radial(inward)}"
    assert abs(_radial(inward) - PUSH) < 1e-6, "an inward shot is pushed to exactly the outward minimum"
    assert abs(_radial(outward_fast) - 300.0) < 1e-6, "a shot already fast and outward keeps its velocity"
    assert outside.vel.x == -40.0 and mine.vel.y == 10.0, "untouched bullets keep their velocity"
    print("[PASS] test_bullets_pushed_outward_slow_removed_fast_kept passed (slow removed, fast pushed or kept)")


def test_fast_bullet_in_range_keeps_its_speed_when_pushed_outward_already():
    player = _player()
    s = _run_state()
    tangential = _bullet(0.0, 120.0, 200.0, 0.0)  # sideways at 200 px/s: radial 0, pushed outward
    s.projectiles.append(tangential)
    repulsor.fire(player, s, 5.0)
    assert tangential in s.projectiles and abs(_radial(tangential) - PUSH) < 1e-6
    assert abs(tangential.vel.x - 200.0) < 1e-6, "the tangential part of the velocity is kept"
    print("[PASS] test_fast_bullet_in_range_keeps_its_speed_when_pushed_outward_already passed")


def test_enemies_in_range_stunned_and_held_still_for_1_5_seconds():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        g.player.pos = Vec2(0.0, 0.0)
        near = Enemy(pos=Vec2(120.0, 0.0), hp=20, speed=60.0, behavior="chaser")
        far = Enemy(pos=Vec2(300.0, 0.0), hp=20, speed=60.0, behavior="chaser")
        s.enemies[:] = [near, far]
        t0 = 10.0
        removed, kept, stunned = repulsor.fire(g.player, s, t0)
        assert stunned == 1, f"only the enemy inside range is stunned, got {stunned}"
        assert abs(float(near.stun_until) - (t0 + STUN)) < 1e-9
        assert not repulsor.is_stunned(far, t0), "an enemy outside the range is not stunned"

        dt = 1.0 / 60.0
        held = (near.pos.x, near.pos.y)
        t = t0
        frozen_ok = True
        while t < t0 + STUN - 1e-6:
            # The caller's gate: a stunned enemy's update is skipped; the far enemy runs normally.
            if not repulsor.is_stunned(near, t):
                update_enemy(near, g.player.pos, s, dt, g, player_vel=Vec2(0.0, 0.0))
            update_enemy(far, g.player.pos, s, dt, g, player_vel=Vec2(0.0, 0.0))
            if (near.pos.x, near.pos.y) != held:
                frozen_ok = False
            t += dt
        assert frozen_ok, "a stunned enemy moved during the stun"
        assert far.pos.x != 300.0 or far.pos.y != 0.0, "the control enemy outside the range should have moved"

        # The stun ends at t0 + 1.5 s. After that the same enemy moves again.
        t = t0 + STUN + 0.01
        assert not repulsor.is_stunned(near, t)
        for _ in range(30):
            update_enemy(near, g.player.pos, s, dt, g, player_vel=Vec2(0.0, 0.0))
        assert (near.pos.x, near.pos.y) != held, "the enemy moves again after the stun"
    finally:
        g.close()
    print("[PASS] test_enemies_in_range_stunned_and_held_still_for_1_5_seconds passed (stunned 1.5 s, held still, then moves)")


def test_cooldown_blocks_a_second_fire():
    player = _player()
    s = _run_state()
    _pickup(player, 10.0)
    assert repulsor.update(player, s, 10.0) == 1, "a pickup on a ready Repulsor fires"
    assert abs(player.repulsor_state.cooldown_until - (10.0 + COOL)) < 1e-9
    assert repulsor.update(player, s, 10.5) == 0 and repulsor.update(player, s, 21.9) == 0, "cooldown blocks a fire"
    _pickup(player, 15.0)  # a pickup during the cooldown stores a charge: it does not fire early
    assert repulsor.update(player, s, 15.0) == 0 and repulsor.update(player, s, 21.99) == 0
    assert repulsor.update(player, s, 22.0) == 1, "the stored charge fires when the cooldown ends"
    assert repulsor.update(player, s, 30.0) == 0, "the next cooldown blocks again"
    print("[PASS] test_cooldown_blocks_a_second_fire passed (no fire during 12 s, stored charge fires at 22 s)")


def test_second_pickup_adds_a_charge_up_to_two():
    player = _player()
    s = _run_state()
    _pickup(player, 10.0)
    assert repulsor.update(player, s, 10.0) == 1
    fires = 1
    for t in (10.5, 10.6, 10.7, 10.8, 10.9):  # five pickups during the cooldown
        _pickup(player, t)
    st = player.repulsor_state
    assert st.charges == 2, f"charges must cap at 2, got {st.charges}"
    assert repulsor.update(player, s, 10.9) == 0, "no fire while cooling down"
    fires += repulsor.update(player, s, 22.0)
    assert st.charges == 1 and abs(st.cooldown_until - 34.0) < 1e-9, (st.charges, st.cooldown_until)
    fires += repulsor.update(player, s, 34.0)
    assert st.charges == 0 and abs(st.cooldown_until - 46.0) < 1e-9
    fires += repulsor.update(player, s, 40.0)
    assert fires == 3, f"one instant shot and two stored charges, got {fires}"
    assert repulsor.update(player, s, 46.5) == 0, "no charges left, nothing fires"
    print("[PASS] test_second_pickup_adds_a_charge_up_to_two passed (cap 2, one fire per cooldown)")


def test_hud_countdown_and_stored_charges():
    player = _player()
    s = _run_state()
    assert format_timed_powerups_hud(player, 0.0) == "", "no Repulsor text before any pickup"
    _pickup(player, 10.0)
    repulsor.update(player, s, 10.0)
    assert format_timed_powerups_hud(player, 10.0) == "Repulsor 12s", format_timed_powerups_hud(player, 10.0)
    assert format_timed_powerups_hud(player, 15.0) == "Repulsor 7s"
    assert format_timed_powerups_hud(player, 21.5) == "Repulsor 1s"
    assert format_timed_powerups_hud(player, 22.0) == "", "ready with no charge shows nothing"
    _pickup(player, 12.0)
    assert format_timed_powerups_hud(player, 15.0) == "Repulsor 7s x1"
    print("[PASS] test_hud_countdown_and_stored_charges passed (ceil countdown, x charges, empty when ready)")


def test_ring_and_dust_on_the_particle_system():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        g.player.pos = Vec2(0.0, 0.0)
        ps = g.particle_system
        ps.particles.clear()
        near = Enemy(pos=Vec2(90.0, 40.0), hp=20, speed=60.0, behavior="chaser")
        far = Enemy(pos=Vec2(330.0, 0.0), hp=20, speed=60.0, behavior="chaser")
        s.enemies[:] = [near, far]
        _pickup(g.player, 5.0)
        assert repulsor.update(g.player, s, 5.0, ps) == 1
        rings = _ring_particles(ps)
        assert len(rings) == 1 and rings[0].grow, "one growing ring when reduced motion is off"
        screen_r = RANGE * math.sqrt(2.0) * float(config.ISO_SCALE_X)  # add_ground_ring projects the world radius
        assert abs(rings[0].size - screen_r) < 1e-6, (rings[0].size, screen_r)
        assert abs(rings[0].max_life - float(config.REPULSOR_RING_SECONDS)) < 1e-6
        assert len(_dot_particles(ps)) == int(config.REPULSOR_DUST_COUNT), "dust on the one stunned enemy"

        ps.particles.clear()
        config.REDUCE_MOTION = True
        try:
            assert motion.reduced()
            _pickup(g.player, 40.0)
            repulsor.update(g.player, s, 40.0, ps)
            rings = _ring_particles(ps)
            assert len(rings) == 1 and rings[0].grow is False, "reduced motion: the ring holds its full size"
            assert _dot_particles(ps) == [], "reduced motion: no dust puff"
        finally:
            config.REDUCE_MOTION = False
    finally:
        g.close()
    print("[PASS] test_ring_and_dust_on_the_particle_system passed (grow ring, dust for stunned enemies, static under reduced motion)")


def test_ring_uses_the_pooled_particle_sprites():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        g.player.pos = Vec2(0.0, 0.0)
        ps = g.particle_system
        ps.particles.clear()
        s.enemies[:] = [Enemy(pos=Vec2(60.0, 0.0), hp=20, speed=60.0, behavior="chaser")]
        t = 0.0
        for _ in range(40):  # forty shockwaves, each rendered and aged out
            _pickup(g.player, t)
            repulsor.update(g.player, s, t, ps)
            for _f in range(40):
                t += 1.0 / 60.0
                ps.update(1.0 / 60.0)
                ps.render(Vec2(0.0, 0.0))
            t += float(config.REPULSOR_COOLDOWN_SECONDS)  # the cooldown ends before the next pickup
            repulsor.update(g.player, s, t, ps)
        pooled = len(ps._ring_sprites)
        assert pooled <= 2, f"the ring pool must reuse sprites, found {pooled} after 40 shockwaves"
    finally:
        g.close()
    print(f"[PASS] test_ring_uses_the_pooled_particle_sprites passed ({pooled} ring sprites after 40 shockwaves)")


def test_idle_frames_allocate_nothing():
    player = _player()
    s = _run_state()
    _pickup(player, 1.0)
    repulsor.update(player, s, 1.0)  # fire once; the state object now exists
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        for i in range(5000):
            repulsor.update(player, s, 2.0 + i * 1e-4)  # cooling down, nothing pending
        after = tracemalloc.get_traced_memory()[0]
    finally:
        tracemalloc.stop()
    growth = after - before
    assert growth < 4096, f"idle Repulsor frames kept {growth} bytes over 5000 frames"
    assert repulsor.update(_player(), s, 3.0) == 0, "a player with no Repulsor state fires nothing"
    print(f"[PASS] test_idle_frames_allocate_nothing passed (net {growth} bytes over 5000 frames)")


def test_guide_has_the_repulsor_entry():
    entries = {e["key"]: e for e in GuideMenu.POWERUP_INFO}
    assert "repulsor" in entries, "the Powerups tab has no Repulsor entry"
    e = entries["repulsor"]
    for field in ("name", "icon", "what", "deal", "lore"):
        assert str(e.get(field, "")).strip(), f"Repulsor entry missing {field}"
    assert "220 px" in e["what"] and "1.5s" in e["what"], e["what"]
    assert "12s" in e["deal"] and "up to 2" in e["deal"], e["deal"]

    saved = (config.REPULSOR_RANGE, config.REPULSOR_STUN_SECONDS, config.REPULSOR_COOLDOWN_SECONDS)
    try:
        config.REPULSOR_RANGE = 300.0
        config.REPULSOR_STUN_SECONDS = 2.0
        config.REPULSOR_COOLDOWN_SECONDS = 9.0
        moved = {x["key"]: x for x in guide_info.powerup_entries()}["repulsor"]
    finally:
        config.REPULSOR_RANGE, config.REPULSOR_STUN_SECONDS, config.REPULSOR_COOLDOWN_SECONDS = saved
    assert "300 px" in moved["what"] and "2s" in moved["what"] and "9s" in moved["deal"], moved
    print("[PASS] test_guide_has_the_repulsor_entry passed (on the Powerups tab, numbers read from config)")


def run_all():
    test_config_and_common_tier()
    test_bullets_pushed_outward_slow_removed_fast_kept()
    test_fast_bullet_in_range_keeps_its_speed_when_pushed_outward_already()
    test_cooldown_blocks_a_second_fire()
    test_second_pickup_adds_a_charge_up_to_two()
    test_hud_countdown_and_stored_charges()
    test_idle_frames_allocate_nothing()
    test_guide_has_the_repulsor_entry()
    test_enemies_in_range_stunned_and_held_still_for_1_5_seconds()
    test_ring_and_dust_on_the_particle_system()
    test_ring_uses_the_pooled_particle_sprites()
    print("\nALL W6 REPULSOR TESTS PASSED")


if __name__ == "__main__":
    run_all()
