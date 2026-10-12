"""Deterministic tests for wave 2 item hudv2: the HUD redesign, the radial Ultra gauge, the weapon
and skin chips, and the achievement toast queue. Plain functions that print [PASS] lines."""

import importlib.util

import config
from game import Game
from hud import achievement_name, current_skin_name
from hud_widgets import ToastQueue, ultra_fraction, weapon_swatch
from states import GameStateName
from weapons import WEAPONS, get_weapon_color


def _module_present(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _tick(g, frames=1):
    # Call update() directly: pyglet.clock.tick() would also fire the game's scheduled
    # update with real elapsed time and double-step the simulation.
    for _ in range(frames):
        g.dispatch_events()
        g.update(1.0 / 60.0)


def _refresh(g):
    """Push the current run state through the HUD the same way PlayingState.draw does."""
    g.hud.update_bars(
        g.player,
        g.state,
        score=g.score,
        has_infinite_boost=False,
        crit_chance_bonus=0.0,
        status_segments=[],
    )


# ----------------------------------------------------------------------
# Toast queue (pure logic)
# ----------------------------------------------------------------------

def test_toast_queue_is_fifo_one_at_a_time():
    q = ToastQueue()
    q.push("First", "ACHIEVEMENT UNLOCKED")
    q.push("Second", "ACHIEVEMENT UNLOCKED")
    q.push("Third", "ACHIEVEMENT UNLOCKED")
    assert q.current == ("First", "ACHIEVEMENT UNLOCKED"), q.current
    assert q.queued == 2, q.queued
    q.tick(2.5)
    assert q.current[0] == "Second", q.current
    q.tick(2.5)
    assert q.current[0] == "Third", q.current
    q.tick(2.5)
    assert q.current is None and q.queued == 0
    print("[PASS] test_toast_queue_is_fifo_one_at_a_time passed (order kept, one toast on screen at a time)")


def test_toast_expires_at_2_5_seconds():
    q = ToastQueue()
    q.push("Only", "sub")
    q.tick(2.49)
    assert q.current is not None, "toast must still be on screen before 2.5 s"
    q.tick(0.02)
    assert q.current is None, "toast must be gone after 2.5 s"
    assert q.alpha() == 0.0
    print("[PASS] test_toast_expires_at_2_5_seconds passed (on screen until 2.5 s, then cleared)")


def test_toast_carries_leftover_time_into_next():
    q = ToastQueue()
    q.push("A", "")
    q.push("B", "")
    q.tick(2.6)
    assert q.current[0] == "B", q.current
    assert abs(q.age - 0.1) < 1e-9, f"next toast should start with the 0.1 s overflow, got {q.age}"
    print("[PASS] test_toast_carries_leftover_time_into_next passed (queued toast keeps exact spacing)")


def test_toast_fade_curve():
    q = ToastQueue()
    q.push("A", "")
    assert q.alpha() == 0.0, "a new toast starts transparent"
    q.tick(0.075)
    assert abs(q.alpha() - 0.5) < 1e-6, f"half-way through fade-in should be 0.5, got {q.alpha()}"
    q.tick(0.925)  # age 1.0: fully opaque in the middle
    assert q.alpha() == 1.0, q.alpha()
    q.tick(1.2)  # age 2.2: last 0.3 s of a 0.4 s fade-out
    assert abs(q.alpha() - 0.75) < 1e-6, f"fade-out should read 0.75 at 2.2 s, got {q.alpha()}"
    print("[PASS] test_toast_fade_curve passed (fade-in, hold and fade-out values match)")


def test_toast_queue_caps_pending_and_counts_drops():
    q = ToastQueue(max_pending=3)
    q.push("On screen", "")
    accepted = [q.push(f"Queued {i}", "") for i in range(5)]
    assert accepted == [True, True, True, False, False], accepted
    assert q.queued == 3 and q.dropped == 2, (q.queued, q.dropped)
    print("[PASS] test_toast_queue_caps_pending_and_counts_drops passed (3 queued, 2 dropped)")


# ----------------------------------------------------------------------
# Ultra gauge
# ----------------------------------------------------------------------

def test_ultra_fraction_at_zero_half_and_full():
    assert ultra_fraction(0, 2) == 0.0
    assert ultra_fraction(1, 2) == 0.5
    assert ultra_fraction(2, 2) == 1.0
    assert ultra_fraction(9, 2) == 1.0, "over-full charge must clamp to 1.0"
    assert ultra_fraction(1, 0) == 0.0, "zero capacity must not divide by zero"
    print("[PASS] test_ultra_fraction_at_zero_half_and_full passed (0, 0.5, 1.0 with clamp)")


def test_ultra_gauge_follows_player_charges(g):
    s = _new_run(g)
    gauge = g.hud.ultra_gauge
    g.player.ultra_max_charges = 2
    g.player.ultra_charges = 0
    _refresh(g)
    assert gauge.fraction == 0.0 and gauge.count_text == "0/2", (gauge.fraction, gauge.count_text)
    assert not gauge._fill.visible, "an empty gauge draws no fill arc"
    g.player.ultra_charges = 1
    _refresh(g)
    assert abs(gauge.fraction - 0.5) < 1e-9 and gauge.count_text == "1/2", gauge.count_text
    assert abs(gauge._fill.angle - 180.0) < 1e-6, gauge._fill.angle
    g.player.ultra_charges = 2
    _refresh(g)
    assert abs(gauge.fraction - 1.0) < 1e-9 and gauge.count_text == "2/2"
    assert abs(gauge._fill.angle - 360.0) < 1e-6, gauge._fill.angle
    print("[PASS] test_ultra_gauge_follows_player_charges passed (0, half and full sweep 0, 180 and 360 deg)")


def test_ultra_full_charge_pulse_respects_reduce_motion(g):
    _new_run(g)
    gauge = g.hud.ultra_gauge
    g.player.ultra_max_charges = 2
    g.player.ultra_charges = 2
    _refresh(g)
    saved = getattr(config, "REDUCE_MOTION", False)
    try:
        # Drive the real path: HUD.tick() reads config.REDUCE_MOTION every frame.
        config.REDUCE_MOTION = False
        seen = set()
        for _ in range(30):
            g.hud.tick(0.05)
            seen.add(gauge._fill.opacity)
        assert len(seen) > 3, f"a full gauge should pulse, saw opacities {sorted(seen)}"
        assert min(seen) >= 170 and max(seen) <= 255, sorted(seen)

        config.REDUCE_MOTION = True
        for _ in range(30):
            g.hud.tick(0.05)
            assert gauge._fill.opacity == 255, "reduced motion must hold the ring steady"
    finally:
        config.REDUCE_MOTION = saved
    print("[PASS] test_ultra_full_charge_pulse_respects_reduce_motion passed (pulse on, steady with REDUCE_MOTION)")


def test_partial_gauge_never_pulses(g):
    _new_run(g)
    gauge = g.hud.ultra_gauge
    g.player.ultra_max_charges = 2
    g.player.ultra_charges = 1
    _refresh(g)
    for step in range(20):
        gauge.animate(step * 0.07)
        assert gauge._fill.opacity == 255, "only a full charge pulses"
    print("[PASS] test_partial_gauge_never_pulses passed (half charge keeps a steady ring)")


# ----------------------------------------------------------------------
# Weapon and skin chips
# ----------------------------------------------------------------------

def test_weapon_chip_text_for_known_weapon(g):
    _new_run(g)
    wp = WEAPONS["basic"]
    g.player.current_weapon = wp
    g.player.ultra_max_charges = 2
    _refresh(g)
    chip = g.hud.weapon_chip
    assert chip.name_text == "BASIC GUN", repr(chip.name_text)
    expected_crit = f"CRIT {int(round(wp.crit_chance * 100))}%"
    assert chip.crit_text == expected_crit, (chip.crit_text, expected_crit)
    if not _module_present("projectile_art"):
        # Until projectile_art lands, the swatch is the weapon table colour for its projectile type.
        expected_swatch = tuple(get_weapon_color(wp.projectile_type))[:3]
        assert chip.swatch_color == expected_swatch, (chip.swatch_color, expected_swatch)
    print(f"[PASS] test_weapon_chip_text_for_known_weapon passed (name {chip.name_text!r}, {chip.crit_text!r})")


def test_weapon_chip_swatch_uses_projectile_art_when_present(g):
    if not _module_present("projectile_art"):
        print("[SKIP requires-wave1] test_weapon_chip_swatch_uses_projectile_art_when_present (projectile_art.py missing)")
        return
    import projectile_art
    from hud_widgets import weapon_swatch
    style = projectile_art.STYLES.get(WEAPONS["basic"].name)
    assert style is not None, "projectile_art must define a style for Basic Gun"
    assert weapon_swatch(WEAPONS["basic"]) == tuple(style.color)[:3]
    print("[PASS] test_weapon_chip_swatch_uses_projectile_art_when_present passed (swatch == projectile_art colour)")


def test_skin_chip_shows_selected_name(g):
    _new_run(g)
    g.hud.set_skin_name("Neon Test")
    assert g.hud.skin_name == "Neon Test"
    assert g.hud.skin_chip.text == "Neon Test"
    assert g.hud.skin_chip._label.text == "NEON TEST", g.hud.skin_chip._label.text
    print("[PASS] test_skin_chip_shows_selected_name passed (chip text is the skin name, uppercased)")


def test_current_skin_name_never_raises():
    name = current_skin_name({})
    assert isinstance(name, str) and name, repr(name)
    print(f"[PASS] test_current_skin_name_never_raises passed (name {name!r} for an empty progress dict)")


def test_hud_keeps_existing_numbers(g):
    _new_run(g)
    g.player.hp = 77
    g.player.max_hp = 100
    g.player.shield = 30
    _refresh(g)
    assert g.hud.hp_value_label.text == "77/100", g.hud.hp_value_label.text
    assert g.hud.shield_value_label.text == f"30/{config.SHIELD_MAX}", g.hud.shield_value_label.text
    assert g.hud.wave_label.text == f"WAVE {int(g.state.wave):02d}", g.hud.wave_label.text
    assert g.hud.score_value_label.text == f"{g.score.score:,}", g.hud.score_value_label.text
    print("[PASS] test_hud_keeps_existing_numbers passed (HULL, SHIELD, WAVE and SCORE text unchanged)")


# ----------------------------------------------------------------------
# Toasts in the HUD
# ----------------------------------------------------------------------

def test_hud_toast_order_and_expiry(g):
    _new_run(g)
    hud = g.hud
    hud.toasts.clear()
    hud.push_toast("Alpha", "ACHIEVEMENT UNLOCKED")
    hud.push_toast("Beta", "ACHIEVEMENT UNLOCKED")
    assert hud.toast_view.visible and hud.toast_view.title_text == "Alpha", hud.toast_view.title_text
    assert hud.toast_view.subtitle_text == "ACHIEVEMENT UNLOCKED"
    hud.tick(2.5)
    assert hud.toast_view.title_text == "Beta", hud.toast_view.title_text
    hud.tick(2.5)
    assert not hud.toast_view.visible, "the view must hide when the queue is empty"
    print("[PASS] test_hud_toast_order_and_expiry passed (Alpha then Beta, then hidden)")


def test_hud_achievement_feed_queues_one_toast_per_id(g):
    _new_run(g)
    hud = g.hud
    hud.toasts.clear()
    count = hud.push_achievement_toasts(["first_blood", "survive_ten"])
    assert count == 2 and hud.toasts.queued == 1, (count, hud.toasts.queued)
    assert hud.toast_view.subtitle_text == "ACHIEVEMENT UNLOCKED"
    assert hud.push_achievement_toasts([]) == 0
    hud.toasts.clear()
    print("[PASS] test_hud_achievement_feed_queues_one_toast_per_id passed (two ids queue two toasts)")


def test_achievement_names_resolve_when_present():
    if not _module_present("achievements"):
        print("[SKIP requires-wave1] test_achievement_names_resolve_when_present (achievements.py missing)")
        return
    import achievements
    first = achievements.ACHIEVEMENTS[0]
    assert achievement_name(first.id) == first.name
    assert achievement_name("no_such_id") == "no_such_id"
    print("[PASS] test_achievement_names_resolve_when_present passed (toast names come from achievements)")


def test_toast_stays_under_score_panel(g):
    _new_run(g)
    for w, h in ((980, 620), (1920, 1080)):
        g.hud.layout(w, h)
        g.hud.push_toast("Check", "ACHIEVEMENT UNLOCKED")
        score = g.hud._frames["score"][-1]  # the fill rectangle is last in its list
        toast = g.hud.toast_view._frame[-1]
        assert toast.y + toast.height <= score.y, f"toast must sit under the score panel at {w}x{h}"
        assert abs((toast.x + toast.width) - (score.x + score.width)) < 1.5, "toast shares the score panel's right edge"
        assert toast.x >= 0 and toast.y >= 0 and toast.x + toast.width <= w and toast.y + toast.height <= h
        g.hud.toasts.clear()
        g.hud.tick(0.0)
    print("[PASS] test_toast_stays_under_score_panel passed (980x620 and 1920x1080)")


def test_status_line_clear_of_score_panel(g):
    _new_run(g)
    for w, h in ((980, 620), (1920, 1080)):
        g.hud.layout(w, h)
        status = g.hud._frames["status"][-1]
        score = g.hud._frames["score"][-1]
        status_top = status.y + status.height
        score_top = score.y + score.height
        vertical = status.y < score_top and score.y < status_top
        if vertical:
            assert status.x + status.width <= score.x, f"status bar must not reach the score panel at {w}x{h}"
        assert g.hud._status_max_w <= status.width, "fitted text budget must fit inside the bar"
    print("[PASS] test_status_line_clear_of_score_panel passed (no status/score overlap at 980x620 or 1920x1080)")


def test_status_line_clear_of_gauge_and_health_panel(g):
    _new_run(g)
    for w, h in ((980, 620), (1920, 1080)):
        g.hud.layout(w, h)
        status = g.hud._frames["status"][-1]
        hull = g.hud._frames["hull"][-1]
        caption = g.hud.ultra_gauge._caption
        caption_right = caption.x + caption.content_width
        ring_top = g.hud.ultra_gauge._geom[1] + g.hud.ultra_gauge._geom[2]
        ring_bottom = g.hud.ultra_gauge._geom[1] - g.hud.ultra_gauge._geom[2]
        status_top = status.y + status.height
        if status.y < ring_top and ring_bottom < status_top:
            assert status.x >= caption_right, f"status bar runs into the Ultra gauge at {w}x{h}"
        hull_top = hull.y + hull.height
        if status.y < hull_top and hull.y < status_top:
            assert status.x >= hull.x + hull.width or status.x + status.width <= hull.x, (
                f"status bar overlaps the health panel at {w}x{h}"
            )
    print("[PASS] test_status_line_clear_of_gauge_and_health_panel passed (no overlap with the gauge or the health panel)")


def test_panels_draw_under_bars_and_chips(g):
    _new_run(g)
    g.hud.layout(980, 620)
    hud = g.hud
    for shape in hud._frames["hull"]:
        assert shape._batch is hud._frame_batch, "panel backgrounds must draw in the frame batch"
    for shape in (hud.hp_bar, hud.shield_bar, hud.boost_bar, hud.weapon_chip._swatch):
        assert shape._batch is hud.batch, "bars and swatches must draw above the panel backgrounds"
    print("[PASS] test_panels_draw_under_bars_and_chips passed (frames in the back batch, bars and swatches on top)")


def test_labels_stay_inside_window(g):
    _new_run(g)
    g.player.current_weapon = WEAPONS["flak"]
    g.player.ultra_max_charges = 2
    g.player.ultra_charges = 2
    g.hud.set_skin_name("A Rather Long Skin Name For Fitting")
    g.hud.push_toast("A Very Long Achievement Name That Must Be Trimmed", "ACHIEVEMENT UNLOCKED")
    for w, h in ((980, 620), (1920, 1080)):
        g.hud.layout(w, h)
        g.hud.toasts.tick(0.0)
        _refresh(g)
        for lbl, _base in g.hud._scaled_labels:
            if not lbl.text or not lbl.visible:
                continue
            left, right, bottom, top = _label_box(lbl)
            assert left >= -1 and right <= w + 1 and bottom >= -1 and top <= h + 1, (
                f"label {lbl.text!r} leaves the {w}x{h} window: {(left, bottom, right, top)}"
            )
    print("[PASS] test_labels_stay_inside_window passed (every HUD label is inside 980x620 and 1920x1080)")


def _label_box(lbl):
    """Approximate pixel box of a pyglet label from its anchor, content size and position."""
    w = float(lbl.content_width)
    h = float(lbl.content_height)
    if lbl.anchor_x == "right":
        left = lbl.x - w
    elif lbl.anchor_x == "center":
        left = lbl.x - w / 2.0
    else:
        left = lbl.x
    if lbl.anchor_y == "top":
        bottom = lbl.y - h
    elif lbl.anchor_y == "center":
        bottom = lbl.y - h / 2.0
    elif lbl.anchor_y == "baseline":
        bottom = lbl.y - 0.22 * h
    else:
        bottom = lbl.y
    return left, left + w, bottom, bottom + h


def test_hud_draws_for_many_frames_with_toasts_and_full_gauge(g):
    _new_run(g)
    g.player.ultra_max_charges = 2
    g.player.ultra_charges = 2
    g.player.current_weapon = WEAPONS["railgun"]
    g.hud.toasts.clear()
    g.hud.push_achievement_toasts(["first_blood", "boss_hunter", "combo_six"])
    for _ in range(120):  # two seconds: the first toast is still up with two queued behind it
        g.dispatch_events()
        g.update(1.0 / 60.0)
        _refresh(g)
        g.hud.draw()
    assert g.hud.toast_view.visible, "the first toast must still be on screen after 2 s"
    assert g.hud.toasts.queued == 2, g.hud.toasts.queued
    print("[PASS] test_hud_draws_for_many_frames_with_toasts_and_full_gauge passed (120 frames, no exceptions)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_ultra_gauge_follows_player_charges(g)
        test_ultra_full_charge_pulse_respects_reduce_motion(g)
        test_partial_gauge_never_pulses(g)
        test_weapon_chip_text_for_known_weapon(g)
        test_weapon_chip_swatch_uses_projectile_art_when_present(g)
        test_skin_chip_shows_selected_name(g)
        test_hud_keeps_existing_numbers(g)
        test_hud_toast_order_and_expiry(g)
        test_hud_achievement_feed_queues_one_toast_per_id(g)
        test_toast_stays_under_score_panel(g)
        test_status_line_clear_of_score_panel(g)
        test_status_line_clear_of_gauge_and_health_panel(g)
        test_panels_draw_under_bars_and_chips(g)
        test_labels_stay_inside_window(g)
        test_hud_draws_for_many_frames_with_toasts_and_full_gauge(g)
    finally:
        g.close()
    test_toast_queue_is_fifo_one_at_a_time()
    test_toast_expires_at_2_5_seconds()
    test_toast_carries_leftover_time_into_next()
    test_toast_fade_curve()
    test_toast_queue_caps_pending_and_counts_drops()
    test_ultra_fraction_at_zero_half_and_full()
    test_current_skin_name_never_raises()
    test_achievement_names_resolve_when_present()
    print("\nALL WAVE2 HUDV2 TESTS PASSED")


if __name__ == "__main__":
    run_all()
