"""Regression tests for the swarm/shake item: stacking, capped, damage-scaled screen shake and the reduced-shake setting."""

import json
import os
import tempfile

import pyglet

import audio
import config
import shake_prefs
from enemy import Enemy
from game import Game
from menu import SettingsMenu
from projectile import Projectile
from states import GameStateName, add_shake
from utils import Vec2


class _Shake:
    """Minimal stand-in for a run state: only the shake amplitude matters to these tests."""

    def __init__(self, shake: float = 0.0):
        self.shake = float(shake)


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Call update() directly, as test_polish.py does, so the fixed-step simulation runs exactly once per call.
    for _ in range(frames):
        g.dispatch_events()
        g.update(1.0 / 60.0)


def _stationary_enemy(s, hp: int = 100000):
    # A chaser with zero speed never moves or touches the player, so it only absorbs hits.
    e = Enemy(pos=Vec2(120.0, 0.0), hp=hp, speed=0.0, behavior="chase", max_hp=hp)
    s.enemies = [e]
    return e


def _spawn_hits(s, enemy, count: int, crit: bool = False):
    for _ in range(count):
        s.projectiles.append(
            Projectile(
                pos=Vec2(enemy.pos.x, enemy.pos.y),
                vel=Vec2(0.0, 0.0),
                damage=5,
                ttl=1.0,
                owner="player",
                projectile_type="bullet",
                is_crit=crit,
            )
        )


def _rect(b):
    return (b.x, b.y, b.x + b.width, b.y + b.height)


def _overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def test_add_shake_stacks_and_caps(g):
    config.SHAKE_SCALE = 1.0
    s = _Shake()
    add_shake(s, 5.0)
    add_shake(s, 5.0)
    assert abs(s.shake - 10.0) < 1e-9, f"impulses must stack, got {s.shake}"
    add_shake(s, 9.0)
    assert abs(s.shake - config.SHAKE_CAP) < 1e-9, f"total must cap at SHAKE_CAP, got {s.shake}"
    add_shake(s, 0.0)
    add_shake(s, -3.0)
    assert abs(s.shake - config.SHAKE_CAP) < 1e-9, "zero or negative impulses must not change shake"
    print(f"[PASS] test_add_shake_stacks_and_caps passed (impulses stack to {config.SHAKE_CAP:g} and stop there)")


def test_limited_source_holds_at_ceiling_without_lowering(g):
    config.SHAKE_SCALE = 1.0
    s = _Shake()
    for _ in range(3):
        add_shake(s, 2.0, limit=4.0)
    assert abs(s.shake - 4.0) < 1e-9, f"a limited source must stop at its ceiling, got {s.shake}"
    s.shake = 10.0
    add_shake(s, 2.0, limit=4.0)
    assert s.shake == 10.0, "a limited source must never lower shake that is already higher"
    print("[PASS] test_limited_source_holds_at_ceiling_without_lowering passed (ceiling holds, bigger shake untouched)")


def test_reduced_shake_halves_every_impulse(g):
    saved = config.SHAKE_SCALE
    try:
        config.SHAKE_SCALE = float(config.SHAKE_REDUCED_SCALE)
        s = _Shake()
        add_shake(s, 4.0)
        assert abs(s.shake - 2.0) < 1e-9, f"reduced shake must halve the impulse, got {s.shake}"
        big = _Shake()
        add_shake(big, 40.0)
        assert abs(big.shake - config.SHAKE_CAP) < 1e-9, "reduced shake still respects the cap"
        limited = _Shake()
        add_shake(limited, 2.0, limit=4.0)
        assert abs(limited.shake - 1.0) < 1e-9, f"ceiling scales with the setting, got {limited.shake}"
    finally:
        config.SHAKE_SCALE = saved
    print("[PASS] test_reduced_shake_halves_every_impulse passed (scale applies to impulses and ceilings)")


def test_player_hit_shake_scales_with_hp_lost(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    g.player.shield = 0
    g.player.invincibility_timer = 0.0
    g.player.hp = 100
    s.shake = 0.0
    g._damage_player(10)  # 2 + 10 * 0.25
    assert abs(s.shake - 4.5) < 1e-9, f"10 HP through should give 4.5 px, got {s.shake}"
    s.shake = 0.0
    g.player.invincibility_timer = 0.0
    g.player.hp = 100
    g._damage_player(100)  # 2 + 25 clamps to the 8 px player-hit maximum
    assert abs(s.shake - config.SHAKE_PLAYER_HIT_MAX) < 1e-9, f"big hits must clamp to 8 px, got {s.shake}"
    print("[PASS] test_player_hit_shake_scales_with_hp_lost passed (4.5 px for 10 HP, clamped at 8 px)")


def test_shield_absorbed_hits_add_no_shake(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    s.shake = 0.0
    g.player.invincibility_timer = 0.0
    g.player.hp = 100
    g.player.shield = 50
    g._damage_player(20)
    assert s.shake == 0.0 and g.player.hp == 100, "a fully shielded hit must add no shake and no HP loss"
    g.player.shield = 5
    g._damage_player(10)  # only 5 HP gets through: 2 + 5 * 0.25
    assert abs(s.shake - 3.25) < 1e-9, f"only the HP that gets through should shake, got {s.shake}"
    print("[PASS] test_shield_absorbed_hits_add_no_shake passed (shield hits silent, partial hits scale by HP through)")


def test_hits_during_invincibility_stay_silent(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    s.shake = 0.0
    g.player.invincibility_timer = 0.5
    g._damage_player(30)
    assert s.shake == 0.0, "hits inside the i-frame window must not shake"
    g.player.invincibility_timer = 0.0
    print("[PASS] test_hits_during_invincibility_stay_silent passed (i-frame early return keeps shake quiet)")


def test_basic_and_crit_hit_impulses(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    s.wave_active = True
    e = _stationary_enemy(s)
    decay = float(config.SHAKE_DECAY) * float(g.balance.fixed_dt)

    s.shake = 0.0
    _spawn_hits(s, e, 1)
    _tick(g)
    assert abs(s.shake - (config.SHAKE_HIT_IMPULSE - decay)) < 1e-6, f"basic hit impulse wrong: {s.shake}"

    s.shake = 0.0
    s.projectiles.clear()
    _spawn_hits(s, e, 1, crit=True)
    _tick(g)
    assert abs(s.shake - (config.SHAKE_CRIT_IMPULSE - decay)) < 1e-6, f"crit hit impulse wrong: {s.shake}"
    print("[PASS] test_basic_and_crit_hit_impulses passed (2.0 px basic, 3.0 px crit, before decay)")


def test_multi_hit_frame_is_clamped(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    s.wave_active = True
    e = _stationary_enemy(s)
    s.shake = 0.0
    _spawn_hits(s, e, 6)  # six pellets land on one frame: 12 px raw
    _tick(g)
    decay = float(config.SHAKE_DECAY) * float(g.balance.fixed_dt)
    expected = config.SHAKE_HIT_FRAME_MAX - decay
    assert abs(s.shake - expected) < 1e-6, f"one frame of weapon hits must sum to at most {config.SHAKE_HIT_FRAME_MAX} px, got {s.shake}"
    print("[PASS] test_multi_hit_frame_is_clamped passed (six pellets in one frame add only the 3 px frame clamp)")


def test_sustained_rapid_fire_stays_under_ceiling(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    s.wave_active = True
    e = _stationary_enemy(s)
    s.shake = 0.0
    peak = 0.0
    for frame in range(240):  # four seconds of fire at one shot every five frames (about 0.083 s)
        if frame % 5 == 0:
            _spawn_hits(s, e, 1)
        _tick(g)
        peak = max(peak, s.shake)
    assert peak <= config.SHAKE_HIT_CEILING + 1e-9, f"sustained fire must stay under the {config.SHAKE_HIT_CEILING} px ceiling, peaked at {peak}"
    assert peak > config.SHAKE_HIT_IMPULSE, f"repeated hits should stack above one impulse, peaked at {peak}"
    print(f"[PASS] test_sustained_rapid_fire_stays_under_ceiling passed (peak {peak:.2f} px, ceiling {config.SHAKE_HIT_CEILING:g})")


def test_shake_decays_at_configured_rate(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    s.enemies = []
    s.wave_active = False
    dt = float(g.balance.fixed_dt)
    s.shake = 10.0
    _tick(g)
    assert abs(s.shake - (10.0 - config.SHAKE_DECAY * dt)) < 1e-6, f"decay should use SHAKE_DECAY, got {s.shake}"

    saved = config.SHAKE_DECAY
    try:
        config.SHAKE_DECAY = 40.0
        s.shake = 10.0
        _tick(g)
        assert abs(s.shake - (10.0 - 40.0 * dt)) < 1e-6, f"decay must follow the config value, got {s.shake}"
    finally:
        config.SHAKE_DECAY = saved
    print("[PASS] test_shake_decays_at_configured_rate passed (linear decay read from config each frame)")


def test_draw_clamps_shake_amplitude_to_cap(g):
    config.SHAKE_SCALE = 1.0
    s = _new_run(g)
    s.shake = 99.0  # set directly, past the cap
    seen = []
    original = g.visuals.sync_scene

    def capture(t, shake, combat_intensity=0.0):
        seen.append(shake)
        return original(t, shake, combat_intensity=combat_intensity)

    g.visuals.sync_scene = capture
    try:
        for _ in range(20):
            g.on_draw()
    finally:
        g.visuals.sync_scene = original
        s.shake = 0.0
    assert seen, "draw should reach the visuals"
    limit = config.SHAKE_CAP + 1e-9
    assert all(abs(v.x) <= limit and abs(v.y) <= limit for v in seen), "draw offsets must never exceed SHAKE_CAP"
    assert any(abs(v.x) > 0.0 or abs(v.y) > 0.0 for v in seen), "shake should move the view while active"
    print("[PASS] test_draw_clamps_shake_amplitude_to_cap passed (render offsets bounded by the cap)")


def test_reduced_shake_setting_wires_through_game_and_persists(g):
    saved_path = audio._SETTINGS_PATH
    saved_scale = config.SHAKE_SCALE
    saved_flag = bool(g.settings.get("reduced_shake", False))
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "user_settings.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump({"music_volume": 0.3}, fh)
        audio._SETTINGS_PATH = path
        try:
            assert shake_prefs.load_reduced_shake() is False, "reduced shake must default to off"
            g._on_settings_change({"reduced_shake": True})
            assert abs(config.SHAKE_SCALE - float(config.SHAKE_REDUCED_SCALE)) < 1e-9, "turning the setting on must set the scale"
            assert g.settings["reduced_shake"] is True
            assert g.settings_menu.reduced_shake is True
            assert g.settings_menu.shake_button.text == "Reduced: On"
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            assert data.get("reduced_shake") is True, "the flag must be written to user_settings.json"
            assert data.get("music_volume") == 0.3, "saving the flag must keep the audio volume key"
            assert shake_prefs.load_reduced_shake() is True

            g._on_settings_change({"reduced_shake": False})
            assert config.SHAKE_SCALE == 1.0, "turning the setting off must restore full shake"
            assert shake_prefs.load_reduced_shake() is False
        finally:
            audio._SETTINGS_PATH = saved_path
            config.SHAKE_SCALE = saved_scale
            g.settings["reduced_shake"] = saved_flag
            g.settings_menu.reduced_shake = saved_flag
            g.settings_menu._refresh_shake_button_text()
    print("[PASS] test_reduced_shake_setting_wires_through_game_and_persists passed (scale, menu and file stay in sync)")


def test_reduced_shake_file_defaults_and_bad_json(g):
    saved_path = audio._SETTINGS_PATH
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "user_settings.json")
        audio._SETTINGS_PATH = path
        try:
            assert shake_prefs.load_reduced_shake() is False, "missing file must read as off"
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("{ not json")
            assert shake_prefs.load_reduced_shake(default=False) is False, "unreadable file must not raise"
            shake_prefs.save_reduced_shake(True)
            assert shake_prefs.load_reduced_shake() is True, "a save must recover from a corrupt file"
        finally:
            audio._SETTINGS_PATH = saved_path
    print("[PASS] test_reduced_shake_file_defaults_and_bad_json passed (missing or corrupt file never raises)")


def test_settings_menu_toggle_defaults_off_and_responds_to_click(g):
    captured = []
    m = SettingsMenu(980, 620, captured.append)
    assert m.reduced_shake is False and m.get_settings()["reduced_shake"] is False, "reduced shake must default to off"
    assert m.shake_button.text == "Reduced: Off"
    btn = m.shake_button
    m.on_mouse_press(btn.x + btn.width / 2.0, btn.y + btn.height / 2.0, pyglet.window.mouse.LEFT)
    assert captured and captured[-1]["reduced_shake"] is True, "clicking the toggle must report the new value to the owner"
    assert m.shake_button.text == "Reduced: On"
    print("[PASS] test_settings_menu_toggle_defaults_off_and_responds_to_click passed (default off, click reports on)")


def test_shake_toggle_clear_of_footer_and_size_grid(g):
    for display in ((1920, 1080), (3840, 2160)):
        m = SettingsMenu(980, 620, lambda d: None, display_size=display)
        m.resize(980, 620)
        toggle = _rect(m.shake_button)
        assert not _overlap(toggle, _rect(m.back_button)), f"toggle overlaps Back on a {display} display"
        for i, sb in enumerate(m.size_buttons):
            assert not _overlap(toggle, _rect(sb)), f"toggle overlaps window-size button {i} on a {display} display"
        label_box = (m.shake_label.x - 130, m.shake_label.y - 10, m.shake_label.x, m.shake_label.y + 10)
        assert not _overlap(label_box, _rect(m.back_button)), f"label overlaps Back on a {display} display"
        assert toggle[2] <= m._panel.x + m._panel.width, "toggle must stay inside the settings panel"
    print("[PASS] test_shake_toggle_clear_of_footer_and_size_grid passed (no overlap at 980x620 on 1080p or 4K displays)")


def run_all():
    g = Game()
    g.set_visible(False)
    saved_scale = config.SHAKE_SCALE
    try:
        test_add_shake_stacks_and_caps(g)
        test_limited_source_holds_at_ceiling_without_lowering(g)
        test_reduced_shake_halves_every_impulse(g)
        test_player_hit_shake_scales_with_hp_lost(g)
        test_shield_absorbed_hits_add_no_shake(g)
        test_hits_during_invincibility_stay_silent(g)
        test_basic_and_crit_hit_impulses(g)
        test_multi_hit_frame_is_clamped(g)
        test_sustained_rapid_fire_stays_under_ceiling(g)
        test_shake_decays_at_configured_rate(g)
        test_draw_clamps_shake_amplitude_to_cap(g)
        test_reduced_shake_setting_wires_through_game_and_persists(g)
        test_reduced_shake_file_defaults_and_bad_json(g)
        test_settings_menu_toggle_defaults_off_and_responds_to_click(g)
        test_shake_toggle_clear_of_footer_and_size_grid(g)
    finally:
        config.SHAKE_SCALE = saved_scale
        g.close()
    print("\nALL SWARM SHAKE REGRESSION TESTS PASSED")


if __name__ == "__main__":
    run_all()
