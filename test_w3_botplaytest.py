"""Tests for tools/playtest.py: the bot, the invariant checks, softlock detection, the report and determinism."""

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

import config
from enemy import Enemy
from fsm import State, StateMachine
from level import GameState
from player import Player
from powerup import PowerUp
from projectile import Projectile
from states import GameStateName
from utils import Vec2

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from tools import playtest  # noqa: E402

_GAME = None


def _shared_game():
    """One hidden window for every integration check in this file; creating windows is slow."""
    global _GAME
    if _GAME is None:
        _GAME = playtest._create_game()
        _GAME.audio = playtest._SilentAudio()
    return _GAME


def _file_hash(path):
    if not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _state(**fields):
    s = GameState()
    s.wave = fields.get("wave", 2)
    s.time = fields.get("time", 0.0)
    s.wave_active = True
    return s


def _enemy(x, y, hp=40, behavior="chaser"):
    return Enemy(pos=Vec2(x, y), hp=hp, speed=0.0, behavior=behavior, max_hp=hp)


def test_invariant_checker_flags_bad_frames():
    """check_frame passes a clean frame and reports NaN positions, HP out of range and runaway lists."""
    s = _state()
    p = Player(pos=Vec2(0.0, 0.0))
    assert playtest.check_frame(s, p, "PlayingState", wave_cap=12) == [], "clean frame must pass"

    p.pos = Vec2(float("nan"), 0.0)
    assert any("not finite" in t for t in playtest.check_frame(s, p, "PlayingState", 12)), "NaN position missed"
    p.pos = Vec2(0.0, float("inf"))
    assert any("not finite" in t for t in playtest.check_frame(s, p, "PlayingState", 12)), "infinite position missed"

    p = Player(pos=Vec2(0.0, 0.0))
    p.hp = p.max_hp + 1
    assert any("above max_hp" in t for t in playtest.check_frame(s, p, "PlayingState", 12)), "overheal missed"
    p.hp = -3
    assert any("below zero" in t for t in playtest.check_frame(s, p, "PlayingState", 12)), "negative hp missed"
    assert playtest.check_frame(s, p, "GameOverState", 12) == [], "negative hp is allowed on the game over frame"

    p = Player(pos=Vec2(0.0, 0.0))
    limit = 12 + playtest.ADD_ALLOWANCE
    s.enemies = [_enemy(10.0 * i, 0.0) for i in range(limit)]
    assert playtest.check_frame(s, p, "PlayingState", 12) == [], "enemy count at the limit must pass"
    s.enemies.append(_enemy(0.0, 500.0))
    assert any("enemies alive" in t for t in playtest.check_frame(s, p, "PlayingState", 12)), "enemy overflow missed"

    s.enemies = []
    s.projectiles = [Projectile(Vec2(0.0, 0.0), Vec2(1.0, 0.0), 1, owner="enemy") for _ in range(playtest.PROJECTILE_LIMIT + 1)]
    assert any("projectiles alive" in t for t in playtest.check_frame(s, p, "PlayingState", 12)), "projectile growth missed"
    print("[PASS] test_invariant_checker_flags_bad_frames passed (NaN, HP bounds, enemy cap and projectile cap)")


def test_softlock_watch_timing():
    """A softlock needs an active wave, live enemies and 60 game seconds with no damage and no kill."""
    e = _enemy(0.0, 0.0)
    watch = playtest.SoftlockWatch(60.0)
    assert watch.update(0.0, True, [e]) is False
    assert watch.update(59.0, True, [e]) is False, "59 seconds without progress is not a softlock"
    assert watch.update(60.0, True, [e]) is True, "60 seconds without progress is a softlock"

    watch = playtest.SoftlockWatch(60.0)
    watch.update(0.0, True, [e])
    e.hp -= 1  # a hit at t=30 is progress
    assert watch.update(30.0, True, [e]) is False
    assert watch.update(89.0, True, [e]) is False, "the clock restarts at the last hit"
    assert watch.update(90.0, True, [e]) is True

    watch = playtest.SoftlockWatch(60.0)
    watch.update(0.0, True, [e, _enemy(50.0, 0.0)])
    assert watch.update(70.0, True, [e]) is False, "a kill at t=70 counts as progress (the enemy left the list)"

    shield_watch = playtest.SoftlockWatch(60.0)
    shielded = _enemy(0.0, 0.0)
    shielded.shield = 20
    shield_watch.update(0.0, True, [shielded])
    shielded.shield = 0
    assert shield_watch.update(10.0, True, [shielded]) is False, "shield damage is progress too"

    watch = playtest.SoftlockWatch(60.0)
    watch.update(0.0, True, [e])
    assert watch.update(100.0, False, [e]) is False, "no softlock when the wave is not active"
    assert watch.update(200.0, True, []) is False, "an empty enemy list is never a softlock"
    assert watch.update(201.0, True, [e]) is False, "a new wave restarts the clock"
    assert watch.update(261.0, True, [e]) is True
    print("[PASS] test_softlock_watch_timing passed (60 s rule, progress resets, inactive waves and new waves)")


def test_transition_guard_flags_illegal_edges():
    """The guard records edges that are not in ALLOWED_TRANSITIONS and removes itself on uninstall."""
    classes = {m.value: type(m.value, (State,), {}) for m in GameStateName}
    fsm = StateMachine(classes["MenuState"](None))
    for name, cls in classes.items():
        if name != "MenuState":
            fsm.add_state(cls(None))
    guard = playtest.TransitionGuard(fsm)
    guard.install()
    fsm.set_state(GameStateName.PLAYING)  # Menu -> Playing is legal
    assert guard.violations == [], f"legal edge reported: {guard.violations}"
    fsm.set_state(GameStateName.MENU)  # Playing -> Menu is not a game edge
    assert guard.violations == ["illegal transition PlayingState -> MenuState"], guard.violations
    guard.uninstall()
    assert "set_state" not in fsm.__dict__, "guard must restore the FSM"
    print("[PASS] test_transition_guard_flags_illegal_edges passed (legal edges pass, Playing -> Menu is flagged)")


def test_transition_table_matches_states_source():
    """Every state the game switches to appears as a destination in ALLOWED_TRANSITIONS."""
    targets = set()
    for name in ("states.py", "game.py"):
        with open(os.path.join(ROOT, name), "r", encoding="utf-8") as fh:
            targets.update(re.findall(r"set_state\(GameStateName\.([A-Z_]+)\)", fh.read()))
    names = {"MENU": "MenuState", "SETTINGS": "SettingsState", "GUIDE": "GuideState", "PLAYING": "PlayingState",
             "PAUSED": "PausedState", "BOSS_REWARD": "BossRewardState", "GAME_OVER": "GameOverState",
             "HANGAR": "HangarState"}
    destinations = {d for dests in playtest.ALLOWED_TRANSITIONS.values() for d in dests}
    missing = sorted(names[t] for t in targets if names[t] not in destinations)
    assert not missing, f"game switches to states the table forbids: {missing}"
    print(f"[PASS] test_transition_table_matches_states_source passed ({len(targets)} game transition targets covered)")


def test_bot_aims_at_nearest_enemy():
    """The aim point is the nearest live enemy, whatever order the list holds."""
    bot = playtest.Bot(7)
    s = _state()
    s.enemies = [_enemy(300.0, 0.0), _enemy(0.0, 120.0)]
    plan = bot.plan(Player(pos=Vec2(0.0, 0.0)), s, config.ROOM_RADIUS)
    assert abs(plan.aim.x) < 1e-9 and abs(plan.aim.y - 120.0) < 1e-9, f"aimed at {plan.aim}"
    print("[PASS] test_bot_aims_at_nearest_enemy passed (aim is the nearest enemy)")


def test_bot_dashes_out_of_an_incoming_shot():
    """An enemy shot on course for the player triggers a dash, and the keys point away from its line."""
    bot = playtest.Bot(7)
    s = _state()
    s.projectiles = [Projectile(Vec2(60.0, 0.0), Vec2(-300.0, 0.0), 10, ttl=1.0, owner="enemy")]
    plan = bot.plan(Player(pos=Vec2(0.0, 0.0)), s, config.ROOM_RADIUS)
    assert plan.dash is True, "a shot 60 px away on course must trigger a dash"
    assert plan.keys == (False, True, False, True), f"expected S+D (world -y), got {plan.keys}"

    p = Player(pos=Vec2(0.0, 0.0))
    p.dash_charges = 0
    assert bot.plan(p, s, config.ROOM_RADIUS).dash is False, "no dash without a charge"

    s.projectiles = [Projectile(Vec2(60.0, 0.0), Vec2(300.0, 0.0), 10, ttl=1.0, owner="enemy")]
    assert playtest.Bot(7).plan(Player(pos=Vec2(0.0, 0.0)), s, config.ROOM_RADIUS).dash is False, \
        "a shot moving away is not a threat"
    print("[PASS] test_bot_dashes_out_of_an_incoming_shot passed (dash on a threat, none without charge or on a receding shot)")


def test_bot_ultra_only_when_charged():
    """Ultra is pressed when a charge is held, the cooldown has ended and an enemy is in range."""
    s = _state(time=5.0)
    s.enemies = [_enemy(200.0, 0.0)]
    p = Player(pos=Vec2(0.0, 0.0))
    p.ultra_charges = 1
    p.ultra_cd_until = 0.0
    assert playtest.Bot(3).plan(p, s, config.ROOM_RADIUS).ultra is True, "charged and ready must fire"
    p.ultra_charges = 0
    assert playtest.Bot(3).plan(p, s, config.ROOM_RADIUS).ultra is False, "no charge, no Ultra"
    p.ultra_charges = 1
    p.ultra_cd_until = 9.0
    assert playtest.Bot(3).plan(p, s, config.ROOM_RADIUS).ultra is False, "cooldown must hold Ultra back"
    s.enemies = [_enemy(900.0, 0.0)]
    p.ultra_cd_until = 0.0
    assert playtest.Bot(3).plan(p, s, config.ROOM_RADIUS).ultra is False, "out of range enemies do not trigger Ultra"
    print("[PASS] test_bot_ultra_only_when_charged passed (charge, cooldown and range gate Ultra)")


def test_bot_collects_powerups_when_calm():
    """With no threat and no enemies the bot walks to a nearby power-up."""
    s = _state()
    s.powerups = [PowerUp(Vec2(100.0, 0.0), "heal")]
    plan = playtest.Bot(11).plan(Player(pos=Vec2(0.0, 0.0)), s, config.ROOM_RADIUS)
    assert plan.mode == "pickup", plan.mode
    assert plan.keys == (True, False, False, True), f"expected W+D (world +x), got {plan.keys}"
    print("[PASS] test_bot_collects_powerups_when_calm passed (walks east to a power-up 100 px away)")


def test_bot_moves_away_from_the_edge():
    """Near the room edge the bot steers back toward the centre."""
    s = _state()
    r = config.ROOM_RADIUS
    plan = playtest.Bot(5).plan(Player(pos=Vec2(r * 0.97, 0.0)), s, r)
    assert plan.mode in ("flee", "center"), plan.mode
    keys_vec = playtest._combo_vector(plan.keys)
    assert keys_vec.x < 0.0, f"expected movement toward the centre (-x), got keys {plan.keys}"
    print("[PASS] test_bot_moves_away_from_the_edge passed (edge pull points back toward the centre)")


def test_bot_decisions_depend_only_on_seed_and_state():
    """Two bots with the same seed make the same decisions over the same sequence of states."""
    def trace(seed):
        bot = playtest.Bot(seed)
        out = []
        for i in range(300):
            s = _state(time=i / 60.0)
            s.enemies = [_enemy(180.0 + 3.0 * (i % 7), 40.0 * ((i // 5) % 3))]
            plan = bot.plan(Player(pos=Vec2(0.0, 0.0)), s, config.ROOM_RADIUS)
            out.append((plan.keys, plan.dash, plan.ultra, plan.mode, round(plan.aim.x, 6), round(plan.aim.y, 6)))
        return out

    assert trace(42) == trace(42), "same seed must give the same decisions"
    print("[PASS] test_bot_decisions_depend_only_on_seed_and_state passed (300 steps identical for one seed)")


def test_report_format_is_documented():
    """Every key of the report, the options, the summary and a run record appears in the module docstring."""
    record = playtest._empty_record(1, "normal")
    report = playtest.build_report({"runs": 1, "difficulties": ["normal"], "seed_base": 1,
                                    "wave_limit": 1, "time_limit": 1.0}, [record], False)
    doc = playtest.__doc__
    soft = {"wave": 1, "game_time": 1.0, "enemies": 1, "last_progress_time": 0.0, "behaviors": {}}
    keys = set(report) | set(report["options"]) | set(report["summary"]) | set(record)
    keys |= {"type", "message", "where"} | set(soft)
    missing = sorted(k for k in keys if not re.search(rf"\b{re.escape(k)}\b", doc))
    assert not missing, f"undocumented report keys: {missing}"
    print(f"[PASS] test_report_format_is_documented passed ({len(keys)} report keys all in the module docstring)")


def test_failed_runs_make_the_report_not_ok():
    """A softlock, an invariant break or an error sets ok to false and names the seed."""
    base = playtest._empty_record(77, "hard")
    base["outcome"] = "game_over"
    ok_report = playtest.build_report({}, [dict(base)], False)
    assert ok_report["ok"] is True and ok_report["summary"]["failed_runs"] == []
    for outcome in ("softlock", "invariant", "error"):
        bad = dict(base, outcome=outcome)
        report = playtest.build_report({}, [bad], False)
        assert report["ok"] is False, outcome
        assert report["summary"]["failed_runs"] == [{"seed": 77, "difficulty": "hard", "outcome": outcome}]
    soft = dict(base, outcome="softlock", softlock={"wave": 3, "game_time": 90.0, "enemies": 2,
                                                    "last_progress_time": 30.0, "behaviors": {"chaser": 2}})
    assert playtest.build_report({}, [soft], False)["summary"]["softlock_seeds"] == [77]
    print("[PASS] test_failed_runs_make_the_report_not_ok passed (softlock, invariant and error all fail the report)")


def test_same_seed_same_report():
    """Same seed, same options: identical report, even with other seeds run in between."""
    game = _shared_game()
    hs_before = _file_hash(os.path.join(ROOT, "high_scores.json"))
    first = playtest.run_playtest(runs=1, difficulties=("normal",), seed_base=4242,
                                  wave_limit=2, time_limit=25.0, game=game)
    playtest.run_playtest(runs=1, difficulties=("normal",), seed_base=5150,
                          wave_limit=2, time_limit=25.0, game=game)
    again = playtest.run_playtest(runs=1, difficulties=("normal",), seed_base=4242,
                                  wave_limit=2, time_limit=25.0, game=game)
    a = json.dumps(first, indent=2, sort_keys=True)
    b = json.dumps(again, indent=2, sort_keys=True)
    assert a == b, "the same seed produced a different report"
    other = playtest.run_playtest(runs=1, difficulties=("normal",), seed_base=5150,
                                  wave_limit=2, time_limit=25.0, game=game)
    assert json.dumps(other["runs"], sort_keys=True) != json.dumps(first["runs"], sort_keys=True), \
        "a different seed must give a different run"
    assert _file_hash(os.path.join(ROOT, "high_scores.json")) == hs_before, "the playtest changed high_scores.json"
    assert first["ok"] is True, first["summary"]
    print("[PASS] test_same_seed_same_report passed (report bytes match for seed 4242 across runs; high scores untouched)")


def test_same_seed_same_report_across_processes():
    """The CLI writes identical bytes in two processes with different hash seeds."""
    outputs = []
    with tempfile.TemporaryDirectory(prefix="playtest-det-") as tmp:
        for hash_seed in ("1", "2"):
            out = os.path.join(tmp, f"report_{hash_seed}.json")
            env = dict(os.environ, PYTHONHASHSEED=hash_seed)
            cmd = [sys.executable, os.path.join(ROOT, "tools", "playtest.py"), "--runs", "1",
                   "--difficulties", "normal", "--seed-base", "4242", "--wave-limit", "2",
                   "--time-limit", "25", "--out", out]
            proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
            assert proc.returncode == 0, proc.stdout + proc.stderr
            with open(out, "rb") as fh:
                outputs.append(fh.read())
    assert outputs[0] == outputs[1], "reports differ between processes"
    print("[PASS] test_same_seed_same_report_across_processes passed (identical bytes under PYTHONHASHSEED 1 and 2)")


def test_cli_exit_codes_and_report_file():
    """A clean sweep exits 0 and writes the report; bad arguments exit 2 before any run starts."""
    with tempfile.TemporaryDirectory(prefix="playtest-cli-") as tmp:
        out = os.path.join(tmp, "report.json")
        code = playtest.main(["--runs", "1", "--difficulties", "normal", "--seed-base", "4242",
                              "--wave-limit", "2", "--time-limit", "20", "--out", out])
        assert code == 0, f"clean sweep returned {code}"
        with open(out, "r", encoding="utf-8") as fh:
            report = json.load(fh)
        assert report["format"] == "plouto-playtest" and report["ok"] is True
        assert len(report["runs"]) == 1
    import contextlib
    import io

    for bad in (["--difficulties", "nightmare"], ["--runs", "0"], ["--time-limit", "0"]):
        try:
            with contextlib.redirect_stderr(io.StringIO()):  # argparse prints its usage error here
                playtest.main(bad)
        except SystemExit as exc:
            assert exc.code == 2, f"{bad} exited {exc.code}"
        else:
            raise AssertionError(f"{bad} was accepted")
    print("[PASS] test_cli_exit_codes_and_report_file passed (exit 0 with a report, exit 2 on bad arguments)")


def test_mutators_are_recorded_when_present():
    """Mutator ids per run come from mutators.py (wave 1). Skipped while that module is absent."""
    try:
        import mutators  # noqa: F401
    except ModuleNotFoundError:
        print("[SKIP requires-wave1] test_mutators_are_recorded_when_present: mutators.py is not in this worktree")
        return
    from mutators import MUTATORS
    picked = playtest._mutator_ids_for_seed(9)
    assert picked == playtest._mutator_ids_for_seed(9), "mutator choice must be deterministic"
    assert set(picked) <= {m.id for m in MUTATORS} and len(picked) <= 2
    print(f"[PASS] test_mutators_are_recorded_when_present passed (seed 9 picks {picked})")


def test_pickups_and_actions_are_counted_by_kind():
    """A power-up that leaves the list was picked up, and the record counts it by kind, with Ultra and dashes."""
    from types import SimpleNamespace

    record = playtest._empty_record(4242, "normal")
    shield = PowerUp(Vec2(0.0, 0.0), "shield")
    heal = PowerUp(Vec2(5.0, 0.0), "heal")
    game = SimpleNamespace(state=SimpleNamespace(powerups=[heal]),
                           player=SimpleNamespace(ultra_charges=1, dash_charges=0))
    playtest._record_events(record, game, [shield, heal], before_ultra=2, before_dash=1)
    assert record["powerups_used"] == {"shield": 1}, record["powerups_used"]
    assert record["ultra_used"] == 1 and record["dashes"] == 1, record
    playtest._record_events(record, game, [heal], before_ultra=1, before_dash=0)
    assert record["powerups_used"] == {"shield": 1}, "a power-up still on the field is not a pickup"
    assert record["ultra_used"] == 1 and record["dashes"] == 1, "no change without a spend"
    print("[PASS] test_pickups_and_actions_are_counted_by_kind passed (pickups by kind, one Ultra and one dash counted)")


def test_boss_reward_menu_is_driven_through_keys():
    """The bot picks both reward stages with the menu's own keys and the game returns to play."""
    game = _shared_game()
    playtest._start_run(game, 77, "normal", None)
    game._roll_boss_rewards()
    game.fsm.set_state(GameStateName.BOSS_REWARD)
    record = playtest._empty_record(77, "normal")
    playtest._pick_reward(game, playtest.Bot(77), record)
    assert playtest._state_key(game.fsm.current_state) == GameStateName.PLAYING.value, "reward flow did not finish"
    assert len(record["rewards"]) == 1, record["rewards"]
    picked = record["rewards"][0]
    assert picked["temp"] and picked["perm"], f"both stages must pick a card: {picked}"
    print(f"[PASS] test_boss_reward_menu_is_driven_through_keys passed (picked temp {picked['temp']}, perm {picked['perm']})")


def _run_all():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in tests:
        fn()
    print(f"\nALL {len(tests)} BOTPLAYTEST CHECKS RAN")


if __name__ == "__main__":
    _run_all()
