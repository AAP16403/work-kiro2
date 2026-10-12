"""Regression tests for the swarm ui_flow group: auto-fire default, status line fitting,
shield cap and the Guide entries for fire, elites and the boss schedule."""

import pyglet

from config import SHIELD_MAX
from enemy import Enemy
from game import Game
from menu import GuideMenu
from powerup import PowerUp, apply_powerup
from states import GameStateName, PlayingState
from utils import Vec2


SEP = "   |   "


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Call update() directly: pyglet.clock.tick() would also fire the game's scheduled
    # update with real elapsed time and double-step the simulation.
    for _ in range(frames):
        g.dispatch_events()
        g.update(1.0 / 60.0)


def _crowded_segments(auto="AUTO ON"):
    # Importance order as PlayingState.draw builds it: lower priority number survives longer.
    return [
        (0, "BOSS Womb Core"),
        (1, "Ultra 2 [Flak Battery] 9s"),
        (2, "Laser 6s"),
        (2, "Vortex 4s"),
        (3, "Temp Targeting Optics:2, Hyper Overdrive:1"),
        (4, "Dash 1/2 1.4s"),
        (5, "BOOSTING 100%"),
        (6, "Run Shield,Crit,Dash,Ultra"),
        (3, auto),
    ]


def test_auto_fire_starts_on_every_run(g):
    g.auto_shoot = False
    g._init_game()
    assert g.auto_shoot is True, "a new run must start with auto-fire on"
    g.auto_shoot = False  # player switched it off during the last run
    g._init_game()  # Try Again builds a fresh run through the same path
    assert g.auto_shoot is True, "Try Again must restart with auto-fire on"
    print("[PASS] test_auto_fire_starts_on_every_run passed (new run and Try Again both start with auto-fire on)")


def test_auto_fire_constructor_default_is_on():
    # Builds its own window, so run_all calls it before the shared game exists.
    g2 = Game()
    g2.set_visible(False)
    try:
        assert g2.auto_shoot is True, "Game() must construct with auto-fire on"
    finally:
        g2.close()
    print("[PASS] test_auto_fire_constructor_default_is_on passed (constructor default is ON)")


def test_lmb_still_toggles_auto_fire(g):
    _new_run(g)
    state = PlayingState(g)
    state.on_mouse_press(100, 100, pyglet.window.mouse.LEFT, 0)
    assert g.auto_shoot is False, "LMB must switch auto-fire off from its ON start"
    state.on_mouse_press(100, 100, pyglet.window.mouse.LEFT, 0)
    assert g.auto_shoot is True, "a second LMB must switch auto-fire back on"
    print("[PASS] test_lmb_still_toggles_auto_fire passed (LMB remains the toggle)")


def test_status_line_ends_with_auto_state(g):
    _new_run(g)
    g.auto_shoot = True
    g.on_draw()
    text = g.hud.status_label.text
    assert text.endswith("AUTO ON"), f"expected AUTO ON at the end of the status line, got {text!r}"
    g.auto_shoot = False
    g.on_draw()
    text = g.hud.status_label.text
    assert text.endswith("AUTO OFF"), f"expected AUTO OFF at the end of the status line, got {text!r}"
    print("[PASS] test_status_line_ends_with_auto_state passed (AUTO segment is the last status segment)")


def test_boss_status_is_name_only_and_survives_draw(g):
    s = _new_run(g)
    boss = Enemy(pos=Vec2(0.0, 0.0), hp=500, speed=0.0, behavior="boss_brute", max_hp=500)
    s.enemies = [boss]
    s.wave_active = True
    g.on_draw()
    text = g.hud.status_label.text
    assert "BOSS Brute" in text, f"boss name missing from status line: {text!r}"
    assert "HP" not in text, f"status line should not repeat boss HP: {text!r}"
    print("[PASS] test_boss_status_is_name_only_and_survives_draw passed (boss segment shows the name, not HP)")


def test_status_fit_keeps_boss_and_ultra_when_crowded(g):
    _new_run(g)
    hud = g.hud
    label = hud.status_label
    # Measure the pair plus the ' +7' suffix, then allow exactly that width.
    label.text = "BOSS Womb Core" + SEP + "Ultra 2 [Flak Battery] 9s +7"
    hud._status_max_w = label.content_width + 2.0
    text = hud._fit_status(_crowded_segments())
    assert text == "BOSS Womb Core" + SEP + "Ultra 2 [Flak Battery] 9s +7", f"unexpected fit: {text!r}"
    label.text = text
    assert label.content_width <= hud._status_max_w, "fitted status line must stay within the bar"
    print("[PASS] test_status_fit_keeps_boss_and_ultra_when_crowded passed (boss and ultra kept, 7 low-priority segments hidden)")


def test_status_fit_keeps_auto_before_perm_and_boost(g):
    _new_run(g)
    hud = g.hud
    label = hud.status_label
    # Room for everything but the perm-reward segment (the lowest priority, 6) plus its ' +1' suffix.
    kept_segments = [seg for seg in _crowded_segments() if "Run Shield" not in seg[1]]
    label.text = SEP.join(text for _, text in kept_segments) + " +1"
    hud._status_max_w = label.content_width + 2.0
    text = hud._fit_status(_crowded_segments())
    assert text.endswith(" +1"), f"exactly one segment should be hidden: {text!r}"
    assert "Run Shield,Crit,Dash,Ultra" not in text, "the perm-reward segment is the one dropped"
    assert text.endswith("AUTO ON +1"), f"auto-fire state must outlast perm rewards: {text!r}"
    print("[PASS] test_status_fit_keeps_auto_before_perm_and_boost passed (auto-fire state outlasts perm rewards, boost and dash)")


def test_status_fit_trims_lone_segment_with_ellipsis(g):
    _new_run(g)
    hud = g.hud
    label = hud.status_label
    hud._status_max_w = 120.0
    text = hud._fit_status([(0, "BOSS Womb Core and a long tail of extra words that cannot fit")])
    assert text.endswith("..."), f"a lone over-wide segment should be trimmed: {text!r}"
    label.text = text
    assert label.content_width <= 120.0, "trimmed segment must fit the width"
    print("[PASS] test_status_fit_trims_lone_segment_with_ellipsis passed (single segment trimmed with '...')")


def test_status_fit_keeps_suffix_when_trimming_lone_segment(g):
    _new_run(g)
    hud = g.hud
    label = hud.status_label
    hud._status_max_w = 120.0
    text = hud._fit_status([(0, "BOSS Womb Core and a long tail of extra words that cannot fit"), (5, "Boost 100%")])
    assert text.endswith("... +1"), f"hidden count must survive trimming: {text!r}"
    label.text = text
    assert label.content_width <= 120.0, "trimmed line with suffix must fit the width"
    print("[PASS] test_status_fit_keeps_suffix_when_trimming_lone_segment passed (' +N' stays readable)")


def test_status_fit_joins_short_segments_without_suffix(g):
    _new_run(g)
    hud = g.hud
    text = hud._fit_status([(0, "BOSS Brute"), (4, ""), (7, "AUTO ON")])
    assert text == "BOSS Brute" + SEP + "AUTO ON", f"empty segments must be skipped: {text!r}"
    assert hud._fit_status([]) == "", "no segments means an empty status line"
    print("[PASS] test_status_fit_joins_short_segments_without_suffix passed (empty segments skipped, no ' +N')")


def test_status_fit_cache_reuses_results(g):
    _new_run(g)
    hud = g.hud
    segments = [(0, "CACHE PROBE 7749"), (7, "AUTO ON")]
    before = len(hud._status_cache)
    first = hud._fit_status(segments)
    after_first = len(hud._status_cache)
    second = hud._fit_status(segments)
    assert first == second == "CACHE PROBE 7749" + SEP + "AUTO ON"
    assert after_first == before + 1, "a new (segments, width) pair must be cached once"
    assert len(hud._status_cache) == after_first, "a repeated pair must hit the cache"
    print("[PASS] test_status_fit_cache_reuses_results passed (fitted text cached by segments and width)")


def test_status_text_argument_still_works(g):
    _new_run(g)
    g.hud.update_bars(g.player, g.state, status_text="Legacy line")
    assert g.hud.status_label.text == "Legacy line", "update_bars without segments must still show status_text"
    print("[PASS] test_status_text_argument_still_works passed (legacy status_text call remains valid)")


def test_shield_bar_and_label_cap_at_shield_max(g):
    s = _new_run(g)
    assert SHIELD_MAX == 120, f"SHIELD_MAX must match the pickup cap of 120, got {SHIELD_MAX}"
    g.player.shield = 118
    g.hud.update_bars(g.player, s, status_segments=[])
    assert g.hud.shield_value_label.text == "118/120", g.hud.shield_value_label.text
    assert abs(g.hud.shield_bar.width - g.hud._bar_w * 118 / 120) < 1.0, "bar must scale to 120, not 100"
    g.player.shield = 150
    g.hud.update_bars(g.player, s, status_segments=[])
    assert g.hud.shield_value_label.text == "120/120", g.hud.shield_value_label.text
    assert abs(g.hud.shield_bar.width - g.hud._bar_w) < 1.0, "bar must be full at the cap and not overflow"
    print("[PASS] test_shield_bar_and_label_cap_at_shield_max passed (bar and label top out at 120)")


def test_shield_pickups_respect_shield_max(g):
    _new_run(g)
    p = g.player
    p.shield = 0
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="shield"), 0.0)
    assert p.shield == 45, f"shield pickup should add 45, got {p.shield}"
    p.shield = 100
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="shield"), 0.0)
    assert p.shield == SHIELD_MAX, f"shield pickup must cap at {SHIELD_MAX}, got {p.shield}"
    p.shield = 110
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="boost"), 0.0)
    assert p.shield == SHIELD_MAX, f"overdrive shield top-up must cap at {SHIELD_MAX}, got {p.shield}"
    print("[PASS] test_shield_pickups_respect_shield_max passed (shield and overdrive caps use SHIELD_MAX)")


def test_guide_basics_teaches_fire_elites_and_boss_schedule(g):
    entries = GuideMenu.BASICS_INFO
    assert len(entries) == 12, f"Basics tab should have 12 entries, got {len(entries)}"
    keys = [e["key"] for e in entries]
    assert len(set(keys)) == len(keys), "Basics keys must be unique"
    for e in entries:
        for field in ("key", "name", "icon", "what", "deal", "lore"):
            assert str(e.get(field, "")).strip(), f"Basics entry {e.get('key')} is missing {field}"

    fire = next(e for e in entries if e["key"] == "fire")
    assert "LMB" in fire["what"] and "starts ON" in fire["what"], fire["what"]

    elites = next(e for e in entries if e["key"] == "elites")
    assert elites["icon"] == "EL"
    assert "2.2x HP" in elites["what"], elites["what"]
    assert "45" in elites["deal"] and "130 px" in elites["deal"], elites["deal"]
    assert "Shielded" in elites["deal"] and "Swift" in elites["lore"], (elites["deal"], elites["lore"])

    boss = next(e for e in entries if e["key"] == "boss_schedule")
    assert boss["name"] == "Boss Schedule" and boss["icon"] == "BS"
    assert "every 5th wave" in boss["what"], boss["what"]
    assert "card" in boss["deal"], boss["deal"]

    menu = GuideMenu(980, 620)
    menu.tab = "basics"
    # Only three rows fit above the nav strip at 980x620, so 12 entries take four pages of three.
    per_page = menu.rows_per_page
    assert per_page == 3, f"three rows fit above the nav strip at 980x620, got {per_page}"
    assert menu._total_pages() == 4, f"12 Basics entries at {per_page} per page should give 4 pages, got {menu._total_pages()}"
    menu.page = 1
    assert len(menu._page_entries()) == per_page, "second Basics page should be full"
    print("[PASS] test_guide_basics_teaches_fire_elites_and_boss_schedule passed (12 entries over 4 pages of 3)")


def run_all():
    test_auto_fire_constructor_default_is_on()
    g = Game()
    g.set_visible(False)
    try:
        test_auto_fire_starts_on_every_run(g)
        test_lmb_still_toggles_auto_fire(g)
        test_status_line_ends_with_auto_state(g)
        test_boss_status_is_name_only_and_survives_draw(g)
        test_status_fit_keeps_boss_and_ultra_when_crowded(g)
        test_status_fit_keeps_auto_before_perm_and_boost(g)
        test_status_fit_trims_lone_segment_with_ellipsis(g)
        test_status_fit_keeps_suffix_when_trimming_lone_segment(g)
        test_status_fit_joins_short_segments_without_suffix(g)
        test_status_fit_cache_reuses_results(g)
        test_status_text_argument_still_works(g)
        test_shield_bar_and_label_cap_at_shield_max(g)
        test_shield_pickups_respect_shield_max(g)
        test_guide_basics_teaches_fire_elites_and_boss_schedule(g)
    finally:
        g.close()
    print("\nALL SWARM UI_FLOW REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
