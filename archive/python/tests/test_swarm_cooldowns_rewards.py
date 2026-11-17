"""Regression tests for the cooldowns_rewards swarm: half-strength sustained enemy attack
cooldowns (enemy_ai-4) and boss-reward perk filtering with run-scaled Ultra charges (progression-3)."""

import importlib.util
import os
import random
from types import SimpleNamespace

import config
import rpg
from enemy import Enemy
from enemy_behaviors.base import sustained_cd_scale
from enemy_behaviors.bomber import Bomber
from enemy_behaviors.engineer import Engineer
from enemy_behaviors.ranged import Ranged
from enemy_behaviors.spitter import Spitter
from enemy_behaviors.tank import Tank
from game import Game
from player import Player
from powerup import PowerUp, apply_powerup
from states import GameStateName
from utils import Vec2

EPS = 1e-9
BANNED_AT_CAP = {"perm_shield", "perm_ultra", "perm_double_dash", "perm_dash"}


def _enemy(behavior, pos=Vec2(0.0, 0.0), attack_mult=None):
    e = Enemy(pos=pos, hp=40, speed=80.0, behavior=behavior, max_hp=40)
    if attack_mult is not None:
        e.ai["attack_mult"] = float(attack_mult)
    return e


def _state(enemies):
    return SimpleNamespace(enemies=enemies, projectiles=[], obstacles=[], traps=[], wave=1)


def _in_range(value, lo, hi):
    return lo - EPS <= value <= hi + EPS


def _load_web_module(name, rel_path):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), rel_path)
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# enemy_ai-4: spawn attack multiplier at half strength for sustained cooldowns
# ---------------------------------------------------------------------------


def test_sustained_cd_scale_is_half_strength_and_clamped():
    assert abs(sustained_cd_scale(_enemy("spitter")) - 1.0) < EPS, "no multiplier means no change"
    assert abs(sustained_cd_scale(_enemy("spitter", attack_mult=1.5)) - 1.25) < EPS
    assert abs(sustained_cd_scale(_enemy("tank", attack_mult=0.9)) - 0.95) < EPS
    assert abs(sustained_cd_scale(_enemy("x", attack_mult=5.0)) - 1.3) < EPS, "high side clamps at 1.6"
    assert abs(sustained_cd_scale(_enemy("x", attack_mult=0.1)) - 0.8) < EPS, "low side clamps at 0.6"
    print("[PASS] test_sustained_cd_scale_is_half_strength_and_clamped passed (1.25 spitter, 0.95 tank, clamped)")


def test_spitter_sustained_volley_uses_half_strength():
    random.seed(3)
    lo, hi = 1.4 / 1.25, 1.7 / 1.25
    for _ in range(40):
        e = _enemy("spitter", pos=Vec2(160.0, 0.0), attack_mult=1.5)
        e.attack_cd = 0.0
        e.ai["volley_mode"] = 0
        e.ai["strafe_sign"] = 1.0
        s = _state([e])
        Spitter().update(e, Vec2(0.0, 0.0), s, 0.01, Vec2(0.0, 0.0))
        assert len(s.projectiles) == 3, "volley mode 0 fires three spread shots"
        assert _in_range(e.attack_cd, lo, hi), f"spitter reset {e.attack_cd} outside [{lo}, {hi}]"
    print("[PASS] test_spitter_sustained_volley_uses_half_strength passed (reset 1.12-1.36 s vs 1.4-1.7 s base)")


def test_tank_sustained_reload_lengthens_with_low_multiplier():
    random.seed(5)
    e = _enemy("tank", pos=Vec2(120.0, 0.0), attack_mult=0.9)
    e.attack_cd = 0.0
    e.ai["brace_t"] = 5.0
    e.ai["push_t"] = 0.0
    s = _state([e])
    Tank().update(e, Vec2(0.0, 0.0), s, 0.01, Vec2(0.0, 0.0))
    assert len(s.projectiles) == 1, "tank fires one shot"
    assert _in_range(e.attack_cd, 1.9 / 0.95, 2.2 / 0.95), f"tank reload {e.attack_cd} not lengthened"
    print("[PASS] test_tank_sustained_reload_lengthens_with_low_multiplier passed (reload 2.0-2.32 s)")


def test_ranged_burst_reload_uses_half_strength():
    random.seed(9)
    e = _enemy("ranged", pos=Vec2(260.0, 0.0), attack_mult=1.2)
    e.attack_cd = 0.0
    e.ai.update({"burst_left": 1, "burst_gap": 0.0, "relocate_t": 0.0, "strafe_sign": 1.0})
    s = _state([e])
    Ranged().update(e, Vec2(0.0, 0.0), s, 0.01, Vec2(0.0, 0.0))
    assert len(s.projectiles) == 1, "ranged fires the last shot of its burst"
    assert _in_range(e.attack_cd, 1.65 / 1.1, 2.0 / 1.1), f"ranged burst reset {e.attack_cd} unexpected"
    print("[PASS] test_ranged_burst_reload_uses_half_strength passed (reset 1.50-1.82 s vs 1.65-2.00 s base)")


def test_engineer_trap_cooldown_uses_half_strength():
    random.seed(13)
    e = _enemy("engineer", pos=Vec2(200.0, 0.0), attack_mult=1.1)
    e.attack_cd = 0.0
    s = _state([e])
    Engineer().update(e, Vec2(0.0, 0.0), s, 0.01, Vec2(0.0, 0.0))
    assert len(s.traps) == 1, "engineer lays one trap"
    assert _in_range(e.attack_cd, 2.9 / 1.05, 3.5 / 1.05), f"engineer reset {e.attack_cd} unexpected"

    base = _enemy("engineer")
    base.attack_cd = 0.0
    Engineer().update(base, Vec2(0.0, 0.0), _state([base]), 0.01, Vec2(0.0, 0.0))
    assert _in_range(base.attack_cd, 2.9, 3.5), "engineer without multiplier keeps the base reset"
    print("[PASS] test_engineer_trap_cooldown_uses_half_strength passed (reset 2.76-3.33 s vs 2.90-3.50 s base)")


def test_bomber_cooldown_uses_half_strength():
    random.seed(17)
    e = _enemy("bomber", pos=Vec2(200.0, 0.0), attack_mult=1.4)
    e.attack_cd = 0.0
    s = _state([e])
    Bomber().update(e, Vec2(0.0, 0.0), s, 0.01, Vec2(0.0, 0.0))
    assert len(s.projectiles) == 1, "bomber throws one bomb"
    assert _in_range(e.attack_cd, 2.2 / 1.2, 2.7 / 1.2), f"bomber reset {e.attack_cd} unexpected"
    print("[PASS] test_bomber_cooldown_uses_half_strength passed (reset 1.83-2.25 s)")


# ---------------------------------------------------------------------------
# progression-3: boss-reward no-op filter and run-scaled Ultra charges
# ---------------------------------------------------------------------------


def test_ultra_capacity_defaults_and_hard_cap_constant():
    assert config.ULTRA_MAX_CHARGES == 2
    assert config.ULTRA_MAX_CHARGES_HARD_CAP == 4
    assert Player(pos=Vec2(0.0, 0.0)).ultra_max_charges == 2
    print("[PASS] test_ultra_capacity_defaults_and_hard_cap_constant passed (base 2, hard cap 4)")


def test_perm_ultra_raises_capacity_and_stops_at_cap():
    p = Player(pos=Vec2(0.0, 0.0))
    perms = []
    seen = []
    for _ in range(4):
        _, applied = rpg.apply_perm_reward(p, perms, "perm_ultra", 1.0)
        assert applied, "perm_ultra is a known key"
        seen.append((p.ultra_max_charges, p.ultra_charges))
    assert seen == [(3, 1), (4, 2), (4, 3), (4, 4)], f"unexpected capacity/charge trail {seen}"
    assert perms == ["perm_ultra"], "the run records the perk once"
    print("[PASS] test_perm_ultra_raises_capacity_and_stops_at_cap passed (2 -> 3 -> 4, never past the cap)")


def test_ultra_pickup_respects_run_capacity():
    p = Player(pos=Vec2(0.0, 0.0))
    pickup = PowerUp(pos=Vec2(0.0, 0.0), kind="ultra")
    trail = []
    for _ in range(3):
        apply_powerup(p, pickup, 0.0)
        trail.append(p.ultra_charges)
    assert trail == [1, 2, 2], f"default capacity 2 must cap pickups, got {trail}"

    p.ultra_max_charges = 4
    trail = []
    for _ in range(3):
        apply_powerup(p, pickup, 0.0)
        trail.append(p.ultra_charges)
    assert trail == [3, 4, 4], f"raised capacity must let pickups add charges, got {trail}"
    print("[PASS] test_ultra_pickup_respects_run_capacity passed (pickups cap at the player's capacity)")


def test_boss_roll_drops_noop_perks_for_capped_player():
    p = Player(pos=Vec2(0.0, 0.0))
    p.shield = 120
    p.ultra_max_charges = 4
    p.dash_max_charges = 2
    random.seed(21)
    for _ in range(300):
        _, perm_opts = rpg.roll_boss_rewards([], "", "", player=p, dash_cd_mult=0.6)
        keys = [o["key"] for o in perm_opts]
        assert len(keys) == 3 and len(set(keys)) == 3, f"expected three distinct cards, got {keys}"
        assert not BANNED_AT_CAP.intersection(keys), f"no-op perk offered: {keys}"
    print("[PASS] test_boss_roll_drops_noop_perks_for_capped_player passed (shield/ultra/dash/double dash filtered)")


def test_boss_roll_keeps_perks_that_still_help():
    p = Player(pos=Vec2(0.0, 0.0))
    random.seed(22)
    seen = set()
    for _ in range(300):
        _, perm_opts = rpg.roll_boss_rewards([], "", "", player=p, dash_cd_mult=1.0)
        seen.update(o["key"] for o in perm_opts)
    assert BANNED_AT_CAP <= seen, f"fresh player should still be offered every useful perk, saw {sorted(seen)}"
    print("[PASS] test_boss_roll_keeps_perks_that_still_help passed (fresh player sees all four)")


def test_boss_roll_excludes_last_perk():
    p = Player(pos=Vec2(0.0, 0.0))
    random.seed(23)
    for _ in range(200):
        _, perm_opts = rpg.roll_boss_rewards([], "", "perm_crit", player=p, dash_cd_mult=1.0)
        assert "perm_crit" not in [o["key"] for o in perm_opts], "last perk must not repeat"
    print("[PASS] test_boss_roll_excludes_last_perk passed (last picked perk never re-offered)")


def test_boss_roll_shows_fewer_cards_instead_of_refilling():
    p = Player(pos=Vec2(0.0, 0.0))
    p.shield = 120
    original = rpg.PERM_REWARD_POOL
    try:
        rpg.PERM_REWARD_POOL = [
            {"key": "perm_shield", "title": "Shield Layer", "desc": "+18 shield now"},
            {"key": "perm_damage", "title": "Core Damage", "desc": "+1 damage this run"},
            {"key": "perm_speed", "title": "Servo Boost", "desc": "+6 move speed this run"},
        ]
        _, perm_opts = rpg.roll_boss_rewards([], "", "perm_speed", player=p, dash_cd_mult=1.0)
        keys = [o["key"] for o in perm_opts]
        assert keys == ["perm_damage"], f"expected only the valid card, got {keys}"
    finally:
        rpg.PERM_REWARD_POOL = original
    print("[PASS] test_boss_roll_shows_fewer_cards_instead_of_refilling passed (1 card, no refill)")


def test_boss_roll_without_player_only_applies_dash_floor():
    random.seed(24)
    seen = set()
    for _ in range(200):
        _, perm_opts = rpg.roll_boss_rewards([], "", "")
        seen.update(o["key"] for o in perm_opts)
    assert {"perm_shield", "perm_ultra", "perm_dash"} <= seen, "without a player only the dash floor is known"

    random.seed(25)
    for _ in range(200):
        _, perm_opts = rpg.roll_boss_rewards([], "", "", dash_cd_mult=0.6)
        assert "perm_dash" not in [o["key"] for o in perm_opts], "dash at its floor is a no-op"
    print("[PASS] test_boss_roll_without_player_only_applies_dash_floor passed (dash floor checked without a player)")


def test_web_reward_helpers_mirror_desktop():
    web_rpg = _load_web_module("web_rpg_swarm_check", os.path.join("vercel_site", "py", "rpg.py"))
    web_powerup = _load_web_module("web_powerup_swarm_check", os.path.join("vercel_site", "py", "powerup.py"))

    p = Player(pos=Vec2(0.0, 0.0))
    perms = []
    for _ in range(4):
        web_rpg.apply_perm_reward(p, perms, "perm_ultra", 1.0)
    assert p.ultra_max_charges == 4, f"web perm_ultra must stop at the cap, got {p.ultra_max_charges}"

    p.shield = 120
    p.dash_max_charges = 2
    random.seed(26)
    for _ in range(200):
        _, perm_opts = web_rpg.roll_boss_rewards([], "", "", player=p, dash_cd_mult=0.6)
        assert not BANNED_AT_CAP.intersection(o["key"] for o in perm_opts), "web roll offered a no-op perk"

    p2 = Player(pos=Vec2(0.0, 0.0))
    p2.ultra_max_charges = 4
    p2.ultra_charges = 2
    web_powerup.apply_powerup(p2, PowerUp(pos=Vec2(0.0, 0.0), kind="ultra"), 0.0)
    web_powerup.apply_powerup(p2, PowerUp(pos=Vec2(0.0, 0.0), kind="ultra"), 0.0)
    assert p2.ultra_charges == 4, f"web ultra pickup must respect run capacity, got {p2.ultra_charges}"
    print("[PASS] test_web_reward_helpers_mirror_desktop passed (web rpg roll filter, ultra cap and pickup)")


def test_game_boss_offers_hide_capped_perks(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.player.shield = 120
    g.player.ultra_max_charges = 4
    g.player.dash_max_charges = 2
    g._dash_cd_mult = 0.6
    random.seed(31)
    for _ in range(40):
        g._roll_boss_rewards()
        keys = [o.get("key", "") for o in g.rpg_menu._perm_opts]
        assert not BANNED_AT_CAP.intersection(keys), f"game offered a no-op perk: {keys}"
    print("[PASS] test_game_boss_offers_hide_capped_perks passed (Game passes player and dash state into the roll)")


def test_game_ultra_rewards_scale_with_run_capacity(g):
    g._init_game()
    p = g.player
    p.ultra_charges = 0
    for _ in range(3):
        g._apply_perm_reward("perm_ultra")
    assert p.ultra_max_charges == 4 and p.ultra_charges == 3, (
        f"expected capacity 4 and 3 charges, got {p.ultra_max_charges} and {p.ultra_charges}"
    )
    assert g._last_reward_perm_key == "perm_ultra", "perm pick is remembered for the next roll"
    assert "perm_ultra" in g._run_permanent_rewards, "perm pick is recorded for the run"

    p.ultra_charges = 3
    g._apply_temp_reward("temp_ultra_flux", 3)
    assert p.ultra_charges == 4, f"temp Ultra Flux must fill to the raised capacity, got {p.ultra_charges}"
    g._apply_temp_reward("temp_ultra_flux", 3)
    assert p.ultra_charges == 4, "temp Ultra Flux must not exceed the raised capacity"

    g._init_game()
    p = g.player
    p.ultra_charges = 2
    g._apply_temp_reward("temp_ultra_flux", 3)
    assert p.ultra_charges == 2, "base capacity of 2 still applies to a fresh run"
    print("[PASS] test_game_ultra_rewards_scale_with_run_capacity passed (perm and temp flux respect run capacity)")


def run_all():
    # Pure-logic checks first, then the Game-backed checks that need a window.
    test_sustained_cd_scale_is_half_strength_and_clamped()
    test_spitter_sustained_volley_uses_half_strength()
    test_tank_sustained_reload_lengthens_with_low_multiplier()
    test_ranged_burst_reload_uses_half_strength()
    test_engineer_trap_cooldown_uses_half_strength()
    test_bomber_cooldown_uses_half_strength()
    test_ultra_capacity_defaults_and_hard_cap_constant()
    test_perm_ultra_raises_capacity_and_stops_at_cap()
    test_ultra_pickup_respects_run_capacity()
    test_boss_roll_drops_noop_perks_for_capped_player()
    test_boss_roll_keeps_perks_that_still_help()
    test_boss_roll_excludes_last_perk()
    test_boss_roll_shows_fewer_cards_instead_of_refilling()
    test_boss_roll_without_player_only_applies_dash_floor()
    test_web_reward_helpers_mirror_desktop()

    g = Game()
    g.set_visible(False)
    try:
        test_game_boss_offers_hide_capped_perks(g)
        test_game_ultra_rewards_scale_with_run_capacity(g)
    finally:
        g.close()
    print("\nALL COOLDOWNS/REWARDS SWARM REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
