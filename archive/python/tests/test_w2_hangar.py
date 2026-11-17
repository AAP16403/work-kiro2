"""Wave-2 Hangar tests: skin selection, keyboard navigation, back action, title button and layout.

Pure-rule tests always run. Screen tests need the wave-1 modules (progress, skins, achievements,
player_art, ui_theme); when one is missing they print "[SKIP requires-wave1]" instead of failing.
Screen tests use temporary progress files, so the real progress.json is never read or written.
"""

import importlib
import os
import re
import shutil
import tempfile
import types

import pyglet

import hangar_rules
from game import Game
from states import GameStateName, HangarState, MenuState


LEFT = pyglet.window.mouse.LEFT
KEY = pyglet.window.key
ROOT = os.path.dirname(os.path.abspath(__file__))
WAVE1_MODULES = ("progress", "skins", "achievements", "player_art", "ui_theme")


def _missing_wave1():
    missing = []
    for name in WAVE1_MODULES:
        try:
            importlib.import_module(name)
        except ImportError:
            missing.append(name)
    return missing


_SKIPPED = []


def _requires_wave1(test_name):
    missing = _missing_wave1()
    if missing:
        _SKIPPED.append(test_name)
        print(f"[SKIP requires-wave1] {test_name} (missing: {', '.join(missing)})")
        return True
    return False


def _temp_progress_dir():
    d = tempfile.mkdtemp(prefix="hangar_test_")
    return d, os.path.join(d, "progress.json")


def _card_center(menu, sid):
    for x, y, w, h, card_sid in menu._cards:
        if card_sid == sid:
            return x + w / 2.0, y + h / 2.0
    raise AssertionError(f"no card for {sid}")


def _button_center(btn):
    return btn.x + btn.width / 2.0, btn.y + btn.height / 2.0


def _hangar_menu(path, width=980, height=620):
    # Fixed size so the grid shape (and so the cursor wrap expectations) does not depend on the window.
    import hangar
    menu = hangar.HangarMenu(width, height, progress_path=path)
    menu.open()
    return menu


# ---------------------------------------------------------------- pure rules (always run)

def test_grid_step_wraps_flat_order(*_):
    # 8 cells in 4 columns: left from the first cell wraps to the last, right from the last wraps to the first.
    assert hangar_rules.grid_step(0, "left", 8, 4) == 7, "left from the first cell must wrap to the last"
    assert hangar_rules.grid_step(7, "right", 8, 4) == 0, "right from the last cell must wrap to the first"
    assert hangar_rules.grid_step(3, "right", 8, 4) == 4, "right inside a row moves one cell"
    assert hangar_rules.grid_step(4, "left", 8, 4) == 3, "left inside a row moves one cell"
    print("[PASS] test_grid_step_wraps_flat_order passed (left/right wrap at both ends)")


def test_grid_step_up_down_wrap_inside_column(*_):
    assert hangar_rules.grid_step(1, "up", 8, 4) == 5, "up from the top row wraps to the bottom of the column"
    assert hangar_rules.grid_step(5, "down", 8, 4) == 1, "down from the bottom row wraps to the top of the column"
    assert hangar_rules.grid_step(2, "down", 8, 4) == 6, "down inside the grid moves one row"
    assert hangar_rules.grid_step(6, "up", 8, 4) == 2, "up inside the grid moves one row"
    # Partial last row: column 2 only exists in row 0.
    assert hangar_rules.grid_step(4, "down", 5, 3) == 1, "down into a missing cell wraps to the column top"
    assert hangar_rules.grid_step(2, "up", 5, 3) == 2, "a column with one cell stays put when it wraps"
    assert hangar_rules.grid_step(0, "up", 5, 3) == 3, "up from the top wraps to the last cell of that column"
    print("[PASS] test_grid_step_up_down_wrap_inside_column passed (partial rows wrap per column)")


def test_grid_step_degenerate_counts(*_):
    assert hangar_rules.grid_step(0, "right", 1, 4) == 0, "one card stays on itself"
    assert hangar_rules.grid_step(0, "down", 0, 4) == 0, "an empty grid stays at zero"
    assert hangar_rules.page_step(0, -1, 3) == 2, "previous page from the first wraps to the last"
    assert hangar_rules.page_step(2, 1, 3) == 0, "next page from the last wraps to the first"
    assert hangar_rules.page_step(0, 1, 0) == 0, "no pages means page zero"
    print("[PASS] test_grid_step_degenerate_counts passed (single, empty and paging edges)")


def test_describe_unlock_reads_each_rule_shape(*_):
    names = {"first_blood": "First Blood"}
    default = types.SimpleNamespace(unlock={})
    achievement = types.SimpleNamespace(unlock={"kind": "achievement", "id": "first_blood"})
    stat = types.SimpleNamespace(unlock={"kind": "stat", "stat": "total_kills", "at_least": 150})
    text = types.SimpleNamespace(unlock={"text": "Clear a run without taking damage"})
    assert hangar_rules.describe_unlock(default, names) == "Open from the start"
    assert hangar_rules.describe_unlock(achievement, names) == "Unlock: earn the First Blood achievement"
    assert hangar_rules.describe_unlock(stat, names) == "Unlock: reach 150 total kills"
    assert hangar_rules.describe_unlock(text, names) == "Unlock: Clear a run without taking damage"
    print("[PASS] test_describe_unlock_reads_each_rule_shape passed (default, achievement, stat and text rules)")


def test_hangar_has_no_colour_literals(*_):
    pattern = re.compile(r"\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*\)")
    for name in ("hangar.py", "hangar_rules.py"):
        with open(os.path.join(ROOT, name), "r", encoding="utf-8") as f:
            src = f.read()
        hits = pattern.findall(src)
        assert not hits, f"{name} hard-codes colour tuples {hits}; use ui_theme tokens"
    print("[PASS] test_hangar_has_no_colour_literals passed (colours come from ui_theme tokens)")


# ---------------------------------------------------------------- title screen (always run)

def test_title_screen_has_six_buttons_with_hangar_and_daily(g):
    # Wave 2 merge: the Hangar (wave2/hangar) and the Daily Run (wave2/daily) buttons both sit on the title screen.
    menu = g.main_menu
    menu.resize(g.width, g.height)
    texts = [b.text for b in menu.buttons]
    assert texts == ["Start Game", "Daily Run", "Guide", "Settings", "Hangar", "Quit"], f"title buttons were {texts}"
    expected = {"Start Game": "start_game", "Daily Run": "daily", "Guide": "guide", "Settings": "settings",
                "Hangar": "hangar", "Quit": "quit"}
    for btn in menu.buttons:
        cx, cy = _button_center(btn)
        action = menu.on_mouse_press(cx, cy, LEFT)
        assert action == expected[btn.text], f"{btn.text} returned {action!r}, expected {expected[btn.text]!r}"
    print("[PASS] test_title_screen_has_six_buttons_with_hangar_and_daily passed (Hangar and Daily Run added, other actions unchanged)")


# ---------------------------------------------------------------- Hangar screen (needs wave 1)

def test_title_hangar_button_opens_hangar(g):
    if _requires_wave1("test_title_hangar_button_opens_hangar"):
        return
    d, path = _temp_progress_dir()
    try:
        g.fsm.set_state(GameStateName.MENU)
        g.hangar_menu = _hangar_menu(path)
        g.main_menu.resize(g.width, g.height)
        btn = next(b for b in g.main_menu.buttons if b.text == "Hangar")
        g.on_mouse_press(*_button_center(btn), LEFT, 0)
        assert isinstance(g.fsm.current_state, HangarState), "clicking Hangar must open the Hangar state"
        assert not os.path.exists(path), "opening the Hangar must not write progress"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("[PASS] test_title_hangar_button_opens_hangar passed (title Hangar button enters HangarState, no write on open)")


def test_locked_skin_is_refused(g):
    if _requires_wave1("test_locked_skin_is_refused"):
        return
    import skins
    d, path = _temp_progress_dir()
    try:
        menu = _hangar_menu(path)
        locked = next(sid for sid in menu.skin_ids if not skins.unlocked(menu.progress, sid))
        before = skins.selected(menu.progress).id
        menu.cursor = menu.skin_ids.index(locked)
        menu.on_mouse_press(*_card_center(menu, locked), LEFT)
        assert skins.selected(menu.progress).id == before, "a locked skin must not become selected by click"
        menu.cursor = menu.skin_ids.index(locked)
        menu.on_key_press(KEY.ENTER)
        assert skins.selected(menu.progress).id == before, "a locked skin must not become selected by ENTER"
        assert not os.path.exists(path), "refused selections must not save progress"
        assert "locked" in menu.footer.text.lower(), "the refusal should say the skin is locked"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"[PASS] test_locked_skin_is_refused passed (click and ENTER on '{locked}' refused, nothing saved)")


def test_unlocked_skin_selection_persists(g):
    if _requires_wave1("test_unlocked_skin_selection_persists"):
        return
    import progress
    import skins
    target = next(skin.id for skin in skins.SKINS.values() if skin.id != skins.DEFAULT_SKIN_ID)
    d, path = _temp_progress_dir()
    try:
        data = progress.default_progress()
        data["unlocked_skins"] = [target]
        progress.save(data, path)
        menu = _hangar_menu(path)
        assert skins.unlocked(menu.progress, target), "the granted skin must read as unlocked"
        menu.on_mouse_press(*_card_center(menu, target), LEFT)
        on_disk = progress.load(path)
        assert on_disk.get("selected_skin") == target, f"selection did not persist, file says {on_disk.get('selected_skin')!r}"
        assert menu._card_state(target) == "selected", "the card should now show SELECTED"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"[PASS] test_unlocked_skin_selection_persists passed (selected '{target}' saved to progress)")


def test_keyboard_navigation_wraps_and_selects(g):
    if _requires_wave1("test_keyboard_navigation_wraps_and_selects"):
        return
    import skins
    d, path = _temp_progress_dir()
    try:
        menu = _hangar_menu(path)
        n = len(menu.skin_ids)
        cols = menu._cols
        menu.cursor = 0
        menu.on_key_press(KEY.LEFT)
        assert menu.cursor == n - 1, f"LEFT from the first card should wrap to {n - 1}, got {menu.cursor}"
        menu.on_key_press(KEY.RIGHT)
        assert menu.cursor == 0, f"RIGHT from the last card should wrap to 0, got {menu.cursor}"
        menu.on_key_press(KEY.UP)
        assert menu.cursor == hangar_rules.grid_step(0, "up", n, cols), "UP must follow the grid wrap rule"
        menu.cursor = 0
        menu.on_key_press(KEY.DOWN)
        assert menu.cursor == hangar_rules.grid_step(0, "down", n, cols), "DOWN must follow the grid wrap rule"
        # ENTER on an unlocked card selects it and saves.
        unlocked = next((sid for sid in menu.skin_ids if skins.unlocked(menu.progress, sid) and sid != skins.selected(menu.progress).id), None)
        if unlocked is not None:
            menu.cursor = menu.skin_ids.index(unlocked)
            menu.on_key_press(KEY.ENTER)
            assert skins.selected(menu.progress).id == unlocked, "ENTER should select the cursor card"
            assert os.path.exists(path), "ENTER selection should save progress"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"[PASS] test_keyboard_navigation_wraps_and_selects passed (LEFT/RIGHT/UP/DOWN wrap on {n} cards, {cols} columns)")


def test_cursor_moves_redraw_only_the_ring(g):
    if _requires_wave1("test_cursor_moves_redraw_only_the_ring"):
        return
    d, path = _temp_progress_dir()
    try:
        menu = _hangar_menu(path)
        content_before = list(menu._content)
        ring_before = list(menu._ring_shapes)
        menu.on_key_press(KEY.RIGHT)
        menu.on_key_press(KEY.DOWN)
        assert len(menu._content) == len(content_before) and all(a is b for a, b in zip(content_before, menu._content)), \
            "arrow keys must not rebuild labels and card plates"
        assert menu._ring_shapes and menu._ring_shapes is not ring_before, "the cursor ring should move with the cursor"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("[PASS] test_cursor_moves_redraw_only_the_ring passed (arrow keys rebuild only the cursor ring)")


def test_back_action_returns_title_screen(g):
    if _requires_wave1("test_back_action_returns_title_screen"):
        return
    d, path = _temp_progress_dir()
    try:
        g.hangar_menu = _hangar_menu(path)
        g.fsm.set_state(GameStateName.HANGAR)
        assert isinstance(g.fsm.current_state, HangarState)
        g.on_key_press(KEY.ESCAPE, 0)
        assert isinstance(g.fsm.current_state, MenuState), "ESC must return to the title screen"
        g.hangar_menu = _hangar_menu(path)
        g.fsm.set_state(GameStateName.HANGAR)
        g.on_mouse_press(*_button_center(g.hangar_menu.btn_back), LEFT, 0)
        assert isinstance(g.fsm.current_state, MenuState), "the Back button must return to the title screen"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("[PASS] test_back_action_returns_title_screen passed (ESC and Back both return to MenuState)")


def test_achievement_pages_wrap_and_tab_toggles(g):
    if _requires_wave1("test_achievement_pages_wrap_and_tab_toggles"):
        return
    d, path = _temp_progress_dir()
    try:
        menu = _hangar_menu(path)
        menu.on_key_press(KEY.TAB)
        assert menu.tab == "achievements", "TAB should switch to the achievements gallery"
        pages = menu._page_count
        menu.on_key_press(KEY.LEFT)
        assert menu.ach_page == pages - 1, "LEFT on the first page should wrap to the last page"
        menu.on_key_press(KEY.RIGHT)
        assert menu.ach_page == 0, "RIGHT on the last page should wrap to the first page"
        menu.on_key_press(KEY.TAB)
        assert menu.tab == "skins", "TAB should switch back to skins"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"[PASS] test_achievement_pages_wrap_and_tab_toggles passed ({pages} achievement pages wrap)")


def test_each_card_previews_its_own_palette(g):
    if _requires_wave1("test_each_card_previews_its_own_palette"):
        return
    import hangar as H
    import skins
    from skin_apply import complete_palette

    # Wave 6: each card holds its own CharacterPreview, so the check reads the palette that preview draws.
    d, path = _temp_progress_dir()
    try:
        menu = H.HangarMenu(980, 620, progress_path=path)
        menu.open()
        menu.update(0.1)
        for sid in menu.skin_ids:
            expected = complete_palette(skins.get(sid).palette)
            assert menu._previews[sid].palette == expected, f"card '{sid}' does not preview its own palette"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print(f"[PASS] test_each_card_previews_its_own_palette passed ({len(menu.skin_ids)} cards, one palette each)")


def test_cards_fit_panel_at_both_sizes(g):
    if _requires_wave1("test_cards_fit_panel_at_both_sizes"):
        return
    d, path = _temp_progress_dir()
    try:
        menu = _hangar_menu(path)
        for (w, h) in ((980, 620), (1920, 1080)):
            menu.resize(w, h)
            px, py, pw, ph = menu._panel_rect
            _ax, ay, _aw, _ah = menu._area
            rects = [(x, y, cw, ch) for x, y, cw, ch, _sid in menu._cards]
            assert len(rects) == len(menu.skin_ids), "every skin needs a card"
            for x, y, cw, ch in rects:
                assert px <= x and x + cw <= px + pw, f"card overflows the panel width at {w}x{h}"
                assert y >= ay and y + ch <= py + ph, f"card overflows the panel height at {w}x{h}"
            for i in range(len(rects)):
                for j in range(i + 1, len(rects)):
                    ax_, ay_, aw_, ah_ = rects[i]
                    bx, by, bw, bh = rects[j]
                    overlap = ax_ < bx + bw and bx < ax_ + aw_ and ay_ < by + bh and by < ay_ + ah_
                    assert not overlap, f"cards {i} and {j} overlap at {w}x{h}"
    finally:
        shutil.rmtree(d, ignore_errors=True)
    print("[PASS] test_cards_fit_panel_at_both_sizes passed (980x620 and 1920x1080: no overflow, no overlap)")


def run_all():
    test_grid_step_wraps_flat_order()
    test_grid_step_up_down_wrap_inside_column()
    test_grid_step_degenerate_counts()
    test_describe_unlock_reads_each_rule_shape()
    test_hangar_has_no_colour_literals()

    g = Game()
    g.set_visible(False)
    try:
        test_title_screen_has_six_buttons_with_hangar_and_daily(g)
        test_title_hangar_button_opens_hangar(g)
        test_locked_skin_is_refused(g)
        test_unlocked_skin_selection_persists(g)
        test_keyboard_navigation_wraps_and_selects(g)
        test_cursor_moves_redraw_only_the_ring(g)
        test_back_action_returns_title_screen(g)
        test_achievement_pages_wrap_and_tab_toggles(g)
        test_each_card_previews_its_own_palette(g)
        test_cards_fit_panel_at_both_sizes(g)
    finally:
        g.close()
    if _SKIPPED:
        print(f"\nWAVE 2 HANGAR TESTS PASSED, {len(_SKIPPED)} skipped [requires-wave1]")
    else:
        print("\nALL WAVE 2 HANGAR TESTS PASSED")


if __name__ == "__main__":
    run_all()
