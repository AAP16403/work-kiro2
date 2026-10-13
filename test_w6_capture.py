"""Deterministic tests for wave 6 item capture: the screen capture tool (tools/screens.py) and the
REDUCE_MOTION paths it reviews (the drone bob, the starfield drift and the thruster glow in visuals.py,
and the boss damage trail in hud.py).

Covers: a screen's fade veil is settled before its frame is read (the settle draws first, so the fade
starts where the screen appears); the hangar capture settles too; saved PNGs are fully opaque; the
--reduce-motion flag reaches run_capture and restores config.REDUCE_MOTION afterwards; the drone bob,
the starfield drift and the thruster glow hold still under reduced motion and move without
it; and the boss damage trail snaps to the new value under reduced motion.

Run with the venv python: ``python test_w6_capture.py``. The GL tests open a hidden window, as the other
files do. Scratch PNGs go to a temp directory, never into the project.
"""

import os
import shutil
import sys
import tempfile
from types import SimpleNamespace

import pyglet

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import config  # noqa: E402
import screens  # noqa: E402
import score as score_mod  # noqa: E402
from drone import DroneCompanion  # noqa: E402
from game import Game  # noqa: E402
from states import GameStateName  # noqa: E402
from utils import Vec2  # noqa: E402


def _set_reduced(on: bool) -> bool:
    prev = bool(config.REDUCE_MOTION)
    config.REDUCE_MOTION = bool(on)
    return prev


def _redirect_saves(g: Game):
    """Point the high-score and progress saves at a temp folder, the way screens.run_capture does.

    Returns (scratch, previous) for _restore_saves, so the real save paths come back after the test.
    """
    scratch = tempfile.mkdtemp(prefix="w6_capture_")
    previous = (score_mod.HIGH_SCORE_FILE, g.progress_path)
    score_mod.HIGH_SCORE_FILE = os.path.join(scratch, "high_scores.json")
    g.progress_path = os.path.join(scratch, "progress.json")
    return scratch, previous


def _restore_saves(g: Game, scratch: str, previous) -> None:
    score_mod.HIGH_SCORE_FILE, g.progress_path = previous
    shutil.rmtree(scratch, ignore_errors=True)


def _fade_opacity_after_capture(g: Game) -> float:
    """Draw the frame the way a capture does, then read the veil at that moment."""
    g.on_draw()
    return g._screen_fade.opacity(float(g._render_time), False)


# ---- capture timing ----------------------------------------------------------------------------
def test_settled_screen_has_no_fade_veil(g):
    """Before the fix a screen change started its fade at capture time, so the frame came out blank."""
    scratch, previous = _redirect_saves(g)
    prev = _set_reduced(False)
    try:
        screens._show_menu(g)
        g.on_draw()  # the menu frame that a capture would have read just before
        screens._show_settings(g)
        assert _fade_opacity_after_capture(g) == 0.0, "settings frame still under the fade veil"
    finally:
        _set_reduced(prev)
        _restore_saves(g, scratch, previous)
    print("[PASS] test_settled_screen_has_no_fade_veil passed (settings frame reads 0 veil after settle)")


def test_hangar_capture_settles(g):
    """The hangar spec used to switch state with no settle at all, so its frame was the veil."""
    hangar = getattr(GameStateName, "HANGAR", None)
    assert hangar is not None, "this build must define GameStateName.HANGAR for the capture suite"
    scratch, previous = _redirect_saves(g)
    prev = _set_reduced(False)
    try:
        screens._show_menu(g)
        g.on_draw()  # the menu frame that a capture would have read just before
        screens._show_hangar(g, hangar)
        assert _fade_opacity_after_capture(g) == 0.0, "hangar frame still under the fade veil"
    finally:
        _set_reduced(prev)
        _restore_saves(g, scratch, previous)
    print("[PASS] test_hangar_capture_settles passed (hangar frame reads 0 veil after settle)")


def test_saved_png_is_opaque(g):
    scratch, previous = _redirect_saves(g)
    prev = _set_reduced(False)
    try:
        screens._show_menu(g)
        g.on_draw()
        buffer = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
        path = os.path.join(scratch, "title.png")
        screens._save_opaque_png(path)
        image = pyglet.image.load(path)
        data = image.get_data("RGBA", image.width * 4)
        assert (image.width, image.height) == (buffer.width, buffer.height), "saved PNG size must match the frame read"
        assert set(data[3::4]) == {255}, "every saved alpha byte must be 255"
    finally:
        _set_reduced(prev)
        _restore_saves(g, scratch, previous)
    print("[PASS] test_saved_png_is_opaque passed (every alpha byte of a saved frame is 255)")


# ---- command line and run plumbing ----------------------------------------------------------------
def test_reduce_motion_flag_parses(_unused=None):
    seen = []
    fake_report = {"sizes": [], "screens": [], "errors": [], "skipped": [], "total_overlaps": 0}
    real_run = screens.run_capture
    scratch = tempfile.mkdtemp(prefix="w6_cli_")
    try:
        def fake_run(out_dir, sizes=screens.SIZES, game=None, reduce_motion=None):
            seen.append(reduce_motion)
            return dict(fake_report)

        screens.run_capture = fake_run
        assert screens.main(["--out", scratch, "--reduce-motion", "on"]) == 0
        assert screens.main(["--out", scratch, "--reduce-motion", "off"]) == 0
        assert screens.main(["--out", scratch]) == 0
    finally:
        screens.run_capture = real_run
        shutil.rmtree(scratch, ignore_errors=True)
    assert seen == [True, False, None], f"--reduce-motion did not reach run_capture: {seen}"
    print("[PASS] test_reduce_motion_flag_parses passed (on, off, unset reach run_capture as True, False, None)")


def test_run_capture_sets_and_restores_reduce_motion(g):
    """run_capture applies the flag after the game exists, reports it, and puts the old value back."""
    scratch = tempfile.mkdtemp(prefix="w6_run_")
    real_specs = screens.screen_specs
    prev = _set_reduced(False)
    saved_paths = (score_mod.HIGH_SCORE_FILE, g.progress_path)
    try:
        def one_screen(game):
            return [screens.ScreenSpec("title", lambda: screens._show_menu(game))], []

        screens.screen_specs = one_screen
        report_on = screens.run_capture(scratch, sizes=((980, 620),), game=g, reduce_motion=True)
        assert report_on["reduce_motion"] is True, report_on["reduce_motion"]
        assert config.REDUCE_MOTION is False, "run_capture must restore the flag it was given"
        assert [s["screen"] for s in report_on["screens"]] == ["title"], report_on["screens"]
        assert os.path.exists(os.path.join(scratch, "980x620", "title.png")), "title frame not written"

        config.REDUCE_MOTION = True
        report_none = screens.run_capture(scratch, sizes=((980, 620),), game=g, reduce_motion=None)
        assert report_none["reduce_motion"] is True, "reduce_motion=None must keep the value the game has"
        assert config.REDUCE_MOTION is True, "reduce_motion=None must not change the flag"
    finally:
        screens.screen_specs = real_specs
        _set_reduced(prev)
        score_mod.HIGH_SCORE_FILE, g.progress_path = saved_paths
        shutil.rmtree(scratch, ignore_errors=True)
    print("[PASS] test_run_capture_sets_and_restores_reduce_motion passed (flag applied, reported, restored)")


# ---- REDUCE_MOTION gaps found by the capture review -----------------------------------------------
def _playing_frame(g: Game, t: float, reduce: bool, drone_active: bool = False):
    """Run one visuals sync with a fixed player, returning the thruster glow tuple the pool received."""
    prev = _set_reduced(reduce)
    try:
        pool = g.visuals._glow_pool
        emitted = {}
        real_emit = pool.emit

        def record(key, x, y, radius, color, opacity):
            emitted[key] = (round(x, 3), round(y, 3), round(radius, 3), tuple(color), opacity)
            return real_emit(key, x, y, radius, color, opacity)

        pool.emit = record
        try:
            state = SimpleNamespace(projectiles=[], powerups=[], enemies=[])
            player = SimpleNamespace(pos=Vec2(100.0, 50.0), is_boosting=False, is_dashing=False,
                                     dash_direction=Vec2(1.0, 0.0))
            g.visuals.sync_glow(state, player, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(1.0, 0.0))
        finally:
            del pool.emit
        return emitted.get("thruster")
    finally:
        _set_reduced(prev)


def test_thruster_glow_holds_under_reduce_motion(g):
    assert _playing_frame(g, 0.7, True) == _playing_frame(g, 3.1, True), "thruster glow must hold still when reduced"
    assert _playing_frame(g, 0.7, False) != _playing_frame(g, 3.1, False), "thruster glow must move without reduce"
    print("[PASS] test_thruster_glow_holds_under_reduce_motion passed (still reduced, pulses without it)")


def test_starfield_drift_clock_is_held_under_reduce_motion(g):
    """The starfield drifts and twinkles on the clock it is given. sync_fx must give it the held clock."""
    starfield = g.visuals._starfield
    assert starfield is not None, "parallax starfield must exist for this test (ENABLE_PARALLAX_STARS)"
    clocks = []
    real_sync = starfield.sync

    def record(t, width, height, camera=None):
        clocks.append(float(t))
        return real_sync(t, width, height, camera=camera)

    starfield.sync = record
    try:
        state = SimpleNamespace(projectiles=[], powerups=[], enemies=[])
        player = SimpleNamespace(pos=Vec2(0.0, 0.0), is_boosting=False, is_dashing=False, dash_direction=Vec2(1.0, 0.0))
        prev = _set_reduced(True)
        try:
            g.visuals.sync_fx(state, player, Vec2(0.0, 0.0), t=5.0, aim_dir=Vec2(1.0, 0.0))
        finally:
            _set_reduced(prev)
        prev = _set_reduced(False)
        try:
            g.visuals.sync_fx(state, player, Vec2(0.0, 0.0), t=5.0, aim_dir=Vec2(1.0, 0.0))
        finally:
            _set_reduced(prev)
    finally:
        del starfield.sync
    assert clocks == [0.0, 5.0], f"starfield clock: reduced should be 0.0 and normal 5.0, got {clocks}"
    print("[PASS] test_starfield_drift_clock_is_held_under_reduce_motion passed (clock 0.0 reduced, 5.0 normal)")


def test_drone_bob_holds_under_reduce_motion(g):
    drone = DroneCompanion()
    drone.active = True
    drone.pos = Vec2(40.0, 0.0)
    shake = Vec2(0.0, 0.0)

    def hull_y(t, reduce):
        prev = _set_reduced(reduce)
        try:
            g.visuals.sync_drone(drone, shake, t=t)
            return float(g.visuals._drone_art.hull.y)
        finally:
            _set_reduced(prev)

    assert hull_y(0.0, True) == hull_y(1.3, True), "drone bob must hold still when reduced"
    assert hull_y(0.0, False) != hull_y(1.3, False), "drone bob must move without reduce"
    print("[PASS] test_drone_bob_holds_under_reduce_motion passed (hull still reduced, bobs without it)")


def test_boss_trail_snaps_under_reduce_motion(g):
    hud = g.hud
    prev = _set_reduced(True)
    try:
        hud.set_boss("Test Boss", 100, 100)
        hud.set_boss("Test Boss", 60, 100)
        assert abs(hud.boss_trail_bar.width - hud.boss_fill.width) < 1e-6, "reduced: trail must match the fill at once"
        hud.tick(0.2)
        assert abs(hud.boss_trail_bar.width - hud.boss_fill.width) < 1e-6, "reduced: trail must stay at the fill"
    finally:
        _set_reduced(prev)
        hud.set_boss(None, 0, 1)

    prev = _set_reduced(False)
    try:
        hud.set_boss("Test Boss", 100, 100)
        hud.set_boss("Test Boss", 60, 100)
        assert hud.boss_trail_bar.width > hud.boss_fill.width, "normal: the trail holds above the fill after damage"
    finally:
        _set_reduced(prev)
        hud.set_boss(None, 0, 1)
    print("[PASS] test_boss_trail_snaps_under_reduce_motion passed (trail matches fill reduced, lags normal)")


def run_all():
    g = Game()
    g.set_visible(False)
    prev = _set_reduced(False)
    try:
        test_settled_screen_has_no_fade_veil(g)
        test_hangar_capture_settles(g)
        test_saved_png_is_opaque(g)
        test_run_capture_sets_and_restores_reduce_motion(g)
        g._init_game()  # builds the visuals and the HUD, as a run does
        test_thruster_glow_holds_under_reduce_motion(g)
        test_starfield_drift_clock_is_held_under_reduce_motion(g)
        test_drone_bob_holds_under_reduce_motion(g)
        test_boss_trail_snaps_under_reduce_motion(g)
    finally:
        _set_reduced(prev)
        g.close()
    test_reduce_motion_flag_parses()
    print("\nALL WAVE 6 CAPTURE TESTS PASSED")


if __name__ == "__main__":
    run_all()
