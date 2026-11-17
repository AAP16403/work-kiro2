"""Regression tests for the playerart item: the pod-robot character is visual only and its flag switches cleanly."""

import math

import config
from game import Game
from player import Player
from player_art import (
    ANTENNA_LEN, BLINK_PERIOD, BODY_A, BODY_B, DASH_BURST_S, DEFAULT_PALETTE, EYE_X, PlayerArt,
)
from states import GameStateName
from utils import Vec2, to_iso


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _player():
    return Player(pos=Vec2(0.0, 0.0))


def _art(g):
    return PlayerArt(g.batch, None)


def _eye(art, side):
    """(side, cheek, eye, glint, glint2, lid, lash, brow) row for the left (-1) or right (+1) eye."""
    return next(row for row in art._eyes if row[0] == side)


def _snapshot(p):
    return (
        p.pos.x, p.pos.y, p.hp, p.max_hp, p.shield, p.speed, p.is_dashing, p.dash_timer,
        p.dash_direction.x, p.dash_direction.y, p.is_boosting, p.damage_flash_timer,
        p.invincibility_timer, p.laser_until, p.dash_cooldown, p.dash_charges,
    )


def test_flag_defaults_to_pod_character(g):
    assert config.USE_PLAYER_ART is True, "USE_PLAYER_ART must default to True"
    print("[PASS] test_flag_defaults_to_pod_character passed (config.USE_PLAYER_ART is True)")


def test_default_palette_has_the_skin_keys(g):
    for key in ("body", "accent", "eye", "glow", "trail", "bullet"):
        assert key in DEFAULT_PALETTE, f"DEFAULT_PALETTE is missing skin key {key!r}"
    print("[PASS] test_default_palette_has_the_skin_keys passed (body, accent, eye, glow, trail, bullet present)")


def test_art_builds_only_in_the_given_batch(g):
    art = _art(g)
    assert len(art.shapes) >= 30, f"character built only {len(art.shapes)} shapes"
    for s in art.shapes:
        assert s._batch is g.batch, "every character shape must live in the batch it was given"
    count = len(art.shapes)
    art.delete()
    assert art.shapes == [], "delete() must release every shape"
    print(f"[PASS] test_art_builds_only_in_the_given_batch passed ({count} shapes, all in the batch, all released)")


def test_sync_returns_the_iso_body_centre(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(31.0, -12.0)
    shake = Vec2(3.0, -2.0)
    cx, cy = art.sync(p, shake, t=0.0, aim_dir=Vec2(1.0, 0.0))
    sx, sy = to_iso(p.pos, shake)
    assert abs(cx - sx) < 1e-9 and abs(cy - sy) < 1e-9, "at t=0 the bob is zero, so the centre is the iso point"
    art.delete()
    print("[PASS] test_sync_returns_the_iso_body_centre passed (centre follows shaken iso position)")


def test_partial_palette_falls_back_to_defaults(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    art.sync(p, Vec2(0.0, 0.0), t=0.0, aim_dir=Vec2(1.0, 0.0), palette={"body": (250, 10, 10)})
    assert tuple(art.body.color[:3]) == (250, 10, 10), "skin body colour not applied"
    assert tuple(_eye(art, -1)[2].color[:3]) == DEFAULT_PALETTE["eye"], "missing eye key must fall back to default"
    art.sync(p, Vec2(0.0, 0.0), t=0.0, aim_dir=Vec2(1.0, 0.0),
             palette={"body": (30, 200, 60), "eye": (1, 2, 3), "accent": (9, 9, 9), "glow": (5, 6, 7),
                      "trail": (8, 8, 8), "bullet": (11, 12, 13)})
    assert tuple(_eye(art, 1)[2].color[:3]) == (1, 2, 3), "skin eye colour not applied to the right eye"
    assert tuple(art.ant_tip.color[:3]) == (9, 9, 9), "skin accent colour not applied to the antenna tip"
    assert tuple(art.muzzle.color[:3]) == (11, 12, 13), "skin bullet colour not applied to the muzzle"
    art.delete()
    print("[PASS] test_partial_palette_falls_back_to_defaults passed (skin recolours; missing keys use defaults)")


def test_blink_about_every_three_seconds(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    closed_edges = 0
    was_closed = False
    closed_frames = 0
    frames = int(12.0 * 60)
    for i in range(frames):
        t = i / 60.0
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(1.0, 0.0))
        closed = _eye(art, -1)[5].opacity == 255
        closed_frames += 1 if closed else 0
        if closed and not was_closed:
            closed_edges += 1
        was_closed = closed
    expected = int(12.0 / BLINK_PERIOD)
    assert closed_edges == expected, f"expected {expected} blinks in 12 s (one per {BLINK_PERIOD:.0f} s), saw {closed_edges}"
    share = closed_frames / frames
    assert 0.02 < share < 0.06, f"eyes shut for {share:.3f} of the time, expected about 0.04"
    art.delete()
    print(f"[PASS] test_blink_about_every_three_seconds passed ({closed_edges} blinks in 12 s, {share:.3f} shut)")


def test_worried_expression_below_thirty_percent_hp(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    saved_hp = p.hp
    try:
        p.hp = 29
        art.sync(p, Vec2(0.0, 0.0), t=0.5, aim_dir=Vec2(1.0, 0.0))
        assert _eye(art, -1)[7].opacity > 0 and _eye(art, 1)[7].opacity > 0, "brows must show below 30 percent HP"
        assert art.frown.opacity == 255 and art.smile.opacity == 0, "mouth must frown below 30 percent HP"
        assert art.sweat.opacity > 0, "sweat drop must show below 30 percent HP"
        p.hp = 30
        art.sync(p, Vec2(0.0, 0.0), t=0.5, aim_dir=Vec2(1.0, 0.0))
        assert _eye(art, -1)[7].opacity == 0 and art.sweat.opacity == 0, "exactly 30 percent is not worried"
        assert art.smile.opacity == 255, "healthy mouth must smile"
    finally:
        p.hp = saved_hp
    art.delete()
    print("[PASS] test_worried_expression_below_thirty_percent_hp passed (worried at 29, calm at 30)")


def test_eyes_look_toward_the_aim(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    left = _eye(art, -1)[2]
    right = _eye(art, 1)[2]
    s = math.hypot(0.7, 0.35)
    screen_aim = (0.7 / s, 0.35 / s)

    def gaze(side, cx, cy):
        eye = _eye(art, side)[2]
        return (eye.position[0] - (cx + side * EYE_X), eye.position[1] - (cy + 1.6))

    cx, cy = art.sync(p, Vec2(0.0, 0.0), t=0.0, aim_dir=Vec2(1.0, 0.0))
    g_right = gaze(-1, cx, cy)
    dot = g_right[0] * screen_aim[0] + g_right[1] * screen_aim[1]
    assert dot > 1.0, f"pupils must lean toward the aim point (dot={dot:.3f})"

    cx, cy = art.sync(p, Vec2(0.0, 0.0), t=0.0, aim_dir=Vec2(-1.0, 0.0))
    g_left = gaze(-1, cx, cy)
    assert g_left[0] * screen_aim[0] + g_left[1] * screen_aim[1] < -1.0, "aim reversed must reverse the gaze"

    # World +x and +y together project straight up the screen.
    cx, cy = art.sync(p, Vec2(0.0, 0.0), t=0.0, aim_dir=Vec2(0.70710678, 0.70710678))
    up = gaze(1, cx, cy)
    assert abs(up[0]) < 1e-6 and up[1] > 1.4, f"aim straight up the screen must lift the pupils, got {up}"
    art.delete()
    print("[PASS] test_eyes_look_toward_the_aim passed (pupils follow the aim in screen space)")


def test_antenna_tip_sits_at_stalk_length(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    for i in range(40):
        t = i / 60.0
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(0.3, 0.9))
        dx = art.ant_tip.position[0] - art.stalk.position[0]
        dy = art.ant_tip.position[1] - art.stalk.position[1]
        assert abs(math.hypot(dx, dy) - ANTENNA_LEN) < 1e-6, "antenna tip must sit ANTENNA_LEN above its pivot"
    art.delete()
    print("[PASS] test_antenna_tip_sits_at_stalk_length passed (tip stays on the stalk while it sways)")


def test_dash_stretch_burst_then_recovers(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    t = 0.0
    for _ in range(30):
        t += 1.0 / 60.0
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(1.0, 0.0))
    assert abs(art.body.a - BODY_A) < 0.6, f"rest shape should be round-ish, a={art.body.a}"

    p.is_dashing = True
    p.dash_direction = Vec2(1.0, 0.0)
    t += 1.0 / 60.0
    art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(1.0, 0.0))
    assert art.body.a > BODY_A * 1.2, f"dash must stretch the body at once, a={art.body.a}"
    assert art.body.b < BODY_B * 0.95, f"dash must squeeze across the stretch, b={art.body.b}"

    p.is_dashing = False
    for _ in range(int((DASH_BURST_S + 0.1) * 60)):
        t += 1.0 / 60.0
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(1.0, 0.0))
    assert abs(art.body.a - BODY_A) < 0.6 and abs(art.body.b - BODY_B) < 0.6, "burst must fade back to rest"
    art.delete()
    print("[PASS] test_dash_stretch_burst_then_recovers passed (stretch on dash, back to rest after the burst)")


def test_moving_squashes_along_the_motion(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    t = 0.0
    for _ in range(90):
        t += 1.0 / 60.0
        p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(1.0, 0.0))
    assert art.body.a > BODY_A * 1.05, f"moving body should stretch along the motion, a={art.body.a}"
    assert art.body.b < BODY_B, f"moving body should narrow across the motion, b={art.body.b}"
    expected = -math.degrees(math.atan2(0.35, 0.7))
    assert abs(art.body.rotation - expected) < 3.0, f"stretch axis should match screen motion, rot={art.body.rotation}"
    assert art.thrust.opacity > 0 and any(j.opacity > 0 for j in art.jets), "thruster must glow while moving"
    art.delete()
    print("[PASS] test_moving_squashes_along_the_motion passed (stretch follows screen motion)")


def test_teleport_is_not_treated_as_motion(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    t = 0.0
    for _ in range(30):
        t += 1.0 / 60.0
        p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
        art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(1.0, 0.0))
    t += 1.0 / 60.0
    p.pos = Vec2(p.pos.x + 400.0, p.pos.y)
    art.sync(p, Vec2(0.0, 0.0), t=t, aim_dir=Vec2(1.0, 0.0))
    assert art._vel.length() == 0.0, "a position jump must not feed the squash velocity"
    art.delete()
    print("[PASS] test_teleport_is_not_treated_as_motion passed (respawn or shove does not squash)")


def test_sync_never_writes_to_the_player(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(12.0, -7.0)
    p.hp = 15
    p.shield = 60
    p.laser_until = 10.0
    t = 0.0
    for i in range(120):
        t += 1.0 / 60.0
        # The test changes the status, then checks that sync() only reads it.
        if i == 20:
            p.is_dashing = True
            p.dash_direction = Vec2(0.0, 1.0)
        if i == 30:
            p.is_dashing = False
            p.is_boosting = True
        if i == 60:
            p.is_boosting = False
            p.damage_flash_timer = 0.2
        if i == 90:
            p.damage_flash_timer = 0.0
            p.pos = Vec2(p.pos.x + 2.9, p.pos.y)
        before = _snapshot(p)
        art.sync(p, Vec2(2.0, -1.0), t=t, aim_dir=Vec2(-0.4, 0.9))
        assert _snapshot(p) == before, f"sync changed the player on frame {i}"
    art.delete()
    print("[PASS] test_sync_never_writes_to_the_player passed (position and status untouched over 120 frames)")


def test_identical_frames_write_nothing(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(4.0, 9.0)
    art.sync(p, Vec2(0.0, 0.0), t=2.25, aim_dir=Vec2(1.0, 0.0))
    before = dict(art._last)
    art.sync(p, Vec2(0.0, 0.0), t=2.25, aim_dir=Vec2(1.0, 0.0))
    assert art._last == before, "an unchanged frame must not rewrite any shape attribute"
    art.delete()
    print(f"[PASS] test_identical_frames_write_nothing passed ({len(before)} tracked values, 0 rewrites)")


def test_auras_follow_shield_laser_and_boost(g):
    art = _art(g)
    p = _player()
    p.pos = Vec2(0.0, 0.0)
    art.sync(p, Vec2(0.0, 0.0), t=1.0, aim_dir=Vec2(1.0, 0.0))
    assert art.aura_shield.opacity == 0 and art.aura_laser.opacity == 0 and art.aura_boost.opacity == 0
    p.shield = 50
    p.laser_until = 5.0
    p.is_boosting = True
    art.sync(p, Vec2(0.0, 0.0), t=1.0, aim_dir=Vec2(1.0, 0.0))
    assert art.aura_shield.opacity > 0 and art.aura_shield2.opacity > 0, "shield ring must show with shield"
    assert art.aura_laser.opacity > 0, "laser ring must show while the laser runs"
    assert art.aura_boost.opacity > 0, "boost ring must show while boosting"
    p.shield = 0
    p.laser_until = 0.0
    p.is_boosting = False
    art.sync(p, Vec2(0.0, 0.0), t=1.0, aim_dir=Vec2(1.0, 0.0))
    assert art.aura_shield.opacity == 0 and art.aura_laser.opacity == 0 and art.aura_boost.opacity == 0
    art.delete()
    print("[PASS] test_auras_follow_shield_laser_and_boost passed (rings show only while their status is active)")


def test_hidden_parts_are_placed_when_they_show(g):
    art = _art(g)
    p = _player()
    for i in range(10):
        p.pos = Vec2(p.pos.x + 3.0, p.pos.y)
        art.sync(p, Vec2(0.0, 0.0), t=1.0 + i / 60.0, aim_dir=Vec2(1.0, 0.0))  # eyes open, brows hidden
    p.pos = Vec2(p.pos.x + 50.0, p.pos.y - 20.0)
    p.hp = 10  # worried: brows show
    cx, cy = art.sync(p, Vec2(0.0, 0.0), t=1.6, aim_dir=Vec2(1.0, 0.0))  # 1.6 s is inside a blink
    for side in (-1, 1):
        _, _, eye, _, _, lid, lash, brow = _eye(art, side)
        assert lid.opacity == 255 and lash.opacity == 255, "eyes must be shut in this frame"
        assert lid.position == eye.position, "a lid shown after being hidden must sit on its eye"
        assert lash.position == eye.position, "a lash shown after being hidden must sit on its eye"
        assert brow.opacity == 235, "brows must show when worried"
        assert brow.position == (cx + side * EYE_X, cy + 1.6 + 4.6 + 2.6), "brow placed from stale position"
    assert art.sweat.opacity == 230 and art.frown.opacity == 255, "worry marks must show"
    art.delete()
    print("[PASS] test_hidden_parts_are_placed_when_they_show passed (no stale positions after a part reappears)")


def test_flag_switches_drawing_paths_over_120_frames(g):
    saved = config.USE_PLAYER_ART
    _new_run(g)
    vis = g.visuals
    shake = Vec2(3.0, -2.0)
    try:
        for frame in range(120):
            config.USE_PLAYER_ART = (frame // 10) % 2 == 0
            vis.sync_player(g.player, shake, t=frame / 60.0, aim_dir=Vec2(0.6, 0.8))
            if frame % 4 == 0:
                g.on_draw()
            if config.USE_PLAYER_ART:
                assert vis._player_art is not None, f"frame {frame}: art path expected"
                assert len(vis._player_handle.objs) == len(vis._player_art.shapes), f"frame {frame}: handle drifted"
            else:
                assert vis._player_art is None, f"frame {frame}: legacy path expected"
                assert len(vis._player_handle.objs) == 15, f"frame {frame}: legacy ship must keep its 15 shapes"
    finally:
        config.USE_PLAYER_ART = saved
    vis.sync_player(g.player, shake, t=2.0, aim_dir=Vec2(0.6, 0.8))
    g.on_draw()
    print("[PASS] test_flag_switches_drawing_paths_over_120_frames passed (120 frames, both paths, no exceptions)")


def test_legacy_ship_still_selectable(g):
    saved = config.USE_PLAYER_ART
    config.USE_PLAYER_ART = False
    try:
        _new_run(g)
        assert g.visuals._player_art is None
        assert len(g.visuals._player_handle.objs) == 15
        g.visuals.sync_player(g.player, Vec2(0.0, 0.0), t=0.5, aim_dir=Vec2(1.0, 0.0))
    finally:
        config.USE_PLAYER_ART = saved
    _new_run(g)
    assert g.visuals._player_art is not None, "a new run must build the art again when the flag is on"
    print("[PASS] test_legacy_ship_still_selectable passed (flag False builds the legacy ship, True the pod)")


def test_player_visual_depth_follows_body(g):
    _new_run(g)
    vis = g.visuals
    vis.sync_player(g.player, Vec2(0.0, 0.0), t=0.0, aim_dir=Vec2(1.0, 0.0))
    handle = vis._player_handle
    assert handle._depth_order is not None, "depth bucket must be assigned to the character"
    for s in handle.objs:
        assert s.group is not None, "every character shape must carry the depth group"
    print("[PASS] test_player_visual_depth_follows_body passed (character depth-sorted as one handle)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        _new_run(g)  # gives the game a player and visuals for the unit-level tests below
        test_flag_defaults_to_pod_character(g)
        test_default_palette_has_the_skin_keys(g)
        test_art_builds_only_in_the_given_batch(g)
        test_sync_returns_the_iso_body_centre(g)
        test_partial_palette_falls_back_to_defaults(g)
        test_blink_about_every_three_seconds(g)
        test_worried_expression_below_thirty_percent_hp(g)
        test_eyes_look_toward_the_aim(g)
        test_antenna_tip_sits_at_stalk_length(g)
        test_dash_stretch_burst_then_recovers(g)
        test_moving_squashes_along_the_motion(g)
        test_teleport_is_not_treated_as_motion(g)
        test_sync_never_writes_to_the_player(g)
        test_identical_frames_write_nothing(g)
        test_auras_follow_shield_laser_and_boost(g)
        test_hidden_parts_are_placed_when_they_show(g)
        test_flag_switches_drawing_paths_over_120_frames(g)
        test_legacy_ship_still_selectable(g)
        test_player_visual_depth_follows_body(g)
    finally:
        g.close()
    print("\nALL WAVE 1 PLAYERART TESTS PASSED")


if __name__ == "__main__":
    run_all()
