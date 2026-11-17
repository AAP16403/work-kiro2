"""Regression tests for the wave-3 final review fixes.

One group per fix. The high-severity fixes come first: replay, the audio hooks, the mutators, and the
splitter and reflector affixes. The medium fixes follow: the access settings write, the progress path,
the bench report, the HUD shine, the plain-language unlock text and the mutator balance table.

Every file these tests write goes to a temp folder. The real progress.json and replays/ are never touched.
"""

import datetime
import importlib
import json
import math
import os
import random
import sys
import tempfile

PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import pyglet  # noqa: E402

import access_prefs  # noqa: E402
import audio as audio_module  # noqa: E402
import audio_cues  # noqa: E402
import boss_rage  # noqa: E402
import config  # noqa: E402
import daily  # noqa: E402
import guide_info  # noqa: E402
import hangar_rules  # noqa: E402
import hud as hud_module  # noqa: E402
import level  # noqa: E402
import replay  # noqa: E402
import score as score_mod  # noqa: E402
import skins  # noqa: E402
from enemy import Enemy  # noqa: E402
from game import Game  # noqa: E402
from projectile import Projectile  # noqa: E402
from states import PlayingState  # noqa: E402
from utils import Vec2  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="w3_fix_")
DAY = datetime.date(2026, 10, 12)


def _isolate(game):
    """Every save the game can write goes to the temp folder for this run."""
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP, "board.json")
    replay.DEFAULT_PATH = os.path.join(_TMP, "last_run.json")
    game.progress_path = os.path.join(_TMP, "progress.json")


class _RecordAudio:
    """Stands in for the audio manager: keeps the name of every play() call, ignores everything else."""

    def __init__(self):
        self.names = []

    def play(self, name, volume=1.0, pitch_jitter=0.0, min_gap=0.0):
        self.names.append(name)

    def __getattr__(self, attr):
        return lambda *args, **kwargs: None


def _fresh_run(game, seed=7, mutators=()):
    replay.start_run(game, seed, "normal", mutators)
    return game.state


# ---------------------------------------------------------------------------
# High: replay was missing from the integrated tree
# ---------------------------------------------------------------------------

def test_replay_round_trip_is_exact(g):
    _isolate(g)

    def script(index, game):
        k = pyglet.window.key
        game.keys[k.D] = (index // 30) % 2 == 0
        game.keys[k.W] = (index // 30) % 2 == 1
        game.mouse_xy = (640 + 180 * math.cos(index * 0.07), 360 + 180 * math.sin(index * 0.07))
        game.mouse_down = True
        if index == 90:
            game._dash()

    recorded = replay.record_scripted(g, 99, "normal", (), 240, script)
    loaded = replay.Recording.from_json(json.loads(json.dumps(recorded.to_json())))
    result = replay.replay(g, loaded)
    assert result.ok and result.first_mismatch is None, f"replay diverged at step {result.first_mismatch}"
    assert result.hashes == recorded.hashes
    print("[PASS] test_replay_round_trip_is_exact passed (240 recorded steps replay with identical state hashes)")


def test_replay_is_off_unless_asked(g):
    _isolate(g)
    assert g.record_runs is False and g.recorder is None
    _fresh_run(g)
    assert g.recorder is None, "a run started without --record must not record"
    print("[PASS] test_replay_is_off_unless_asked passed (recording needs --record or record_runs=True)")


# ---------------------------------------------------------------------------
# High: 19 of the 21 new sound effects never played
# ---------------------------------------------------------------------------

def test_time_slow_end_plays_its_cue(g):
    _isolate(g)
    s = _fresh_run(g)
    rec = _RecordAudio()
    real_audio = g.audio
    g.audio = rec
    try:
        g.player.time_slow_until = s.time + 1.0
        g._fixed_step()  # the slow is on: the flag is set
        assert "time_slow_off" not in rec.names, rec.names
        g.player.time_slow_until = s.time + 1e-9  # ends on the next step
        g._fixed_step()
        assert "time_slow_off" in rec.names, f"time_slow_off not played at expiry: {rec.names}"
    finally:
        g.audio = real_audio
    print("[PASS] test_time_slow_end_plays_its_cue passed (time_slow_off plays when the slow expires)")


def test_boss_rage_plays_rage_warn(g):
    _isolate(g)
    _fresh_run(g)
    rec = _RecordAudio()
    real_audio = g.audio
    g.audio = rec
    try:
        boss = Enemy(pos=Vec2(0.0, 0.0), hp=10, speed=0.0, behavior="boss_womb_core", max_hp=100)
        boss.ai["max_hp"] = 100
        assert boss_rage.update_rage(boss, g) is True
    finally:
        g.audio = real_audio
    assert rec.names == ["rage_warn"], rec.names
    print("[PASS] test_boss_rage_plays_rage_warn passed (the rage start plays rage_warn, not boss_warn)")


def test_every_cue_has_a_call_site_in_project_code(g):
    import ast
    sites = set()
    for name in sorted(os.listdir(PROJECT_ROOT)):
        if not name.endswith(".py") or name.startswith("test_") or name == "audio_cues.py":
            continue
        with open(os.path.join(PROJECT_ROOT, name), "r", encoding="utf-8-sig") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                func = node.func
                if (isinstance(func, ast.Attribute) and func.attr == "cue") or (isinstance(func, ast.Name) and func.id == "cue"):
                    sites.add(node.args[1].value)
    played = sites | set(audio_cues.POWERUP_CUES.values()) | set(audio_cues.ELITE_DEATH_CUES.values())
    unplayed = sorted(set(audio_cues.CUE_SPECS) - played)
    assert not unplayed, f"cue names with no event hook: {unplayed}"
    print(f"[PASS] test_every_cue_has_a_call_site_in_project_code passed ({len(audio_cues.CUE_SPECS)} cues hooked)")


# ---------------------------------------------------------------------------
# High: mutators were absent from the integrated build
# ---------------------------------------------------------------------------

def test_mutators_are_in_the_build(g):
    import mutators
    assert [m.id for m in mutators.MUTATORS] == ["glass_cannon", "bullet_hell", "drift", "frenzy", "iron_man"]
    entries = guide_info.mutator_entries(mutators)
    assert len(entries) == 5 and all(e["what"].startswith("Score x") for e in entries), entries
    print("[PASS] test_mutators_are_in_the_build passed (five mutators, each with a Guide entry)")


def _tools_module(name):
    tools_dir = os.path.join(PROJECT_ROOT, "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    return importlib.import_module(name)


def test_balance_sim_reads_every_mutator(g):
    bs = _tools_module("balance_sim")
    rows, note = bs.mutator_rows(10, 0.28)
    assert note == "" and len(rows) == 5, (note, rows)
    glass = next(r for r in rows if r["id"] == "glass_cannon")
    assert glass["score_mult"] == 1.25 and "player_damage_mult 1.0 -> 1.5" in glass["change"], glass
    print("[PASS] test_balance_sim_reads_every_mutator passed (five rows; glass cannon shows its damage change)")


def test_daily_run_plays_its_own_mutator(g):
    _isolate(g)
    g.mutator_ids = ("drift",)  # the saved title selection must not leak into the daily run
    try:
        g._start_daily_run(today=DAY)
        picked = daily.daily_mutator(DAY.isoformat())
        assert g.run_mutators == (picked,), (g.run_mutators, picked)
        assert g.run_mutator_ids == (picked,)
    finally:
        g.daily_date = None
        g.run_mutator_ids = ()
        g.mutator_ids = ()
    print("[PASS] test_daily_run_plays_its_own_mutator passed (the day's single mutator, not the title selection)")


# ---------------------------------------------------------------------------
# High: splitter and reflector affixes never spawned or behaved
# ---------------------------------------------------------------------------

def test_both_new_affixes_spawn(g):
    rng = random.Random(2026)
    seen = {level._choose_affix(rng) for _ in range(400)}
    assert {"splitter", "reflector"} <= seen, f"affixes drawn: {sorted(seen)}"
    print("[PASS] test_both_new_affixes_spawn passed (splitter and reflector are drawn with the other affixes)")


def test_splitter_death_leaves_two_half_hp_copies(g):
    _isolate(g)
    s = _fresh_run(g)
    e = Enemy(pos=Vec2(260.0, 0.0), hp=0, speed=0.0, behavior="chaser", max_hp=40,
              is_elite=True, elite_affix="splitter")
    s.enemies = [e]
    PlayingState._kill_enemy(g, s, e)
    copies = [c for c in s.enemies if c is not e]
    assert len(copies) == int(config.ELITE_SPLIT_COUNT), f"{len(copies)} copies"
    for c in copies:
        assert c.hp == 20 and c.max_hp == 20, (c.hp, c.max_hp)
        assert c.elite_affix == "" and not c.is_elite, "a copy never splits again"
    print("[PASS] test_splitter_death_leaves_two_half_hp_copies passed (2 copies at 20 HP, no affix)")


def test_reflector_sends_the_first_shot_back(g):
    _isolate(g)
    s = _fresh_run(g)
    s.wave_active = True  # no new wave spawns during the two steps
    s.obstacles = []
    s.enemies = []
    s.projectiles = []
    e = Enemy(pos=Vec2(200.0, 0.0), hp=100, speed=0.0, behavior="chaser", max_hp=100,
              is_elite=True, elite_affix="reflector")
    e.attack_cd = 999.0
    e.ai["attack_mult"] = 1.0
    s.enemies.append(e)
    first = Projectile(Vec2(200.0, 0.0), Vec2(0.0, 0.0), 10, ttl=2.0, owner="player")
    first.prev_pos = Vec2(200.0, 0.0)
    s.projectiles.append(first)
    g._fixed_step()
    assert e.hp == 100, f"the reflected shot must not hurt the reflector ({e.hp})"
    back = [p for p in s.projectiles if p.owner == "enemy"]
    assert back and back[0].vel.x < 0, "the reflected shot flies back toward the player"
    # A second shot inside the cooldown is not reflected: it hurts the reflector.
    second = Projectile(Vec2(200.0, 0.0), Vec2(0.0, 0.0), 10, ttl=2.0, owner="player")
    second.prev_pos = Vec2(200.0, 0.0)
    s.projectiles.append(second)
    g._fixed_step()
    assert e.hp == 90, f"a shot inside the cooldown must hurt the reflector ({e.hp})"
    print("[PASS] test_reflector_sends_the_first_shot_back passed (first shot returned, second shot inside the cooldown hits)")


# ---------------------------------------------------------------------------
# Medium fixes
# ---------------------------------------------------------------------------

def test_access_settings_write_quarantines_a_corrupt_file(g):
    path = os.path.join(_TMP, "user_settings_access.json")
    for leftover in (path, path + ".corrupt-1", path + ".corrupt-2"):
        if os.path.exists(leftover):
            os.remove(leftover)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    real = audio_module._SETTINGS_PATH
    audio_module._SETTINGS_PATH = path
    try:
        access_prefs.save_access_settings({access_prefs.REDUCED_MOTION_KEY: True})
        assert os.path.exists(path + ".corrupt-1"), "the corrupt bytes must be kept, not overwritten"
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        assert data[access_prefs.REDUCED_MOTION_KEY] is True and "version" in data, data
        loaded = access_prefs.load_access_settings()
        assert loaded[access_prefs.REDUCED_MOTION_KEY] is True
    finally:
        audio_module._SETTINGS_PATH = real
    print("[PASS] test_access_settings_write_quarantines_a_corrupt_file passed (corrupt file kept as .corrupt-1, write versioned)")


def test_run_progress_goes_to_progress_path(g):
    _isolate(g)
    real_root = os.path.join(PROJECT_ROOT, "progress.json")
    before = os.path.exists(real_root) and os.path.getmtime(real_root)
    _fresh_run(g)
    g.progress_path = os.path.join(_TMP, "progress_run.json")
    if os.path.exists(g.progress_path):
        os.remove(g.progress_path)
    g._finish_meta_run()
    assert os.path.exists(g.progress_path), "a finished run must save through progress_path"
    after = os.path.exists(real_root) and os.path.getmtime(real_root)
    assert before == after, "the project-root progress.json must not be written by a test run"
    print("[PASS] test_run_progress_goes_to_progress_path passed (the run saved to the temp path only)")


def test_bench_out_writes_the_report(g):
    bench = _tools_module("bench")
    out = os.path.join(_TMP, "bench_report.json")
    cwd = os.getcwd()
    try:
        assert bench.main(["--wave", "2", "--frames", "3", "--repeats", "1", "--out", out]) == 0
    finally:
        os.chdir(cwd)
    with open(out, "r", encoding="utf-8") as fh:
        report = json.load(fh)
    assert report["results"] and len(report["results"]) == 1, report.get("results")
    assert 0 < len(report["top_cumulative"]) <= 15, len(report["top_cumulative"])
    assert all("function" in row and "cumulative_s" in row for row in report["top_cumulative"])
    print(f"[PASS] test_bench_out_writes_the_report passed ({len(report['top_cumulative'])} cProfile entries)")


def test_hud_shine_keeps_its_own_alpha(g):
    g.hud._frame("probe", 10, 10, 200, 50, 2)
    shapes_ = g.hud._frames["probe"]  # shadow [edge, body, shine], edge [...], fill [edge, body, shine]
    try:
        fill_body, fill_shine = shapes_[7], shapes_[8]
        assert fill_body.opacity == hud_module.PANEL_FILL_ALPHA, f"fill body opacity {fill_body.opacity}"
        assert fill_shine.opacity == 16, f"the fill shine was overwritten (opacity {fill_shine.opacity})"
    finally:
        for shp in g.hud._frames.pop("probe", []):
            shp.delete()
    print("[PASS] test_hud_shine_keeps_its_own_alpha passed (only the edge and body take the HUD alphas)")


def test_unlock_text_is_plain_words(g):
    for skin in skins.SKINS.values():
        text = hangar_rules.describe_unlock(skin, {})
        assert "UnlockRule(" not in text, text
        assert text == "Open from the start" or text.startswith("Unlock: "), text
    entries = guide_info.systems_entries({"skins": skins, "achievements": None, "mutators": None, "events": None})
    for e in entries:
        assert "UnlockRule(" not in e["deal"], e
    print(f"[PASS] test_unlock_text_is_plain_words passed ({len(skins.SKINS)} skins read as plain words)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_replay_round_trip_is_exact(g)
        test_replay_is_off_unless_asked(g)
        test_time_slow_end_plays_its_cue(g)
        test_boss_rage_plays_rage_warn(g)
        test_every_cue_has_a_call_site_in_project_code(g)
        test_mutators_are_in_the_build(g)
        test_balance_sim_reads_every_mutator(g)
        test_daily_run_plays_its_own_mutator(g)
        test_both_new_affixes_spawn(g)
        test_splitter_death_leaves_two_half_hp_copies(g)
        test_reflector_sends_the_first_shot_back(g)
        test_access_settings_write_quarantines_a_corrupt_file(g)
        test_run_progress_goes_to_progress_path(g)
        test_bench_out_writes_the_report(g)
        test_hud_shine_keeps_its_own_alpha(g)
        test_unlock_text_is_plain_words(g)
    finally:
        g.close()
    print("\nALL W3 FIX TESTS PASSED")


if __name__ == "__main__":
    run_all()
