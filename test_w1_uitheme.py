"""Regression tests for the wave-1 uitheme item: UI tokens, the title screen redesign and reduced motion.

Plain functions that print [PASS] lines. Each test that needs OpenGL uses one hidden window.
"""

import random

import pyglet

import config
import title_fx
import ui_theme
from menu import Menu, _ui_scale
from rpg import BossRewardMenu

_WINDOW = None


def _gl():
    """One hidden window for the whole run, made current before any pyglet object is built."""
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = pyglet.window.Window(980, 620, visible=False)
    _WINDOW.switch_to()
    return _WINDOW


def _close_gl():
    global _WINDOW
    if _WINDOW is not None:
        _WINDOW.close()
        _WINDOW = None


def _box(label):
    """Axis-aligned box (left, bottom, right, top) of a label's glyphs in window pixels.

    pyglet's content_height is the full line box, with leading and descender space. The
    glyph box is approximated by the cap height (about 0.72 of the font size) on the same
    anchor line, which is the extent a viewer sees. The screenshots confirm the result.
    """
    w = float(label.content_width)
    h = 0.72 * float(label.font_size)
    x = float(label.x)
    y = float(label.y)
    if label.anchor_x == "center":
        left = x - w / 2.0
    elif label.anchor_x == "right":
        left = x - w
    else:
        left = x
    if label.anchor_y == "center":
        bottom = y - h / 2.0
    elif label.anchor_y == "top":
        bottom = y - h
    else:
        bottom = y
    return (left, bottom, left + w, bottom + h)


def _rect_box(shape):
    return (float(shape.x), float(shape.y), float(shape.x + shape.width), float(shape.y + shape.height))


def _button_box(btn):
    return (float(btn.x), float(btn.y), float(btn.x + btn.width), float(btn.y + btn.height))


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _inside(box, width, height):
    return box[0] >= 0 and box[1] >= 0 and box[2] <= width and box[3] <= height


def _new_menu(width=980, height=620):
    _gl()
    random.seed(1234)  # the orb backdrop uses the global random; keep construction repeatable
    return Menu(width, height)


# ---------------------------------------------------------------------------
# ui_theme: tokens, type scale, spacing and shape helpers
# ---------------------------------------------------------------------------

def test_tokens_and_type_scale():
    for name in ("background", "panel", "accent", "text", "danger", "success", "muted"):
        rgb = ui_theme.TOKENS[name]
        assert len(rgb) == 3 and all(0 <= c <= 255 for c in rgb), f"bad token {name}: {rgb}"
    assert ui_theme.font_size("display", 1.0) == 38
    assert ui_theme.font_size("heading", 1.0) == 30
    assert ui_theme.font_size("display", 1.85) > ui_theme.font_size("display", 1.0), "type must grow with scale"
    assert ui_theme.font_size("caption", 0.85) >= ui_theme.TYPE_SCALE["caption"][1], "smallest size is a floor"
    assert ui_theme.font_name("display") == "Orbitron" and ui_theme.font_name("button") == "Rajdhani"
    assert ui_theme.space("md", 2.0) == 2.0 * ui_theme.SPACING["md"]
    print("[PASS] test_tokens_and_type_scale passed (7 tokens, scaled type roles, spacing steps)")


def test_ui_scale_matches_menu_scale():
    for size in ((980, 620), (1280, 720), (1920, 1080), (640, 480), (4000, 3000)):
        assert abs(ui_theme.ui_scale(*size) - _ui_scale(*size)) < 1e-12, f"scale drift at {size}"
    assert abs(ui_theme.ui_scale(980, 620) - 1.0) < 1e-12
    print("[PASS] test_ui_scale_matches_menu_scale passed (ui_theme and menu scale agree at 5 sizes)")


def test_mix_rgb_endpoints_and_clamp():
    assert ui_theme.mix_rgb((0, 0, 0), (255, 255, 255), 0.0) == (0, 0, 0)
    assert ui_theme.mix_rgb((0, 0, 0), (255, 255, 255), 1.0) == (255, 255, 255)
    assert ui_theme.mix_rgb((0, 0, 0), (200, 100, 50), 2.0) == (200, 100, 50), "t above 1 must clamp"
    print("[PASS] test_mix_rgb_endpoints_and_clamp passed (endpoints exact, t clamped)")


def test_draw_panel_returns_deletable_shapes_and_places():
    _gl()
    batch = pyglet.graphics.Batch()
    parts = ui_theme.draw_panel(batch, 100, 50, 300, 200)
    assert len(parts) == 3, f"panel should return edge, body and shine, got {len(parts)}"
    body = parts[1]
    assert (body.x, body.y, body.width, body.height) == (100, 50, 300, 200)
    ui_theme.place_panel(parts, 10, 20, 40, 60, border_pad=2)
    assert (body.x, body.y, body.width, body.height) == (10, 20, 40, 60), "place_panel must move the body"
    assert (parts[0].x, parts[0].width) == (8, 44), "edge sits border_pad outside the body"
    for shape in parts:
        shape.delete()
    assert all(getattr(s, "_vertex_list", None) is None for s in parts), "delete() must free every shape"
    print("[PASS] test_draw_panel_returns_deletable_shapes_and_places passed (3 parts, placed, freed)")


def test_draw_chip_width_active_and_delete():
    _gl()
    batch = pyglet.graphics.Batch()
    short = ui_theme.draw_chip(batch, 0, 0, "A")
    long = ui_theme.draw_chip(batch, 0, 0, "SPACE BAR")
    assert len(short) == 3 and len(long) == 3, "chip returns edge, body and label"
    assert long[1].width > short[1].width, "a longer label makes a wider chip"
    assert abs(short[1].width - ui_theme.chip_width("A")) < 1e-9, "chip width matches chip_width()"
    idle = ui_theme.draw_chip(batch, 0, 0, "ON", active=False)
    on = ui_theme.draw_chip(batch, 0, 0, "ON", active=True)
    assert tuple(idle[1].color[:3]) != tuple(on[1].color[:3]), "active chip takes the accent fill"
    assert tuple(on[1].color[:3]) == tuple(ui_theme.ACCENT)
    for shape in short + long + idle + on:
        shape.delete()
    print("[PASS] test_draw_chip_width_active_and_delete passed (width follows text, active fill differs, freed)")


# ---------------------------------------------------------------------------
# config flag and title-screen shimmer maths
# ---------------------------------------------------------------------------

def test_reduce_motion_flag_defaults_false():
    assert hasattr(config, "REDUCE_MOTION"), "config.REDUCE_MOTION must exist"
    assert config.REDUCE_MOTION is False, "REDUCE_MOTION must default to False"
    print("[PASS] test_reduce_motion_flag_defaults_false passed (config.REDUCE_MOTION is False)")


def test_shimmer_levels_sweep_left_to_right():
    assert title_fx.shimmer_levels(0, 1.0) == [], "no letters, no levels"
    rest = title_fx.shimmer_levels(6, 4.0)  # phase 0.8 is past the active share, so the band rests
    assert rest == [0.0] * 6, f"band should rest between sweeps, got {rest}"
    peaks = []
    for step in range(0, 34):
        t = step * 0.05  # one sweep runs across the first 34% of a 5 s cycle
        levels = title_fx.shimmer_levels(6, t)
        assert all(0.0 <= v <= 1.0 for v in levels), "levels stay in 0..1"
        peaks.append(max(range(6), key=lambda i: levels[i]) if max(levels) > 0.05 else None)
    seen = [p for p in peaks if p is not None]
    assert seen == sorted(seen), f"the band should move left to right, peaks were {seen}"
    assert seen[0] == 0 and seen[-1] == 5, f"the band should cross every letter, peaks were {seen}"
    print("[PASS] test_shimmer_levels_sweep_left_to_right passed (rest is 0, band moves 0 to 5, values in 0..1)")


def test_shimmer_text_applies_per_letter_colour():
    _gl()
    menu = _new_menu()
    doc = menu.title.document
    assert isinstance(doc, pyglet.text.document.FormattedDocument), "wordmark must hold a formatted document"
    assert menu.title.text == "P L O U T O", "wordmark text is unchanged"
    menu.update(0.733)  # band centred on the third letter, the O at character 4
    assert doc.get_style("color", 4) == (255, 255, 255, 255), f"peak letter colour: {doc.get_style('color', 4)}"
    assert doc.get_style("color", 10)[:3] == tuple(ui_theme.ACCENT), "far letter stays at the accent colour"
    print("[PASS] test_shimmer_text_applies_per_letter_colour passed (peak letter white, far letter accent)")


# ---------------------------------------------------------------------------
# title screen: actions, reduced motion, layout
# ---------------------------------------------------------------------------

def test_title_buttons_keep_text_and_actions():
    menu = _new_menu()
    # Wave 2 adds Daily Run and Hangar to the title, so the stack has six buttons in this order.
    expected = [("Start Game", "start_game"), ("Daily Run", "daily"), ("Guide", "guide"), ("Settings", "settings"), ("Hangar", "hangar"), ("Quit", "quit")]
    assert [b.text for b in menu.buttons] == [t for t, _ in expected], "button labels must not change"
    for btn, (_, action) in zip(menu.buttons, expected):
        cx = btn.x + btn.width / 2.0
        cy = btn.y + btn.height / 2.0
        got = menu.on_mouse_press(cx, cy, pyglet.window.mouse.LEFT)
        assert got == action, f"{btn.text} returned {got!r}, expected {action!r}"
    assert menu.on_mouse_press(1.0, 1.0, pyglet.window.mouse.LEFT) is None, "a miss returns None"
    assert menu.on_mouse_press(menu.buttons[0].x, menu.buttons[0].y, pyglet.window.mouse.RIGHT) is None, "only LMB acts"
    print("[PASS] test_title_buttons_keep_text_and_actions passed (6 labels and actions in order, misses ignored)")


def test_reduced_motion_freezes_title_animation():
    _gl()
    original = config.REDUCE_MOTION
    try:
        config.REDUCE_MOTION = True
        menu = _new_menu()
        base_title_y = menu.title.y
        base_buttons = [(b.x, b.y) for b in menu.buttons]
        base_colours = menu._wordmark.colours
        base_stars = menu._stars.positions()
        base_orbs = [(o.x, o.y, o.opacity) for o, _, _, _ in menu._orbs]
        for _ in range(360):  # six seconds at 60 fps
            menu.update(1.0 / 60.0)
        assert menu.title.y == base_title_y, "title bobbing must stop"
        assert [(b.x, b.y) for b in menu.buttons] == base_buttons, "button bobbing must stop"
        assert menu._wordmark.colours == base_colours and len(set(base_colours)) == 1, "shimmer must stop"
        assert menu._stars.positions() == base_stars, "stars must hold"
        assert [(o.x, o.y, o.opacity) for o, _, _, _ in menu._orbs] == base_orbs, "orb drift must hold"

        config.REDUCE_MOTION = False
        moving = _new_menu()
        y0 = moving.title.y
        b0 = [(b.x, b.y) for b in moving.buttons]
        for _ in range(60):
            moving.update(1.0 / 60.0)
        assert moving.title.y != y0 or [(b.x, b.y) for b in moving.buttons] != b0, "motion must run when not reduced"
        assert len(set(moving._wordmark.colours)) > 1, "the shimmer must run when not reduced"
    finally:
        config.REDUCE_MOTION = original
    print("[PASS] test_reduced_motion_freezes_title_animation passed (title, buttons, shimmer, stars, orbs all still)")


def _check_title_frame(menu, width, height, label):
    texts = {"logo": _box(menu.title), "tagline": _box(menu.subtitle)}
    buttons = {btn.text: _button_box(btn) for btn in menu.buttons}
    hints = [_box(obj) for obj in menu._hint_parts if isinstance(obj, pyglet.text.Label)]
    panel = _rect_box(menu._panel[1])
    names = list(texts.items()) + list(buttons.items())
    for name, box in names:
        assert _inside(box, width, height), f"{name} leaves the window at {width}x{height} ({label}): {box}"
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a_name, a = names[i]
            b_name, b = names[j]
            assert not _overlaps(a, b), f"{a_name} overlaps {b_name} at {width}x{height} ({label})"
    for box in hints:
        assert _inside(box, width, height), f"hint leaves the window at {width}x{height} ({label})"
        assert not _overlaps(box, texts["logo"]) and not _overlaps(box, texts["tagline"]), "hint overlaps the header"
        assert not _overlaps(box, panel), f"hint overlaps the button panel at {width}x{height} ({label})"


def test_title_layout_has_no_text_overlap():
    _gl()
    for width, height in ((980, 620), (1280, 720), (1920, 1080)):
        menu = _new_menu(width, height)
        _check_title_frame(menu, width, height, "t=0")
        # Sample four seconds of bob and wave motion, so the check covers the moving extremes.
        for step in range(40):
            menu.update(0.1)
            _check_title_frame(menu, width, height, f"t={0.1 * (step + 1):.1f}")
        print(f"[PASS] title layout at {width}x{height}: logo, tagline, 4 buttons and hints never overlap over 4 s of bob")


def test_hint_row_resize_does_not_leak():
    _gl()
    menu = _new_menu()
    count = len(menu._hint_parts)
    assert count == 4 * len(menu.HINTS), f"each hint is edge, body, key label and action label: {count}"
    for size in ((1280, 720), (1920, 1080), (980, 620), (1920, 1080)):
        menu.resize(*size)
    assert len(menu._hint_parts) == count, f"hint shapes must be rebuilt, not added: {len(menu._hint_parts)} != {count}"
    labels = [obj.text for obj in menu._hint_parts if isinstance(obj, pyglet.text.Label)]
    for key, action in menu.HINTS:
        assert key in labels and action in labels, f"hint {key} {action} missing from the row"
    print("[PASS] test_hint_row_resize_does_not_leak passed (rebuilt on resize, every key and action present)")


def test_starfield_wraps_and_stays_in_bounds():
    _gl()
    batch = pyglet.graphics.Batch()
    field = title_fx.Starfield(batch, 980, 620)
    before = field.star_count
    assert before > 0
    start = field.positions()
    field.update(1.0 / 60.0)
    assert field.positions() != start, "stars must drift when motion is on"
    for _ in range(600):
        field.update(1.0 / 60.0)
    for x, y in field.positions():
        assert 0.0 <= x < 980.0, f"star escaped the wrap at x={x}"
        assert 0.0 <= y <= 620.0, f"star left the screen vertically at y={y}"
    same = field._layers[0]["vl"]
    field.resize(980, 620)
    assert field._layers[0]["vl"] is same, "resize to the same size must not rebuild"
    field.resize(1920, 1080)
    assert field.star_count > before, "a bigger window gets more stars"
    assert field.star_count < 4 * before, "star count grows with the square root of the area, not the area"
    print(f"[PASS] test_starfield_wraps_and_stays_in_bounds passed ({before} stars at 980x620, wraps, no rebuild on same size)")


def test_starfield_uses_local_rng():
    _gl()
    random.seed(99)
    expected = random.random()
    random.seed(99)
    title_fx.Starfield(pyglet.graphics.Batch(), 980, 620)
    assert random.random() == expected, "the starfield must not consume the global random stream"
    print("[PASS] test_starfield_uses_local_rng passed (global random stream untouched)")


def test_horizon_spans_width():
    _gl()
    horizon = title_fx.Horizon(pyglet.graphics.Batch(), 980, 99)
    sprite = horizon._sprite
    assert abs(sprite.scale_x * title_fx.HORIZON_TEX_W - 980) < 1e-6, "horizon must cover the full width"
    horizon.place(1920, 120)
    assert abs(sprite.scale_x * title_fx.HORIZON_TEX_W - 1920) < 1e-6
    assert abs(sprite.y + title_fx.HORIZON_TEX_H / 2.0 - 120) < 1e-6, "horizon is centred on its y"
    print("[PASS] test_horizon_spans_width passed (covers 980 and 1920 wide, centred on y)")


# ---------------------------------------------------------------------------
# boss reward menu header
# ---------------------------------------------------------------------------

def test_reward_header_uses_theme_tokens():
    _gl()
    menu = BossRewardMenu(980, 620, lambda k, d: None, lambda k: None)
    s = min(_ui_scale(980, 620), 1.45)
    assert menu.title.font_name == ui_theme.font_name("heading")
    assert menu.title.font_size == ui_theme.font_size("heading", s), "header size must come from the type scale"
    assert menu.subtitle.font_name == ui_theme.font_name("subhead")
    assert tuple(menu.title.color[:3]) == tuple(ui_theme.TEXT), "header title colour must be the theme text token"
    assert tuple(menu.subtitle.color[:3]) == tuple(ui_theme.MUTED), "subtitle colour must be the theme muted token"
    assert menu.section.font_name == ui_theme.font_name("section")
    print("[PASS] test_reward_header_uses_theme_tokens passed (title, subtitle and section use the theme)")


def test_reward_header_does_not_hit_the_cards():
    _gl()
    menu = BossRewardMenu(980, 620, lambda k, d: None, lambda k: None)
    menu.begin(
        [{"key": "temp_overdrive", "title": "Overdrive", "desc": "+28% damage", "duration": 2}],
        [],
    )
    for _ in range(12):
        menu.update(0.1)
    menu._place_all()
    header = [_box(menu.eyebrow), _box(menu.title), _box(menu.subtitle), _box(menu.section)]
    card_top = menu._card_top
    for box in header:
        assert box[1] >= card_top - 1, f"a header label sits on top of the first card: {box} vs {card_top}"
    print("[PASS] test_reward_header_does_not_hit_the_cards passed (header labels clear the card stack)")


def run_all():
    try:
        test_tokens_and_type_scale()
        test_ui_scale_matches_menu_scale()
        test_mix_rgb_endpoints_and_clamp()
        test_draw_panel_returns_deletable_shapes_and_places()
        test_draw_chip_width_active_and_delete()
        test_reduce_motion_flag_defaults_false()
        test_shimmer_levels_sweep_left_to_right()
        test_shimmer_text_applies_per_letter_colour()
        test_title_buttons_keep_text_and_actions()
        test_reduced_motion_freezes_title_animation()
        test_title_layout_has_no_text_overlap()
        test_hint_row_resize_does_not_leak()
        test_starfield_wraps_and_stays_in_bounds()
        test_starfield_uses_local_rng()
        test_horizon_spans_width()
        test_reward_header_uses_theme_tokens()
        test_reward_header_does_not_hit_the_cards()
    finally:
        _close_gl()
    print("\nALL WAVE-1 UITHEME TESTS PASSED")


if __name__ == "__main__":
    run_all()
