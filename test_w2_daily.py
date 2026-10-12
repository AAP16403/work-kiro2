"""Wave 2 daily challenge: one seed and one mutator per local date, a best score per date, and the Game Over line.

Run from the worktree root with the project venv. Pure tests need no window. Tests that need the wave-1
modules (progress.py for the store, mutators.py for the pool) print [SKIP requires-wave1] when the module is
missing from the worktree, and the rest still run. Dates are always injected: daily.local_today is replaced
with a guard, so any test that reads the real clock fails.
"""

import datetime as dt
import importlib
import itertools
import json
import os
import random
import shutil
import tempfile

import pyglet

import daily
import score as score_mod
from daily import DailyResult
from game import Game
from menu import _GO_STAT_RGBA
from states import GameStateName

LEFT = pyglet.window.mouse.LEFT
DAY = dt.date(2026, 10, 12)
DAY_ISO = "2026-10-12"
# sha256("ploto-daily-v1|2026-10-12")[:8] read as a big-endian integer. Pinned so any change to the hash shows up.
DAY_SEED = 7166630417128988712
# Mutator ids as wave 1 names them, sorted. DAY_SEED % 5 == 2, so the pick for DAY_ISO is index 2.
POOL = ("bullet_hell", "drift", "frenzy", "glass_cannon", "iron_man")
DAY_MUTATOR = "frenzy"

_TMP_DIR = tempfile.mkdtemp(prefix="plouto_w2_daily_")
_REAL_SCORE_FILE = score_mod.HIGH_SCORE_FILE


def _no_clock():
    raise AssertionError("daily tests must inject a date; something read the local clock")


class _FixedTime:
    """Stands in for score.py's time module, which stamps high-score board entries. Keeps Game Over tests off the clock."""

    @staticmethod
    def strftime(fmt):
        return "2026-10-12 20:00"


def _have(module_name):
    try:
        importlib.import_module(module_name)
        return True
    except ImportError:
        return False


def _skip(test_name, module_name):
    print(f"[SKIP requires-wave1] {test_name}: {module_name}.py is not in this worktree")


_board_ids = itertools.count()


def _temp_board():
    """Point the high-score file at an empty temp board so no Game Over here touches the tracked high_scores.json."""
    path = os.path.join(_TMP_DIR, f"board_{next(_board_ids)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({}, f)
    score_mod.HIGH_SCORE_FILE = path
    return path


def _center(widget):
    return widget.x + widget.width / 2.0, widget.y + widget.height / 2.0


def _button(menu, text):
    return next(b for b in menu.buttons if b.text == text)


def _new_daily_run(g, date_iso=DAY_ISO, score_value=0, survived=0.0):
    g.daily_date = date_iso
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.state.time = float(survived)
    g.score.score = int(score_value)
    return g.state


def _end_run(g, score_value, wave=1):
    g.score.score = int(score_value)
    g.state.wave = int(wave)
    g.fsm.set_state(GameStateName.GAME_OVER)


def _result(**overrides):
    fields = dict(
        date_iso=DAY_ISO, run_score=800, run_wave=6, best_score=800, best_wave=6,
        previous_score=500, changed=True, new_best=True,
    )
    fields.update(overrides)
    return DailyResult(**fields)


# ---------------------------------------------------------------------------
# Seed and mutator (pure)
# ---------------------------------------------------------------------------

def test_seed_is_fixed_for_a_date():
    assert daily.daily_seed(DAY_ISO) == DAY_SEED, daily.daily_seed(DAY_ISO)
    assert daily.daily_seed(DAY.isoformat()) == daily.daily_seed(DAY_ISO), "same date, same seed"
    assert daily.daily_seed("2026-10-12") == DAY_SEED
    print("[PASS] test_seed_is_fixed_for_a_date passed (the date gives the pinned seed on every call)")


def test_seed_differs_between_dates():
    seeds = [daily.daily_seed((DAY + dt.timedelta(days=i)).isoformat()) for i in range(120)]
    assert len(set(seeds)) == len(seeds), "two different dates share a seed"
    assert all(0 <= s < 2 ** 64 for s in seeds), "seeds stay in 64 unsigned bits"
    print("[PASS] test_seed_differs_between_dates passed (120 consecutive dates, 120 distinct seeds)")


def test_bad_dates_are_refused():
    for bad in ("2026-13-01", "2026-1-5", "12/10/2026", "", "2026-02-30"):
        try:
            daily.daily_seed(bad)
        except ValueError:
            continue
        raise AssertionError(f"daily_seed accepted {bad!r}")
    print("[PASS] test_bad_dates_are_refused passed (non-ISO and impossible dates raise ValueError)")


def test_mutator_is_fixed_for_a_date():
    first = daily.daily_mutator(DAY_ISO, POOL)
    assert first == daily.daily_mutator(DAY.isoformat(), POOL), "same date, same mutator"
    assert first == DAY_MUTATOR, f"pinned pick for {DAY_ISO} should be {DAY_MUTATOR}, got {first}"
    print(f"[PASS] test_mutator_is_fixed_for_a_date passed ({DAY_ISO} picks {first} every time)")


def test_mutator_pool_is_reached_over_a_year():
    picks = {daily.daily_mutator((DAY + dt.timedelta(days=i)).isoformat(), POOL) for i in range(365)}
    assert picks == set(POOL), f"a year of dates should reach every mutator, got {sorted(picks)}"
    print("[PASS] test_mutator_pool_is_reached_over_a_year passed (365 dates reach all five mutators)")


def test_empty_pool_is_refused():
    try:
        daily.daily_mutator(DAY_ISO, ())
    except ValueError:
        print("[PASS] test_empty_pool_is_refused passed (no mutators to pick from raises ValueError)")
        return
    raise AssertionError("an empty pool must not return a mutator")


def test_mutator_pool_matches_mutators_module():
    if not _have("mutators"):
        return _skip("test_mutator_pool_matches_mutators_module", "mutators")
    mutators = importlib.import_module("mutators")
    assert daily.mutator_pool() == tuple(sorted(mutators.MUTATORS)), "daily pool must be exactly mutators.MUTATORS"
    assert daily.daily_mutator(DAY_ISO) in mutators.MUTATORS
    print("[PASS] test_mutator_pool_matches_mutators_module passed (pool is the sorted mutators.MUTATORS keys)")


def test_today_uses_the_injected_date():
    assert daily.today_iso(DAY) == DAY_ISO
    assert daily.today_iso(dt.date(2026, 1, 9)) == "2026-01-09", "dates are zero-padded"
    print("[PASS] test_today_uses_the_injected_date passed (today_iso returns the date it is given)")


# ---------------------------------------------------------------------------
# Record rules (pure, no file I/O)
# ---------------------------------------------------------------------------

def test_record_moves_only_on_a_strictly_higher_score():
    p = {}
    assert daily.record_daily(p, DAY_ISO, 500, 4) is True, "the first run of the day is stored"
    assert daily.record_daily(p, DAY_ISO, 500, 9) is False, "a tie keeps the existing record"
    assert daily.record_daily(p, DAY_ISO, 300, 9) is False, "a lower score keeps the existing record"
    assert p["daily"][DAY_ISO] == {"score": 500, "wave": 4}, p
    assert daily.record_daily(p, DAY_ISO, 501, 5) is True, "one point higher replaces the record"
    assert p["daily"][DAY_ISO] == {"score": 501, "wave": 5}, p
    assert daily.record_daily(p, "2026-10-13", 10, 1) is True, "another date has its own record"
    assert p["daily"][DAY_ISO]["score"] == 501, "other dates do not touch this one"
    print("[PASS] test_record_moves_only_on_a_strictly_higher_score passed (tie and lower keep it, higher replaces it)")


def test_record_run_reports_new_best_and_previous():
    p = {}
    first = daily.record_run(p, DAY_ISO, 250, 3)
    assert first.new_best and first.changed and first.previous_score is None
    assert (first.best_score, first.best_wave, first.run_score, first.run_wave) == (250, 3, 250, 3), first
    tie = daily.record_run(p, DAY_ISO, 250, 7)
    assert not tie.new_best and not tie.changed and tie.previous_score == 250
    assert (tie.best_score, tie.best_wave) == (250, 3), "a tie keeps the old wave too"
    up = daily.record_run(p, DAY_ISO, 400, 6)
    assert up.new_best and up.changed and up.previous_score == 250
    assert (up.best_score, up.best_wave) == (400, 6), up
    print("[PASS] test_record_run_reports_new_best_and_previous passed (first, tie and higher runs flagged correctly)")


def test_zero_point_first_run_is_stored_but_not_a_new_best():
    p = {}
    res = daily.record_run(p, DAY_ISO, 0, 1)
    assert res.changed and not res.new_best, "a 0-point first run fills the record without claiming a new best"
    assert daily.best_for_date(p, DAY_ISO) == {"score": 0, "wave": 1}
    print("[PASS] test_zero_point_first_run_is_stored_but_not_a_new_best passed (matches the high-score tie rules)")


def test_corrupt_daily_table_is_repaired():
    p = {"daily": "junk"}
    assert daily.record_daily(p, DAY_ISO, 90, 2) is True and isinstance(p["daily"], dict)
    p = {"daily": {DAY_ISO: "junk"}}
    assert daily.best_for_date(p, DAY_ISO) is None, "a non-dict entry reads as no record"
    assert daily.record_daily(p, DAY_ISO, 90, 2) is True, "a non-dict entry is replaced"
    assert daily.best_for_date(p, DAY_ISO) == {"score": 90, "wave": 2}
    print("[PASS] test_corrupt_daily_table_is_repaired passed (bad daily table and bad entry both recover)")


# ---------------------------------------------------------------------------
# Store round trip (needs the wave-1 progress.py store)
# ---------------------------------------------------------------------------

def test_settle_saves_only_when_the_record_changes():
    if not _have("progress"):
        return _skip("test_settle_saves_only_when_the_record_changes", "progress")
    path = os.path.join(_TMP_DIR, "progress_settle.json")
    if os.path.exists(path):
        os.remove(path)
    first = daily.settle_daily_run(DAY_ISO, 320, 4, path=path)
    assert first.new_best and first.changed
    with open(path, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert saved["daily"][DAY_ISO] == {"score": 320, "wave": 4}, saved
    with open(path, "rb") as f:
        before = f.read()
    lower = daily.settle_daily_run(DAY_ISO, 100, 2, path=path)
    assert not lower.changed and not lower.new_best and lower.best_score == 320
    with open(path, "rb") as f:
        assert f.read() == before, "a lower run must not rewrite progress.json"
    print("[PASS] test_settle_saves_only_when_the_record_changes passed (first run saved, lower run left the file alone)")


# ---------------------------------------------------------------------------
# Game wiring
# ---------------------------------------------------------------------------

def test_daily_run_seeds_the_run_rng(g):
    _new_daily_run(g)
    assert g.state.seed == DAY_SEED, f"run seed should be the daily seed, got {g.state.seed}"
    first_draw = g.state.rng.random()
    assert first_draw == random.Random(DAY_SEED).random(), "the run RNG must start from the daily seed"
    g._init_game()
    assert g.state.rng.random() == first_draw, "a retried daily run starts from the same RNG state"
    g.daily_date = "2026-10-13"
    g._init_game()
    assert g.state.seed == daily.daily_seed("2026-10-13") != DAY_SEED, "another date gets its own seed"
    g.daily_date = None
    print("[PASS] test_daily_run_seeds_the_run_rng passed (daily seed, same first draw on retry, other date differs)")


def test_retry_keeps_the_daily_and_menu_exit_clears_it(g):
    _new_daily_run(g)
    g.run_mutator_ids = (DAY_MUTATOR,)
    g._init_game()  # Try Again goes through _init_game
    assert g.daily_date == DAY_ISO and g.state.seed == DAY_SEED, "Try Again replays the same daily"
    g._return_to_menu()
    assert g.daily_date is None, "leaving to the menu ends the daily"
    assert g.run_mutator_ids == (), "leaving to the menu drops the daily mutator"
    print("[PASS] test_retry_keeps_the_daily_and_menu_exit_clears_it passed (retry keeps it, menu exit clears it)")


def test_daily_start_pins_exactly_one_mutator(g):
    if not _have("mutators"):
        return _skip("test_daily_start_pins_exactly_one_mutator", "mutators")
    g._start_daily_run(today=DAY)
    assert g.daily_date == DAY_ISO and g.state.seed == DAY_SEED
    assert g.run_mutator_ids == (daily.daily_mutator(DAY_ISO),), g.run_mutator_ids
    assert len(g.run_mutator_ids) == 1, "a daily run never stacks mutators"
    g._return_to_menu()
    print("[PASS] test_daily_start_pins_exactly_one_mutator passed (one mutator, the date's seed)")


def test_title_daily_button_returns_its_action(g):
    menu = g.main_menu
    menu.resize(980, 620)
    assert menu.on_mouse_press(*_center(_button(menu, "Daily Run")), LEFT) == "daily"
    expected = {"Start Game": "start_game", "Guide": "guide", "Settings": "settings", "Quit": "quit"}
    for label, action in expected.items():
        got = menu.on_mouse_press(*_center(_button(menu, label)), LEFT)
        assert got == action, f"{label} should still return {action}, got {got}"
    print("[PASS] test_title_daily_button_returns_its_action passed (Daily Run is \"daily\", the other four are unchanged)")


def test_title_daily_button_is_clear_of_the_subtitle(g):
    menu = g.main_menu
    try:
        for w, h in ((980, 620), (1920, 1080)):
            menu.resize(w, h)
            tops = [base_y + btn.height for (base_x, base_y), btn in zip(menu._button_base_positions, menu.buttons)]
            bottoms = [base_y for (base_x, base_y) in menu._button_base_positions]
            sub_bottom = menu.subtitle.y - menu.subtitle.content_height / 2.0
            assert sub_bottom > max(tops) + 4, f"subtitle collides with the top title button at {w}x{h}"
            assert menu._panel.y < min(bottoms), f"title panel does not wrap the lowest button at {w}x{h}"
            assert menu._panel.y + menu._panel.height > max(tops), f"title panel does not wrap the top button at {w}x{h}"
            assert min(bottoms) > 0, f"lowest title button falls off the screen at {w}x{h}"
    finally:
        menu.resize(g.width, g.height)
    print("[PASS] test_title_daily_button_is_clear_of_the_subtitle passed (6 title buttons fit under the subtitle at 980x620 and 1920x1080)")


# ---------------------------------------------------------------------------
# Game Over line
# ---------------------------------------------------------------------------

def test_game_over_line_wording(g):
    menu = g.game_over_menu
    menu.set_daily(_result())
    assert menu.daily_label.text == "DAILY 2026-10-12: NEW DAILY BEST 800 (wave 6)", menu.daily_label.text
    menu.set_daily(_result(run_score=300, run_wave=2, best_score=800, best_wave=6, previous_score=800, changed=False, new_best=False))
    assert menu.daily_label.text == "DAILY 2026-10-12: today's best 800 (wave 6). This run (300) did not beat it", menu.daily_label.text
    menu.set_daily(None)
    assert menu.daily_label.text == "", "no daily run, no daily line"
    print("[PASS] test_game_over_line_wording passed (new best, beaten-not-this-run and no-daily wording)")


def test_game_over_daily_line_fades_in_as_its_own_stage(g):
    menu = g.game_over_menu
    menu.set_daily(_result())
    menu.set_reveal(0.0, 1.0)
    assert menu.daily_label.opacity == 0, "the daily line starts hidden"
    menu.set_reveal(1.0, 1.0)
    assert menu.daily_label.opacity == _GO_STAT_RGBA[3], "the daily line is fully shown when the reveal ends"
    menu.set_daily(None)
    print("[PASS] test_game_over_daily_line_fades_in_as_its_own_stage passed (hidden at start, full at the end)")


def test_game_over_daily_line_has_its_own_row(g):
    menu = g.game_over_menu
    try:
        for w, h in ((980, 620), (1280, 720), (1920, 1080)):
            menu.resize(w, h)
            base = menu._base_y
            stats_h = menu.stats_labels[0].font_size * 0.75
            daily_h = menu.daily_label.font_size * 0.75
            btn0_top = menu._button_base_y[0] + menu.buttons[0].height
            assert base["stats"] - stats_h > base["daily"] + daily_h + 2, f"daily line collides with run stats at {w}x{h}"
            assert base["daily"] - daily_h > btn0_top + 2, f"daily line collides with Try Again at {w}x{h}"
    finally:
        menu.resize(g.width, g.height)
    print("[PASS] test_game_over_daily_line_has_its_own_row passed (daily line sits between run stats and the buttons at 3 sizes)")


def test_daily_game_over_records_the_day(g):
    if not _have("progress"):
        return _skip("test_daily_game_over_records_the_day", "progress")
    path = os.path.join(_TMP_DIR, "progress_game_over.json")
    if os.path.exists(path):
        os.remove(path)
    _temp_board()
    g.progress_path = path
    try:
        _new_daily_run(g)
        _end_run(g, 400)
        assert g.game_over_menu.daily_label.text == "DAILY 2026-10-12: NEW DAILY BEST 400 (wave 1)", g.game_over_menu.daily_label.text
        with open(path, "r", encoding="utf-8") as f:
            assert json.load(f)["daily"][DAY_ISO] == {"score": 400, "wave": 1}
        with open(path, "rb") as f:
            before = f.read()

        _new_daily_run(g)
        _end_run(g, 200)
        assert g.game_over_menu.daily_label.text == "DAILY 2026-10-12: today's best 400 (wave 1). This run (200) did not beat it", g.game_over_menu.daily_label.text
        with open(path, "rb") as f:
            assert f.read() == before, "a lower daily run must not rewrite the record"

        g.daily_date = None
        _new_daily_run_plain(g)
        _end_run(g, 999)
        assert g.game_over_menu.daily_label.text == "", "a normal run shows no daily line"
        with open(path, "rb") as f:
            assert f.read() == before, "a normal run must not write the daily record"
    finally:
        g.progress_path = None
    print("[PASS] test_daily_game_over_records_the_day passed (record stored on a new best, untouched by a lower or normal run)")


def _new_daily_run_plain(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)


# ---------------------------------------------------------------------------

def run_all():
    real_clock = daily.local_today
    real_score_time = score_mod._time
    daily.local_today = _no_clock  # nothing in this file may read the real date
    score_mod._time = _FixedTime()
    score_mod.HIGH_SCORE_FILE = _temp_board()
    g = Game()
    g.set_visible(False)
    try:
        test_seed_is_fixed_for_a_date()
        test_seed_differs_between_dates()
        test_bad_dates_are_refused()
        test_mutator_is_fixed_for_a_date()
        test_mutator_pool_is_reached_over_a_year()
        test_empty_pool_is_refused()
        test_mutator_pool_matches_mutators_module()
        test_today_uses_the_injected_date()
        test_record_moves_only_on_a_strictly_higher_score()
        test_record_run_reports_new_best_and_previous()
        test_zero_point_first_run_is_stored_but_not_a_new_best()
        test_corrupt_daily_table_is_repaired()
        test_settle_saves_only_when_the_record_changes()
        test_daily_run_seeds_the_run_rng(g)
        test_retry_keeps_the_daily_and_menu_exit_clears_it(g)
        test_daily_start_pins_exactly_one_mutator(g)
        test_title_daily_button_returns_its_action(g)
        test_title_daily_button_is_clear_of_the_subtitle(g)
        test_game_over_line_wording(g)
        test_game_over_daily_line_fades_in_as_its_own_stage(g)
        test_game_over_daily_line_has_its_own_row(g)
        test_daily_game_over_records_the_day(g)
    finally:
        g.close()
        daily.local_today = real_clock
        score_mod._time = real_score_time
        score_mod.HIGH_SCORE_FILE = _REAL_SCORE_FILE
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    print("\nALL WAVE 2 DAILY TESTS PASSED")


if __name__ == "__main__":
    run_all()
