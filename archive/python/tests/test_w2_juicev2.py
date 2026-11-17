"""Deterministic tests for game feel v2: enemy hit squash, low-health vignette and Ultra flash."""

import config
from enemy import Enemy
from game import Game
from juice import (
    HIT_SQUASH_TIME,
    LOW_HP_MAX_OPACITY,
    ULTRA_FLASH_TIME,
    _squash_table,
    hit_squash_scale,
    low_hp_vignette_strength,
    ultra_flash_color,
    ultra_flash_strength,
)
from states import GameStateName
from utils import Vec2

_MISSING = object()


def _new_run(g):
    g._init_game()
    g.fsm.set_state(GameStateName.PLAYING)
    return g.state


def _set_reduce_motion(value):
    """Set config.REDUCE_MOTION for a test and return the previous value (or _MISSING)."""
    previous = getattr(config, "REDUCE_MOTION", _MISSING)
    config.REDUCE_MOTION = value
    return previous


def _restore_reduce_motion(previous):
    if previous is _MISSING:
        try:
            del config.REDUCE_MOTION
        except AttributeError:
            pass
    else:
        config.REDUCE_MOTION = previous


def test_hit_squash_springs_back_to_rest():
    assert hit_squash_scale(0.0) == (1.0, 1.0), "no timer means rest"
    assert hit_squash_scale(-0.5) == (1.0, 1.0), "a negative timer means rest"
    sx, sy = hit_squash_scale(HIT_SQUASH_TIME)
    assert sx > 1.1 and sy < 0.92, f"impact should squash wide and short, got {sx:.3f}, {sy:.3f}"
    assert abs(sx * sy - 1.0) < 1e-9, "the squash should hold the body's area"
    # Walking the timer down to zero must end exactly at rest and never leave the body stuck.
    tail = [hit_squash_scale(HIT_SQUASH_TIME * k / 100.0)[0] for k in range(10, -1, -1)]
    assert tail[-1] == 1.0, "the squash must end at exactly 1.0"
    assert abs(tail[-2] - 1.0) < 0.05, "the squash must be nearly finished before the timer ends"
    print(f"[PASS] test_hit_squash_springs_back_to_rest passed (impact {sx:.3f} x {sy:.3f}, rest exactly 1.0)")


def test_enemy_body_squashes_on_hit_and_returns_to_rest(g):
    _new_run(g)
    vis = g.visuals
    center = Vec2(0.0, 0.0)
    e = Enemy(pos=Vec2(40.0, 10.0), hp=30, speed=0.0, behavior="chaser")
    vis.ensure_enemy(e)
    vis.sync_enemy(e, center)
    h = vis._enemy_handles[id(e)]
    body = h.objs[1]
    shape_count = len(h.objs)
    rest_positions = tuple(body._vertex_list.position[:])

    e.hit_flash_timer = HIT_SQUASH_TIME
    vis.sync_enemy(e, center)
    squashed_positions = tuple(body._vertex_list.position[:])
    assert squashed_positions != rest_positions, "a hit must change the body geometry"
    assert len(h.objs) == shape_count, "the squash must not create shapes"

    frames = 0
    while e.hit_flash_timer > 0.0 and frames < 100:
        e.hit_flash_timer = max(0.0, e.hit_flash_timer - 1.0 / 60.0)
        vis.sync_enemy(e, center)
        frames += 1
    assert e.hit_flash_timer == 0.0
    assert tuple(body._vertex_list.position[:]) == rest_positions, "the body must return to its exact rest geometry"
    assert len(h.objs) == shape_count
    print(f"[PASS] test_enemy_body_squashes_on_hit_and_returns_to_rest passed (squash then rest in {frames} frames, no new shapes)")


def test_squash_geometry_is_cached_not_rebuilt(g):
    _new_run(g)
    vis = g.visuals
    e = Enemy(pos=Vec2(-30.0, 25.0), hp=30, speed=0.0, behavior="swarm")
    vis.ensure_enemy(e)
    center = Vec2(0.0, 0.0)

    def hit_and_decay():
        e.hit_flash_timer = HIT_SQUASH_TIME
        vis.sync_enemy(e, center)
        while e.hit_flash_timer > 0.0:
            e.hit_flash_timer = max(0.0, e.hit_flash_timer - 1.0 / 60.0)
            vis.sync_enemy(e, center)

    hit_and_decay()  # build this body's squash table once
    misses_before = _squash_table.cache_info().misses
    hits_before = _squash_table.cache_info().hits
    hit_and_decay()
    hit_and_decay()
    assert _squash_table.cache_info().misses == misses_before, "repeat hits must reuse the squash table"
    assert _squash_table.cache_info().hits == hits_before, "a body keeps its table reference, so repeat hits do no lookups"
    print("[PASS] test_squash_geometry_is_cached_not_rebuilt passed (repeat hits build nothing and look nothing up)")


def test_vignette_is_zero_at_and_above_thirty_percent(g):
    for hp_ratio in (1.0, 0.75, 0.5, 0.31, 0.30):
        for t in (0.0, 0.7, 1.9):
            assert low_hp_vignette_strength(hp_ratio, t) == 0.0, f"vignette must be zero at hp {hp_ratio}"
    assert low_hp_vignette_strength(0.29, 0.0) > 0.0, "the vignette must start fading in below 30 percent"

    _new_run(g)
    vis = g.visuals
    g.player.max_hp = 100
    for hp in (100, 60, 30):
        g.player.hp = hp
        vis.sync_juice(0.5, Vec2(0.0, 0.0), g.player, g.width, g.height)
        assert vis._juice._vignette.opacity == 0, f"vignette sprite must be hidden at {hp} percent HP"
    g.player.hp = 15
    vis.sync_juice(0.5, Vec2(0.0, 0.0), g.player, g.width, g.height)
    assert vis._juice._vignette.opacity > 0, "vignette sprite must show at 15 percent HP"
    print("[PASS] test_vignette_is_zero_at_and_above_thirty_percent passed (zero at 100, 75, 50, 31, 30 percent; fades in below)")


def test_vignette_strengthens_as_hp_falls():
    previous = _set_reduce_motion(False)
    try:
        strengths = [low_hp_vignette_strength(hp, 1.0) for hp in (0.29, 0.2, 0.1, 0.0)]
    finally:
        _restore_reduce_motion(previous)
    assert all(a < b for a, b in zip(strengths, strengths[1:])), f"vignette should rise as HP falls: {strengths}"
    assert 0.0 < strengths[0] and strengths[-1] <= LOW_HP_MAX_OPACITY + 1e-9, f"vignette stays within its cap: {strengths}"
    print("[PASS] test_vignette_strengthens_as_hp_falls passed (rises monotonically from 29 to 0 percent HP)")


def test_reduce_motion_disables_vignette_pulse():
    samples = [0.0, 0.6, 1.2, 1.8, 2.4]
    previous = _set_reduce_motion(False)
    try:
        pulsed = [low_hp_vignette_strength(0.1, t) for t in samples]
        _set_reduce_motion(True)
        steady = [low_hp_vignette_strength(0.1, t) for t in samples]
    finally:
        _restore_reduce_motion(previous)
    assert max(pulsed) - min(pulsed) > 0.05, f"without reduce motion the vignette should pulse: {pulsed}"
    assert max(steady) == min(steady) > 0.0, f"reduce motion should hold the vignette steady and visible: {steady}"
    print("[PASS] test_reduce_motion_disables_vignette_pulse passed (pulse varies normally, steady with REDUCE_MOTION)")


def test_reduce_motion_steadies_the_vignette_sprite(g):
    _new_run(g)
    vis = g.visuals
    g.player.max_hp = 100
    g.player.hp = 12
    previous = _set_reduce_motion(True)
    try:
        opacities = []
        for t in (0.0, 0.7, 1.4, 2.1):
            vis.sync_juice(t, Vec2(0.0, 0.0), g.player, g.width, g.height)
            opacities.append(vis._juice._vignette.opacity)
    finally:
        _restore_reduce_motion(previous)
    assert len(set(opacities)) == 1 and opacities[0] > 0, f"sprite opacity should not pulse with REDUCE_MOTION: {opacities}"
    print(f"[PASS] test_reduce_motion_steadies_the_vignette_sprite passed (sprite opacity {opacities[0]} at every sampled time)")


def test_default_reduce_motion_is_off():
    if not hasattr(config, "REDUCE_MOTION"):
        print("[SKIP requires-wave1] test_default_reduce_motion_is_off needs config.REDUCE_MOTION from wave 1")
        return
    assert config.REDUCE_MOTION is False, "REDUCE_MOTION must default to False"
    print("[PASS] test_default_reduce_motion_is_off passed (config.REDUCE_MOTION defaults to False)")


def test_ultra_flash_fades_out_over_its_time():
    assert ultra_flash_strength(0.0) == 1.0, "the flash starts at full strength"
    assert ultra_flash_strength(ULTRA_FLASH_TIME) == 0.0, "the flash is gone when its time ends"
    assert ultra_flash_strength(-0.01) == 0.0, "a flash before its trigger is off"
    vals = [ultra_flash_strength(ULTRA_FLASH_TIME * k / 20.0) for k in range(21)]
    assert all(a >= b for a, b in zip(vals, vals[1:])), "the flash must fade monotonically"
    print("[PASS] test_ultra_flash_fades_out_over_its_time passed (full at 0, zero at the end, monotone)")


def test_ultra_flash_is_white_tinted_by_variant():
    variants = (tuple(config.ULTRA_BEAM_COLOR), (255, 180, 180), (255, 220, 180))
    for variant in variants:
        tint = ultra_flash_color(variant)
        assert tint != (255, 255, 255), f"the flash must be tinted, not pure white, for {variant}"
        for c, v in zip(tint, variant):
            assert v <= c <= 255, f"tint {tint} must sit between the variant {variant} and white"
    print("[PASS] test_ultra_flash_is_white_tinted_by_variant passed (each variant tints the white flash)")


def test_ultra_fire_flashes_in_the_variant_colour(g):
    _new_run(g)
    vis = g.visuals
    beam = tuple(config.ULTRA_BEAM_COLOR)
    expected_base = (beam, (255, 180, 180), (255, 220, 180))
    for variant in (0, 1, 2):
        g.player.ultra_charges = 2
        g.player.ultra_cd_until = 0.0
        g.player.ultra_variant_idx = variant
        g.player.pos = Vec2(0.0, 0.0)
        g.mouse_xy = (g.width * 0.6, g.height * 0.5)
        g.state.time = 10.0 + variant
        g._use_ultra()
        juice = vis._juice
        assert juice._flash_on, f"variant {variant} must start the Ultra flash"
        assert juice._flash_t0 == g.state.time, "the flash must start at the Ultra trigger time"
        got = tuple(juice._flash.color[:3])
        assert got == ultra_flash_color(expected_base[variant]), f"variant {variant} flash colour {got}"
        # Let the flash finish before the next variant so each trigger starts clean.
        vis.sync_juice(g.state.time + ULTRA_FLASH_TIME + 0.01, Vec2(0.0, 0.0), g.player, g.width, g.height)
        assert not juice._flash_on, "the flash must switch off once its time has passed"
    print("[PASS] test_ultra_fire_flashes_in_the_variant_colour passed (beam, tri-beam and shockwave each tint the flash)")


def test_ultra_flash_layers_over_the_shockwave_ring(g):
    _new_run(g)
    vis = g.visuals
    flash_order = vis._juice._flash.group.order
    ring_order = g.particle_system.group.order
    assert flash_order > ring_order, f"the flash ({flash_order}) must draw above the shockwave ring ({ring_order})"
    print(f"[PASS] test_ultra_flash_layers_over_the_shockwave_ring passed (flash group {flash_order} above ring group {ring_order})")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_hit_squash_springs_back_to_rest()
        test_enemy_body_squashes_on_hit_and_returns_to_rest(g)
        test_squash_geometry_is_cached_not_rebuilt(g)
        test_vignette_is_zero_at_and_above_thirty_percent(g)
        test_vignette_strengthens_as_hp_falls()
        test_reduce_motion_disables_vignette_pulse()
        test_reduce_motion_steadies_the_vignette_sprite(g)
        test_default_reduce_motion_is_off()
        test_ultra_flash_fades_out_over_its_time()
        test_ultra_flash_is_white_tinted_by_variant()
        test_ultra_fire_flashes_in_the_variant_colour(g)
        test_ultra_flash_layers_over_the_shockwave_ring(g)
    finally:
        g.close()
    print("\nALL WAVE 2 JUICEV2 TESTS PASSED")


if __name__ == "__main__":
    run_all()
