"""Regression tests for meta progression: the progress.json store, the skin catalogue,
achievements, and the single save at the end of a run.

Every write goes to a temp folder, and the high-score board is pointed at a temp file too,
so the real progress.json and high_scores.json are never touched.
"""

import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pyglet

import achievements
import progress
import score as score_mod
import skins
from achievements import RunStats
from enemy import Enemy
from game import Game
from states import GameStateName, MenuState, PlayingState
from utils import Vec2


_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_TMP_DIR = None
_ids = itertools.count()
_REQUIRED_ACHIEVEMENTS = (
    "first_blood", "boss_hunter", "no_damage_wave", "elite_slayer", "combo_6x", "survive_ten_waves",
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_dir():
    path = os.path.join(_TMP_DIR, f"case_{next(_ids)}")
    os.makedirs(path)
    return path


def _file_in_fresh_dir(name="progress.json"):
    return os.path.join(_fresh_dir(), name)


def _write(path, text):
    """Write a text file, or raw bytes when ``text`` is bytes."""
    if isinstance(text, bytes):
        with open(path, "wb") as fh:
            fh.write(text)
    else:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def _stats(**fields):
    """A run dict in the RunStats.to_dict() shape, with every key present."""
    run = {
        "kills": 0, "elite_kills": 0, "boss_kills": 0, "hits_taken": 0, "damage_taken": 0,
        "waves_cleared": 0, "perfect_waves": 0, "best_combo": 1.0, "wave": 0,
        "score": 0, "survived_s": 0.0,
    }
    run.update(fields)
    return run


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Call update() directly, as test_polish does, so each call is one deterministic 1/60 s frame.
    for _ in range(frames):
        g.dispatch_events()
        g.update(1.0 / 60.0)


class _SaveCounter:
    """Wraps progress.save so a test can count writes without changing what is written."""

    def __init__(self):
        self.calls = []
        self._real = progress.save

    def __enter__(self):
        def counting(data, path=None):
            self.calls.append(path)
            return self._real(data, path)
        progress.save = counting
        return self

    def __exit__(self, *exc):
        progress.save = self._real
        return False


# ---------------------------------------------------------------------------
# progress.py: load, corrupt files, atomic save
# ---------------------------------------------------------------------------

def test_missing_or_corrupt_file_loads_defaults():
    assert progress.load(os.path.join(_fresh_dir(), "absent.json")) == progress.default_progress()
    cases = {
        "truncated": '{"best_wave": 4',
        "garbage": "\x00\x01 not json at all",
        "json list": "[1, 2, 3]",
        "empty": "",
    }
    for label, text in cases.items():
        path = _file_in_fresh_dir()
        _write(path, text)
        assert progress.load(path) == progress.default_progress(), f"{label} file must load as defaults"
    binary = _file_in_fresh_dir()
    _write(binary, b"\xff\xfe\x00\x9f")
    assert progress.load(binary) == progress.default_progress(), "non-UTF-8 bytes must load as defaults"
    print("[PASS] test_missing_or_corrupt_file_loads_defaults passed (missing, truncated, garbage, list, empty and binary files)")


def test_bad_fields_fall_back_one_by_one():
    path = _file_in_fresh_dir()
    _write(path, (
        '{"best_wave": -3, "best_score": true, "total_kills": "lots", "bosses_defeated": NaN, '
        '"runs_played": 4, "unlocked_skins": "ember", '
        '"achievements": ["first_blood", 7, "first_blood", ""], "selected_skin": 12}'
    ))
    data = progress.load(path)
    assert data["best_wave"] == 0 and data["best_score"] == 0, "negative and boolean counts must reset to 0"
    assert data["total_kills"] == 0 and data["bosses_defeated"] == 0, "string and NaN counts must reset to 0"
    assert data["runs_played"] == 4, "a valid count must survive next to bad ones"
    assert data["unlocked_skins"] == [], "a non-list skin list must reset to empty"
    assert data["achievements"] == ["first_blood"], "non-string and duplicate ids must be dropped"
    assert data["selected_skin"] == skins.DEFAULT_SKIN_ID, "a non-string selection must reset to the default"
    print("[PASS] test_bad_fields_fall_back_one_by_one passed (each bad field resets alone, valid ones survive)")


def test_save_then_load_round_trip():
    path = _file_in_fresh_dir()
    data = progress.default_progress()
    progress.apply_run(data, _stats(kills=12, boss_kills=1, wave=8, score=4321))
    data["unlocked_skins"] = ["classic", "ember"]
    data["achievements"] = ["first_blood"]
    data["selected_skin"] = "ember"
    assert progress.save(data, path) is True
    assert progress.load(path) == data, "a saved record must load back unchanged"
    print("[PASS] test_save_then_load_round_trip passed (every field survives save and load)")


def test_failed_write_keeps_previous_file_intact():
    d = _fresh_dir()
    path = os.path.join(d, "progress.json")
    good = progress.default_progress()
    good["best_score"] = 1234
    assert progress.save(good, path) is True
    before = _read(path)

    real_dump = json.dump

    def broken_dump(obj, fh, **kwargs):
        fh.write('{"best_score": ')  # part of the new record reaches the temp file, then the write fails
        raise OSError("simulated disk failure")

    bad = progress.default_progress()
    bad["best_score"] = 99999
    json.dump = broken_dump
    try:
        ok = progress.save(bad, path)
    finally:
        json.dump = real_dump
    assert ok is False, "a failed write must report False"
    assert _read(path) == before, "the previous progress.json must be untouched by a failed write"
    assert progress.load(path)["best_score"] == 1234
    leftovers = [f for f in os.listdir(d) if f != "progress.json"]
    assert leftovers == [], f"a failed write must remove its temp file, found {leftovers}"
    print("[PASS] test_failed_write_keeps_previous_file_intact passed (old file kept, temp file removed)")


def test_save_writes_temp_file_then_replaces():
    d = _fresh_dir()
    path = os.path.join(d, "progress.json")
    calls = []
    real_replace = os.replace

    def spy(src, dst):
        calls.append((src, dst))
        return real_replace(src, dst)

    os.replace = spy
    try:
        assert progress.save(progress.default_progress(), path) is True
    finally:
        os.replace = real_replace
    assert len(calls) == 1, "exactly one replace per save"
    src, dst = calls[0]
    assert dst == path, "the replace must target progress.json"
    assert os.path.dirname(src) == d, "the temp file must sit beside the target so the replace is a same-volume rename"
    assert os.path.basename(src).startswith(".progress-") and src.endswith(".tmp"), f"unexpected temp name {src}"
    assert sorted(os.listdir(d)) == ["progress.json"], "no temp file may remain after a good save"
    print("[PASS] test_save_writes_temp_file_then_replaces passed (temp file in the same folder, then os.replace)")


def test_failed_replace_cleans_up_and_keeps_old_file():
    d = _fresh_dir()
    path = os.path.join(d, "progress.json")
    assert progress.save(progress.default_progress(), path) is True
    before = _read(path)

    real_replace = os.replace

    def refuse(src, dst):
        raise PermissionError("simulated file lock")

    os.replace = refuse
    try:
        assert progress.save(progress.apply_run(progress.default_progress(), _stats(kills=5)), path) is False
    finally:
        os.replace = real_replace
    assert _read(path) == before, "a locked target must keep the old content"
    assert sorted(os.listdir(d)) == ["progress.json"], "the temp file must be removed when the replace fails"
    print("[PASS] test_failed_replace_cleans_up_and_keeps_old_file passed (PermissionError -> False, no temp left)")


def test_save_never_raises():
    d = _fresh_dir()
    assert progress.save(progress.default_progress(), os.path.join(d, "no_such_dir", "progress.json")) is False
    unserialisable = progress.default_progress()
    unserialisable["extra"] = object()
    path = os.path.join(d, "progress.json")
    assert progress.save(unserialisable, path) is False, "an unserialisable record must report False, not raise"
    assert sorted(os.listdir(d)) == [], "a refused save must leave no file behind"
    print("[PASS] test_save_never_raises passed (missing folder and unserialisable record both return False)")


def test_import_has_no_side_effects():
    before = os.stat(progress.PROGRESS_FILE) if os.path.exists(progress.PROGRESS_FILE) else None
    probe = _fresh_dir()
    env = dict(os.environ)
    env["PYTHONPATH"] = _PROJECT_ROOT + os.pathsep + env.get("PYTHONPATH", "")
    code = "import progress, skins, achievements; print('imported')"
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=probe, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0 and "imported" in result.stdout, result.stderr
    assert os.listdir(probe) == [], "importing the meta modules must not write files in the working folder"
    after = os.stat(progress.PROGRESS_FILE) if os.path.exists(progress.PROGRESS_FILE) else None
    assert (before is None) == (after is None), "importing must not create progress.json"
    if before is not None:
        assert before.st_mtime == after.st_mtime and before.st_size == after.st_size, "importing must not modify progress.json"
    print("[PASS] test_import_has_no_side_effects passed (fresh interpreter imports with no file writes)")


# ---------------------------------------------------------------------------
# skins.py
# ---------------------------------------------------------------------------

def test_catalogue_has_eight_valid_skins():
    assert len(skins.SKINS) >= 8, f"need at least 8 skins, found {len(skins.SKINS)}"
    ids = [s.id for s in skins.SKINS.values()]
    assert len(set(ids)) == len(ids), "skin ids must be unique"
    assert skins.DEFAULT_SKIN_ID in ids
    for s in skins.SKINS.values():
        assert s.name and "\n" not in s.description and s.description, f"{s.id}: name and one-line description required"
        assert set(s.palette.keys()) == set(skins.PALETTE_KEYS), f"{s.id}: palette keys must match PALETTE_KEYS"
        for key, rgb in s.palette.items():
            assert isinstance(rgb, tuple) and len(rgb) == 3, f"{s.id}.{key} must be an RGB tuple"
            assert all(isinstance(c, int) and 0 <= c <= 255 for c in rgb), f"{s.id}.{key} out of range: {rgb}"
    try:
        import player_art  # present once the player-art item lands; keys must then agree
    except ImportError:
        player_art = None
    if player_art is not None and hasattr(player_art, "DEFAULT_PALETTE"):
        assert set(player_art.DEFAULT_PALETTE.keys()) == set(skins.PALETTE_KEYS), "palette keys must match player_art.DEFAULT_PALETTE"
    print(f"[PASS] test_catalogue_has_eight_valid_skins passed ({len(skins.SKINS)} skins, unique ids, full RGB palettes)")


def test_default_skin_is_unlocked_and_selected():
    p = progress.default_progress()
    assert skins.unlocked(p, skins.DEFAULT_SKIN_ID) is True
    assert skins.selected(p).id == skins.DEFAULT_SKIN_ID
    print("[PASS] test_default_skin_is_unlocked_and_selected passed (classic is open on a fresh record)")


def test_unlock_rules_at_their_thresholds():
    cases = [
        # (skin id, progress field, threshold)
        ("ember", "best_score", 5000),
        ("crimson", "best_score", 25000),
        ("frost", "best_wave", 10),
        ("verdant", "total_kills", 250),
        ("solar", "bosses_defeated", 2),
        ("storm", "bosses_defeated", 5),
    ]
    for skin_id, field, threshold in cases:
        p = progress.default_progress()
        p[field] = threshold - 1
        assert skins.unlocked(p, skin_id) is False, f"{skin_id} must stay locked at {field}={threshold - 1}"
        p[field] = threshold
        assert skins.unlocked(p, skin_id) is True, f"{skin_id} must unlock at {field}={threshold}"
    p = progress.default_progress()
    assert skins.unlocked(p, "void") is False
    p["achievements"] = ["combo_6x"]
    assert skins.unlocked(p, "void") is True, "an achievement rule unlocks when that achievement is held"
    print("[PASS] test_unlock_rules_at_their_thresholds passed (score, wave, kills, bosses and achievement rules)")


def test_locked_skin_is_refused():
    p = progress.default_progress()
    assert skins.select(p, "ember") is False, "a locked skin must be refused"
    assert p["selected_skin"] == skins.DEFAULT_SKIN_ID, "a refused select must change nothing"
    assert skins.selected(p).id == skins.DEFAULT_SKIN_ID
    assert skins.select(p, "no_such_skin") is False, "an unknown skin must be refused"
    assert skins.get("no_such_skin") is None and skins.get(None) is None
    print("[PASS] test_locked_skin_is_refused passed (locked and unknown skins refused, selection unchanged)")


def test_unlocked_skin_can_be_selected_and_persists():
    path = _file_in_fresh_dir()
    p = progress.default_progress()
    p["best_score"] = 6000
    assert skins.select(p, "ember") is True
    assert skins.selected(p).id == "ember"
    assert progress.save(p, path)
    assert skins.selected(progress.load(path)).id == "ember", "the chosen skin must survive a reload"
    print("[PASS] test_unlocked_skin_can_be_selected_and_persists passed (selection saved and reloaded)")


def test_selected_falls_back_when_saved_skin_is_locked():
    p = progress.default_progress()
    p["selected_skin"] = "ember"  # saved while unlocked, now locked (for example after a bad file edit)
    assert skins.selected(p).id == skins.DEFAULT_SKIN_ID
    print("[PASS] test_selected_falls_back_when_saved_skin_is_locked passed (locked choice falls back to the default)")


def test_refresh_unlocks_records_each_skin_once():
    p = progress.default_progress()
    p["best_score"] = 5000
    first = skins.refresh_unlocks(p)
    assert "classic" in first and "ember" in first, f"classic and ember should be recorded, got {first}"
    assert "crimson" not in first
    assert skins.refresh_unlocks(p) == [], "a second refresh must report nothing new"
    print("[PASS] test_refresh_unlocks_records_each_skin_once passed (classic and ember recorded, then no repeats)")


def test_unlock_hints_are_one_line():
    for s in skins.SKINS.values():
        hint = skins.unlock_hint(s)
        assert hint and "\n" not in hint, f"{s.id} needs a one-line hint"
    assert skins.unlock_hint(skins.get("ember")) == "Score 5,000 in one run"
    print("[PASS] test_unlock_hints_are_one_line passed (every skin has a one-line unlock hint)")


# ---------------------------------------------------------------------------
# achievements.py
# ---------------------------------------------------------------------------

def test_catalogue_has_about_twenty_with_required_ids():
    n = len(achievements.ACHIEVEMENTS)
    assert 18 <= n <= 24, f"about 20 achievements expected, found {n}"
    ids = [a.id for a in achievements.ACHIEVEMENTS]
    assert len(set(ids)) == n, "achievement ids must be unique"
    for required in _REQUIRED_ACHIEVEMENTS:
        assert required in ids, f"missing required achievement {required}"
    for a in achievements.ACHIEVEMENTS:
        assert a.name and a.description and "\n" not in a.description
    for s in skins.SKINS.values():
        if s.unlock.kind == "achievement":
            assert achievements.get(s.unlock.value) is not None, f"{s.id} refers to an unknown achievement"
    print(f"[PASS] test_catalogue_has_about_twenty_with_required_ids passed ({n} achievements, required ids present)")


def test_evaluate_reports_each_achievement_once():
    p = progress.default_progress()
    new = achievements.evaluate(_stats(kills=1), p)
    assert new == ["first_blood"], f"only first blood should fire, got {new}"
    assert "first_blood" in p["achievements"]
    assert achievements.evaluate(_stats(kills=1), p) == [], "an earned achievement must not be reported again"
    print("[PASS] test_evaluate_reports_each_achievement_once passed (first blood marked, then silent)")


def test_run_achievement_conditions():
    cases = [
        ("elite_slayer", _stats(elite_kills=5), _stats(elite_kills=4)),
        ("giant_slayer", _stats(boss_kills=1), _stats(boss_kills=0)),
        ("no_damage_wave", _stats(perfect_waves=1), _stats(perfect_waves=0)),
        ("combo_6x", _stats(best_combo=6.0), _stats(best_combo=5.75)),
        ("combo_max", _stats(best_combo=8.0), _stats(best_combo=7.75)),
        ("survive_ten_waves", _stats(waves_cleared=10), _stats(waves_cleared=9)),
        ("massacre", _stats(kills=50), _stats(kills=49)),
        ("marathon", _stats(survived_s=300.0), _stats(survived_s=299.0)),
        ("five_digits", _stats(score=10000), _stats(score=9999)),
        ("stellar_score", _stats(score=50000), _stats(score=49999)),
        ("into_the_deep", _stats(wave=10), _stats(wave=9)),
        ("edge_of_stars", _stats(wave=30), _stats(wave=29)),
    ]
    for ach_id, earned_run, short_run in cases:
        assert ach_id in achievements.evaluate(earned_run, progress.default_progress()), f"{ach_id} must fire at its threshold"
        assert ach_id not in achievements.evaluate(short_run, progress.default_progress()), f"{ach_id} must not fire below it"
    print(f"[PASS] test_run_achievement_conditions passed ({len(cases)} run-based thresholds checked)")


def test_total_achievement_conditions():
    p = progress.default_progress()
    p.update({"total_kills": 100, "bosses_defeated": 3, "runs_played": 10})
    new = achievements.evaluate(_stats(), p)
    for expected in ("centurion", "boss_hunter", "veteran"):
        assert expected in new, f"{expected} must fire from lifetime totals, got {new}"
    assert "exterminator" not in new and "bossbreaker" not in new
    print("[PASS] test_total_achievement_conditions passed (centurion, boss hunter and veteran from totals)")


def test_run_stats_hooks_count_correctly():
    run = RunStats()
    run.on_kill()
    run.on_kill(elite=True, combo=1.5)
    run.on_kill(boss=True, combo=1.25)  # combo never drops within the object
    assert (run.kills, run.elite_kills, run.boss_kills) == (3, 1, 1)
    assert run.best_combo == 1.5

    run.on_wave_clear(1)
    assert (run.waves_cleared, run.perfect_waves) == (1, 1), "a clear with no hits is perfect"
    run.on_player_hit(10)
    run.on_player_hit(0)  # a shield-absorbed hit still counts as a hit taken
    assert (run.hits_taken, run.damage_taken) == (2, 10)
    run.on_wave_clear(2)
    assert (run.waves_cleared, run.perfect_waves) == (2, 1), "a clear after a hit is not perfect"
    run.on_wave_clear(3)
    assert run.perfect_waves == 2, "a clear with no hits since the last clear is perfect again"

    run.finish(score=900, wave=4, survived=61.5, best_combo=2.0)
    run.finish(score=1, wave=1, survived=1.0)  # only the first finish counts
    d = run.to_dict()
    assert (d["score"], d["wave"], d["survived_s"]) == (900, 4, 61.5)
    print("[PASS] test_run_stats_hooks_count_correctly passed (kills, bosses, elites, combo, perfect waves, finish once)")


# ---------------------------------------------------------------------------
# End-of-run merge and save (no window needed)
# ---------------------------------------------------------------------------

def test_apply_run_merges_totals_and_bests():
    p = progress.default_progress()
    progress.apply_run(p, _stats(kills=10, boss_kills=1, wave=7, score=1200))
    progress.apply_run(p, _stats(kills=5, boss_kills=0, wave=3, score=9000))
    progress.apply_run(p, _stats(kills=2, boss_kills=0, wave=5, score=400))
    assert p["runs_played"] == 3
    assert p["total_kills"] == 17
    assert p["bosses_defeated"] == 1
    assert p["best_wave"] == 7, "best wave keeps the highest value"
    assert p["best_score"] == 9000, "best score keeps the highest value"
    print("[PASS] test_apply_run_merges_totals_and_bests passed (totals add up, bests only go up)")


def test_end_run_saves_once_and_persists():
    path = _file_in_fresh_dir()
    run = RunStats()
    run.on_kill()
    run.on_kill(elite=True, combo=1.5)
    run.on_wave_clear(1)
    run.finish(score=1500, wave=2, survived=42.0, best_combo=1.5)
    with _SaveCounter() as counter:
        summary = progress.end_run(run, path)
    assert len(counter.calls) == 1, f"a run must save exactly once, saw {len(counter.calls)}"
    assert summary["saved"] is True
    stored = progress.load(path)
    assert stored["runs_played"] == 1 and stored["total_kills"] == 2
    assert stored["best_score"] == 1500 and stored["best_wave"] == 2
    assert "first_blood" in summary["new_achievements"] and "first_blood" in stored["achievements"]
    assert "classic" in summary["new_skins"] and "classic" in stored["unlocked_skins"]
    print("[PASS] test_end_run_saves_once_and_persists passed (one write, totals stored, achievement and default skin recorded)")


def test_end_run_unlocks_skin_on_disk():
    path = _file_in_fresh_dir()
    run = RunStats()
    run.finish(score=6000, wave=3, survived=90.0)
    summary = progress.end_run(run, path)
    assert "ember" in summary["new_skins"], "a 6000-point run must unlock Ember Pod"
    assert skins.unlocked(progress.load(path), "ember") is True
    print("[PASS] test_end_run_unlocks_skin_on_disk passed (score unlock written to progress.json)")


def test_end_run_summary_when_save_fails():
    path = _file_in_fresh_dir()
    run = RunStats()
    run.finish(score=10, wave=1, survived=1.0)
    real_replace = os.replace

    def refuse(src, dst):
        raise OSError("simulated write failure")

    os.replace = refuse
    try:
        summary = progress.end_run(run, path)
    finally:
        os.replace = real_replace
    assert summary["saved"] is False and not os.path.exists(path), "a failed save is reported, not raised"
    print("[PASS] test_end_run_summary_when_save_fails passed (failed write reported through the summary)")


# ---------------------------------------------------------------------------
# Game hooks (needs the hidden window)
# ---------------------------------------------------------------------------

def test_kill_hook_counts_kills_bosses_and_elites(g):
    s = _new_run(g)
    boss = Enemy(pos=Vec2(40.0, 0.0), hp=0, speed=0.0, behavior="boss_brute", max_hp=100)
    elite = Enemy(pos=Vec2(-40.0, 0.0), hp=0, speed=0.0, behavior="chaser", is_elite=True)
    s.enemies = [boss, elite]
    PlayingState._kill_enemy(g, s, boss)
    PlayingState._kill_enemy(g, s, elite)
    PlayingState._kill_enemy(g, s, boss)  # the death guard means a second call counts nothing
    run = g.run_stats
    assert (run.kills, run.boss_kills, run.elite_kills) == (2, 1, 1), (run.kills, run.boss_kills, run.elite_kills)
    assert abs(run.best_combo - 1.5) < 1e-9, f"combo after two kills should be 1.5, got {run.best_combo}"
    print("[PASS] test_kill_hook_counts_kills_bosses_and_elites passed (boss and elite kills counted once each, combo carried)")


def test_damage_hook_counts_every_landed_hit(g):
    _new_run(g)
    run = g.run_stats
    g.player.shield = 0
    g.player.invincibility_timer = 0.0
    hp_before = g.player.hp
    g._damage_player(10)
    assert (run.hits_taken, run.damage_taken) == (1, 10), (run.hits_taken, run.damage_taken)
    g.player.invincibility_timer = 0.0
    g.player.shield = 50
    hp_mid = g.player.hp
    g._damage_player(10)  # fully absorbed by the shield, still a hit taken
    assert (run.hits_taken, run.damage_taken) == (2, 20), (run.hits_taken, run.damage_taken)
    assert g.player.hp == hp_mid and hp_mid == hp_before - 10
    print("[PASS] test_damage_hook_counts_every_landed_hit passed (HP hits and shield-absorbed hits both counted)")


def test_wave_clear_hook_tracks_perfect_waves(g):
    s = _new_run(g)
    run = g.run_stats
    s.enemies = []
    s.wave_active = True
    _tick(g, 2)
    assert (run.waves_cleared, run.perfect_waves) == (1, 1), (run.waves_cleared, run.perfect_waves)

    g.player.invincibility_timer = 0.0
    g.player.shield = 0
    g._damage_player(5)
    s.enemies = []
    s.wave_active = True
    _tick(g, 2)
    assert (run.waves_cleared, run.perfect_waves) == (2, 1), "a wave that took a hit is not perfect"

    s.enemies = []
    s.wave_active = True
    _tick(g, 2)
    assert (run.waves_cleared, run.perfect_waves) == (3, 2)
    print("[PASS] test_wave_clear_hook_tracks_perfect_waves passed (clears counted, hit breaks the perfect streak)")


def test_run_end_saves_progress_exactly_once(g):
    before = progress.load()
    with _SaveCounter() as counter:
        _new_run(g)
        _tick(g, 60)  # one live second of play
        assert counter.calls == [], "nothing may be written while the run is live"
        g.fsm.set_state(GameStateName.GAME_OVER)
        assert len(counter.calls) == 1, "the run must be saved as it ends"
        _tick(g, 120)  # the game-over screen keeps ticking
        assert len(counter.calls) == 1, "later frames must not write again"
        assert g._finish_meta_run() is None, "a finished run must not be saved twice"
        assert len(counter.calls) == 1
    after = progress.load()
    assert after["runs_played"] == before["runs_played"] + 1, "exactly one run added to the record"
    print("[PASS] test_run_end_saves_progress_exactly_once passed (no writes while live, one write at game over)")


def test_pause_quit_saves_the_run_once(g):
    _new_run(g)
    g.fsm.set_state(GameStateName.PAUSED)
    before = progress.load()
    real_press = g.pause_menu.on_mouse_press
    g.pause_menu.on_mouse_press = lambda x, y, button: "quit_to_menu"
    with _SaveCounter() as counter:
        try:
            g.fsm.current_state.on_mouse_press(0, 0, pyglet.window.mouse.LEFT, 0)
        finally:
            g.pause_menu.on_mouse_press = real_press
    assert isinstance(g.fsm.current_state, MenuState), "quit to menu must still reach the menu"
    assert len(counter.calls) == 1, "quitting a live run from pause must save it once"
    assert progress.load()["runs_played"] == before["runs_played"] + 1
    print("[PASS] test_pause_quit_saves_the_run_once passed (pause-quit counts as a run end, saved once)")


def test_window_close_saves_an_active_run(g):
    _new_run(g)
    before = progress.load()
    g._schedule_app_close = lambda: None  # keep the test window open
    try:
        with _SaveCounter() as counter:
            g.on_close()
            g.on_close()
    finally:
        del g._schedule_app_close
    assert len(counter.calls) == 1, "closing mid-run saves once, and a second close does not"
    assert progress.load()["runs_played"] == before["runs_played"] + 1
    print("[PASS] test_window_close_saves_an_active_run passed (closing mid-run keeps the run's progress)")


def run_all():
    global _TMP_DIR
    _TMP_DIR = tempfile.mkdtemp(prefix="plouto_meta_")
    real_progress_file = progress.PROGRESS_FILE
    real_board = score_mod.HIGH_SCORE_FILE
    progress.PROGRESS_FILE = os.path.join(_TMP_DIR, "progress.json")
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP_DIR, "high_scores.json")
    try:
        test_missing_or_corrupt_file_loads_defaults()
        test_bad_fields_fall_back_one_by_one()
        test_save_then_load_round_trip()
        test_failed_write_keeps_previous_file_intact()
        test_save_writes_temp_file_then_replaces()
        test_failed_replace_cleans_up_and_keeps_old_file()
        test_save_never_raises()
        test_import_has_no_side_effects()
        test_catalogue_has_eight_valid_skins()
        test_default_skin_is_unlocked_and_selected()
        test_unlock_rules_at_their_thresholds()
        test_locked_skin_is_refused()
        test_unlocked_skin_can_be_selected_and_persists()
        test_selected_falls_back_when_saved_skin_is_locked()
        test_refresh_unlocks_records_each_skin_once()
        test_unlock_hints_are_one_line()
        test_catalogue_has_about_twenty_with_required_ids()
        test_evaluate_reports_each_achievement_once()
        test_run_achievement_conditions()
        test_total_achievement_conditions()
        test_run_stats_hooks_count_correctly()
        test_apply_run_merges_totals_and_bests()
        test_end_run_saves_once_and_persists()
        test_end_run_unlocks_skin_on_disk()
        test_end_run_summary_when_save_fails()

        g = Game()
        g.set_visible(False)
        try:
            test_kill_hook_counts_kills_bosses_and_elites(g)
            test_damage_hook_counts_every_landed_hit(g)
            test_wave_clear_hook_tracks_perfect_waves(g)
            test_run_end_saves_progress_exactly_once(g)
            test_pause_quit_saves_the_run_once(g)
            test_window_close_saves_an_active_run(g)
        finally:
            g.close()
    finally:
        progress.PROGRESS_FILE = real_progress_file
        score_mod.HIGH_SCORE_FILE = real_board
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    print("\nALL WAVE 1 META TESTS PASSED")


if __name__ == "__main__":
    run_all()
