"""Regression tests for the wave 1 final review fixes.

    mutators      title-screen chips save the selection, the run applies it once, enemies scale with it,
                  and the Game Over screen shows the combined multiplier (high severity, three findings)
    radius        per-frame shape radius writes are cached so an unchanged radius is not rewritten (medium)
    guide         the Guide's rows fit above the nav strip at 980x620 (medium)
    contract      the progress load/save contract names exist (medium)

Every test writes only to temp files: the settings file, progress.json and the high-score board.
"""

import json
import os
import random
import shutil
import tempfile

import pyglet

import audio
import level
import mutators
import progress as meta_progress
import score as score_mod
import visuals
from game import Game
from menu import GuideMenu
from states import GameStateName
from utils import Vec2

_LEFT = pyglet.window.mouse.LEFT
_TMP_DIR = tempfile.mkdtemp(prefix="plouto_w1_fix_")
_REAL_SETTINGS = audio._SETTINGS_PATH
_REAL_PROGRESS = meta_progress.PROGRESS_FILE
_REAL_SCORE_FILE = score_mod.HIGH_SCORE_FILE
_SETTINGS_PATH = os.path.join(_TMP_DIR, "user_settings.json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fresh_settings():
    """An empty temp settings file, so each test starts with no saved selection."""
    if os.path.exists(_SETTINGS_PATH):
        os.remove(_SETTINGS_PATH)
    return _SETTINGS_PATH


def _center(obj):
    return obj.x + obj.width / 2.0, obj.y + obj.height / 2.0


class _Radius:
    """A stand-in shape that counts radius writes."""

    def __init__(self, radius):
        self._radius = radius
        self.writes = 0

    @property
    def radius(self):
        return self._radius

    @radius.setter
    def radius(self, value):
        self._radius = value
        self.writes += 1


# ---------------------------------------------------------------------------
# Mutators (high severity)
# ---------------------------------------------------------------------------

def test_mutator_table_and_identity():
    assert set(mutators.MUTATORS) == {"bullet_hell", "drift", "frenzy", "glass_cannon", "iron_man"}, sorted(mutators.MUTATORS)
    assert mutators.combined(()) == mutators.Mods(), "no mutators must be the identity"
    assert mutators.combined(("drift",)).player_speed == 1.25
    frenzy = mutators.combined(("frenzy",))
    assert frenzy.player_fire_rate == 1.3 and frenzy.enemy_speed == 1.2, frenzy
    try:
        mutators.combined(("not_a_mutator",))
    except KeyError:
        pass
    else:
        raise AssertionError("an unknown mutator id must fail loudly")
    print("[PASS] test_mutator_table_and_identity passed (five mutators, identity with none, unknown ids raise)")


def test_selection_round_trips_and_keeps_other_keys():
    path = _fresh_settings()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"music_volume": 0.5, "sfx_volume": 0.25}, fh)
    assert mutators.save_selected_ids(("frenzy", "drift", "drift", "not_a_mutator"), path=path)
    assert mutators.load_selected_ids(path=path) == ("drift", "frenzy"), mutators.load_selected_ids(path=path)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["music_volume"] == 0.5 and data["sfx_volume"] == 0.25, "saving mutators must keep the audio keys"
    assert data[mutators.SETTINGS_KEY] == ["drift", "frenzy"], data
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert mutators.load_selected_ids(path=path) == (), "a broken settings file gives no selection"
    assert mutators.normalise_ids("drift") == (), "a bare string is not a selection"
    print("[PASS] test_selection_round_trips_and_keeps_other_keys passed (saved to user_settings.json, audio keys kept, bad file gives none)")


def test_title_chips_toggle_and_keep_the_four_actions(g):
    _fresh_settings()
    m = g.main_menu
    m._mutator_selected = set()
    m._sync_mutator_chips()
    g.switch_to()
    assert [b.text for b in m.buttons] == ["Start Game", "Guide", "Settings", "Quit"], [b.text for b in m.buttons]
    chips = dict(m._mutator_chips)
    assert set(chips) == set(mutators.MUTATORS), sorted(chips)

    x, y = _center(chips["drift"])
    assert m.on_mouse_press(x, y, _LEFT) is None, "a chip click is not a menu action"
    assert m.selected_mutator_ids() == ("drift",), m.selected_mutator_ids()
    assert mutators.load_selected_ids() == ("drift",), "the chip click must save the selection"
    m.on_mouse_press(x, y, _LEFT)
    assert m.selected_mutator_ids() == () and mutators.load_selected_ids() == (), "a second click clears it"

    assert m.on_mouse_press(*_center(m.buttons[0]), _LEFT) == "start_game", "Start Game keeps its action"
    print("[PASS] test_title_chips_toggle_and_keep_the_four_actions passed (chips toggle and save, four action buttons unchanged)")


def _select(g, ids):
    """Set the title-screen selection the way the chips do, without a click."""
    g.main_menu._mutator_selected = set(ids)
    g.main_menu._sync_mutator_chips()


def test_run_applies_the_selection_once(g):
    _fresh_settings()
    _select(g, ("drift", "frenzy"))
    g._init_game()
    assert g.run_mutator_ids == ("drift", "frenzy"), g.run_mutator_ids
    assert g.state.mutator_mods == mutators.combined(("drift", "frenzy")), g.state.mutator_mods
    assert abs(g._effective_player_speed() - g.player.speed * 1.25) < 1e-9, "Drift must raise player speed"
    assert abs(g._effective_player_fire_rate() - max(0.08, g.player.fire_rate / 1.3)) < 1e-9, "Frenzy must shorten the shot interval"

    # A stale saved file must not override what the chips show.
    mutators.save_selected_ids(())
    _select(g, ("drift",))
    g._init_game()
    assert g.run_mutator_ids == ("drift",), "the run must follow the chips, not an older saved file"

    _select(g, ())
    g._init_game()
    assert g.run_mutator_ids == () and g.state.mutator_mods == mutators.Mods()
    assert g._effective_player_speed() == g.player.speed, "no mutators must leave the player unchanged"
    print("[PASS] test_run_applies_the_selection_once passed (the chips' selection is applied in _init_game, Drift and Frenzy change the player, none is identity)")


def test_enemy_stats_follow_the_selection():
    base = level.GameState(difficulty="normal")
    base.init_rng(12345)
    base.wave = 2
    mut = level.GameState(difficulty="normal")
    mut.init_rng(12345)
    mut.wave = 2
    mut.mutator_mods = mutators.combined(("iron_man", "bullet_hell"))
    # The wave plan draws from the global random module, so seed it before each spawn to get the same enemies.
    random.seed(99)
    level.spawn_wave(base, Vec2(0.0, 0.0))
    random.seed(99)
    level.spawn_wave(mut, Vec2(0.0, 0.0))
    assert base.enemies and len(base.enemies) == len(mut.enemies), (len(base.enemies), len(mut.enemies))
    for eb, em in zip(base.enemies, mut.enemies):
        assert em.hp == int(round(eb.hp * 1.5)), (eb.hp, em.hp)
        assert abs(em.attack_cd - eb.attack_cd / 1.5) < 1e-9, (eb.attack_cd, em.attack_cd)
    print("[PASS] test_enemy_stats_follow_the_selection passed (Iron Man scales enemy HP, Bullet Hell shortens attack cooldown, same spawns)")


def test_game_over_shows_the_combined_multiplier(g):
    menu = g.game_over_menu
    menu.set_mutators(("drift", "frenzy"))
    assert menu.mutator_label.text == "Mutators: Drift, Frenzy  |  speed x1.25, fire rate x1.30, enemy speed x1.20", menu.mutator_label.text
    menu.set_mutators(())
    assert menu.mutator_label.text == "Mutators: none", menu.mutator_label.text

    # A real run: the selection is applied, and the Game Over screen reports it.
    _fresh_settings()
    _select(g, ("iron_man",))
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP_DIR, "board_w1_fix.json")
    meta_progress.PROGRESS_FILE = os.path.join(_TMP_DIR, "progress_w1_fix.json")
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.state.time = 1.0
    g.score.score = 10
    g.fsm.set_state(GameStateName.GAME_OVER)
    text = g.game_over_menu.mutator_label.text
    assert text == "Mutators: Iron Man  |  enemy HP x1.50", text
    print("[PASS] test_game_over_shows_the_combined_multiplier passed (Game Over names the mutators and their combined multiplier)")


# ---------------------------------------------------------------------------
# Radius cache (medium severity)
# ---------------------------------------------------------------------------

def test_radius_is_written_only_when_it_moves():
    s = _Radius(0.0)
    visuals._set_radius(s, 10.0)
    assert s.writes == 1 and s.radius == 10.0, (s.writes, s.radius)
    visuals._set_radius(s, 10.2)
    assert s.writes == 1, "a move below one step must not rewrite the radius"
    visuals._set_radius(s, 10.4)
    assert s.writes == 2 and s.radius == 10.5, (s.writes, s.radius)
    visuals._set_radius(s, 0.1)
    assert s.radius == visuals.RADIUS_STEP, "a positive radius must never be written as zero"
    print("[PASS] test_radius_is_written_only_when_it_moves passed (unchanged steps are skipped, positive radii never become zero)")


# ---------------------------------------------------------------------------
# Guide rows (medium severity)
# ---------------------------------------------------------------------------

def test_guide_rows_stay_above_the_nav_strip(g):
    m = GuideMenu(980, 620)
    g.switch_to()
    nav_top = m.btn_prev.y + m.btn_prev.height
    for tab in ("enemies", "powerups", "basics"):
        m.tab = tab
        for page in range(m._total_pages()):
            m.page = page
            for row in m._rows[: len(m._page_entries())]:
                bg = row[0]
                assert bg.y >= nav_top and bg.y + bg.height <= 620, (tab, page, bg.y, bg.height, nav_top)
    m.tab = "powerups"
    found = False
    for page in range(m._total_pages()):
        m.page = page
        keys = [e["key"] for e in m._page_entries()]
        if "homing" in keys:
            bg = m._rows[keys.index("homing")][0]
            assert bg.y >= nav_top and bg.y + bg.height <= 620, "the Homing entry must be fully on screen"
            found = True
    assert found, "Homing must appear on a page"
    print("[PASS] test_guide_rows_stay_above_the_nav_strip passed (every row at 980x620 sits above the nav strip, Homing included)")


# ---------------------------------------------------------------------------
# Contract names (medium severity)
# ---------------------------------------------------------------------------

def test_contract_names_for_progress_load_and_save():
    assert meta_progress.load_progress is meta_progress.load
    assert meta_progress.save_progress is meta_progress.save
    print("[PASS] test_contract_names_for_progress_load_and_save passed (load_progress and save_progress exist)")


def run_all():
    audio._SETTINGS_PATH = _SETTINGS_PATH
    meta_progress.PROGRESS_FILE = os.path.join(_TMP_DIR, "progress.json")
    score_mod.HIGH_SCORE_FILE = os.path.join(_TMP_DIR, "high_scores.json")
    try:
        test_mutator_table_and_identity()
        test_selection_round_trips_and_keeps_other_keys()
        test_radius_is_written_only_when_it_moves()
        test_contract_names_for_progress_load_and_save()

        g = Game()
        g.set_visible(False)
        g.switch_to()
        try:
            test_title_chips_toggle_and_keep_the_four_actions(g)
            test_run_applies_the_selection_once(g)
            test_enemy_stats_follow_the_selection()
            test_game_over_shows_the_combined_multiplier(g)
            test_guide_rows_stay_above_the_nav_strip(g)
        finally:
            g.close()
    finally:
        audio._SETTINGS_PATH = _REAL_SETTINGS
        meta_progress.PROGRESS_FILE = _REAL_PROGRESS
        score_mod.HIGH_SCORE_FILE = _REAL_SCORE_FILE
        shutil.rmtree(_TMP_DIR, ignore_errors=True)
    print("\nALL W1 FINAL FIX TESTS PASSED")


if __name__ == "__main__":
    run_all()
