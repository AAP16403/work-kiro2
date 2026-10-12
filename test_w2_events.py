"""Wave 2 arena events: schedule, telegraphs, damage windows, shields, reduce motion (events.py, event_visuals.py).

Pure schedule tests run without a window. The rest use one hidden Game window, like the other swarm tests.
"""

import math

import config
from enemy import Enemy
from events import (
    EVENT_FLARE,
    EVENT_METEOR,
    EVENT_NEBULA,
    EVENTS,
    begin_wave_event,
    end_wave_event,
    event_banner_suffix,
    event_status_text,
    plan_event,
    schedule_for_wave,
    update_arena_event,
)
from game import Game
from states import GameStateName
from utils import Vec2

DT = 1.0 / 60.0
NONBOSS_WAVES = (6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 19)


def _event_run(g):
    """A playing run with no enemies and no automatic wave start, so each test drives the events itself."""
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    s = g.state
    s.enemies = []
    s.projectiles = []
    s.wave_active = False
    s.last_wave_clear = 1e9  # keeps the wave cooldown from starting a wave
    g.player.pos = Vec2(0.0, 0.0)
    g.player.invincibility_timer = 0.0
    g.player.shield = 0
    g.player.hp = 1000  # high enough that a multi-hit sweep never reaches game over and stops the event
    g._incoming_damage_mult = 1.0
    g._temp_incoming_damage_mult = 1.0
    return s


def _tick(g, frames=1):
    # Call update() directly: pyglet.clock.tick() would also fire the game's scheduled update.
    for _ in range(frames):
        g.dispatch_events()
        g.update(DT)


def _attach(s, ev):
    s.arena_event = ev
    if ev.beam is not None:
        s.lasers.append(ev.beam)
    return ev


def _find_seed_for(kind, wave):
    for seed in range(1, 5000):
        if schedule_for_wave(seed, wave) == kind:
            return seed
    raise AssertionError(f"no seed gives {kind} on wave {wave}")


def _set_config(name, value):
    """Set a config flag and return a function that restores the old state, including a missing flag."""
    had = hasattr(config, name)
    old = getattr(config, name, None)
    setattr(config, name, value)

    def restore():
        if had:
            setattr(config, name, old)
        else:
            delattr(config, name)
    return restore


def test_schedule_is_seeded_and_only_names_real_events(g):
    ids = [spec.id for spec in EVENTS]
    assert ids == [EVENT_METEOR, EVENT_FLARE, EVENT_NEBULA], f"unexpected event list {ids}"
    run_a = [schedule_for_wave(7, w) for w in range(1, 120)]
    run_b = [schedule_for_wave(7, w) for w in range(1, 120)]
    assert run_a == run_b, "the same seed must give the same schedule"
    other = [schedule_for_wave(8, w) for w in range(1, 120)]
    assert run_a != other, "a different seed should change the schedule somewhere"
    for kind in run_a:
        assert kind is None or kind in ids, f"schedule returned unknown id {kind!r}"
    a = plan_event(EVENT_METEOR, 7, 4)
    b = plan_event(EVENT_METEOR, 7, 4)
    assert [(i.pos.x, i.pos.y, i.mark_t) for i in a.impacts] == [(i.pos.x, i.pos.y, i.mark_t) for i in b.impacts], \
        "the same seed and wave must give the same meteor zones"
    print("[PASS] test_schedule_is_seeded_and_only_names_real_events passed (same seed same schedule, real ids only)")


def test_no_events_before_wave_four_or_on_boss_waves(g):
    for seed in range(300):
        for wave in (1, 2, 3):
            assert schedule_for_wave(seed, wave) is None, f"no event before wave 4 (seed {seed}, wave {wave})"
        for wave in range(5, 400, 5):
            assert schedule_for_wave(seed, wave) is None, f"no event on boss wave {wave} (seed {seed})"
    assert any(schedule_for_wave(seed, 4) is not None for seed in range(300)), "wave 4 must be able to get an event"
    print("[PASS] test_no_events_before_wave_four_or_on_boss_waves passed (waves 1-3 and every fifth wave stay clear)")


def test_about_one_in_three_eligible_waves(g):
    total = 0
    fired = 0
    per_kind = {EVENT_METEOR: 0, EVENT_FLARE: 0, EVENT_NEBULA: 0}
    for seed in range(2000):
        for wave in NONBOSS_WAVES:
            total += 1
            kind = schedule_for_wave(seed, wave)
            if kind is not None:
                fired += 1
                per_kind[kind] += 1
    ratio = fired / total
    assert 0.31 <= ratio <= 0.36, f"event rate {ratio:.3f} should be about 1/3"
    for kind, n in per_kind.items():
        share = n / max(1, fired)
        assert 0.27 <= share <= 0.40, f"{kind} share {share:.3f} should be about one third of events"
    print(f"[PASS] test_about_one_in_three_eligible_waves passed (measured {fired}/{total} = {ratio:.3f}; "
          f"meteor {per_kind[EVENT_METEOR]}, flare {per_kind[EVENT_FLARE]}, nebula {per_kind[EVENT_NEBULA]})")


def test_begin_wave_event_runs_one_event_and_leaves_main_rng_alone(g):
    s = _event_run(g)
    seed = _find_seed_for(EVENT_FLARE, 4)
    s.seed = seed
    s.wave = 4
    rng_before = s.rng.getstate()
    ev = begin_wave_event(s, g)
    assert ev is not None and ev.kind == EVENT_FLARE, "the chosen event must start"
    assert s.rng.getstate() == rng_before, "event scheduling must not advance the run's main RNG"
    begin_wave_event(s, g)  # a second start in the same wave replaces the first, never stacks
    beams = [lb for lb in s.lasers if getattr(lb, "owner", "") == "event"]
    assert len(beams) == 1, f"one flare beam at a time, got {len(beams)}"
    assert s.arena_event is not None and s.arena_event.kind == EVENT_FLARE
    end_wave_event(s, g)
    assert s.arena_event is None and not [lb for lb in s.lasers if getattr(lb, "owner", "") == "event"], \
        "ending the wave must remove the beam"
    s.wave = 5
    assert begin_wave_event(s, g) is None, "boss waves never start an event"
    print("[PASS] test_begin_wave_event_runs_one_event_and_leaves_main_rng_alone passed (one event, main RNG untouched, boss wave clear)")


def test_meteor_hits_once_after_warning_inside_zone(g):
    s = _event_run(g)
    ev = plan_event(EVENT_METEOR, 11, 4)
    ev.impacts[0].pos = Vec2(0.0, 0.0)  # the player stands in this zone
    ev.impacts[1].pos = Vec2(-240.0, 150.0)  # far from the player
    ev.impacts[2].pos = Vec2(200.0, -200.0)
    _attach(s, ev)
    warn = float(config.EVENT_METEOR_WARN)
    hits = []
    last_hp = g.player.hp
    for _ in range(int((ev.total + 0.5) / DT)):
        _tick(g)
        if g.player.hp != last_hp:
            hits.append((ev.t, last_hp - g.player.hp))
            last_hp = g.player.hp
    assert len(hits) == 1, f"one zone under the player must hit exactly once, got {hits}"
    t_hit, dmg = hits[0]
    assert dmg == int(config.EVENT_METEOR_DAMAGE), f"zone damage should be {config.EVENT_METEOR_DAMAGE}, got {dmg}"
    assert warn - 2 * DT <= t_hit <= warn + 0.25, f"zone must hit after its {warn}s warning, hit at {t_hit:.3f}s"
    assert s.arena_event is None, "the event must end once all zones have passed"
    print(f"[PASS] test_meteor_hits_once_after_warning_inside_zone passed (hit {dmg} at {t_hit:.2f}s, 1.5s warning)")


def test_meteor_zone_outside_its_radius_is_safe(g):
    s = _event_run(g)
    g.player.pos = Vec2(80.0, 0.0)
    ev = plan_event(EVENT_METEOR, 11, 4)
    ev.impacts[0].pos = Vec2(0.0, 0.0)
    ev.impacts[1].pos = Vec2(-240.0, 150.0)
    ev.impacts[2].pos = Vec2(200.0, -200.0)
    _attach(s, ev)
    reach = float(config.EVENT_METEOR_RADIUS) + float(g._player_radius())
    assert 80.0 > reach, "the test position must sit outside the impact radius"
    hp0 = g.player.hp
    for _ in range(int((ev.total + 0.5) / DT)):
        _tick(g)
    assert g.player.hp == hp0, "a zone the player is outside of must not damage"
    print("[PASS] test_meteor_zone_outside_its_radius_is_safe passed (no damage 80 units from the zone centre)")


def test_flare_beam_hits_on_its_path_after_warning(g):
    s = _event_run(g)
    ev = plan_event(EVENT_FLARE, 5, 4)
    _attach(s, ev)
    mid = ev.angle_mid
    g.player.pos = Vec2(math.cos(mid) * 150.0, math.sin(mid) * 150.0)  # the beam passes the player at mid-sweep
    warn = float(config.EVENT_FLARE_WARN)
    sweep = float(config.EVENT_FLARE_SWEEP)
    hits = []
    last_hp = g.player.hp
    for _ in range(int((ev.total + 0.5) / DT)):
        _tick(g)
        if g.player.hp != last_hp:
            hits.append(ev.t)
            last_hp = g.player.hp
    assert len(hits) == 1, f"a single pass of the beam over the player must hit once, got {len(hits)}"
    assert hits[0] >= warn - 2 * DT, f"no beam damage before the warning ends ({hits[0]:.3f}s)"
    expected = warn + sweep * 0.5
    assert abs(hits[0] - expected) <= 0.2, f"beam should cross the player near {expected:.2f}s, hit at {hits[0]:.2f}s"
    print(f"[PASS] test_flare_beam_hits_on_its_path_after_warning passed (one hit at {hits[0]:.2f}s, beam crosses at {expected:.2f}s)")


def test_flare_tick_limits_repeat_hits(g):
    s = _event_run(g)
    ev = plan_event(EVENT_FLARE, 5, 4)
    _attach(s, ev)
    g.player.pos = Vec2(0.0, 0.0)  # the beam starts at the arena centre, so it always touches the player
    warn = float(config.EVENT_FLARE_WARN)
    hit_times = []
    last_hp = g.player.hp
    for _ in range(int((ev.total + 0.5) / DT)):
        _tick(g)
        if g.player.hp != last_hp:
            hit_times.append(ev.t)
            last_hp = g.player.hp
    assert hit_times, "a player on the beam must be hit"
    assert hit_times[0] >= warn - 2 * DT, "the first beam hit must wait for the warning"
    gaps = [b - a for a, b in zip(hit_times, hit_times[1:])]
    assert all(gap >= float(config.EVENT_FLARE_TICK) - 2 * DT for gap in gaps), f"hits closer than the tick: {gaps}"
    expected_max = int(float(config.EVENT_FLARE_SWEEP) / float(config.EVENT_FLARE_TICK)) + 1
    assert len(hit_times) <= expected_max, f"{len(hit_times)} hits in one sweep, expected at most {expected_max}"
    print(f"[PASS] test_flare_tick_limits_repeat_hits passed ({len(hit_times)} hits, gaps >= {config.EVENT_FLARE_TICK}s)")


def test_nebula_shield_entry_exit_and_release(g):
    s = _event_run(g)
    ev = plan_event(EVENT_NEBULA, 3, 4)
    ev.center = Vec2(0.0, 0.0)
    _attach(s, ev)
    shield = int(config.EVENT_NEBULA_SHIELD)
    warn = float(config.EVENT_NEBULA_WARN)
    inside = Enemy(pos=Vec2(30.0, 0.0), hp=50, speed=0.0, behavior="chaser", seed=1.0)
    spare = Enemy(pos=Vec2(20.0, 10.0), hp=50, speed=0.0, behavior="chaser", seed=1.0)
    spare.shield = 10  # an existing shield must survive the cloud
    outside = Enemy(pos=Vec2(300.0, 0.0), hp=50, speed=0.0, behavior="chaser", seed=1.0)
    s.enemies = [inside, spare, outside]
    while ev.t < warn - DT:
        update_arena_event(s, g, DT)
    assert inside.shield == 0 and spare.shield == 10, "the cloud must not shield during its warning"
    while ev.t < warn + 0.1:
        update_arena_event(s, g, DT)
    assert inside.shield == shield, f"enemy inside the cloud should gain {shield}, has {inside.shield}"
    assert spare.shield == shield, f"existing shield below the cloud value should top up to {shield}, has {spare.shield}"
    assert outside.shield == 0, "enemy outside the cloud gets no shield"
    inside.pos = Vec2(300.0, 0.0)  # leaves the cloud
    update_arena_event(s, g, DT)
    assert inside.shield == 0 and getattr(inside, "_nebula_base", None) is None, "leaving the cloud removes the grant"
    spare.shield -= 5  # a bullet is absorbed while inside the cloud
    while s.arena_event is not None:
        update_arena_event(s, g, DT)
    assert spare.shield == 10, f"at the end the spare enemy keeps its own shield (10), got {spare.shield}"
    assert inside.shield == 0 and outside.shield == 0, "no shield is left after the cloud ends"
    print("[PASS] test_nebula_shield_entry_exit_and_release passed (grant on entry, removed on exit and at the end, base kept)")


def test_reduce_motion_stops_sweep_and_pulse_but_keeps_damage(g):
    restore = _set_config("REDUCE_MOTION", True)
    try:
        s = _event_run(g)
        ev = plan_event(EVENT_FLARE, 5, 4)
        _attach(s, ev)
        g.player.pos = Vec2(math.cos(ev.angle_mid) * 150.0, math.sin(ev.angle_mid) * 150.0)
        warn = float(config.EVENT_FLARE_WARN)
        ends = []
        hits = 0
        last_hp = g.player.hp
        for _ in range(int((ev.total + 0.5) / DT)):
            _tick(g)
            if ev.t > warn + 0.1 and s.arena_event is not None:
                ends.append((ev.beam.end.x, ev.beam.end.y))
            if g.player.hp != last_hp:
                hits += 1
                last_hp = g.player.hp
        assert len(ends) > 10, "the test must sample the sweep"
        assert all(abs(x - ends[0][0]) < 1e-9 and abs(y - ends[0][1]) < 1e-9 for x, y in ends), \
            "with Reduce Motion the beam must not rotate"
        assert hits >= 1, "with Reduce Motion the beam still deals damage to a player on its line"

        m = _event_run(g)
        mev = plan_event(EVENT_METEOR, 11, 4)
        mev.impacts[0].pos = Vec2(0.0, 0.0)
        mev.impacts[1].pos = Vec2(-240.0, 150.0)
        mev.impacts[2].pos = Vec2(200.0, -200.0)
        _attach(m, mev)
        _tick(g, 3)
        assert any(getattr(tr, "kind", "") == "meteor" for tr in m.traps), "meteor warnings still appear"
        g.player.pos = Vec2(0.0, 0.0)
        hp0 = g.player.hp
        for _ in range(int((mev.total + 0.5) / DT)):
            _tick(g)
        assert g.player.hp == hp0 - int(config.EVENT_METEOR_DAMAGE), "meteor damage still lands with Reduce Motion"

        n = _event_run(g)
        nev = plan_event(EVENT_NEBULA, 3, 4)
        nev.center = Vec2(0.0, 0.0)
        _attach(n, nev)
        n.enemies = []
        nev.t = float(config.EVENT_NEBULA_WARN) + 0.2
        g.visuals.sync_arena_event(nev, Vec2(0.0, 0.0))
        op_a = g.visuals._arena_fx._handles[id(nev)].fill.opacity
        nev.t = float(config.EVENT_NEBULA_WARN) + 1.1
        g.visuals.sync_arena_event(nev, Vec2(0.0, 0.0))
        op_b = g.visuals._arena_fx._handles[id(nev)].fill.opacity
        assert op_a == op_b, f"the cloud pulse must stop with Reduce Motion ({op_a} vs {op_b})"
        g.visuals.drop_arena_event(nev)
    finally:
        restore()

    s2 = _event_run(g)
    nev2 = plan_event(EVENT_NEBULA, 3, 4)
    _attach(s2, nev2)
    nev2.t = float(config.EVENT_NEBULA_WARN) + 0.2
    g.visuals.sync_arena_event(nev2, Vec2(0.0, 0.0))
    op_c = g.visuals._arena_fx._handles[id(nev2)].fill.opacity
    nev2.t = float(config.EVENT_NEBULA_WARN) + 1.1
    g.visuals.sync_arena_event(nev2, Vec2(0.0, 0.0))
    op_d = g.visuals._arena_fx._handles[id(nev2)].fill.opacity
    assert op_c != op_d, "without Reduce Motion the cloud pulses"
    g.visuals.drop_arena_event(nev2)
    print("[PASS] test_reduce_motion_stops_sweep_and_pulse_but_keeps_damage passed "
          "(beam fixed, meteor warnings and damage kept, cloud pulse stopped)")


def test_fx_handles_built_and_dropped(g):
    s = _event_run(g)
    meteor = _attach(s, plan_event(EVENT_METEOR, 11, 4))
    _tick(g, 2)
    assert any(imp.trap is not None for imp in meteor.impacts), "meteor zones are created at their mark"
    g.on_draw()
    assert any(id(imp.trap) in g.visuals._trap_handles for imp in meteor.impacts if imp.trap is not None), \
        "meteor zones draw through the trap visuals"
    end_wave_event(s, g)
    assert not g.visuals._trap_handles, "ending the event must drop the zone visuals"
    assert not s.traps, "ending the event must remove its zones"

    flare = _attach(s, plan_event(EVENT_FLARE, 5, 4))
    _tick(g, 2)
    g.on_draw()
    assert id(flare) in g.visuals._arena_fx._handles, "the flare sector is drawn"
    end_wave_event(s, g)
    assert id(flare) not in g.visuals._arena_fx._handles and not s.lasers, "ending the event drops the sector and beam"

    cloud = _attach(s, plan_event(EVENT_NEBULA, 3, 4))
    _tick(g, 2)
    g.on_draw()
    assert id(cloud) in g.visuals._arena_fx._handles, "the nebula cloud is drawn"
    end_wave_event(s, g)
    assert id(cloud) not in g.visuals._arena_fx._handles, "ending the event drops the cloud"
    print("[PASS] test_fx_handles_built_and_dropped passed (every event draws through the draw path and cleans up)")


def test_objects_are_reused_frame_to_frame(g):
    s = _event_run(g)
    ev = _attach(s, plan_event(EVENT_FLARE, 5, 4))
    beam = ev.beam
    start_obj, end_obj = beam.start, beam.end
    _tick(g, 3)
    assert ev.beam is beam and beam.start is start_obj and beam.end is end_obj, "the beam is updated in place"
    assert len(s.lasers) == 1, "the beam is not re-added every frame"
    meteor = _attach(s, plan_event(EVENT_METEOR, 11, 4))
    _tick(g, 2)
    traps_now = [imp.trap for imp in meteor.impacts if imp.trap is not None]
    _tick(g, 3)
    assert [imp.trap for imp in meteor.impacts if imp.trap is not None] == traps_now, \
        "meteor zones are created once and then ticked by states.py"
    end_wave_event(s, g)
    print("[PASS] test_objects_are_reused_frame_to_frame passed (beam endpoints and zones kept, nothing re-added per frame)")


def test_banner_and_status_text(g):
    s = _event_run(g)
    assert event_banner_suffix(s) == "" and event_status_text(s) == "", "no event, no text"
    _attach(s, plan_event(EVENT_FLARE, 5, 4))
    assert event_banner_suffix(s) == "  -  SOLAR FLARE", f"banner suffix was {event_banner_suffix(s)!r}"
    assert event_status_text(s).startswith("SOLAR FLARE "), f"status text was {event_status_text(s)!r}"
    end_wave_event(s, g)
    print("[PASS] test_banner_and_status_text passed (wave banner names the event, status line shows it while it runs)")


def test_wave_clear_removes_event_hazards_and_shields(g):
    s = _event_run(g)
    meteor = _attach(s, plan_event(EVENT_METEOR, 11, 4))
    _tick(g, 2)
    assert any(imp.trap is not None for imp in meteor.impacts)
    end_wave_event(s, g)
    assert s.arena_event is None and not s.traps, "wave clear removes unfinished zones"

    s2 = _event_run(g)
    cloud = plan_event(EVENT_NEBULA, 3, 4)
    cloud.center = Vec2(0.0, 0.0)
    _attach(s2, cloud)
    e = Enemy(pos=Vec2(10.0, 0.0), hp=50, speed=0.0, behavior="chaser", seed=1.0)
    s2.enemies = [e]
    cloud.t = float(config.EVENT_NEBULA_WARN) + 0.1
    update_arena_event(s2, g, DT)
    assert e.shield == int(config.EVENT_NEBULA_SHIELD), "the cloud shields the enemy"
    end_wave_event(s2, g)
    assert e.shield == 0 and getattr(e, "_nebula_base", None) is None, "wave clear releases the cloud shield"
    print("[PASS] test_wave_clear_removes_event_hazards_and_shields passed (zones, beam and cloud shields cleared)")


def test_wave_start_and_clear_hooks_run_in_real_update(g):
    """spawn_wave -> begin_wave_event and wave clear -> end_wave_event through the real PlayingState.update."""
    s = _event_run(g)
    wave4_seed = _find_seed_for(EVENT_NEBULA, 4)
    s.seed = wave4_seed
    s.wave = 4
    s.wave_active = False
    s.last_wave_clear = -100.0  # the cooldown has passed, so the next tick starts the wave
    _tick(g)
    assert s.wave_active, "the tick must start wave 4"
    assert s.arena_event is not None and s.arena_event.kind == EVENT_NEBULA, \
        f"the wave start must roll the seeded event, got {s.arena_event}"
    s.enemies = []  # clear the wave: the event must end with it
    _tick(g)
    assert s.wave == 5 and s.arena_event is None, "wave clear must end the event before the next wave"

    s.seed = _find_seed_for(EVENT_METEOR, 4)
    s.wave = 5  # a boss wave: the spawn hook must not start an event
    s.wave_active = False
    s.last_wave_clear = -100.0
    _tick(g)
    assert s.wave_active and s.arena_event is None, "boss waves never start an event"
    s.enemies = []
    _tick(g)
    print("[PASS] test_wave_start_and_clear_hooks_run_in_real_update passed (start rolls the seeded event, clear ends it, boss waves stay clear)")


def test_event_run_end_to_end_draw(g):
    """A full event in the real draw path: every warning renders without error."""
    s = _event_run(g)
    for kind in (EVENT_METEOR, EVENT_FLARE, EVENT_NEBULA):
        ev = _attach(s, plan_event(kind, 21, 4))
        drawn = 0
        for frame in range(int((ev.total + 0.5) / DT)):
            _tick(g)
            if frame % 6 == 0:
                g.on_draw()  # every sixth frame: the warning and the active phase both get drawn
                drawn += 1
            if s.arena_event is None:
                break
        assert s.arena_event is None, f"{kind} must finish within its total time"
        assert drawn > 0, f"{kind} must reach the draw path"
        end_wave_event(s, g)
    print("[PASS] test_event_run_end_to_end_draw passed (all three events ran to completion through update and draw)")


def test_float_helpers_match_utils(g):
    """The per-frame float helpers must agree with the utils functions they replace on the hot path."""
    import random

    from event_visuals import _sx, _sy
    from events import segment_dist_sq
    from utils import point_segment_distance_sq, to_iso

    rng = random.Random(4)
    for _ in range(500):
        p = Vec2(rng.uniform(-400.0, 400.0), rng.uniform(-400.0, 400.0))
        a = Vec2(rng.uniform(-400.0, 400.0), rng.uniform(-400.0, 400.0))
        b = Vec2(rng.uniform(-400.0, 400.0), rng.uniform(-400.0, 400.0))
        ref = point_segment_distance_sq(p, a, b)
        got = segment_dist_sq(p.x, p.y, a.x, a.y, b.x, b.y)
        assert abs(ref - got) <= 1e-6 * max(1.0, ref), f"segment distance mismatch: {ref} vs {got}"
    degenerate = segment_dist_sq(3.0, 4.0, 1.0, 1.0, 1.0, 1.0)
    assert abs(degenerate - (4.0 + 9.0)) < 1e-9, "a zero-length segment is a point"
    shake = Vec2(3.5, -2.0)
    for _ in range(100):
        w = Vec2(rng.uniform(-400.0, 400.0), rng.uniform(-400.0, 400.0))
        tx, ty = to_iso(w, shake)
        assert abs(tx - _sx(w.x, w.y, shake)) < 1e-9 and abs(ty - _sy(w.x, w.y, shake)) < 1e-9, "projection mismatch"
    print("[PASS] test_float_helpers_match_utils passed (segment distance and iso projection match utils on 500 random cases)")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_float_helpers_match_utils(g)
        test_schedule_is_seeded_and_only_names_real_events(g)
        test_no_events_before_wave_four_or_on_boss_waves(g)
        test_about_one_in_three_eligible_waves(g)
        test_begin_wave_event_runs_one_event_and_leaves_main_rng_alone(g)
        test_meteor_hits_once_after_warning_inside_zone(g)
        test_meteor_zone_outside_its_radius_is_safe(g)
        test_flare_beam_hits_on_its_path_after_warning(g)
        test_flare_tick_limits_repeat_hits(g)
        test_nebula_shield_entry_exit_and_release(g)
        test_reduce_motion_stops_sweep_and_pulse_but_keeps_damage(g)
        test_fx_handles_built_and_dropped(g)
        test_objects_are_reused_frame_to_frame(g)
        test_banner_and_status_text(g)
        test_wave_clear_removes_event_hazards_and_shields(g)
        test_wave_start_and_clear_hooks_run_in_real_update(g)
        test_event_run_end_to_end_draw(g)
    finally:
        g.close()
    print("\nALL WAVE 2 ARENA EVENT TESTS PASSED")


if __name__ == "__main__":
    run_all()
