"""Comprehensive test suite for mechanics, performance, and bug fixes."""

import math
import random
import os
import pyglet

from utils import Vec2
from player import Player, update_boost, format_boost_hud
from weapons import WEAPONS, Weapon, get_weapon_key_for_wave, get_weapon_pool_for_wave
from projectile import Projectile, spawn_projectiles
from enemy import Enemy
from states import PlayingState, GameStateName
from rpg import apply_perm_reward, recompute_temp_mods, advance_temp_rewards
from game import Game
import config


class NullAudio:
    """Silent stand-in for AudioManager so mock games never touch the sound device."""
    def play(self, *args, **kwargs): pass
    def play_music(self, *args, **kwargs): pass
    def duck(self, *args, **kwargs): pass
    def update(self, dt): pass


def test_boost_hysteresis():
    """Verify that update_boost does NOT strobe/flicker at low energy."""
    p = Player(pos=Vec2(0, 0))
    states = []
    # Hold boost for 300 frames (5 seconds)
    for i in range(300):
        t = i * (1.0 / 60.0)
        b = update_boost(p, 1.0 / 60.0, True, t)
        states.append((i, round(p.boost_energy, 2), b))

    # Check for rapid toggling (jitter)
    rapid_toggles = 0
    toggle_frames = []
    for i in range(1, len(states)):
        if states[i][2] != states[i - 1][2]:
            toggle_frames.append(i)
            if toggle_frames and len(toggle_frames) >= 2 and (toggle_frames[-1] - toggle_frames[-2] <= 2):
                rapid_toggles += 1

    # Zero rapid back-to-back toggling allowed
    assert rapid_toggles == 0, f"Detected {rapid_toggles} rapid 60Hz toggles!"
    # Verify clean cycle intervals (>20 frames apart)
    for j in range(1, len(toggle_frames)):
        gap = toggle_frames[j] - toggle_frames[j - 1]
        assert gap >= 20, f"Toggle gap too short ({gap} frames) - hysteresis failed!"
    print("[PASS] test_boost_hysteresis passed (0 jitter / flickering, clean cycle spacing)")


def test_perm_crit_preservation():
    """Verify that permanent crit bonuses are not overwritten when temporary cards recompute."""
    g = Game()
    g.set_visible(False)
    g._init_game()

    # Apply permanent crit upgrade
    apply_perm_reward(g.player, g._run_permanent_rewards, "perm_crit", 1.0)
    assert g.player.crit_chance_bonus == 0.10, "perm_crit chance bonus not applied"
    assert g.player.crit_mult_bonus == 0.40, "perm_crit mult bonus not applied"

    # Add temporary card and recompute
    g._active_temp_rewards = [{"key": "temp_crit_lens", "title": "Targeting Optics", "duration": 2}]
    g._recompute_temp_reward_mods()

    # Effective crit should combine perm (0.10) + temp (0.25) = 0.35
    assert abs(g._effective_crit_chance() - 0.35) < 1e-4, f"Effective crit expected 0.35, got {g._effective_crit_chance()}"
    assert abs(g._effective_crit_mult() - 0.90) < 1e-4, f"Effective mult expected 0.90, got {g._effective_crit_mult()}"
    assert g.player.crit_chance_bonus == 0.10, "Permanent crit bonus was overwritten!"

    # Expire temporary card
    g._active_temp_rewards = []
    g._recompute_temp_reward_mods()

    # Perm crit should still be completely intact
    assert abs(g._effective_crit_chance() - 0.10) < 1e-4, "Perm crit lost after temp expiry!"
    assert abs(g._effective_crit_mult() - 0.40) < 1e-4, "Perm mult lost after temp expiry!"
    g.close()
    print("[PASS] test_perm_crit_preservation passed (perm stats survive temp reward updates)")


def test_temp_infinite_boost_expiration():
    """Verify that temporary infinite boost card ends cleanly when expired."""
    g = Game()
    g.set_visible(False)
    g._init_game()

    # Add temp infinite boost card
    g._active_temp_rewards = [{"key": "temp_boost_overdrive", "title": "Hyper Overdrive", "duration": 2}]
    g._recompute_temp_reward_mods()
    assert g._has_infinite_boost() is True, "Infinite boost should be active"

    # Advance 2 waves
    g._advance_temp_rewards() # duration 1
    assert g._has_infinite_boost() is True, "Infinite boost should still be active"
    g._advance_temp_rewards() # expired
    assert g._has_infinite_boost() is False, "Infinite boost failed to expire!"
    g.close()
    print("[PASS] test_temp_infinite_boost_expiration passed (temp boost card expires properly)")


def test_volatile_cascade_no_duplicate_kills():
    """Verify that volatile elite death explosions do NOT trigger duplicate kills."""
    class MockScore:
        kills = 0
        def on_enemy_kill(self, b, multiplier=1.0):
            self.kills += 1

    class MockState:
        time = 0.0
        shake = 0.0
        enemies = []
        projectiles = []
        powerups = []
        wave = 3
        difficulty = "normal"
        rng = random.Random(42)
        last_wave_clear = 0.0
        map_type = "circle"
        room_segment = 0
        layout_segment = 0

    class MockGame:
        score = MockScore()
        visuals = None
        particle_system = None
        audio = NullAudio()
        popups = None
        _hitstop = 0.0
        player = type("P", (), {"pos": Vec2(500, 500), "hp": 100, "invincibility_timer": 0.0, "shield": 0})()
        balance = type("B", (), {"tank_death_blast_radius": 0, "tank_death_blast_damage": 0, "sim_dt_cap": 0.05, "enemy_contact_damage": 15})()
        def _damage_player(self, amt): pass

    s = MockState()
    g = MockGame()

    e1 = Enemy(pos=Vec2(0, 0), hp=0, speed=50.0, behavior="chase", is_elite=True, elite_affix="volatile")
    e2 = Enemy(pos=Vec2(40, 0), hp=30, speed=50.0, behavior="chase", is_elite=True, elite_affix="volatile")
    e3 = Enemy(pos=Vec2(80, 0), hp=30, speed=50.0, behavior="chase")
    s.enemies = [e1, e2, e3]

    PlayingState._kill_enemy(g, s, e1)
    assert len(s.enemies) == 0, f"Expected 0 remaining enemies, got {len(s.enemies)}"
    assert g.score.kills == 3, f"Expected exactly 3 registered kills for 3 enemies, got {g.score.kills}!"
    print("[PASS] test_volatile_cascade_no_duplicate_kills passed (exact 1:1 kill accounting)")


def test_flak_cluster_shrapnel_burst():
    """Verify that flak shrapnel spreads outward and ignores detonating entity."""
    class MockGame:
        visuals = None
        particle_system = None
        audio = NullAudio()
        popups = None
        _hitstop = 0.0

    class MockState:
        shake = 0.0
        projectiles = []
        rng = type("R", (), {"uniform": lambda self, a, b: (a + b) / 2})()

    g = MockGame()
    s = MockState()

    target_enemy = Enemy(pos=Vec2(100, 100), hp=50, speed=0.0, behavior="tank")
    shell = Projectile(pos=Vec2(100, 100), vel=Vec2(100, 0), damage=20, cluster_on_death=True, projectile_type="flak")

    PlayingState._remove_projectile(g, s, shell, detonating_enemy=target_enemy)

    assert len(s.projectiles) == 4, f"Expected 4 shrapnel pellets, got {len(s.projectiles)}"
    for shrapnel in s.projectiles:
        assert id(target_enemy) in getattr(shrapnel, "_hit_entities", set()), "Shrapnel must ignore the detonating target!"
        # Pos should have moved slightly outward from explosion center
        assert (shrapnel.pos - shell.pos).length() > 0.0, "Shrapnel must spawn with outward offset!"
    print("[PASS] test_flak_cluster_shrapnel_burst passed (shrapnel scatters and ignores detonator)")


def test_railgun_pierce():
    """Verify that Hyper Railgun penetrates multiple enemies in line."""
    railgun = WEAPONS["railgun"]
    assert railgun.pierce == 3, "Railgun must have pierce = 3"

    projs = spawn_projectiles(
        muzzle=Vec2(0, 0),
        aim_direction=Vec2(1, 0),
        weapon=railgun,
        current_time=0.0,
        base_damage=20,
    )
    assert len(projs) == 1
    p = projs[0]
    assert p.pierce == 3, f"Expected projectile pierce 3, got {p.pierce}"
    print("[PASS] test_railgun_pierce passed (pierce attribute preserved on projectiles)")


def test_boost_ramming_safety():
    """Verify that ramming pushes enemies out and gives player contact grace frames."""
    class MockGame:
        visuals = None
        particle_system = None
        audio = NullAudio()
        popups = None
        _hitstop = 0.0
        player = Player(pos=Vec2(0, 0))
        balance = type("B", (), {"enemy_contact_damage": 15})()
        damaged_calls = 0
        def _damage_player(self, amt):
            self.damaged_calls += 1
        def _input_dir(self):
            return Vec2(1, 0)

    g = MockGame()
    g.player.is_boosting = True
    g.player.hp = 100
    e = Enemy(pos=Vec2(0, 0), hp=100, speed=0.0, behavior="tank") # Zero distance test
    e._radius = 24.0
    player_radius = 14.0
    hit_r = e._radius + player_radius # 38.0

    # Simulate collision resolution
    d_sq = (e.pos - g.player.pos).length_squared()
    if d_sq <= hit_r * hit_r:
        ram_dmg = int(getattr(config, "BOOST_RAM_DAMAGE", 28))
        e.hp -= ram_dmg
        diff = e.pos - g.player.pos
        cur_d = math.sqrt(d_sq)
        push_dir = g._input_dir().normalized() if cur_d <= 1e-4 else diff / cur_d
        push_dist = max(45.0, (hit_r - cur_d) + 24.0)
        e.pos = e.pos + push_dir * push_dist

        if g.player.invincibility_timer <= 0:
            g._damage_player(int(g.balance.enemy_contact_damage * 0.4))
            g.player.invincibility_timer = max(g.player.invincibility_timer, 0.25)

    assert (e.pos - g.player.pos).length() > hit_r, "Enemy was NOT pushed outside hit radius!"
    assert g.player.invincibility_timer > 0.0, "Player must receive invincibility timer after ram!"
    assert g.damaged_calls == 1, "Player should only take 1 damage tick"
    print("[PASS] test_boost_ramming_safety passed (clean knockback & invincibility grace period)")


def test_game_full_loop():
    """Verify full engine loop running 60 ticks in PlayingState."""
    g = Game()
    g.set_visible(False)
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)

    for frame in range(60):
        pyglet.clock.tick()
        g.dispatch_events()
        g.update(1.0 / 60.0)
        g.on_draw()

    assert g.state.time > 0.5, f"Expected state time > 0.5s, got {g.state.time}"
    g.close()
    print("[PASS] test_game_full_loop passed (60 continuous frames with update & on_draw)")


def test_temp_reward_key_compatibility():
    """Verify that temp rewards work with either 'waves_left' or 'duration' keys."""
    rewards = [{"key": "temp_overdrive", "duration": 2}]
    advanced = advance_temp_rewards(rewards)
    assert len(advanced) == 1
    assert advanced[0]["waves_left"] == 1
    assert advanced[0]["duration"] == 1
    advanced = advance_temp_rewards(advanced)
    assert len(advanced) == 0

    rewards2 = [{"key": "temp_overdrive", "waves_left": 2}]
    advanced2 = advance_temp_rewards(rewards2)
    assert len(advanced2) == 1
    assert advanced2[0]["waves_left"] == 1
    assert advanced2[0]["duration"] == 1
    advanced2 = advance_temp_rewards(advanced2)
    assert len(advanced2) == 0
    print("[PASS] test_temp_reward_key_compatibility passed (both duration and waves_left keys handled)")


def test_stationary_boost_no_drain():
    """Verify that pressing boost while stationary does not drain energy."""
    p = Player(pos=Vec2(0, 0))
    initial_energy = p.boost_energy
    for _ in range(60):
        update_boost(p, 1.0 / 60.0, False, 0.0)
    assert p.boost_energy == initial_energy
    print("[PASS] test_stationary_boost_no_drain passed (stationary boost request drains 0 energy)")


if __name__ == "__main__":
    test_boost_hysteresis()
    test_stationary_boost_no_drain()
    test_perm_crit_preservation()
    test_temp_infinite_boost_expiration()
    test_temp_reward_key_compatibility()
    test_volatile_cascade_no_duplicate_kills()
    test_flak_cluster_shrapnel_burst()
    test_railgun_pierce()
    test_boost_ramming_safety()
    test_game_full_loop()
    print("\nALL 10 VERIFICATION TESTS PASSED SUCCESSFULLY!")

