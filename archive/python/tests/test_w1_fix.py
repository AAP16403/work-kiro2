"""Regression tests for the wave 1 final review fixes.

    mutators      title-screen chips save the selection, the run applies it once, enemies scale with it,
                  and the Game Over screen shows the combined multiplier (high severity, three findings)
    radius        per-frame shape radius writes are cached so an unchanged radius is not rewritten (medium)
    guide         the Guide's rows fit above the nav strip at 980x620 (medium)
    contract      the progress load/save contract names exist (medium)

The mutator tests use the contract API of mutators.py (wave-3 integration): the selection is
mutators.save_selection / load_selection, the rules are mutators.apply_mutators, and the title chips
are menu.MutatorChipRow. The wave-1 names they used before (save_selected_ids, combined, Mods,
_mutator_chips) no longer exist in the merged build.

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


def _chip_centre(chip):
    return chip.x + chip.w / 2.0, chip.y + chip.h / 2.0


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
    ids = {m.id for m in mutators.MUTATORS}
    assert ids == {"bullet_hell", "drift", "frenzy", "glass_cannon", "iron_man"}, sorted(ids)
    assert mutators.apply_mutators(()) == mutators.RunRules(), "no mutators must be the stock rules"
    assert mutators.apply_mutators(("drift",)).player_accel == mutators.DRIFT_ACCEL
    frenzy = mutators.apply_mutators(("frenzy",))
    assert frenzy.enemy_speed_mult == mutators.FRENZY_ENEMY_SPEED_MULT, frenzy
    assert frenzy.spawn_size_mult == mutators.FRENZY_SPAWN_SIZE_MULT, frenzy
    # Contract (wave 3): an unknown id is ignored rather than raised, so a stale save cannot crash a run.
    assert mutators.apply_mutators(("not_a_mutator",)) == mutators.RunRules(), "an unknown id must be ignored"
    print("[PASS] test_mutator_table_and_identity passed (five mutators, stock rules with none, unknown ids ignored)")


def test_selection_round_trips_and_keeps_other_keys():
    path = _fresh_settings()
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"music_volume": 0.5, "sfx_volume": 0.25}, fh)
    mutators.save_selection(("frenzy", "drift", "drift", "not_a_mutator"), path=path)
    assert mutators.load_selection(path=path) == ("drift", "frenzy"), mutators.load_selection(path=path)
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert data["music_volume"] == 0.5 and data["sfx_volume"] == 0.25, "saving mutators must keep the audio keys"
    assert data[mutators.MUTATORS_KEY] == ["drift", "frenzy"], data
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("{not json")
    assert mutators.load_selection(path=path) == (), "a broken settings file gives no selection"
    assert mutators.normalize_selection("drift") == (), "a bare string is not a selection"
    print("[PASS] test_selection_round_trips_and_keeps_other_keys passed (saved to user_settings.json, audio keys kept, bad file gives none)")


def test_title_chips_toggle_and_keep_the_action_buttons(g):
    _fresh_settings()
    m = g.main_menu
    g.mutator_ids = ()
    m.set_mutator_selection(())
    g.switch_to()
    # Wave-3 title screen: six buttons (Daily Run and Hangar were added in wave 2).
    assert [b.text for b in m.buttons] == ["Start Game", "Daily Run", "Guide", "Settings", "Hangar", "Quit"], [b.text for b in m.buttons]
    chip = next(c for c in m.mutator_row._chips if c.mutator.id == "drift")
    x, y = _chip_centre(chip)
    assert m.on_mouse_press(x, y, _LEFT) is None, "a chip click is not a menu action"
    assert g.mutator_ids == ("drift",), g.mutator_ids
    assert mutators.load_selection() == ("drift",), "the chip click must save the selection"
    m.on_mouse_press(x, y, _LEFT)
    assert g.mutator_ids == () and mutators.load_selection() == (), "a second click clears it"

    assert m.on_mouse_press(*_center(m.buttons[0]), _LEFT) == "start_game", "Start Game keeps its action"
    print("[PASS] test_title_chips_toggle_and_keep_the_action_buttons passed (chips toggle and save, action buttons unchanged)")


def _select(g, ids):
    """Set the title-screen selection the way the chips do, without a click."""
    g.mutator_ids = mutators.normalize_selection(ids)
    g.main_menu.set_mutator_selection(g.mutator_ids)


def test_run_applies_the_selection_once(g):
    _fresh_settings()
    _select(g, ("drift", "frenzy"))
    g._init_game()
    assert g.run_mutators == ("drift", "frenzy"), g.run_mutators
    assert g.run_rules == mutators.apply_mutators(("drift", "frenzy")), "the run must carry the selection's rules"
    assert g.run_rules.player_accel == mutators.DRIFT_ACCEL, "Drift must ease the steering"
    assert g.run_rules.enemy_speed_mult == mutators.FRENZY_ENEMY_SPEED_MULT, "Frenzy must speed the enemies"
    g._init_game()  # a second start with the same selection must not stack the rules
    assert g.run_rules == mutators.apply_mutators(("drift", "frenzy")), "rules must not stack across starts"

    # A stale saved file must not override what the chips show.
    mutators.save_selection(())
    _select(g, ("glass_cannon",))
    g._init_game()
    assert g.run_mutators == ("glass_cannon",), "the run must follow the chips, not an older saved file"
    base = int(g.player.damage)
    expected = max(1, int(base * mutators.GLASS_CANNON_DAMAGE_MULT + 0.5))
    assert g._effective_player_damage() == expected, f"glass cannon damage {g._effective_player_damage()}, expected {expected}"
    g._init_game()
    assert g._effective_player_damage() == expected, "the damage multiplier must be applied once, not per start"

    _select(g, ())
    g._init_game()
    assert g.run_mutators == () and g.run_rules == mutators.RunRules(), "no mutators must be the stock rules"
    assert g._effective_player_speed() == g.player.speed, "no mutators must leave the player speed unchanged"
    print("[PASS] test_run_applies_the_selection_once passed (the chips' selection is applied once in _init_game, stock with none)")


def test_enemy_stats_follow_the_selection():
    base = level.GameState(difficulty="normal")
    base.init_rng(12345)
    base.wave = 2
    mut = level.GameState(difficulty="normal")
    mut.init_rng(12345)
    mut.wave = 2
    mut.rules = mutators.apply_mutators(("frenzy",))
    # The wave plan draws from the global random module, so seed it before each spawn to get the same enemies.
    random.seed(99)
    level.spawn_wave(base, Vec2(0.0, 0.0))
    random.seed(99)
    level.spawn_wave(mut, Vec2(0.0, 0.0))
    assert base.enemies and mut.enemies, "both waves must spawn enemies"
    # Frenzy also raises the spawn size, so the plans differ; compare the first enemy of each behaviour that both waves spawn.
    first_base, first_mut = {}, {}
    for e in base.enemies:
        first_base.setdefault(e.behavior, e)
    for e in mut.enemies:
        first_mut.setdefault(e.behavior, e)
    pairs = [(first_base[b], first_mut[b]) for b in first_base if b in first_mut and first_base[b].elite_affix == first_mut[b].elite_affix]
    assert pairs, "no behaviour spawned in both waves with the same affix"
    for eb, em in pairs:
        assert abs(em.speed - eb.speed * mutators.FRENZY_ENEMY_SPEED_MULT) < 1e-6, (eb.behavior, eb.speed, em.speed)
    print(f"[PASS] test_enemy_stats_follow_the_selection passed (Frenzy scales {len(pairs)} matched enemies by 1.2 on the same spawn)")


def test_game_over_shows_the_combined_multiplier(g):
    menu = g.game_over_menu
    pair = ("drift", "frenzy")
    mult = mutators.combined_score_multiplier(pair)
    menu.set_mutators(["Drift", "Frenzy"], mult)
    expected = f"Mutators: Drift, Frenzy   |   score {mutators.format_score_mult(mult)}"
    assert menu.mutator_label.text == expected, menu.mutator_label.text
    menu.set_mutators([], 1.0)
    assert menu.mutator_label.text == "Mutators: none   |   score x1.00", menu.mutator_label.text

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
    expected_run = f"Mutators: Iron Man   |   score {mutators.format_score_mult(mutators.combined_score_multiplier(('iron_man',)))}"
    assert text == expected_run, text
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
            test_title_chips_toggle_and_keep_the_action_buttons(g)
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
