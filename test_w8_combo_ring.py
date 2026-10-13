"""Wave 8 combo ring tests: the combo timeout's sweep, the tier colours, the pulse on a tier change (full and reduced
motion), steady frames that build no objects, a ring clear of every HUD label at 980x620 and 1920x1080, the feature
switch, and a scripted run with real kills that reports the tier changes.

Covers: combo_window_fraction and ScoreTracker.combo_window_left (the sweep maths); combo_tier and combo_tier_color
(the tier mapping); ComboRing's pulse on each tier change, one per change, with the halo in full motion and a colour
flash with REDUCE_MOTION; steady frames (ring and HUD) under tracemalloc; the ring against every visible label; the
switch off building no ring; and a seeded run with kills in play. Plain functions that print [PASS] lines, run from
run_all().
"""

import gc
import os
import random
import tempfile
import tracemalloc

import pyglet

import config
import progress
import score as score_mod
from combo_ring import ComboRing, combo_tier, combo_tier_color
from enemy import Enemy
from game import Game
from projectile import Projectile
from score import ScoreTracker, combo_window_fraction
from states import GameStateName
from utils import Vec2

FRAME = 1.0 / 60.0
GREY = (150, 160, 172)
BLUE = (84, 176, 255)
GOLD = (255, 200, 60)
MAGENTA = (240, 90, 230)
_WINDOW = None
_SAVED_PATHS = None


def _batch():
    """A batch on a hidden window, so the ring's pyglet arcs have a GL context."""
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = pyglet.window.Window(width=64, height=64, visible=False)
    return pyglet.graphics.Batch()


def _redirect_saves():
    """Point the score and progress files at a temp folder, so a run never writes the repo's saves."""
    global _SAVED_PATHS
    folder = tempfile.mkdtemp(prefix="w8ring_")
    _SAVED_PATHS = (score_mod.HIGH_SCORE_FILE, progress.PROGRESS_FILE)
    score_mod.HIGH_SCORE_FILE = os.path.join(folder, "high_scores.json")
    progress.PROGRESS_FILE = os.path.join(folder, "progress.json")


def _restore_saves():
    global _SAVED_PATHS
    if _SAVED_PATHS is not None:
        score_mod.HIGH_SCORE_FILE, progress.PROGRESS_FILE = _SAVED_PATHS
        _SAVED_PATHS = None


def _ring(batch=None):
    ring = ComboRing(_batch() if batch is None else batch)
    ring.place(700.0, 570.0, 22.0, 5.0)
    return ring


def _frame(g):
    """One real frame: the game's update (fixed steps, the HUD tick) and then its draw (the HUD bars)."""
    g.update(FRAME)
    g.on_draw()


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.state.wave_active = True
    g.player.pos = Vec2(0.0, 0.0)
    return g.state


def _label_box(label):
    """(left, bottom, right, top) of a label, placed the way pyglet and tools/screens.py place it."""
    w = float(label.content_width)
    h = float(label.content_height)
    em = float(label.font_size) * (96.0 / 72.0)
    ax = label.anchor_x
    ay = label.anchor_y
    left = label.x - (w if ax == "right" else (w / 2.0 if ax == "center" else 0.0))
    if ay == "baseline":
        bottom, top = label.y - 0.22 * em, label.y + 0.72 * em
    elif ay == "bottom":
        bottom, top = label.y, label.y + h
    elif ay == "center":
        bottom, top = label.y - h / 2.0, label.y + h / 2.0
    else:
        bottom, top = label.y - h, label.y
    return (left, bottom, left + w, top)


def _overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


# ----------------------------------------------------------------------
# The sweep maths
# ----------------------------------------------------------------------

def test_sweep_fraction_maths():
    assert combo_window_fraction(0.0, 2.0) == 1.0
    assert combo_window_fraction(0.5, 2.0) == 0.75
    assert combo_window_fraction(1.0, 2.0) == 0.5
    assert combo_window_fraction(2.0, 2.0) == 0.0, "the timeout itself is closed"
    assert combo_window_fraction(3.0, 2.0) == 0.0, "past the timeout the window stays closed"
    assert combo_window_fraction(-0.5, 2.0) == 1.0, "a negative elapsed time clamps to the full window"
    assert combo_window_fraction(1.0, 0.0) == 0.0 and combo_window_fraction(1.0, -2.0) == 0.0, "no window, no sweep"

    t = ScoreTracker("normal")
    assert t.combo_window_left() == 0.0, "no combo, no sweep"
    for _ in range(4):
        t.on_enemy_kill("chaser")
    assert t.combo == 2.0 and t.combo_window_left() == 1.0, "a kill opens the full window"
    t.update(0.5)
    assert t.combo_window_left() == 0.75, t.combo_window_left()
    t.update(1.0)
    assert t.combo_window_left() == 0.25, t.combo_window_left()
    t.update(0.5)
    assert t.combo_window_left() == 0.0, "the timeout passed, the combo decays from here"
    assert t.combo == 1.5, f"the decay has begun, so the ring reads empty while the combo is still up: {t.combo}"
    t.on_enemy_kill("chaser")
    assert t.combo_window_left() == 1.0, "a new kill refills the window"
    t.on_player_hit()
    assert t.combo == 1.0 and t.combo_window_left() == 0.0, "a hit resets the combo and closes the sweep"

    ring = _ring()
    ring.update(2.0, 0.5)
    assert abs(ring.sweep_fraction - 0.5) < 1e-12, ring.sweep_fraction
    assert abs(ring._sweep.angle - 180.0) < 1e-9, ring._sweep.angle
    ring.update(2.0, 3.0)
    assert ring.sweep_fraction == 1.0 and ring._sweep.angle == 360.0, "a sweep reads at most one full turn"
    ring.update(1.0, 0.8)
    assert ring.sweep_fraction == 0.0 and not ring.sweep_visible, "at x1 there is no combo window to show"
    print("[PASS] test_sweep_fraction_maths passed (1.0 after a kill, 0.5 at 1 s, 0.0 at the 2 s timeout, 0 at x1)")


# ----------------------------------------------------------------------
# Tier colours
# ----------------------------------------------------------------------

def test_tier_colour_mapping():
    expect = {1.0: 0, 1.25: 0, 1.99: 0, 2.0: 1, 3.75: 1, 4.0: 2, 5.99: 2, 6.0: 3, 6.5: 3, 8.0: 3}
    for combo, tier in expect.items():
        assert combo_tier(combo) == tier, (combo, combo_tier(combo), tier)
    assert combo_tier_color(0) == GREY and combo_tier_color(1) == BLUE, "grey, then blue"
    assert combo_tier_color(2) == GOLD and combo_tier_color(3) == MAGENTA, "gold, then magenta"
    assert combo_tier_color(9) == MAGENTA and combo_tier_color(-1) == GREY, "out-of-range tiers clamp"
    assert len(config.COMBO_RING_TIER_MIN) == len(config.COMBO_RING_TIER_COLORS) == 4, "four tiers, four colours"
    assert len({combo_tier_color(t) for t in range(4)}) == 4, "the four tiers are told apart by colour"
    assert float(config.COMBO_RING_TIER_MIN[-1]) <= float(score_mod.COMBO_MAX), "the top tier is reachable"
    ring = _ring()
    ring.update(6.5, 0.6)
    assert ring.tier == 3 and ring.sweep_color == MAGENTA, ring.sweep_color
    ring.update(4.5, 0.6)
    assert ring.sweep_color == GOLD, ring.sweep_color
    print("[PASS] test_tier_colour_mapping passed (x1 grey, x2 blue, x4 gold, x6 magenta; the sweep takes the tier colour)")


# ----------------------------------------------------------------------
# The pulse
# ----------------------------------------------------------------------

def test_pulse_fires_once_per_tier_change():
    saved = config.REDUCE_MOTION
    try:
        config.REDUCE_MOTION = False
        ring = _ring()
        ring.update(1.0, 0.0)
        assert ring.pulse_count == 0 and not ring.pulsing, "the first tier does not pulse"
        ring.update(1.25, 1.0)
        assert ring.pulse_count == 0, "a kill inside the same tier does not pulse"
        ring.update(2.0, 1.0)
        assert ring.pulse_count == 1 and ring.pulsing, "x2 is a tier change: one pulse"
        ring.tick(0.1)
        assert ring.pulsing and ring.halo_visible, "the halo shows while the pulse runs"
        assert ring.halo_radius > 22.0, f"the halo grows in full motion: {ring.halo_radius}"
        ring.tick(0.3)
        assert not ring.pulsing and not ring.halo_visible, "the pulse ends after COMBO_RING_PULSE_SECONDS"
        ring.update(2.25, 1.0)
        assert ring.pulse_count == 1, "x2.25 is still blue"
        ring.update(4.0, 1.0)
        assert ring.pulse_count == 2 and ring.tier == 2, "x4 is a tier change"
        ring.update(1.0, 0.0)
        assert ring.pulse_count == 3 and ring.tier == 0, "a hit drops the tier and that change pulses too"
        ring.update(2.0, 1.0)
        assert ring.pulse_count == 4
        ring.tick(0.2)
        ring.update(4.0, 1.0)  # a second change mid-pulse restarts the pulse rather than stacking a second
        assert ring.pulse_count == 5 and ring.pulsing
        ring.tick(0.2)
        assert ring.pulsing, "the restarted pulse runs its full length"
        ring.tick(0.2)
        assert not ring.pulsing
    finally:
        config.REDUCE_MOTION = saved
    print("[PASS] test_pulse_fires_once_per_tier_change passed (up and down, one pulse each, no pulse inside a tier)")


def test_reduced_motion_pulse_is_a_colour_flash_only():
    saved = config.REDUCE_MOTION
    try:
        config.REDUCE_MOTION = True
        ring = _ring()
        ring.update(1.0, 0.0)
        ring.update(2.0, 0.0)  # the sweep is empty: the flash must still show on the track
        assert ring.pulse_count == 1 and ring.pulsing
        base_track = ring.track_color
        geom = ring.geometry
        ring.tick(0.1, reduce_motion=True)
        assert not ring.halo_visible, "no halo under reduced motion"
        assert ring.halo_radius == 22.0, f"nothing grows under reduced motion: {ring.halo_radius}"
        assert ring.geometry == geom, "the ring does not move or resize"
        flash_track = ring.track_color
        assert flash_track[3] > base_track[3], f"the track flashes brighter: {base_track} -> {flash_track}"
        assert flash_track[:3] != base_track[:3], "the track takes the tier colour"
        ring.tick(0.1, reduce_motion=True)
        assert ring.track_color[3] < flash_track[3], "the flash fades out"
        ring.tick(0.3, reduce_motion=True)
        assert not ring.pulsing
        assert ring.track_color == base_track and ring.sweep_color == BLUE, "the colours settle back"
    finally:
        config.REDUCE_MOTION = saved
    print("[PASS] test_reduced_motion_pulse_is_a_colour_flash_only passed (no halo, no movement, the flash fades)")


# ----------------------------------------------------------------------
# Steady frames build no objects
# ----------------------------------------------------------------------

def test_steady_frames_build_no_new_objects():
    saved = config.REDUCE_MOTION
    try:
        config.REDUCE_MOTION = False
        ring = _ring()
        ring.update(2.0, 1.0)

        def frame(f):
            # The sweep moves every frame, and the tier changes every 10 s, so pulses run too.
            tier_combo = 2.0 if (f // 600) % 2 == 0 else 4.0
            ring.update(tier_combo, (f % 120) / 120.0)
            ring.tick(FRAME)

        for f in range(60):
            frame(f)
        tracemalloc.start()
        try:
            gc.collect()
            base, _ = tracemalloc.get_traced_memory()
            for f in range(60, 3060):
                frame(f)
            gc.collect()
            net, _ = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert ring.pulse_count >= 4, ring.pulse_count
        assert net - base < 16384, f"ring net growth {net - base} bytes over 3000 frames"
    finally:
        config.REDUCE_MOTION = saved
    print(f"[PASS] test_steady_frames_build_no_new_objects passed (ring: net {net - base} bytes over 3000 frames)")


def test_hud_steady_frames_build_no_new_objects():
    _redirect_saves()
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        for _ in range(8):
            g.score.on_enemy_kill("chaser")  # combo 3.0 (blue): the warm-up decays it through to x1
        hud = g.hud

        def frame(_f):
            g.score.update(FRAME)
            hud.tick(FRAME)
            hud.update_bars(g.player, s, score=g.score, status_segments=[])

        # Tracing starts before the warm-up: the first traced frames also record each new allocation site
        # (tracemalloc's own table), which is a one-time cost and not growth per frame. The traced total counts
        # every thread, and pyglet's audio driver refills on its own thread, so two windows are measured and the
        # smaller is judged: a frame that allocates grows in both, a refill burst grows in one.
        nets = []
        tracemalloc.start()
        try:
            for f in range(480):  # warm-up: the timeout passes and the combo decays to x1
                frame(f)
            assert g.score.combo == 1.0 and hud.combo_ring.tier == 0, (g.score.combo, hud.combo_ring.tier)
            for _window in range(2):
                gc.collect()  # cyclic garbage from earlier is freed now, not later mid-measurement
                base, _ = tracemalloc.get_traced_memory()
                for f in range(1500):
                    frame(f)
                gc.collect()
                net_now, _ = tracemalloc.get_traced_memory()
                nets.append(net_now - base)
        finally:
            tracemalloc.stop()
        net = min(nets)
    finally:
        g.close()
        _restore_saves()
    assert net < 16384, f"HUD net growth {nets} bytes over two windows of 1500 steady frames"
    print(f"[PASS] test_hud_steady_frames_build_no_new_objects passed (HUD: net {net} bytes over 1500 frames, best of two)")


# ----------------------------------------------------------------------
# Layout: the ring clears every label, at both sizes
# ----------------------------------------------------------------------

def test_ring_clears_every_label_at_both_sizes():
    _redirect_saves()
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        g.score.on_enemy_kill("chaser")
        g.score.on_enemy_kill("chaser")
        g.score.on_enemy_kill("chaser")
        g.score.on_enemy_kill("chaser")
        hud = g.hud
        hud.push_toast("Ring check", "ACHIEVEMENT UNLOCKED")
        names = (
            "hp_label", "hp_value_label", "shield_label", "shield_value_label", "boost_label", "boost_value_label",
            "wave_label", "meta_label", "status_label", "score_title_label", "score_value_label", "combo_label",
        )
        hidden_at = []
        # The two sizes the screens suite checks must keep the ring on and clear. The others may also hide the ring
        # at a tiny size where the status line cannot clear it; the ring never overlaps a label while it is shown.
        for w, h in ((980, 620), (1920, 1080), (640, 400), (800, 500), (1280, 720), (1440, 900), (2560, 1440), (480, 320)):
            hud.layout(w, h)
            hud.update_bars(g.player, s, score=g.score, status_segments=[(0, "Boost 100%"), (3, "AUTO OFF")])
            cx, cy, r, t = hud.combo_ring.geometry
            ring_box = (cx - (r + t), cy - (r + t), cx + (r + t), cy + (r + t))
            labels = [getattr(hud, n) for n in names]
            labels += [hud.ultra_gauge._count, hud.ultra_gauge._caption, hud.skin_chip._label]
            labels += list(hud.weapon_chip.labels())
            labels += [hud.toast_view._title, hud.toast_view._sub, hud.toast_view._count]
            checked = 0
            for label in labels:
                if not str(label.text or "").strip():
                    continue
                checked += 1
                box = _label_box(label)
                if hud.combo_ring.enabled:
                    assert not _overlaps(ring_box, box), f"{w}x{h}: the combo ring {ring_box} overlaps {label.text!r} {box}"
            assert checked >= 10, f"only {checked} labels had text at {w}x{h}"
            left, bottom, top = hud._combo_ring_span
            assert ring_box[0] == left and ring_box[1] == bottom and ring_box[3] == top, (ring_box, hud._combo_ring_span)
            assert ring_box[2] <= hud.score_title_label.x, f"{w}x{h}: the ring sits left of the score panel's text"
            if not hud.combo_ring.enabled:
                hidden_at.append(f"{w}x{h}")
            if (w, h) in ((980, 620), (1920, 1080)):
                assert hud.combo_ring.enabled, f"{w}x{h}: the ring must be on at the screens sizes"
        assert "980x620" not in hidden_at and "1920x1080" not in hidden_at
        assert "480x320" in hidden_at, "at 480x320 the status line cannot clear the ring, so the ring hides"
        print("[PASS] test_ring_clears_every_label_at_both_sizes passed (no overlap with any labelled HUD text; "
              f"ring on at 980x620 and 1920x1080, hidden at {', '.join(hidden_at)})")
    finally:
        g.close()
        _restore_saves()


# ----------------------------------------------------------------------
# The switch
# ----------------------------------------------------------------------

def test_switch_off_builds_no_ring():
    saved = config.ENABLE_COMBO_RING
    _redirect_saves()
    try:
        config.ENABLE_COMBO_RING = False
        g = Game()
        g.set_visible(False)
        try:
            s = _new_run(g)
            assert g.hud.combo_ring is None and g.hud._combo_ring_span is None, "no ring when the switch is off"
            g.score.on_enemy_kill("chaser")
            g.hud.update_bars(g.player, s, score=g.score, status_segments=[])
            g.hud.tick(FRAME)
        finally:
            g.close()
    finally:
        config.ENABLE_COMBO_RING = saved
        _restore_saves()
    assert config.ENABLE_COMBO_RING is True, "the switch ships on"
    print("[PASS] test_switch_off_builds_no_ring passed (switch off: no ring, no reserved space; switch ships on)")


# ----------------------------------------------------------------------
# In play: a scripted run with real kills
# ----------------------------------------------------------------------

def test_scripted_run_with_kills_reports_tier_changes():
    _redirect_saves()
    random.seed(1729)
    g = Game()
    g.set_visible(False)
    saved = config.REDUCE_MOTION
    config.REDUCE_MOTION = False
    seen = []
    try:
        s = _new_run(g)
        ring = g.hud.combo_ring
        # A far, slow enemy that never dies keeps the wave active, so no wave clears or rewards fire mid-run.
        dummy = Enemy(pos=Vec2(-400.0, 0.0), hp=10 ** 6, speed=0.0, behavior="chaser")

        def record(label):
            seen.append((label, round(g.score.combo, 2), ring.tier, ring.pulse_count))

        for kill in range(1, 23):
            g.player.invincibility_timer = 1e9  # a hit would reset the combo; the run is about kills
            victim = Enemy(pos=Vec2(200.0, 0.0), hp=1, speed=0.0, behavior="chaser")
            s.enemies[:] = [dummy, victim]
            s.projectiles.append(Projectile(
                pos=Vec2(150.0, 0.0), vel=Vec2(900.0, 0.0), damage=int(g.player.damage), ttl=2.0, owner="player",
            ))
            for _ in range(120):
                _frame(g)
                if victim not in s.enemies:
                    break
            assert victim not in s.enemies, f"kill {kill} did not land"
            record(f"kill {kill}")
            for _ in range(30):  # half a second between kills keeps the combo window open
                _frame(g)
        pulses_up = ring.pulse_count
        for step in range(480):  # 8 s with no kills: the timeout passes and the combo decays
            _frame(g)
            if step % 60 == 59:
                record(f"+{(step + 1) // 60}s")
        pulses_total = ring.pulse_count
    finally:
        config.REDUCE_MOTION = saved
        g.close()
        _restore_saves()

    def tier_at(label):
        return next(entry[2] for entry in seen if entry[0] == label)

    assert tier_at("kill 3") == 0 and tier_at("kill 4") == 1, "x2 comes on the fourth kill"
    assert tier_at("kill 11") == 1 and tier_at("kill 12") == 2, "x4 comes on the twelfth kill"
    assert tier_at("kill 19") == 2 and tier_at("kill 20") == 3, "x6 comes on the twentieth kill"
    assert pulses_up == 3, f"three tier changes on the way up, saw {pulses_up}"
    assert pulses_total > pulses_up, "the decay changes tiers too, and each change pulses"
    changes = []
    last = 0
    for label, combo, tier, pulses in seen:
        if tier != last:
            changes.append(f"{label}: x{combo:.2f} {['grey', 'blue', 'gold', 'magenta'][tier]}")
            last = tier
    print("[PASS] test_scripted_run_with_kills_reports_tier_changes passed (22 kills, then 8 s of decay)")
    print("       tier changes seen: " + "; ".join(changes))
    print(f"       pulses: {pulses_up} on the way up, {pulses_total} in total")


def run_all():
    test_sweep_fraction_maths()
    test_tier_colour_mapping()
    test_pulse_fires_once_per_tier_change()
    test_reduced_motion_pulse_is_a_colour_flash_only()
    test_steady_frames_build_no_new_objects()
    test_hud_steady_frames_build_no_new_objects()
    test_ring_clears_every_label_at_both_sizes()
    test_switch_off_builds_no_ring()
    test_scripted_run_with_kills_reports_tier_changes()
    print("ALL W8 COMBO RING TESTS PASSED")


if __name__ == "__main__":
    run_all()
