"""Deterministic tests for the drone companion power-up (wave 2, item "drone").

Plain functions that print [PASS] lines, like the other test_*.py files. Nothing here reads the real
clock: every timestamp is passed in, and the integration tests step the simulation with fixed dt.
"""

import math
import random

import config
import drone as drone_mod
from drone import (
    DRONE_DROP_SHARE,
    DRONE_DURATION,
    DRONE_FIRE_INTERVAL,
    DRONE_FLASH_TIME,
    DRONE_MUZZLE_OFFSET,
    DRONE_ORBIT_RADIUS,
    DRONE_RANGE,
    DroneCompanion,
    drone_bullets,
)
from enemy import Enemy
from game import Game
from level import GameState, _pick_powerup_kind_for_wave
from menu import GuideMenu
from player import Player
from powerup import PowerUp, apply_powerup
from projectile import spawn_projectiles
from states import GameStateName
from utils import Vec2
from weapons import WEAPONS


class NullAudio:
    """Silent stand-in for AudioManager so the tests never touch the sound device."""
    def play(self, *args, **kwargs): pass
    def play_music(self, *args, **kwargs): pass
    def duck(self, *args, **kwargs): pass
    def update(self, dt): pass


class _AlwaysCrit:
    """RNG stub whose every roll is 0.0, so every crit check succeeds."""
    def random(self):
        return 0.0


def _enemy(x, y, hp=100, behavior="chase"):
    return Enemy(pos=Vec2(x, y), hp=hp, speed=0.0, behavior=behavior, max_hp=hp)


def _step(d, t, dt, owner, enemies, until):
    """One companion step at time t + dt. Returns (new_t, shot_or_None)."""
    t += dt
    return t, d.update(dt, t, until, owner, enemies)


def test_drone_repick_refreshes_timer_without_stacking():
    p = Player(pos=Vec2(0.0, 0.0))
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="drone"), 0.0)
    assert abs(p.drone_until - DRONE_DURATION) < 1e-9, f"first pickup should run {DRONE_DURATION}s, got {p.drone_until}"
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="drone"), 10.0)
    assert abs(p.drone_until - 22.0) < 1e-9, f"re-pick at t=10 must refresh to 22, not stack to 24; got {p.drone_until}"
    print("[PASS] test_drone_repick_refreshes_timer_without_stacking passed (re-pick sets now + 12, no stacking)")


def test_drone_orbits_at_fixed_radius():
    d = DroneCompanion()
    owner = Vec2(120.0, -35.0)
    t = 0.0
    dt = 1.0 / 60.0
    for _ in range(240):
        t, _shot = _step(d, t, dt, owner, [], until=99.0)
        r = (d.pos - owner).length()
        assert abs(r - DRONE_ORBIT_RADIUS) < 1e-9, f"orbit radius drifted to {r}"
    assert d.angle > 1.0, "the drone should be moving around the player"
    print("[PASS] test_drone_orbits_at_fixed_radius passed (240 frames at radius 40.0, drone moves)")


def test_drone_fires_at_nearest_live_enemy_in_range():
    owner = Vec2(0.0, 0.0)
    d = DroneCompanion()
    d.update(0.0, 0.0, 12.0, owner, [])  # deploy with no targets: the drone now sits at (40, 0)
    assert abs(d.pos.x - DRONE_ORBIT_RADIUS) < 1e-9 and abs(d.pos.y) < 1e-9
    near = _enemy(40.0, 120.0)            # 120 units above the drone
    mid = _enemy(240.0, 0.0)              # 200 units east of the drone
    far = _enemy(40.0 - 350.0, 0.0)       # 350 units west: beyond DRONE_RANGE
    dead = _enemy(40.0, 60.0, hp=0)       # closer than near, but already dead
    assert DRONE_RANGE == 300.0
    shot = d.update(0.0, 0.0, 12.0, owner, [far, mid, near, dead])
    assert shot is not None, "a live target in range should be fired at"
    muzzle, aim = shot
    assert d.target is near, "the nearest live in-range enemy must be the target"
    assert abs(aim.x) < 1e-9 and abs(aim.y - 1.0) < 1e-9, f"aim should point at the near enemy, got {aim}"
    assert abs((muzzle - d.pos).length() - DRONE_MUZZLE_OFFSET) < 1e-9, "the muzzle sits DRONE_MUZZLE_OFFSET ahead of the drone"

    solo = DroneCompanion()
    solo.update(0.0, 0.0, 12.0, owner, [])
    assert solo.update(0.0, 0.0, 12.0, owner, [far]) is None, "an enemy beyond range must not be fired at"
    assert solo.target is None
    print("[PASS] test_drone_fires_at_nearest_live_enemy_in_range passed (nearest, live, in range only)")


def test_drone_fire_interval_is_0_6_seconds():
    owner = Vec2(0.0, 0.0)
    target = _enemy(200.0, 0.0, hp=100000)
    d = DroneCompanion()
    dt = 0.05
    t = 0.0
    shot_times = []
    while t < 3.0 - 1e-9:
        t, shot = _step(d, t, dt, owner, [target], until=99.0)
        if shot is not None:
            shot_times.append(t)
    assert 5 <= len(shot_times) <= 6, f"3 s at a 0.6 s interval should give 5 or 6 volleys, got {len(shot_times)}"
    for a, b in zip(shot_times, shot_times[1:]):
        assert abs((b - a) - DRONE_FIRE_INTERVAL) <= dt + 1e-9, f"volley gap {b - a:.3f}s is not {DRONE_FIRE_INTERVAL}s"
    print(f"[PASS] test_drone_fire_interval_is_0_6_seconds passed ({len(shot_times)} volleys in 3 s, gaps 0.6 s)")


def test_drone_muzzle_flash_lights_then_clears():
    owner = Vec2(0.0, 0.0)
    target = _enemy(200.0, 0.0)
    d = DroneCompanion()
    _t, shot = _step(d, 0.0, 1.0 / 60.0, owner, [target], until=99.0)
    assert shot is not None, "the first frame with a target should fire"
    assert d.flash == DRONE_FLASH_TIME, "a volley lights the muzzle flash for DRONE_FLASH_TIME"
    t = 1.0 / 60.0
    while d.flash > 0.0 and t < 1.0:
        t, _shot = _step(d, t, 1.0 / 60.0, owner, [target], until=99.0)
    assert d.flash == 0.0, "the muzzle flash must burn out"
    print("[PASS] test_drone_muzzle_flash_lights_then_clears passed (flash lights on volley, decays to zero)")


def test_drone_timer_expires_and_clears_state():
    owner = Vec2(0.0, 0.0)
    target = _enemy(200.0, 0.0, hp=100000)
    until = DRONE_DURATION
    d = DroneCompanion()
    dt = 1.0 / 60.0
    t = 0.0
    while t < until - 0.25:
        t, _shot = _step(d, t, dt, owner, [target], until=until)
    assert d.active and d.target is target, "the drone should be out and tracking before the timer runs out"
    expired_at = None
    late_shots = 0
    while t < until + 1.0:
        t, shot = _step(d, t, dt, owner, [target], until=until)
        if t >= until:
            if expired_at is None:
                expired_at = t
            if shot is not None:
                late_shots += 1
    assert expired_at is not None and expired_at - until <= dt + 1e-9, f"expiry should land on the first frame at or after {until}s"
    assert late_shots == 0, "an expired drone must not fire"
    assert not d.active and d.target is None, "expiry must clear the active flag and the target"
    assert d.flash == 0.0 and d.fire_cd == 0.0, "expiry must clear the muzzle flash and the cooldown"
    print("[PASS] test_drone_timer_expires_and_clears_state passed (expires at 12s, no shots after, state cleared)")


def test_drone_repick_extends_the_deployment_through_the_player_timer():
    owner = Vec2(0.0, 0.0)
    target = _enemy(200.0, 0.0, hp=100000)
    p = Player(pos=owner)
    d = DroneCompanion()
    apply_powerup(p, PowerUp(pos=owner, kind="drone"), 0.0)
    dt = 1.0 / 60.0
    t = 0.0
    while t < 10.0:
        t, _shot = _step(d, t, dt, owner, [target], until=p.drone_until)
    apply_powerup(p, PowerUp(pos=owner, kind="drone"), t)  # re-pick at about t=10
    while t < 15.0:
        t, _shot = _step(d, t, dt, owner, [target], until=p.drone_until)
    assert d.active, "a re-pick at t=10 must keep the drone out past the original 12s"
    while t < 22.5:
        t, _shot = _step(d, t, dt, owner, [target], until=p.drone_until)
    assert not d.active, "the refreshed drone must expire 12s after the re-pick"
    print("[PASS] test_drone_repick_extends_the_deployment_through_the_player_timer passed (refresh runs to ~22s)")


def test_drone_bullets_use_the_player_damage_function():
    calls = []
    real = drone_mod.spawn_projectiles

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    drone_mod.spawn_projectiles = spy
    try:
        shots = drone_bullets(Vec2(10.0, 0.0), Vec2(1.0, 0.0), 0.0, 10, random.Random(3))
    finally:
        drone_mod.spawn_projectiles = real
    assert len(calls) == 1, "drone volleys must be built by the shared spawn_projectiles"
    args = calls[0][0]
    assert args[2] is WEAPONS["basic"], "the drone fires the basic bullet"
    assert args[4] == 10, "the player's current damage is the base damage"
    assert len(shots) == 1 and shots[0].owner == "player", "drone bullets are player-owned"

    for base in (10, 14, 20):
        for seed in range(40):
            mine = drone_bullets(Vec2(0.0, 0.0), Vec2(0.0, 1.0), 1.0, base, random.Random(seed), crit_chance_bonus=0.2)
            theirs = spawn_projectiles(Vec2(0.0, 0.0), Vec2(0.0, 1.0), WEAPONS["basic"], 1.0, base,
                                       rng=random.Random(seed), crit_chance_bonus=0.2)
            assert [(p.damage, p.is_crit) for p in mine] == [(p.damage, p.is_crit) for p in theirs], (
                f"drone and player damage diverged at base {base}, seed {seed}")

    crit = drone_bullets(Vec2(0.0, 0.0), Vec2(1.0, 0.0), 0.0, 10, _AlwaysCrit())
    assert crit[0].is_crit and crit[0].damage == 30, f"a forced crit should hit for 2x the basic 15, got {crit[0].damage}"
    print("[PASS] test_drone_bullets_use_the_player_damage_function passed (one shared damage path, crits match)")


def test_drone_idle_and_firing_never_touch_the_global_random():
    st = GameState(wave=5)
    st.init_rng(4)
    run_state = st.rng.getstate()
    global_state = random.getstate()
    d = DroneCompanion()
    enemies = [_enemy(200.0, 0.0, hp=100000)]
    t = 0.0
    for _ in range(600):
        t, _shot = _step(d, t, 1.0 / 60.0, Vec2(0.0, 0.0), enemies, until=99.0)
    assert random.getstate() == global_state, "drone steering and aiming must not use the global random module"
    assert st.rng.getstate() == run_state, "the companion itself draws no random numbers; crits are rolled in the shared bullet path"
    print("[PASS] test_drone_idle_and_firing_never_touch_the_global_random passed (no RNG draws in the companion)")


def _share(wave, source, n=20000, seed=11):
    st = GameState(wave=wave, difficulty="normal")
    st.init_rng(seed)
    hits = 0
    for _ in range(n):
        # Keep the ultra guarantees out of the sample so only the base pool is measured.
        st._last_ultra_wave = wave
        st._kills_since_ultra = 0
        if _pick_powerup_kind_for_wave(st, source=source) == "drone":
            hits += 1
    return hits / n


def test_drone_is_a_rare_drop_from_wave_3():
    assert _share(1, "kill") == 0.0, "no drones on waves 1 and 2"
    assert _share(2, "wave") == 0.0, "no drones on waves 1 and 2"
    share = _share(5, "kill")
    assert 0.5 * DRONE_DROP_SHARE <= share <= 1.5 * DRONE_DROP_SHARE, f"drone share {share:.4f} should be about {DRONE_DROP_SHARE}"
    assert share < 0.05, "the drone must stay rare"
    assert _share(3, "wave") > 0.0, "drones can drop from wave 3"
    print(f"[PASS] test_drone_is_a_rare_drop_from_wave_3 passed (share {share:.4f}, none before wave 3)")


def test_drone_state_lives_on_the_game_state():
    st = GameState(wave=1)
    assert isinstance(st.drone, DroneCompanion) and not st.drone.active
    assert GameState(wave=1).drone is not st.drone, "each run gets its own companion"
    print("[PASS] test_drone_state_lives_on_the_game_state passed (a fresh companion per run)")


def test_drone_guide_entry_and_pickup_colour(g):
    g._init_game()
    entries = [e for e in GuideMenu.POWERUP_INFO if e["key"] == "drone"]
    assert len(entries) == 1, "the Guide Powerups tab needs exactly one drone entry"
    assert "12s" in entries[0]["what"] and "0.6s" in entries[0]["deal"], "the guide should state the timer and fire rate"
    colour = tuple(config.POWERUP_COLORS["drone"])
    others = [tuple(v) for k, v in config.POWERUP_COLORS.items() if k != "drone"]
    assert colour not in others, "the drone needs its own icon colour"
    pu = PowerUp(pos=Vec2(0.0, 0.0), kind="drone")
    g.visuals.ensure_powerup(pu)
    orb = g.visuals._power_handles[id(pu)].objs[2]
    assert tuple(orb.color[:3]) == colour, "the pickup orb uses the drone colour"
    print("[PASS] test_drone_guide_entry_and_pickup_colour passed (guide entry, own colour, pickup orb)")


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.audio = NullAudio()
    return g.state


def _screen_angle(v):
    """Screen angle (degrees, counter-clockwise) of a world vector, projected the way drone_art does."""
    return math.degrees(math.atan2((v.x + v.y) * config.ISO_SCALE_Y, (v.x - v.y) * config.ISO_SCALE_X))


def test_drone_visual_faces_target_bobs_and_flashes(g):
    s = _new_run(g)
    drone = s.drone
    owner = g.player.pos
    s.wave_active = True
    target = _enemy(200.0, 0.0, hp=100000)
    s.enemies = [target]
    g.visuals.sync_drone(drone, Vec2(0.0, 0.0), t=0.0)
    art = g.visuals._drone_art
    assert art is not None and not art.hull.visible, "no drone is out, so the hull stays hidden"

    g.player.drone_until = s.time + DRONE_DURATION
    drone.update(1.0 / 60.0, s.time, g.player.drone_until, owner, s.enemies)
    g.visuals.sync_drone(drone, Vec2(0.0, 0.0), t=0.0)
    assert art.hull.visible and art.halo.visible, "a deployed drone is drawn"
    halo_y0 = art.halo.y

    g.visuals.sync_drone(drone, Vec2(0.0, 0.0), t=0.2)
    assert abs(art.halo.y - halo_y0) > 0.5, "the hull bobs over time"

    # Move the target so the hull has to turn; the orbit keeps moving, so check the facing against the live target.
    target.pos = Vec2(drone.pos.x - 150.0, drone.pos.y + 60.0)
    for _ in range(90):
        drone.update(1.0 / 60.0, s.time, g.player.drone_until, owner, s.enemies)
    g.visuals.sync_drone(drone, Vec2(0.0, 0.0), t=0.4)
    want = (target.pos - drone.pos).normalized()
    facing_error = abs(((-art.hull.rotation) - _screen_angle(want) + 180.0) % 360.0 - 180.0)
    assert facing_error < 10.0, f"the hull should face its target on screen, off by {facing_error:.1f} degrees"

    # Muzzle flash: lit on the volley frame, then gone.
    drone.flash = DRONE_FLASH_TIME
    g.visuals.sync_drone(drone, Vec2(0.0, 0.0), t=0.5)
    assert art.flash_glow.visible, "the muzzle flash shows right after a volley"
    drone.flash = 0.0
    g.visuals.sync_drone(drone, Vec2(0.0, 0.0), t=0.6)
    assert not art.flash_glow.visible, "the muzzle flash is hidden once it burns out"

    # Expiry hides the hull again.
    g.player.drone_until = s.time - 1.0
    drone.update(1.0 / 60.0, s.time, g.player.drone_until, owner, s.enemies)
    g.visuals.sync_drone(drone, Vec2(0.0, 0.0), t=0.7)
    assert not art.hull.visible and not art.halo.visible, "an expired drone is hidden"
    print("[PASS] test_drone_visual_faces_target_bobs_and_flashes passed (turns, bobs, flashes, hides on expiry)")


def test_drone_bullets_hit_bosses_through_the_player_loop(g):
    s = _new_run(g)
    g.auto_shoot = False  # only the drone shoots, so every hit on the boss is a drone hit
    g.player.hp = 10 ** 6
    g.player.drone_until = s.time + DRONE_DURATION
    boss = Enemy(pos=Vec2(150.0, 0.0), hp=5000, speed=0.0, behavior="boss_brute", max_hp=5000)
    s.enemies = [boss]
    s.wave_active = True
    start = boss.hp
    for _ in range(240):  # 4 s of fixed 1/60 steps
        g.fsm.update(1.0 / 60.0)
    dealt = start - boss.hp
    assert dealt >= 30, f"the drone should have hit the boss at least twice, dealt {dealt}"
    assert dealt % 15 == 0, f"each drone hit is 15 (basic) or 30 (crit) at base damage 10; dealt {dealt}"
    print(f"[PASS] test_drone_bullets_hit_bosses_through_the_player_loop passed (boss took {dealt} from drone volleys)")


def _seeded_trace(g, seed):
    s = _new_run(g)
    random.seed(0)  # keep any incidental global-random use identical between the two runs
    s.init_rng(seed)
    g.player.drone_until = s.time + 60.0
    g.auto_shoot = False
    g.player.hp = 10 ** 6
    for _ in range(900):
        g.fsm.update(1.0 / 60.0)
    return (
        round(g.state.time, 9),
        tuple((round(e.pos.x, 6), round(e.pos.y, 6), e.hp) for e in g.state.enemies),
        len(g.state.projectiles),
        round(g.state.drone.fire_cd, 9),
        round(g.state.drone.angle, 9),
    )


def test_seeded_drone_run_is_reproducible(g):
    a = _seeded_trace(g, 21)
    b = _seeded_trace(g, 21)
    assert a == b, "the same seed with a drone out must give the same final state"
    print("[PASS] test_seeded_drone_run_is_reproducible passed (same seed, identical final state)")


def test_drone_shows_in_the_status_line(g):
    s = _new_run(g)
    s.enemies = []
    s.wave_active = True
    g.player.drone_until = s.time + DRONE_DURATION
    g.on_draw()
    text = g.hud.status_label.text
    assert "Drone" in text, f"the status line should show the drone timer, got {text!r}"
    print(f"[PASS] test_drone_shows_in_the_status_line passed (status: {text!r})")


def run_all():
    test_drone_repick_refreshes_timer_without_stacking()
    test_drone_orbits_at_fixed_radius()
    test_drone_fires_at_nearest_live_enemy_in_range()
    test_drone_fire_interval_is_0_6_seconds()
    test_drone_muzzle_flash_lights_then_clears()
    test_drone_timer_expires_and_clears_state()
    test_drone_repick_extends_the_deployment_through_the_player_timer()
    test_drone_bullets_use_the_player_damage_function()
    test_drone_idle_and_firing_never_touch_the_global_random()
    test_drone_is_a_rare_drop_from_wave_3()
    test_drone_state_lives_on_the_game_state()
    g = Game()
    g.set_visible(False)
    try:
        test_drone_guide_entry_and_pickup_colour(g)
        test_drone_visual_faces_target_bobs_and_flashes(g)
        test_drone_bullets_hit_bosses_through_the_player_loop(g)
        test_seeded_drone_run_is_reproducible(g)
        test_drone_shows_in_the_status_line(g)
    finally:
        g.close()
    print("\nALL W2 DRONE TESTS PASSED")


if __name__ == "__main__":
    run_all()
