"""Regression tests for the swarm/menus item: SettingsMenu difficulty handler and arena save-on-release."""

import random

import pyglet

import config
from config import MAP_CIRCLE
from game import Game
from menu import SettingsMenu


LEFT = pyglet.window.mouse.LEFT


def _settings_menu(g, saves, on_save=None):
    random.seed(1234)  # The orb backdrop uses random; keep construction deterministic.
    return SettingsMenu(
        g.width,
        g.height,
        on_save if on_save is not None else saves.append,
        display_size=(1920, 1080),
        advanced_fx_enabled=True,
        map_type=MAP_CIRCLE,
        music_volume=0.5,
        sfx_volume=0.8,
    )


def _center(widget):
    return widget.x + widget.width / 2.0, widget.y + widget.height / 2.0


def _slider_at(slider, frac):
    return slider.x + frac * slider.width, slider.y


def test_set_difficulty_saves_and_selects(g):
    saves = []
    sm = _settings_menu(g, saves)
    sm._set_difficulty(2)
    assert sm.difficulty == 2, f"difficulty index expected 2, got {sm.difficulty}"
    assert saves == [{"difficulty": "hard"}], f"unexpected saves: {saves}"
    sm._set_difficulty(0)
    assert saves[-1] == {"difficulty": "easy"}, f"unexpected saves: {saves}"
    assert sm.get_settings()["difficulty"] == "easy", "get_settings should agree with the handler"
    print("[PASS] test_set_difficulty_saves_and_selects passed (hard then easy saved, get_settings agrees)")


def test_difficulty_click_saves_once_and_moves_highlight(g):
    saves = []
    sm = _settings_menu(g, saves)
    hard = sm.difficulty_buttons[2]
    assert sm.on_mouse_press(*_center(hard), LEFT) is None
    assert saves == [{"difficulty": "hard"}], f"click should save exactly once, got {saves}"
    assert sm.difficulty == 2
    assert sm._selected_diff_highlight.x == hard.x - 2, "highlight should move onto the Hard button"
    assert sm._selected_diff_highlight.width == hard.width + 4
    print("[PASS] test_difficulty_click_saves_once_and_moves_highlight passed (one save, highlight on Hard)")


def test_arena_drag_saves_once_on_release(g):
    saves = []
    sm = _settings_menu(g, saves)
    arena = sm.arena_slider
    sm.on_mouse_press(arena.get_knob_x(), arena.y, LEFT)
    assert arena.is_dragging, "pressing the arena knob should start a drag"
    for frac in (0.2, 0.4, 0.6, 0.8, 0.5):
        sm.on_mouse_drag(*_slider_at(arena, frac), 0, 0)
    assert saves == [], f"arena drag must not save per tick, got {saves}"
    assert abs(sm.arena_margin - 0.945) < 1e-6, f"live margin should track the drag, got {sm.arena_margin}"
    sm.on_mouse_release(*_slider_at(arena, 0.5), LEFT)
    assert len(saves) == 1, f"release should save once, got {saves}"
    assert abs(saves[0]["arena_margin"] - 0.945) < 1e-6, f"saved margin wrong: {saves}"
    assert not arena.is_dragging, "release should end the drag"
    print("[PASS] test_arena_drag_saves_once_on_release passed (5 drag ticks, 1 save at 0.945)")


def test_release_without_arena_drag_saves_nothing(g):
    saves = []
    sm = _settings_menu(g, saves)
    sm.on_mouse_release(0.0, 0.0, LEFT)
    assert saves == [], f"release with no active drag must not save, got {saves}"
    print("[PASS] test_release_without_arena_drag_saves_nothing passed (idle release is silent)")


def test_music_slider_still_saves_every_tick(g):
    saves = []
    sm = _settings_menu(g, saves)
    music = sm.music_slider
    sm.on_mouse_press(*_slider_at(music, 0.5), LEFT)
    for frac in (0.25, 0.75):
        sm.on_mouse_drag(*_slider_at(music, frac), 0, 0)
    sm.on_mouse_release(*_slider_at(music, 0.75), LEFT)
    assert len(saves) == 3, f"music press + 2 drag ticks should save 3 times, got {saves}"
    assert all(set(s) == {"music_volume"} for s in saves), f"music must only send music_volume: {saves}"
    assert abs(saves[-1]["music_volume"] - 0.75) < 1e-6, f"unexpected last music volume: {saves}"
    print("[PASS] test_music_slider_still_saves_every_tick passed (music unchanged: 3 saves, no release save)")


def test_difficulty_note_sits_beside_difficulty_row(g):
    sm = _settings_menu(g, [])
    for w, h in ((980, 620), (1280, 720), (1920, 1080)):
        sm.resize(w, h)
        note, head = sm.difficulty_note, sm.difficulty_label
        last = sm.difficulty_buttons[-1]
        assert "next run" in note.text.lower(), f"note text unexpected: {note.text!r}"
        assert note.y == head.y, f"note should share the Difficulty row at {w}x{h}"
        btn_right = last.x + last.width
        assert -1 <= note.x - btn_right <= 3, f"note should right-align with the buttons at {w}x{h}"
        note_left = note.x - note.content_width
        assert note_left >= head.x + head.content_width + 8, f"note collides with heading at {w}x{h}"
    print("[PASS] test_difficulty_note_sits_beside_difficulty_row passed (same row, no collision at 3 sizes)")


def test_hard_click_applies_to_next_run(g):
    menu = g.settings_menu
    menu.on_mouse_press(*_center(menu.difficulty_buttons[2]), LEFT)
    assert g.settings["difficulty"] == "hard", f"game settings not updated: {g.settings['difficulty']}"
    g._init_game()
    assert g.state.difficulty == "hard", f"next run should use hard, got {g.state.difficulty}"
    menu.on_mouse_press(*_center(menu.difficulty_buttons[1]), LEFT)
    assert g.settings["difficulty"] == "normal", "restoring normal failed"
    print("[PASS] test_hard_click_applies_to_next_run passed (settings -> next run state, restored to normal)")


def test_arena_drag_rebuilds_room_once(g):
    original_margin = config.ARENA_MARGIN
    g._init_game()
    room = g.room
    real_rebuild = room.rebuild
    rebuilds = []

    def counting_rebuild(*args, **kwargs):
        rebuilds.append(kwargs)
        return real_rebuild(*args, **kwargs)

    room.rebuild = counting_rebuild
    try:
        sm = _settings_menu(g, [], on_save=g._on_settings_change)
        arena = sm.arena_slider
        sm.on_mouse_press(arena.get_knob_x(), arena.y, LEFT)
        for frac in (0.1, 0.3, 0.5, 0.7, 0.9):
            sm.on_mouse_drag(*_slider_at(arena, frac), 0, 0)
        assert rebuilds == [], f"room rebuilt {len(rebuilds)} times during the drag"
        sm.on_mouse_release(*_slider_at(arena, 0.9), LEFT)
        assert len(rebuilds) == 1, f"expected one room rebuild on release, got {len(rebuilds)}"
        assert abs(config.ARENA_MARGIN - 0.981) < 1e-6, f"config margin not applied: {config.ARENA_MARGIN}"
    finally:
        room.rebuild = real_rebuild
        g._on_settings_change({"arena_margin": original_margin})
    print("[PASS] test_arena_drag_rebuilds_room_once passed (0 rebuilds mid-drag, 1 on release)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_set_difficulty_saves_and_selects(g)
        test_difficulty_click_saves_once_and_moves_highlight(g)
        test_arena_drag_saves_once_on_release(g)
        test_release_without_arena_drag_saves_nothing(g)
        test_music_slider_still_saves_every_tick(g)
        test_difficulty_note_sits_beside_difficulty_row(g)
        test_hard_click_applies_to_next_run(g)
        test_arena_drag_rebuilds_room_once(g)
    finally:
        g.close()
    print("\nALL SWARM MENUS REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
