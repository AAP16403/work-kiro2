"""Wave 6 Chain Lightning tests: the timed powerup, the kill chain, its damage, the arc pool and the Guide entry.

Covers: the config keys and the rare tier; the HUD countdown; the chain firing only during CHAIN_DURATION seconds
(the edge at expiry included); the nearest-target rules (dead, out of range, already hit, the range edge); each kill
throwing at most one arc, and a chain running through kills while a survivor ends it; damage at CHAIN_DAMAGE_PERCENT
rounded half up; a re-pick refreshing the timer without stacking; the arc pool's place, fade, hide and slot reuse;
REDUCE_MOTION keeping the arc while dropping the re-roll; the pickup decoration; steady frames building no objects;
and the Guide entry reading its numbers from config. Plain functions that print [PASS] lines, run from run_all().
"""

import math
import random
import tracemalloc

import pyglet

import config
import guide_info
from chain import ChainArcPool, chain_active, chain_damage, make_chain_pickup_art, nearest_chain_target, resolve_chain
from enemy import Enemy
from menu import GuideMenu
from player import Player
from powerup import (
    POWERUP_NAMES,
    RARE_POWERUP_KINDS,
    TIMED_POWERUPS,
    PowerUp,
    apply_powerup,
    expire_timed_effects,
    format_timed_powerups_hud,
    is_rare_powerup,
)
from utils import Vec2

SECS = float(config.CHAIN_DURATION)
_WINDOW = None


def _batch():
    """A batch on a hidden window, so the pool's pyglet shapes have a GL context."""
    global _WINDOW
    if _WINDOW is None:
        _WINDOW = pyglet.window.Window(width=64, height=64, visible=False)
    return pyglet.graphics.Batch()


def _player(damage=None):
    p = Player(pos=Vec2(0.0, 0.0))
    if damage is not None:
        p.damage = damage
    return p


def _pickup(player, now):
    apply_powerup(player, PowerUp(pos=Vec2(0.0, 0.0), kind="chain"), now)


def _enemy(x, y, hp=100):
    return Enemy(pos=Vec2(float(x), float(y)), hp=int(hp), speed=0.0, behavior="chaser")


def _deal_log():
    """A deal_damage stand-in: records (enemy id, amount) and kills when hp reaches 0."""
    log = []

    def deal(e, amount):
        log.append((id(e), amount))
        e.hp -= amount
        return e.hp <= 0

    return log, deal


def _identity(x, y):
    return (x, y)


def test_config_and_kind_wiring():
    assert config.CHAIN_DURATION == 8.0, config.CHAIN_DURATION
    assert config.CHAIN_RANGE == 160.0, config.CHAIN_RANGE
    assert config.CHAIN_DAMAGE_PERCENT == 30, config.CHAIN_DAMAGE_PERCENT
    assert "chain" in RARE_POWERUP_KINDS and is_rare_powerup("chain"), RARE_POWERUP_KINDS
    assert is_rare_powerup("drone") and not is_rare_powerup("ricochet")
    assert "chain" not in TIMED_POWERUPS, "chain is handled by chain.py, so the Player field is read with a default"
    assert POWERUP_NAMES.get("chain", "CHAIN") == "CHAIN"
    p = _player()
    apply_powerup(p, PowerUp(pos=Vec2(0.0, 0.0), kind="chain"), 10.0)
    assert float(p.chain_until) == 10.0 + SECS, "a pickup sets the expiry CHAIN_DURATION ahead"
    print("[PASS] test_config_and_kind_wiring passed (8 s, 160 px, 30%, chain is rare and timed)")


def test_hud_countdown_then_gone():
    p = _player()
    _pickup(p, 100.0)
    assert format_timed_powerups_hud(p, 103.0) == "Chain 5s", format_timed_powerups_hud(p, 103.0)
    assert format_timed_powerups_hud(p, 107.2) == "Chain 1s", format_timed_powerups_hud(p, 107.2)
    assert format_timed_powerups_hud(p, 108.0) == "", format_timed_powerups_hud(p, 108.0)
    print("[PASS] test_hud_countdown_then_gone passed ('Chain 5s', 'Chain 1s', then empty at 108.0)")


def test_chain_fires_only_during_its_eight_seconds():
    idle = _player(10)
    e_idle = [_enemy(0, 0), _enemy(50, 0)]
    _, deal = _deal_log()
    assert resolve_chain(e_idle[0], e_idle, idle, 101.0, deal) == 0
    assert e_idle[1].hp == 100, "no pickup, no arc"

    p = _player(10)
    assert not chain_active(p, 0.0), "a player who never picked it up has no chain"
    _pickup(p, 100.0)
    assert chain_active(p, 100.0) and chain_active(p, 100.001) and chain_active(p, 107.999)
    assert not chain_active(p, 108.0), "the expiry edge is out"

    killed = _enemy(0, 0, hp=0)
    fresh = [_enemy(50, 0)]
    log, deal = _deal_log()
    assert resolve_chain(killed, fresh, p, 100.5, deal) == 1, "inside the window the kill chains"
    assert log == [(id(fresh[0]), 3)], log

    late = [_enemy(50, 0)]
    log, deal = _deal_log()
    assert resolve_chain(killed, late, p, 108.0, deal) == 0, "at the expiry the chain is off"
    assert resolve_chain(killed, late, p, 109.5, deal) == 0
    assert log == [] and late[0].hp == 100
    print("[PASS] test_chain_fires_only_during_its_eight_seconds passed (idle 0, 100.0 to 107.999 on, 108.0 off)")


def test_nearest_target_rules():
    src = Vec2(0.0, 0.0)
    dead = _enemy(5, 0, hp=0)
    flagged = _enemy(6, 0, hp=50)
    flagged._is_dead = True
    far = _enemy(161, 0)
    edge = _enemy(0, 160)
    near = _enemy(100, 0)
    behind = _enemy(-120, 0)
    everyone = [dead, flagged, far, behind, edge, near]
    assert nearest_chain_target(src, everyone, set()) is near, "nearest in range wins over list order"
    assert nearest_chain_target(src, [dead, flagged, far], set()) is None, "dead and out-of-range are skipped"
    assert nearest_chain_target(src, [edge], set()) is edge, "exactly CHAIN_RANGE counts as in range"
    assert nearest_chain_target(src, [near], {id(near)}) is None, "an enemy already hit is skipped"
    assert nearest_chain_target(src, [near, behind], {id(near)}) is behind, "the next nearest takes its place"
    print("[PASS] test_nearest_target_rules passed (dead, flagged, out of range and hit enemies skipped; edge included)")


def test_damage_is_thirty_percent_rounded_half_up():
    table = {0: 0, 1: 0, 3: 1, 5: 2, 7: 2, 8: 2, 9: 3, 10: 3, 15: 5, 16: 5, 25: 8, 33: 10, 35: 11, 100: 30}
    for dmg, want in table.items():
        assert chain_damage(dmg) == want, f"chain_damage({dmg}) = {chain_damage(dmg)}, want {want}"
    assert chain_damage(15.0) == 5 and chain_damage(4.5) == 1, "float damage uses the same rule"
    # Through a real chain: 15 damage gives an arc of 5 (banker's rounding would give 4).
    p = _player(15)
    _pickup(p, 0.0)
    killed = _enemy(0, 0, hp=0)
    target = _enemy(40, 0)
    log, deal = _deal_log()
    assert resolve_chain(killed, [target], p, 1.0, deal) == 1
    assert log == [(id(target), 5)] and target.hp == 95, (log, target.hp)
    print("[PASS] test_damage_is_thirty_percent_rounded_half_up passed (15 -> 5, 35 -> 11, 25 -> 8, 10 -> 3)")


def test_each_kill_chains_at_most_once():
    # One kill, a pack of three in range: one arc, to the nearest. The others are untouched.
    p = _player(10)
    _pickup(p, 0.0)
    killed = _enemy(0, 0, hp=0)
    pack = [_enemy(80, 0), _enemy(40, 0), _enemy(60, 0)]
    log, deal = _deal_log()
    assert resolve_chain(killed, pack, p, 1.0, deal) == 1
    assert log == [(id(pack[1]), 3)], "the arc goes to the nearest, at 40 px"
    assert pack[0].hp == 100 and pack[2].hp == 100

    # A chain through kills: K kills A, A's arc kills B, B's arc hits C and C survives, so the chain stops.
    # Three kills (K, A, B) throw three arcs, and each enemy is hit once.
    p = _player(10)
    _pickup(p, 0.0)
    killed = _enemy(0, 0, hp=0)
    a = _enemy(50, 0, hp=3)
    b = _enemy(100, 0, hp=3)
    c = _enemy(150, 0, hp=100)
    log, deal = _deal_log()
    arcs = resolve_chain(killed, [a, b, c], p, 1.0, deal)
    assert arcs == 3, arcs
    assert [i for i, _ in log] == [id(a), id(b), id(c)], "every enemy is hit once, in chain order"
    assert [amt for _, amt in log] == [3, 3, 3]
    assert a.hp <= 0 and b.hp <= 0 and c.hp == 97

    # A survivor does not chain: the first arc leaves its target alive, so the nearer-to-it enemy is never hit.
    p = _player(10)
    _pickup(p, 0.0)
    killed = _enemy(0, 0, hp=0)
    alive = _enemy(40, 0, hp=100)
    behind_alive = _enemy(45, 0, hp=3)
    log, deal = _deal_log()
    assert resolve_chain(killed, [alive, behind_alive], p, 1.0, deal) == 1
    assert [i for i, _ in log] == [id(alive)] and behind_alive.hp == 3

    # The killed enemy is never its own target, even while it is still in the list flagged dead.
    p = _player(10)
    _pickup(p, 0.0)
    killed = _enemy(0, 0, hp=0)
    killed._is_dead = True
    log, deal = _deal_log()
    assert resolve_chain(killed, [killed], p, 1.0, deal) == 0 and log == []
    print("[PASS] test_each_kill_chains_at_most_once passed (one arc per pack kill, 3 kills = 3 arcs, survivors stop it)")


def test_repick_refreshes_the_timer_and_does_not_stack():
    p = _player()
    _pickup(p, 100.0)
    assert float(p.chain_until) == 100.0 + SECS, p.chain_until
    _pickup(p, 105.0)
    assert float(p.chain_until) == 105.0 + SECS, "a re-pick restarts the full duration, it does not add"
    assert chain_active(p, 112.99) and not chain_active(p, 113.0)
    _pickup(p, 107.5)
    assert float(p.chain_until) == 107.5 + SECS, p.chain_until
    expire_timed_effects(p, 115.5)
    assert float(p.chain_until) == 0.0 and not chain_active(p, 115.5)
    print("[PASS] test_repick_refreshes_the_timer_and_does_not_stack passed (105 -> 113, 107.5 -> 115.5, not 123.5)")


def test_pool_places_fades_hides_and_reuses_slots():
    batch = _batch()
    pool = ChainArcPool(batch, size=3, segments=5, rng=random.Random(1))
    assert pool.size == 3 and pool.live_count == 0
    assert all(len(a.core_pos) == 12 * 5 and len(a.glow_pos) == 12 * 5 for a in pool._arcs), "a quad per segment"
    pool.spawn(Vec2(0.0, 0.0), Vec2(100.0, 0.0), 1.0)
    pool.update(1.05, lambda x, y: (x + 500.0, y + 300.0))
    assert pool.live_count == 1
    first = pool._arcs[0]
    assert first.shown
    assert first.pts[0] == 500.0 and first.pts[1] == 300.0, "the start follows the projection"
    assert 180 <= first.core_col[3] <= 200, first.core_col[3]  # 255 * (1 - 0.05 / 0.22)
    assert 0 < first.glow_col[3] <= int(config.CHAIN_ARC_GLOW_OPACITY), first.glow_col[3]
    pool.update(1.5, _identity)
    assert pool.live_count == 0 and not first.shown and first.core_col[3] == 0 and first.glow_col[3] == 0, \
        "hidden after the fade"

    # Slot reuse: all three busy, the fourth arc takes the oldest slot. No vertex list is added.
    pool.reset()
    for i, t in enumerate((2.0, 2.01, 2.02)):
        pool.spawn(Vec2(0.0, float(i)), Vec2(50.0, float(i)), t)
    assert pool.live_count == 3
    pool.spawn(Vec2(0.0, 9.0), Vec2(50.0, 9.0), 2.03)
    assert pool.live_count == 3 and pool.size == 3
    assert pool._arcs[0].t0 == 2.03, "the oldest arc gave way"
    print("[PASS] test_pool_places_fades_hides_and_reuses_slots passed (placed, faded to 0.22 s, reused the oldest)")


def test_core_width_is_the_configured_thickness():
    batch = _batch()
    pool = ChainArcPool(batch, size=1, segments=5, rng=random.Random(9))
    pool.spawn(Vec2(0.0, 0.0), Vec2(100.0, 0.0), 0.0)
    pool.update(0.01, lambda x, y: (x, y))
    arc = pool._arcs[0]
    ax, ay, bx, by = arc.core_pos[0], arc.core_pos[1], arc.core_pos[2], arc.core_pos[3]
    width = math.hypot(ax - bx, ay - by)
    assert abs(width - float(config.CHAIN_ARC_CORE_WIDTH)) < 1e-6, width
    gx, gy, hx, hy = arc.glow_pos[0], arc.glow_pos[1], arc.glow_pos[2], arc.glow_pos[3]
    assert abs(math.hypot(gx - hx, gy - hy) - float(config.CHAIN_ARC_GLOW_WIDTH)) < 1e-6
    print("[PASS] test_core_width_is_the_configured_thickness passed (the quads are CHAIN_ARC_CORE_WIDTH wide)")


def test_resolve_draws_one_arc_per_kill_in_the_pool():
    batch = _batch()
    pool = ChainArcPool(batch, size=12, segments=5, rng=random.Random(2))
    p = _player(10)
    _pickup(p, 0.0)
    killed = _enemy(0, 0, hp=0)
    a = _enemy(50, 0, hp=3)
    b = _enemy(100, 0, hp=3)
    c = _enemy(150, 0, hp=100)
    _, deal = _deal_log()
    arcs = resolve_chain(killed, [a, b, c], p, 1.0, deal, pool=pool)
    assert arcs == 3 and pool.live_count == 3, (arcs, pool.live_count)
    print("[PASS] test_resolve_draws_one_arc_per_kill_in_the_pool passed (3 kills, 3 pooled arcs)")


def test_reduce_motion_keeps_the_arc_and_drops_the_flicker():
    saved = config.REDUCE_MOTION
    try:
        batch = _batch()
        # Normal motion: the shape re-rolls once CHAIN_FLICKER_SECONDS have passed, not before.
        config.REDUCE_MOTION = False
        pool = ChainArcPool(batch, size=1, segments=5, rng=random.Random(3))
        pool.spawn(Vec2(0.0, 0.0), Vec2(100.0, 0.0), 0.0)
        pool.update(0.02, _identity)
        y_a = pool._arcs[0].pts[3]  # the first interior point's y
        pool.update(0.03, _identity)
        assert pool._arcs[0].pts[3] == y_a, "no re-roll inside the flicker interval"
        pool.update(0.06, _identity)
        assert pool._arcs[0].pts[3] != y_a, "normal motion re-rolls the jagged shape"

        # REDUCE_MOTION: the shape never re-rolls, and the arc still draws and fades.
        config.REDUCE_MOTION = True
        pool = ChainArcPool(batch, size=1, segments=5, rng=random.Random(3))
        pool.spawn(Vec2(0.0, 0.0), Vec2(100.0, 0.0), 0.0)
        seen = []
        for t in (0.02, 0.06, 0.10, 0.15):
            pool.update(t, _identity)
            seen.append((pool._arcs[0].pts[3], pool._arcs[0].core_col[3]))
        assert len({round(y, 9) for y, _ in seen}) == 1, f"the shape is fixed: {seen}"
        assert seen[0][1] > seen[-1][1] > 0, f"the arc still fades out: {seen}"
        assert pool.live_count == 1, "the arc is still drawn in reduced motion"
    finally:
        config.REDUCE_MOTION = saved
    print("[PASS] test_reduce_motion_keeps_the_arc_and_drops_the_flicker passed (re-roll every 0.05 s, or never)")


def test_pickup_decoration_is_a_zigzag_ring():
    batch = _batch()
    color = tuple(config.CHAIN_COLOR)
    out, offsets = make_chain_pickup_art(batch, color, 14.0)
    assert len(out) == 6 and len(offsets) == 6, (len(out), len(offsets))
    near = 14.0 + float(config.CHAIN_PICKUP_RING_NEAR)
    far = 14.0 + float(config.CHAIN_PICKUP_RING_FAR)
    for i, (dx, dy) in enumerate(offsets):
        r = math.hypot(dx, dy)
        want = far if i % 2 else near
        assert abs(r - want) < 1e-6, (i, r, want)
    assert all(abs(s.radius - float(config.CHAIN_PICKUP_DOT)) < 1e-6 for s in out)
    assert tuple(out[0].color[:3]) == color
    print("[PASS] test_pickup_decoration_is_a_zigzag_ring passed (six dots, radii alternate 21 and 26 px)")


def test_steady_frames_build_no_new_objects():
    saved_secs = config.CHAIN_ARC_SECONDS
    saved_motion = config.REDUCE_MOTION
    try:
        config.CHAIN_ARC_SECONDS = 1000.0  # keep the arcs alive for the whole measurement
        config.REDUCE_MOTION = False       # the re-roll path runs too
        batch = _batch()
        pool = ChainArcPool(batch, size=4, segments=5, rng=random.Random(4))
        for i in range(4):
            pool.spawn(Vec2(0.0, float(i)), Vec2(90.0, float(i)), 0.0)
        proj = lambda x, y: (x * 0.5 + 300.0, y * 0.5 + 200.0)  # noqa: E731  returns a fresh tuple per point
        for f in range(30):
            pool.update(f / 60.0, proj)
        tracemalloc.start()
        try:
            base, _ = tracemalloc.get_traced_memory()
            t = 0.5
            for f in range(3000):
                t += 1.0 / 60.0
                pool.update(t, proj)
            net, _ = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert pool.live_count == 4, pool.live_count
        assert net - base < 16384, f"net growth {net - base} bytes over 3000 frames"
    finally:
        config.CHAIN_ARC_SECONDS = saved_secs
        config.REDUCE_MOTION = saved_motion
    print(f"[PASS] test_steady_frames_build_no_new_objects passed (net {net - base} bytes over 3000 frames)")


def test_guide_entry_reads_config():
    entries = {e["key"]: e for e in guide_info.powerup_entries()}
    assert "chain" in entries, sorted(entries)
    assert entries["chain"]["name"] == "Chain Lightning (Z)", entries["chain"]["name"]
    what = entries["chain"]["what"]
    assert "within 160 px" in what and "for 8s" in what and "30% of your damage" in what, what
    saved = config.CHAIN_RANGE, config.CHAIN_DURATION, config.CHAIN_DAMAGE_PERCENT
    try:
        config.CHAIN_RANGE = 220.0
        config.CHAIN_DURATION = 5.5
        config.CHAIN_DAMAGE_PERCENT = 45
        changed = {e["key"]: e for e in guide_info.powerup_entries()}["chain"]["what"]
    finally:
        config.CHAIN_RANGE, config.CHAIN_DURATION, config.CHAIN_DAMAGE_PERCENT = saved
    assert "within 220 px" in changed and "for 5.5s" in changed and "45% of your damage" in changed, changed
    tab_keys = [e["key"] for e in GuideMenu.POWERUP_INFO]
    assert "chain" in tab_keys and "drone" in tab_keys, tab_keys
    assert guide_info.powerup_entries()[-1]["key"] == "chain"
    print("[PASS] test_guide_entry_reads_config passed (the Powerups tab lists Chain Lightning, numbers from config)")


def run_all():
    test_config_and_kind_wiring()
    test_hud_countdown_then_gone()
    test_chain_fires_only_during_its_eight_seconds()
    test_nearest_target_rules()
    test_damage_is_thirty_percent_rounded_half_up()
    test_each_kill_chains_at_most_once()
    test_repick_refreshes_the_timer_and_does_not_stack()
    test_pool_places_fades_hides_and_reuses_slots()
    test_core_width_is_the_configured_thickness()
    test_resolve_draws_one_arc_per_kill_in_the_pool()
    test_reduce_motion_keeps_the_arc_and_drops_the_flicker()
    test_pickup_decoration_is_a_zigzag_ring()
    test_steady_frames_build_no_new_objects()
    test_guide_entry_reads_config()
    print("ALL W6 CHAIN LIGHTNING TESTS PASSED")


if __name__ == "__main__":
    run_all()
