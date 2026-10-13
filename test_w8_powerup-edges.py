"""Wave 8 powerup-edges tests: four edges from the verification batch, one group of checks per fix.

    1. Chain Lightning fires on every kill the player makes: bullets, lasers, the vortex, a boost ram and the Ultra.
       Enemy-caused kills (contact, the volatile blast, splitter copies) still never chain.
    2. A Repulsor cooldown starts when its shot fires, so the next shot lands exactly REPULSOR_COOLDOWN_SECONDS
       (720 frames at 60 FPS) after the first, on the pending path and on the stored-charge path.
    3. Whole-second countdowns read exactly: 10.000000000000002 seconds left shows 10, not 11, in the Repulsor
       cooldown, the timed powerup labels and the weapon chip.
    4. A stunned non-boss enemy deals no contact damage and does not kill itself on contact. A boost ram into it
       still works. Bosses are unchanged.

The real-run checks drive a Game through _fixed_step and on_draw, the way test_w6_wiring does. A far, slow guard
enemy keeps the wave open so no wave spawns mid-check. ENABLE_POWERUP_EDGES = False restores the wave-6 rules,
and one check confirms that. Plain functions that print [PASS] lines, run from run_all().
"""

from types import SimpleNamespace

import pyglet

import chain
import config
import repulsor
from enemy import Enemy
from game import Game
from player import Player
from powerup import PowerUp, apply_powerup, format_timed_powerups_hud, weapon_pickup_secs_left
from states import GameStateName
from utils import Vec2, to_iso

FRAME = 1.0 / 60.0
COOL_FRAMES = int(round(float(config.REPULSOR_COOLDOWN_SECONDS) / FRAME))  # 720 at 60 FPS
COOL = float(config.REPULSOR_COOLDOWN_SECONDS)


def _new_run(g):
    """A fresh run in PLAYING with no auto-fire, the player at the origin and one far, slow guard enemy."""
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.state.wave_active = True
    g.player.pos = Vec2(0.0, 0.0)
    s = g.state
    s.enemies[:] = [Enemy(pos=Vec2(-400.0, 0.0), hp=50, speed=0.0, behavior="chaser")]  # keeps the wave open
    return s


def _steps(g, n):
    for _ in range(n):
        g._fixed_step()


def _enemy(x, y, hp=100, **kw):
    """A slow chaser at (x, y). speed 0 keeps it where the check put it."""
    return Enemy(pos=Vec2(float(x), float(y)), hp=int(hp), speed=0.0, behavior="chaser", **kw)


def _aim_east(g):
    """Point the aim along +x from the player, so a laser or Ultra beam runs through enemies on the x axis."""
    g.mouse_xy = to_iso(Vec2(100.0, 0.0), Vec2(0.0, 0.0))


def _pickup(player, kind, now):
    apply_powerup(player, PowerUp(pos=Vec2(0.0, 0.0), kind=kind), now)


def _player():
    return Player(pos=Vec2(0.0, 0.0))


def _run_state():
    return SimpleNamespace(projectiles=[], enemies=[])


def _arc_check(g, victim, neighbour, label):
    """After the killing step: the victim is gone, one arc was thrown and it hit the neighbour."""
    assert victim not in g.state.enemies, f"{label}: the victim should be dead"
    assert g.chain_pool.live_count == 1, f"{label}: one kill should throw one arc, got {g.chain_pool.live_count}"
    assert neighbour.hp == 100 - chain.chain_damage(g.player.damage), f"{label}: neighbour hp {neighbour.hp}"


# ---------------------------------------------------------------- config

def test_config_switch_and_rounding_block():
    assert config.ENABLE_POWERUP_EDGES is True
    assert int(config.COUNTDOWN_ROUND_DIGITS) == 6
    assert COOL_FRAMES == 720, COOL_FRAMES
    print("[PASS] test_config_switch_and_rounding_block passed (switch on, 6 decimals, 720 frames per cooldown)")


# ---------------------------------------------------------------- fix 1: chain on every player kill

def test_laser_kill_throws_an_arc():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        g.auto_shoot = True
        _aim_east(g)
        _pickup(g.player, "chain", s.time)
        _pickup(g.player, "laser", s.time)
        victim = _enemy(120.0, 0.0, hp=1)  # on the beam, one hp
        neighbour = _enemy(180.0, 100.0)   # off the beam, 117 px from the victim (inside CHAIN_RANGE)
        s.enemies.extend([victim, neighbour])
        assert g.chain_pool.live_count == 0
        _steps(g, 1)  # the laser shot fires on this step
        _arc_check(g, victim, neighbour, "laser")
    finally:
        g.close()
    print("[PASS] test_laser_kill_throws_an_arc passed (laser kill throws one arc that hits the neighbour)")


def test_vortex_kill_throws_an_arc():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        _pickup(g.player, "chain", s.time)
        _pickup(g.player, "vortex", s.time)
        victim = _enemy(40.0, 0.0, hp=1)   # inside the vortex radius (70 px)
        neighbour = _enemy(40.0, 100.0)    # outside the vortex, 100 px from the victim
        s.enemies.extend([victim, neighbour])
        killed = False
        for _ in range(12):
            _steps(g, 1)
            if victim not in s.enemies:
                killed = True
                break
            assert g.chain_pool.live_count == 0, "no arc before the kill"
        assert killed, "the vortex should kill the one-hp victim within 12 steps"
        _arc_check(g, victim, neighbour, "vortex")
    finally:
        g.close()
    print("[PASS] test_vortex_kill_throws_an_arc passed (vortex kill: one arc, neighbour hit)")


class _Keys(dict):
    """Stands in for the window's key handler: held keys are True, every other key reads False."""

    def __missing__(self, key):
        return False


def test_boost_ram_kill_throws_an_arc():
    """A boost ram into a stunned enemy still kills it, and the kill chains. The ram is the player's action."""
    g = Game()
    g.set_visible(False)
    k = pyglet.window.key
    try:
        s = _new_run(g)
        _pickup(g.player, "chain", s.time)
        g.keys = _Keys({k.LSHIFT: True, k.D: True})  # boost held and moving, so the boost is active
        victim = _enemy(10.0, 0.0, hp=1)
        victim.stun_until = s.time + 5.0  # stunned by a Repulsor
        neighbour = _enemy(60.0, 100.0)
        s.enemies.extend([victim, neighbour])
        _steps(g, 1)
        assert g.player.is_boosting, "the ram needs an active boost"
        _arc_check(g, victim, neighbour, "boost ram")
    finally:
        g.close()
    print("[PASS] test_boost_ram_kill_throws_an_arc passed (ram kills a stunned enemy, and the kill chains)")


def test_ultra_kill_throws_an_arc():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        _aim_east(g)
        _pickup(g.player, "chain", s.time)
        g.player.ultra_charges = 1
        victim = _enemy(120.0, 0.0, hp=1)  # on the Ultra beam
        neighbour = _enemy(180.0, 100.0)
        s.enemies.extend([victim, neighbour])
        g._use_ultra()
        _arc_check(g, victim, neighbour, "ultra")
    finally:
        g.close()
    print("[PASS] test_ultra_kill_throws_an_arc passed (Ultra kill: one arc, neighbour hit)")


def test_enemy_caused_kills_throw_no_arc():
    g = Game()
    g.set_visible(False)
    try:
        # Contact suicide: a live chaser on the player dies on contact.
        s = _new_run(g)
        _pickup(g.player, "chain", s.time)
        hp_before = g.player.hp
        contact = _enemy(0.0, 0.0, hp=1)
        far = _enemy(60.0, 100.0)
        s.enemies.extend([contact, far])
        _steps(g, 1)
        assert contact not in s.enemies and g.player.hp < hp_before, "the contact kill should land"
        assert g.chain_pool.live_count == 0, "a contact suicide throws no arc"
        assert far.hp == 100

        # Volatile blast: the elite's contact death blasts a second enemy. The blast kill throws no arc.
        s = _new_run(g)
        _pickup(g.player, "chain", s.time)
        volatile = _enemy(0.0, 0.0, hp=1, is_elite=True, elite_affix="volatile", max_hp=20)
        blasted = _enemy(60.0, 0.0, hp=1)     # inside the 130 px blast
        outside = _enemy(200.0, 0.0)          # outside the blast, 140 px from the blasted enemy
        s.enemies.extend([volatile, blasted, outside])
        _steps(g, 1)
        assert blasted not in s.enemies, "the volatile blast should kill the one-hp enemy"
        assert g.chain_pool.live_count == 0, "a volatile blast kill throws no arc"
        assert outside.hp == 100

        # Splitter: the elite's contact death leaves two copies and no kill.
        s = _new_run(g)
        _pickup(g.player, "chain", s.time)
        splitter = _enemy(0.0, 0.0, hp=1, is_elite=True, elite_affix="splitter", max_hp=40)
        s.enemies.append(splitter)
        _steps(g, 1)
        assert splitter not in s.enemies
        assert len(s.enemies) == 3, f"guard plus two splitter copies, got {len(s.enemies)}"
        assert g.chain_pool.live_count == 0, "the splitter's contact death throws no arc"
    finally:
        g.close()
    print("[PASS] test_enemy_caused_kills_throw_no_arc passed (contact, volatile blast and splitter throw no arc)")


# ---------------------------------------------------------------- fix 2: the cooldown starts at the shot

def test_cooldown_starts_when_the_shot_fires():
    player = _player()
    s = _run_state()
    repulsor.pickup(player, 10.0)
    st = player.repulsor_state
    assert st.fire_pending and st.cooldown_until == 0.0, "the pickup no longer anchors the cooldown"
    assert repulsor.update(player, s, 10.5) == 1, "the pending shot fires one frame after the pickup"
    assert abs(st.cooldown_until - (10.5 + COOL)) < 1e-9, st.cooldown_until
    repulsor.pickup(player, 22.0)  # 11.5 s after the shot: still cooling down, so this stores a charge
    assert not st.fire_pending and st.charges == 1
    assert repulsor.update(player, s, 22.0) == 0, "no shot before the anchored cooldown ends"
    assert repulsor.update(player, s, 22.5) == 1, "the stored charge fires exactly 12 s after the shot"
    print("[PASS] test_cooldown_starts_when_the_shot_fires passed (pickup at 10.0, shot 10.5, next at 22.5)")


def _second_shot_frames(idle_steps: int):
    """Run a real game: a pickup on a ready Repulsor, then a pickup during its cooldown. Returns the step indices of
    the two shockwaves."""
    g = Game()
    g.set_visible(False)
    shots = []
    frame = [0]
    real_fire = repulsor.fire

    def recording_fire(player, s, now, particles=None):
        shots.append(frame[0])
        return real_fire(player, s, now, particles)

    try:
        s = _new_run(g)
        repulsor.fire = recording_fire
        for i in range(idle_steps + COOL_FRAMES + 40):
            frame[0] = i
            if i == idle_steps:
                _pickup(g.player, "repulsor", s.time)       # ready: the shot fires on this step (pending path)
            elif i == idle_steps + 1:
                _pickup(g.player, "repulsor", s.time)       # during the cooldown: stores a charge
            _steps(g, 1)
    finally:
        repulsor.fire = real_fire
        g.close()
    return shots


def test_second_shot_lands_720_frames_after_the_first():
    # Two start offsets: the second run starts after 1000 idle frames, where float noise in the run clock pushed
    # the second shot to 721 frames before the cooldown was rounded.
    for idle in (0, 1000):
        shots = _second_shot_frames(idle)
        assert len(shots) == 2, f"idle {idle}: expected two shockwaves, got {shots}"
        assert shots[0] == idle, f"idle {idle}: the first shot lands on the pickup's step, got {shots}"
        gap = shots[1] - shots[0]
        assert gap == COOL_FRAMES, f"idle {idle}: the second shot landed {gap} frames after the first, not 720"
    print("[PASS] test_second_shot_lands_720_frames_after_the_first passed (stored-charge shot 720 frames after the pending one, from frame 0 and frame 1000)")


# ---------------------------------------------------------------- fix 3: whole-second countdowns

def test_whole_second_countdowns_read_exactly():
    noisy = 10.000000000000002  # 10 seconds plus float noise: must read 10, not 11
    p = _player()
    p.ricochet_until = noisy
    assert format_timed_powerups_hud(p, 0.0) == "Ricochet 10s", format_timed_powerups_hud(p, 0.0)
    p.ricochet_until = 10.0
    assert format_timed_powerups_hud(p, 0.0) == "Ricochet 10s"
    p.ricochet_until = 10.0000004  # under half a microsecond past 10: still 10
    assert format_timed_powerups_hud(p, 0.0) == "Ricochet 10s"
    p.ricochet_until = 10.000001   # a microsecond past 10: 11 s, the next whole second
    assert format_timed_powerups_hud(p, 0.0) == "Ricochet 11s", format_timed_powerups_hud(p, 0.0)
    p.ricochet_until = 1.000001
    assert format_timed_powerups_hud(p, 0.0) == "Ricochet 2s"
    p.ricochet_until = 1.0
    assert format_timed_powerups_hud(p, 0.0) == "Ricochet 1s"
    p.ricochet_until = 1.0
    assert format_timed_powerups_hud(p, 1.0) == "", "at the expiry the label is gone"
    p.ricochet_until = 0.0000001
    assert format_timed_powerups_hud(p, 0.0) == "", "a sub-microsecond remainder shows no '0s' label"

    p.ricochet_until = 0.0
    p.chain_until = noisy
    assert format_timed_powerups_hud(p, 0.0) == "Chain 10s", format_timed_powerups_hud(p, 0.0)

    p.chain_until = 0.0
    p.weapon_until = noisy
    assert weapon_pickup_secs_left(p, 0.0) == 10, weapon_pickup_secs_left(p, 0.0)
    assert weapon_pickup_secs_left(p, 0.5) == 10
    p.weapon_until = 10.000001
    assert weapon_pickup_secs_left(p, 0.0) == 11

    r = _player()
    r.repulsor_state = repulsor.RepulsorState(cooldown_until=noisy)
    assert repulsor.hud_text(r, 0.0) == "Repulsor 10s", repulsor.hud_text(r, 0.0)
    assert repulsor.hud_text(r, noisy) == "", "ready at the exact end, no charge: no text"
    r.repulsor_state.charges = 1
    assert repulsor.hud_text(r, noisy) == "Repulsor x1"
    print("[PASS] test_whole_second_countdowns_read_exactly passed (10.000000000000002 reads 10; 10.000001 reads 11)")


# ---------------------------------------------------------------- fix 4: stunned enemies are inert on contact

def test_stunned_chaser_on_player_takes_no_damage_for_60_steps():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        chaser = _enemy(0.0, 0.0, hp=50)  # on the player: contact every step
        s.enemies.append(chaser)
        _pickup(g.player, "repulsor", s.time)
        before = g.player.hp + g.player.shield
        _steps(g, 1)  # the shockwave fires before the body checks, so the stun is in place on this step
        assert repulsor.is_stunned(chaser, s.time), "the chaser is stunned by the shockwave"
        for i in range(60):
            _steps(g, 1)
            assert g.player.hp + g.player.shield == before, f"contact damage on stunned step {i + 1}"
            assert chaser in s.enemies and chaser.hp == 50, f"the stunned chaser killed itself on step {i + 1}"
        assert repulsor.is_stunned(chaser, s.time), "still inside the 1.5 s stun for all 60 steps"
    finally:
        g.close()

    # Control: the same chaser on the player, not stunned, does hit and kills itself on the first step.
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        chaser = _enemy(0.0, 0.0, hp=50)
        s.enemies.append(chaser)
        before = g.player.hp + g.player.shield
        _steps(g, 1)
        assert g.player.hp + g.player.shield < before, "control: an unstunned contact hurts the player"
        assert chaser not in s.enemies, "control: an unstunned contact kills the chaser"
    finally:
        g.close()
    print("[PASS] test_stunned_chaser_on_player_takes_no_damage_for_60_steps passed (60 steps, no damage, no suicide; control hurts)")


def test_stunned_boss_still_hits_on_contact():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        boss = Enemy(pos=Vec2(0.0, 0.0), hp=500, speed=0.0, behavior="boss_brute")
        boss.stun_until = s.time + 5.0
        s.enemies.append(boss)
        before = g.player.hp + g.player.shield
        _steps(g, 1)
        assert g.player.hp + g.player.shield < before, "a stunned boss still deals contact damage"
        assert boss in s.enemies, "a boss never dies from contact"
    finally:
        g.close()
    print("[PASS] test_stunned_boss_still_hits_on_contact passed (bosses unchanged)")


# ---------------------------------------------------------------- the switch restores wave 6

def test_switch_off_restores_the_wave6_rules():
    prev = config.ENABLE_POWERUP_EDGES
    config.ENABLE_POWERUP_EDGES = False
    g = Game()
    g.set_visible(False)
    try:
        # Countdowns: the float-noise boundary reads 11 again.
        p = _player()
        p.ricochet_until = 10.000000000000002
        assert format_timed_powerups_hud(p, 0.0) == "Ricochet 11s"

        # Cooldown: anchored at the pickup, so the shot at 10.5 leaves the cooldown ending at 22.0.
        r = _player()
        s = _run_state()
        repulsor.pickup(r, 10.0)
        assert repulsor.update(r, s, 10.5) == 1
        assert abs(r.repulsor_state.cooldown_until - 22.0) < 1e-9

        # Chain: a laser kill throws no arc, as before.
        s = _new_run(g)
        g.auto_shoot = True
        _aim_east(g)
        _pickup(g.player, "chain", s.time)
        _pickup(g.player, "laser", s.time)
        victim = _enemy(120.0, 0.0, hp=1)
        neighbour = _enemy(180.0, 100.0)
        s.enemies.extend([victim, neighbour])
        _steps(g, 1)
        assert victim not in s.enemies and g.chain_pool.live_count == 0, "wave 6: laser kills do not chain"

        # Stunned contact: the chaser hurts the player and kills itself, as before.
        s = _new_run(g)
        chaser = _enemy(0.0, 0.0, hp=50)
        s.enemies.append(chaser)
        _pickup(g.player, "repulsor", s.time)
        before = g.player.hp + g.player.shield
        _steps(g, 1)
        assert g.player.hp + g.player.shield < before and chaser not in s.enemies, "wave 6: stunned contact hurts"
    finally:
        g.close()
        config.ENABLE_POWERUP_EDGES = prev
    print("[PASS] test_switch_off_restores_the_wave6_rules passed (switch off: 11 s, cooldown at pickup, no laser chain, stunned contact hurts)")


def run_all():
    test_config_switch_and_rounding_block()
    test_laser_kill_throws_an_arc()
    test_vortex_kill_throws_an_arc()
    test_boost_ram_kill_throws_an_arc()
    test_ultra_kill_throws_an_arc()
    test_enemy_caused_kills_throw_no_arc()
    test_cooldown_starts_when_the_shot_fires()
    test_second_shot_lands_720_frames_after_the_first()
    test_whole_second_countdowns_read_exactly()
    test_stunned_chaser_on_player_takes_no_damage_for_60_steps()
    test_stunned_boss_still_hits_on_contact()
    test_switch_off_restores_the_wave6_rules()
    print("\nALL W8 POWERUP-EDGES TESTS PASSED")


if __name__ == "__main__":
    run_all()
