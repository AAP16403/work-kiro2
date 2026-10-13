"""Wave 8 Afterburn tests: a dash leaves a short burning strip on the ground.

Covers: the config block; the drop cadence (every 0.05 s while dashing, the first drop at once, none while not
dashing); the 12-segment cap with the oldest reused; expiry at 2.5 s; the damage cadence (4 per 0.5 s, each enemy on
its own timer, a re-entry after a gap ticks at once); the 26 px reach edge; boss halving; the kill going through
the normal kill path and scoring; nothing happening with ENABLE_AFTERBURN False; the trail colour from the run
skin (warm orange for the default skin); REDUCE_MOTION stopping the flicker while the fade stays; the disc matching
utils.to_iso; steady frames building no objects; the frame cost; and in play, a scripted dash across a line of
chasers that reports hits, kills and the segment count.

Plain functions that print [PASS] lines, run from run_all().
"""

import math
import os
import random
import tempfile
import time
import tracemalloc

import pyglet

import config
import progress
import score
from afterburn import AfterburnTrail, damage_for
from afterburn_art import AfterburnPool, scorch_rgb
from enemy import Enemy
from game import Game
from skin_apply import RunSkin, complete_palette, default_run_skin
from states import GameStateName
from utils import Vec2, to_iso

FRAME = 1.0 / 60.0
ROOT = os.path.dirname(os.path.abspath(__file__))
ORANGE = (255, 140, 40)
_WINDOW = None


def _batch():
    """A batch on a hidden window, so the pool's pyglet shapes have a GL context."""
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = pyglet.window.Window(width=64, height=64, visible=False)
    return pyglet.graphics.Batch()


class _cfg:
    """Set config values for a with-block, then put them back."""

    def __init__(self, **kw):
        self.kw = kw
        self.saved = {}

    def __enter__(self):
        for k, v in self.kw.items():
            self.saved[k] = getattr(config, k)
            setattr(config, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.saved.items():
            setattr(config, k, v)
        return False


def _enemy(x, y, hp=100, behavior="chaser"):
    return Enemy(pos=Vec2(float(x), float(y)), hp=int(hp), speed=0.0, behavior=behavior)


def _deal_log(clock=None):
    """A deal stand-in: records (id, amount, clock time) and applies the damage. Returns True on a kill."""
    log = []

    def deal(e, amount):
        log.append((id(e), amount, None if clock is None else round(clock[0], 6)))
        e.hp -= amount
        return e.hp <= 0

    return log, deal


def _new_run(g):
    """A fresh run in PLAYING with no auto-fire and no wave spawns, so each test controls the enemies."""
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    g.auto_shoot = False
    g.state.wave_active = True
    g.state.obstacles = []
    g.player.pos = Vec2(0.0, 0.0)
    return g.state


def _steps(g, n):
    for _ in range(n):
        g._fixed_step()


def test_config_block():
    assert config.ENABLE_AFTERBURN is True
    assert config.AFTERBURN_DROP_SECONDS == 0.05, config.AFTERBURN_DROP_SECONDS
    assert config.AFTERBURN_LIFE_SECONDS == 2.5, config.AFTERBURN_LIFE_SECONDS
    assert config.AFTERBURN_MAX_SEGMENTS == 12, config.AFTERBURN_MAX_SEGMENTS
    assert config.AFTERBURN_HIT_RADIUS == 26.0, config.AFTERBURN_HIT_RADIUS
    assert config.AFTERBURN_TICK_SECONDS == 0.5, config.AFTERBURN_TICK_SECONDS
    assert config.AFTERBURN_DAMAGE == 4 and config.AFTERBURN_BOSS_MULT == 0.5
    assert tuple(config.AFTERBURN_COLOR) == ORANGE, config.AFTERBURN_COLOR
    assert 0 < config.AFTERBURN_LAYER_ORDER < 15000 and config.AFTERBURN_LAYER_ORDER < 60, \
        "above the floor (0), below the particles (15000) and the entity depth buckets (60+)"
    with open(os.path.join(ROOT, "config.py"), encoding="utf-8") as fh:
        src = fh.read()
    head = src.rfind("# wave8 afterburn")
    assert head > 0, "the block is headed '# wave8 afterburn'"
    body = [ln for ln in src[head:].splitlines()[1:] if ln.strip()]
    assert all(ln.startswith(("ENABLE_AFTERBURN", "AFTERBURN_")) for ln in body), body
    print("[PASS] test_config_block passed (0.05 s drops, 2.5 s life, 12 segments, 26 px, 4 per 0.5 s, orange, block at the end)")


def test_drops_every_fifty_ms_while_dashing():
    for dash_frames, want in ((12, 4), (15, 5), (24, 8)):  # 0.2 s, 0.25 s, 0.4 s
        trail = AfterburnTrail()
        drops = []
        for k in range(dash_frames):
            t = 1.0 + k * FRAME
            if trail.update_dash(True, 800.0 * (k + 1) * FRAME, 0.0, t):
                drops.append(t)
        assert len(drops) == want, (dash_frames, drops)
        gaps = [b - a for a, b in zip(drops, drops[1:])]
        assert all(abs(g - 0.05) < 1e-6 for g in gaps), gaps
        assert abs(drops[0] - 1.0) < 1e-9, "the first drop is on the dash's first frame"
        assert trail.update_dash(False, 0.0, 0.0, 1.0 + dash_frames * FRAME) is False
    trail = AfterburnTrail()
    assert trail.update_dash(False, 5.0, 5.0, 0.0) is False and trail.drops == 0, "no dash, no drops"
    print("[PASS] test_drops_every_fifty_ms_while_dashing passed (0.2 s -> 4, 0.25 s -> 5, 0.4 s -> 8; gaps 0.05 s)")


def test_twelve_segment_cap_reuses_the_oldest():
    trail = AfterburnTrail()
    assert trail.size == 12 == int(config.AFTERBURN_MAX_SEGMENTS)
    for i in range(12):
        trail.spawn(10.0 * i, 0.0, 0.05 * i)
    assert trail.live_count == 12
    oldest = trail.segments[0]
    assert oldest.t0 == 0.0
    trail.spawn(500.0, 0.0, 0.6)
    assert trail.live_count == 12, trail.live_count
    assert oldest.x == 500.0 and abs(oldest.t0 - 0.6) < 1e-9, "the oldest live segment was reused"
    for i in range(30):
        trail.spawn(700.0 + i, 0.0, 0.7 + 0.05 * i)
    assert trail.live_count == 12 and trail.drops == 43, (trail.live_count, trail.drops)
    t0s = sorted(seg.t0 for seg in trail.segments)
    assert abs(t0s[0] - (0.7 + 0.05 * 18)) < 1e-9 and abs(t0s[-1] - (0.7 + 0.05 * 29)) < 1e-9, t0s
    # A free slot is used before a live one is reused.
    trail.expire(100.0)
    assert trail.live_count == 0
    trail.spawn(1.0, 1.0, 100.0)
    assert trail.live_count == 1
    print("[PASS] test_twelve_segment_cap_reuses_the_oldest passed (13th drop reuses the oldest; 43 drops keep 12 live)")


def test_segment_expires_at_two_and_a_half_seconds():
    trail = AfterburnTrail()
    trail.spawn(0.0, 0.0, 1.0)
    trail.expire(3.4999)
    assert trail.live_count == 1, "still burning just before 2.5 s"
    trail.expire(3.5)
    assert trail.live_count == 0, "gone at 2.5 s of age"
    trail2 = AfterburnTrail()
    trail2.spawn(0.0, 0.0, 1.0)
    e = _enemy(5.0, 0.0, hp=1000)
    _, deal = _deal_log()
    assert trail2.tick([e], 3.49, deal) == 1, "a tick just before expiry still lands"
    assert trail2.tick([e], 3.5, deal) == 0, "no tick once the segment has expired"
    print("[PASS] test_segment_expires_at_two_and_a_half_seconds passed (live at 3.4999, gone at 3.5 for spawn 1.0)")


def test_damage_is_four_every_half_second():
    trail = AfterburnTrail()
    trail.spawn(0.0, 0.0, 0.0)
    e = _enemy(10.0, 0.0, hp=100)
    clock = [0.0]
    log, deal = _deal_log(clock)
    ticks = 0
    for k in range(120):  # 0 to 1.983 s: a 2 s window
        clock[0] = k / 60.0
        ticks += trail.tick([e], clock[0], deal)
    times = [t for _, _, t in log]
    assert times == [0.0, 0.5, 1.0, 1.5], times
    assert all(amount == 4 for _, amount, _ in log), log
    assert ticks == 4 and e.hp == 100 - 16, (ticks, e.hp)
    assert trail.hits == 4 and trail.kills == 0
    print("[PASS] test_damage_is_four_every_half_second passed (ticks at 0, 0.5, 1.0, 1.5 s: 16 damage in 2 s)")


def test_each_enemy_keeps_its_own_timer():
    trail = AfterburnTrail()
    trail.spawn(0.0, 0.0, 0.0)
    a = _enemy(10.0, 0.0, hp=1000)
    b = _enemy(-300.0, 0.0, hp=1000)  # out of reach until 0.3 s
    clock = [0.0]
    log, deal = _deal_log(clock)
    for k in range(120):
        clock[0] = k / 60.0
        if clock[0] >= 0.3 and b.pos.x < 0.0:
            b.pos = Vec2(10.0, 5.0)  # steps into reach at 0.3 s
        trail.tick([a, b], clock[0], deal)
    a_times = [t for i, _, t in log if i == id(a)]
    b_times = [t for i, _, t in log if i == id(b)]
    assert a_times == [0.0, 0.5, 1.0, 1.5], a_times
    assert b_times == [0.3, 0.8, 1.3, 1.8], "b's own timer starts when it enters reach, not when a's does"
    print("[PASS] test_each_enemy_keeps_its_own_timer passed (a: 0, 0.5, 1.0, 1.5; b enters at 0.3: 0.3, 0.8, 1.3, 1.8)")


def test_re_entry_after_a_gap_ticks_at_once():
    trail = AfterburnTrail()
    trail.spawn(0.0, 0.0, 0.0)
    e = _enemy(10.0, 0.0, hp=1000)
    clock = [0.0]
    log, deal = _deal_log(clock)
    for k in range(108):  # to 1.8 s
        clock[0] = k / 60.0
        in_reach = not (0.1 <= clock[0] < 1.2)
        e.pos = Vec2(10.0, 0.0) if in_reach else Vec2(400.0, 0.0)
        trail.tick([e], clock[0], deal)
    times = [t for _, _, t in log]
    assert times == [0.0, 1.2, 1.7], times
    print("[PASS] test_re_entry_after_a_gap_ticks_at_once passed (out 0.1 to 1.2 s; back at 1.2 s, then 1.7 s)")


def test_reach_is_the_twenty_six_px_edge():
    trail = AfterburnTrail()
    trail.spawn(0.0, 0.0, 0.0)
    on = _enemy(26.0, 0.0, hp=100)
    off = _enemy(0.0, 26.5, hp=100)
    _, deal = _deal_log()
    assert trail.tick([on, off], 0.0, deal) == 1
    assert on.hp == 96 and off.hp == 100, (on.hp, off.hp)
    print("[PASS] test_reach_is_the_twenty_six_px_edge passed (26.0 px burns, 26.5 px does not)")


def test_boss_takes_half():
    assert damage_for(_enemy(0.0, 0.0)) == 4
    boss = _enemy(10.0, 0.0, hp=100, behavior="boss_brute")
    assert damage_for(boss) == 2, damage_for(boss)
    trail = AfterburnTrail()
    trail.spawn(0.0, 0.0, 0.0)
    clock = [0.0]
    log, deal = _deal_log(clock)
    for k in range(120):
        clock[0] = k / 60.0
        trail.tick([boss], clock[0], deal)
    amounts = [amount for _, amount, _ in log]
    assert amounts == [2, 2, 2, 2] and boss.hp == 92, (amounts, boss.hp)
    print("[PASS] test_boss_takes_half passed (boss 2 per tick, 8 in 2 s; a normal enemy 4 per tick)")


def test_nothing_happens_when_disabled():
    batch = _batch()
    with _cfg(ENABLE_AFTERBURN=False):
        trail = AfterburnTrail()
        assert trail.spawn(0.0, 0.0, 0.0) is None
        for k in range(60):
            assert trail.update_dash(True, float(k), 0.0, k * FRAME) is False
        assert trail.drops == 0 and trail.live_count == 0
        seg = trail.segments[0]
        seg.x, seg.y, seg.t0, seg.live = 0.0, 0.0, 0.0, True  # even a live segment does nothing
        e = _enemy(5.0, 0.0, hp=100)
        log, deal = _deal_log()
        assert trail.tick([e], 0.0, deal) == 0 and log == [] and e.hp == 100
        pool = AfterburnPool(batch, colour=ORANGE)
        pool.update(0.1, trail, 0.0, 0.0)
        assert pool.shown_count == 0, "nothing is drawn"
    assert config.ENABLE_AFTERBURN is True, "the switch is restored"
    print("[PASS] test_nothing_happens_when_disabled passed (no drops, no ticks, no discs with the switch off)")


def test_colour_is_the_skin_trail_or_warm_orange():
    g = Game()
    g.set_visible(False)
    try:
        _new_run(g)
        assert tuple(g.visuals.afterburn_color) == ORANGE, g.visuals.afterburn_color
        assert tuple(g.afterburn_pool._glow_rgb) == ORANGE
        neon = RunSkin("neon", complete_palette({"trail": (10, 240, 120)}))
        g.visuals.apply_skin(neon)
        assert tuple(g.visuals.afterburn_color) == (10, 240, 120), g.visuals.afterburn_color
        g.visuals.apply_skin(default_run_skin())
        assert tuple(g.visuals.afterburn_color) == ORANGE, "the default skin keeps the warm orange"
        g.visuals.apply_skin(neon)
        pool = AfterburnPool(g.batch, colour=g.visuals.afterburn_color)
        assert tuple(pool._glow_rgb) == (10, 240, 120)
        assert pool._core_rgb == scorch_rgb((10, 240, 120)), pool._core_rgb
        assert sum(pool._core_rgb) < sum(pool._glow_rgb), "the scorch core is darker than the glow"
        order = g.afterburn_pool._group.parent.order
        assert order == config.AFTERBURN_LAYER_ORDER and 0 < order < 15000, order
    finally:
        g.close()
    print("[PASS] test_colour_is_the_skin_trail_or_warm_orange passed (orange by default, the skin's trail otherwise, core darker)")


def test_reduce_motion_stops_the_flicker_and_keeps_the_fade():
    batch = _batch()
    results = {}
    for reduced in (True, False):
        with _cfg(REDUCE_MOTION=reduced):
            trail = AfterburnTrail()
            trail.spawn(0.0, 0.0, 0.0)
            pool = AfterburnPool(batch, colour=ORANGE)
            glow, core = [], []
            for k in range(40):
                pool.update(0.2 + k / 120.0, trail, 0.0, 0.0)
                glow.append(pool._slots[0].glow_vl.colors[3])  # the first triangle's centre alpha, as drawn
                core.append(pool._slots[0].core_vl.colors[3])
            results[reduced] = (glow, core)
    rg, rc = results[True]
    ng, nc = results[False]
    assert all(b <= a for a, b in zip(rg, rg[1:])), f"reduced motion: the glow only fades {rg}"
    assert all(b <= a for a, b in zip(rc, rc[1:])), f"reduced motion: the core only fades {rc}"
    assert rg[0] > rg[-1] > 0 and rc[0] > rc[-1] > 0, "the fade stays"
    assert any(b > a for a, b in zip(ng, ng[1:])), "normal motion flickers: the glow rises somewhere"
    assert ng[0] > ng[-1] > 0, "normal motion fades too"
    assert all(b <= a for a, b in zip(nc, nc[1:])), "the core does not flicker in either mode"
    print(f"[PASS] test_reduce_motion_stops_the_flicker_and_keeps_the_fade passed (glow {rg[0]} to {rg[-1]}, no rise; normal rises)")


def test_disc_is_the_iso_image_of_the_world_circle():
    batch = _batch()
    trail = AfterburnTrail()
    trail.spawn(100.0, 40.0, 0.0)
    shake = Vec2(3.0, -2.0)
    pool = AfterburnPool(batch, colour=ORANGE)
    ox, oy = to_iso(Vec2(0.0, 0.0), shake)
    pool.update(0.1, trail, ox, oy)
    slot = pool._slots[0]
    for pos, radius in ((slot.glow_pos, config.AFTERBURN_HIT_RADIUS), (slot.core_pos, config.AFTERBURN_CORE_RADIUS)):
        # Triangle k runs centre, rim k, rim k + 1. Every triangle repeats the centre.
        for k in range(12):
            for v, ang in ((0, None), (1, math.tau * k / 12.0), (2, math.tau * (k + 1) / 12.0)):
                if ang is None:
                    wx, wy = 100.0, 40.0
                else:
                    wx = 100.0 + radius * math.cos(ang)
                    wy = 40.0 + radius * math.sin(ang)
                px, py = to_iso(Vec2(wx, wy), shake)
                i = 6 * k + 2 * v
                assert abs(pos[i] - px) < 1e-4 and abs(pos[i + 1] - py) < 1e-4, (k, v, radius, pos[i:i + 2], px, py)
    print("[PASS] test_disc_is_the_iso_image_of_the_world_circle passed (each of 12 triangles matches utils.to_iso)")


def _afterburn_growth(fn):
    """Net bytes that code in the Afterburn modules keeps allocating while ``fn`` runs.

    A Game leaves loader threads running, and tracemalloc counts their allocations too. A filter keeps only the
    allocations whose stack passes through an afterburn file, so the measurement is this feature's alone.
    """
    flt = [tracemalloc.Filter(True, "*afterburn*", all_frames=True)]
    tracemalloc.start(1)
    try:
        before = tracemalloc.take_snapshot().filter_traces(flt)
        fn()
        after = tracemalloc.take_snapshot().filter_traces(flt)
    finally:
        tracemalloc.stop()
    return sum(d.size_diff for d in after.compare_to(before, "filename"))


def test_steady_frames_build_no_new_objects():
    batch = _batch()
    enemies = [_enemy(-400.0 + 20.0 * i, 5.0 * (i % 5), hp=10 ** 6) for i in range(40)]
    with _cfg(AFTERBURN_LIFE_SECONDS=1000.0, REDUCE_MOTION=False):
        trail = AfterburnTrail()
        for i in range(12):
            trail.spawn(10.0 * i, 5.0 * i, 0.0)
        for e in enemies[::3]:
            e.pos = Vec2(e.pos.x, 0.0)
        pool = AfterburnPool(batch, colour=ORANGE)
        deal = (lambda e, a: False)  # noqa: E731  one closure for the whole measurement
        for f in range(30):
            t = f * FRAME
            pool.update(t, trail, 300.0, 200.0)
            trail.tick(enemies, t, deal)

        def steady():
            for f in range(30, 3030):
                t = f * FRAME
                trail.update_dash(False, 0.0, 0.0, t)
                pool.update(t, trail, 300.0 + (f % 7), 200.0)
                trail.tick(enemies, t, deal)

        net = _afterburn_growth(steady)
        base = 0
    assert pool.shown_count == 12, pool.shown_count
    assert net - base < 16384, f"net growth {net - base} bytes over 3000 frames"
    print(f"[PASS] test_steady_frames_build_no_new_objects passed (net {net - base} bytes over 3000 frames, 12 discs drawn)")


def test_frame_cost():
    """Times the strip's per-frame work with 12 live segments and 40 enemies in reach. Prints the cost in ms."""
    batch = _batch()
    enemies = [_enemy(10.0 + 3.0 * i, 4.0, hp=10 ** 6) for i in range(40)]
    trail = AfterburnTrail()
    for i in range(12):
        trail.spawn(10.0 * i, 0.0, 0.0)
    pool = AfterburnPool(batch, colour=ORANGE)
    deal = (lambda e, a: False)  # noqa: E731
    frames = 2000
    with _cfg(AFTERBURN_LIFE_SECONDS=1000.0, REDUCE_MOTION=False):  # keep all 12 alive for the whole measurement
        t0 = time.perf_counter()
        for f in range(frames):
            t = 0.01 + f * FRAME
            trail.update_dash(False, 0.0, 0.0, t)
            trail.tick(enemies, t, deal)
            pool.update(t, trail, 300.0, 200.0)
        ms = (time.perf_counter() - t0) * 1000.0 / frames
        assert pool.shown_count == 12, pool.shown_count
    assert ms < 2.0, f"afterburn costs {ms:.3f} ms a frame, over the 2 ms budget"
    print(f"[PASS] test_frame_cost passed (afterburn {ms:.3f} ms a frame: tick + draw, 12 live segments, 40 enemies)")


def test_kill_goes_through_the_normal_kill_path():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        target = Enemy(pos=Vec2(5.0, 0.0), hp=4, speed=0.0, behavior="chaser")
        s.enemies[:] = [target]
        before = g.score.score
        g.afterburn.spawn(0.0, 0.0, s.time)
        dealt = g.afterburn.tick(s.enemies, s.time, g.afterburn_deal)
        assert dealt == 1 and target not in s.enemies and getattr(target, "_is_dead", False), dealt
        assert g.afterburn.kills == 1 and g.score.score > before, (g.afterburn.kills, g.score.score, before)
    finally:
        g.close()
    print("[PASS] test_kill_goes_through_the_normal_kill_path passed (the kill left the list and scored)")


def _dash_across_chasers(g, s, lane_y=22.0, duration=2.6):
    """Dash along +x past a line of chasers 22 px to each side. Returns (hp left, chasers killed, drops, peak live)."""
    lane = []
    for x in (20.0, 50.0, 80.0):
        for y in (lane_y, -lane_y):
            lane.append(Enemy(pos=Vec2(x, y), hp=20, speed=0.0, behavior="chaser"))
    s.enemies[:] = lane
    g.player.pos = Vec2(0.0, 0.0)
    g.mouse_xy = to_iso(Vec2(400.0, 0.0), Vec2(0.0, 0.0))  # aim the dash down +x
    g._dash()
    assert g.player.is_dashing, "the dash started"
    peak = 0
    mid_shown = 0
    steps = int(round(duration * 60))
    for k in range(steps):
        _steps(g, 1)
        peak = max(peak, sum(1 for seg in g.afterburn.segments if seg.live))
        if k == 40:  # draw in mid-burn so the discs are placed
            g.on_draw()
            mid_shown = g.afterburn_pool.shown_count
    return lane, peak, mid_shown


def test_in_play_dash_across_chasers():
    g = Game()
    g.set_visible(False)
    try:
        s = _new_run(g)
        lane, peak, mid_shown = _dash_across_chasers(g, s)
        assert mid_shown >= 1, "a live strip is drawn mid-burn"
        hits = g.afterburn.hits
        kills = g.afterburn.kills
        drops = g.afterburn.drops
        alive_left = sum(1 for seg in g.afterburn.segments if seg.live)
        hp_left = [max(0, e.hp) for e in lane]
        dead = [e for e in lane if getattr(e, "_is_dead", False)]
        assert g.player.hp > 0 and g.state is not None
        assert kills == len(dead) == 6, (kills, len(dead), hp_left)
        assert hits == 6 * 5, f"each chaser burns 5 ticks (20 hp at 4 a tick): {hits}"
        assert all(h == 0 for h in hp_left), hp_left
        assert 3 <= drops <= 4, f"a 0.15 s dash drops 3 or 4 segments: {drops}"
        assert peak == drops and alive_left <= drops
        print(f"[PASS] test_in_play_dash_across_chasers passed (hits {hits}, kills {kills} of {len(lane)} chasers, "
              f"segments dropped {drops}, peak live {peak}, live at 2.6 s {alive_left})")
    finally:
        g.close()


def _patch_mean(x: int, y: int, half: int = 2) -> tuple:
    """Mean colour of a (2 * half + 1) square of the frame, centred at GL point (x, y) in view pixels.

    The buffer's rows run bottom-up, the same as GL y, so the row index is y itself. The buffer may be a different
    size from the view, so the point is scaled to it.
    """
    from utils import VIEW_H, VIEW_W

    img = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
    w, h = img.width, img.height
    raw = img.get_data("RGBA", w * 4)
    cx = int(round(x * w / float(VIEW_W)))
    cy = int(round(y * h / float(VIEW_H)))
    sums = [0, 0, 0]
    n = 0
    for dy in range(-half, half + 1):
        for dx in range(-half, half + 1):
            i = ((cy + dy) * w + (cx + dx)) * 4
            for c in range(3):
                sums[c] += raw[i + c]
            n += 1
    return tuple(v / n for v in sums)


def test_strip_is_drawn_in_a_real_frame():
    """The strip changes the pixels of the frame where its oldest segment sits, and nothing changes with the switch off."""
    from utils import to_iso

    spot = None
    means = {}
    for enabled in (True, False):
        random.seed(8)  # the same particles in both frames, so the only difference is the strip
        with _cfg(ENABLE_AFTERBURN=enabled):
            g = Game()
            g.set_visible(True)
            try:
                s = _new_run(g)
                s.enemies[:] = []
                g.player.pos = Vec2(-150.0, 0.0)
                g.mouse_xy = to_iso(Vec2(400.0, 0.0), Vec2(0.0, 0.0))
                g._dash()
                _steps(g, 10)
                g.on_draw()
                if enabled:
                    live = [seg for seg in g.afterburn.segments if seg.live]
                    assert live, "the dash dropped segments"
                    oldest = min(live, key=lambda seg: seg.t0)
                    spot = to_iso(Vec2(oldest.x, oldest.y), Vec2(0.0, 0.0))
                means[enabled] = _patch_mean(int(round(spot[0])), int(round(spot[1])))
            finally:
                g.close()
    diff = sum(abs(a - b) for a, b in zip(means[True], means[False]))
    assert diff > 60, f"the strip did not change the frame at its oldest segment: on {means[True]} off {means[False]}"
    print(f"[PASS] test_strip_is_drawn_in_a_real_frame passed (the oldest segment's patch: on {tuple(round(v) for v in means[True])}, "
          f"off {tuple(round(v) for v in means[False])})")


def test_in_play_disabled_does_nothing():
    g = Game()
    g.set_visible(False)
    try:
        with _cfg(ENABLE_AFTERBURN=False):
            s = _new_run(g)
            lane, peak, mid_shown = _dash_across_chasers(g, s)
            assert g.afterburn.hits == 0 and g.afterburn.kills == 0 and g.afterburn.drops == 0
            assert peak == 0 and mid_shown == 0 and g.afterburn_pool.shown_count == 0
            assert all(e.hp == 20 and not getattr(e, "_is_dead", False) for e in lane), [e.hp for e in lane]
    finally:
        g.close()
    print("[PASS] test_in_play_disabled_does_nothing passed (switch off: no drops, no hits, nothing drawn, chasers untouched)")


def run_all():
    tmp = tempfile.mkdtemp(prefix="w8_afterburn_")
    score.HIGH_SCORE_FILE = os.path.join(tmp, "high_scores.json")
    progress.PROGRESS_FILE = os.path.join(tmp, "progress.json")
    test_config_block()
    test_drops_every_fifty_ms_while_dashing()
    test_twelve_segment_cap_reuses_the_oldest()
    test_segment_expires_at_two_and_a_half_seconds()
    test_damage_is_four_every_half_second()
    test_each_enemy_keeps_its_own_timer()
    test_re_entry_after_a_gap_ticks_at_once()
    test_reach_is_the_twenty_six_px_edge()
    test_boss_takes_half()
    test_nothing_happens_when_disabled()
    test_colour_is_the_skin_trail_or_warm_orange()
    test_reduce_motion_stops_the_flicker_and_keeps_the_fade()
    test_disc_is_the_iso_image_of_the_world_circle()
    test_steady_frames_build_no_new_objects()
    test_frame_cost()
    test_kill_goes_through_the_normal_kill_path()
    test_strip_is_drawn_in_a_real_frame()
    test_in_play_dash_across_chasers()
    test_in_play_disabled_does_nothing()
    print("ALL W8 AFTERBURN TESTS PASSED")


if __name__ == "__main__":
    run_all()
