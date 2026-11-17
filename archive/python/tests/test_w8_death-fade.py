"""Wave 8 death fade: the engine glow and the low-health vignette fade over the death dissolve.

Before this wave both cut off on the frame hp reached 0. With config.ENABLE_DEATH_FADE on they hold what they showed
on the last living frame and fade with the dissolve: 1 at death, 0 at its end. The fade is the pod-robot's dissolve
progress (PlayerArt.fade), so the body and its glow share one clock. The legacy ship has no dissolve, so it runs its
own clock over the same DISSOLVE_S.

Covers:
  - the engine glow and the vignette are non-increasing over the dissolve, start above 0 and reach 0 at its end, with
    about half their living value at half the dissolve (the game clock stopped, as it is at game over);
  - the same holds while the game clock still moves: the pulse is held, so the fade is the only change;
  - the fade runs under REDUCE_MOTION: the pulses stop, the fade does not;
  - the glow and the vignette scale by one shared fade factor;
  - a living player draws what main drew: the thruster pulse, colour and radius, and the vignette strength;
  - a new life after a death shows the living glow again, and no vignette;
  - ENABLE_DEATH_FADE off restores the cut at hp 0;
  - the legacy ship fades over the same DISSOLVE_S of real time;
  - a dying player's engine glow keeps the aim of its last living frame, so its spot stays where it was (the mouse
    moves on while the body dies), and a living glow still follows the aim;
  - the legacy ship's own engine glow sprite fades over the same DISSOLVE_S, at its last living spot;
  - ENABLE_DEATH_FADE off leaves the legacy body glow as main: lit at its living pulse, on the live aim.

The dissolve runs on real time, so the tests put a fake wall clock in place of the time module inside visuals.py.

Run with the venv python: ``python test_w8_death-fade.py``.
"""

import math
import os
import shutil
import sys
import tempfile
import traceback
from contextlib import contextmanager

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import config  # noqa: E402
import progress  # noqa: E402
import score  # noqa: E402
import visuals  # noqa: E402
from game import Game  # noqa: E402
from juice import low_hp_vignette_strength  # noqa: E402
from player_art import DISSOLVE_S  # noqa: E402
from states import GameStateName  # noqa: E402
from utils import Vec2  # noqa: E402

FRAME = 1.0 / 60.0
LIVING_FRAMES = 6
LOW_HP_RATIO = 0.15          # below the 30 percent vignette threshold, so the living vignette shows
MAX_DISSOLVE_FRAMES = int(DISSOLVE_S / FRAME) + 10


class _WallClock:
    """Stands in for the time module inside visuals.py, so the dissolve runs on a wall clock the test sets."""

    def __init__(self, now: float = 5000.0):
        self.now = float(now)

    def perf_counter(self) -> float:
        return self.now


@contextmanager
def _wall_clock():
    clock = _WallClock()
    saved = visuals.time
    visuals.time = clock
    try:
        yield clock
    finally:
        visuals.time = saved


@contextmanager
def _config_value(name: str, value):
    saved = getattr(config, name)
    setattr(config, name, value)
    try:
        yield
    finally:
        setattr(config, name, saved)


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.state.wave_active = True
    g.state.enemies = []
    g.state.projectiles = []
    g.player.is_boosting = False
    return g.state


def _art(g):
    return g.visuals._player_art


def _fade(g) -> float:
    """The fade the body shows: the pod-robot's dissolve, or the legacy ship's own clock when no PlayerArt is built."""
    art = _art(g)
    return float(art.fade) if art is not None else float(g.visuals._legacy_fade)


def _draw(g):
    """One real draw, the way the game loop draws it.

    Returns (the thruster glow this frame: its opacity, radius and colour, opacity 0 when none is drawn; and the
    vignette sprite's opacity).
    """
    pool = g.visuals._glow_pool
    drawn = {"op": 0, "radius": 0.0, "color": None}
    real_emit = pool.emit

    def emit(key, x, y, radius, color, opacity=255, *args, **kwargs):
        if key == "thruster":
            drawn["op"] = int(opacity)
            drawn["radius"] = float(radius)
            drawn["color"] = tuple(color)
        return real_emit(key, x, y, radius, color, opacity, *args, **kwargs)

    pool.emit = emit
    try:
        g.on_draw()
    finally:
        del pool.emit  # the instance attribute goes; the pool's own emit is the class method again
    return drawn, int(g.visuals._juice._vignette.opacity)


def _advance(g, wall, clock_moves: bool) -> None:
    wall.now += FRAME
    if clock_moves:
        g.state.time += FRAME


def _hurt_then_die(g, wall, clock_moves: bool):
    """Living frames at low HP, then hp 0. Returns (the last living frame, the dying frames).

    The last living frame is (drawn thruster dict, vignette opacity). Each dying frame is a dict with the fade the
    body shows, the thruster opacity, radius and colour, and the vignette opacity. The list ends with the first frame
    whose fade reads 0. clock_moves=False is the real game, where the game clock stops at game over.
    """
    g.player.hp = LOW_HP_RATIO * g.player.max_hp
    living = None
    for _ in range(LIVING_FRAMES):
        _advance(g, wall, clock_moves)
        living = _draw(g)
    g.player.hp = 0
    frames = []
    for _ in range(MAX_DISSOLVE_FRAMES):
        _advance(g, wall, clock_moves)
        drawn, vignette = _draw(g)
        fade = _fade(g)
        frames.append({"fade": fade, "op": drawn["op"], "radius": drawn["radius"],
                       "color": drawn["color"], "vignette": vignette})
        if fade <= 0.0:
            break
    return living, frames


AIM_A = Vec2(1.0, 0.0)
AIM_B = Vec2(-0.6, 0.8)  # the mouse moves here while the player dies


def _frame_with_aim(g, aim: Vec2) -> dict:
    """One frame drawn with this aim: the player, then its glow, as states.py does it (shake zero).

    Returns the thruster glow drawn as {x, y, op}, or {} when none is drawn.
    """
    pool = g.visuals._glow_pool
    drawn = {}
    real_emit = pool.emit

    def emit(key, x, y, radius, color, opacity=255, *args, **kwargs):
        if key == "thruster":
            drawn.update(x=float(x), y=float(y), op=int(opacity))
        return real_emit(key, x, y, radius, color, opacity, *args, **kwargs)

    pool.emit = emit
    try:
        g.visuals.sync_player(g.player, Vec2(0.0, 0.0), t=g.state.time, aim_dir=aim)
        g.visuals.sync_fx(g.state, g.player, Vec2(0.0, 0.0), t=g.state.time, aim_dir=aim)
    finally:
        del pool.emit  # the instance attribute goes; the pool's own emit is the class method again
    return drawn


def _body_glow(g) -> tuple:
    """The legacy ship's own engine glow sprite as (opacity, x, y): the 11th part of its handle (Visuals.make_player)."""
    glow = g.visuals._player_handle.objs[10]
    return int(glow.opacity), float(glow.x), float(glow.y)


def _assert_non_increasing(values, what: str) -> None:
    assert all(a >= b for a, b in zip(values, values[1:])), f"{what} must only fall over the dissolve: {values}"


def _assert_faded_to_zero(frames) -> None:
    last = frames[-1]
    assert last["fade"] <= 0.0, "the dissolve must end with its fade at 0"
    assert last["op"] == 0 and last["vignette"] == 0, f"the glow and the vignette must be gone at the end: {last}"


def _half_point(frames):
    return min(frames, key=lambda f: abs(f["fade"] - 0.5))


def test_glow_and_vignette_fade_over_the_dissolve(g):
    """The game clock stops at game over. Both effects fall from their living values to 0 over the dissolve."""
    with _wall_clock() as wall:
        _new_run(g)
        (living_glow, living_vig), frames = _hurt_then_die(g, wall, clock_moves=False)
        living_op = living_glow["op"]
        assert living_op > 0 and living_vig > 0, "the glow and the vignette must show on the last living frame"
        assert frames[0]["op"] > 0 and frames[0]["vignette"] > 0, "both must still show on the death frame"
        assert frames[0]["fade"] > 0.97, f"the death frame reads about 1, got {frames[0]['fade']:.4f}"
        assert frames[0]["op"] <= living_op and frames[0]["vignette"] <= living_vig, "the death frame does not brighten"
        _assert_non_increasing([f["op"] for f in frames], "the engine glow opacity")
        _assert_non_increasing([f["vignette"] for f in frames], "the vignette opacity")
        _assert_faded_to_zero(frames)
        half = _half_point(frames)
        assert abs(half["op"] / living_op - half["fade"]) < 0.05, f"half-way glow {half['op']} of {living_op}, fade {half['fade']:.3f}"
        assert abs(half["vignette"] / living_vig - half["fade"]) < 0.05, f"half-way vignette {half['vignette']} of {living_vig}"
        length = len(frames) * FRAME
        assert abs(length - DISSOLVE_S) < 2 * FRAME, f"the fade must last the dissolve, {length:.3f} s against {DISSOLVE_S} s"
    print(f"[PASS] test_glow_and_vignette_fade_over_the_dissolve passed (glow {living_op} to 0, vignette {living_vig} to 0 over {len(frames)} frames)")


def test_fade_is_one_factor_for_both(g):
    """The glow and the vignette each equal their living value times the body's fade, within integer rounding."""
    with _wall_clock() as wall:
        _new_run(g)
        (living_glow, living_vig), frames = _hurt_then_die(g, wall, clock_moves=False)
        for f in frames:
            assert abs(f["op"] - living_glow["op"] * f["fade"]) <= 2.0, f"glow {f['op']} is not {living_glow['op']} times {f['fade']:.4f}"
            assert abs(f["vignette"] - living_vig * f["fade"]) <= 2.0, f"vignette {f['vignette']} is not {living_vig} times {f['fade']:.4f}"
    print("[PASS] test_fade_is_one_factor_for_both passed (glow and vignette track the body fade on every dying frame)")


def test_fade_holds_while_the_game_clock_moves(g):
    """With the game clock still running the pulse is held at its death value, so only the fade changes."""
    with _wall_clock() as wall:
        _new_run(g)
        _, frames = _hurt_then_die(g, wall, clock_moves=True)
        _assert_non_increasing([f["op"] for f in frames], "the engine glow opacity with the clock moving")
        _assert_non_increasing([f["vignette"] for f in frames], "the vignette opacity with the clock moving")
        _assert_faded_to_zero(frames)
        drawn = [f for f in frames if f["op"] > 0]  # the last frame draws no glow at all
        radii = {round(f["radius"], 6) for f in drawn}
        colours = {f["color"] for f in drawn}
        assert len(radii) == 1, f"the held pulse must keep the glow radius still, saw {sorted(radii)}"
        assert len(colours) == 1, f"the glow colour must not change while it fades, saw {colours}"
    print("[PASS] test_fade_holds_while_the_game_clock_moves passed (pulse held, opacity only falls)")


def test_fade_runs_under_reduced_motion(g):
    """The fade is not motion: it runs under REDUCE_MOTION. Only the pulses stop."""
    with _config_value("REDUCE_MOTION", True), _wall_clock() as wall:
        _new_run(g)
        living_frames = []
        g.player.hp = LOW_HP_RATIO * g.player.max_hp
        for _ in range(LIVING_FRAMES):
            _advance(g, wall, clock_moves=True)
            drawn, vignette = _draw(g)
            living_frames.append((drawn["op"], vignette))
        assert len({op for op, _ in living_frames}) == 1, f"reduced motion must hold the living pulse still: {living_frames}"
        assert len({vig for _, vig in living_frames}) == 1, f"reduced motion must hold the vignette still: {living_frames}"
        living_op, living_vig = living_frames[-1]
        _, frames = _hurt_then_die(g, wall, clock_moves=True)
        assert frames[0]["op"] > 0 and frames[0]["vignette"] > 0, "the fade starts from the living values under REDUCE_MOTION"
        _assert_non_increasing([f["op"] for f in frames], "the glow opacity under REDUCE_MOTION")
        _assert_non_increasing([f["vignette"] for f in frames], "the vignette opacity under REDUCE_MOTION")
        _assert_faded_to_zero(frames)
        half = _half_point(frames)
        assert abs(half["op"] / living_op - half["fade"]) < 0.05, "under REDUCE_MOTION the glow fades in step with the body"
    print("[PASS] test_fade_runs_under_reduced_motion passed (pulses held, fade still falls to 0)")


def test_living_player_matches_main(g):
    """A living player draws what main drew. The expected values below are main's formulas (visuals.sync_glow
    and juice.JuiceOverlay.sync at 87384ff), evaluated at the same game clock."""
    with _wall_clock() as wall:
        _new_run(g)
        palette_glow = tuple(g.visuals.player_palette["glow"])
        for hp, clock in ((g.player.max_hp, 0.37), (LOW_HP_RATIO * g.player.max_hp, 1.9), (LOW_HP_RATIO * g.player.max_hp, 2.6)):
            g.player.hp = hp
            g.state.time = clock
            wall.now += FRAME
            drawn, vignette = _draw(g)
            pulse = 0.5 + 0.5 * math.sin(clock * 15.0)  # not boosting: main's rate is 15 per second
            assert drawn["op"] == int(120 + 100 * pulse), f"thruster opacity at t={clock}: {drawn['op']}"
            assert abs(drawn["radius"] - (9.0 + 3.0 * pulse)) < 1e-9, f"thruster radius at t={clock}: {drawn['radius']}"
            assert drawn["color"] == tuple(int(c) for c in palette_glow), f"thruster colour: {drawn['color']}"
            expected_vig = int(255 * low_hp_vignette_strength(hp / float(g.player.max_hp), clock))
            assert vignette == expected_vig, f"vignette at hp {hp} t={clock}: {vignette}, main gives {expected_vig}"
        assert _fade(g) == 1.0, "a living body is not fading"
    print("[PASS] test_living_player_matches_main passed (thruster pulse, colour and radius, and vignette, as on main)")


def test_new_life_shows_the_living_glow_again(g):
    """After a full dissolve, a new life draws the living glow and no vignette, with no leftover fade."""
    with _wall_clock() as wall:
        _new_run(g)
        _hurt_then_die(g, wall, clock_moves=False)
        assert _fade(g) <= 0.0, "the dissolve must have ended before the new life"
        g.player.hp = g.player.max_hp
        g.state.time = 0.0
        _advance(g, wall, clock_moves=False)
        drawn, vignette = _draw(g)
        assert drawn["op"] >= 120, f"the glow must come back at full strength, saw {drawn['op']}"
        assert vignette == 0, "a healthy new life has no vignette"
        assert _fade(g) == 1.0, "the body shows again"
    print("[PASS] test_new_life_shows_the_living_glow_again passed (glow back at full, no vignette)")


def test_switch_off_restores_the_cut(g):
    """ENABLE_DEATH_FADE off: the glow and the vignette stop on the frame hp reaches 0, as on main."""
    with _config_value("ENABLE_DEATH_FADE", False), _wall_clock() as wall:
        _new_run(g)
        _, frames = _hurt_then_die(g, wall, clock_moves=False)
        assert frames[0]["op"] == 0, f"with the switch off the glow stops at hp 0, saw {frames[0]['op']}"
        assert frames[0]["vignette"] == 0, f"with the switch off the vignette stops at hp 0, saw {frames[0]['vignette']}"
        assert frames[0]["fade"] < 1.0, "the body still dissolves: the switch touches only the glow and the vignette"
    assert config.ENABLE_DEATH_FADE is True, "the switch is on by default"
    print("[PASS] test_switch_off_restores_the_cut passed (switch off: cut at hp 0; default on)")


def test_legacy_ship_fades_on_the_same_clock(g):
    """The legacy ship has no dissolve of its own. Its glow and vignette fade over the same DISSOLVE_S of real time."""
    with _config_value("USE_PLAYER_ART", False), _wall_clock() as wall:
        _new_run(g)
        (living_glow, living_vig), frames = _hurt_then_die(g, wall, clock_moves=False)
        assert g.visuals._player_art is None, "the legacy ship must be the character on screen"
        assert living_glow["op"] > 0 and living_vig > 0
        assert frames[0]["op"] > 0 and frames[0]["vignette"] > 0, "the legacy glow and vignette fade in from their living values"
        _assert_non_increasing([f["op"] for f in frames], "the legacy engine glow opacity")
        _assert_non_increasing([f["vignette"] for f in frames], "the legacy vignette opacity")
        _assert_faded_to_zero(frames)
        length = len(frames) * FRAME
        assert abs(length - DISSOLVE_S) < 2 * FRAME, f"the legacy fade must last {DISSOLVE_S} s, took {length:.3f} s"
    # Back to the pod-robot for the tests that follow.
    g.visuals.sync_player(g.player, Vec2(0.0, 0.0))
    print(f"[PASS] test_legacy_ship_fades_on_the_same_clock passed (legacy fade over {len(frames)} frames, {DISSOLVE_S} s)")


def test_engine_glow_holds_its_aim_while_dying(g):
    """A dying player's engine glow keeps the aim of its last living frame, so its spot does not swing with the mouse.
    Living, the glow still follows the aim."""
    with _wall_clock() as wall:
        _new_run(g)
        g.player.hp = LOW_HP_RATIO * g.player.max_hp
        _advance(g, wall, clock_moves=False)
        at_b = _frame_with_aim(g, AIM_B)
        _advance(g, wall, clock_moves=False)
        last = _frame_with_aim(g, AIM_A)  # the last living frame aims at A
        assert "x" in at_b and "x" in last, "the living glow must be drawn"
        moved = abs(at_b["x"] - last["x"]) + abs(at_b["y"] - last["y"])
        assert moved > 1.0, f"a living glow must follow the aim, but it moved only {moved:.3f} px from A to B"
        g.player.hp = 0
        checked = 0
        for _ in range(MAX_DISSOLVE_FRAMES):
            _advance(g, wall, clock_moves=False)
            drawn = _frame_with_aim(g, AIM_B)  # the mouse has moved on to B while the body dies
            fade = _fade(g)
            if "x" in drawn:
                checked += 1
                assert abs(drawn["x"] - last["x"]) < 1e-9 and abs(drawn["y"] - last["y"]) < 1e-9, (
                    f"the dying glow moved to ({drawn['x']:.3f}, {drawn['y']:.3f}), "
                    f"not held at its last living spot ({last['x']:.3f}, {last['y']:.3f})")
            if fade <= 0.0:
                break
        assert checked >= 10, f"the dying glow must be drawn for a while, it was drawn on {checked} frames"
    print(f"[PASS] test_engine_glow_holds_its_aim_while_dying passed (spot held on {checked} dying frames, aim B ignored)")


def test_legacy_body_glow_fades_over_the_dissolve(g):
    """The legacy ship's own engine glow sprite fades over the same DISSOLVE_S as the pool glow. It keeps its last living
    spot, and its opacity is its living pulse times the fade: 0 at the end of the dissolve, not 230 for ever."""
    with _config_value("USE_PLAYER_ART", False), _wall_clock() as wall:
        _new_run(g)
        assert g.visuals._player_art is None, "the legacy ship must be the character on screen"
        g.player.hp = LOW_HP_RATIO * g.player.max_hp
        _advance(g, wall, clock_moves=False)
        _frame_with_aim(g, AIM_B)
        _advance(g, wall, clock_moves=False)
        _frame_with_aim(g, AIM_A)  # the last living frame
        living_op, lx, ly = _body_glow(g)
        assert living_op > 0, "the body's engine glow must be lit on the last living frame"
        g.player.hp = 0
        frames = []
        for _ in range(MAX_DISSOLVE_FRAMES):
            _advance(g, wall, clock_moves=False)
            _frame_with_aim(g, AIM_B)
            op, x, y = _body_glow(g)
            fade = _fade(g)
            frames.append({"fade": fade, "op": op, "x": x, "y": y})
            if fade <= 0.0:
                break
        assert frames[0]["op"] > 0, "the body glow fades in from its living value on the death frame"
        for f in frames:
            assert abs(f["op"] - living_op * f["fade"]) <= 2.0, f"body glow {f['op']} is not {living_op} times {f['fade']:.4f}"
        _assert_non_increasing([f["op"] for f in frames], "the legacy body engine glow opacity")
        assert frames[-1]["op"] == 0, f"the body glow must be dark at the end of the dissolve, saw {frames[-1]['op']}"
        half = _half_point(frames)
        assert abs(half["op"] / living_op - half["fade"]) < 0.05, f"half-way body glow {half['op']} of {living_op}, fade {half['fade']:.3f}"
        length = len(frames) * FRAME
        assert abs(length - DISSOLVE_S) < 2 * FRAME, f"the body glow must fade over {DISSOLVE_S} s, took {length:.3f} s"
        for f in frames:
            assert abs(f["x"] - lx) < 1e-9 and abs(f["y"] - ly) < 1e-9, (
                f"the dying body glow moved to ({f['x']:.3f}, {f['y']:.3f}), not held at ({lx:.3f}, {ly:.3f})")
    # Back to the pod-robot for the tests that follow.
    g.visuals.sync_player(g.player, Vec2(0.0, 0.0))
    print(f"[PASS] test_legacy_body_glow_fades_over_the_dissolve passed (body glow {living_op} to 0 over {len(frames)} frames)")


def test_switch_off_keeps_the_body_glow_as_main(g):
    """ENABLE_DEATH_FADE off: the legacy body's engine glow is drawn as on main. It stays lit at its living pulse and
    follows the live aim while the ship dies, and the pool glow is cut at hp 0."""
    with _config_value("ENABLE_DEATH_FADE", False), _config_value("USE_PLAYER_ART", False), _wall_clock() as wall:
        _new_run(g)
        assert g.visuals._player_art is None, "the legacy ship must be the character on screen"
        g.player.hp = LOW_HP_RATIO * g.player.max_hp
        _advance(g, wall, clock_moves=False)
        _frame_with_aim(g, AIM_B)
        living_b = _body_glow(g)
        _advance(g, wall, clock_moves=False)
        _frame_with_aim(g, AIM_A)
        living_a = _body_glow(g)
        assert living_b[0] > 0 and living_b[0] == living_a[0], "living, the body glow shows its pulse"
        assert abs(living_b[1] - living_a[1]) + abs(living_b[2] - living_a[2]) > 1.0, "the living body glow must follow the aim"
        g.player.hp = 0
        for _ in range(MAX_DISSOLVE_FRAMES // 2):  # the switch is off, so the glow must not fade within the dissolve
            _advance(g, wall, clock_moves=False)
            drawn = _frame_with_aim(g, AIM_B)
            op, x, y = _body_glow(g)
            assert "x" not in drawn, f"with the switch off the pool glow stops at hp 0, saw {drawn}"
            assert op == living_b[0], f"with the switch off the body glow stays at its living pulse, saw {op}"
            assert abs(x - living_b[1]) < 1e-9 and abs(y - living_b[2]) < 1e-9, (
                f"with the switch off the body glow follows the live aim, as on main, saw ({x:.3f}, {y:.3f})")
    g.visuals.sync_player(g.player, Vec2(0.0, 0.0))
    print("[PASS] test_switch_off_keeps_the_body_glow_as_main passed (switch off: body glow lit and on the live aim, as on main)")


def run_all():
    score_saved = score.HIGH_SCORE_FILE
    progress_saved = progress.PROGRESS_FILE
    scratch = tempfile.mkdtemp(prefix="w8_death_fade_")  # the save files go here, never into the repo
    score.HIGH_SCORE_FILE = os.path.join(scratch, "high_scores.json")
    progress.PROGRESS_FILE = os.path.join(scratch, "progress.json")
    g = Game()
    g.set_visible(False)
    try:
        test_glow_and_vignette_fade_over_the_dissolve(g)
        test_fade_is_one_factor_for_both(g)
        test_fade_holds_while_the_game_clock_moves(g)
        test_fade_runs_under_reduced_motion(g)
        test_living_player_matches_main(g)
        test_new_life_shows_the_living_glow_again(g)
        test_switch_off_restores_the_cut(g)
        test_legacy_ship_fades_on_the_same_clock(g)
        test_engine_glow_holds_its_aim_while_dying(g)
        test_legacy_body_glow_fades_over_the_dissolve(g)
        test_switch_off_keeps_the_body_glow_as_main(g)
    finally:
        g.close()
        score.HIGH_SCORE_FILE = score_saved
        progress.PROGRESS_FILE = progress_saved
        shutil.rmtree(scratch, ignore_errors=True)  # only the folder this run made
    print("\nALL WAVE 8 DEATH FADE TESTS PASSED")


if __name__ == "__main__":
    try:
        run_all()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
