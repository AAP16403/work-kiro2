"""Wave 3 accessibility tests: the Settings toggles, their persistence, and the keyboard navigation.

Covers the colour-blind enemy palette (checked with the Machado 2009 colour-vision simulation and CIE76
distance), the high-contrast HUD (brighter text and a dark plate behind every number), the reduced-motion
switch (shake, pulses, shimmer and drift), arrow-key and ENTER navigation of the Settings screen, and the
unchanged mouse path. Every file write goes to a temporary folder, never to the real user_settings.json.
"""

import json
import math
import os
import subprocess
import sys
import tempfile

import pyglet

import access_prefs
import audio
import config
import motion
from game import Game
from menu import Menu, MenuSlider, SettingsMenu
from states import GameStateName, add_shake
from visuals import GroupCache, Visuals
from utils import Vec2

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = pyglet.window.key
MOUSE_LEFT = pyglet.window.mouse.LEFT


class _Shake:
    """Minimal stand-in for a run state: only the shake amplitude matters here."""

    def __init__(self, shake: float = 0.0):
        self.shake = float(shake)


def _rect(item):
    return (float(item.x), float(item.y), float(item.x) + float(item.width), float(item.y) + float(item.height))


def _overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def _label_box(label):
    w = float(label.content_width)
    h = float(label.content_height)
    x0 = label.x - (w if label.anchor_x == "right" else w / 2.0 if label.anchor_x == "center" else 0.0)
    y0 = label.y - (h / 2.0 if label.anchor_y == "center" else 0.0)
    return (x0, y0, x0 + w, y0 + h)


def _reset_runtime(saved):
    config.REDUCE_MOTION = saved["reduce"]
    config.HIGH_CONTRAST_HUD = saved["contrast"]
    config.COLORBLIND_PALETTE = saved["colorblind"]
    config.SHAKE_SCALE = saved["shake_scale"]
    access_prefs.set_colorblind_palette(saved["colorblind"])


# ----- colour-vision maths (same model as the palette search) -----------------

_DEUT = [[0.367322, 0.860646, -0.227968], [0.280085, 0.672501, 0.047413], [-0.011820, 0.042940, 0.968881]]
_PROT = [[0.152286, 1.052583, -0.204868], [0.114503, 0.786281, 0.099216], [-0.003882, -0.048116, 1.051998]]


def _lin(c):
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _to_lab(rgb):
    r, g, b = (_lin(x) for x in rgb)
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116

    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def _simulate(rgb, matrix):
    lin = [_lin(c) for c in rgb]
    return tuple(sum(matrix[i][j] * lin[j] for j in range(3)) for i in range(3))


def _lab_views(rgb):
    """Lab of the colour as seen by a normal, a deuteranope and a protanope (linear values clipped to 0..1)."""
    def clip(lin3):
        return tuple(min(1.0, max(0.0, v)) for v in lin3)

    def to_srgb_bytes(lin3):
        out = []
        for v in clip(lin3):
            c = 12.92 * v if v <= 0.0031308 else 1.055 * (v ** (1 / 2.4)) - 0.055
            out.append(int(round(c * 255.0)))
        return tuple(out)

    return (
        _to_lab(rgb),
        _to_lab(to_srgb_bytes(_simulate(rgb, _DEUT))),
        _to_lab(to_srgb_bytes(_simulate(rgb, _PROT))),
    )


def _min_separation(palette: dict, keys) -> dict:
    worst = {"normal": 1e9, "deuteranopia": 1e9, "protanopia": 1e9}
    names = ("normal", "deuteranopia", "protanopia")
    keys = list(keys)
    for i, a in enumerate(keys):
        va = _lab_views(palette[a])
        for b in keys[i + 1:]:
            vb = _lab_views(palette[b])
            for idx, name in enumerate(names):
                worst[name] = min(worst[name], math.dist(va[idx], vb[idx]))
    return worst


# ----- tests -------------------------------------------------------------------

def test_access_settings_round_trip_keeps_other_keys_and_survives_bad_files():
    saved_path = audio._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "user_settings.json")
        audio._SETTINGS_PATH = path
        try:
            assert access_prefs.load_access_settings() == {
                access_prefs.REDUCED_MOTION_KEY: False,
                access_prefs.COLORBLIND_KEY: False,
                access_prefs.HIGH_CONTRAST_KEY: False,
            }, "a missing file must read as all three options off"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"music_volume": 0.4, "shake_level": "reduced", "reduced_shake": True}, fh)
            access_prefs.save_access_settings({
                access_prefs.REDUCED_MOTION_KEY: True,
                access_prefs.COLORBLIND_KEY: True,
                access_prefs.HIGH_CONTRAST_KEY: False,
            })
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            assert data["music_volume"] == 0.4 and data["shake_level"] == "reduced", "audio and shake keys must survive"
            assert data["reduced_motion"] is True and data["colorblind_palette"] is True and data["high_contrast_hud"] is False
            loaded = access_prefs.load_access_settings()
            assert loaded[access_prefs.REDUCED_MOTION_KEY] is True and loaded[access_prefs.COLORBLIND_KEY] is True
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ truncated")
            assert access_prefs.load_access_settings()[access_prefs.HIGH_CONTRAST_KEY] is False, "a truncated file reads as defaults"
            access_prefs.save_access_settings({access_prefs.HIGH_CONTRAST_KEY: True})
            assert access_prefs.load_access_settings()[access_prefs.HIGH_CONTRAST_KEY] is True, "a save recovers from a truncated file"
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"reduced_motion": "yes", "colorblind_palette": 2}, fh)
            loaded = access_prefs.load_access_settings()
            assert loaded[access_prefs.REDUCED_MOTION_KEY] is False and loaded[access_prefs.COLORBLIND_KEY] is False, \
                "non-boolean values fall back to the config defaults"
        finally:
            audio._SETTINGS_PATH = saved_path
    print("[PASS] test_access_settings_round_trip_keeps_other_keys_and_survives_bad_files passed (shared file, defaults, corrupt file)")


def test_each_setting_persists_through_the_game_and_changes_its_value(g, saved):
    saved_path = audio._SETTINGS_PATH
    checks = (
        ("reduced_motion", "REDUCE_MOTION", access_prefs.REDUCED_MOTION_KEY),
        ("colorblind_palette", "COLORBLIND_PALETTE", access_prefs.COLORBLIND_KEY),
        ("high_contrast_hud", "HIGH_CONTRAST_HUD", access_prefs.HIGH_CONTRAST_KEY),
    )
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "user_settings.json")
        audio._SETTINGS_PATH = path
        try:
            for settings_key, config_name, file_key in checks:
                g._on_settings_change({settings_key: True})
                assert getattr(config, config_name) is True, f"{settings_key} on must set config.{config_name}"
                with open(path, "r", encoding="utf-8") as fh:
                    assert json.load(fh)[file_key] is True, f"{settings_key} on must be written to user_settings.json"
                assert access_prefs.load_access_settings()[file_key] is True
                g._on_settings_change({settings_key: False})
                assert getattr(config, config_name) is False, f"{settings_key} off must clear config.{config_name}"
                assert access_prefs.load_access_settings()[file_key] is False, f"{settings_key} off must persist"
                assert g.settings_menu.get_settings()[settings_key] is False, "the menu mirrors the applied value"
        finally:
            audio._SETTINGS_PATH = saved_path
    print("[PASS] test_each_setting_persists_through_the_game_and_changes_its_value passed (on and off reach config and user_settings.json)")


def test_colorblind_setting_swaps_enemy_colors_in_place(g, saved):
    import states
    import visuals
    original_dict = config.ENEMY_COLORS
    standard = dict(config.ENEMY_COLORS)
    saved_path = audio._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        audio._SETTINGS_PATH = os.path.join(tmp, "user_settings.json")
        try:
            g._on_settings_change({"colorblind_palette": True})
            assert config.ENEMY_COLORS is original_dict, "the palette must be swapped in place so imported references see it"
            assert states.ENEMY_COLORS is original_dict and visuals.ENEMY_COLORS is original_dict
            assert dict(config.ENEMY_COLORS) == dict(config.COLORBLIND_ENEMY_COLORS), "palette on must hold the colour-blind values"
            assert dict(config.ENEMY_COLORS) != standard
            g._on_settings_change({"colorblind_palette": False})
            assert dict(config.ENEMY_COLORS) == standard, "palette off must restore the standard values exactly"
        finally:
            audio._SETTINGS_PATH = saved_path
            access_prefs.set_colorblind_palette(saved["colorblind"])
    print("[PASS] test_colorblind_setting_swaps_enemy_colors_in_place passed (same dict object, values change and restore)")


def test_colorblind_palette_keeps_all_enemies_apart_under_colour_blindness():
    keys = sorted(config.COLORBLIND_ENEMY_COLORS)
    assert keys == sorted(access_prefs._STANDARD_ENEMY_COLORS), "the palette must cover exactly the enemy keys"
    palette = config.COLORBLIND_ENEMY_COLORS
    worst = _min_separation(palette, keys)
    assert worst["deuteranopia"] >= 12.0, f"deuteranopia min dE76 {worst['deuteranopia']:.2f} is below 12"
    assert worst["protanopia"] >= 12.0, f"protanopia min dE76 {worst['protanopia']:.2f} is below 12"
    assert worst["normal"] >= 20.0, f"normal vision min dE76 {worst['normal']:.2f} is below 20"
    standard = _min_separation(access_prefs._STANDARD_ENEMY_COLORS, keys)
    assert standard["deuteranopia"] < 12.0, "the standard palette is expected to fail this check (it shows the check bites)"
    print(
        "[PASS] test_colorblind_palette_keeps_all_enemies_apart_under_colour_blindness passed "
        f"(min dE76 normal {worst['normal']:.1f}, deuteranopia {worst['deuteranopia']:.1f}, protanopia {worst['protanopia']:.1f}; "
        f"standard palette deuteranopia {standard['deuteranopia']:.1f})"
    )


def test_high_contrast_setting_brightens_hud_text_and_adds_number_plates(g, saved):
    saved_path = audio._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        audio._SETTINGS_PATH = os.path.join(tmp, "user_settings.json")
        try:
            g._init_game()
            hud = g.hud
            label = hud.score_title_label
            base = (214, 200, 160, 220)
            assert tuple(label.color)[:3] == base[:3], "high contrast starts off, so the base colour shows"
            hud.hp_value_label.text = "100/100"
            hud._sync_number_plates()
            assert all(plate.opacity == 0 for _lbl, plate in hud._number_pairs), "no plates while high contrast is off"

            g._on_settings_change({"high_contrast_hud": True})
            assert hud.high_contrast is True
            lifted = tuple(label.color)
            assert lifted[3] == 255, "high-contrast text is fully opaque"
            assert all(lifted[i] > base[i] for i in range(3)), f"every channel is brighter ({lifted} vs {base})"
            hud._sync_number_plates()
            value_label = hud.hp_value_label
            plate = dict((id(lbl), p) for lbl, p in hud._number_pairs)[id(value_label)]
            assert plate.opacity > 0, "a plate shows behind a HUD number in high contrast"
            x0, y0, x1, y1 = _label_box(value_label)
            assert plate.x <= x0 and plate.x + plate.width >= x1, "the plate spans the number horizontally"
            plate_mid = plate.y + plate.height / 2.0
            assert y0 <= plate_mid <= y1, "the plate sits on the number vertically"
            assert plate.height < (y1 - y0) * 1.6, "the plate hugs the glyphs and does not stretch over the line box"
            empty = [p for lbl, p in hud._number_pairs if not str(lbl.text or "").strip()]
            assert empty and all(p.opacity == 0 for p in empty), "empty readouts get no plate"
            assert hud._plate_group.order < hud._text_group.order, "plates draw under the text"
            covered = [lbl for lbl, _p in hud._number_pairs]
            for name in ("hp_value_label", "shield_value_label", "boost_value_label", "score_value_label",
                         "combo_label", "wave_label", "meta_label", "status_label", "weapon_label", "boss_pct_label"):
                assert any(lbl is getattr(hud, name) for lbl in covered), f"{name} has a number plate"

            g._on_settings_change({"high_contrast_hud": False})
            assert tuple(label.color)[:3] == base[:3], "turning high contrast off restores the base colour"
            hud._sync_number_plates()
            assert plate.opacity == 0, "plates hide again"
        finally:
            audio._SETTINGS_PATH = saved_path
            config.HIGH_CONTRAST_HUD = saved["contrast"]
    print("[PASS] test_high_contrast_setting_brightens_hud_text_and_adds_number_plates passed (brighter text, plates over every number, drawn under text)")


def test_reduced_motion_setting_stops_shake(g, saved):
    saved_path = audio._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        audio._SETTINGS_PATH = os.path.join(tmp, "user_settings.json")
        try:
            config.SHAKE_SCALE = 1.0
            s = _Shake(0.0)
            add_shake(s, 10.0)
            assert s.shake > 0.0, "control: shake works with reduced motion off"
            g._on_settings_change({"reduced_motion": True})
            assert config.REDUCE_MOTION is True and motion.factor() == 0.0
            s = _Shake(0.0)
            add_shake(s, 10.0)
            add_shake(s, 8.0, limit=4.0)
            assert s.shake == 0.0, "with reduced motion no impulse reaches the shake amplitude"
            assert motion.clock(12.3) == 0.0 and motion.anim_dt(1 / 60) == 0.0, "pulses and animation clocks sit at rest"
            g._on_settings_change({"reduced_motion": False})
            s = _Shake(0.0)
            add_shake(s, 10.0)
            assert s.shake > 0.0, "turning reduced motion off brings shake back"
        finally:
            audio._SETTINGS_PATH = saved_path
            config.REDUCE_MOTION = saved["reduce"]
    print("[PASS] test_reduced_motion_setting_stops_shake passed (impulses are zero; shake returns when off)")


def _scene_run(reduce_on: bool):
    """Run the starfield and glow for 40 frames. Returns star positions, ring radii and star opacities at the end."""
    config.REDUCE_MOTION = reduce_on
    vis = Visuals(pyglet.graphics.Batch(), GroupCache())
    for step in range(40):
        vis.sync_scene(0.5 * step, Vec2(0.0, 0.0), combat_intensity=1.0)
    stars = [(round(s.x, 3), round(s.y, 3), s.opacity) for s, _vx, _vy, _ph in vis._scene_stars]
    rings = [round(r.radius, 3) for r in vis._scene_rings]
    return stars, rings


def _menu_run(make, reduce_on: bool):
    """Advance a menu for 30 frames. Returns its drifting orb positions and the title height."""
    config.REDUCE_MOTION = reduce_on
    menu = make()
    orbs_start = [(round(o.x, 3), round(o.y, 3)) for o, *_ in menu._orbs]
    for _ in range(30):
        menu.update(1.0 / 30.0)
    orbs_end = [(round(o.x, 3), round(o.y, 3)) for o, *_ in menu._orbs]
    return orbs_start, orbs_end, menu


def test_reduced_motion_freezes_starfield_glow_and_menu_drift(g, saved):
    saved_path = audio._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        audio._SETTINGS_PATH = os.path.join(tmp, "user_settings.json")
        try:
            # Star start positions are random per instance, so every comparison below stays inside one instance.
            moving_rings = _scene_run(False)[1]
            still_rings = _scene_run(True)[1]
            vis = Visuals(pyglet.graphics.Batch(), GroupCache())
            start = [(s.x, s.y) for s, *_ in vis._scene_stars]
            config.REDUCE_MOTION = True
            for step in range(40):
                vis.sync_scene(0.5 * step, Vec2(0.0, 0.0), combat_intensity=1.0)
            assert start == [(s.x, s.y) for s, *_ in vis._scene_stars], "reduced motion must not move the starfield"
            assert all(abs(r - (180 + i * 42)) < 1e-6 for i, r in enumerate(still_rings)), "ring pulses sit at their rest radius"
            config.REDUCE_MOTION = False
            vis = Visuals(pyglet.graphics.Batch(), GroupCache())
            start = [(s.x, s.y) for s, *_ in vis._scene_stars]
            for step in range(40):
                vis.sync_scene(0.5 * step, Vec2(0.0, 0.0), combat_intensity=1.0)
            assert start != [(s.x, s.y) for s, *_ in vis._scene_stars], "control: the starfield drifts when reduced motion is off"
            assert moving_rings != still_rings, "control: the glow rings pulse when reduced motion is off"

            start, end, _menu = _menu_run(lambda: SettingsMenu(980, 620, lambda d: None), True)
            assert start == end, "reduced motion: settings orbs must not drift"
            start, end, _menu = _menu_run(lambda: SettingsMenu(980, 620, lambda d: None), False)
            assert start != end, "control: settings orbs drift when reduced motion is off"

            config.REDUCE_MOTION = True
            main = Menu(980, 620)
            base_title = main.title.y
            for _ in range(30):
                main.update(1.0 / 30.0)
            assert main.title.y == base_title, "the main menu title holds its rest position"
            assert all(abs(b.x - bx) < 1e-6 for b, bx in zip(main.buttons, [bb[0] for bb in main._button_base_positions])), \
                "the main menu buttons hold their rest positions"
        finally:
            audio._SETTINGS_PATH = saved_path
            config.REDUCE_MOTION = saved["reduce"]
    print("[PASS] test_reduced_motion_freezes_starfield_glow_and_menu_drift passed (stars, rings, orbs, title and buttons hold still)")


def test_reduce_motion_config_default_is_off():
    code = "import config; print(config.REDUCE_MOTION, config.COLORBLIND_PALETTE, config.HIGH_CONTRAST_HUD)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ["False", "False", "False"], f"config defaults must stay off, got {out.stdout!r}"
    print("[PASS] test_reduce_motion_config_default_is_off passed (config defaults are False for all three options)")


def test_arrow_keys_move_focus_and_enter_activates(g):
    captured = []
    m = SettingsMenu(980, 620, captured.append, display_size=(1920, 1080))
    m.resize(980, 620)
    assert m._focus is None, "no focus until a key is pressed"
    m.on_key_press(KEY.RIGHT)
    assert m._focus is m._focus_items()[0], "the first arrow press focuses the first control"
    m._focus = m.motion_button
    m.on_key_press(KEY.LEFT)
    assert m._focus is not m.motion_button and m._focus is not None, "LEFT moves focus to a neighbour"
    assert SettingsMenu._focus_center(m._focus)[0] < SettingsMenu._focus_center(m.motion_button)[0], "LEFT goes left"
    m._focus = m.motion_button
    m.on_key_press(KEY.RIGHT)
    assert m._focus is m.contrast_button, "RIGHT moves across the accessibility row"
    m._focus = m.motion_button
    m.on_key_press(KEY.UP)
    assert SettingsMenu._focus_center(m._focus)[1] > SettingsMenu._focus_center(m.motion_button)[1], "UP moves focus up the screen"
    m._focus = m.colorblind_button
    m.on_key_press(KEY.DOWN)
    assert m._focus is m.shake_button, "DOWN from the bottom-right toggle reaches the Screen Shake button directly beneath it"
    m.on_key_press(KEY.DOWN)
    assert m._focus is m.shake_button, "nothing lies below Screen Shake, so DOWN keeps focus on it"
    m.on_key_press(KEY.LEFT)
    assert m._focus is m.back_button, "LEFT from Screen Shake reaches Back, the footer's centre button on the same row"
    m._focus = m.motion_button
    m.on_key_press(KEY.ENTER)
    assert captured and captured[-1] == {"reduced_motion": True}, "ENTER on the focused toggle reports only its key"
    assert m.reduced_motion is True and m.motion_button.text == "Motion: Reduced"
    m.on_key_press(KEY.NUM_ENTER)
    assert captured[-1] == {"reduced_motion": False}, "the keypad ENTER activates too"
    m._focus = m.shake_button
    shake_before = m.shake_level
    m.on_key_press(KEY.ENTER)
    assert m.shake_level != shake_before, "ENTER cycles the focused Screen Shake button, as a click does"
    m._focus = m.back_button
    result = m.on_key_press(KEY.ENTER)
    assert result == "back", "ENTER on Back asks the screen to close, like a click"
    assert captured[-1]["shake_level"] == m.shake_level, "Back saves the full settings"
    print("[PASS] test_arrow_keys_move_focus_and_enter_activates passed (LEFT/RIGHT/UP/DOWN move focus, ENTER activates, Back closes)")


def test_focus_ring_shows_only_after_keyboard_use_and_wraps_the_control(g):
    m = SettingsMenu(980, 620, lambda d: None, display_size=(1920, 1080))
    m.resize(980, 620)
    m._sync_focus_ring()
    assert all(edge.opacity == 0 for edge in m._focus_ring), "mouse-only use shows no focus ring"
    m.on_key_press(KEY.RIGHT)
    m._focus = m.motion_button
    m._sync_focus_ring()
    assert all(edge.opacity == 255 for edge in m._focus_ring)
    left, bottom, top, right = m._focus_ring[2], m._focus_ring[1], m._focus_ring[0], m._focus_ring[3]
    btn = m.motion_button
    assert left.x < btn.x and right.x + right.width > btn.x + btn.width, "the ring surrounds the focused control horizontally"
    assert bottom.y < btn.y and top.y + top.height > btn.y + btn.height, "the ring surrounds the focused control vertically"
    print("[PASS] test_focus_ring_shows_only_after_keyboard_use_and_wraps_the_control passed (hidden until a key, drawn around the control)")


def test_slider_grab_adjusts_with_left_and_right_and_releases(g):
    captured = []
    m = SettingsMenu(980, 620, captured.append, display_size=(1920, 1080), music_volume=0.5)
    m.resize(980, 620)
    m._focus = m.music_slider
    start = float(m.music_slider.current_val)
    m.on_key_press(KEY.ENTER)
    assert m.is_adjusting(), "ENTER on a slider grabs it"
    m.on_key_press(KEY.LEFT)
    assert abs(m.music_slider.current_val - (start - 5.0)) < 1e-9, "LEFT lowers the grabbed slider by 5"
    assert abs(captured[-1]["music_volume"] - (start - 5.0) / 100.0) < 1e-9, "the change is reported to the owner"
    m.on_key_press(KEY.RIGHT)
    m.on_key_press(KEY.RIGHT)
    assert abs(m.music_slider.current_val - (start + 5.0)) < 1e-9
    m.on_key_press(KEY.ESCAPE)
    assert not m.is_adjusting() and m._focus is m.music_slider, "ESC lets go of the slider and keeps focus on it"
    m.on_key_press(KEY.RIGHT)
    assert m._focus is not m.music_slider, "without a grab, RIGHT moves focus again"
    assert isinstance(m.music_slider, MenuSlider)
    print("[PASS] test_slider_grab_adjusts_with_left_and_right_and_releases passed (ENTER grabs, arrows change the value, ESC releases)")


def test_mouse_path_is_unchanged_and_does_not_move_focus(g):
    captured = []
    m = SettingsMenu(980, 620, captured.append, display_size=(1920, 1080))
    m.resize(980, 620)
    btn = m.motion_button
    cx, cy = btn.x + btn.width / 2.0, btn.y + btn.height / 2.0
    m.on_mouse_motion(cx, cy)
    assert btn.is_hovered, "hover still lights the toggle"
    m.on_mouse_press(cx, cy, MOUSE_LEFT)
    assert captured[-1] == {"reduced_motion": True}, "a click still toggles reduced motion"
    assert m._focus is None, "mouse use does not move keyboard focus"
    fx = m.fx_button
    fx_before = m.advanced_fx
    m.on_mouse_press(fx.x + fx.width / 2.0, fx.y + fx.height / 2.0, MOUSE_LEFT)
    assert m.advanced_fx is (not fx_before) and captured[-1]["advanced_fx"] is m.advanced_fx, "the FX button still toggles on click"
    back = m.back_button
    assert m.on_mouse_press(back.x + back.width / 2.0, back.y + back.height / 2.0, MOUSE_LEFT) == "back", "Back still returns 'back'"
    assert m.on_mouse_press(0, 0, MOUSE_LEFT) is None, "clicks on empty space do nothing"
    print("[PASS] test_mouse_path_is_unchanged_and_does_not_move_focus passed (clicks, hover and Back behave as before)")


def test_accessibility_row_clear_of_footer_and_grid(g):
    for display in ((1920, 1080), (3840, 2160), None):
        m = SettingsMenu(980, 620, lambda d: None, display_size=display)
        m.resize(980, 620)
        m._refresh_access_button_texts()
        label_box = _label_box(m.access_label)
        pieces = [_rect(b) for b in m._access_buttons()]
        for i, a in enumerate(pieces):
            assert not _overlap(a, _rect(m.back_button)), f"accessibility button {i} overlaps Back on display {display}"
            assert not _overlap(a, _rect(m.shake_button)), f"accessibility button {i} overlaps Screen Shake on display {display}"
            for sb in m.size_buttons:
                assert not _overlap(a, _rect(sb)), f"accessibility button {i} overlaps a window-size button on display {display}"
            assert not _overlap(a, label_box), f"accessibility button {i} overlaps its heading on display {display}"
            assert a[0] >= m._panel.x and a[2] <= m._panel.x + m._panel.width, "accessibility row stays inside the panel"
            assert a[1] > _rect(m.back_button)[3], f"accessibility row sits above the footer on display {display}"
        for i, btn in enumerate(m._access_buttons()):
            assert btn.font_size <= 14 and float(btn._label.content_width) <= float(btn.width) - 6.0, \
                f"toggle {i} text fits its button on display {display}"
        assert not _overlap(label_box, _rect(m.back_button)), f"heading overlaps Back on display {display}"
    print("[PASS] test_accessibility_row_clear_of_footer_and_grid passed (no overlap with Back, Screen Shake, sizes or heading; text fits)")


def test_get_settings_reports_the_three_options(g):
    m = SettingsMenu(980, 620, lambda d: None, reduced_motion=True, colorblind_palette=True, high_contrast_hud=False)
    data = m.get_settings()
    assert data["reduced_motion"] is True and data["colorblind_palette"] is True and data["high_contrast_hud"] is False
    assert m.motion_button.text == "Motion: Reduced" and m.colorblind_button.text == "Colorblind: On"
    assert m.contrast_button.text == "Contrast: Normal"
    print("[PASS] test_get_settings_reports_the_three_options passed (menu state and labels agree)")


def run_all():
    tmpdir = tempfile.TemporaryDirectory()
    saved_path = audio._SETTINGS_PATH
    audio._SETTINGS_PATH = os.path.join(tmpdir.name, "user_settings.json")
    saved = {
        "reduce": bool(config.REDUCE_MOTION),
        "contrast": bool(config.HIGH_CONTRAST_HUD),
        "colorblind": bool(config.COLORBLIND_PALETTE),
        "shake_scale": float(config.SHAKE_SCALE),
    }
    g = Game()
    g.set_visible(False)
    try:
        test_access_settings_round_trip_keeps_other_keys_and_survives_bad_files()
        test_each_setting_persists_through_the_game_and_changes_its_value(g, saved)
        test_colorblind_setting_swaps_enemy_colors_in_place(g, saved)
        test_colorblind_palette_keeps_all_enemies_apart_under_colour_blindness()
        test_high_contrast_setting_brightens_hud_text_and_adds_number_plates(g, saved)
        test_reduced_motion_setting_stops_shake(g, saved)
        test_reduced_motion_freezes_starfield_glow_and_menu_drift(g, saved)
        test_reduce_motion_config_default_is_off()
        test_arrow_keys_move_focus_and_enter_activates(g)
        test_focus_ring_shows_only_after_keyboard_use_and_wraps_the_control(g)
        test_slider_grab_adjusts_with_left_and_right_and_releases(g)
        test_mouse_path_is_unchanged_and_does_not_move_focus(g)
        test_accessibility_row_clear_of_footer_and_grid(g)
        test_get_settings_reports_the_three_options(g)
    finally:
        _reset_runtime(saved)
        audio._SETTINGS_PATH = saved_path
        g.close()
        tmpdir.cleanup()
    print("\nALL WAVE 3 ACCESSIBILITY TESTS PASSED")


if __name__ == "__main__":
    run_all()
