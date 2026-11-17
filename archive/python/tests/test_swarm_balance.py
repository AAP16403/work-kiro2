"""Regression tests for the swarm/balance pass: wave-size ramp, damage scaling and upgrade-only weapons.

Pure logic tests run without a window; the Game-backed tests share one hidden window in run_all().
"""

import importlib.util
import os
import random
import sys

import config
from config import PLAYER_DAMAGE
from game import Game
from level import GameState, get_difficulty_mods, spawn_loot_on_enemy_death, spawn_wave
from logic import EnemySpawnLogic, EnemyTuningLogic
from player import Player
from powerup import PowerUp, apply_powerup
from projectile import spawn_projectiles
from states import GameStateName
from utils import Vec2
from weapons import (
    WEAPONS,
    get_weapon_key_for_wave,
    is_weapon_upgrade,
    roll_wave_clear_upgrade,
)


class _NoCritRng:
    """Stand-in RNG that never crits and never jitters, so shot damage is exact."""

    def random(self):
        return 1.0

    def uniform(self, a, b):
        return (a + b) / 2.0


class _Stub:
    """Bare object for calling Game methods that only read attributes."""


def _shot_damage(weapon_key, base_damage):
    projs = spawn_projectiles(Vec2(0.0, 0.0), Vec2(1.0, 0.0), WEAPONS[weapon_key], 0.0, base_damage, rng=_NoCritRng())
    return projs[0].damage


def _load_vercel_module(name):
    here = os.path.dirname(os.path.abspath(__file__))
    path = os.path.join(here, "vercel_site", "py", name + ".py")
    mod_name = "vercel_" + name
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    # Register before executing so dataclass decorators can resolve the module.
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _new_run(g, seed):
    g._init_game()
    g.state.init_rng(seed)
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Call update() directly: pyglet.clock.tick() would also fire the game's scheduled
    # update with real elapsed time and double-step the simulation.
    for _ in range(frames):
        g.dispatch_events()
        g.update(1.0 / 60.0)


def _clear_wave(g):
    s = g.state
    s.wave_active = True
    s.enemies = []
    _tick(g)


# ---------------------------------------------------------------------------
# balance-1: player damage scales the whole shot
# ---------------------------------------------------------------------------

def test_full_shot_damage_matches_tuning_point():
    assert _shot_damage("basic", 10) == 15, "basic at base 10 must stay 15"
    assert _shot_damage("heavy", 10) == 25, "heavy at base 10 must stay 25"
    assert _shot_damage("railgun", 10) == 45, "railgun at base 10 must stay 45"
    print("[PASS] test_full_shot_damage_matches_tuning_point passed (base 10 reproduces the old numbers)")


def test_damage_upgrades_scale_the_whole_shot():
    assert _shot_damage("basic", 11) == 17, "16.5 must round half-up to 17"
    assert _shot_damage("heavy", 11) == 28, "27.5 must round half-up to 28"
    assert _shot_damage("railgun", 11) == 50, "49.5 must round half-up to 50"
    assert _shot_damage("basic", 15) == 23, "22.5 must round half-up to 23, not banker's 22"
    print("[PASS] test_damage_upgrades_scale_the_whole_shot passed (first Core Damage pick now changes shots)")


def test_shot_damage_is_monotonic_in_player_damage():
    for key in ("basic", "spread", "rapid", "heavy", "plasma", "railgun", "flak"):
        vals = [_shot_damage(key, base) for base in range(10, 31)]
        assert vals == sorted(vals), f"{key} damage must not fall as base damage rises: {vals}"
        assert vals[-1] > vals[0], f"{key} damage must grow across base damage 10-30"
    print("[PASS] test_shot_damage_is_monotonic_in_player_damage passed (every weapon grows with base damage)")


def test_effective_player_damage_rounds_half_up():
    stub = _Stub()
    stub.player = Player(pos=Vec2(0.0, 0.0))
    stub._temp_damage_mult = 1.25
    assert Game._effective_player_damage(stub) == 13, "10 * 1.25 = 12.5 must round up to 13 (round() gives 12)"
    stub._temp_damage_mult = 1.28
    assert Game._effective_player_damage(stub) == 13, "Overdrive 10 * 1.28 = 12.8 must round to 13"
    stub._temp_damage_mult = 1.0
    assert Game._effective_player_damage(stub) == PLAYER_DAMAGE
    stub.player.damage = 0
    assert Game._effective_player_damage(stub) == 1, "effective damage keeps its floor of 1"
    print("[PASS] test_effective_player_damage_rounds_half_up passed (Overdrive is not truncated)")


def test_damage_pickup_adds_one_base_point():
    p = Player(pos=Vec2(0.0, 0.0))
    base = p.damage
    for _ in range(3):
        apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="damage"), 0.0)
    assert p.damage == base + 3, f"three damage pickups must add exactly 3 base damage, got {p.damage - base}"
    print("[PASS] test_damage_pickup_adds_one_base_point passed (pickup is +1 base, not +4)")


# ---------------------------------------------------------------------------
# balance-2: wave-size ramp and difficulty caps in logic.py
# ---------------------------------------------------------------------------

def test_wave_cap_ramps_after_wave_five():
    logic = EnemySpawnLogic()
    expected = {1: 12, 5: 12, 6: 12, 7: 12, 8: 13, 10: 13, 11: 14, 13: 14, 14: 15, 20: 17, 29: 20, 40: 20}
    for wave, cap in expected.items():
        got = logic.wave_cap(wave, 12)
        assert got == cap, f"wave {wave}: expected cap {cap}, got {got}"
    print("[PASS] test_wave_cap_ramps_after_wave_five passed (+1 per 3 waves after wave 5, max +8)")


def test_plan_total_follows_ramped_cap():
    logic = EnemySpawnLogic()
    for wave, expected in ((6, 12), (8, 13), (21, 17), (29, 20)):
        plan = logic.plan_wave(wave, "normal", logic.wave_cap(wave, 12))
        assert plan.total_count == expected, f"wave {wave}: plan total {plan.total_count}, expected {expected}"
        assert sum(plan.behavior_counts.values()) == expected, f"wave {wave}: behavior counts do not sum to the plan total"
    print("[PASS] test_plan_total_follows_ramped_cap passed (large waves no longer clamp at 12)")


def test_spawn_wave_adds_ramped_head_count():
    for wave, expected in ((6, 12), (8, 13), (21, 17), (29, 20)):
        state = GameState(wave=wave, difficulty="normal", max_enemies=12)
        state.init_rng(wave)
        spawn_wave(state, Vec2(0.0, 0.0))
        assert len(state.enemies) == expected, f"wave {wave}: spawned {len(state.enemies)}, expected {expected}"
        assert state.max_enemies == 12, "boss adds read the base cap, so state.max_enemies must not ramp"
    print("[PASS] test_spawn_wave_adds_ramped_head_count passed (spawn_wave uses the ramp, boss cap stays on base)")


def test_difficulty_caps_live_in_logic_table():
    assert int(get_difficulty_mods("easy")["max_enemies"]) == 10
    assert int(get_difficulty_mods("normal")["max_enemies"]) == 12
    assert int(get_difficulty_mods("hard")["max_enemies"]) == 14
    assert int(get_difficulty_mods("unknown")["max_enemies"]) == 12, "unknown difficulty falls back to normal"
    assert not hasattr(config, "MAX_ENEMIES"), "the unused config.MAX_ENEMIES must be gone"
    print("[PASS] test_difficulty_caps_live_in_logic_table passed (caps read through the mods lookup)")


def test_spawn_multiplier_reads_shared_tuning_table():
    tuning = EnemyTuningLogic()
    tuning.difficulty_modifiers["normal"]["spawn"] = 0.5
    assert EnemySpawnLogic(tuning)._base_count(10, "normal", 99) == int((4 + 14) * 0.5), "spawn key must drive the base count"
    assert EnemySpawnLogic()._base_count(10, "easy", 99) == int(18 * 0.85)
    assert EnemySpawnLogic()._base_count(10, "hard", 99) == int(18 * 1.12)
    print("[PASS] test_spawn_multiplier_reads_shared_tuning_table passed (one table drives spawn scaling)")


def test_wave_cap_applies_to_easy_and_hard_bases():
    assert EnemySpawnLogic().wave_cap(8, 10) == 11, "easy base 10 plus wave-8 ramp"
    assert EnemySpawnLogic().wave_cap(8, 14) == 15, "hard base 14 plus wave-8 ramp"
    print("[PASS] test_wave_cap_applies_to_easy_and_hard_bases passed (ramp is additive to every difficulty)")


# ---------------------------------------------------------------------------
# progression-1: upgrade-only weapons with a seeded roll
# ---------------------------------------------------------------------------

def test_weapon_ranks_follow_expected_dps():
    dps = {}
    for key, w in WEAPONS.items():
        raw = w.damage + 0.5 * PLAYER_DAMAGE
        dps[key] = raw * w.projectile_count * (1.0 + w.crit_chance * (w.crit_mult - 1.0)) / w.fire_rate
    by_dps = sorted(WEAPONS, key=lambda k: dps[k])
    ranks = [WEAPONS[k].rank for k in by_dps]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks), f"ranks must follow expected DPS order: {ranks}"
    assert WEAPONS["basic"].rank == 1, "the starting weapon sits at the bottom of the ladder"
    assert WEAPONS["flak"].rank == max(w.rank for w in WEAPONS.values()), "flak is the top rank"
    print("[PASS] test_weapon_ranks_follow_expected_dps passed (ranks match post-bonus expected DPS)")


def test_is_weapon_upgrade_is_strict():
    basic, spread, plasma = WEAPONS["basic"], WEAPONS["spread"], WEAPONS["plasma"]
    assert is_weapon_upgrade(None, basic), "any weapon beats having none"
    assert not is_weapon_upgrade(basic, None), "no candidate is never an upgrade"
    assert is_weapon_upgrade(basic, spread)
    assert not is_weapon_upgrade(plasma, spread), "a lower rank is not an upgrade"
    assert not is_weapon_upgrade(plasma, plasma), "equal rank is not an upgrade"
    print("[PASS] test_is_weapon_upgrade_is_strict passed (only strictly higher ranks upgrade)")


def test_weapon_pickup_only_upgrades():
    p = Player(pos=Vec2(0.0, 0.0))
    p.current_weapon = WEAPONS["plasma"]
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="weapon", data="basic"), 0.0)
    assert p.current_weapon is WEAPONS["plasma"], "a downgrade pickup must not equip"
    assert p.shield == 20, "a non-upgrade weapon pickup pays off as a +20 shield top-up"
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="weapon", data="flak"), 0.0)
    assert p.current_weapon is WEAPONS["flak"], "an upgrade pickup must equip"
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="weapon", data="spread"), 0.0)
    assert p.current_weapon is WEAPONS["flak"] and p.shield == 40, "flak is never replaced by a pickup"

    q = Player(pos=Vec2(0.0, 0.0))
    q.current_weapon = None
    apply_powerup(q, PowerUp(pos=Vec2(0.0, 0.0), kind="weapon", data="heavy"), 0.0)
    assert q.current_weapon is WEAPONS["heavy"], "with no weapon equipped, any pickup equips"
    apply_powerup(q, PowerUp(pos=Vec2(0.0, 0.0), kind="weapon", data="no_such_gun"), 0.0)
    assert q.current_weapon is WEAPONS["heavy"] and q.shield == 20, "unknown keys become shield top-ups"
    print("[PASS] test_weapon_pickup_only_upgrades passed (downgrades pay off as shield, flak holds)")


def test_wave_clear_roll_only_equips_upgrades():
    seeds = range(60)
    for seed in seeds:
        assert roll_wave_clear_upgrade(WEAPONS["flak"], 7, random.Random(seed), chance=1.0) is None, "nothing outranks flak"
        assert roll_wave_clear_upgrade(WEAPONS["basic"], 7, random.Random(seed), chance=0.0) is None, "chance 0 never rolls"
        assert roll_wave_clear_upgrade(None, 7, random.Random(seed), chance=1.0) is not None, "no weapon means any roll equips"
    equips = [roll_wave_clear_upgrade(WEAPONS["basic"], 7, random.Random(seed), chance=1.0) for seed in seeds]
    got = [w for w in equips if w is not None]
    assert got, "some rolls from basic must equip an upgrade"
    assert all(w.rank > WEAPONS["basic"].rank for w in got), "every equipped weapon must outrank basic"
    print("[PASS] test_wave_clear_roll_only_equips_upgrades passed (rolls never downgrade)")


def test_weapon_rolls_use_the_passed_rng_only():
    before = random.getstate()
    rng = random.Random(3)
    for wave in range(1, 12):
        get_weapon_key_for_wave(wave, rng=rng)
        roll_wave_clear_upgrade(WEAPONS["basic"], wave, rng, chance=0.5)
    assert random.getstate() == before, "seeded weapon picks must not consume the global random module"

    def run(seed):
        r = random.Random(seed)
        names = []
        for wave in range(6, 20):
            up = roll_wave_clear_upgrade(WEAPONS["basic"], wave, r, chance=0.5)
            names.append("none" if up is None else up.name)
        return names

    assert run(11) == run(11), "the same seed must give the same wave-clear weapon sequence"
    print("[PASS] test_weapon_rolls_use_the_passed_rng_only passed (weapon picks are reproducible)")


def test_boss_weapon_drop_outranks_current_weapon():
    for seed in range(40):
        st = GameState(wave=5, difficulty="normal")
        st.init_rng(seed)
        spawn_loot_on_enemy_death(st, "boss_brute", Vec2(0.0, 0.0), current_weapon=WEAPONS["spread"])
        drops = [p.data for p in st.powerups if p.kind == "weapon"]
        assert len(drops) == 1, f"seed {seed}: a boss must drop exactly one weapon, got {drops}"
        assert WEAPONS[drops[0]].rank > WEAPONS["spread"].rank, f"seed {seed}: boss drop {drops[0]} is not an upgrade"

    st = GameState(wave=5, difficulty="normal")
    st.init_rng(1)
    spawn_loot_on_enemy_death(st, "boss_brute", Vec2(0.0, 0.0), current_weapon=WEAPONS["flak"])
    drops = [p.data for p in st.powerups if p.kind == "weapon"]
    # Flak is not in the wave 5-6 pool, so with flak held the best pool weapon at wave 5 is plasma.
    assert drops == ["plasma"], f"with the top of the pool held, the drop is the best pool weapon, got {drops}"
    hero = Player(pos=Vec2(0.0, 0.0))
    hero.current_weapon = WEAPONS["flak"]
    apply_powerup(hero, PowerUp(pos=Vec2(0.0, 0.0), kind="weapon", data=drops[0]), 0.0)
    assert hero.current_weapon is WEAPONS["flak"] and hero.shield == 20, "that drop pays off as a shield top-up"
    assert WEAPONS["plasma"].rank < WEAPONS["flak"].rank, "plasma must be a downgrade against held flak"
    print("[PASS] test_boss_weapon_drop_outranks_current_weapon passed (boss drops are upgrades)")


def test_loot_weapon_rolls_stay_on_run_rng():
    st = GameState(wave=6, difficulty="normal")
    st.init_rng(9)
    before = random.getstate()
    for _ in range(300):
        spawn_loot_on_enemy_death(st, "chase", Vec2(0.0, 0.0))
    assert random.getstate() == before, "loot rolls must draw from the run RNG, not the global random module"
    assert any(p.kind == "weapon" for p in st.powerups), "300 kills at wave 6 should drop at least one weapon"
    print("[PASS] test_loot_weapon_rolls_stay_on_run_rng passed (kill drops are seeded)")


def test_vercel_mirrors_match_desktop_balance():
    vw = _load_vercel_module("weapons")
    assert {k: w.rank for k, w in vw.WEAPONS.items()} == {k: w.rank for k, w in WEAPONS.items()}, "vercel weapon ranks drifted"

    vl = _load_vercel_module("logic")
    assert vl.EnemySpawnLogic().wave_cap(21, 12) == 17, "vercel wave ramp drifted"
    assert int(vl.EnemyTuningLogic().difficulty_mods("easy")["max_enemies"]) == 10
    assert int(vl.EnemyTuningLogic().difficulty_mods("hard")["max_enemies"]) == 14

    vp = _load_vercel_module("projectile")
    projs = vp.spawn_projectiles(Vec2(0.0, 0.0), Vec2(1.0, 0.0), vw.WEAPONS["basic"], 0.0, 11, rng=_NoCritRng())
    assert projs[0].damage == 17, "vercel shot scaling drifted"

    vpow = _load_vercel_module("powerup")
    p = Player(pos=Vec2(0.0, 0.0))
    vpow.apply_powerup(p, vpow.PowerUp(pos=Vec2(0.0, 0.0), kind="damage"), 0.0)
    assert p.damage == PLAYER_DAMAGE + 1, "vercel damage pickup must be +1 base"

    vcfg = _load_vercel_module("config")
    assert vcfg.WEAPON_WAVE_UPGRADE_CHANCE == 0.5

    here = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(here, "vercel_site", "py", "browser_game.py"), encoding="utf-8") as fh:
        src = fh.read()
    assert "self.player.current_weapon = get_weapon_for_wave(s.wave)" not in src, "vercel wave clear still resets the weapon"
    assert "roll_wave_clear_upgrade(" in src, "vercel wave clear must use the upgrade-only roll"
    print("[PASS] test_vercel_mirrors_match_desktop_balance passed (Vercel copies carry the same balance)")


# ---------------------------------------------------------------------------
# Game-backed tests (need the hidden window)
# ---------------------------------------------------------------------------

def test_run_start_applies_difficulty_cap(g):
    for difficulty, cap, incoming in (("easy", 10, 0.85), ("normal", 12, 1.0), ("hard", 14, 1.15)):
        g.settings["difficulty"] = difficulty
        g._init_game()
        assert g.state.max_enemies == cap, f"{difficulty}: base cap {g.state.max_enemies}, expected {cap}"
        assert abs(g._incoming_damage_mult - incoming) < 1e-9, f"{difficulty}: incoming damage mult drifted"
    g.settings["difficulty"] = "normal"
    print("[PASS] test_run_start_applies_difficulty_cap passed (run start reads the logic.py cap table)")


def test_wave_clears_never_downgrade_weapon(g):
    for seed in range(1, 7):
        s = _new_run(g, seed)
        g.player.current_weapon = WEAPONS["heavy"]
        ranks = [g.player.current_weapon.rank]
        for wave in (6, 7, 8):
            s.wave = wave
            _clear_wave(g)
            ranks.append(g.player.current_weapon.rank)
        assert ranks == sorted(ranks), f"seed {seed}: weapon rank fell across wave clears: {ranks}"
    print("[PASS] test_wave_clears_never_downgrade_weapon passed (rank never falls at a wave clear)")


def test_flak_is_kept_through_wave_clears(g):
    s = _new_run(g, 4)
    g.player.current_weapon = WEAPONS["flak"]
    for wave in (6, 7, 8):
        s.wave = wave
        _clear_wave(g)
    assert g.player.current_weapon is WEAPONS["flak"], "flak must never be replaced by a wave-clear roll"
    print("[PASS] test_flak_is_kept_through_wave_clears passed (top rank holds)")


def test_wave_clear_weapon_is_seeded(g):
    outcomes = []
    for _ in range(2):
        s = _new_run(g, 21)
        g.player.current_weapon = WEAPONS["basic"]
        names = []
        for wave in (6, 7, 8):
            s.wave = wave
            _clear_wave(g)
            names.append(g.player.current_weapon.name)
        outcomes.append(names)
    assert outcomes[0] == outcomes[1], f"same seed gave different weapons: {outcomes}"
    print("[PASS] test_wave_clear_weapon_is_seeded passed (same seed, same weapon sequence)")


def run_all():
    pure_tests = (
        test_full_shot_damage_matches_tuning_point,
        test_damage_upgrades_scale_the_whole_shot,
        test_shot_damage_is_monotonic_in_player_damage,
        test_effective_player_damage_rounds_half_up,
        test_damage_pickup_adds_one_base_point,
        test_wave_cap_ramps_after_wave_five,
        test_plan_total_follows_ramped_cap,
        test_spawn_wave_adds_ramped_head_count,
        test_difficulty_caps_live_in_logic_table,
        test_spawn_multiplier_reads_shared_tuning_table,
        test_wave_cap_applies_to_easy_and_hard_bases,
        test_weapon_ranks_follow_expected_dps,
        test_is_weapon_upgrade_is_strict,
        test_weapon_pickup_only_upgrades,
        test_wave_clear_roll_only_equips_upgrades,
        test_weapon_rolls_use_the_passed_rng_only,
        test_boss_weapon_drop_outranks_current_weapon,
        test_loot_weapon_rolls_stay_on_run_rng,
        test_vercel_mirrors_match_desktop_balance,
    )
    for test in pure_tests:
        test()

    g = Game()
    g.set_visible(False)
    try:
        test_run_start_applies_difficulty_cap(g)
        test_wave_clears_never_downgrade_weapon(g)
        test_flak_is_kept_through_wave_clears(g)
        test_wave_clear_weapon_is_seeded(g)
    finally:
        g.close()
    print("\nALL SWARM BALANCE REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
