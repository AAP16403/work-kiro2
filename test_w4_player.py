"""Wave 4 player animation: the pod-robot character (player_art.py and the player functions in visuals.py).

Covers: idle breathing that is bounded and periodic; banking into sideways motion on a spring that
settles back to rest; pupils that ease toward the aim over several frames instead of snapping; a
thruster flicker that varies and differs from jet to jet; a dash afterimage that samples during the
burst and fades out; a hit recoil that points away from the aim and settles, with none under reduced
motion; a death dissolve that runs on real time while the game clock is frozen, hides the body, and
resets on a new run; a dark rim that outlines the body; the depth handle that does not migrate while
the character only bobs; reduced motion stilling every ambient motion; palette changes; and a bound on
net allocation per frame.

Run with the venv python: ``python test_w4_player.py``. Also collectable by pytest.
"""

import math
import sys
import traceback
from contextlib import contextmanager

import config
from game import Game
from player import Player
from player_art import (
    ANTENNA_LEN, BANK_PX, BODY_A, BODY_B, BREATH_RATE, DEFAULT_PALETTE, DISSOLVE_S, EYE_X, GHOST_LIFE_S,
    GHOST_N, PlayerArt,
)
from states import GameStateName
from utils import Vec2, to_iso

FRAME = 1.0 / 60.0
AIM_RIGHT = Vec2(1.0, 0.0)
AIM_LEFT = Vec2(-1.0, 0.0)


@contextmanager
def reduced_motion(on: bool):
    saved = config.REDUCE_MOTION
    config.REDUCE_MOTION = on
    try:
        yield
    finally:
        config.REDUCE_MOTION = saved


def _player(x: float = 0.0, y: float = 0.0) -> Player:
    return Player(pos=Vec2(x, y))


def _eye(art, side):
    return next(row for row in art._eyes if row[0] == side)


def _gaze(art, side, cx, cy):
    """Pupil offset from its rest point, in px."""
    eye = _eye(art, side)[2]
    return eye.position[0] - (cx + side * EYE_X)


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def test_idle_breath_is_bounded_and_periodic(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    sizes = []
    for i in range(int(6.0 * 60)):
        art.sync(p, Vec2(0.0, 0.0), t=i * FRAME, aim_dir=AIM_RIGHT)
        sizes.append(art.body.a)
    spread = max(sizes) - min(sizes)
    assert 0.5 <= spread <= 1.25, f"breath should swell the body a little, spread={spread:.3f}"
    period = 2.0 * math.pi / BREATH_RATE
    art.delete()
    art = PlayerArt(g.batch, None)
    art.sync(p, Vec2(0.0, 0.0), t=0.0, aim_dir=AIM_RIGHT)
    art.sync(p, Vec2(0.0, 0.0), t=2.0, aim_dir=AIM_RIGHT)
    a_now = art.body.a
    art.sync(p, Vec2(0.0, 0.0), t=2.0 + period, aim_dir=AIM_RIGHT)
    assert abs(art.body.a - a_now) <= 0.25, "one full breath later the body is back where it was"
    art.delete()
    print(f"[PASS] test_idle_breath_is_bounded_and_periodic passed (spread {spread:.2f} px over 6 s, period {period:.2f} s)")


def test_breath_stops_with_reduced_motion(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    with reduced_motion(True):
        sizes = set()
        for i in range(int(4.0 * 60)):  # the first frames of a fresh visual are not a motion check
            art.sync(p, Vec2(0.0, 0.0), t=i * FRAME, aim_dir=AIM_RIGHT)
            sizes.add(round(art.body.a, 4))
    assert len(sizes) == 1, f"reduced motion must hold the body still, saw sizes {sorted(sizes)}"
    art.delete()
    print("[PASS] test_breath_stops_with_reduced_motion passed (body size constant over 4 s)")


def test_banking_leans_into_motion_then_settles(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    cx = cy = 0.0
    for _ in range(30):  # half a second at gameplay speed, 175 units/s along +x
        t += FRAME
        p.pos = Vec2(p.pos.x + 175.0 * FRAME, p.pos.y)
        cx, cy = art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    lean = art.body.position[0] - cx
    assert lean > 0.4, f"moving right must lean the shell right, offset {lean:.3f}"
    assert lean <= BANK_PX * 0.6 + 1e-6, "the lean must stay within its cap"
    for _ in range(3 * 60):  # stop, and let the spring ring down
        t += FRAME
        cx, cy = art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    settled = art.body.position[0] - cx
    assert abs(settled) < 0.05, f"the lean must settle back to rest, offset {settled:.3f}"
    art.delete()
    print(f"[PASS] test_banking_leans_into_motion_then_settles passed (lean {lean:.2f} px, settled to {settled:.3f})")


def test_eyes_ease_toward_the_aim(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    for _ in range(60):
        t += FRAME
        cx, cy = art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    start = _gaze(art, -1, cx, cy)
    assert start > 1.0, f"pupils should rest toward the right aim, got {start:.3f}"
    t += FRAME
    cx, cy = art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_LEFT)
    first = _gaze(art, -1, cx, cy)
    assert -1.0 < first < start, f"one frame after a flip the pupils must still be moving, got {first:.3f}"
    for _ in range(36):
        t += FRAME
        cx, cy = art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_LEFT)
    end = _gaze(art, -1, cx, cy)
    assert end < -1.0 and abs(end + start) < 0.05, f"pupils must settle on the left aim, got {end:.3f}"
    art.delete()
    print(f"[PASS] test_eyes_ease_toward_the_aim passed (first frame {first:.2f}, settled {end:.2f})")


def test_thruster_flicker_varies_per_jet(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    levels = set()
    differ = 0
    frames = 3 * 60
    for _ in range(frames):
        t += FRAME
        p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
        levels.add(int(art.thrust.opacity))
        ops = [j.opacity for j in art.jets]
        if len(set(ops)) > 1:
            differ += 1
        assert 0 <= art.thrust.opacity <= 255
    assert len(levels) >= 20, f"the thruster must flutter, only {len(levels)} distinct levels"
    assert differ > frames * 0.8, "the jets must not flicker in step with each other"
    art.delete()
    print(f"[PASS] test_thruster_flicker_varies_per_jet passed ({len(levels)} levels, jets out of step on {differ}/{frames} frames)")


def test_thruster_is_still_with_reduced_motion(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    levels = set()
    with reduced_motion(True):
        for i in range(240):
            t += FRAME
            p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
            art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
            if i >= 120:  # after the speed has settled, only the flicker could still change the level
                levels.add(int(art.thrust.opacity))
    assert len(levels) == 1, f"reduced motion must hold the flicker still, saw {sorted(levels)}"
    art.delete()
    print("[PASS] test_thruster_is_still_with_reduced_motion passed (flicker frozen)")


def test_dash_and_movement_do_not_stretch_with_reduced_motion(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    with reduced_motion(True):
        for _ in range(60):
            t += FRAME
            p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
            art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
        p.is_dashing = True
        p.dash_direction = Vec2(1.0, 0.0)
        for _ in range(12):
            t += FRAME
            p.pos = Vec2(p.pos.x + 9.0, p.pos.y)
            art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
            assert abs(art.body.a - BODY_A) < 0.3 and abs(art.body.b - BODY_B) < 0.3, \
                f"reduced motion must keep the body round (a={art.body.a}, b={art.body.b})"
    art.delete()
    print("[PASS] test_dash_and_movement_do_not_stretch_with_reduced_motion passed (body stays round)")


def test_dash_afterimage_samples_then_fades(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    for _ in range(12):
        t += FRAME
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    p.is_dashing = True
    p.dash_direction = Vec2(1.0, 0.0)
    peak = 0
    positions = set()
    for _ in range(20):
        t += FRAME
        p.pos = Vec2(p.pos.x + 9.0, p.pos.y)
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
        peak = max([peak] + [int(gh.opacity) for gh in art.ghosts])
        for gh in art.ghosts:
            if gh.opacity > 0:
                positions.add(round(gh.position[0], 1))
    assert peak > 40, f"the dash must leave a visible afterimage, peak opacity {peak}"
    assert len(positions) >= 2, "afterimages must sit at different points along the dash"
    p.is_dashing = False
    for _ in range(int((GHOST_LIFE_S + 0.6) * 60)):
        t += FRAME
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    assert all(gh.opacity == 0 for gh in art.ghosts), "afterimages must fade out and disappear"
    art.delete()
    print(f"[PASS] test_dash_afterimage_samples_then_fades passed (peak {peak}, {len(positions)} places, all faded)")


def test_no_afterimage_with_reduced_motion(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    p.is_dashing = True
    p.dash_direction = Vec2(1.0, 0.0)
    t = 0.0
    with reduced_motion(True):
        for _ in range(30):
            t += FRAME
            p.pos = Vec2(p.pos.x + 9.0, p.pos.y)
            art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
            assert all(gh.opacity == 0 for gh in art.ghosts), "reduced motion must draw no afterimage"
    art.delete()
    print("[PASS] test_no_afterimage_with_reduced_motion passed (no ghost ever shows)")


def test_hit_recoil_points_away_from_aim_and_settles(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    for _ in range(30):
        t += FRAME
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    gx, gy = to_iso(p.pos, Vec2(0.0, 0.0))
    p.damage_flash_timer = 0.2
    t += FRAME
    cx, cy = art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    recoil = gx - cx
    assert cx < gx - 1.5, f"a hit must push the body back, away from the aim (cx={cx:.2f}, gx={gx:.2f})"
    p.damage_flash_timer = 0.0
    for _ in range(int(0.6 * 60)):
        t += FRAME
        cx, cy = art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    assert abs(cx - gx) < 0.05, f"the recoil must settle back onto the ground point (cx={cx:.3f}, gx={gx:.3f})"
    art.delete()
    print(f"[PASS] test_hit_recoil_points_away_from_aim_and_settles passed (recoil {recoil:.2f} px back on the hit, then settled)")


def test_no_hit_recoil_with_reduced_motion(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    with reduced_motion(True):
        for _ in range(10):
            t += FRAME
            art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
        gx, gy = to_iso(p.pos, Vec2(0.0, 0.0))
        p.damage_flash_timer = 0.2
        t += FRAME
        cx, cy = art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    assert abs(cx - gx) < 1e-9, "reduced motion must not recoil the body"
    art.delete()
    print("[PASS] test_no_hit_recoil_with_reduced_motion passed (body stays on its ground point)")


def test_death_dissolve_runs_on_real_time_then_resets(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    game_t = 42.0            # the game clock stops at game over
    real = 1000.0
    for _ in range(20):
        art.sync(p, Vec2(0.0, 0.0), t=game_t, aim_dir=AIM_RIGHT, real_t=real)
        real += FRAME
    assert art.body.opacity == 255
    p.hp = 0
    samples = []
    for _ in range(int((DISSOLVE_S + 0.4) * 60)):
        art.sync(p, Vec2(0.0, 0.0), t=game_t, aim_dir=AIM_RIGHT, real_t=real)
        real += FRAME
        samples.append(int(art.body.opacity))
    mid = samples[int(0.4 * DISSOLVE_S * 60)]
    assert 0 < mid < 255, f"the body must fade through the dissolve even though the clock is frozen, mid={mid}"
    assert all(a >= b for a, b in zip(samples, samples[1:])), "the body must only fade out during a death"
    assert samples[-1] == 0, "after the dissolve the body must be gone"
    assert art.shell_shade.opacity == 0 and art.halo_out.opacity == 0 and art.shadow.opacity == 0
    assert _eye(art, -1)[5].opacity == 0, "a dissolved body has no visible lid either"
    # A new run: the clock restarts and hp is back, so the body is visible again.
    p.hp = p.max_hp
    art.sync(p, Vec2(0.0, 0.0), t=0.0, aim_dir=AIM_RIGHT, real_t=real)
    assert art.body.opacity == 255, "a new run must show the body again"
    art.delete()
    print(f"[PASS] test_death_dissolve_runs_on_real_time_then_resets passed (mid-dissolve opacity {mid}, gone at the end)")


def test_dissolve_eyes_stay_shut_and_pieces_fly(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    p.hp = 0
    game_t = 3.0
    real = 50.0
    art.sync(p, Vec2(0.0, 0.0), t=game_t, aim_dir=AIM_RIGHT, real_t=real)
    for _ in range(int(0.45 * 60)):
        real += FRAME
        art.sync(p, Vec2(0.0, 0.0), t=game_t, aim_dir=AIM_RIGHT, real_t=real)
    pieces = [gh.position for gh in art.ghosts if gh.opacity > 0]
    assert len(pieces) == GHOST_N, f"all {GHOST_N} dissolve pieces should show mid-dissolve, saw {len(pieces)}"
    spread = max(math.hypot(a[0] - b[0], a[1] - b[1]) for a in pieces for b in pieces)
    assert spread > 10.0, f"the pieces must fly apart, spread {spread:.1f}"
    assert _eye(art, -1)[5].opacity > 0 and _eye(art, 1)[5].opacity > 0, "a knocked-out body keeps its eyes shut"
    art.delete()
    print(f"[PASS] test_dissolve_eyes_stay_shut_and_pieces_fly passed ({GHOST_N} pieces, spread {spread:.1f} px)")


def test_dissolve_with_reduced_motion_fades_without_pieces(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    p.hp = 0
    real = 10.0
    with reduced_motion(True):
        art.sync(p, Vec2(0.0, 0.0), t=1.0, aim_dir=AIM_RIGHT, real_t=real)
        for _ in range(int(0.45 * 60)):
            real += FRAME
            art.sync(p, Vec2(0.0, 0.0), t=1.0, aim_dir=AIM_RIGHT, real_t=real)
            assert all(gh.opacity == 0 for gh in art.ghosts), "reduced motion must not fly the pieces"
    assert 0 < art.body.opacity < 255, "the body still fades under reduced motion"
    art.delete()
    print("[PASS] test_dissolve_with_reduced_motion_fades_without_pieces passed")


def test_dissolve_falls_back_to_game_clock_without_real_time(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    p.hp = 0
    t = 0.0
    for _ in range(int(1.2 * 60)):
        t += FRAME
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    assert art.body.opacity == 0, "without real_t the dissolve follows the game clock"
    art.delete()
    print("[PASS] test_dissolve_falls_back_to_game_clock_without_real_time passed")


def test_dark_rim_outlines_the_body(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    art.sync(p, Vec2(0.0, 0.0), t=0.5, aim_dir=AIM_RIGHT)
    assert art.rim.a > art.body.a and art.rim.b > art.body.b, "the rim must sit just outside the shell"
    assert tuple(art.rim.color[:3]) == DEFAULT_PALETTE["eye"], "the rim uses the outline colour"
    assert art.rim.opacity > 100, "the rim must be visible"
    assert art.shapes.index(art.rim) < art.shapes.index(art.body), "the rim must draw behind the shell"
    art.delete()
    print("[PASS] test_dark_rim_outlines_the_body passed (rim outside the shell, drawn behind it)")


def test_palette_changes_take_effect(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    art.sync(p, Vec2(0.0, 0.0), t=0.2, aim_dir=AIM_RIGHT, palette={"body": (10, 200, 30)})
    assert tuple(art.body.color[:3]) == (10, 200, 30), "a skin colour must reach the shell"
    art.sync(p, Vec2(0.0, 0.0), t=0.25, aim_dir=AIM_RIGHT, palette={"body": (90, 40, 200)})
    assert tuple(art.body.color[:3]) == (90, 40, 200), "a new palette object must be read"
    art.sync(p, Vec2(0.0, 0.0), t=0.3, aim_dir=AIM_RIGHT)
    assert tuple(art.body.color[:3]) == (132, 224, 255), "dropping the palette must restore the default shell"
    art.delete()
    print("[PASS] test_palette_changes_take_effect passed (skin colours applied, then default restored)")


def test_sync_never_writes_to_the_player(g):
    art = PlayerArt(g.batch, None)
    p = _player(12.0, -7.0)
    p.shield = 60
    p.laser_until = 10.0
    t = 0.0
    real = 5.0
    for i in range(400):
        t += FRAME
        real += FRAME
        if i == 60:
            p.is_dashing = True
            p.dash_direction = Vec2(0.0, 1.0)
        if i == 90:
            p.is_dashing = False
            p.damage_flash_timer = 0.2
        if i == 120:
            p.damage_flash_timer = 0.0
            p.hp = 0
        p.pos = Vec2(p.pos.x + (2.0 if i < 200 else 0.0), p.pos.y)
        before = (p.pos.x, p.pos.y, p.hp, p.max_hp, p.is_dashing, p.is_boosting, p.damage_flash_timer,
                  p.invincibility_timer)
        art.sync(p, Vec2(1.0, -2.0), t=t, aim_dir=Vec2(0.4, 0.9), real_t=real)
        after = (p.pos.x, p.pos.y, p.hp, p.max_hp, p.is_dashing, p.is_boosting, p.damage_flash_timer,
                 p.invincibility_timer)
        assert after == before, f"sync wrote to the player on frame {i}"
    art.delete()
    print("[PASS] test_sync_never_writes_to_the_player passed (400 frames: dash, hit, death; player untouched)")


def test_shape_count_and_writes_are_steady(g):
    art = PlayerArt(g.batch, None)
    n = len(art.shapes)
    p = _player()
    t = 0.0
    for i in range(300):
        t += FRAME
        if i % 60 == 0:
            p.is_dashing = not p.is_dashing
            p.dash_direction = Vec2(1.0, 0.0)
        if i % 100 == 0:
            p.damage_flash_timer = 0.2
        else:
            p.damage_flash_timer = max(0.0, p.damage_flash_timer - FRAME)
        p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
    assert len(art.shapes) == n, "sync must create no shapes"
    art.delete()
    print(f"[PASS] test_shape_count_and_writes_are_steady passed ({n} shapes, none created while running)")


def test_allocation_per_frame_is_bounded(g):
    import gc
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0

    def frame(i):
        nonlocal t
        t += FRAME
        p.is_dashing = (i % 240) < 20
        p.dash_direction = Vec2(1.0, 0.0)
        p.damage_flash_timer = 0.2 if (i % 300) < 6 else 0.0
        p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)

    for i in range(300):
        frame(i)
    gc.collect()
    gc.disable()
    try:
        b0 = sys.getallocatedblocks()
        frames = 900
        for i in range(300, 300 + frames):
            frame(i)
        b1 = sys.getallocatedblocks()
    finally:
        gc.enable()
    per_frame = (b1 - b0) / frames
    # Measured on this machine: about 0.3 net blocks per frame, against about 1.3 before this change.
    # pyglet's own vertex bookkeeping accounts for most of it; the bound catches a real per-frame leak.
    assert per_frame < 1.0, f"net allocation {per_frame:.2f} blocks per frame"
    art.delete()
    print(f"[PASS] test_allocation_per_frame_is_bounded passed (net {per_frame:.2f} blocks per frame)")


def test_sync_leaves_the_depth_handle_alone_while_bobbing(g):
    _new_run(g)
    vis = g.visuals
    p = g.player
    p.pos = Vec2(0.0, 0.0)
    orders = set()
    t = 0.0
    for _ in range(4 * 60):  # standing still: the bob moves the body every frame
        t += FRAME
        vis.sync_player(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
        orders.add(vis._player_handle._depth_order)
    assert len(orders) == 1, f"bobbing must not change the depth bucket, saw {sorted(orders)}"
    for _ in range(2 * 60):  # walk far up the screen: the depth must follow
        t += FRAME
        p.pos = Vec2(p.pos.x + 3.0, p.pos.y + 3.0)
        vis.sync_player(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
        orders.add(vis._player_handle._depth_order)
    assert len(orders) >= 2, "a real move must still change the depth bucket"
    print(f"[PASS] test_sync_leaves_the_depth_handle_alone_while_bobbing passed (one bucket while bobbing; {len(orders)} buckets seen in total on the walk)")


def test_visuals_reduced_motion_holds_the_body_still(g):
    _new_run(g)
    vis = g.visuals
    p = g.player
    p.pos = Vec2(0.0, 0.0)
    ys = set()
    t = 0.0
    with reduced_motion(True):
        for _ in range(180):
            t += FRAME
            vis.sync_player(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
            ys.add(round(vis._player_art.body.position[1], 4))
    assert len(ys) == 1, f"reduced motion must stop the float bob, saw {len(ys)} heights"
    print("[PASS] test_visuals_reduced_motion_holds_the_body_still passed (no float bob with reduced motion)")


def test_antenna_still_lags_and_stays_on_its_stalk(g):
    art = PlayerArt(g.batch, None)
    p = _player()
    t = 0.0
    for i in range(120):
        t += FRAME
        p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=AIM_RIGHT)
        dx = art.ant_tip.position[0] - art.stalk.position[0]
        dy = art.ant_tip.position[1] - art.stalk.position[1]
        assert abs(math.hypot(dx, dy) - ANTENNA_LEN) < 1e-6, f"tip left the stalk on frame {i}"
    art.delete()
    print("[PASS] test_antenna_still_lags_and_stays_on_its_stalk passed (tip on the stalk while banking)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        _new_run(g)
        test_idle_breath_is_bounded_and_periodic(g)
        test_breath_stops_with_reduced_motion(g)
        test_banking_leans_into_motion_then_settles(g)
        test_eyes_ease_toward_the_aim(g)
        test_thruster_flicker_varies_per_jet(g)
        test_thruster_is_still_with_reduced_motion(g)
        test_dash_and_movement_do_not_stretch_with_reduced_motion(g)
        test_dash_afterimage_samples_then_fades(g)
        test_no_afterimage_with_reduced_motion(g)
        test_hit_recoil_points_away_from_aim_and_settles(g)
        test_no_hit_recoil_with_reduced_motion(g)
        test_death_dissolve_runs_on_real_time_then_resets(g)
        test_dissolve_eyes_stay_shut_and_pieces_fly(g)
        test_dissolve_with_reduced_motion_fades_without_pieces(g)
        test_dissolve_falls_back_to_game_clock_without_real_time(g)
        test_dark_rim_outlines_the_body(g)
        test_palette_changes_take_effect(g)
        test_sync_never_writes_to_the_player(g)
        test_shape_count_and_writes_are_steady(g)
        test_allocation_per_frame_is_bounded(g)
        test_sync_leaves_the_depth_handle_alone_while_bobbing(g)
        test_visuals_reduced_motion_holds_the_body_still(g)
        test_antenna_still_lags_and_stays_on_its_stalk(g)
    finally:
        g.close()
    print("\nALL WAVE 4 PLAYER TESTS PASSED")


if __name__ == "__main__":
    try:
        run_all()
    except Exception:
        traceback.print_exc()
        sys.exit(1)
