"""Deterministic tests for the boss rage phase and the boss-kill set piece (wave 2, bossv2).

Boss AI tests use a minimal fake run state with a seeded RNG, so they never read the real clock or
global random. Banner, audio and flash tests use a real Game and are the only ones that need a window.
"""

import math
import random

import boss_rage
from boss_rage import FANFARE_MIN_GAP, RAGE_COOLDOWN_MULT
from enemy import Enemy, update_enemy
from game import Game
from states import GameStateName, PlayingState
from utils import Vec2

DT = 1.0 / 60.0
BOSSES = [
    "boss_thunder",
    "boss_laser",
    "boss_trapmaster",
    "boss_swarmqueen",
    "boss_brute",
    "boss_abyss_gaze",
    "boss_womb_core",
]
# Bosses whose attack cooldown is Enemy.attack_cd, and the state-machine timers used by the others.
ATTACK_CD_BOSSES = ["boss_trapmaster", "boss_swarmqueen", "boss_abyss_gaze", "boss_womb_core"]


class _FakeHud:
    def __init__(self):
        self.banners = []

    def show_banner(self, title, subtitle="", color=(238, 245, 255), duration=2.2):
        self.banners.append((str(title), str(subtitle), tuple(color), float(duration)))


class _FakeAudio:
    def __init__(self):
        self.plays = []

    def play(self, name, volume=1.0, pitch_jitter=0.0, min_gap=0.0):
        self.plays.append((str(name), float(volume), float(min_gap)))


class _FakeGame:
    def __init__(self):
        self.hud = _FakeHud()
        self.audio = _FakeAudio()
        self.advanced_fx = None


class _FakeState:
    """The fields the boss AI reads and writes, with a seeded RNG for the run."""

    def __init__(self, seed, wave=10, difficulty="normal"):
        self.rng = random.Random(seed)
        self.wave = wave
        self.difficulty = difficulty
        self.max_enemies = 12
        self.enemies = []
        self.projectiles = []
        self.traps = []
        self.lasers = []
        self.thunders = []


def _boss(behavior, hp=500, seed=2.0, pos=None):
    # seed 2.0 gives the trickster persona (fires its phase-0 fan) and seed 1.0 the cautious one.
    return Enemy(pos=pos or Vec2(260.0, 40.0), hp=hp, speed=60.0, behavior=behavior, max_hp=hp, seed=seed)


def _tick_boss(boss, state, game, player_pos=None, frames=1):
    for _ in range(frames):
        update_enemy(boss, player_pos or Vec2(0.0, 0.0), state, DT, game, player_vel=Vec2(0.0, 0.0))


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


def test_update_rage_threshold_is_inclusive_at_35_percent():
    game = _FakeGame()
    boss = _boss("boss_womb_core", hp=500)
    boss.ai["max_hp"] = 500
    boss.attack_cd = 2.0
    assert boss_rage.update_rage(boss, game) is False, "full HP must not enter rage"
    boss.hp = 176  # 35.2 percent
    assert boss_rage.update_rage(boss, game) is False, "just above 35 percent must not enter rage"
    assert not boss_rage.is_raged(boss)
    boss.hp = 175  # exactly 35 percent
    assert boss_rage.update_rage(boss, game) is True, "exactly 35 percent must enter rage"
    assert abs(boss.attack_cd - 2.0 * RAGE_COOLDOWN_MULT) < 1e-9, "the pending cooldown shrinks with rage"
    assert boss_rage.update_rage(boss, game) is False, "rage must not start a second time"
    boss.hp = 40
    assert boss_rage.update_rage(boss, game) is False, "further damage must not start rage again"
    assert len(game.hud.banners) == 1, f"banner requested {len(game.hud.banners)} times"
    print("[PASS] test_update_rage_threshold_is_inclusive_at_35_percent passed (35 percent enters once, cooldown shrinks)")


def test_every_boss_enters_rage_once_with_one_banner_and_warning():
    for name in BOSSES:
        state = _FakeState(seed=3)
        game = _FakeGame()
        boss = _boss(name)
        state.enemies.append(boss)
        # The first AI update records max HP, so the boss must be ticked at full HP before it is hurt.
        for hp in (500, 450, 300, 176):
            boss.hp = hp
            _tick_boss(boss, state, game)
        assert not boss_rage.is_raged(boss), f"{name} raged above 35 percent"
        boss.hp = 175  # exactly 35 percent: rage must start on this frame
        _tick_boss(boss, state, game)
        assert boss_rage.is_raged(boss), f"{name} did not rage at 35 percent"
        for hp in (170, 120, 60):
            boss.hp = hp
            _tick_boss(boss, state, game, frames=3)
        titles = [b[0] for b in game.hud.banners]
        assert titles == ["BOSS RAGE"], f"{name}: banner requests {titles}"
        # The rage warning is the wave-3 "rage_warn" cue (audio_cues.CUE_SPECS), one sound per rage.
        assert [p[0] for p in game.audio.plays] == ["rage_warn"], f"{name}: sounds {game.audio.plays}"
        assert name[5:].replace("_", " ").upper() in game.hud.banners[0][1], f"{name}: subtitle {game.hud.banners[0][1]!r}"
    print(f"[PASS] test_every_boss_enters_rage_once_with_one_banner_and_warning passed ({len(BOSSES)} bosses, one banner and one rage_warn each)")


def _cooldown_after_one_volley(name, raged):
    state = _FakeState(seed=5)
    game = _FakeGame()
    boss = _boss(name, seed=2.0)
    if raged:
        boss.ai["rage"] = True
    state.enemies.append(boss)
    if name in ATTACK_CD_BOSSES:
        boss.attack_cd = 0.0
        _tick_boss(boss, state, game)
        return {"cd": boss.attack_cd}
    if name == "boss_thunder":
        boss.ai["thunder_state"] = "attack"
        boss.ai["thunder_timer"] = 0.0
        _tick_boss(boss, state, game)
        return {"cd": boss.ai["thunder_timer"]}
    if name == "boss_brute":
        boss.ai["brute_state"] = "recover"
        boss.ai["brute_timer"] = 0.0
        _tick_boss(boss, state, game)
        return {"cd": boss.ai["brute_timer"]}
    # laser: one sweep volley, then the reposition cooldown after it
    boss.ai["laser_state"] = "attack"
    boss.ai["laser_timer"] = 0.0
    boss.ai["laser_tick"] = 0.0
    _tick_boss(boss, state, game)
    return {"cd": boss.ai["laser_timer"], "tick": boss.ai["laser_tick"]}


def test_cooldowns_shrink_by_25_percent_while_raged():
    for name in BOSSES:
        normal = _cooldown_after_one_volley(name, raged=False)
        raged = _cooldown_after_one_volley(name, raged=True)
        for key in normal:
            assert normal[key] > 0.0, f"{name} {key} cooldown was not set"
            assert abs(raged[key] - normal[key] * 0.75) < 1e-9, f"{name} {key}: normal {normal[key]}, raged {raged[key]}"
    print(f"[PASS] test_cooldowns_shrink_by_25_percent_while_raged passed ({len(BOSSES)} bosses, every cooldown is 0.75x)")


def _projectiles_and_beams_per_volley(name, raged):
    state = _FakeState(seed=7)
    game = _FakeGame()
    boss = _boss(name, seed=2.0 if name != "boss_laser" else 1.0)
    if raged:
        boss.ai["rage"] = True
    state.enemies.append(boss)
    if name == "boss_laser":
        boss.ai["laser_state"] = "attack"
        boss.ai["laser_timer"] = 5.0
        boss.ai["laser_tick"] = 0.0
    else:
        boss.attack_cd = 0.0
    _tick_boss(boss, state, game)
    return len(state.projectiles), len(state.lasers)


def test_each_volley_gains_exactly_one_projectile_or_beam():
    for name in ("boss_trapmaster", "boss_abyss_gaze", "boss_womb_core"):
        normal, _ = _projectiles_and_beams_per_volley(name, raged=False)
        raged, _ = _projectiles_and_beams_per_volley(name, raged=True)
        assert normal > 0, f"{name} fired nothing in a normal volley"
        assert raged - normal == 1, f"{name}: {normal} shots normally, {raged} while raged"
    _, normal_beams = _projectiles_and_beams_per_volley("boss_laser", raged=False)
    _, raged_beams = _projectiles_and_beams_per_volley("boss_laser", raged=True)
    assert normal_beams == 1 and raged_beams == 2, f"laser beams: normal {normal_beams}, raged {raged_beams}"
    assert boss_rage.volley(_boss("boss_brute"), 12) == 12, "brute shockwave must not change before rage"
    print("[PASS] test_each_volley_gains_exactly_one_projectile_or_beam passed (trapmaster, abyss, womb +1 shot; laser 1 to 2 beams)")


def _seeded_rage_trace(name, seed):
    state = _FakeState(seed=seed)
    game = _FakeGame()
    boss = Enemy(pos=Vec2(260.0, 40.0), hp=500, speed=60.0, behavior=name, max_hp=500)
    state.enemies.append(boss)
    trace = []
    for frame in range(480):
        if frame == 200:
            boss.hp = 170  # 34 percent: rage starts here
        ang = frame * 0.05
        player = Vec2(math.cos(ang) * 120.0, math.sin(ang) * 120.0)
        update_enemy(boss, player, state, DT, game, player_vel=Vec2(0.0, 0.0))
        trace.append((
            round(boss.pos.x, 6), round(boss.pos.y, 6), round(boss.attack_cd, 6),
            len(state.projectiles), len(state.traps), len(state.lasers), len(state.thunders), len(state.enemies),
        ))
    return tuple(trace), boss_rage.is_raged(boss), [b[0] for b in game.hud.banners]


def test_seeded_rage_run_is_reproducible():
    for name in BOSSES:
        first = _seeded_rage_trace(name, seed=99)
        second = _seeded_rage_trace(name, seed=99)
        assert first[1], f"{name} never raged in the seeded run"
        assert first[0] == second[0], f"{name}: same seed gave different runs"
        assert first[2] == ["BOSS RAGE"], f"{name}: banners {first[2]}"
        assert len(set(first[0])) > 1, f"{name}: trace did not move, so the check proves nothing"
    print(f"[PASS] test_seeded_rage_run_is_reproducible passed ({len(BOSSES)} bosses, identical traces for seed 99)")


def test_rage_draws_no_global_random_calls():
    names = ["random", "uniform", "randint", "randrange", "choice", "gauss", "shuffle", "sample", "triangular"]
    saved = {n: getattr(random, n) for n in names}

    def _forbidden(*args, **kwargs):
        raise AssertionError("global random call inside boss rage code")

    try:
        for n in names:
            setattr(random, n, _forbidden)
        for name in BOSSES:
            state = _FakeState(seed=11)
            game = _FakeGame()
            boss = _boss(name, seed=0.0)
            state.enemies.append(boss)
            _tick_boss(boss, state, game)
            boss.hp = 150
            _tick_boss(boss, state, game, frames=120)
            assert boss_rage.is_raged(boss), f"{name} did not rage"
    finally:
        for n, fn in saved.items():
            setattr(random, n, fn)
    print("[PASS] test_rage_draws_no_global_random_calls passed (all 7 bosses rage with the global random module disabled)")


def test_rage_helpers_are_identity_before_rage():
    boss = _boss("boss_womb_core")
    assert not boss_rage.is_raged(boss)
    assert boss_rage.cooldown(boss, 2.0) == 2.0
    assert boss_rage.volley(boss, 5) == 5
    print("[PASS] test_rage_helpers_are_identity_before_rage passed (cooldown and volley unchanged before rage)")


def test_rage_banner_reaches_the_real_hud(g):
    s = _new_run(g)
    boss = _boss("boss_brute", hp=500)
    s.enemies = [boss]
    _tick_boss(boss, s, g)
    boss.hp = 120
    _tick_boss(boss, s, g)
    assert g.hud._banner_active, "rage banner must be on screen"
    assert g.hud._banner_src[0] == "BOSS RAGE", f"banner title {g.hud._banner_src[0]!r}"
    assert "BRUTE" in g.hud._banner_src[1], f"banner subtitle {g.hud._banner_src[1]!r}"
    print("[PASS] test_rage_banner_reaches_the_real_hud passed (BOSS RAGE banner active on the HUD)")


def test_boss_kill_flashes_and_plays_fanfare(g):
    s = _new_run(g)
    boss = _boss("boss_womb_core", hp=500)
    s.enemies = [boss]
    played = []
    real_play = g.audio.play

    def spy(name, volume=1.0, pitch_jitter=0.0, min_gap=0.0):
        played.append((name, float(min_gap)))
        return real_play(name, volume=volume, pitch_jitter=pitch_jitter, min_gap=min_gap)

    g.audio.play = spy
    try:
        g.advanced_fx.enabled = True
        g.advanced_fx._boss_flash = 0.0
        PlayingState._kill_enemy(g, s, boss)
    finally:
        del g.audio.play
    assert g.advanced_fx._boss_flash > 0.9, f"boss kill flash {g.advanced_fx._boss_flash}"
    # The victory fanfare is its own cue ("victory_fanfare", wave 3); the wave-clear chirp is skipped on this frame.
    assert any(name == "victory_fanfare" for name, _gap in played), f"fanfare not played: {played}"
    assert not any(name == "wave_clear" for name, _gap in played), f"chirp doubled the fanfare: {played}"
    assert ("boss_die", 0.0) in played, f"boss_die not played: {played}"
    assert FANFARE_MIN_GAP > 0.0, "fanfare needs a minimum gap so the same-frame wave clear is dropped"
    print("[PASS] test_boss_kill_flashes_and_plays_fanfare passed (camera flash and victory fanfare on a boss kill)")


def test_boss_flash_decays_to_zero(g):
    fx = g.advanced_fx
    fx.enabled = True
    fx.trigger_boss_flash(5.0)
    assert fx._boss_flash == 1.0, "flash strength must clamp to 1.0"
    for _ in range(40):
        fx.render(0.0, 0.5, hp_ratio=1.0, boss_active=False)
    assert fx._boss_flash == 0.0, f"flash still {fx._boss_flash} after 40 frames"
    print("[PASS] test_boss_flash_decays_to_zero passed (strength clamps to 1.0 and fades within 40 frames)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_update_rage_threshold_is_inclusive_at_35_percent()
        test_every_boss_enters_rage_once_with_one_banner_and_warning()
        test_cooldowns_shrink_by_25_percent_while_raged()
        test_each_volley_gains_exactly_one_projectile_or_beam()
        test_seeded_rage_run_is_reproducible()
        test_rage_draws_no_global_random_calls()
        test_rage_helpers_are_identity_before_rage()
        test_rage_banner_reaches_the_real_hud(g)
        test_boss_kill_flashes_and_plays_fanfare(g)
        test_boss_flash_decays_to_zero(g)
    finally:
        g.close()
    print("\nALL WAVE 2 BOSSV2 TESTS PASSED")


if __name__ == "__main__":
    run_all()
