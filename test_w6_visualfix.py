"""Wave 6 visual fixes: the pause title clears the HUD status line, one dash afterimage per character,
and the thruster glow and low-health vignette stop at hp 0 so the death dissolve plays clean.

Covers:
  - PAUSED sits above the Resume / Quit block and no label overlaps it, at 980x620 and 1920x1080
    (the same overlap checker tools/screens.py uses, run on one drawn pause frame);
  - the pod-robot dash shows only its body-shaped ghosts, not the glow streak on top of them;
  - the legacy ship keeps the glow streak, since it has no ghosts of its own;
  - ENABLE_DASH_AFTERIMAGE off silences the pod-robot ghosts too;
  - the thruster glow and the low-health vignette are on while hp > 0 and off at hp 0.

Run with the venv python: ``python test_w6_visualfix.py``. Also collectable by pytest.
"""

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import config  # noqa: E402
import screens  # noqa: E402
from game import Game  # noqa: E402
from player import perform_dash  # noqa: E402
from states import GameStateName  # noqa: E402
from utils import Vec2  # noqa: E402

DT = 1.0 / 60.0
SIZES = ((980, 620), (1920, 1080))


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _clear_field(s):
    s.enemies = []
    s.projectiles = []


def _draw_frame(g):
    """One real draw, the way the game loop draws it. Returns the glow keys shown after the frame."""
    g.on_draw()
    return set(g.visuals._glow_pool._shown.keys())


def _dash_keys(keys):
    return [k for k in keys if isinstance(k, tuple) and k and k[0] == "dash"]


def _run_dash(g, frames=8):
    """Start a dash and run update and draw each frame. Returns (glow keys seen on the last frame, peak ghost opacity)."""
    s = g.state
    g.player.dash_charges = g.player.dash_max_charges
    perform_dash(g.player, s.time, g.balance, 1.0, 1.0, Vec2(1.0, -1.0), Vec2(0.0, 0.0))
    peak_ghost = 0.0
    keys = set()
    for _ in range(frames):
        g.update(DT)
        keys = _draw_frame(g)
        art = g.visuals._player_art
        if art is not None:
            peak_ghost = max([peak_ghost] + [float(gh.opacity) for gh in art.ghosts])
    return keys, peak_ghost


def _use_player_art(on: bool):
    saved = config.USE_PLAYER_ART
    config.USE_PLAYER_ART = on
    return saved


def test_pause_title_clear_of_hud_status_line(g):
    """PAUSED must not overlap any painted label on the pause screen, at both sizes checked by tools/screens.py."""
    w0, h0 = g.width, g.height
    try:
        for w, h in SIZES:
            screens._apply_size(g, w, h)
            _new_run(g)
            g.fsm.set_state(GameStateName.PAUSED)
            recorder = screens.DrawRecorder()
            with recorder:
                g.on_draw()
            infos, _ = screens.collect_label_infos(screens.painted_layouts(recorder), g.width, g.height)
            pairs = screens.find_overlaps(infos)
            hits = [(p.a.text, p.b.text) for p in pairs if "PAUSED" in (p.a.text, p.b.text)]
            assert not hits, f"PAUSED overlaps a label at {w}x{h}: {hits}"

            title = g.pause_menu.title
            top_button = max(b.y + b.height for b in g.pause_menu.buttons)
            assert title.y > top_button, f"PAUSED must sit above the button block at {w}x{h}"
    finally:
        screens._apply_size(g, w0, h0)
        g.fsm.set_state(GameStateName.PAUSED)
    print("[PASS] test_pause_title_clear_of_hud_status_line passed (no PAUSED overlap at 980x620 or 1920x1080)")


def test_pod_robot_dash_has_only_its_ghosts(g):
    """With the pod-robot character the dash draws its body ghosts and no glow streak."""
    saved = _use_player_art(True)
    try:
        g.visuals.sync_player(g.player, Vec2(0.0, 0.0))  # build the pod-robot character
        s = _new_run(g)
        _clear_field(s)
        keys, peak_ghost = _run_dash(g)
        assert not _dash_keys(keys), f"the glow streak must not draw over the pod-robot ghosts, saw {_dash_keys(keys)}"
        assert peak_ghost > 40.0, f"the pod-robot dash must still show its afterimage, peak ghost opacity {peak_ghost}"
    finally:
        _use_player_art(saved)
    print(f"[PASS] test_pod_robot_dash_has_only_its_ghosts passed (ghosts peak {peak_ghost:.0f}, no streak glows)")


def test_legacy_ship_keeps_glow_streak(g):
    """The legacy ship has no ghosts, so its dash keeps the glow streak."""
    saved = _use_player_art(False)
    try:
        g.visuals.sync_player(g.player, Vec2(0.0, 0.0))  # rebuild as the legacy ship
        s = _new_run(g)
        _clear_field(s)
        keys, _ = _run_dash(g)
        assert _dash_keys(keys), "the legacy ship must keep its dash glow streak"
    finally:
        _use_player_art(saved)
        g.visuals.sync_player(g.player, Vec2(0.0, 0.0))  # back to the pod-robot character
    print("[PASS] test_legacy_ship_keeps_glow_streak passed (streak glows drawn for the legacy ship)")


def test_dash_flag_off_silences_pod_ghosts(g):
    """ENABLE_DASH_AFTERIMAGE off means no dash afterimage at all, pod-robot included."""
    saved_flag = config.ENABLE_DASH_AFTERIMAGE
    saved_art = _use_player_art(True)
    config.ENABLE_DASH_AFTERIMAGE = False
    try:
        g.visuals.sync_player(g.player, Vec2(0.0, 0.0))
        s = _new_run(g)
        _clear_field(s)
        keys, peak_ghost = _run_dash(g)
        assert peak_ghost == 0.0, f"no ghost may show with ENABLE_DASH_AFTERIMAGE off, peak {peak_ghost}"
        assert not _dash_keys(keys), "no glow streak may show with ENABLE_DASH_AFTERIMAGE off"
    finally:
        config.ENABLE_DASH_AFTERIMAGE = saved_flag
        _use_player_art(saved_art)
    print("[PASS] test_dash_flag_off_silences_pod_ghosts passed (no afterimage with the switch off)")


def test_thruster_and_vignette_stop_at_zero_hp(g):
    """The thruster glow and the low-health vignette are on while hp > 0 and off at hp 0."""
    s = _new_run(g)
    _clear_field(s)
    g.player.hp = g.player.max_hp
    keys = _draw_frame(g)
    assert "thruster" in keys, "the thruster glow must show on a living player"
    assert g.visuals._juice._vignette.opacity == 0, "no vignette at full health"

    g.player.hp = max(1.0, 0.15 * g.player.max_hp)
    _draw_frame(g)
    assert g.visuals._juice._vignette.opacity > 0, "the vignette must show below 30 percent hp"

    g.player.hp = 0
    keys = _draw_frame(g)
    assert "thruster" not in keys, "the thruster glow must stop at hp 0, so the death dissolve does not keep it lit"
    assert g.visuals._juice._vignette.opacity == 0, "the vignette must be off at hp 0"
    g.player.hp = g.player.max_hp
    print("[PASS] test_thruster_and_vignette_stop_at_zero_hp passed (thruster and vignette on at hp > 0, off at 0)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_pause_title_clear_of_hud_status_line(g)
        test_pod_robot_dash_has_only_its_ghosts(g)
        test_legacy_ship_keeps_glow_streak(g)
        test_dash_flag_off_silences_pod_ghosts(g)
        test_thruster_and_vignette_stop_at_zero_hp(g)
    finally:
        g.close()
    print("\nALL WAVE 6 VISUAL FIX TESTS PASSED")


if __name__ == "__main__":
    try:
        run_all()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
