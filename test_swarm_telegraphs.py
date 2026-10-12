"""Regression tests for telegraph clarity: flyer/chaser/charger windups and boss warnings (swarm/telegraphs)."""

import random

import config
from enemy import Enemy, brute_charge_lane, brute_charge_speed, update_enemy
from enemy_behaviors.chase import LUNGE_WINDUP_S
from enemy_behaviors.flyer import Flyer
from game import Game
from hazards import LaserBeam, ThunderLine, Trap
from states import GameStateName
from utils import Vec2

DT = 1.0 / 60.0


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    s = g.state
    s.enemies = []
    s.projectiles = []
    s.lasers = []
    s.traps = []
    s.thunders = []
    s.wave_active = True
    return s


def _tick(g, frames=1):
    # Call update() directly: pyglet.clock.tick() would also fire the game's scheduled
    # update with real elapsed time and double-step the simulation.
    for _ in range(frames):
        g.dispatch_events()
        g.update(DT)


def _telegraphs(s):
    return [lb for lb in getattr(s, "lasers", []) if getattr(lb, "owner", "") == "telegraph"]


def _charger_aim(enemy, player_pos, player_vel, speed_mult=3.0):
    dist = (player_pos - enemy.pos).length()
    prediction_time = dist / (enemy.speed * speed_mult) * 0.5
    return player_pos + player_vel * prediction_time


def test_flyer_windup_locks_target_and_holds_still(g):
    s = _new_run(g)
    random.seed(5)
    flyer = Enemy(pos=Vec2(-150.0, 40.0), hp=20, speed=90.0, behavior="flyer", seed=1.0)
    s.enemies = [flyer]
    flyer.ai = {"state": "CIRCLING", "state_timer": 1e-6}

    aim_at_windup = Vec2(0.0, 0.0)
    update_enemy(flyer, aim_at_windup, s, DT, g, player_vel=Vec2(0.0, 0.0))
    assert flyer.ai["state"] == "WINDUP", f"expected WINDUP, got {flyer.ai['state']}"
    assert abs(flyer.ai["dash_target"].x - aim_at_windup.x) < 1e-9 and abs(flyer.ai["dash_target"].y - aim_at_windup.y) < 1e-9, \
        "dash target must lock at windup entry"

    beams = _telegraphs(s)
    assert len(beams) == 1, f"expected one telegraph beam at windup entry, got {len(beams)}"
    beam = beams[0]
    assert beam.damage == 0 and abs(beam.warn - Flyer().windup_time) < 1e-9, "telegraph must be harmless and last the windup"
    assert abs(beam.end.x - aim_at_windup.x) < 1e-6 and abs(beam.end.y - aim_at_windup.y) < 1e-6, "aim line must end at the locked target"

    start_pos = Vec2(flyer.pos.x, flyer.pos.y)
    frames = 0
    while flyer.ai["state"] == "WINDUP" and frames < 200:
        # The player runs away during the windup. The dash must still go to the locked spot.
        update_enemy(flyer, Vec2(220.0, 200.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
        if flyer.ai["state"] == "WINDUP":
            assert flyer.vel.length() < 1e-9, "flyer must hold still during windup"
            assert abs(flyer.pos.x - start_pos.x) < 1e-9 and abs(flyer.pos.y - start_pos.y) < 1e-9, "flyer must not drift during windup"
        frames += 1
    elapsed = frames * DT
    assert 0.40 <= elapsed <= 0.50, f"windup lasted {elapsed:.3f}s, expected about 0.45s"
    assert abs(flyer.ai["dash_target"].x - aim_at_windup.x) < 1e-9, "dash target must not follow the player after windup entry"

    update_enemy(flyer, Vec2(220.0, 200.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
    assert flyer.vel.length() > 0.0 and (flyer.pos.x - start_pos.x) != 0.0, "dash must move the flyer once the windup ends"
    print(f"[PASS] test_flyer_windup_locks_target_and_holds_still passed (windup {elapsed:.2f}s, target locked, then dash)")


def test_flyer_cadence_unchanged_by_windup(g):
    base = Flyer()
    assert abs((base.circling_duration + base.windup_time) - 2.5) < 1e-9, "circling plus windup must keep the old 2.5s dash cadence"
    print("[PASS] test_flyer_cadence_unchanged_by_windup passed (circling 2.05s + windup 0.45s = 2.5s)")


def test_chaser_lunge_windup_is_planted_and_drawn(g):
    s = _new_run(g)
    random.seed(3)
    chaser = Enemy(pos=Vec2(-160.0, 0.0), hp=30, speed=110.0, behavior="chaser", seed=1.0)
    s.enemies = [chaser]
    chaser.ai = {"lunge_cd": 0.0, "lunge_t": 0.0}

    update_enemy(chaser, Vec2(0.0, 0.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
    assert abs(chaser.ai["lunge_windup"] - LUNGE_WINDUP_S) < 1e-9, "lunge must start with a windup"
    assert chaser.vel.length() < 1e-9, "chaser must be planted during windup"
    cd_after_trigger = chaser.ai["lunge_cd"]
    assert 1.4 - LUNGE_WINDUP_S - 1e-9 <= cd_after_trigger <= 2.0 - LUNGE_WINDUP_S + 1e-9, \
        f"lunge cooldown must be shortened by the windup, got {cd_after_trigger}"

    beams = _telegraphs(s)
    assert len(beams) == 1 and abs(beams[0].warn - LUNGE_WINDUP_S) < 1e-9, "one aim line must cover the windup"
    beam_dir = (beams[0].end - beams[0].start).normalized()
    locked = Vec2(chaser.ai["lunge_dir"].x, chaser.ai["lunge_dir"].y)
    assert abs(beam_dir.x - locked.x) < 1e-6 and abs(beam_dir.y - locked.y) < 1e-6, "aim line must match the lunge direction"

    start_pos = Vec2(chaser.pos.x, chaser.pos.y)
    windup_frames = 0
    while True:
        before = Vec2(chaser.pos.x, chaser.pos.y)
        # Player moves sideways. The locked direction must hold.
        update_enemy(chaser, Vec2(0.0, 150.0), s, DT, g, player_vel=Vec2(0.0, 300.0))
        if chaser.ai["lunge_windup"] > 0.0:
            windup_frames += 1
            assert abs(chaser.pos.x - before.x) < 1e-9 and abs(chaser.pos.y - before.y) < 1e-9, "chaser must not move during windup"
            continue
        break
    windup_time = windup_frames * DT
    assert 0.18 <= windup_time <= 0.26, f"windup lasted {windup_time:.3f}s, expected about 0.22s"
    assert abs(chaser.ai["lunge_dir"].x - locked.x) < 1e-9 and abs(chaser.ai["lunge_dir"].y - locked.y) < 1e-9, \
        "lunge direction must stay locked at windup start"
    assert (chaser.pos.x - start_pos.x) != 0.0 or (chaser.pos.y - start_pos.y) != 0.0, "lunge must move the chaser after the windup"
    print(f"[PASS] test_chaser_lunge_windup_is_planted_and_drawn passed (windup {windup_time:.2f}s, direction locked, aim line drawn)")


def test_charger_aim_line_tracks_windup_and_locks_charge(g):
    s = _new_run(g)
    random.seed(7)
    charger = Enemy(pos=Vec2(-150.0, 0.0), hp=40, speed=60.0, behavior="charger", seed=1.0)
    s.enemies = [charger]

    aim = None
    transitioned = False
    for i in range(60):
        pp = Vec2(0.0, 100.0 + 2.0 * i)
        pv = Vec2(60.0, 0.0)
        update_enemy(charger, pp, s, DT, g, player_vel=pv)
        aim = _charger_aim(charger, pp, pv)
        if charger.ai["state"] == "WINDUP":
            assert charger.vel.length() < 1e-9, "charger must be stopped during windup"
            beams = _telegraphs(s)
            assert len(beams) == 1, "one aim line must be drawn during windup"
            assert abs(beams[0].end.x - aim.x) < 1e-6 and abs(beams[0].end.y - aim.y) < 1e-6, \
                "aim line must be redrawn at the current aim every windup frame"
            continue
        transitioned = True
        break
    assert transitioned and charger.ai["state"] == "CHARGING", "charger must start charging after windup"
    assert charger.ai["charger_dashing"] is True, "charger_dashing must be set while charging"
    assert abs(charger.ai["charge_target"].x - aim.x) < 1e-6 and abs(charger.ai["charge_target"].y - aim.y) < 1e-6, \
        "charge must lock onto the aim at windup end"

    for _ in range(300):
        update_enemy(charger, Vec2(0.0, 100.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
        if charger.ai["state"] != "CHARGING":
            break
        assert charger.ai["charger_dashing"] is True, "charger_dashing must stay set while charging"
    assert charger.ai["state"] == "COOLDOWN", "charger must reach cooldown after the charge"
    assert charger.ai["charger_dashing"] is False, "charger_dashing must clear in cooldown"

    start_speed = charger.vel.length()
    speeds = []
    for _ in range(30):
        update_enemy(charger, Vec2(0.0, 100.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
        speeds.append(charger.vel.length())
    assert start_speed > 0.0
    assert all(b <= a + 1e-9 for a, b in zip([start_speed] + speeds, speeds)), "cooldown must never speed the charger back up"
    assert speeds[-1] < 0.03 * start_speed, "cooldown must be a real stop, not a settle near 0.4x speed"

    while charger.ai["state"] == "COOLDOWN":
        update_enemy(charger, Vec2(0.0, 100.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
    update_enemy(charger, Vec2(0.0, 100.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
    assert charger.ai["charger_dashing"] is False, "charger_dashing must clear on repositioning"
    print("[PASS] test_charger_aim_line_tracks_windup_and_locks_charge passed (aim redrawn, charge locked, real cooldown stop)")


def test_brute_charge_keeps_telegraphed_direction(g):
    s = _new_run(g)
    random.seed(9)
    brute = Enemy(pos=Vec2(-100.0, 0.0), hp=500, speed=60.0, behavior="boss_brute", max_hp=500, seed=1.0)
    s.enemies = [brute]
    brute.ai = {"brute_state": "telegraph", "brute_timer": 0.0005, "charge_dir_x": 1.0, "charge_dir_y": 0.0, "phase": 0, "max_hp": 500}
    # The player is straight up from the brute, so re-aiming would turn the charge to the vertical.
    update_enemy(brute, Vec2(-100.0, 300.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
    assert brute.ai["brute_state"] == "charge", "telegraph must end into the charge"
    assert abs(brute.ai["charge_dir_x"] - 1.0) < 1e-9 and abs(brute.ai["charge_dir_y"]) < 1e-9, \
        "charge must keep the lane direction chosen at telegraph start"
    print("[PASS] test_brute_charge_keeps_telegraphed_direction passed (charge lane fixed at telegraph start)")


def test_brute_lane_matches_charge_reach_and_wall(g):
    brute = Enemy(pos=Vec2(300.0, 0.0), hp=500, speed=60.0, behavior="boss_brute", max_hp=500, seed=1.0)
    brute.ai = {"brute_state": "telegraph", "charge_dir_x": 1.0, "charge_dir_y": 0.0, "phase": 0, "max_hp": 500}
    lane = brute_charge_lane(brute)
    assert lane is not None, "telegraph must produce a lane"
    direction, length = lane
    wall = config.ROOM_RADIUS * 0.95 - 300.0
    assert abs(direction.x - 1.0) < 1e-9 and abs(direction.y) < 1e-9
    assert abs(length - wall) < 1e-6, f"lane must stop at the arena wall, got {length}, expected {wall}"

    brute.pos = Vec2(0.0, 0.0)
    brute.ai["charge_dir_x"], brute.ai["charge_dir_y"] = 0.0, 1.0
    brute.ai["phase"] = 1
    _, length = brute_charge_lane(brute)
    expected = brute_charge_speed(60.0, 1) * 1.2
    assert abs(length - expected) < 1e-6, f"lane length must match charge reach ({expected}), got {length}"

    brute.ai["brute_state"] = "chase"
    assert brute_charge_lane(brute) is None, "no lane outside the telegraph"
    print("[PASS] test_brute_lane_matches_charge_reach_and_wall passed (lane = charge reach, clipped at wall)")


def test_boss_laser_warning_is_030s(g):
    s = _new_run(g)
    boss = Enemy(pos=Vec2(0.0, 0.0), hp=500, speed=0.0, behavior="boss_laser", max_hp=500, seed=1.0)
    s.enemies = [boss]
    boss.ai = {"laser_state": "attack", "laser_timer": 2.0, "laser_tick": 0.0, "max_hp": 500, "phase": 0, "persona": "cautious"}
    update_enemy(boss, Vec2(200.0, 0.0), s, DT, g, player_vel=Vec2(0.0, 0.0))
    beams = [lb for lb in s.lasers if getattr(lb, "owner", "") == "enemy"]
    assert len(beams) == 1, f"expected one boss beam, got {len(beams)}"
    assert abs(beams[0].warn - 0.30) < 1e-9, f"boss laser warning must last 0.30s, got {beams[0].warn}"
    assert abs(beams[0].ttl - 0.13) < 1e-9, "boss laser active window must stay 0.13s"
    print("[PASS] test_boss_laser_warning_is_030s passed (warn 0.30s, active window unchanged)")


def test_telegraph_line_is_harmless_and_clears_at_windup_end(g):
    s = _new_run(g)
    random.seed(11)
    flyer = Enemy(pos=Vec2(-200.0, 0.0), hp=30, speed=0.0001, behavior="flyer", seed=1.0)
    s.enemies = [flyer]
    flyer.ai = {"state": "CIRCLING", "state_timer": 1e-6}
    g.player.pos = Vec2(-100.0, 0.0)  # standing right on the aim line
    hp_before = g.player.hp
    _tick(g, 18)  # 0.30s, still inside the windup
    assert _telegraphs(s), "aim line must be on screen during windup"
    assert g.player.hp == hp_before, "a telegraph line must never damage the player"
    s.enemies = []  # stop the dash from reaching the player; this test only checks the line's lifetime
    _tick(g, 12)  # past 0.45s
    assert not _telegraphs(s), "aim line must be removed when the windup ends"
    print("[PASS] test_telegraph_line_is_harmless_and_clears_at_windup_end passed (no damage, removed at windup end)")


def test_telegraphs_and_warnings_are_drawn(g):
    s = _new_run(g)
    vis = g.visuals
    origin = Vec2(0.0, 0.0)
    far = Vec2(100.0, 0.0)
    no_shake = Vec2(0.0, 0.0)

    # Enemy telegraph line: faint at windup start, brighter as the windup runs down.
    tel = LaserBeam(start=origin, end=far, damage=0, thickness=5.0, ttl=0.0, warn=0.5, color=(235, 235, 230), owner="telegraph")
    vis.ensure_laser(tel)
    tel.t = 0.0
    vis.sync_laser(tel, no_shake)
    line, core = vis._laser_handles[id(tel)].objs
    early = line.opacity
    tel.t = 0.49
    vis.sync_laser(tel, no_shake)
    late = line.opacity
    assert 90 <= early < late <= 140, f"telegraph opacity should ramp up, got {early} -> {late}"
    vis.drop_laser(tel)

    # Boss and enemy beam warnings: raised from 70/40 to 120/80.
    beam = LaserBeam(start=origin, end=far, damage=10, thickness=12.0, ttl=0.13, warn=0.3, color=(255, 100, 255), owner="enemy")
    vis.ensure_laser(beam)
    beam.t = 0.1
    vis.sync_laser(beam, no_shake)
    line, core = vis._laser_handles[id(beam)].objs
    assert line.opacity == 120 and core.opacity == 80, f"enemy warn must read at 120/80, got {line.opacity}/{core.opacity}"
    vis.drop_laser(beam)

    # Thunder warning: raised from 55/20 to 110/50.
    th = ThunderLine(start=origin, end=far, damage=10, warn=1.0, ttl=0.16)
    vis.ensure_thunder(th)
    th.t = 0.2
    vis.sync_thunder(th, no_shake)
    outer, core = vis._thunder_handles[id(th)].objs
    assert outer.opacity == 110 and core.opacity == 50, f"thunder warn must read at 110/50, got {outer.opacity}/{core.opacity}"
    vis.drop_thunder(th)

    # Womb warning: a violet ring, distinct from slam red. The spike look stays on womb_pulse.
    warn = Trap(pos=origin, radius=102.0, damage=0, ttl=1.0, armed_delay=0.52, kind="womb_warn")
    vis.ensure_trap(warn)
    warn.t = 0.1
    vis.sync_trap(warn, no_shake)
    handles = vis._trap_handles[id(warn)].objs
    assert len(handles) == 3, "womb warning must be a ring, not the spike shape"
    base = handles[0]
    assert tuple(base.color[:3]) == (150, 110, 255), f"womb warning tint wrong: {base.color}"
    assert tuple(base.color[:3]) != (255, 80, 80), "womb warning must not reuse slam red"
    assert base.opacity > 0, "womb warning must be visible"
    vis.drop_trap(warn)

    pulse = Trap(pos=origin, radius=86.0, damage=10, ttl=0.72, armed_delay=0.52, kind="womb_pulse")
    vis.ensure_trap(pulse)
    pulse.t = 0.1
    vis.sync_trap(pulse, no_shake)
    p_handles = vis._trap_handles[id(pulse)].objs
    assert len(p_handles) == 4, "womb pulse keeps the spike shape"
    spike = p_handles[2]
    assert spike.opacity == 0, "spikes stay hidden until the womb pulse arms"
    pulse.t = 0.6
    vis.sync_trap(pulse, no_shake)
    assert spike.opacity == 220, "spikes show the live damage window once armed"
    vis.drop_trap(pulse)

    # Brute charge lane: shown only during the telegraph, along the locked direction.
    brute = Enemy(pos=origin, hp=500, speed=60.0, behavior="boss_brute", max_hp=500, seed=1.0)
    brute.ai = {"brute_state": "telegraph", "charge_dir_x": 1.0, "charge_dir_y": 0.0, "phase": 0, "max_hp": 500}
    vis.ensure_enemy(brute)
    vis.sync_enemy(brute, no_shake)
    lane = vis._enemy_handles[id(brute)].objs[-1]
    assert lane.opacity > 0, "brute lane must show during telegraph"
    assert lane.x2 > lane.x, "brute lane must point along the charge direction"
    brute.ai["brute_state"] = "charge"
    vis.sync_enemy(brute, no_shake)
    assert lane.opacity == 0, "brute lane must hide outside the telegraph"
    vis.drop_enemy(brute)
    print("[PASS] test_telegraphs_and_warnings_are_drawn passed (enemy aim line, boss/thunder/womb warnings, brute lane)")


def test_telegraph_renders_in_draw_path(g):
    s = _new_run(g)
    random.seed(13)
    flyer = Enemy(pos=Vec2(-160.0, 40.0), hp=20, speed=90.0, behavior="flyer", seed=1.0)
    s.enemies = [flyer]
    flyer.ai = {"state": "CIRCLING", "state_timer": 1e-6}
    _tick(g, 2)
    assert _telegraphs(s), "flyer windup must add an aim line"
    g.on_draw()  # the normal draw path must render the aim line without error
    print("[PASS] test_telegraph_renders_in_draw_path passed (aim line reaches the draw path)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_flyer_windup_locks_target_and_holds_still(g)
        test_flyer_cadence_unchanged_by_windup(g)
        test_chaser_lunge_windup_is_planted_and_drawn(g)
        test_charger_aim_line_tracks_windup_and_locks_charge(g)
        test_brute_charge_keeps_telegraphed_direction(g)
        test_brute_lane_matches_charge_reach_and_wall(g)
        test_boss_laser_warning_is_030s(g)
        test_telegraph_line_is_harmless_and_clears_at_windup_end(g)
        test_telegraphs_and_warnings_are_drawn(g)
        test_telegraph_renders_in_draw_path(g)
    finally:
        g.close()
    print("\nALL SWARM TELEGRAPH REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
