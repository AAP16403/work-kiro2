"""Regression tests for the wave-2 final review fixes.

One test per fix: the Hangar opens, the Daily Run starts with one mutator that changes play, the Daily
Game Over settles, the mutator module exists, the Splitter and Reflector elites work, the selected skin
reaches the player, achievement toasts reach the next HUD, the HUD skin badge reads the wave-1 store,
and REDUCE_MOTION is defined. Run with: python test_w2_fix.py
"""

import datetime
import json
import os
import random
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config  # noqa: E402
import daily  # noqa: E402
import hud  # noqa: E402
import hud_widgets  # noqa: E402
import level  # noqa: E402
import mutators  # noqa: E402
import progress  # noqa: E402
import skins  # noqa: E402
import ui_theme  # noqa: E402
from enemy import Enemy  # noqa: E402
from game import Game  # noqa: E402
from hangar import HangarMenu  # noqa: E402
from player_art import DEFAULT_PALETTE  # noqa: E402
from projectile import Projectile  # noqa: E402
from states import PlayingState  # noqa: E402
from utils import Vec2  # noqa: E402

DAY = datetime.date(2026, 10, 12)
DAY_ISO = "2026-10-12"


def _temp_dir() -> str:
    return tempfile.mkdtemp(prefix="w2fix-")


def test_hangar_menu_opens_with_integrated_modules(g):
    d = _temp_dir()
    try:
        menu = HangarMenu(980, 620, progress_path=os.path.join(d, "progress.json"))
        ids = [s.id for s in skins.SKINS.values()]  # SKINS is a dict id -> Skin (wave-3 contract)
        assert menu.skin_ids == ids, f"hangar lists {menu.skin_ids}, catalogue is {ids}"
        assert set(menu._palettes) == set(ids), "every skin needs a preview palette"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("[PASS] test_hangar_menu_opens_with_integrated_modules passed (Hangar builds from the merged wave-1 modules)")


def test_daily_run_starts_with_one_mutator(g):
    g._start_daily_run(DAY)
    assert g.daily_date == DAY_ISO, f"daily date is {g.daily_date!r}"
    assert len(g.run_mutator_ids) == 1, "a daily run never stacks mutators"
    assert g.run_mutator_ids[0] in {m.id for m in mutators.MUTATORS}, "the daily mutator must be a real mutators.py id"
    assert g.run_rules == mutators.apply_mutators(g.run_mutator_ids), "the run must carry the mutator's rules, applied once"
    print(f"[PASS] test_daily_run_starts_with_one_mutator passed (mutator '{g.run_mutator_ids[0]}' applied to the run)")


def test_mutator_changes_player_damage(g):
    g.run_mutator_ids = ("glass_cannon",)
    g._init_game()
    base = int(g.player.damage)
    expected = max(1, int(base * 1.5 + 0.5))
    assert g._effective_player_damage() == expected, f"glass_cannon damage {g._effective_player_damage()}, expected {expected}"
    g.run_mutator_ids = ()
    g._init_game()
    assert g._effective_player_damage() == max(1, base), "without a mutator the damage is unchanged"
    print("[PASS] test_mutator_changes_player_damage passed (glass_cannon 1.5x on shots, identity otherwise)")


def test_mutator_module_has_five_daily_rules(g):
    # Wave-2 expectation updated to the contract mutators.py (one module): MUTATORS is a tuple of records,
    # apply_mutators folds the rules, and an unknown id is dropped instead of raising.
    ids = {m.id for m in mutators.MUTATORS}
    assert len(mutators.MUTATORS) == 5, f"expected 5 mutators, got {sorted(ids)}"
    assert ids == {"bullet_hell", "drift", "frenzy", "glass_cannon", "iron_man"}
    assert daily.mutator_pool() == tuple(sorted(ids))
    assert mutators.apply_mutators(()) == mutators.RunRules(), "no mutators is the stock rules"
    # Contract: a selection is a set, so a repeated id applies once (wave-2 expected 2.25 from stacking).
    assert mutators.apply_mutators(("glass_cannon", "glass_cannon")).player_damage_mult == 1.5
    assert mutators.apply_mutators(("nope",)) == mutators.RunRules(), "an unknown mutator id is dropped"
    print("[PASS] test_mutator_module_has_five_daily_rules passed (5 ids, apply_mutators multiplies, unknown ids dropped)")


def test_daily_game_over_settles_record(g):
    d = _temp_dir()
    path = os.path.join(d, "progress.json")
    try:
        result = daily.settle_daily_run(DAY_ISO, 1234, 5, path=path)
        assert result.best_score == 1234 and result.new_best, "first run of the day sets the record"
        with open(path, "r", encoding="utf-8") as fh:
            saved = json.load(fh)
        assert saved["daily"][DAY_ISO]["score"] == 1234, "the daily table must be saved in progress.json"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("[PASS] test_daily_game_over_settles_record passed (settle_daily_run saves the date's record)")


def test_elite_affix_pool_has_five_affixes(g):
    rng = random.Random(3)
    seen = {level._choose_affix(rng) for _ in range(2000)}
    assert seen == {"volatile", "swift", "shielded", "splitter", "reflector"}, f"affixes rolled: {sorted(seen)}"
    print("[PASS] test_elite_affix_pool_has_five_affixes passed (all five affixes are rolled)")


def test_splitter_death_spawns_two_half_hp_children(g):
    g._init_game()
    s = g.state
    s.enemies.clear()
    centre = Vec2(g.player.pos.x + 260.0, g.player.pos.y)
    e = Enemy(pos=centre, hp=40, speed=40.0, behavior="chaser", max_hp=40, is_elite=True, elite_affix="splitter")
    s.enemies.append(e)
    PlayingState._kill_enemy(g, s, e)
    assert e not in s.enemies, "the splitter is removed on death"
    assert len(s.enemies) == 2, f"expected two children, found {len(s.enemies)}"
    for child in s.enemies:
        assert child.hp == 20 and child.max_hp == 20, "each child has half the splitter's max HP"
        assert child.elite_affix == "", "children carry no affix, so they never split again"
    xs = sorted(c.pos.x for c in s.enemies)
    assert xs[0] < centre.x < xs[1], "children appear on opposite sides of the splitter"
    print("[PASS] test_splitter_death_spawns_two_half_hp_children passed (two 20 HP children, opposite sides, no chaining)")


def test_reflector_returns_first_shot_then_takes_damage(g):
    g._init_game()
    s = g.state
    s.enemies.clear()
    s.projectiles.clear()
    e = Enemy(pos=Vec2(g.player.pos.x + 300.0, g.player.pos.y), hp=60, speed=0.0, behavior="chaser",
              max_hp=60, is_elite=True, elite_affix="reflector")
    s.enemies.append(e)
    shot = Projectile(Vec2(e.pos.x - 12.0, e.pos.y), Vec2(900.0, 0.0), 7, ttl=1.0, owner="player", projectile_type="bullet")
    s.projectiles.append(shot)
    ps = PlayingState(g)
    ps.update(1.0 / 60.0)
    assert e.hp == 60, "the first shot in a window is sent back, not taken"
    returned = [p for p in s.projectiles if p.owner == "enemy"]
    assert returned, "a reflected shot must be fired back at the player"

    s.projectiles.clear()
    s.projectiles.append(Projectile(Vec2(e.pos.x - 12.0, e.pos.y), Vec2(900.0, 0.0), 7, ttl=1.0, owner="player",
                                    projectile_type="bullet"))
    ps.update(1.0 / 60.0)
    assert e.hp < 60, "a second shot inside the cooldown damages the reflector"
    print("[PASS] test_reflector_returns_first_shot_then_takes_damage passed (first shot reflected, cooldown then damage)")


def test_selected_skin_reaches_player_and_default_is_unchanged(g):
    d = _temp_dir()
    saved_file = progress.PROGRESS_FILE
    try:
        path = os.path.join(d, "progress.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"selected_skin": "ember", "unlocked_skins": ["ember"]}, fh)
        progress.PROGRESS_FILE = path
        g._init_game()
        ember = skins.get("ember")
        assert g.visuals.player_palette["body"] == ember.palette["body"], "the selected skin must recolour the player"
        assert g.visuals.player_bullet_tint == ember.palette["bullet"], "the skin's bullet colour tints the player's shots"

        progress.PROGRESS_FILE = os.path.join(d, "missing.json")
        g._init_game()
        assert g.visuals.player_palette == DEFAULT_PALETTE, "the default skin keeps wave 1's palette exactly"
        assert g.visuals.player_bullet_tint is None, "the default skin keeps weapon-coloured shots"
    finally:
        progress.PROGRESS_FILE = saved_file
        shutil.rmtree(d, ignore_errors=True)
    print("[PASS] test_selected_skin_reaches_player_and_default_is_unchanged passed (ember applied, default identical)")


def test_achievement_toasts_reach_next_run_hud(g):
    shown = []
    original = hud.HUD.push_achievement_toasts

    def record(self, achievement_ids):
        shown.append(list(achievement_ids))
        return len(list(achievement_ids))

    hud.HUD.push_achievement_toasts = record
    try:
        g._pending_achievement_ids = ["first_blood"]
        g._init_game()
    finally:
        hud.HUD.push_achievement_toasts = original
    assert shown == [["first_blood"]], f"toasts pushed: {shown}"
    assert g._pending_achievement_ids == [], "the queue is drained once shown"
    print("[PASS] test_achievement_toasts_reach_next_run_hud passed (earned ids feed the next run's HUD once)")


def test_hud_skin_badge_reads_wave1_store(g):
    name = hud.current_skin_name({"selected_skin": "classic", "unlocked_skins": []})
    assert name == skins.get("classic").name, f"badge shows {name!r}"
    locked = hud.current_skin_name({"selected_skin": "ember", "unlocked_skins": []})
    assert locked == skins.get("classic").name, "a locked selection falls back to the default name"
    print("[PASS] test_hud_skin_badge_reads_wave1_store passed (selected or default name, never an error)")


def _click_title_button(g, text: str) -> None:
    from pyglet.window import mouse
    from states import MenuState

    if hasattr(g.main_menu, "resize"):
        g.main_menu.resize(g.width, g.height)
    btn = next(b for b in g.main_menu.buttons if b.text == text)
    MenuState(g).on_mouse_press(btn.x + btn.width / 2.0, btn.y + btn.height / 2.0, mouse.LEFT, 0)


def test_title_daily_and_hangar_buttons_change_state(g):
    _click_title_button(g, "Daily Run")
    name = g.fsm.current_state.__class__.__name__
    assert name == "PlayingState", f"Daily Run left the game in {name}, expected PlayingState"
    assert g.daily_date and len(g.run_mutator_ids) == 1, "Daily Run must start a daily run with one mutator"

    _click_title_button(g, "Hangar")
    name = g.fsm.current_state.__class__.__name__
    assert name == "HangarState", f"Hangar button left the game in {name}, expected HangarState"
    print("[PASS] test_title_daily_and_hangar_buttons_change_state passed (Daily Run enters PLAYING, Hangar enters HANGAR)")


def test_reduce_motion_is_defined_and_read(g):
    assert hasattr(config, "REDUCE_MOTION"), "config.REDUCE_MOTION must exist so reduce motion can be set"
    assert ui_theme.reduce_motion() == bool(config.REDUCE_MOTION)
    print("[PASS] test_reduce_motion_is_defined_and_read passed (config.REDUCE_MOTION exists and ui_theme reads it)")


def test_hud_panels_use_ui_theme_fill(g):
    import pyglet

    batch = pyglet.graphics.Batch()
    parts = hud_widgets.draw_panel(batch, 0, 0, 40, 20, color=(12, 34, 56))
    assert len(parts) == 3, "a ui_theme panel is edge, body and shine"
    assert tuple(parts[1].color)[:3] == (12, 34, 56), "the fill colour must reach the panel body"
    print("[PASS] test_hud_panels_use_ui_theme_fill passed (hud_widgets passes fill= to ui_theme)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_hangar_menu_opens_with_integrated_modules(g)
        test_daily_run_starts_with_one_mutator(g)
        test_mutator_changes_player_damage(g)
        test_mutator_module_has_five_daily_rules(g)
        test_daily_game_over_settles_record(g)
        test_elite_affix_pool_has_five_affixes(g)
        test_splitter_death_spawns_two_half_hp_children(g)
        test_reflector_returns_first_shot_then_takes_damage(g)
        test_selected_skin_reaches_player_and_default_is_unchanged(g)
        test_achievement_toasts_reach_next_run_hud(g)
        test_hud_skin_badge_reads_wave1_store(g)
        test_title_daily_and_hangar_buttons_change_state(g)
        test_reduce_motion_is_defined_and_read(g)
        test_hud_panels_use_ui_theme_fill(g)
    finally:
        g.close()
    print("\nALL W2 FIX REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
