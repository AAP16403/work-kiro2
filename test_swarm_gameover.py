"""Regression tests for the Game Over run summary, tie-safe high scores, keyboard replay and the staged reveal."""

import importlib.util
import itertools
import json
import math
import os
import shutil
import tempfile

import pyglet

import config
import progress as meta_progress
import score as score_mod
from game import Game
from score import ScoreTracker
from states import GameOverState, GameStateName, MenuState, PlayingState

_TMP_DIR = tempfile.mkdtemp(prefix="plouto_gameover_")
_REAL_SCORE_FILE = score_mod.HIGH_SCORE_FILE
_REAL_PROGRESS_FILE = meta_progress.PROGRESS_FILE
_board_ids = itertools.count()
_REVEAL_T = float(config.GAME_OVER_REVEAL_S)


def _set_board(scores, difficulty="normal"):
    """Point the high-score file at a temp board so these tests never touch the real high_scores.json."""
    path = os.path.join(_TMP_DIR, f"board_{next(_board_ids)}.json")
    entries = [
        {"score": int(s), "wave": 1, "kills": 0, "best_combo": 1.0, "date": "2026-01-01 00:00"}
        for s in scores
    ]
    with open(path, "w", encoding="utf-8") as f:
        json.dump({difficulty: entries}, f)
    score_mod.HIGH_SCORE_FILE = path
    return path


def _read_board(path, difficulty="normal"):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f).get(difficulty, [])


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _advance(g, seconds):
    # Drive update() directly, as test_polish does, so each call is one deterministic 1/60 s frame.
    for _ in range(int(math.ceil(seconds * 60.0)) + 1):
        g.update(1.0 / 60.0)


def _die(g, *, score_value=0, survived=0.0, kills=0, combo=1.0, board=()):
    """Start a run, give it stats, put them on a temp board, then end it through the real GAME_OVER state."""
    s = _new_run(g)
    _set_board(board)
    s.time = float(survived)
    g.score.score = int(score_value)
    g.score.kills = int(kills)
    g.score.best_combo = float(combo)
    g.fsm.set_state(GameStateName.GAME_OVER)
    return s


# ---------------------------------------------------------------------------
# High-score placement (no window needed)
# ---------------------------------------------------------------------------

def test_tie_with_top_score_is_not_new_high():
    _set_board([500, 300])
    t = ScoreTracker("normal")
    t.score = 500
    t.kills = 3
    assert t.submit_score(5) is False, "a run that ties the top score must not show NEW HIGH"
    assert t.last_rank == 2, f"tied run should land below the older entry, got rank {t.last_rank}"
    assert t.last_points_to_next == 1, f"a tie should read as one point to beat, got {t.last_points_to_next}"
    print("[PASS] test_tie_with_top_score_is_not_new_high passed (tie is not NEW HIGH, reads as +1 to beat #1)")


def test_zero_point_first_run_is_not_new_high():
    _set_board([])
    t = ScoreTracker("normal")
    t.score = 0
    assert t.submit_score(1) is False, "a 0-point first run must not show NEW HIGH"
    assert t.last_rank == 1 and t.last_points_to_next is None
    print("[PASS] test_zero_point_first_run_is_not_new_high passed (empty board, 0 points: no false NEW HIGH)")


def test_strict_best_is_new_high():
    path = _set_board([500])
    t = ScoreTracker("normal")
    t.score = 501
    assert t.submit_score(6) is True, "a strictly higher score must be NEW HIGH"
    assert t.last_rank == 1 and t.last_points_to_next is None
    assert _read_board(path)[0]["score"] == 501
    print("[PASS] test_strict_best_is_new_high passed (501 over 500 is NEW HIGH and ranks #1)")


def test_rank_and_points_to_next_on_board():
    path = _set_board([900, 700, 500, 300, 100])
    t = ScoreTracker("normal")
    t.score = 650
    assert t.submit_score(7) is False
    assert t.last_rank == 3, f"650 belongs at #3 on this board, got {t.last_rank}"
    assert t.last_points_to_next == 51, f"need 701 to pass #2 (700): 51 more than 650, got {t.last_points_to_next}"
    saved = _read_board(path)
    assert len(saved) == 5 and saved[-1]["score"] == 300, "board must stay capped at the top five"
    print("[PASS] test_rank_and_points_to_next_on_board passed (rank #3, 51 to beat the entry above)")


def test_off_board_run_reports_rank_zero():
    _set_board([900, 800, 700, 600, 500])
    t = ScoreTracker("normal")
    t.score = 100
    assert t.submit_score(2) is False
    assert t.last_rank == 0 and t.last_points_to_next is None
    print("[PASS] test_off_board_run_reports_rank_zero passed (below a full board: rank 0)")


def test_web_score_mirror_uses_same_tie_rules():
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "plouto_web_score", os.path.join(here, "vercel_site", "py", "score.py")
    )
    web = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(web)
    path = os.path.join(_TMP_DIR, f"web_board_{next(_board_ids)}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"normal": [{"score": 500, "wave": 1, "kills": 0, "best_combo": 1.0, "date": "x"}]}, f)
    web.HIGH_SCORE_FILE = path
    t = web.ScoreTracker("normal")
    t.score = 500
    assert t.submit_score(3) is False, "web mirror must not call a tie NEW HIGH"
    assert t.last_rank == 2 and t.last_points_to_next == 1
    t2 = web.ScoreTracker("normal")
    t2.score = 900
    assert t2.submit_score(4) is True and t2.last_rank == 1
    print("[PASS] test_web_score_mirror_uses_same_tie_rules passed (vercel_site score.py matches desktop)")


# ---------------------------------------------------------------------------
# Game Over screen content
# ---------------------------------------------------------------------------

def test_rank_label_wording(g):
    menu = g.game_over_menu
    cases = [
        (dict(rank=1, points_to_next=None, is_new_high=True), "RANK: NEW #1"),
        (dict(rank=1, points_to_next=None, is_new_high=False), "RANK: #1"),
        (dict(rank=2, points_to_next=1, is_new_high=False), "RANK: 1 to beat #1"),
        (dict(rank=3, points_to_next=51, is_new_high=False), "RANK: 51 to beat #2"),
        (dict(rank=0, points_to_next=None, is_new_high=False), "RANK: Off the board"),
    ]
    for kwargs, expected in cases:
        menu.set_run_stats(survived=65.0, kills=7, best_combo=3.5, **kwargs)
        assert menu.stats_labels[3].text == expected, f"{kwargs} -> {menu.stats_labels[3].text!r}"
    menu.set_run_stats(survived=65.0, kills=7, best_combo=3.5, rank=1, is_new_high=True)
    assert menu.stats_labels[0].text == "SURVIVED: 1:05"
    assert menu.stats_labels[1].text == "KILLS: 7"
    assert menu.stats_labels[2].text == "BEST COMBO: 3.5x"
    print("[PASS] test_rank_label_wording passed (NEW #1, N to beat #k, Off the board, stats formatting)")


def test_game_over_submits_and_shows_run_summary(g):
    _die(g, score_value=300, survived=125.0, kills=9, combo=2.5, board=())
    menu = g.game_over_menu
    assert menu.stats_labels[0].text == "SURVIVED: 2:05", menu.stats_labels[0].text
    assert menu.stats_labels[1].text == "KILLS: 9", menu.stats_labels[1].text
    assert menu.stats_labels[2].text == "BEST COMBO: 2.5x", menu.stats_labels[2].text
    assert menu.stats_labels[3].text == "RANK: NEW #1", menu.stats_labels[3].text
    assert menu.high_score_label.text == "High Score: 300"
    assert menu.new_high_label.text != "", "a first real score is NEW HIGH"
    saved = _read_board(score_mod.HIGH_SCORE_FILE)
    assert len(saved) == 1 and saved[0]["score"] == 300 and saved[0]["kills"] == 9
    print("[PASS] test_game_over_submits_and_shows_run_summary passed (time, kills, combo, rank, board saved)")


def test_zero_point_run_shows_no_new_high(g):
    _die(g, score_value=0, survived=4.0, board=())
    menu = g.game_over_menu
    assert menu.new_high_label.text == "", "a 0-point run must not show NEW HIGH"
    assert menu.stats_labels[3].text == "RANK: #1"
    assert menu.high_score_label.text == "High Score: 0"
    print("[PASS] test_zero_point_run_shows_no_new_high passed (no false NEW HIGH on a first 0-point run)")


def test_death_path_reaches_game_over_with_summary(g):
    _new_run(g)
    _set_board([50])
    g.score.score = 80
    g.player.hp = 0
    g.update(1.0 / 60.0)
    assert isinstance(g.fsm.current_state, GameOverState), "hp reaching zero must enter GAME_OVER"
    assert g.game_over_menu.high_score_label.text == "High Score: 80"
    assert g.game_over_menu.new_high_label.text != ""
    print("[PASS] test_death_path_reaches_game_over_with_summary passed (real death path submits the run)")


def test_hint_text_and_reveal_constant(g):
    assert g.game_over_menu.hint_label.text == "ENTER retry  |  ESC main menu"
    assert isinstance(config.GAME_OVER_REVEAL_S, float) and config.GAME_OVER_REVEAL_S > 0.0
    print("[PASS] test_hint_text_and_reveal_constant passed (control hint text and shared reveal length)")


# ---------------------------------------------------------------------------
# Input gating and keyboard replay
# ---------------------------------------------------------------------------

def test_input_locked_until_reveal_ends(g):
    _die(g, score_value=120, survived=20.0, kills=2, board=())
    gs = g.fsm.current_state
    assert isinstance(gs, GameOverState)
    key = pyglet.window.key

    g.on_key_press(key.ENTER, 0)
    g.on_key_press(key.R, 0)
    assert g.fsm.current_state is gs, "keys must be ignored while the reveal runs"
    btn = g.game_over_menu.buttons[0]
    g.on_mouse_press(btn.x + btn.width / 2, btn.y + btn.height / 2, pyglet.window.mouse.LEFT, 0)
    assert g.fsm.current_state is gs, "clicks must be ignored while the reveal runs"

    _advance(g, _REVEAL_T * 0.5)
    g.on_key_press(key.R, 0)
    assert g.fsm.current_state is gs, "a key pressed mid-reveal must not count"

    _advance(g, _REVEAL_T * 0.6)
    g.on_key_press(key.R, 0)
    assert isinstance(g.fsm.current_state, PlayingState), "R must replay once the reveal has ended"
    print("[PASS] test_input_locked_until_reveal_ends passed (keys and clicks blocked during the reveal)")


def test_keyboard_replay_with_enter_and_r(g):
    for key in (pyglet.window.key.ENTER, pyglet.window.key.R):
        old_state = _die(g, score_value=50, survived=3.0, board=())
        _advance(g, _REVEAL_T + 0.25)
        g.on_key_press(key, 0)
        assert isinstance(g.fsm.current_state, PlayingState), f"key {key} must start a new run"
        assert g.state is not old_state, "replay must build a fresh run state"
        assert g.score.score == 0 and g.score.kills == 0, "replay must reset the score"
    print("[PASS] test_keyboard_replay_with_enter_and_r passed (ENTER and R restart the run)")


def test_escape_and_m_return_to_menu(g):
    for key in (pyglet.window.key.ESCAPE, pyglet.window.key.M):
        _die(g, score_value=10, survived=2.0, board=())
        _advance(g, _REVEAL_T + 0.25)
        g.on_key_press(key, 0)
        assert isinstance(g.fsm.current_state, MenuState), f"key {key} must return to the main menu"
    print("[PASS] test_escape_and_m_return_to_menu passed (ESC and M go to the main menu)")


def test_held_key_cannot_auto_restart(g):
    key = pyglet.window.key.R
    g.keys.data[key] = True  # still held when the run ends (KeyStateHandler tracks held keys in .data)
    _die(g, score_value=40, survived=6.0, board=())
    _advance(g, _REVEAL_T + 0.25)
    g.on_key_press(key, 0)  # auto-repeat of the key that was already down
    assert isinstance(g.fsm.current_state, GameOverState), "a key held through death must not restart the run"
    g.keys.data[key] = False
    _advance(g, 0.05)  # the release is seen by a frame
    g.on_key_press(key, 0)
    assert isinstance(g.fsm.current_state, PlayingState), "a fresh press after release must restart the run"
    print("[PASS] test_held_key_cannot_auto_restart passed (held key blocked until released, then fresh press works)")


def test_mouse_click_locked_until_armed(g):
    _die(g, score_value=10, survived=1.0, board=())
    gs = g.fsm.current_state
    menu = g.game_over_menu
    _advance(g, _REVEAL_T * 0.9)
    btn = menu.buttons[0]
    g.on_mouse_press(btn.x + btn.width / 2, btn.y + btn.height / 2, pyglet.window.mouse.LEFT, 0)
    assert g.fsm.current_state is gs, "a click before the reveal ends must do nothing"
    _advance(g, _REVEAL_T * 0.3)
    btn = menu.buttons[0]
    g.on_mouse_press(btn.x + btn.width / 2, btn.y + btn.height / 2, pyglet.window.mouse.LEFT, 0)
    assert isinstance(g.fsm.current_state, PlayingState), "Try Again must work once input is armed"
    print("[PASS] test_mouse_click_locked_until_armed passed (clicks gated by the reveal, then Try Again works)")


# ---------------------------------------------------------------------------
# Staged reveal and layout
# ---------------------------------------------------------------------------

def test_reveal_timeline_and_count_up(g):
    _die(g, score_value=1000, survived=75.0, kills=12, combo=3.5, board=())
    menu = g.game_over_menu
    menu.set_reveal(0.0)
    assert menu.final_score_label.text == "Score: 0"
    assert menu.overlay.opacity == 0, "the frozen scene shows first, with no overlay"
    assert menu.title.opacity == 0 and menu.stats_labels[0].opacity == 0

    menu.set_reveal(_REVEAL_T * 0.2)
    assert menu.overlay.opacity == 0 and menu.title.opacity == 0, "nothing fades in during the frozen beat"

    menu.set_reveal(_REVEAL_T * 0.75)
    assert menu.final_score_label.text == "Score: 875", menu.final_score_label.text  # ease-out cubic at the midpoint of the count

    samples = []
    for i in range(0, 101):
        menu.set_reveal(_REVEAL_T * i / 100.0)
        samples.append(int(menu.final_score_label.text.split(":")[1].replace(",", "")))
    assert samples == sorted(samples), "the count-up must never go backwards"
    assert samples[-1] == 1000

    menu.set_reveal(_REVEAL_T)
    assert menu.final_score_label.text == "Score: 1,000"
    assert menu.overlay.opacity == 216 and menu.title.opacity == 255
    assert menu.stats_labels[3].opacity == 235
    assert all(abs(b.alpha - 1.0) < 1e-9 for b in menu.buttons), "buttons are fully shown when the reveal ends"
    print("[PASS] test_reveal_timeline_and_count_up passed (frozen beat, fades, monotonic count to 1,000)")


def test_count_text_is_written_only_on_change(g):
    _die(g, score_value=1000, survived=75.0, board=())
    menu = g.game_over_menu
    menu.set_reveal(_REVEAL_T * 0.75)
    shown_before = menu._shown_score
    menu.set_reveal(_REVEAL_T * 0.75 + 1e-6)  # same integer, so the text must not be rewritten
    assert menu._shown_score == shown_before
    assert menu.final_score_label.text == f"Score: {shown_before:,}"
    print("[PASS] test_count_text_is_written_only_on_change passed (displayed integer tracked, no rewrite churn)")


def test_new_high_pulse_offset(g):
    _die(g, score_value=500, board=[100])
    menu = g.game_over_menu
    assert menu.new_high_label.text != ""
    base = menu._base_y["new_high"]
    for t in (_REVEAL_T + 0.1, _REVEAL_T + 0.4, _REVEAL_T + 1.3):
        menu.set_reveal(t)
        offset = menu.new_high_label.y - base
        assert offset == int(round(4.0 * math.sin(t * 6.0))), f"pulse at t={t}: offset {offset}"
        assert abs(offset) <= 4
    print("[PASS] test_new_high_pulse_offset passed (NEW HIGH bobs with 4 * sin(6t), matching the web build)")


def test_reveal_survives_resize_without_drift(g):
    _die(g, score_value=500, board=[100])
    menu = g.game_over_menu
    menu.resize(980, 620)
    base_stats = menu._base_y["stats"]
    menu.set_reveal(_REVEAL_T * 0.7)
    mid_y = menu.stats_labels[0].y
    menu.set_reveal(_REVEAL_T * 0.7)
    assert menu.stats_labels[0].y == mid_y, "re-driving the same time must not drift the labels"
    menu.set_reveal(_REVEAL_T)
    assert menu.stats_labels[0].y == base_stats
    menu.resize(1280, 720)
    menu.resize(980, 620)
    menu.set_reveal(_REVEAL_T)
    assert menu.stats_labels[0].y == base_stats, "resizing must restore the resting position exactly"
    menu.resize(g.width, g.height)
    print("[PASS] test_reveal_survives_resize_without_drift passed (base positions stored, no offset drift)")


def test_game_over_layout_has_no_collisions(g):
    menu = g.game_over_menu
    try:
        for w, h in ((980, 620), (1280, 720), (1920, 1080)):
            menu.resize(w, h)
            base = menu._base_y
            stats_h = menu.stats_labels[0].font_size * 0.75
            new_h = menu.new_high_label.font_size * 0.75
            high_h = menu.high_score_label.font_size * 0.75
            hint_h = menu.hint_label.font_size * 0.75
            btn0_top = menu._button_base_y[0] + menu.buttons[0].height
            btn1_bottom = menu._button_base_y[1]

            # Top to bottom: High Score, NEW HIGH (pulse up to 4 px), run stats, Try Again.
            assert base["high"] - high_h > base["new_high"] + new_h + 4, f"High Score collides with NEW HIGH at {w}x{h}"
            assert base["new_high"] - new_h - 4 > base["stats"] + stats_h, f"NEW HIGH collides with run stats at {w}x{h}"
            assert base["stats"] - stats_h > btn0_top, f"run stats collide with the buttons at {w}x{h}"
            assert base["hint"] + hint_h < btn1_bottom, f"control hint overlaps the lower button at {w}x{h}"
            assert base["hint"] - hint_h > 0, f"control hint falls off the screen at {w}x{h}"

            # Estimated width of the longest rank text must stay on screen at the outer column.
            longest = "RANK: 1,250 to beat #12"
            col_w = int(200 * min(max(1.0, w) / 980.0, max(1.0, h) / 620.0, 1.6))
            font = menu.stats_labels[3].font_size
            half_text = 0.55 * font * len(longest) / 2.0
            outer_right = w // 2 + int(1.5 * col_w) + half_text
            assert outer_right < w, f"rank text runs off the right edge at {w}x{h}"
    finally:
        menu.resize(g.width, g.height)
    print("[PASS] test_game_over_layout_has_no_collisions passed (stats, NEW HIGH, High Score and buttons clear at 980x620, 1280x720, 1920x1080)")


def run_all():
    # Keep every test on a temp board: the real high_scores.json is tracked in git.
    score_mod.HIGH_SCORE_FILE = _set_board([])
    # Game Over ends the run through progress.end_run; keep that write off the developer's progress.json.
    meta_progress.PROGRESS_FILE = os.path.join(_TMP_DIR, "progress.json")
    test_tie_with_top_score_is_not_new_high()
    test_zero_point_first_run_is_not_new_high()
    test_strict_best_is_new_high()
    test_rank_and_points_to_next_on_board()
    test_off_board_run_reports_rank_zero()
    test_web_score_mirror_uses_same_tie_rules()

    g = Game()
    g.set_visible(False)
    try:
        test_rank_label_wording(g)
        test_game_over_submits_and_shows_run_summary(g)
        test_zero_point_run_shows_no_new_high(g)
        test_death_path_reaches_game_over_with_summary(g)
        test_hint_text_and_reveal_constant(g)
        test_input_locked_until_reveal_ends(g)
        test_keyboard_replay_with_enter_and_r(g)
        test_escape_and_m_return_to_menu(g)
        test_held_key_cannot_auto_restart(g)
        test_mouse_click_locked_until_armed(g)
        test_reveal_timeline_and_count_up(g)
        test_count_text_is_written_only_on_change(g)
        test_new_high_pulse_offset(g)
        test_reveal_survives_resize_without_drift(g)
        test_game_over_layout_has_no_collisions(g)
    finally:
        g.close()
        score_mod.HIGH_SCORE_FILE = _REAL_SCORE_FILE
        meta_progress.PROGRESS_FILE = _REAL_PROGRESS_FILE
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    print("\nALL GAME OVER SWARM REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
