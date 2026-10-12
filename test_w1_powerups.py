"""Deterministic regression tests for the four timed powerups: Ricochet, Homing, Time Slow and Magnet.

Run from the project root: python test_w1_powerups.py. Every test prints a [PASS] line.
Simulation tests drive PlayingState through Game.fsm.update with a fixed 1/60 step and a seeded run.
"""

import math
from collections import Counter

import pyglet

import config
import level
import shot_mods
import states
from enemy import Enemy
from game import Game
from level import GameState as LevelGameState, POWERUP_POOL_WEIGHTS
from menu import GuideMenu
from player import Player
from powerup import (
    POWERUP_NAMES,
    RARE_POWERUP_KINDS,
    TIMED_POWERUPS,
    PowerUp,
    apply_powerup,
    enemy_time_scale,
    expire_timed_effects,
    format_timed_powerups_hud,
    is_rare_powerup,
    pickup_magnet_mods,
    powerup_popup_name,
    timed_active,
)
from powerup_art import PICKUP_ART_KINDS, make_pickup_art
from projectile import Projectile
from hazards import LaserBeam
from states import GameStateName
from utils import Vec2, to_iso

NEW_KINDS = ("ricochet", "homing", "time_slow", "magnet")
FRAME = 1.0 / 60.0
ARENA_R = 400.0


class RecordingAudio:
    """Stand-in for AudioManager that records the sound names played."""

    def __init__(self):
        self.played = []

    def play(self, name, *args, **kwargs):
        self.played.append(name)

    def play_music(self, *args, **kwargs):
        pass

    def duck(self, *args, **kwargs):
        pass

    def update(self, dt):
        pass


def _new_game():
    """A hidden Game in PlayingState with auto-fire off, a recording audio stub and one idle anchor enemy.

    The anchor is a stationary egg sac far from the arena centre. It keeps the wave-clear logic from
    firing during a test, and tests can add their own actors next to it.
    """
    g = Game()
    g.set_visible(False)
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.audio = RecordingAudio()
    g.state.wave_active = True
    g.state.enemies.append(Enemy(pos=Vec2(-380.0, -380.0), hp=30, speed=0.0, behavior="egg_sac"))
    return g


class _HeldKeys(dict):
    """Writable stand-in for pyglet's KeyStateHandler: unknown keys read as not held."""

    def __missing__(self, key):
        return False


def _close(g):
    try:
        g.close()
    except Exception:
        pass


def _tick(g, dt=FRAME):
    g.fsm.update(dt)


def test_timed_durations_match_the_spec():
    assert config.RICOCHET_DURATION == 8.0
    assert config.HOMING_DURATION == 6.0
    assert config.TIME_SLOW_DURATION == 4.0
    assert config.MAGNET_DURATION == 10.0
    assert config.HOMING_RANGE == 260.0
    assert config.TIME_SLOW_SCALE == 0.5
    assert config.MAGNET_RADIUS_MULT == 3.0
    print("[PASS] test_timed_durations_match_the_spec passed (8s, 6s, 4s, 10s, 260 px, half speed, x3 magnet)")


def test_timed_powerups_apply_refresh_and_do_not_stack():
    p = Player(pos=Vec2(0.0, 0.0))
    for kind, (field, duration_name) in TIMED_POWERUPS.items():
        duration = float(getattr(config, duration_name))
        apply_powerup(p, PowerUp(Vec2(0.0, 0.0), kind), 10.0)
        assert abs(getattr(p, field) - (10.0 + duration)) < 1e-9, f"{kind} did not set its expiry"
        apply_powerup(p, PowerUp(Vec2(0.0, 0.0), kind), 12.0)
        assert abs(getattr(p, field) - (12.0 + duration)) < 1e-9, f"{kind} re-pickup must restart the timer, not add to it"
    print("[PASS] test_timed_powerups_apply_refresh_and_do_not_stack passed (expiry set, re-pickup refreshes)")


def test_expiry_clears_every_timed_state():
    for kind, (field, duration_name) in TIMED_POWERUPS.items():
        duration = float(getattr(config, duration_name))
        p = Player(pos=Vec2(0.0, 0.0))
        apply_powerup(p, PowerUp(Vec2(0.0, 0.0), kind), 0.0)
        expire_timed_effects(p, duration - 0.01)
        assert timed_active(p, field, duration - 0.01), f"{kind} expired early"
        expire_timed_effects(p, duration)
        assert getattr(p, field) == 0.0, f"{kind} did not clear its expiry field"
        assert not timed_active(p, field, duration), f"{kind} still reads as active after expiry"

    p = Player(pos=Vec2(0.0, 0.0))
    for kind in NEW_KINDS:
        apply_powerup(p, PowerUp(Vec2(0.0, 0.0), kind), 0.0)
    assert enemy_time_scale(p, 1.0) == config.TIME_SLOW_SCALE
    assert pickup_magnet_mods(p, 1.0) == (config.MAGNET_RADIUS_MULT, config.MAGNET_PULL_MULT)
    assert format_timed_powerups_hud(p, 1.0) != ""
    expire_timed_effects(p, 11.0)
    assert enemy_time_scale(p, 11.0) == 1.0
    assert pickup_magnet_mods(p, 11.0) == (1.0, 1.0)
    assert format_timed_powerups_hud(p, 11.0) == ""
    assert all(getattr(p, field) == 0.0 for field, _n in TIMED_POWERUPS.values())
    print("[PASS] test_expiry_clears_every_timed_state passed (each timer clears at its duration, state reads inactive)")


def test_timed_hud_text_counts_down_and_drops_expired_entries():
    p = Player(pos=Vec2(0.0, 0.0))
    apply_powerup(p, PowerUp(Vec2(0.0, 0.0), "ricochet"), 0.0)
    assert format_timed_powerups_hud(p, 0.0) == "Ricochet 8s"
    assert format_timed_powerups_hud(p, 7.2) == "Ricochet 1s", "the last partial second must still show"
    assert format_timed_powerups_hud(p, 8.0) == ""
    q = Player(pos=Vec2(0.0, 0.0))
    apply_powerup(q, PowerUp(Vec2(0.0, 0.0), "homing"), 0.0)
    apply_powerup(q, PowerUp(Vec2(0.0, 0.0), "magnet"), 0.0)
    assert format_timed_powerups_hud(q, 0.0) == "Homing 6s  Magnet 10s"
    assert format_timed_powerups_hud(q, 5.5) == "Homing 1s  Magnet 5s"
    print("[PASS] test_timed_hud_text_counts_down_and_drops_expired_entries passed (ceil countdown, expired text dropped)")


def test_ricochet_bounces_once_off_the_rim_then_is_spent():
    player = Player(pos=Vec2(0.0, 0.0))
    apply_powerup(player, PowerUp(Vec2(0.0, 0.0), "ricochet"), 0.0)
    p = Projectile(Vec2(395.0, 0.0), Vec2(900.0, 0.0), 10, owner="player")
    p.prev_pos = Vec2(385.0, 0.0)
    p.update(FRAME)  # now at x = 410, past the rim at 400
    assert shot_mods.ricochet_step(p, player, 1.0, "circle", ARENA_R) == "bounced"
    assert p.vel.x < 0.0 and abs(p.vel.x + 900.0) < 1e-6 and abs(p.vel.y) < 1e-9, f"velocity not mirrored: {p.vel.x}, {p.vel.y}"
    assert abs(p.pos.x - 390.0) < 0.05 and abs(p.pos.y) < 1e-9, f"overshoot not reflected: {p.pos.x}"
    assert abs(p.prev_pos.x - 400.0) < 0.05, "the bounce point should be the rim"
    assert p.bounces == 1

    p.update(FRAME)  # travelling back inward
    assert shot_mods.ricochet_step(p, player, 1.1, "circle", ARENA_R) == ""
    p.pos = Vec2(ARENA_R + 3.0, 0.0)
    p.vel = Vec2(900.0, 0.0)
    assert shot_mods.ricochet_step(p, player, 1.2, "circle", ARENA_R) == "spent", "a second exit must spend the bullet, not bounce it"
    assert p.bounces == 1, "one bounce per bullet"
    print("[PASS] test_ricochet_bounces_once_off_the_rim_then_is_spent passed (one bounce, mirrored velocity, second exit spends)")


def test_ricochet_mirror_law_holds_for_an_angled_shot():
    theta = math.radians(30.0)
    player = Player(pos=Vec2(0.0, 0.0))
    apply_powerup(player, PowerUp(Vec2(0.0, 0.0), "ricochet"), 0.0)
    prev = Vec2(392.0 * math.cos(theta), 392.0 * math.sin(theta))
    aim = math.radians(30.0 + 17.0)
    vel = Vec2(math.cos(aim), math.sin(aim)) * 900.0
    p = Projectile(prev, vel, 10, owner="player")
    p.update(FRAME)
    assert shot_mods.ricochet_step(p, player, 1.0, "circle", ARENA_R) == "bounced"
    contact = p.prev_pos  # the bounce records the rim contact point here
    assert abs(contact.length() - ARENA_R) < 0.05, "contact point must sit on the rim"
    n = contact.normalized()  # the radial normal at the contact point
    t = Vec2(-n.y, n.x)
    assert abs(p.vel.dot(n) + vel.dot(n)) < 1e-6 * 900.0, "normal component must flip sign"
    assert abs(p.vel.dot(t) - vel.dot(t)) < 1e-6 * 900.0, "tangential component must be kept"
    assert shot_mods.arena_inside(p.pos, "circle", ARENA_R), "reflected position must land back inside"
    print("[PASS] test_ricochet_mirror_law_holds_for_an_angled_shot passed (normal flips, tangent kept, exact on a circle)")


def test_ricochet_is_off_without_the_powerup_and_ignores_enemy_shots():
    plain = Player(pos=Vec2(0.0, 0.0))
    p = Projectile(Vec2(405.0, 0.0), Vec2(900.0, 0.0), 10, owner="player")
    p.prev_pos = Vec2(395.0, 0.0)
    assert shot_mods.ricochet_step(p, plain, 1.0, "circle", ARENA_R) == ""
    assert p.bounces == 0 and p.vel.x == 900.0 and p.pos.x == 405.0, "a plain bullet must not change"

    boosted = Player(pos=Vec2(0.0, 0.0))
    apply_powerup(boosted, PowerUp(Vec2(0.0, 0.0), "ricochet"), 0.0)
    enemy_shot = Projectile(Vec2(405.0, 0.0), Vec2(900.0, 0.0), 10, owner="enemy")
    enemy_shot.prev_pos = Vec2(395.0, 0.0)
    assert shot_mods.ricochet_step(enemy_shot, boosted, 1.0, "circle", ARENA_R) == ""
    assert enemy_shot.bounces == 0 and enemy_shot.vel.x == 900.0, "enemy shots never ricochet"
    print("[PASS] test_ricochet_is_off_without_the_powerup_and_ignores_enemy_shots passed (plain and enemy shots unchanged)")


def test_ricochet_in_the_playing_loop_bounces_then_removes_the_bullet():
    g = _new_game()
    try:
        s = g.state
        R = float(config.ROOM_RADIUS)
        apply_powerup(g.player, PowerUp(Vec2(0.0, 0.0), "ricochet"), s.time)
        bullet = Projectile(Vec2(R - 5.0, 0.0), Vec2(900.0, 0.0), 10, owner="player")
        s.projectiles.append(bullet)
        _tick(g)
        assert bullet in s.projectiles, "a ricochet bullet must survive its bounce"
        assert bullet.bounces == 1 and bullet.vel.x < 0.0
        bullet.pos = Vec2(R + 2.0, 0.0)
        bullet.prev_pos = Vec2(R - 2.0, 0.0)
        bullet.vel = Vec2(900.0, 0.0)  # heading out through the rim again
        _tick(g)
        assert bullet not in s.projectiles, "a bounced bullet leaving the arena again must be removed"
    finally:
        _close(g)
    print("[PASS] test_ricochet_in_the_playing_loop_bounces_then_removes_the_bullet passed (game loop bounce, then removal)")


def test_plain_bullet_keeps_flying_past_the_rim_in_the_game_loop():
    g = _new_game()
    try:
        s = g.state
        R = float(config.ROOM_RADIUS)
        bullet = Projectile(Vec2(R - 5.0, 0.0), Vec2(900.0, 0.0), 10, owner="player")
        s.projectiles.append(bullet)
        _tick(g)
        assert bullet in s.projectiles and bullet.bounces == 0
        assert bullet.pos.x > R, "without Ricochet the bullet is not turned back at the rim"
    finally:
        _close(g)
    print("[PASS] test_plain_bullet_keeps_flying_past_the_rim_in_the_game_loop passed (no powerup, no bounce)")


def test_homing_turns_toward_the_target_at_the_capped_rate():
    player = Player(pos=Vec2(0.0, 0.0))
    apply_powerup(player, PowerUp(Vec2(0.0, 0.0), "homing"), 0.0)
    target = Enemy(pos=Vec2(150.0, 150.0), hp=30, speed=0.0, behavior="egg_sac")  # 212 px away, 45 degrees
    p = Projectile(Vec2(0.0, 0.0), Vec2(400.0, 0.0), 10, owner="player")
    cap = float(config.HOMING_TURN_RATE) * FRAME

    shot_mods.steer_homing(p, [target], player, 1.0, FRAME)
    angle = math.atan2(p.vel.y, p.vel.x)
    assert abs(angle - cap) < 1e-9, f"first tick should turn by exactly the cap ({cap}), got {angle}"
    assert abs(p.vel.length() - 400.0) < 1e-9, "homing must keep the bullet speed"

    previous = angle
    for _ in range(60):
        shot_mods.steer_homing(p, [target], player, 1.0, FRAME)
        angle = math.atan2(p.vel.y, p.vel.x)
        assert angle - previous <= cap + 1e-9, "per-tick turn exceeded the cap"
        assert angle <= math.pi / 4.0 + 1e-9, "homing overshot the target"
        previous = angle
    assert abs(angle - math.pi / 4.0) < 1e-9, f"bullet should settle on the target at 45 degrees, got {angle}"
    print("[PASS] test_homing_turns_toward_the_target_at_the_capped_rate passed (turn capped, settles on target, speed kept)")


def test_homing_ignores_far_dead_and_already_hit_enemies_and_picks_the_nearest():
    player = Player(pos=Vec2(0.0, 0.0))
    apply_powerup(player, PowerUp(Vec2(0.0, 0.0), "homing"), 0.0)
    far = Enemy(pos=Vec2(300.0, 0.0), hp=30, speed=0.0, behavior="egg_sac")
    dead = Enemy(pos=Vec2(50.0, 0.0), hp=0, speed=0.0, behavior="egg_sac")
    already_hit = Enemy(pos=Vec2(40.0, 0.0), hp=30, speed=0.0, behavior="egg_sac")
    p = Projectile(Vec2(0.0, 0.0), Vec2(400.0, 0.0), 10, owner="player")
    p._hit_entities = {id(already_hit)}
    shot_mods.steer_homing(p, [far, dead, already_hit], player, 1.0, FRAME)
    assert p.vel.x == 400.0 and p.vel.y == 0.0, "no valid target means no steering"

    near = Enemy(pos=Vec2(0.0, 120.0), hp=30, speed=0.0, behavior="egg_sac")
    farther = Enemy(pos=Vec2(0.0, -200.0), hp=30, speed=0.0, behavior="egg_sac")
    p2 = Projectile(Vec2(0.0, 0.0), Vec2(400.0, 0.0), 10, owner="player")
    shot_mods.steer_homing(p2, [farther, near], player, 1.0, FRAME)
    assert p2.vel.y > 0.0, "the nearest enemy (above the bullet) must win over the farther one (below)"

    idle = Player(pos=Vec2(0.0, 0.0))
    p3 = Projectile(Vec2(0.0, 0.0), Vec2(400.0, 0.0), 10, owner="player")
    shot_mods.steer_homing(p3, [near], idle, 1.0, FRAME)
    assert p3.vel.y == 0.0, "without Homing running, bullets fly straight"

    enemy_shot = Projectile(Vec2(0.0, 0.0), Vec2(400.0, 0.0), 10, owner="enemy")
    shot_mods.steer_homing(enemy_shot, [near], player, 1.0, FRAME)
    assert enemy_shot.vel.y == 0.0, "enemy shots never home"
    print("[PASS] test_homing_ignores_far_dead_and_already_hit_enemies_and_picks_the_nearest passed (range, liveness, hit set, nearest)")


def test_homing_in_the_playing_loop_steers_the_bullet():
    g = _new_game()
    try:
        s = g.state
        apply_powerup(g.player, PowerUp(Vec2(0.0, 0.0), "homing"), s.time)
        s.enemies.append(Enemy(pos=Vec2(150.0, 150.0), hp=30, speed=0.0, behavior="egg_sac"))
        bullet = Projectile(Vec2(0.0, 0.0), Vec2(400.0, 0.0), 10, owner="player")
        s.projectiles.append(bullet)
        _tick(g)
        angle = math.atan2(bullet.vel.y, bullet.vel.x)
        assert abs(angle - float(config.HOMING_TURN_RATE) * FRAME) < 1e-9, f"loop steering angle wrong: {angle}"
        assert bullet.pos.y > 0.0, "the bullet should now be moving toward the target"
    finally:
        _close(g)
    print("[PASS] test_homing_in_the_playing_loop_steers_the_bullet passed (real update steers a live bullet)")


def _record_enemy_dt(g, fn):
    """Run fn while states.update_enemy records the dt each enemy receives. Restores the real function after."""
    seen = []
    original = states.update_enemy

    def recorder(enemy, player_pos, s, dt, game, player_vel=None):
        seen.append(float(dt))

    states.update_enemy = recorder
    try:
        fn()
    finally:
        states.update_enemy = original
    return seen


def test_time_slow_halves_the_enemy_step_and_leaves_the_player_alone():
    g = _new_game()
    try:
        s = g.state
        seen = _record_enemy_dt(g, lambda: _tick(g))
        assert seen and abs(seen[-1] - FRAME) < 1e-12, "without Time Slow enemies get the full frame dt"

        apply_powerup(g.player, PowerUp(Vec2(0.0, 0.0), "time_slow"), s.time)
        seen = _record_enemy_dt(g, lambda: _tick(g))
        assert seen and abs(seen[-1] - FRAME * 0.5) < 1e-12, f"time slow must halve the enemy dt, got {seen[-1]}"
        assert enemy_time_scale(g.player, s.time) == 0.5

        # Enemy projectiles advance at half speed too; player bullets and the player move at full speed.
        enemy_shot = Projectile(Vec2(-300.0, 200.0), Vec2(120.0, 0.0), 10, owner="enemy")
        player_shot = Projectile(Vec2(0.0, -300.0), Vec2(0.0, 500.0), 10, owner="player")
        s.projectiles.extend([enemy_shot, player_shot])
        g.keys = _HeldKeys()
        g.keys[pyglet.window.key.UP] = True
        start_player = Vec2(g.player.pos.x, g.player.pos.y)
        _tick(g)
        g.keys[pyglet.window.key.UP] = False
        assert abs((enemy_shot.pos.x + 300.0) - 120.0 * FRAME * 0.5) < 1e-6, "enemy projectile must move half as far"
        assert abs((player_shot.pos.y + 300.0) - 500.0 * FRAME) < 1e-6, "player bullets must keep full speed"
        moved = (g.player.pos - start_player).length()
        assert abs(moved - float(g._effective_player_speed()) * FRAME) < 1e-6, f"player must move at full speed, moved {moved}"
    finally:
        _close(g)
    print("[PASS] test_time_slow_halves_the_enemy_step_and_leaves_the_player_alone passed (enemy dt and shots halved, player full speed)")


def test_time_slow_expires_back_to_full_enemy_speed():
    g = _new_game()
    try:
        s = g.state
        apply_powerup(g.player, PowerUp(Vec2(0.0, 0.0), "time_slow"), s.time)
        s.time = float(config.TIME_SLOW_DURATION) + 0.5
        seen = _record_enemy_dt(g, lambda: _tick(g))
        assert seen and abs(seen[-1] - FRAME) < 1e-12, "after expiry enemies must return to full speed"
        assert g.player.time_slow_until == 0.0, "expiry must clear the state"
    finally:
        _close(g)
    print("[PASS] test_time_slow_expires_back_to_full_enemy_speed passed (expiry restores full speed and clears state)")


def test_time_slow_also_slows_enemy_lasers_but_not_player_beams():
    g = _new_game()
    try:
        s = g.state
        apply_powerup(g.player, PowerUp(Vec2(0.0, 0.0), "time_slow"), s.time)
        enemy_beam = LaserBeam(start=Vec2(-300.0, -300.0), end=Vec2(-300.0, 300.0), damage=5, thickness=6.0, ttl=0.5, owner="enemy")
        player_beam = LaserBeam(start=Vec2(300.0, -300.0), end=Vec2(300.0, 300.0), damage=5, thickness=6.0, ttl=0.5, owner="player")
        s.lasers.extend([enemy_beam, player_beam])
        _tick(g)
        assert abs(enemy_beam.t - FRAME * 0.5) < 1e-9, "enemy beam warn and ttl must run on enemy time"
        assert abs(player_beam.t - FRAME) < 1e-9, "player beams run on real time"
    finally:
        _close(g)
    print("[PASS] test_time_slow_also_slows_enemy_lasers_but_not_player_beams passed (enemy hazards on enemy time)")


def test_magnet_widens_the_pull_radius_and_speeds_the_pull():
    g = _new_game()
    try:
        s = g.state
        s.powerups.append(PowerUp(Vec2(300.0, 0.0), "heal"))
        s.powerups.append(PowerUp(Vec2(420.0, 0.0), "heal"))
        far_pu, edge_pu = s.powerups
        _tick(g)
        assert far_pu.pos.x == 300.0 and edge_pu.pos.x == 420.0, "without Magnet, pickups beyond 150 px stay put"

        apply_powerup(g.player, PowerUp(Vec2(0.0, 0.0), "magnet"), s.time)
        assert pickup_magnet_mods(g.player, s.time) == (3.0, 1.5)
        for pu in (far_pu, edge_pu):
            d = pu.pos.length()
            r = g.balance.pickup_magnet_radius("heal", g._pickup_magnet_bonus) * 3.0
            assert d < r, "test pickup must be inside the widened radius"
        before_far = far_pu.pos.length()
        before_edge = edge_pu.pos.length()
        _tick(g)
        step_far = before_far - far_pu.pos.length()
        step_edge = before_edge - edge_pu.pos.length()
        expect_far = g.balance.pickup_pull_speed(g.balance.pickup_magnet_radius("heal", 0.0) * 3.0, before_far) * 1.5 * FRAME
        expect_edge = g.balance.pickup_pull_speed(g.balance.pickup_magnet_radius("heal", 0.0) * 3.0, before_edge) * 1.5 * FRAME
        assert step_far > 0.0 and step_edge > 0.0, "Magnet must pull pickups inside the widened radius"
        assert abs(step_far - expect_far) < 1e-6, f"pull step wrong: {step_far} vs {expect_far}"
        assert abs(step_edge - expect_edge) < 1e-6, f"pull step wrong: {step_edge} vs {expect_edge}"
        assert step_far > g.balance.pickup_pull_speed(150.0, before_far) * FRAME, "Magnet pull must be faster than the normal pull"
    finally:
        _close(g)
    print("[PASS] test_magnet_widens_the_pull_radius_and_speeds_the_pull passed (x3 radius, x1.5 pull, normal radius unchanged)")


def test_rare_timed_pickups_use_rare_sound_and_ring_and_popup_names():
    g = _new_game()
    try:
        s = g.state
        rings = []
        popups = []
        g.particle_system.add_pickup_ring = lambda pos, color: rings.append(color)
        g.popups.spawn = lambda pos, text, *args, **kwargs: popups.append(text)
        for kind in NEW_KINDS:
            g.audio.played.clear()
            rings.clear()
            popups.clear()
            pu = PowerUp(Vec2(0.0, 0.0), kind)
            s.powerups.append(pu)
            _tick(g)
            rare = is_rare_powerup(kind)
            assert ("pickup_rare" if rare else "pickup") in g.audio.played, f"{kind} played the wrong sound: {g.audio.played}"
            assert ("pickup" if rare else "pickup_rare") not in g.audio.played, f"{kind} played both sounds"
            assert bool(rings) == rare, f"{kind} ring state wrong"
            assert popups == [powerup_popup_name(kind)], f"{kind} popup text {popups}"
            assert pu not in s.powerups, f"{kind} pickup was not collected"
        assert g.player.ricochet_until > 0 and g.player.homing_until > 0 and g.player.time_slow_until > 0 and g.player.magnet_until > 0
    finally:
        _close(g)
    assert powerup_popup_name("time_slow") == "TIME SLOW" and powerup_popup_name("heal") == "HEAL"
    assert {"homing", "time_slow"} <= RARE_POWERUP_KINDS and not ({"ricochet", "magnet"} & RARE_POWERUP_KINDS)
    assert all(is_rare_powerup(k) for k in ("ultra", "weapon", "vortex", "laser")), "existing rare kinds must stay rare"
    assert not is_rare_powerup("heal")
    print("[PASS] test_rare_timed_pickups_use_rare_sound_and_ring_and_popup_names passed (homing and time slow rare, ricochet and magnet common)")


def test_spawn_table_gives_every_new_kind_a_share_and_matches_its_weight():
    weights = dict(POWERUP_POOL_WEIGHTS)
    for kind in NEW_KINDS:
        assert weights.get(kind, 0.0) > 0.0, f"{kind} has no spawn weight"
    st = LevelGameState(difficulty="normal")
    st.init_rng(seed=20260)
    st.wave = 6
    draws = 6000
    counts = Counter(level._pick_powerup_kind_for_wave(st, source="kill") for _ in range(draws))
    total = sum(weights.values())
    for kind in NEW_KINDS:
        expected = weights[kind] / total * 0.80  # the ordinary pool is 80% of rolls from wave 3
        observed = counts[kind] / draws
        assert counts[kind] > 0, f"{kind} never spawned in {draws} rolls"
        assert abs(observed - expected) < 0.35 * expected + 0.003, f"{kind} share {observed:.4f} far from weight share {expected:.4f}"
    print("[PASS] test_spawn_table_gives_every_new_kind_a_share_and_matches_its_weight passed (weighted pool, seeded)")


def test_new_kinds_have_colours_names_and_distinct_art():
    old_colors = {v for k, v in config.POWERUP_COLORS.items() if k not in NEW_KINDS}
    seen = set()
    for kind in NEW_KINDS:
        color = config.POWERUP_COLORS[kind]
        assert len(color) == 3 and all(0 <= c <= 255 for c in color), f"{kind} colour malformed"
        assert color not in old_colors and color not in seen, f"{kind} colour is not distinct"
        seen.add(color)
        assert kind in POWERUP_NAMES and POWERUP_NAMES[kind].strip(), f"{kind} has no popup name"
    assert set(PICKUP_ART_KINDS) == set(NEW_KINDS)

    g = Game()
    try:
        g.set_visible(False)
        g._init_game()
        signatures = {}
        for kind in NEW_KINDS:
            art_shapes, offsets = make_pickup_art(kind, g.batch, config.POWERUP_COLORS[kind], 14)
            assert art_shapes and len(art_shapes) == len(offsets), f"{kind} art missing"
            signatures[kind] = tuple(sorted(type(sh).__name__ for sh in art_shapes))
        assert len(set(signatures.values())) == len(NEW_KINDS), f"pickup art not distinct: {signatures}"
        assert make_pickup_art("heal", g.batch, (1, 2, 3), 14) == ([], []), "old kinds keep the plain orb"
    finally:
        _close(g)
    print("[PASS] test_new_kinds_have_colours_names_and_distinct_art passed (distinct icon colours and shape sets)")


def test_pickup_visuals_follow_the_orb_and_are_removed_with_it():
    g = _new_game()
    try:
        for kind in NEW_KINDS:
            pu = PowerUp(Vec2(120.0, 40.0), kind)
            g.visuals.ensure_powerup(pu)
            g.visuals.sync_powerup(pu, Vec2(3.0, -2.0))
            handle = g.visuals._power_handles[id(pu)]
            sx, sy = to_iso(pu.pos, Vec2(3.0, -2.0))
            for shape, (dx, dy) in zip(handle.objs[5:], handle.art_offsets):
                assert abs(shape.x - (sx + dx)) < 1e-6 and abs(shape.y - (sy + dy)) < 1e-6, f"{kind} art not on the orb"
            pu.pos = Vec2(-60.0, 10.0)
            g.visuals.sync_powerup(pu, Vec2(0.0, 0.0))
            sx2, sy2 = to_iso(pu.pos, Vec2(0.0, 0.0))
            for shape, (dx, dy) in zip(handle.objs[5:], handle.art_offsets):
                assert abs(shape.x - (sx2 + dx)) < 1e-6 and abs(shape.y - (sy2 + dy)) < 1e-6, f"{kind} art lagged the orb"
            g.visuals.drop_powerup(pu)
            assert id(pu) not in g.visuals._power_handles, f"{kind} visual not dropped"
    finally:
        _close(g)
    print("[PASS] test_pickup_visuals_follow_the_orb_and_are_removed_with_it passed (art tracks the orb, drops with it)")


def test_guide_powerups_tab_documents_the_new_kinds():
    entries = GuideMenu.POWERUP_INFO
    # 14 wave-1 kinds (10 original + 4 new) plus the wave-2 drone entry.
    assert len(entries) == 15, f"Powerups tab should have 15 entries, got {len(entries)}"
    by_key = {e["key"]: e for e in entries}
    for kind in NEW_KINDS:
        assert kind in by_key, f"Guide has no {kind} entry"
        entry = by_key[kind]
        for field in ("name", "icon", "what", "deal", "lore"):
            assert str(entry.get(field, "")).strip(), f"{kind} entry missing {field}"
    assert f"{config.RICOCHET_DURATION:.0f}s" in by_key["ricochet"]["what"]
    assert f"{config.HOMING_RANGE:.0f} px" in by_key["homing"]["what"]
    assert f"{config.TIME_SLOW_SCALE * 100:.0f}% speed" in by_key["time_slow"]["what"]
    assert f"{config.MAGNET_RADIUS_MULT:.0f}x" in by_key["magnet"]["what"]
    print("[PASS] test_guide_powerups_tab_documents_the_new_kinds passed (14 entries, numbers come from config)")


if __name__ == "__main__":
    test_timed_durations_match_the_spec()
    test_timed_powerups_apply_refresh_and_do_not_stack()
    test_expiry_clears_every_timed_state()
    test_timed_hud_text_counts_down_and_drops_expired_entries()
    test_ricochet_bounces_once_off_the_rim_then_is_spent()
    test_ricochet_mirror_law_holds_for_an_angled_shot()
    test_ricochet_is_off_without_the_powerup_and_ignores_enemy_shots()
    test_ricochet_in_the_playing_loop_bounces_then_removes_the_bullet()
    test_plain_bullet_keeps_flying_past_the_rim_in_the_game_loop()
    test_homing_turns_toward_the_target_at_the_capped_rate()
    test_homing_ignores_far_dead_and_already_hit_enemies_and_picks_the_nearest()
    test_homing_in_the_playing_loop_steers_the_bullet()
    test_time_slow_halves_the_enemy_step_and_leaves_the_player_alone()
    test_time_slow_expires_back_to_full_enemy_speed()
    test_time_slow_also_slows_enemy_lasers_but_not_player_beams()
    test_magnet_widens_the_pull_radius_and_speeds_the_pull()
    test_rare_timed_pickups_use_rare_sound_and_ring_and_popup_names()
    test_spawn_table_gives_every_new_kind_a_share_and_matches_its_weight()
    test_new_kinds_have_colours_names_and_distinct_art()
    test_pickup_visuals_follow_the_orb_and_are_removed_with_it()
    test_guide_powerups_tab_documents_the_new_kinds()
    print("\nALL W1 POWERUP TESTS PASSED")
