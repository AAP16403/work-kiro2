"""Wave 8 Echo tests: the frame a dash ends, the pod drops one homing echo.

Covers: the config block and the switch; the damage (ECHO_DAMAGE_PERCENT of the effective player damage, half up,
at least 1); exactly one echo per dash (a press mid-dash is refused, and each later dash drops its own single echo);
the echo's speed along the dash heading and its ttl, which expires it; the homing turning toward the nearest live
enemy within ECHO_HOMING_RANGE, only for ECHO_HOMING_SECONDS, at the turn rate, keeping its speed; other projectiles
passing through untouched; the ring pulse at the drop point, held at full size under reduced motion; nothing dropped
when ENABLE_ECHO is off; steering leaving no memory behind over many calls; and an in-play scripted dash with an enemy
250 px from the dash end point, straight ahead and 60 degrees off the heading, reporting the echo hits.

Plain functions that print [PASS] lines, run from run_all().
"""

import math
import os
import shutil
import tempfile
import time
import tracemalloc

import pyglet

import config
import echo
import motion
import score as score_mod
from enemy import Enemy
from game import Game
from projectile import Projectile
from states import GameStateName
from utils import Vec2

FRAME = 1.0 / 60.0

# A still enemy far behind the dash, out of the echo's range for its whole flight. It keeps the wave open,
# so the wave-clear logic does not run on the first frame of a test. A stun holds an enemy still (repulsor.py):
# a stunned enemy neither moves nor acts, and it still takes hits, so it makes a fixed target.
_BYSTANDER_POS = (-380.0, 0.0)
_STILL_UNTIL = 1.0e9


def _still_enemy(pos):
    """An enemy that stays where it is for the whole test: a stun that outlasts the run."""
    e = Enemy(pos=Vec2(pos.x, pos.y), hp=100, speed=0.0, behavior="chaser")
    e.stun_until = _STILL_UNTIL
    return e


class _Player:
    """Just the fields echo.drop_echo reads: a position and a dash heading."""

    def __init__(self, pos, dash_direction):
        self.pos = Vec2(pos.x, pos.y)
        self.dash_direction = dash_direction


def _redirect_saves(g):
    """Point the high-score and progress files at a scratch folder, so a test never touches the real saves."""
    scratch = tempfile.mkdtemp(prefix="w8_echo_")
    previous = (score_mod.HIGH_SCORE_FILE, g.progress_path)
    score_mod.HIGH_SCORE_FILE = os.path.join(scratch, "high_scores.json")
    g.progress_path = os.path.join(scratch, "progress.json")
    return scratch, previous


def _restore_saves(g, scratch, previous):
    score_mod.HIGH_SCORE_FILE, g.progress_path = previous
    shutil.rmtree(scratch, ignore_errors=True)


def _new_run(g):
    """A fresh run in PLAYING with no auto-fire, and one far bystander enemy that never moves."""
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.state.wave_active = True
    g.player.pos = Vec2(0.0, 0.0)
    g.state.enemies[:] = [_still_enemy(Vec2(*_BYSTANDER_POS))]
    return g.state


def _steps(g, n):
    for _ in range(n):
        g._fixed_step()


def _echoes(s):
    return [p for p in s.projectiles if echo.is_echo(p)]


def _rings(g):
    return [p for p in g.particle_system.particles if getattr(p, "kind", "") == "ring"]


class _HeldKeys(dict):
    """A key map for one press: the keys in it are held, every other key reads as up."""

    def __missing__(self, key):
        return False


def _press_dash_east(g):
    """Hold W and D (their sum is world +x, the dash heading), press dash, then let both keys go."""
    k = pyglet.window.key
    saved = g.keys
    g.keys = _HeldKeys({k.W: True, k.D: True})
    try:
        g._dash()
    finally:
        g.keys = saved


def _run_dash_to_end(g, limit=60):
    """Step until the dash timer runs out. Returns the number of steps taken."""
    n = 0
    while g.player.is_dashing and n < limit:
        g._fixed_step()
        n += 1
    assert not g.player.is_dashing, "the dash should end within the limit"
    return n


def test_config_block_and_switch():
    assert config.ENABLE_ECHO is True, "the switch defaults to on"
    assert config.ECHO_DAMAGE_PERCENT == 60
    assert config.ECHO_SPEED == 520.0
    assert abs(config.ECHO_TTL - 1.6) < 1e-9
    assert abs(config.ECHO_HOMING_SECONDS - 1.2) < 1e-9
    assert config.ECHO_HOMING_RANGE == 300.0
    with open(config.__file__, encoding="utf-8") as fh:
        text = fh.read()
    assert text.find("# wave8 echo-dash") > text.find("COLORBLIND_ENEMY_COLORS = {"), "the wave8 block is at the end"
    print("[PASS] test_config_block_and_switch passed (switch on; 60%, 520 px/s, 1.6 s, 1.2 s, 300 px)")


def test_drop_sets_damage_speed_ttl_and_owner():
    """A bare drop, no run needed: the projectile the dash hands to the bullet loops."""
    q = echo.drop_echo(_Player(Vec2(10.0, -5.0), Vec2(0.0, 2.0)), [], 6, 3.0)
    assert q.owner == "player" and q.projectile_type == "echo"
    assert q.damage == 6
    assert q.ttl == float(config.ECHO_TTL) == 1.6
    assert abs(math.hypot(q.vel.x, q.vel.y) - 520.0) < 1e-9, "520 px per second"
    assert abs(q.vel.y - 520.0) < 1e-9 and abs(q.vel.x) < 1e-9, "along the (normalised) dash heading"
    assert (q.pos.x, q.pos.y) == (10.0, -5.0), "dropped at the given point"
    zero = echo.drop_echo(_Player(Vec2(0.0, 0.0), Vec2(0.0, 0.0)), [], 6, 0.0)
    assert (zero.vel.x, zero.vel.y) == (520.0, 0.0), "no dash heading: the echo flies along +x"
    print("[PASS] test_drop_sets_damage_speed_ttl_and_owner passed (player-owned echo, 6 dmg, 520 px/s, ttl 1.6)")


def test_damage_is_sixty_percent_of_effective_damage():
    cases = {10: 6, 15: 9, 25: 15, 13: 8, 5: 3, 1: 1}
    for player_damage, want in cases.items():
        got = echo.echo_damage(player_damage)
        assert got == want, (player_damage, got, want)
    # 60% of 10 is 6 exactly. 60% of 13 is 7.8, which rounds half up to 8. The floor is 1.

    g = Game()
    g.set_visible(False)
    scratch, previous = _redirect_saves(g)
    try:
        s = _new_run(g)
        assert g._effective_player_damage() == 10
        g._temp_damage_mult = 1.5  # a damage multiplier: 10 * 1.5 = 15 effective
        assert g._effective_player_damage() == 15
        _press_dash_east(g)
        _run_dash_to_end(g)
        drops = _echoes(s)
        assert len(drops) == 1 and drops[0].damage == echo.echo_damage(15) == 9, [p.damage for p in drops]
    finally:
        g._temp_damage_mult = 1.0
        _restore_saves(g, scratch, previous)
        g.close()
    print("[PASS] test_damage_is_sixty_percent_of_effective_damage passed (10 -> 6, 13 -> 8, 15 -> 9, floor 1)")


def test_exactly_one_echo_per_dash():
    g = Game()
    g.set_visible(False)
    scratch, previous = _redirect_saves(g)
    try:
        s = _new_run(g)
        g.player.dash_max_charges = 2
        g.player.dash_charges = 2
        g.player.dash_cooldown = 0.0
        assert _echoes(s) == []

        # Dash one. A second press mid-dash is refused: no charge is spent and no second echo drops.
        _press_dash_east(g)
        assert g.player.is_dashing
        charges_mid = g.player.dash_charges
        _steps(g, 3)
        _press_dash_east(g)
        assert g.player.dash_charges == charges_mid, "a press mid-dash spends no charge"
        _run_dash_to_end(g)
        assert len(_echoes(s)) == 1, f"one dash, one echo (got {len(_echoes(s))})"
        first = _echoes(s)[0]

        # The frames after the dash drop nothing more.
        _steps(g, 30)
        assert len(_echoes(s)) == 1 and _echoes(s)[0] is first, "no further echo after the dash ends"

        # Dash two, on a fresh charge, drops its own single echo.
        g.player.dash_charges = 1
        g.player.dash_cooldown = 0.0
        _press_dash_east(g)
        _run_dash_to_end(g)
        newer = [p for p in _echoes(s) if p is not first]
        assert len(newer) == 1, f"the second dash drops one echo (got {len(newer)})"
        assert len(_echoes(s)) == 2, "two dashes, two echoes, never more"
    finally:
        _restore_saves(g, scratch, previous)
        g.close()
    print("[PASS] test_exactly_one_echo_per_dash passed (mid-dash press refused; one echo per dash)")


def test_echo_flies_along_the_dash_heading_and_expires_at_1_6_seconds():
    g = Game()
    g.set_visible(False)
    scratch, previous = _redirect_saves(g)
    try:
        s = _new_run(g)
        _press_dash_east(g)
        _run_dash_to_end(g)
        (p,) = _echoes(s)
        # The drop frame also moved the echo one step, so its ttl is 1.6 s minus one frame.
        assert float(config.ECHO_TTL) - 2 * FRAME < p.ttl <= float(config.ECHO_TTL), p.ttl
        speed = math.hypot(p.vel.x, p.vel.y)
        assert abs(speed - float(config.ECHO_SPEED)) < 1e-6, speed
        assert p.vel.x > 0.0 and abs(p.vel.y) < 1e-6, (p.vel.x, p.vel.y)
        steps = 0
        while p in s.projectiles and steps < 300:
            _steps(g, 1)
            steps += 1
        seconds = steps * FRAME
        assert p not in s.projectiles, "the echo expires"
        assert abs(seconds - float(config.ECHO_TTL)) <= 2 * FRAME + 1e-9, f"expired after {seconds:.3f} s"
    finally:
        _restore_saves(g, scratch, previous)
        g.close()
    print(f"[PASS] test_echo_flies_along_the_dash_heading_and_expires_at_1_6_seconds passed "
          f"(520 px/s along +x, gone after {seconds:.2f} s)")


def test_homing_turns_toward_the_nearest_enemy():
    p = echo.drop_echo(_Player(Vec2(0.0, 0.0), Vec2(1.0, 0.0)), [], 6, 0.0)
    near = Enemy(pos=Vec2(0.0, 120.0), hp=50, speed=0.0, behavior="chaser")   # 120 px, straight up the screen plane
    far = Enemy(pos=Vec2(-250.0, 0.0), hp=50, speed=0.0, behavior="chaser")   # 250 px, behind the echo
    enemies = [far, near]

    target = echo.steer(p, enemies, 0.0, FRAME)
    assert target is near, "the nearer enemy is the target, not the far one"
    max_turn = float(config.ECHO_HOMING_TURN_RATE) * FRAME
    assert abs(math.atan2(p.vel.y, p.vel.x) - max_turn) < 1e-9, "one frame turns by at most the turn rate"
    assert p.vel.y > 0.0, "it turns toward the near enemy, not the far one"
    assert abs(math.hypot(p.vel.x, p.vel.y) - float(config.ECHO_SPEED)) < 1e-6, "speed is kept"

    # Over the homing window the heading swings onto the near enemy, which is straight up from the echo.
    t = 0.0
    for _ in range(40):
        t += FRAME
        echo.steer(p, enemies, t, FRAME)
    heading = math.atan2(p.vel.y, p.vel.x)
    assert abs(heading - math.pi / 2.0) < 1e-6, heading
    assert abs(math.hypot(p.vel.x, p.vel.y) - float(config.ECHO_SPEED)) < 1e-6

    # An enemy beyond ECHO_HOMING_RANGE is not a target: nothing steers and the velocity stays.
    q = echo.drop_echo(_Player(Vec2(0.0, 0.0), Vec2(1.0, 0.0)), [], 6, 0.0)
    lone = [Enemy(pos=Vec2(float(config.ECHO_HOMING_RANGE) + 40.0, 0.0), hp=50, speed=0.0, behavior="chaser")]
    before = (q.vel.x, q.vel.y)
    assert echo.steer(q, lone, 0.0, FRAME) is None
    assert (q.vel.x, q.vel.y) == before, "out of range: no steering"
    # An enemy just inside the range is a target.
    edge = [Enemy(pos=Vec2(float(config.ECHO_HOMING_RANGE) - 5.0, 0.0), hp=50, speed=0.0, behavior="chaser")]
    assert echo.steer(q, edge, 0.0, FRAME) is edge[0]
    print("[PASS] test_homing_turns_toward_the_nearest_enemy passed (nearest wins, turns at the rate, keeps speed, range)")


def test_homing_stops_after_1_2_seconds_and_skips_other_shots():
    p = echo.drop_echo(_Player(Vec2(0.0, 0.0), Vec2(1.0, 0.0)), [], 6, 0.0)
    enemy = Enemy(pos=Vec2(0.0, 150.0), hp=50, speed=0.0, behavior="chaser")
    assert echo.steer(p, [enemy], 1.19, FRAME) is enemy, "still homing just inside the window"
    before = (p.vel.x, p.vel.y)
    assert echo.steer(p, [enemy], float(config.ECHO_HOMING_SECONDS) + 0.01, FRAME) is None
    assert (p.vel.x, p.vel.y) == before, "past the window the echo flies straight"

    # Any other projectile passes through untouched, even with an enemy in range.
    shot = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(900.0, 0.0), damage=5, ttl=2.0, owner="player")
    assert echo.steer(shot, [enemy], 0.1, FRAME) is None
    assert (shot.vel.x, shot.vel.y) == (900.0, 0.0)
    enemy_shot = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=5, ttl=2.0, owner="enemy",
                            projectile_type="echo")
    assert echo.steer(enemy_shot, [enemy], 0.1, FRAME) is None, "an enemy-owned shot is never an echo"
    print("[PASS] test_homing_stops_after_1_2_seconds_and_skips_other_shots passed (window ends at 1.2 s; others untouched)")


def test_ring_pulse_at_the_drop_point_and_reduced_motion():
    g = Game()
    g.set_visible(False)
    scratch, previous = _redirect_saves(g)
    prev_reduce = config.REDUCE_MOTION
    try:
        _new_run(g)
        g.particle_system.particles.clear()
        _press_dash_east(g)
        _run_dash_to_end(g)
        drop = Vec2(g.player.pos.x, g.player.pos.y)  # the player does not move after the dash, so this is the drop
        rings = _rings(g)
        assert len(rings) == 1, f"one ring at the drop (got {len(rings)})"
        ring = rings[0]
        assert abs(ring.pos.x - drop.x) < 1e-6 and abs(ring.pos.y - drop.y) < 1e-6, "the ring sits at the drop point"
        assert abs(ring.size - float(config.ECHO_RING_RADIUS)) < 1e-6
        assert ring.grow is True, "full motion: the ring grows"

        g.particle_system.particles.clear()
        config.REDUCE_MOTION = True
        assert motion.reduced()
        g.player.dash_charges = 1
        g.player.dash_cooldown = 0.0
        _press_dash_east(g)
        _run_dash_to_end(g)
        rings = _rings(g)
        assert len(rings) == 1 and rings[0].grow is False, "reduced motion: the ring holds its full size"
    finally:
        config.REDUCE_MOTION = prev_reduce
        _restore_saves(g, scratch, previous)
        g.close()
    print("[PASS] test_ring_pulse_at_the_drop_point_and_reduced_motion passed (ring at the drop; static under reduced motion)")


def test_nothing_happens_when_disabled():
    g = Game()
    g.set_visible(False)
    scratch, previous = _redirect_saves(g)
    prev = config.ENABLE_ECHO
    try:
        s = _new_run(g)
        g.particle_system.particles.clear()
        config.ENABLE_ECHO = False
        target = _still_enemy(Vec2(370.0, 0.0))
        s.enemies[:] = [target]
        _press_dash_east(g)
        _run_dash_to_end(g)
        _steps(g, 60)
        assert _echoes(s) == [], "no echo with the switch off"
        assert _rings(g) == [], "no ring with the switch off"
        assert target.hp == 100, "no echo hit with the switch off"
        assert echo.on_dash_end(g, s) is None, "the drop itself also returns nothing"
        assert _echoes(s) == []
    finally:
        config.ENABLE_ECHO = prev
        _restore_saves(g, scratch, previous)
        g.close()
    print("[PASS] test_nothing_happens_when_disabled passed (no echo, no ring, no hit with ENABLE_ECHO off)")


def test_steering_leaves_no_memory_behind():
    p = echo.drop_echo(_Player(Vec2(0.0, 0.0), Vec2(1.0, 0.0)), [], 6, 0.0)
    enemies = [Enemy(pos=Vec2(0.0, 200.0), hp=50, speed=0.0, behavior="chaser")]
    echo.steer(p, enemies, 0.01, FRAME)  # warm up
    tracemalloc.start()
    try:
        base, _ = tracemalloc.get_traced_memory()
        for i in range(3000):
            echo.steer(p, enemies, 0.02 + i * 1e-6, FRAME)
        current, _ = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    grown = current - base
    assert grown < 4096, f"steering grew traced memory by {grown} bytes over 3000 calls"

    # Cost, measured without tracemalloc running.
    t0 = time.perf_counter()
    for i in range(3000):
        echo.steer(p, enemies, 0.02 + i * 1e-6, FRAME)
    per_call_ms = (time.perf_counter() - t0) / 3000.0 * 1000.0
    # Loose on purpose: a guard against a regression, not a benchmark (the machine may be busy).
    assert per_call_ms < 0.5, f"steer costs {per_call_ms:.4f} ms per call"
    print(f"[PASS] test_steering_leaves_no_memory_behind passed (+{grown} B over 3000 calls, "
          f"{per_call_ms * 1000.0:.2f} us per steer call)")


def test_scripted_dash_echo_hits_enemy_250_px_away():
    """In play: a scripted dash, then an enemy 250 px from the dash end point. The echo's hits are counted."""
    g = Game()
    g.set_visible(False)
    scratch, previous = _redirect_saves(g)
    report = []
    try:
        for label, bearing_deg in (("straight ahead", 0.0), ("60 degrees off the heading", 60.0)):
            s = _new_run(g)
            g.particle_system.particles.clear()
            g.player.dash_charges = 1
            g.player.dash_cooldown = 0.0
            _press_dash_east(g)
            dash_steps = _run_dash_to_end(g)
            # The dash has settled and the echo is out. Now the enemy goes exactly 250 px from the dash end point.
            end = Vec2(g.player.pos.x, g.player.pos.y)
            rad = math.radians(bearing_deg)
            target = _still_enemy(Vec2(end.x + 250.0 * math.cos(rad), end.y + 250.0 * math.sin(rad)))
            s.enemies[:] = [target]
            hp0 = target.hp
            gap = math.hypot(target.pos.x - end.x, target.pos.y - end.y)
            assert abs(gap - 250.0) < 1e-6, gap
            hits = 0
            hit_at = None
            hp_before = target.hp
            for n in range(1, 121):
                g._fixed_step()
                if target.hp < hp_before:
                    hits += 1
                    hit_at = n * FRAME
                    hp_before = target.hp
            dmg = hp0 - target.hp
            want = echo.echo_damage(g._effective_player_damage())
            report.append((label, dash_steps, round(gap, 1), hits, dmg, hit_at))
            assert hits == 1, f"{label}: the echo should hit exactly once (hits={hits})"
            assert dmg == want == 6, f"{label}: echo damage {dmg}, want {want}"
            assert not _echoes(s), f"{label}: the echo is gone once it hits"
    finally:
        _restore_saves(g, scratch, previous)
        g.close()
    for label, dash_steps, gap, hits, dmg, hit_at in report:
        print(f"  echo report: {label}: dash {dash_steps} steps, enemy {gap} px from the dash end, "
              f"echo hits {hits}, damage {dmg}, hit {hit_at:.2f} s after the dash ended")
    print("[PASS] test_scripted_dash_echo_hits_enemy_250_px_away passed (the echo hits the 250 px enemy, straight and off-axis)")


def run_all():
    test_config_block_and_switch()
    test_drop_sets_damage_speed_ttl_and_owner()
    test_damage_is_sixty_percent_of_effective_damage()
    test_exactly_one_echo_per_dash()
    test_echo_flies_along_the_dash_heading_and_expires_at_1_6_seconds()
    test_homing_turns_toward_the_nearest_enemy()
    test_homing_stops_after_1_2_seconds_and_skips_other_shots()
    test_ring_pulse_at_the_drop_point_and_reduced_motion()
    test_nothing_happens_when_disabled()
    test_steering_leaves_no_memory_behind()
    test_scripted_dash_echo_hits_enemy_250_px_away()
    print("\nALL W8 ECHO-DASH TESTS PASSED")


if __name__ == "__main__":
    run_all()
