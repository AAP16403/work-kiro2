"""Regression tests for the verified swarm review findings.

Covers: the web elite score multiplier, the chaser lunge cooldown cadence, the Full / Reduced / Off
screen shake setting, damage-scaled bullet shake, the auto-fire status priority and the flak balance
pass. Pure logic tests run without a window; the Game-backed tests share one hidden window in run_all().
"""

import ast
import importlib.util
import json
import os
import random
import sys
import tempfile
import types

import audio
import config
import shake_prefs
from config import PLAYER_DAMAGE
from enemy import Enemy
from enemy_behaviors.chase import Chase
from game import Game
from projectile import Projectile, spawn_projectiles
from score import ScoreTracker
from states import GameStateName, add_shake, projectile_hit_impulse
from utils import Vec2
from weapons import WEAPONS, _pool_weights_for_wave, get_weapon_pool_for_wave

HERE = os.path.dirname(os.path.abspath(__file__))
DT = 1.0 / 60.0


class _Shake:
    """Minimal stand-in for a run state: only the shake amplitude matters to these tests."""

    def __init__(self, shake: float = 0.0):
        self.shake = float(shake)


class _NoCritRng:
    """Stand-in RNG that never crits and never jitters, so shot counts and damage are exact."""

    def random(self):
        return 1.0

    def uniform(self, a, b):
        return (a + b) / 2.0


def _load_vercel_module(name):
    path = os.path.join(HERE, "vercel_site", "py", name + ".py")
    mod_name = "vercel_" + name
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Call update() directly so the fixed-step simulation runs exactly once per call.
    for _ in range(frames):
        g.dispatch_events()
        g.update(DT)


def _stationary_enemy(s, hp: int = 100000):
    e = Enemy(pos=Vec2(120.0, 0.0), hp=hp, speed=0.0, behavior="chase", max_hp=hp)
    s.enemies = [e]
    return e


def _spawn_bullet(s, enemy, damage: int, crit: bool = False):
    s.projectiles.append(
        Projectile(
            pos=Vec2(enemy.pos.x, enemy.pos.y),
            vel=Vec2(0.0, 0.0),
            damage=damage,
            ttl=1.0,
            owner="player",
            projectile_type="bullet",
            is_crit=crit,
        )
    )


# ---------------------------------------------------------------------------
# Finding: web build never applied the elite score multiplier (vercel score.py and browser_game.py)
# ---------------------------------------------------------------------------

def test_web_score_tracker_applies_elite_multiplier():
    vs = _load_vercel_module("score")
    vconfig = _load_vercel_module("config")
    assert float(vconfig.ELITE_SCORE_MULT) == float(config.ELITE_SCORE_MULT), "web and desktop elite multiplier must match"

    assert vs.ScoreTracker().on_enemy_kill("chaser") == 100, "a plain web kill keeps its base points"
    elite = vs.ScoreTracker().on_enemy_kill("chaser", multiplier=float(vconfig.ELITE_SCORE_MULT))
    desktop = ScoreTracker().on_enemy_kill("chaser", multiplier=float(config.ELITE_SCORE_MULT))
    assert elite == desktop == int(100 * float(config.ELITE_SCORE_MULT)), f"elite web kill {elite} must match desktop {desktop}"
    print(f"[PASS] test_web_score_tracker_applies_elite_multiplier passed (elite chaser scores {elite} on web and desktop)")


def test_web_kill_path_passes_elite_multiplier():
    # browser_game imports js/pyodide, so it cannot run on desktop. Check the call sites instead.
    path = os.path.join(HERE, "vercel_site", "py", "browser_game.py")
    with open(path, "r", encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "on_enemy_kill"
    ]
    assert calls, "browser_game must still record kills through on_enemy_kill"
    for call in calls:
        assert any(k.arg == "multiplier" for k in call.keywords), f"web kill at line {call.lineno} skips the elite multiplier"
    print("[PASS] test_web_kill_path_passes_elite_multiplier passed (every web kill passes a multiplier)")


# ---------------------------------------------------------------------------
# Finding: lunge cooldown counted the windup twice (enemy_behaviors/chase.py)
# ---------------------------------------------------------------------------

def test_chaser_lunge_interval_equals_cooldown_roll():
    random.seed(7)
    behavior = Chase()
    chaser = Enemy(pos=Vec2(0.0, 0.0), hp=30, speed=110.0, behavior="chaser", seed=1.0)
    chaser.ai = {"lunge_cd": 0.0, "lunge_t": 0.0}
    state = types.SimpleNamespace(enemies=[chaser], projectiles=[])
    trigger_times = []
    prev_windup = 0.0
    t = 0.0
    for _ in range(int(40.0 / DT)):
        chaser.pos = Vec2(160.0, 0.0)  # hold the player inside the 80-240 px lunge band
        behavior.update(chaser, Vec2(0.0, 0.0), state, DT, Vec2(0.0, 0.0))
        t += DT
        windup = float(chaser.ai["lunge_windup"])
        if windup > 0.0 and prev_windup <= 0.0:
            trigger_times.append(t)
        prev_windup = windup
    intervals = [b - a for a, b in zip(trigger_times, trigger_times[1:])]
    assert len(intervals) >= 8, f"expected several lunges in 40 s, got {len(intervals)}"
    # The cooldown roll is 1.4-2.0 s. Subtracting the windup again would put intervals near 1.18-1.78 s.
    for iv in intervals:
        assert 1.4 - 2 * DT <= iv <= 2.0 + 2 * DT, f"lunge interval {iv:.3f}s is shorter than the 1.4-2.0 s cooldown roll"
    print(f"[PASS] test_chaser_lunge_interval_equals_cooldown_roll passed ({len(intervals)} lunges, intervals {min(intervals):.2f}-{max(intervals):.2f}s)")


# ---------------------------------------------------------------------------
# Finding: screen shake was two-state; the plan requires Full 1.0, Reduced 0.5 and Off 0.0
# ---------------------------------------------------------------------------

def test_shake_levels_map_to_full_reduced_and_off():
    assert shake_prefs.shake_scale_for_level("full") == 1.0
    assert shake_prefs.shake_scale_for_level("reduced") == 0.5
    assert shake_prefs.shake_scale_for_level("off") == 0.0
    assert shake_prefs.shake_scale_for_level("nonsense") == 1.0, "unknown levels fall back to Full"
    assert shake_prefs.shake_level_is_reduced("off") and shake_prefs.shake_level_is_reduced("reduced")
    assert not shake_prefs.shake_level_is_reduced("full")
    assert config.SHAKE_LEVELS == ("full", "reduced", "off"), "the menu cycles Full, Reduced, Off"
    print("[PASS] test_shake_levels_map_to_full_reduced_and_off passed (1.0 / 0.5 / 0.0 and the boolean view)")


def test_shake_level_file_round_trip_and_legacy_key():
    saved_path = audio._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "user_settings.json")
        audio._SETTINGS_PATH = path
        try:
            assert shake_prefs.load_shake_level() == "full", "a missing file reads as Full"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"reduced_shake": True}, fh)
            assert shake_prefs.load_shake_level() == "reduced", "a legacy reduced_shake=true maps to Reduced"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"shake_level": "off", "reduced_shake": True, "music_volume": 0.4}, fh)
            assert shake_prefs.load_shake_level() == "off", "the level key wins over the legacy flag"
            shake_prefs.save_shake_level("reduced")
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            assert data["shake_level"] == "reduced" and data["reduced_shake"] is True, "save writes the level and its derived flag"
            assert data["music_volume"] == 0.4, "saving shake must keep the audio volume"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"shake_level": "bogus"}, fh)
            assert shake_prefs.load_shake_level() == "full", "an unknown level value reads as the default"
        finally:
            audio._SETTINGS_PATH = saved_path
    print("[PASS] test_shake_level_file_round_trip_and_legacy_key passed (level persists, legacy flag still read)")


def test_shake_off_silences_every_impulse(g):
    saved_path = audio._SETTINGS_PATH
    saved_scale = config.SHAKE_SCALE
    saved_level = str(g.settings.get("shake_level", "full"))
    saved_flag = bool(g.settings.get("reduced_shake", False))
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "user_settings.json")
        audio._SETTINGS_PATH = path
        try:
            g._on_settings_change({"shake_level": "off"})
            assert config.SHAKE_SCALE == 0.0, "Off must set the shake scale to 0.0"
            assert g.settings["shake_level"] == "off" and g.settings["reduced_shake"] is True
            s = _Shake()
            add_shake(s, 9.0)
            add_shake(s, 4.0, limit=4.0)
            assert s.shake == 0.0, "Off must add no shake at all"
            assert shake_prefs.load_shake_level() == "off", "Off must be written to user_settings.json"

            g._on_settings_change({"shake_level": "reduced"})
            assert abs(config.SHAKE_SCALE - 0.5) < 1e-9, "Reduced must set the scale to 0.5"
            s = _Shake()
            add_shake(s, 4.0)
            assert abs(s.shake - 2.0) < 1e-9, "Reduced halves every impulse"

            g._on_settings_change({"shake_level": "full"})
            assert config.SHAKE_SCALE == 1.0, "Full restores the 1.0 scale"
            assert shake_prefs.load_shake_level() == "full"
        finally:
            audio._SETTINGS_PATH = saved_path
            config.SHAKE_SCALE = saved_scale
            g.settings["shake_level"] = saved_level
            g.settings["reduced_shake"] = saved_flag
            g.settings_menu.shake_level = saved_level
            g.settings_menu._refresh_shake_button_text()
    print("[PASS] test_shake_off_silences_every_impulse passed (Off is silent, Reduced halves, Full restores)")


# ---------------------------------------------------------------------------
# Finding: bullet hit shake was flat per hit (states.py); it is meant to scale with damage
# ---------------------------------------------------------------------------

def test_bullet_hit_impulse_scales_with_damage():
    assert abs(projectile_hit_impulse(PLAYER_DAMAGE) - config.SHAKE_HIT_IMPULSE) < 1e-9, "the basic gun keeps the base impulse"
    assert abs(projectile_hit_impulse(5) - config.SHAKE_HIT_IMPULSE) < 1e-9, "weak bullets never drop below the base"
    plasma = projectile_hit_impulse(WEAPONS["plasma"].damage)
    assert config.SHAKE_HIT_IMPULSE < plasma < config.SHAKE_HIT_FRAME_MAX, f"plasma should shake between base and the clamp, got {plasma}"
    heavy = projectile_hit_impulse(WEAPONS["heavy"].damage)
    assert abs(heavy - config.SHAKE_HIT_FRAME_MAX) < 1e-9, "a double-damage hit lands on the 1.5x scale cap"
    assert abs(projectile_hit_impulse(WEAPONS["railgun"].damage) - heavy) < 1e-9, "the scale is capped, so railgun does not exceed heavy"
    assert abs(projectile_hit_impulse(PLAYER_DAMAGE, True) - config.SHAKE_CRIT_IMPULSE) < 1e-9, "a basic crit keeps the 3 px crit impulse"
    assert projectile_hit_impulse(20, True) > projectile_hit_impulse(20, False), "a crit adds its impulse on top"
    print(f"[PASS] test_bullet_hit_impulse_scales_with_damage passed (basic 2.0, plasma {plasma:.1f}, capped {heavy:.1f}, crit 3.0)")


def test_damage_scaled_hit_reaches_the_shake_state(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    s.wave_active = True
    e = _stationary_enemy(s)
    decay = float(config.SHAKE_DECAY) * float(g.balance.fixed_dt)

    s.shake = 0.0
    _spawn_bullet(s, e, PLAYER_DAMAGE)
    _tick(g)
    assert abs(s.shake - (config.SHAKE_HIT_IMPULSE - decay)) < 1e-6, f"basic-damage hit should give the base impulse, got {s.shake}"

    s.shake = 0.0
    s.projectiles.clear()
    _spawn_bullet(s, e, WEAPONS["heavy"].damage)
    _tick(g)
    expected = config.SHAKE_HIT_FRAME_MAX - decay
    assert abs(s.shake - expected) < 1e-6, f"a 20-damage hit should shake harder than basic, got {s.shake}"
    print("[PASS] test_damage_scaled_hit_reaches_the_shake_state passed (basic 2.0 px, heavy hits the 3 px frame clamp)")


# ---------------------------------------------------------------------------
# Finding: flak was an unbalanced permanent top rank that wave 5-6 could lock in
# ---------------------------------------------------------------------------

def test_flak_balance_pass_desktop_and_web():
    vw = _load_vercel_module("weapons")
    for mod, label in ((None, "desktop"), (vw, "web")):
        weapons = WEAPONS if mod is None else mod.WEAPONS
        pool = get_weapon_pool_for_wave if mod is None else mod.get_weapon_pool_for_wave
        assert weapons["flak"].projectile_count == 3, f"{label} flak must fire 3 pellets"
        assert "flak" not in pool(5) and "flak" not in pool(6), f"{label} flak must not enter the wave 5-6 pool"
        assert "flak" in pool(7), f"{label} flak must still appear from wave 7"
    assert {k: w.rank for k, w in vw.WEAPONS.items()} == {k: w.rank for k, w in WEAPONS.items()}, "web and desktop ranks must match"
    assert WEAPONS["flak"].rank == max(w.rank for w in WEAPONS.values()), "flak keeps the top rank"

    for wave in range(1, 13):
        assert len(_pool_weights_for_wave(wave)) == len(get_weapon_pool_for_wave(wave)), f"wave {wave}: weights must align with the pool"
    print("[PASS] test_flak_balance_pass_desktop_and_web passed (3 pellets, held out of waves 5-6, ranks and pools mirrored)")


def test_flak_fires_three_pellets():
    shots = spawn_projectiles(Vec2(0.0, 0.0), Vec2(1.0, 0.0), WEAPONS["flak"], 0.0, 11, rng=_NoCritRng())
    assert len(shots) == 3, f"flak should fire 3 pellets, got {len(shots)}"
    print("[PASS] test_flak_fires_three_pellets passed (one shot is three cluster pellets)")


def run_all():
    pure_tests = [
        test_web_score_tracker_applies_elite_multiplier,
        test_web_kill_path_passes_elite_multiplier,
        test_chaser_lunge_interval_equals_cooldown_roll,
        test_shake_levels_map_to_full_reduced_and_off,
        test_shake_level_file_round_trip_and_legacy_key,
        test_bullet_hit_impulse_scales_with_damage,
        test_flak_balance_pass_desktop_and_web,
        test_flak_fires_three_pellets,
    ]
    for test in pure_tests:
        test()

    g = Game()
    g.set_visible(False)
    saved_scale = config.SHAKE_SCALE
    try:
        test_shake_off_silences_every_impulse(g)
        test_damage_scaled_hit_reaches_the_shake_state(g)
    finally:
        config.SHAKE_SCALE = saved_scale
        g.close()
    print("\nALL SWARM FIX REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
