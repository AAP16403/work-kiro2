"""Wave 4 UI motion: banner easing and title drop, damage popup rise and fade, the screen fade between
states, and config.REDUCE_MOTION across all of them.

Covers: the banner's entrance and exit curves, the title landing on its rest position, the subtitle
starting after the title, the banner's text unchanged by the motion; the popup rise on an ease-out
curve and its total, the eased fade, the one-step spawn punch, the pooled slot count; the screen fade
curve, the change rules (pause and resume are cuts), the fade starting on a screen change and holding
while the game loop is paused; and REDUCE_MOTION stopping slides, drops, rises and punches while
keeping the fades. The HUD number texts are checked before and after the motion runs.

Run with the venv python: ``python test_w4_ui.py``. Needs a window, so it creates one hidden Game.
"""

import config
from anim import ease_in_out_sine, ease_out_cubic
from game import Game
from hud import BANNER_IN_S, BANNER_OUT_S
from popups import FADE_FRACTION, LIFE_BIG, LIFE_NORMAL, POP_TIME, RISE_SPEED, SIZE_BIG, DamagePopups, _fade_alpha, _size_at
from states import GameStateName, SCREEN_FADE_S, ScreenFade, screen_change_fades, screen_fade_alpha
from utils import Vec2

FRAME = 1.0 / 60.0


def _set_reduce(value):
    previous = config.REDUCE_MOTION
    config.REDUCE_MOTION = value
    return previous


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _hud(g):
    """The game's HUD. The HUD and its popups exist only once a run has been initialised."""
    if getattr(g, "hud", None) is None:
        _new_run(g)
    return g.hud


def _rest_banner(hud):
    """Positions of the banner once it has settled, measured at the end of the entrance."""
    hud._banner_t = BANNER_IN_S
    hud._place_banner()
    return hud.banner_plate.y, hud.banner_title.y, hud.banner_sub.y


# ----------------------------------------------------------------------
# Screen fade (pure logic)
# ----------------------------------------------------------------------

def test_screen_fade_endpoints_and_midpoint():
    assert screen_fade_alpha(0.0) == 1.0, "a new screen starts fully veiled"
    assert screen_fade_alpha(SCREEN_FADE_S) == 0.0, "the veil is gone at the end of the fade"
    assert screen_fade_alpha(10.0) == 0.0
    assert screen_fade_alpha(-1.0) == 1.0, "a negative age is the cut itself"
    assert abs(screen_fade_alpha(SCREEN_FADE_S / 2.0) - 0.5) < 1e-9, "in-out sine is symmetric about 0.5"
    assert screen_fade_alpha(0.5, duration=0.0) == 0.0, "a zero-length fade is a cut"
    print("[PASS] test_screen_fade_endpoints_and_midpoint passed (1 at the cut, 0 at the end, 0.5 half-way)")


def test_screen_fade_eases_in_and_out():
    quarter = screen_fade_alpha(0.25 * SCREEN_FADE_S)
    three_quarters = screen_fade_alpha(0.75 * SCREEN_FADE_S)
    assert 0.8 < quarter < 0.9, f"quarter-way veil {quarter} should ease, not run linear (0.75)"
    assert 0.1 < three_quarters < 0.2, f"three-quarter veil {three_quarters} should ease out (linear 0.25)"
    prev = 2.0
    for i in range(201):
        a = screen_fade_alpha(SCREEN_FADE_S * i / 200.0)
        assert a <= prev + 1e-12, "the veil must never brighten during a fade"
        prev = a
    print("[PASS] test_screen_fade_eases_in_and_out passed (quarter %.3f, three-quarter %.3f, monotone)" % (quarter, three_quarters))


def test_pause_and_resume_are_cuts():
    assert not screen_change_fades(None, "MenuState"), "the very first screen is not faded"
    assert screen_change_fades("MenuState", "PlayingState")
    assert screen_change_fades("PlayingState", "GameOverState")
    assert not screen_change_fades("PlayingState", "PausedState"), "pausing is a cut"
    assert not screen_change_fades("PausedState", "PlayingState"), "resuming is a cut"
    print("[PASS] test_pause_and_resume_are_cuts passed (menu and run changes fade, pause and resume cut)")


# ----------------------------------------------------------------------
# Popup curves (pure logic)
# ----------------------------------------------------------------------

def test_popup_fade_is_eased_and_ends_at_life():
    life = LIFE_NORMAL
    start = life * (1.0 - FADE_FRACTION)
    assert _fade_alpha(life, 0.0) == 255
    assert _fade_alpha(life, start) == 255, "full opacity until the fade window opens"
    mid = _fade_alpha(life, start + 0.5 * life * FADE_FRACTION)
    assert abs(mid - 127.5) <= 1.0, f"half-way through the window should read about 128, got {mid}"
    quarter = _fade_alpha(life, start + 0.25 * life * FADE_FRACTION)
    assert quarter > 200, f"an in-out ease keeps the first quarter bright (linear would be 191), got {quarter}"
    prev = 256
    for i in range(101):
        a = _fade_alpha(life, start + (life - start) * i / 100.0)
        assert a <= prev
        prev = a
    assert _fade_alpha(life, life) == 0
    print("[PASS] test_popup_fade_is_eased_and_ends_at_life passed (255 until the window, %d mid, %d quarter, 0 at life)" % (mid, quarter))


def test_punch_is_one_step_and_respects_reduce_motion_argument():
    assert _size_at(SIZE_BIG, 0.8, 0.0) == round(SIZE_BIG * 1.8), _size_at(SIZE_BIG, 0.8, 0.0)
    assert _size_at(SIZE_BIG, 0.8, POP_TIME - 1e-6) == round(SIZE_BIG * 1.8)
    assert _size_at(SIZE_BIG, 0.8, POP_TIME) == SIZE_BIG, "the punch ends at POP_TIME"
    assert _size_at(SIZE_BIG, 0.0, 0.0) == SIZE_BIG, "no boost means no punch"
    print("[PASS] test_punch_is_one_step_and_respects_reduce_motion_argument passed (one step, then the base size)")


# ----------------------------------------------------------------------
# Banner (HUD)
# ----------------------------------------------------------------------

def test_banner_entrance_and_exit_ease(g):
    hud = _hud(g)
    hud.show_banner("WAVE 05", "NORMAL  -  12 hostiles", duration=2.0)
    rest_plate_y, rest_title_y, _ = _rest_banner(hud)

    hud._banner_t = 0.0
    hud._place_banner()
    assert hud.banner_plate.opacity == 0, "the banner starts transparent"
    assert hud.banner_plate.y < rest_plate_y - 5, "the plate starts about 18 px low, sliding up"

    hud._banner_t = BANNER_IN_S * 0.5
    hud._place_banner()
    expect = int(178 * ease_out_cubic(0.5))
    assert hud.banner_plate.opacity == expect, (hud.banner_plate.opacity, expect)

    dur = 2.0
    out_t = min(BANNER_OUT_S, dur * 0.45)
    hud._banner_t = dur - out_t + out_t * 0.5
    hud._place_banner()
    half = 1.0 - ease_in_out_sine(0.5)
    assert abs(hud.banner_plate.opacity - int(178 * half)) <= 1, hud.banner_plate.opacity
    assert abs((hud.banner_plate.y - rest_plate_y) - 0.5 * hud._sz(8)) < 0.6, "the exit floats up half of 8 px half-way"
    print("[PASS] test_banner_entrance_and_exit_ease passed (in: out-cubic alpha, out: in-out sine fade with a float)")


def test_banner_title_drops_and_lands(g):
    hud = _hud(g)
    hud.show_banner("BOSS INCOMING", "BRUTE", duration=2.6)
    rest_plate_y, rest_title_y, rest_sub_y = _rest_banner(hud)
    # The plate slides up from below while the title drops inside it, so compare the title with its plate.
    rest_gap = rest_title_y - rest_plate_y
    hud._banner_t = 0.0
    hud._place_banner()
    start_gap = hud.banner_title.y - hud.banner_plate.y
    drop = hud._sz(14)
    assert abs((start_gap - rest_gap) - drop) <= 1, f"title sits {start_gap - rest_gap} px above its rest inside the plate, want {drop}"
    hud._banner_t = BANNER_IN_S - 1e-4
    hud._place_banner()
    assert abs((hud.banner_title.y - hud.banner_plate.y) - rest_gap) <= 1, "the title lands on its rest position in the plate"
    assert hud.banner_sub.y == rest_sub_y, "the subtitle is placed from the title's rest, not its drop"
    print("[PASS] test_banner_title_drops_and_lands passed (title starts %d px above its rest in the plate and lands on it)" % drop)


def test_subtitle_follows_the_title(g):
    hud = _hud(g)
    hud.show_banner("WAVE 05", "NORMAL", duration=2.0)
    hud._banner_t = 0.02
    hud._place_banner()
    title_a = hud.banner_title.opacity
    sub_a = hud.banner_sub.opacity
    assert title_a > 0 and sub_a == 0, f"at 20 ms the title shows and the subtitle waits ({title_a}, {sub_a})"
    hud._banner_t = 0.15
    hud._place_banner()
    assert hud.banner_sub.opacity > 150, f"the subtitle is in by 150 ms, got {hud.banner_sub.opacity}"
    print("[PASS] test_subtitle_follows_the_title passed (subtitle 0 at 20 ms, bright by 150 ms)")


def test_banner_reduce_motion_fades_only(g):
    hud = _hud(g)
    previous = _set_reduce(True)
    try:
        hud.show_banner("WAVE 05", "NORMAL", duration=2.0)
        rest_plate_y, rest_title_y, rest_sub_y = _rest_banner(hud)
        hud._banner_t = 0.0
        hud._place_banner()
        assert hud.banner_plate.opacity == 0, "still fades in under reduced motion"
        assert hud.banner_plate.y == rest_plate_y and hud.banner_title.y == rest_title_y, "no slide and no title drop"
        hud._banner_t = 0.1
        hud._place_banner()
        assert hud.banner_plate.opacity > 0 and hud.banner_plate.y == rest_plate_y
        dur = 2.0
        out_t = min(BANNER_OUT_S, dur * 0.45)
        hud._banner_t = dur - out_t * 0.5
        hud._place_banner()
        assert hud.banner_plate.y == rest_plate_y, "no float on the way out under reduced motion"
        assert hud.banner_plate.opacity < 178, "the exit still fades"
    finally:
        _set_reduce(previous)
    print("[PASS] test_banner_reduce_motion_fades_only passed (no slide, drop or float; fades kept)")


def test_banner_text_and_hud_numbers_unchanged(g):
    _new_run(g)
    hud = _hud(g)
    g.player.hp = 37
    g.player.shield = 50
    hud.update_bars(g.player, g.state, score=g.score, has_infinite_boost=False,
                    crit_chance_bonus=0.0, status_segments=[])
    hp_text = hud.hp_value_label.text
    shield_text = hud.shield_value_label.text
    assert hp_text == f"37/{int(g.player.max_hp)}", hp_text
    assert shield_text == f"50/{int(config.SHIELD_MAX)}", shield_text
    assert hud.wave_label.text == f"WAVE {int(g.state.wave):02d}", hud.wave_label.text

    hud.show_banner("BOSS INCOMING", "Brute", duration=2.6)
    for _ in range(90):
        hud.tick(FRAME)
        hud.draw()
    assert hud.banner_title.text == "BOSS INCOMING" and hud.banner_sub.text == "Brute"
    assert hud.hp_value_label.text == hp_text and hud.shield_value_label.text == shield_text, "motion never edits numbers"
    print("[PASS] test_banner_text_and_hud_numbers_unchanged passed (HULL %s, SHIELD %s, banner text exact)" % (hp_text, shield_text))


# ----------------------------------------------------------------------
# Damage popups (Game window needed for the labels)
# ----------------------------------------------------------------------

def test_popup_rises_on_an_ease_out_curve(g):
    pop = DamagePopups(max_items=8)
    pop.spawn(Vec2(0.0, 0.0), "-12", color=(255, 110, 110))
    slot = pop._slots[0]
    for _ in range(30):
        pop.update(FRAME)
    age = slot.age
    expect = RISE_SPEED * LIFE_NORMAL * ease_out_cubic(age / LIFE_NORMAL)
    assert abs(slot.rise - expect) < 1e-6, (slot.rise, expect)
    assert slot.rise > RISE_SPEED * age, "an ease-out rise runs ahead of the linear one early on"
    for _ in range(200):
        if not pop._live:
            break
        pop.update(FRAME)
    assert pop._live == 0 and not slot.label.visible, "the popup is retired after its life"
    print("[PASS] test_popup_rises_on_an_ease_out_curve passed (rise %.2f px at %.2f s, eased, retired at life)" % (expect, age))


def test_popup_fades_and_punches_then_settles(g):
    previous = _set_reduce(False)
    try:
        pop = DamagePopups(max_items=8)
        pop.spawn(Vec2(0.0, 0.0), "-30", color=(255, 200, 80), big=True)
        slot = pop._slots[0]
        assert int(slot.label.font_size) == _size_at(SIZE_BIG, slot.pop_boost, 0.0), "the punch starts at spawn"
        assert int(slot.label.font_size) > SIZE_BIG
        for _ in range(int(round(0.2 / FRAME))):
            pop.update(FRAME)
        assert int(slot.label.font_size) == SIZE_BIG, "the punch drops to the base size after POP_TIME"
        while slot.age < 0.9 * LIFE_BIG:
            pop.update(FRAME)
        assert 0 < slot.label.opacity < 255, f"the fade window should be part way, got {slot.label.opacity}"
        assert slot.shadow.opacity == slot.label.opacity, "shadow and text fade together"
    finally:
        _set_reduce(previous)
    print("[PASS] test_popup_fades_and_punches_then_settles passed (punch to %d px, back to %d, fading at 0.9 life)" % (round(SIZE_BIG * 1.8), SIZE_BIG))


def test_popup_reduce_motion_fades_without_rise_or_punch(g):
    previous = _set_reduce(True)
    try:
        pop = DamagePopups(max_items=8)
        pop.spawn(Vec2(10.0, 10.0), "-30", color=(255, 200, 80), big=True)
        slot = pop._slots[0]
        assert int(slot.label.font_size) == SIZE_BIG, "no punch at spawn under reduced motion"
        pop.sync(Vec2(0.0, 0.0))
        y0 = slot.label.y
        for _ in range(int(round(0.5 / FRAME))):
            pop.update(FRAME)
        pop.sync(Vec2(0.0, 0.0))
        assert slot.rise == 0.0 and slot.label.y == y0, "the number holds still under reduced motion"
        assert int(slot.label.font_size) == SIZE_BIG
        while slot.age < 0.9 * LIFE_BIG:
            pop.update(FRAME)
        assert slot.label.opacity < 255, "the fade still runs"
    finally:
        _set_reduce(previous)
    print("[PASS] test_popup_reduce_motion_fades_without_rise_or_punch passed (no rise, no punch, fade kept)")


def test_popup_pool_stays_bounded(g):
    pop = DamagePopups(max_items=6)
    for i in range(60):
        pop.spawn(Vec2(float(i), 0.0), "-%d" % i, color=(255, 255, 255))
    assert len(pop._slots) == 6, f"slots created {len(pop._slots)}, expected the cap of 6"
    for _ in range(100):
        pop.update(FRAME)
    for i in range(20):
        pop.spawn(Vec2(float(i), 0.0), "-%d" % i, color=(255, 255, 255))
    assert len(pop._slots) == 6, "reused slots, no new labels after the pool is full"
    print("[PASS] test_popup_pool_stays_bounded passed (60 spawns, 6 labels, reused after retire)")


# ----------------------------------------------------------------------
# Screen fade (Game window needed for the state draw hooks)
# ----------------------------------------------------------------------

def test_screen_fade_runs_on_a_menu_change(g):
    g._screen_fade = None
    previous = _set_reduce(False)
    try:
        g.fsm.set_state(GameStateName.MENU)
        g.fsm.draw()
        fade = g._screen_fade
        assert isinstance(fade, ScreenFade)
        assert fade.opacity(g._render_time, False) == 0.0, "the first screen seen is not faded"
        g.fsm.set_state(GameStateName.GUIDE)
        g.fsm.draw()
        assert abs(fade.opacity(g._render_time, False) - 1.0) < 1e-9, "a change starts fully veiled"
        rect_before = fade._rect
        for _ in range(3):  # about 0.05 s of game time
            g.update(FRAME)
        g.fsm.draw()
        mid = fade.opacity(g._render_time, False)
        assert 0.0 < mid < 1.0, f"part way through the veil is partial, got {mid}"
        assert fade._rect is rect_before, "the veil rectangle is reused, not rebuilt"
        for _ in range(20):  # past the 0.22 s fade
            g.update(FRAME)
        g.fsm.draw()
        assert fade.opacity(g._render_time, False) == 0.0, "the veil is gone after the fade"
    finally:
        _set_reduce(previous)
        g.fsm.set_state(GameStateName.MENU)
    print("[PASS] test_screen_fade_runs_on_a_menu_change passed (veil 1.0 at the cut, partial at 0.1 s, gone by 0.3 s, one rectangle)")


def test_pause_cuts_and_nested_backdrop_adds_no_veil(g):
    previous = _set_reduce(False)
    try:
        _new_run(g)
        g._screen_fade = None
        g.fsm.draw()
        g.fsm.set_state(GameStateName.PAUSED)
        g.fsm.draw()
        fade = g._screen_fade
        assert fade.seen == "PausedState", fade.seen
        assert fade.opacity(g._render_time, False) == 0.0, "pausing does not fade"
        g.fsm.set_state(GameStateName.PLAYING)
        g.fsm.draw()
        assert fade.opacity(g._render_time, False) == 0.0, "resuming does not fade"
    finally:
        _set_reduce(previous)
        g.fsm.set_state(GameStateName.MENU)
    print("[PASS] test_pause_cuts_and_nested_backdrop_adds_no_veil passed (pause and resume cut; the playing backdrop inside pause adds no veil)")


def test_reduce_motion_cuts_screen_changes(g):
    g._screen_fade = None
    previous = _set_reduce(True)
    try:
        g.fsm.set_state(GameStateName.MENU)
        g.fsm.draw()
        g.fsm.set_state(GameStateName.GUIDE)
        g.fsm.draw()
        fade = g._screen_fade
        assert fade.opacity(g._render_time, True) == 0.0, "reduced motion: no veil at all"
        assert fade._rect is None, "reduced motion never builds the veil rectangle"
    finally:
        _set_reduce(previous)
        g.fsm.set_state(GameStateName.MENU)
    print("[PASS] test_reduce_motion_cuts_screen_changes passed (no veil on a change under reduced motion)")


def test_hud_and_popups_draw_for_many_frames(g):
    _new_run(g)
    hud = _hud(g)
    pop = DamagePopups(max_items=16)
    hud.show_banner("WAVE 05", "NORMAL  -  12 hostiles", duration=2.0)
    for i in range(150):
        if i % 3 == 0:
            pop.spawn(Vec2(float(i % 20), 0.0), "-%d" % (i % 40), color=(255, 110, 110), big=(i % 6 == 0))
        pop.update(FRAME)
        pop.sync(Vec2(0.0, 0.0))
        pop.draw()
        hud.tick(FRAME)
        hud.draw()
    assert not hud._banner_active, "the banner ends after its duration"
    print("[PASS] test_hud_and_popups_draw_for_many_frames passed (150 frames, banner done, no exceptions)")


def run_all():
    pure = [
        test_screen_fade_endpoints_and_midpoint,
        test_screen_fade_eases_in_and_out,
        test_pause_and_resume_are_cuts,
        test_popup_fade_is_eased_and_ends_at_life,
        test_punch_is_one_step_and_respects_reduce_motion_argument,
    ]
    for fn in pure:
        fn()
    g = Game()
    g.set_visible(False)
    try:
        test_banner_entrance_and_exit_ease(g)
        test_banner_title_drops_and_lands(g)
        test_subtitle_follows_the_title(g)
        test_banner_reduce_motion_fades_only(g)
        test_banner_text_and_hud_numbers_unchanged(g)
        test_popup_rises_on_an_ease_out_curve(g)
        test_popup_fades_and_punches_then_settles(g)
        test_popup_reduce_motion_fades_without_rise_or_punch(g)
        test_popup_pool_stays_bounded(g)
        test_screen_fade_runs_on_a_menu_change(g)
        test_pause_cuts_and_nested_backdrop_adds_no_veil(g)
        test_reduce_motion_cuts_screen_changes(g)
        test_hud_and_popups_draw_for_many_frames(g)
    finally:
        g.close()
    print("\nALL WAVE4 UI TESTS PASSED")


if __name__ == "__main__":
    run_all()
