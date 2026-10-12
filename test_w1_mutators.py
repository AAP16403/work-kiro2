"""Regression tests for opt-in run mutators: apply functions, combined score multiplier, saved selection,
the run hooks (movement, enemy volleys, spawns, pickups, shield recharge, score), the title chips and the
Game Over line. Deterministic: no wall-clock timing, temp files only, the real user_settings.json and
high_scores.json are never touched."""

import json
import math
import os
import random
import shutil
import tempfile

import pyglet

import audio
import config
import level
import mutators
import score as score_mod
import states
from enemy import Enemy
from game import Game
from level import GameState, maybe_spawn_powerup, spawn_loot_on_enemy_death
from logic import EnemySpawnLogic, EnemyTuningLogic
from mutators import RunRules, MUTATORS
from player import Player
from projectile import Projectile
from score import ScoreTracker
from states import GameOverState, GameStateName, PlayingState
from utils import Vec2

_TMP = tempfile.mkdtemp(prefix="plouto_w1_mutators_")
DT = 1.0 / 60.0


def _tmp_path(name="user_settings.json"):
    return os.path.join(_TMP, f"{name}_{random.randrange(1 << 30)}.json")


def _enemy_bullet(x, y, vx, vy, ptype="bullet"):
    return Projectile(Vec2(x, y), Vec2(vx, vy), 8, ttl=2.0, owner="enemy", projectile_type=ptype)


def _angles(projs):
    return sorted(math.atan2(p.vel.y, p.vel.x) for p in projs)


# ---------------------------------------------------------------------------
# Mutator records and apply functions
# ---------------------------------------------------------------------------

def test_registry_has_five_described_mutators():
    ids = [m.id for m in MUTATORS]
    assert ids == ["glass_cannon", "bullet_hell", "drift", "frenzy", "iron_man"], ids
    for m in MUTATORS:
        assert m.name and m.description, f"{m.id} needs a name and a description"
        assert m.score_mult > 1.0, f"{m.id} must give a score bonus for risk"
        assert m.apply(RunRules()) != RunRules(), f"{m.id} must change the run rules"
    print("[PASS] test_registry_has_five_described_mutators passed (5 mutators, each with name, description and bonus)")


def test_glass_cannon_apply():
    r = mutators.mutator_by_id("glass_cannon").apply(RunRules())
    assert abs(r.player_damage_mult - 1.5) < 1e-9, r
    assert abs(r.player_max_hp_mult - 0.6) < 1e-9, r
    assert mutators.scaled_max_hp(config.PLAYER_HP, r) == 60, "max HP must be 60 percent of PLAYER_HP"
    print("[PASS] test_glass_cannon_apply passed (damage x1.5, max HP 60 percent)")


def test_bullet_hell_apply():
    r = mutators.mutator_by_id("bullet_hell").apply(RunRules())
    assert abs(r.enemy_projectile_speed_mult - 1.25) < 1e-9, r
    assert r.enemy_volley_extra == 1, r
    print("[PASS] test_bullet_hell_apply passed (shot speed x1.25, one extra shot per volley)")


def test_drift_apply():
    r = mutators.mutator_by_id("drift").apply(RunRules())
    assert r.player_accel > 0.0 and r.player_decel > 0.0, "Drift must switch on eased steering"
    assert r.player_accel < 50.0, "reduced acceleration: a rate near instant would not read as Drift"
    assert r.player_decel < r.player_accel, "the slide after release must be slower than the pick-up"
    print("[PASS] test_drift_apply passed (eased steering with a slow slide)")


def test_frenzy_apply():
    r = mutators.mutator_by_id("frenzy").apply(RunRules())
    assert abs(r.enemy_speed_mult - 1.2) < 1e-9, r
    assert abs(r.spawn_size_mult - 1.25) < 1e-9, r
    print("[PASS] test_frenzy_apply passed (enemy speed x1.2, spawn size x1.25)")


def test_iron_man_apply():
    r = mutators.mutator_by_id("iron_man").apply(RunRules())
    assert r.pickups_enabled is False, "Iron Man spawns no pickups"
    assert r.shield_regen_per_s > 0.0, "Iron Man recharges shields over time"
    print("[PASS] test_iron_man_apply passed (no pickups, passive shield recharge)")


def test_score_multiplier_label_rounds_half_up():
    assert mutators.format_score_mult(1.625) == "x1.63", "1.625 must not show as 1.62"
    assert mutators.format_score_mult(1.0) == "x1.00"
    assert mutators.format_score_mult(2.4675) == "x2.47"
    print("[PASS] test_score_multiplier_label_rounds_half_up passed (x1.63 for 1.625, two decimals always)")


def test_stock_rules_are_neutral():
    assert mutators.apply_mutators(()) == RunRules(), "an empty selection must leave the stock rules"
    assert mutators.apply_mutators(None) == RunRules()
    assert mutators.combined_score_multiplier(()) == 1.0
    assert mutators.combined_score_multiplier(["not_a_mutator"]) == 1.0, "unknown ids must not change the score"
    print("[PASS] test_stock_rules_are_neutral passed (no mutators means stock rules and a x1.00 score)")


def test_combined_multiplier_and_stacking():
    expected = 1.25 * 1.30
    assert abs(mutators.combined_score_multiplier(("glass_cannon", "frenzy")) - expected) < 1e-9
    assert abs(mutators.combined_score_multiplier(("frenzy", "glass_cannon", "frenzy")) - expected) < 1e-9, \
        "duplicates must count once"
    all_ids = [m.id for m in MUTATORS]
    prod = 1.0
    for m in MUTATORS:
        prod *= m.score_mult
    assert abs(mutators.combined_score_multiplier(all_ids) - prod) < 1e-9
    # Two stacking rules really stack: Glass Cannon plus Frenzy speeds and damages together.
    r = mutators.apply_mutators(("glass_cannon", "frenzy"))
    assert abs(r.player_damage_mult - 1.5) < 1e-9 and abs(r.enemy_speed_mult - 1.2) < 1e-9
    print("[PASS] test_combined_multiplier_and_stacking passed (product of bonuses, duplicates counted once)")


def test_selection_normalize_and_toggle():
    assert mutators.normalize_selection(["iron_man", "bogus", "drift", "iron_man", 7]) == ("drift", "iron_man")
    assert mutators.normalize_selection("drift") == (), "a bare string is not a list of ids"
    sel = mutators.toggle_selection((), "frenzy")
    assert sel == ("frenzy",)
    sel = mutators.toggle_selection(sel, "drift")
    assert sel == ("drift", "frenzy"), "selection stays in canonical order"
    sel = mutators.toggle_selection(sel, "frenzy")
    assert sel == ("drift",)
    assert mutators.toggle_selection(sel, "nope") == ("drift",), "unknown ids change nothing"
    print("[PASS] test_selection_normalize_and_toggle passed (canonical order, unknown ids dropped)")


# ---------------------------------------------------------------------------
# Persistence (user_settings.json, temp path)
# ---------------------------------------------------------------------------

def test_persistence_round_trip_keeps_other_keys():
    path = _tmp_path()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"music_volume": 0.3, "sfx_volume": 0.6, "shake_level": "reduced"}, fh)
    mutators.save_selection(("iron_man", "drift"), path=path)
    assert mutators.load_selection(path=path) == ("drift", "iron_man")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["music_volume"] == 0.3 and data["sfx_volume"] == 0.6 and data["shake_level"] == "reduced", \
        "saving mutators must keep the volume and shake keys"
    assert data[mutators.MUTATORS_KEY] == ["drift", "iron_man"]
    mutators.save_selection((), path=path)
    assert mutators.load_selection(path=path) == (), "an empty selection round-trips"
    assert not os.path.exists(path + ".tmp"), "the temp file must be replaced, not left behind"
    print("[PASS] test_persistence_round_trip_keeps_other_keys passed (temp path, other keys kept, no temp file left)")


def test_load_tolerates_missing_corrupt_and_mistyped_files():
    assert mutators.load_selection(path=_tmp_path("missing")) == (), "missing file gives no mutators"
    bad = _tmp_path("corrupt")
    with open(bad, "w", encoding="utf-8") as fh:
        fh.write("{ not json")
    assert mutators.load_selection(path=bad) == (), "corrupt file must not raise"
    wrong = _tmp_path("wrong_type")
    with open(wrong, "w", encoding="utf-8") as fh:
        json.dump({"mutators": "glass_cannon"}, fh)
    assert mutators.load_selection(path=wrong) == (), "a string instead of a list gives no mutators"
    listy = _tmp_path("list_root")
    with open(listy, "w", encoding="utf-8") as fh:
        json.dump(["drift"], fh)
    assert mutators.load_selection(path=listy) == (), "a non-dict root gives no mutators"
    print("[PASS] test_load_tolerates_missing_corrupt_and_mistyped_files passed (never raises, empty selection)")


def test_failed_save_leaves_existing_file_intact():
    path = _tmp_path("guarded")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"music_volume": 0.4, "mutators": ["drift"]}, fh)
    os.mkdir(path + ".tmp")  # the temp path is blocked, so the write must fail quietly
    try:
        mutators.save_selection(("frenzy",), path=path)  # must not raise
        assert mutators.load_selection(path=path) == ("drift",), "a failed write must not touch the saved file"
    finally:
        os.rmdir(path + ".tmp")
    print("[PASS] test_failed_save_leaves_existing_file_intact passed (blocked write is swallowed, file unchanged)")


# ---------------------------------------------------------------------------
# Per-frame hooks (pure functions)
# ---------------------------------------------------------------------------

def test_steer_stock_is_instant_and_drift_eases():
    desired = Vec2(175.0, 0.0)
    stock = mutators.steer_velocity(Vec2(0.0, 0.0), desired, DT, RunRules())
    assert stock is desired, "stock steering must return the desired velocity unchanged"
    drift = mutators.apply_mutators(("drift",))
    v = Vec2(0.0, 0.0)
    for _ in range(6):
        v = mutators.steer_velocity(v, desired, DT, drift)
    assert 0.0 < v.x < 175.0, f"Drift must ramp up over several frames, got {v.x}"
    for _ in range(600):
        v = mutators.steer_velocity(v, desired, DT, drift)
    assert abs(v.x - 175.0) < 0.5, "Drift must still reach full speed while input is held"
    print("[PASS] test_steer_stock_is_instant_and_drift_eases passed (stock snaps, Drift ramps up to full speed)")


def test_drift_slides_after_release_and_stock_does_not():
    desired = Vec2(175.0, 0.0)
    none = Vec2(0.0, 0.0)
    drift = mutators.apply_mutators(("drift",))
    v = Vec2(0.0, 0.0)
    for _ in range(120):
        v = mutators.steer_velocity(v, desired, DT, drift)
    slide = 0.0
    for _ in range(60):
        v = mutators.steer_velocity(v, none, DT, drift)
        slide += v.x * DT
    assert slide > 20.0, f"Drift must slide after release, slid {slide:.1f}"
    assert v.x < 175.0 * 0.5, "the slide must slow the ship down, not stop it dead"
    assert mutators.steer_velocity(Vec2(175.0, 0.0), none, DT, RunRules()) == none, "stock stops at once"
    print(f"[PASS] test_drift_slides_after_release_and_stock_does_not passed (slid {slide:.1f} units after release, stock 0)")


def test_shield_recharge_is_slow_capped_and_stock_free():
    rules = mutators.apply_mutators(("iron_man",))
    p = Player(pos=Vec2(0.0, 0.0), shield=0)
    carry = 0.0
    for _ in range(60):  # one second at 2 points per second
        carry = mutators.tick_shield_regen(p, carry, DT, rules, float(config.SHIELD_MAX))
    assert p.shield in (1, 2), f"about 2 shield per second, got {p.shield}"
    for _ in range(60 * 200):
        carry = mutators.tick_shield_regen(p, carry, DT, rules, float(config.SHIELD_MAX))
    assert p.shield == int(config.SHIELD_MAX), "recharge must stop at SHIELD_MAX"
    assert carry == 0.0, "a full shield keeps no carry"
    stock = Player(pos=Vec2(0.0, 0.0), shield=5)
    assert mutators.tick_shield_regen(stock, 0.0, 1.0, RunRules(), float(config.SHIELD_MAX)) == 0.0
    assert stock.shield == 5, "stock runs never recharge shields"
    print("[PASS] test_shield_recharge_is_slow_capped_and_stock_free passed (about 2/s, capped at SHIELD_MAX)")


def test_bullet_hell_speeds_and_adds_one_shot_to_a_fan():
    rules = mutators.apply_mutators(("bullet_hell",))
    # A 3-shot fan at -20, 0 and +20 degrees, every shot at speed 100.
    fan = [_enemy_bullet(10, 0, 100 * math.cos(a), 100 * math.sin(a)) for a in (math.radians(-20), 0.0, math.radians(20))]
    shots = list(fan)
    added = mutators.shape_enemy_volley(shots, 0, rules)
    assert added == 1 and len(shots) == 4, f"one extra shot expected, got {added}"
    for p in fan:
        assert abs(p.vel.length() - 125.0) < 1e-6, "every shot is 25 percent faster (100 -> 125)"
    extra = shots[-1]
    assert abs(extra.vel.length() - 125.0) < 1e-6, "the extra shot matches the volley speed"
    assert extra.owner == "enemy" and extra.damage == 8 and abs(extra.ttl - 2.0) < 1e-9
    ang = math.atan2(extra.vel.y, extra.vel.x)
    assert math.radians(-40.0) < ang < math.radians(40.0), "the extra shot sits inside the fan"
    print("[PASS] test_bullet_hell_speeds_and_adds_one_shot_to_a_fan passed (fan of 3 becomes 4, all 25 percent faster)")


def test_bullet_hell_lone_shot_gets_side_shot_and_skips_bombs():
    rules = mutators.apply_mutators(("bullet_hell",))
    shots = [_enemy_bullet(0, 0, 100, 0)]
    assert mutators.shape_enemy_volley(shots, 0, rules) == 1 and len(shots) == 2
    a0, a1 = _angles(shots)
    assert abs((a1 - a0) - math.radians(12.0)) < 1e-6, "a lone shot's extra is 12 degrees to the side"
    bomb = [_enemy_bullet(0, 0, 100, 0, ptype="bomb")]
    before = bomb[0].vel
    assert mutators.shape_enemy_volley(bomb, 0, rules) == 0 and len(bomb) == 1, "bombs get no extra shot"
    assert bomb[0].vel is before, "bombs keep their speed"
    print("[PASS] test_bullet_hell_lone_shot_gets_side_shot_and_skips_bombs passed (12 degree side shot, bombs untouched)")


def test_volley_hook_ignores_player_shots_and_stock_rules():
    rules = mutators.apply_mutators(("bullet_hell",))
    mine = Projectile(Vec2(0, 0), Vec2(300, 0), 10, owner="player")
    shots = [mine]
    assert mutators.shape_enemy_volley(shots, 0, rules) == 0 and len(shots) == 1
    assert mine.vel.x == 300, "player shots keep their speed"
    stock_shots = [_enemy_bullet(0, 0, 100, 0)]
    vel_before = stock_shots[0].vel
    assert mutators.shape_enemy_volley(stock_shots, 0, RunRules()) == 0
    assert stock_shots[0].vel is vel_before and len(stock_shots) == 1, "stock rules change nothing"
    assert mutators.shape_enemy_volley(stock_shots, 0, None) == 0, "a state without rules is stock"
    print("[PASS] test_volley_hook_ignores_player_shots_and_stock_rules passed (player and stock shots untouched)")


# ---------------------------------------------------------------------------
# Spawning (level.py) and score (score.py)
# ---------------------------------------------------------------------------

def test_frenzy_spawn_size_is_bounded_by_the_wave_cap():
    logic = EnemySpawnLogic(EnemyTuningLogic())
    for wave in (1, 3, 6, 10, 15, 22, 29):
        cap = logic.wave_cap(wave, 12)
        stock = logic.plan_wave(wave, "normal", cap).total_count
        frenzy = logic.plan_wave(wave, "normal", cap, size_mult=1.25).total_count
        assert frenzy >= stock, f"wave {wave}: Frenzy must not shrink a wave"
        assert frenzy <= cap, f"wave {wave}: Frenzy count {frenzy} exceeds the wave cap {cap}"
    assert logic.plan_wave(1, "normal", logic.wave_cap(1, 12), size_mult=1.25).total_count == 6, \
        "wave 1 normal: 5 bodies become 6 with x1.25"
    print("[PASS] test_frenzy_spawn_size_is_bounded_by_the_wave_cap passed (bigger waves, never past the cap)")


def test_spawn_wave_applies_enemy_speed_mult():
    speed_rules = RunRules(enemy_speed_mult=1.2)
    stock = GameState(wave=4, difficulty="normal", max_enemies=12)
    fast = GameState(wave=4, difficulty="normal", max_enemies=12, rules=speed_rules)
    random.seed(4242)
    stock.init_rng(seed=7)
    level.spawn_wave(stock, Vec2(0.0, 0.0))
    random.seed(4242)
    fast.init_rng(seed=7)
    level.spawn_wave(fast, Vec2(0.0, 0.0))
    assert len(stock.enemies) == len(fast.enemies) and stock.enemies, "identical seeds give identical waves"
    for a, b in zip(stock.enemies, fast.enemies):
        assert a.behavior == b.behavior
        assert abs(b.speed - a.speed * 1.2) < 1e-6, f"{b.behavior}: {b.speed} vs {a.speed} * 1.2"
    print("[PASS] test_spawn_wave_applies_enemy_speed_mult passed (same wave, every enemy 1.2x faster)")


def test_iron_man_blocks_every_pickup_source():
    no_drops = GameState(wave=6, difficulty="normal", rules=mutators.apply_mutators(("iron_man",)))
    no_drops.init_rng(seed=11)
    for _ in range(400):
        maybe_spawn_powerup(no_drops, Vec2(0.0, 0.0))
        spawn_loot_on_enemy_death(no_drops, "chaser", Vec2(0.0, 0.0), current_weapon=None)
    spawn_loot_on_enemy_death(no_drops, "boss_thunder", Vec2(0.0, 0.0), current_weapon=None)
    assert no_drops.powerups == [], f"Iron Man must spawn no pickups, got {len(no_drops.powerups)}"

    stock = GameState(wave=6, difficulty="normal")
    stock.init_rng(seed=11)
    spawn_loot_on_enemy_death(stock, "boss_thunder", Vec2(0.0, 0.0), current_weapon=None)
    assert len(stock.powerups) >= 2, "stock boss kills still drop loot"
    print("[PASS] test_iron_man_blocks_every_pickup_source passed (no random, kill or boss drops)")


def test_score_multiplier_scales_points_and_default_is_unchanged():
    t = ScoreTracker("normal", score_mult=2.0)
    assert t.on_enemy_kill("chaser") == 200, "a x2 run doubles kill points"
    fresh = ScoreTracker("normal", score_mult=2.0)
    wave_one = score_mod.WAVE_CLEAR_BASE + 1 * score_mod.WAVE_CLEAR_PER_WAVE  # 650 at combo 1.0
    assert fresh.on_wave_clear(1) == 2 * wave_one, "the wave-clear bonus doubles too"
    plain = ScoreTracker("normal")
    assert plain.score_mult == 1.0 and plain.on_enemy_kill("chaser") == 100, "default score is unchanged"
    print("[PASS] test_score_multiplier_scales_points_and_default_is_unchanged passed (kills and wave bonus scale)")


# ---------------------------------------------------------------------------
# Game integration (window needed)
# ---------------------------------------------------------------------------

def _quiet_state(g):
    """The live run (built by the caller's _init_game) with no enemies and no wave spawns, so a frame only exercises the player."""
    s = g.state
    s.enemies = []
    s.wave_active = False
    s.last_wave_clear = 1e9  # keeps the wave timer from firing during the test
    return s


def _step(g, frames):
    playing = PlayingState(g)
    for _ in range(frames):
        playing.update(DT)


def test_init_game_applies_the_mutators_it_was_given(g):
    saved = g.mutator_ids
    try:
        g.mutator_ids = ()
        g._init_game(mutator_ids=("glass_cannon", "iron_man"))
        assert g.run_mutators == ("glass_cannon", "iron_man")
        assert g.player.max_hp == 60 and g.player.hp == 60, "Glass Cannon sets max HP to 60"
        assert abs(g.run_rules.player_damage_mult - 1.5) < 1e-9
        assert g.state.rules is g.run_rules, "the state carries the run's rules"
        assert g.state.rules.pickups_enabled is False, "Iron Man reaches the state"
        assert g._effective_player_damage() == 15, "10 * 1.5 is the shot base the run uses"
        assert abs(g.score.score_mult - 1.25 * 1.15) < 1e-9, "the run's score uses the combined multiplier"
        assert g.mutator_ids == (), "applying a run never rewrites the title selection"

        g._init_game(mutator_ids=())
        assert g.player.max_hp == config.PLAYER_HP and g.player.hp == config.PLAYER_HP
        assert g.run_rules == RunRules() and g.score.score_mult == 1.0 and g.state.rules.pickups_enabled
        print("[PASS] test_init_game_applies_the_mutators_it_was_given passed (given selection applied, stock run restored)")
    finally:
        g.mutator_ids = saved
        g._init_game()


def test_run_snapshot_is_fixed_for_the_run(g):
    g._init_game(mutator_ids=("drift",))
    rules_before = g.run_rules
    g.mutator_ids = ("frenzy",)  # a title-screen change while a run is live must not reach it
    assert g.run_rules is rules_before and g.run_mutators == ("drift",)
    _step(g, 1)
    assert g.run_rules is rules_before, "updates never re-apply mutators"
    g.mutator_ids = ()
    g._init_game(mutator_ids=("drift",))
    assert g.run_mutators == ("drift",), "the next run picks up whatever it is given"
    print("[PASS] test_run_snapshot_is_fixed_for_the_run passed (mutators fixed for the run, applied only in _init_game)")


def test_hooks_run_in_the_live_update(g):
    # Bullet Hell: enemy volleys get the speed and extra shot inside the real update loop.
    g._init_game(mutator_ids=("bullet_hell",))
    s = _quiet_state(g)
    shooter = Enemy(pos=Vec2(260.0, 0.0), hp=50, speed=0.0, behavior="ranged")
    s.enemies = [shooter]

    real_update_enemy = states.update_enemy

    def fake_update(enemy, player_pos, state, dt, game, player_vel=None):
        state.projectiles.append(Projectile(Vec2(enemy.pos.x, enemy.pos.y), Vec2(100.0, 0.0), 8, ttl=2.0, owner="enemy"))

    states.update_enemy = fake_update
    try:
        _step(g, 1)
    finally:
        states.update_enemy = real_update_enemy
    enemy_shots = [p for p in s.projectiles if p.owner == "enemy"]
    assert len(enemy_shots) == 2, f"the volley must gain one shot, got {len(enemy_shots)}"
    assert all(abs(p.vel.length() - 125.0) < 1e-6 for p in enemy_shots), "shots fly at 1.25x"

    # Drift: holding D (south-east in iso space, +x / -y) moves the ship with easing; releasing it slides on.
    held = Vec2(1.0, -1.0)
    g._init_game(mutator_ids=("drift",))
    s = _quiet_state(g)
    g._input_dir = lambda: held
    try:
        _step(g, 4)
        moved_held = g.player.pos.x
        assert g.player.move_vel.length() > 0.0, "Drift builds velocity while input is held"
        assert moved_held > 0.0
        g._input_dir = lambda: Vec2(0.0, 0.0)
        before_slide = g.player.pos.x
        _step(g, 20)
        assert g.player.pos.x - before_slide > 0.5, "Drift keeps moving after release"

        # Stock: the ship stops the frame input is released.
        g._init_game(mutator_ids=())
        s = _quiet_state(g)
        g._input_dir = lambda: held
        _step(g, 4)
        g._input_dir = lambda: Vec2(0.0, 0.0)
        stop_at = g.player.pos.x
        _step(g, 20)
        assert abs(g.player.pos.x - stop_at) < 1e-9, "stock steering stops at once"
    finally:
        g.__dict__.pop("_input_dir", None)  # back to the keyboard

    # Iron Man: shields recharge during real frames.
    g._init_game(mutator_ids=("iron_man",))
    s = _quiet_state(g)
    g.player.shield = 0
    _step(g, 90)  # 1.5 seconds
    assert g.player.shield in (2, 3), f"about 3 shield after 1.5 s, got {g.player.shield}"
    print("[PASS] test_hooks_run_in_the_live_update passed (Bullet Hell volley, Drift slide, stock stop, Iron Man recharge)")


def test_glass_cannon_keeps_incoming_damage_unchanged(g):
    g._init_game(mutator_ids=("glass_cannon",))
    g.player.invincibility_timer = 0.0
    g.player.shield = 0
    before = g.player.hp
    g._damage_player(10)
    assert g.player.hp == before - 10, "Glass Cannon raises outgoing damage only"
    print("[PASS] test_glass_cannon_keeps_incoming_damage_unchanged passed (outgoing x1.5 only, incoming unchanged)")


def test_game_over_shows_combined_multiplier(g):
    saved_board = score_mod.HIGH_SCORE_FILE
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP, "board_gameover.json")
    try:
        g._init_game(mutator_ids=("glass_cannon", "frenzy"))
        g.state.wave = 3
        g.score.score = 1234
        g.fsm.set_state(GameStateName.GAME_OVER)
        text = g.game_over_menu.mutator_label.text
        assert "Glass Cannon, Frenzy" in text, text
        assert "score x1.63" in text, f"1.25 * 1.30 = 1.625 must read x1.63: {text}"
        g._init_game(mutator_ids=())
        g.fsm.set_state(GameStateName.GAME_OVER)
        assert "none" in g.game_over_menu.mutator_label.text and "score x1.00" in g.game_over_menu.mutator_label.text
    finally:
        score_mod.HIGH_SCORE_FILE = saved_board
        g._init_game()
    print("[PASS] test_game_over_shows_combined_multiplier passed (names and x multiplier on the Game Over screen)")


def test_game_over_mutator_line_has_room(g):
    menu = g.game_over_menu
    for w, h in ((980, 620), (1280, 720), (1920, 1080)):
        menu.resize(w, h)
        base = menu._base_y
        mut_h = menu.mutator_label.font_size * 0.75
        hint_h = menu.hint_label.font_size * 0.75
        assert base["mutators"] + mut_h < base["hint"] - hint_h, f"mutator line overlaps the hint at {w}x{h}"
        assert base["mutators"] - mut_h > 0, f"mutator line falls off the screen at {w}x{h}"
        assert base["mutators"] + mut_h < menu._button_base_y[1], f"mutator line overlaps the lower button at {w}x{h}"
    menu.resize(g.width, g.height)
    print("[PASS] test_game_over_mutator_line_has_room passed (mutator line clear of the hint and the screen edge)")


def test_title_buttons_keep_their_actions(g):
    menu = g.main_menu
    menu.resize(980, 620)
    expected = {"Start Game": "start_game", "Guide": "guide", "Settings": "settings", "Quit": "quit"}
    for btn in menu.buttons:
        cx = btn.x + btn.width / 2.0
        cy = btn.y + btn.height / 2.0
        action = menu.on_mouse_press(cx, cy, pyglet.window.mouse.LEFT)
        assert action == expected[btn.text], f"{btn.text} returned {action!r}"
    assert len(menu.buttons) == 4, "the title keeps its four buttons"
    menu.resize(g.width, g.height)
    print("[PASS] test_title_buttons_keep_their_actions passed (Start Game, Guide, Settings, Quit unchanged)")


def test_title_chip_toggles_and_saves(g):
    saved_path = audio._SETTINGS_PATH
    saved_ids = g.mutator_ids
    path = _tmp_path("title_chips")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"music_volume": 0.25}, fh)
    audio._SETTINGS_PATH = path
    try:
        menu = g.main_menu
        menu.resize(980, 620)
        g.mutator_ids = ()
        menu.set_mutator_selection(())
        chip = menu.mutator_row._chips[mutators.MUTATORS.index(mutators.mutator_by_id("drift"))]
        cx = chip.x + chip.w / 2.0
        cy = chip.y + chip.h / 2.0
        action = menu.on_mouse_press(cx, cy, pyglet.window.mouse.LEFT)
        assert action is None, "a chip click returns no action"
        assert g.mutator_ids == ("drift",), g.mutator_ids
        assert menu.mutator_row.selected_ids == ("drift",)
        assert mutators.load_selection(path=path) == ("drift",), "the selection is saved"
        with open(path, "r", encoding="utf-8") as fh:
            assert json.load(fh)["music_volume"] == 0.25, "saving the selection keeps the volume"
        menu.on_mouse_press(cx, cy, pyglet.window.mouse.LEFT)
        assert g.mutator_ids == () and mutators.load_selection(path=path) == (), "a second click switches it off"
        assert menu.on_mouse_press(cx, cy, pyglet.window.mouse.RIGHT) is None
    finally:
        audio._SETTINGS_PATH = saved_path
        g.mutator_ids = saved_ids
        g.main_menu.set_mutator_selection(saved_ids)
        g.main_menu.resize(g.width, g.height)
    print("[PASS] test_title_chip_toggles_and_saves passed (chip click toggles, returns no action, saves without losing keys)")


def test_title_chips_sit_below_the_panel(g):
    menu = g.main_menu
    for w, h in ((980, 620), (1920, 1080)):
        menu.resize(w, h)
        row = menu.mutator_row
        panel_bottom = menu._panel.y
        chip_tops = [c.y + c.h for c in row._chips]
        assert all(top < panel_bottom for top in chip_tops), f"chips must sit below the button panel at {w}x{h}"
        assert all(c.x >= 0 and c.x + c.w <= w for c in row._chips), f"chips run off the screen at {w}x{h}"
        assert min(c.y for c in row._chips) > 0, f"chips fall off the bottom at {w}x{h}"
        footer_top = menu.footer.y + menu.footer.content_height
        assert min(c.y for c in row._chips) > footer_top, f"chips collide with the footer at {w}x{h}"
    menu.resize(g.width, g.height)
    print("[PASS] test_title_chips_sit_below_the_panel passed (chips below the panel, on screen, clear of the footer)")


# ---------------------------------------------------------------------------

def run_all():
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP, "board_main.json")
    test_registry_has_five_described_mutators()
    test_score_multiplier_label_rounds_half_up()
    test_glass_cannon_apply()
    test_bullet_hell_apply()
    test_drift_apply()
    test_frenzy_apply()
    test_iron_man_apply()
    test_stock_rules_are_neutral()
    test_combined_multiplier_and_stacking()
    test_selection_normalize_and_toggle()
    test_persistence_round_trip_keeps_other_keys()
    test_load_tolerates_missing_corrupt_and_mistyped_files()
    test_failed_save_leaves_existing_file_intact()
    test_steer_stock_is_instant_and_drift_eases()
    test_drift_slides_after_release_and_stock_does_not()
    test_shield_recharge_is_slow_capped_and_stock_free()
    test_bullet_hell_speeds_and_adds_one_shot_to_a_fan()
    test_bullet_hell_lone_shot_gets_side_shot_and_skips_bombs()
    test_volley_hook_ignores_player_shots_and_stock_rules()
    test_frenzy_spawn_size_is_bounded_by_the_wave_cap()
    test_spawn_wave_applies_enemy_speed_mult()
    test_iron_man_blocks_every_pickup_source()
    test_score_multiplier_scales_points_and_default_is_unchanged()

    g = Game()
    g.set_visible(False)
    saved_path = audio._SETTINGS_PATH
    audio._SETTINGS_PATH = _tmp_path("run_all")  # the real user_settings.json is never written
    try:
        test_init_game_applies_the_mutators_it_was_given(g)
        test_run_snapshot_is_fixed_for_the_run(g)
        test_hooks_run_in_the_live_update(g)
        test_glass_cannon_keeps_incoming_damage_unchanged(g)
        test_game_over_shows_combined_multiplier(g)
        test_game_over_mutator_line_has_room(g)
        test_title_buttons_keep_their_actions(g)
        test_title_chip_toggles_and_saves(g)
        test_title_chips_sit_below_the_panel(g)
    finally:
        audio._SETTINGS_PATH = saved_path
        g.close()
        shutil.rmtree(_TMP, ignore_errors=True)
    print("\nALL W1 MUTATOR TESTS PASSED")


if __name__ == "__main__":
    run_all()
