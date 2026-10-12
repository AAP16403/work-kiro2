"""Regression tests for the wave1 gaps: the Guide elite score clause, boss reward cards that show
only real options (centred, no placeholders, zero candidates safe), one shared shield cap in the
desktop code, and the Game Over click sound during its input lock."""

import os
import re
import shutil
import tempfile

import pyglet

import config
import powerup
import rpg
import score as score_mod
import visuals
from game import Game
from powerup import PowerUp, apply_powerup
from states import GameOverState, GameStateName
from utils import Vec2
from weapons import WEAPONS

_KEY = pyglet.window.key
_LEFT = pyglet.window.mouse.LEFT
_TMP_DIR = tempfile.mkdtemp(prefix="plouto_w1_gaps_")
_REAL_SCORE_FILE = score_mod.HIGH_SCORE_FILE
_REVEAL_T = float(config.GAME_OVER_REVEAL_S)
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
_SKIP_DIRS = {"build", "dist", "__pycache__", "vercel_site"}
_LITERAL_120_SHIELD = re.compile(
    r"min\(\s*120\b[^)]*shield|shield[^\n]*min\(\s*120\b|_SHIELD\w*\s*=\s*120\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _temp_opts(n):
    return [dict(o) for o in rpg.TEMP_REWARD_POOL[:n]]


def _perm_opts(n):
    return [dict(o) for o in rpg.PERM_REWARD_POOL[:n]]


def _reward_menu(width=980, height=620):
    picks = []
    m = rpg.BossRewardMenu(
        width,
        height,
        lambda key, duration: picks.append(("temp", key, duration)),
        lambda key: picks.append(("perm", key)),
    )
    return m, picks


def _center(rect):
    x, y, w, h = rect
    return x + w / 2.0, y + h / 2.0


def _advance(g, seconds):
    # One deterministic 1/60 s frame per update, as the other swarm tests do.
    for _ in range(int(seconds * 60.0) + 2):
        g.update(1.0 / 60.0)


def _spy_audio(g):
    plays = []
    g.audio.play = lambda name, *a, **k: plays.append(name)
    return plays


def _desktop_py_files():
    for root, dirs, files in os.walk(_PROJECT_ROOT):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(".py") and not name.startswith("test_"):
                yield os.path.join(root, name)


# ---------------------------------------------------------------------------
# Guide: elite score clause
# ---------------------------------------------------------------------------

def test_guide_elites_entry_names_score_multiplier(g):
    clause = f"{float(config.ELITE_SCORE_MULT):g}x score"
    entry = next(e for e in g.guide_menu.BASICS_INFO if e["key"] == "elites")
    assert clause in entry["what"], entry["what"]
    # The number must come from config, so the literal text may not live in menu.py.
    with open(os.path.join(_PROJECT_ROOT, "menu.py"), "r", encoding="utf-8") as f:
        assert "2.5x score" not in f.read(), "elite score clause must be built from config.ELITE_SCORE_MULT"
    # The Basics tab draws the entry, so the clause must reach the rendered row text.
    m = g.guide_menu
    m.tab = "basics"
    idx = next(i for i, e in enumerate(m._entries()) if e["key"] == "elites")
    m.page = idx // m.rows_per_page
    g.switch_to()
    m.draw()
    desc = m._rows[idx % m.rows_per_page][7]
    assert clause in desc.text, desc.text
    assert desc.content_width <= m._desc_max_w, (desc.content_width, m._desc_max_w)
    print(f"[PASS] test_guide_elites_entry_names_score_multiplier passed (Elites row says '{clause}' and fits its row)")


def test_guide_rows_fit_their_width(g):
    m = g.guide_menu
    g.switch_to()
    checked = 0
    for tab in ("enemies", "powerups", "basics"):
        m.tab = tab
        m.page = 0
        for page in range(m._total_pages()):
            m.page = page
            m.draw()
            for row in m._rows[: len(m._page_entries())]:
                assert row[7].content_width <= m._desc_max_w + 1, (tab, page, row[7].text)
                checked += 1
    m.tab = "basics"
    m.page = 0
    print(f"[PASS] test_guide_rows_fit_their_width passed ({checked} guide rows fit their width)")


# ---------------------------------------------------------------------------
# Boss reward menu: real cards only, centred, zero candidates
# ---------------------------------------------------------------------------

def test_reward_cards_match_real_options(g):
    for n in (1, 2, 3):
        m, _ = _reward_menu()
        m.begin(_temp_opts(n), [])
        assert m._visible_count() == n, (n, m._visible_count())
        for i, card in enumerate(m._cards):
            shown = i < n
            assert card.active == shown and card.enabled == shown, (n, i)
            assert all(bool(part.visible) == shown for part in card._parts), (n, i)
        titles = [c.title.text for c in m._cards[:n]]
        assert all(titles) and "--" not in titles, titles
        assert not m._empty.visible
    print("[PASS] test_reward_cards_match_real_options passed (1, 2 and 3 options give 1, 2 and 3 real cards, no '--')")


def test_reward_stack_is_centred_for_each_count(g):
    for width, height in ((980, 620), (1920, 1080)):
        for n in (1, 2, 3):
            m, _ = _reward_menu(width, height)
            m.begin(_temp_opts(n), [])
            rects = [m._card_rect(i) for i in range(n)]
            stack_top = rects[0][1] + rects[0][3]
            stack_bottom = rects[-1][1]
            stack_mid = (stack_top + stack_bottom) / 2.0
            region_mid = m._card_region_top - m._avail_h / 2.0
            assert abs(stack_mid - region_mid) < 1.0, (width, n, stack_mid, region_mid)
            for x, _, w, h in rects:
                assert abs((x + w / 2.0) - width // 2) < 1.0, (width, n)
                assert abs(h - m._card_h) < 1e-6
            for a, b in zip(rects, rects[1:]):
                assert abs((a[1] - (b[1] + b[3])) - m._card_gap) < 1e-6
    print("[PASS] test_reward_stack_is_centred_for_each_count passed (1-3 cards centred at 980x620 and 1920x1080)")


def test_reward_menu_hides_unused_slots_when_drawn(g):
    m, _ = _reward_menu()
    m.begin(_temp_opts(1), [])
    g.switch_to()
    m.update(1.0 / 60.0)
    m.draw()
    assert all(bool(p.visible) for p in m._cards[0]._parts), "the real card must be drawn"
    for card in m._cards[1:]:
        assert not any(bool(p.visible) for p in card._parts), "unused slots must not be drawn"
    # Switching to the permanent step with two options re-shows the second slot and hides the third.
    m.begin(_temp_opts(3), _perm_opts(2))
    m.on_key_press(_KEY._1)
    m.on_key_press(_KEY.ENTER)
    assert m._stage == "perm"
    m.draw()
    assert [bool(c.active) for c in m._cards] == [True, True, False]
    assert not any(bool(p.visible) for p in m._cards[2]._parts)
    print("[PASS] test_reward_menu_hides_unused_slots_when_drawn passed (unused slots stay hidden through draw and stage change)")


def test_reward_keyboard_selection_with_fewer_cards(g):
    m, picks = _reward_menu()
    m.begin(_temp_opts(2), _perm_opts(1))
    assert m.on_key_press(_KEY._3) is None and m._selected is None, "key 3 has no card to pick"
    m.on_key_press(_KEY._2)
    assert m._selected == 1 and m._cards[1].selected
    assert m.on_key_press(_KEY.ENTER) is None
    assert picks == [("temp", rpg.TEMP_REWARD_POOL[1]["key"], rpg.TEMP_REWARD_POOL[1]["duration"])], picks
    assert m._stage == "perm"
    m.on_key_press(_KEY.NUM_1)
    assert m.on_key_press(_KEY.SPACE) == "done"
    assert picks[-1] == ("perm", rpg.PERM_REWARD_POOL[0]["key"]), picks
    print("[PASS] test_reward_keyboard_selection_with_fewer_cards passed (1-2 highlight and ENTER/SPACE confirm, key 3 ignored)")


def test_reward_mouse_selection_with_fewer_cards(g):
    m, picks = _reward_menu()
    m.begin(_temp_opts(2), _perm_opts(2))
    assert m.on_mouse_press(*_center(m._card_rect(0)), _LEFT) is None  # first temp card picked, stage moves on
    assert picks == [("temp", rpg.TEMP_REWARD_POOL[0]["key"], rpg.TEMP_REWARD_POOL[0]["duration"])], picks
    # Slot 3 has no card: a click where it would sit must do nothing.
    assert m.on_mouse_press(*_center(m._card_rect(2)), _LEFT) is None
    assert len(picks) == 1
    assert m.on_mouse_press(*_center(m._card_rect(1)), _LEFT) == "done"
    assert picks[-1] == ("perm", rpg.PERM_REWARD_POOL[1]["key"]), picks
    print("[PASS] test_reward_mouse_selection_with_fewer_cards passed (clicks hit the real cards and ignore empty slots)")


def test_reward_zero_candidates_do_not_crash(g):
    m, picks = _reward_menu()
    m.begin([], [])
    assert m._visible_count() == 0 and m._empty.visible
    assert "--" not in m._tip_text()
    g.switch_to()
    m.update(1.0 / 60.0)
    m.draw()
    assert all(not c.active for c in m._cards)
    # Keyboard path: empty temp step hands over to the permanent step, which then finishes the flow.
    assert m.on_key_press(_KEY.ENTER) is None and m._stage == "perm"
    assert m.on_key_press(_KEY.ENTER) == "done"
    # Mouse path with zero options on both steps.
    m.begin([], [])
    assert m.on_mouse_press(10.0, 10.0, _LEFT) is None and m._stage == "perm"
    assert m.on_mouse_press(10.0, 10.0, _LEFT) == "done"
    assert m.on_mouse_press(10.0, 10.0, pyglet.window.mouse.RIGHT) is None
    # Resize with zero options must also be safe.
    m.resize(1280, 720)
    m.draw()
    assert picks == []
    # A temp step with options followed by an empty permanent step still finishes cleanly.
    m.begin(_temp_opts(2), [])
    assert m.on_key_press(_KEY._1) is None and m.on_key_press(_KEY.ENTER) is None
    assert m._stage == "perm" and m._visible_count() == 0
    assert m.on_key_press(_KEY.ENTER) == "done"
    assert picks == [("temp", rpg.TEMP_REWARD_POOL[0]["key"], rpg.TEMP_REWARD_POOL[0]["duration"])], picks
    print("[PASS] test_reward_zero_candidates_do_not_crash passed (empty steps draw, skip with ENTER or click, and finish)")


# ---------------------------------------------------------------------------
# Shield cap
# ---------------------------------------------------------------------------

def test_no_literal_120_shield_cap_in_desktop_code(g):
    offenders = []
    checked = 0
    for path in _desktop_py_files():
        checked += 1
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, 1):
                if _LITERAL_120_SHIELD.search(line):
                    offenders.append(f"{os.path.relpath(path, _PROJECT_ROOT)}:{lineno}: {line.strip()}")
    assert checked > 20, checked
    assert not offenders, "literal 120 shield caps remain:\n" + "\n".join(offenders)
    print(f"[PASS] test_no_literal_120_shield_cap_in_desktop_code passed ({checked} desktop files, no literal 120 shield cap)")


def test_shield_caps_read_shield_max(g):
    assert rpg._SHIELD_CAP == config.SHIELD_MAX, (rpg._SHIELD_CAP, config.SHIELD_MAX)
    assert visuals.SHIELD_MAX == config.SHIELD_MAX, visuals.SHIELD_MAX
    g._init_game()
    p = g.player
    p.shield = config.SHIELD_MAX - 3
    rpg.apply_perm_reward(p, [], "perm_shield", 1.0)
    assert p.shield == config.SHIELD_MAX, p.shield

    # Weapon-fallback top-up reads the shared constant: with a larger cap it may go past 120.
    saved = powerup.SHIELD_MAX
    try:
        powerup.SHIELD_MAX = 150
        p.shield = 140
        p.current_weapon = WEAPONS["basic"]
        apply_powerup(p, PowerUp(Vec2(0.0, 0.0), "weapon", data="basic"), 0.0)
        assert p.shield == 150, f"weapon fallback must use SHIELD_MAX, got {p.shield}"
    finally:
        powerup.SHIELD_MAX = saved
    p.shield = config.SHIELD_MAX - 5
    p.current_weapon = WEAPONS["basic"]
    apply_powerup(p, PowerUp(Vec2(0.0, 0.0), "weapon", data="basic"), 0.0)
    assert p.shield == config.SHIELD_MAX, p.shield
    print("[PASS] test_shield_caps_read_shield_max passed (perm shield, weapon fallback and HUD cap follow config.SHIELD_MAX)")


# ---------------------------------------------------------------------------
# Game Over click sound
# ---------------------------------------------------------------------------

def test_game_over_accepts_input_only_after_reveal(g):
    fresh = GameOverState(g)
    assert fresh.accepts_input() is False, "a state that was never entered must not accept input"
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.state.time = 1.0
    g.score.score = 10
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP_DIR, "board_gap.json")
    g.fsm.set_state(GameStateName.GAME_OVER)
    gs = g.fsm.current_state
    assert isinstance(gs, GameOverState)
    assert gs.accepts_input() is False
    _advance(g, _REVEAL_T * 0.5)
    assert gs.accepts_input() is False
    _advance(g, _REVEAL_T * 0.6)
    assert gs.accepts_input() is True
    print("[PASS] test_game_over_accepts_input_only_after_reveal passed (input lock ends with the reveal)")


def test_game_over_click_silent_while_locked(g):
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP_DIR, "board_gap_click.json")
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.state.time = 1.0
    g.score.score = 10
    g.fsm.set_state(GameStateName.GAME_OVER)
    gs = g.fsm.current_state
    plays = _spy_audio(g)
    btn = g.game_over_menu.buttons[0]
    g.on_mouse_press(*_center((btn.x, btn.y, btn.width, btn.height)), _LEFT, 0)
    assert "ui_click" not in plays, plays
    assert g.fsm.current_state is gs, "a locked click must not start a new run"

    _advance(g, _REVEAL_T * 1.2)
    btn = g.game_over_menu.buttons[0]
    g.on_mouse_press(*_center((btn.x, btn.y, btn.width, btn.height)), _LEFT, 0)
    assert plays.count("ui_click") == 1, plays
    assert not isinstance(g.fsm.current_state, GameOverState), "Try Again must still work once armed"
    print("[PASS] test_game_over_click_silent_while_locked passed (no ui_click during the lock, click sound and Try Again after it)")


def run_all():
    # Keep every test off the real high_scores.json, which is tracked in git.
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP_DIR, "high_scores.json")
    g = Game()
    g.set_visible(False)
    g.switch_to()
    try:
        test_guide_elites_entry_names_score_multiplier(g)
        test_guide_rows_fit_their_width(g)
        test_reward_cards_match_real_options(g)
        test_reward_stack_is_centred_for_each_count(g)
        test_reward_menu_hides_unused_slots_when_drawn(g)
        test_reward_keyboard_selection_with_fewer_cards(g)
        test_reward_mouse_selection_with_fewer_cards(g)
        test_reward_zero_candidates_do_not_crash(g)
        test_no_literal_120_shield_cap_in_desktop_code(g)
        test_shield_caps_read_shield_max(g)
        test_game_over_accepts_input_only_after_reveal(g)
        test_game_over_click_silent_while_locked(g)
    finally:
        g.close()
        score_mod.HIGH_SCORE_FILE = _REAL_SCORE_FILE
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    print("\nALL W1 GAPS REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
