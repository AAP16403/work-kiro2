"""Wave 4 projectile effects: the auto-fire cost fix, the Flak Battery rework and the per-weapon looks.

Covers: the pooled shot bank (slots reused, no new pages per shot, bounded churn); the pooled quad arrays
(a placed line or disc writes the values the shader reads); the steady frame allocating nothing; the
Flak radius matching the real fragment reach in states.py; the telegraph and detonation ring being the
iso image of that radius; the shell's arc, flicker and landing point; reduced motion freezing the flak
oscillators and the ring growth; the trail and impact look of each weapon being distinct; and the pixel
direction of a Rapid Fire trail on screen.

Run with the venv python: ``python test_w4_fx.py``. The GL tests open a hidden window, as the other files do.
"""

import math
import random
import sys
from types import SimpleNamespace

import pyglet
from pyglet import gl

import config
import projectile_art as pa
from game import Game
from particles import ParticleSystem
from projectile import Projectile
from projectile_art import (
    FLAK_BLAST_RADIUS,
    FLAK_LIFT_PX,
    FRAGMENT_STYLE,
    WEAPON_STYLES,
    ProjectileVisual,
    ShotBank,
    flak_detonation,
    iso_ring_axes,
    spawn_impact,
    style_for_projectile,
)
from states import PlayingState
from utils import Vec2, to_iso
from weapons import WEAPONS


def _set_reduced(on: bool) -> bool:
    prev = bool(config.REDUCE_MOTION)
    config.REDUCE_MOTION = bool(on)
    return prev


def _flak_shell(ttl0: float = 1.0, pos=(0.0, 0.0), vel=(300.0, 0.0), ttl=None) -> Projectile:
    return Projectile(pos=Vec2(*pos), vel=Vec2(*vel), damage=10, ttl=ttl0 if ttl is None else ttl,
                      weapon_name="Flak Battery", projectile_type="flak", cluster_on_death=True)


def _visual(bank: ShotBank, proj) -> ProjectileVisual:
    group = pyglet.graphics.Group(order=14000)
    return ProjectileVisual(bank, group, proj)


# ---- pure geometry (no GL) ---------------------------------------------------------------------

def test_flak_radius_is_the_farthest_real_fragment():
    """Run the real shrapnel spawn and check its farthest fragment reaches FLAK_BLAST_RADIUS, and no farther."""
    ps = ParticleSystem()
    rng = random.Random(4)
    game = SimpleNamespace(particle_system=ps)
    far = 0.0
    near = float("inf")
    speeds = []
    ttls = []
    for trial in range(3000):
        s = SimpleNamespace(rng=rng, projectiles=[], shake=0.0)
        p = Projectile(pos=Vec2(trial * 1.0, -trial * 0.5), vel=Vec2(300.0, 0.0), damage=10,
                       ttl=0.0, projectile_type="flak", cluster_on_death=True)
        PlayingState._spawn_cluster_shrapnel(game, s, p)
        for frag in s.projectiles:
            offset = (frag.pos - p.pos).length()
            speed = frag.vel.length()
            reach = offset + speed * frag.ttl
            far = max(far, reach)
            near = min(near, reach)
            speeds.append(speed)
            ttls.append(frag.ttl)
    assert far <= FLAK_BLAST_RADIUS + 1e-6, f"a fragment reaches {far:.2f}, past the drawn radius {FLAK_BLAST_RADIUS}"
    assert far >= 0.985 * FLAK_BLAST_RADIUS, f"the drawn radius {FLAK_BLAST_RADIUS} is not the real reach ({far:.2f})"
    assert min(speeds) >= 340.0 - 1e-6 and max(speeds) <= 460.0 + 1e-6, "fragment speed range changed"
    assert min(ttls) >= 0.24 - 1e-9 and max(ttls) <= 0.40 + 1e-9, "fragment ttl range changed"
    assert near < far, "fragments should reach a range of distances, not one"
    print(f"[PASS] test_flak_radius_is_the_farthest_real_fragment passed (real reach {near:.1f} to {far:.1f}, drawn {FLAK_BLAST_RADIUS:.0f} px)")


def test_ring_is_the_iso_image_of_the_blast_radius():
    horiz, aspect = iso_ring_axes(FLAK_BLAST_RADIUS)
    xs, ys = [], []
    for k in range(720):
        a = math.tau * k / 720.0
        sx, sy = to_iso(Vec2(FLAK_BLAST_RADIUS * math.cos(a), FLAK_BLAST_RADIUS * math.sin(a)), Vec2(0.0, 0.0))
        xs.append(sx)
        ys.append(sy)
    half_w = (max(xs) - min(xs)) * 0.5
    half_h = (max(ys) - min(ys)) * 0.5
    assert abs(half_w - horiz) / horiz < 0.002, f"horizontal semi-axis {half_w:.3f} vs {horiz:.3f}"
    assert abs(half_h / half_w - aspect) < 0.002, f"aspect {half_h / half_w:.4f} vs {aspect:.4f}"
    ps = ParticleSystem()
    ps.add_ground_ring(Vec2(0.0, 0.0), (255, 190, 90), FLAK_BLAST_RADIUS, 0.3)
    ring = ps.particles[-1]
    assert ring.kind == "ring" and abs(ring.size - horiz) < 1e-9 and abs(ring.aspect - aspect) < 1e-9, "shockwave ring is not the iso blast"
    print(f"[PASS] test_ring_is_the_iso_image_of_the_blast_radius passed (semi-axes {horiz:.1f} x {horiz * aspect:.1f} px)")


def test_ring_grows_unless_reduced_motion():
    ps = ParticleSystem()
    ps.add_ground_ring(Vec2(0.0, 0.0), (255, 190, 90), FLAK_BLAST_RADIUS, 0.3, grow=False)
    assert ps.particles[-1].grow is False, "a held ring must not grow"
    ps2 = ParticleSystem()
    prev = _set_reduced(True)
    try:
        flak_detonation(ps2, Vec2(0.0, 0.0))
    finally:
        _set_reduced(prev)
    rings = [p for p in ps2.particles if p.kind == "ring"]
    assert rings and all(not r.grow for r in rings), "reduced motion must hold the detonation rings"
    ps3 = ParticleSystem()
    flak_detonation(ps3, Vec2(0.0, 0.0))
    assert all(r.grow for r in ps3.particles if r.kind == "ring"), "normal motion grows the detonation rings"
    print("[PASS] test_ring_grows_unless_reduced_motion passed (rings grow normally and hold under reduced motion)")


def test_fragments_get_their_own_look_and_shells_do_not():
    frag = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(400.0, 0.0), damage=5, ttl=0.3, projectile_type="bullet")
    assert style_for_projectile(frag) is FRAGMENT_STYLE, "a short-lived unnamed bullet is a flak fragment"
    basic = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(400.0, 0.0), damage=5, ttl=2.0, projectile_type="bullet")
    assert style_for_projectile(basic) is pa.BASIC_STYLE, "an ordinary bullet keeps the basic look"
    enemy = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(400.0, 0.0), damage=5, ttl=0.3, owner="enemy", projectile_type="bullet")
    assert style_for_projectile(enemy) is not FRAGMENT_STYLE, "an enemy bullet is never a fragment"
    assert style_for_projectile(_flak_shell()) is WEAPON_STYLES["Flak Battery"], "a flak shell keeps the flak look"
    print("[PASS] test_fragments_get_their_own_look_and_shells_do_not passed (fragments amber, shells and enemy shots unchanged)")


def test_per_weapon_looks_are_distinct():
    """Each weapon's trail (painter, piece types) and impact recipe are a signature no other weapon shares."""
    bank_batch = pyglet.graphics.Batch()
    bank = ShotBank(bank_batch)
    signatures = {}
    for weapon in WEAPONS.values():
        p = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, ttl=1.0,
                       weapon_name=weapon.name, projectile_type=weapon.projectile_type)
        h = _visual(bank, p)
        st = h.style
        sig = (st.trail, tuple(type(o).__name__ for o in h._trail), st.impact, st.trail_color)
        assert sig not in signatures.values(), f"{weapon.name} looks like another weapon"
        signatures[weapon.name] = sig
    assert len(set(v[0] for v in signatures.values())) == len(WEAPONS), "every weapon needs its own trail painter"
    assert len(set(v[2] for v in signatures.values())) == len(WEAPONS), "every weapon needs its own impact"
    print(f"[PASS] test_per_weapon_looks_are_distinct passed ({len(signatures)} weapons, each with its own trail and impact)")


def test_impacts_leave_distinct_particles():
    seen = {}
    for name, st in WEAPON_STYLES.items():
        random.seed(7)
        ps = ParticleSystem()
        proj = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, weapon_name=name)
        spawn_impact(ps, proj, Vec2(0.0, 0.0), (120, 200, 90))
        sig = tuple(sorted((p.kind, round(p.size, 1), tuple(p.color)) for p in ps.particles))
        assert sig and sig not in seen.values(), f"{name} impact is not distinct"
        seen[name] = sig
    print("[PASS] test_impacts_leave_distinct_particles passed (every weapon's hit leaves its own particle mix)")


def test_placed_quad_writes_the_values_the_shader_reads():
    batch = pyglet.graphics.Batch()
    line_pool = pa._Pool(batch, 14000, pa._texture("line"), pa._LINE_TEX)
    disc_pool = pa._Pool(batch, 14000, pa._texture("disc"), pa._DISC_TEX)
    line = pa.LinePiece(line_pool, None, (10, 20, 30), 3.0, 200)
    line.set_ends(100.0, 50.0, 130.0, 90.0)
    bank_slot, slot = line._bank, line._slot
    t = bank_slot._translate
    assert abs(t[12 * slot] - 115.0) < 1e-4 and abs(t[12 * slot + 1] - 70.0) < 1e-4, "midpoint not uploaded"
    length = math.hypot(30.0, 40.0)
    assert abs(bank_slot._scale[8 * slot] - length / 4.0) < 1e-4, "length not uploaded as the x scale"
    assert abs(bank_slot._scale[8 * slot + 1] - 3.0 / 4.0) < 1e-4, "thickness not uploaded as the y scale"
    assert abs(bank_slot._rotation[4 * slot] - (-math.degrees(math.atan2(40.0, 30.0)))) < 1e-3, "rotation sign differs from DashAfterimage"
    assert bank_slot._colors[16 * slot + 3] == 200, "opacity is the colour alpha"
    disc = pa.DiscPiece(disc_pool, None, 6.0, (255, 0, 0), 255)
    disc.move(-40.0, 12.0)
    assert abs(disc._bank._scale[8 * disc._slot] - 2.0 * 6.0 / pa._DISC_TEX) < 1e-6, "disc scale is 2r / texture size"
    assert abs(disc._bank._translate[12 * disc._slot] + 40.0) < 1e-6, "disc centre not uploaded"
    line.delete()
    disc.delete()
    assert line._bank is None and disc._bank is None, "delete must release the slot"
    print("[PASS] test_placed_quad_writes_the_values_the_shader_reads passed (position, length, thickness, rotation sign and alpha land in the arrays)")


def test_pool_reuses_slots_and_creates_no_pages_per_shot():
    batch = pyglet.graphics.Batch()
    bank = ShotBank(batch)
    for name in ("line", "trail", "body", "core", "flare"):
        bank.pool(name).warm()
    shots = [_flak_shell(ttl0=1.0) for _ in range(40)] + [
        Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(300.0, 0.0), damage=10, ttl=2.0, weapon_name="Rapid Fire",
                   projectile_type="bullet") for _ in range(40)]
    free_before = {n: bank.pool(n).free_count for n in ("line", "trail", "body", "core", "flare", "ring", "ground")}
    handles = [_visual(bank, p) for p in shots]
    pages = bank.pages
    for h in handles:
        h.delete()
    free_after = {n: bank.pool(n).free_count for n in free_before}
    assert free_after == free_before, f"deleting every shot must give back every slot: {free_before} vs {free_after}"
    for _ in range(3):
        handles = [_visual(bank, p) for p in shots]
        for h in handles:
            h.delete()
    assert bank.pages == pages, f"churn grew the bank from {pages} to {bank.pages} pages"
    print(f"[PASS] test_pool_reuses_slots_and_creates_no_pages_per_shot passed ({bank.pages} pages hold 3 full waves of 80 shots)")


def test_steady_frames_allocate_nothing():
    batch = pyglet.graphics.Batch()
    bank = ShotBank(batch)
    shots = [_flak_shell(ttl0=100.0, pos=(float(i) * 3.0, -20.0), vel=(300.0, 40.0), ttl=100.0) for i in range(12)]
    shots += [Projectile(pos=Vec2(float(i), 30.0), vel=Vec2(340.0, 0.0), damage=10, ttl=100.0, weapon_name="Rapid Fire",
                         projectile_type="bullet") for i in range(12)]
    handles = [_visual(bank, p) for p in shots]
    shake = Vec2(0.0, 0.0)

    def frame(k):
        for p, h in zip(shots, handles):
            p.pos = Vec2(p.pos.x + p.vel.x / 60.0, p.pos.y + p.vel.y / 60.0)
            p.ttl = 100.0 - (k + 1) / 60.0
            h.sync(p, shake)
        bank.flush()

    import gc
    for k in range(30):
        frame(k)
    gc.collect()
    # Warm-up is done. Count the live Python blocks over 400 frames: a leak of even one object per frame
    # would add 400 or more, and the frame loop itself must add none.
    blocks0 = sys.getallocatedblocks()
    for k in range(30, 430):
        frame(k)
    gc.collect()
    grown = sys.getallocatedblocks() - blocks0
    assert grown < 32, f"400 steady frames of 24 shots left {grown} live blocks behind"
    print(f"[PASS] test_steady_frames_allocate_nothing passed (400 steady frames, 24 shots, {grown} net live blocks)")


def test_flak_shell_arcs_over_its_shadow_and_lands_on_the_ring():
    prev = _set_reduced(False)
    try:
        bank = ShotBank(pyglet.graphics.Batch())
        proj = _flak_shell(ttl0=1.0, pos=(-50.0, 30.0), vel=(300.0, -20.0), ttl=1.0)
        h = _visual(bank, proj)
        gaps = {}
        for ttl in (1.0, 0.75, 0.5, 0.25, 0.02):
            proj.pos = Vec2(-50.0 + 300.0 * (1.0 - ttl), 30.0 - 20.0 * (1.0 - ttl))
            proj.ttl = ttl
            h.sync(proj, Vec2(0.0, 0.0))
            gaps[ttl] = h._body.y - h._shadow.y
        assert abs(gaps[1.0]) < 1e-6, "the shell launches from the ground"
        assert abs(gaps[0.02]) < FLAK_LIFT_PX * 0.1, "the shell lands on its shadow"
        assert abs(gaps[0.5] - FLAK_LIFT_PX) < 1e-6, f"apex is {gaps[0.5]:.3f}, expected {FLAK_LIFT_PX}"
        assert gaps[0.75] > 0 and gaps[0.25] > 0, "the arc rises on both sides of the apex"
        landing = Vec2(proj.pos.x + proj.vel.x * proj.ttl, proj.pos.y + proj.vel.y * proj.ttl)
        lx, ly = to_iso(landing, Vec2(0.0, 0.0))
        h.sync(proj, Vec2(0.0, 0.0))
        assert abs(h._telegraph.x - lx) < 1e-4 and abs(h._telegraph.y - ly) < 1e-4, "the ring must sit on the landing point"
    finally:
        _set_reduced(prev)
    print(f"[PASS] test_flak_shell_arcs_over_its_shadow_and_lands_on_the_ring passed (apex gap {FLAK_LIFT_PX:.0f} px, ring on the landing point)")


def test_telegraph_brightens_as_the_shell_comes_down():
    prev = _set_reduced(True)
    try:
        bank = ShotBank(pyglet.graphics.Batch())
        proj = _flak_shell(ttl0=1.0, ttl=1.0)
        h = _visual(bank, proj)
        h.sync(proj, Vec2(0.0, 0.0))
        early = h._telegraph.opacity
        proj.ttl = 0.05
        h.sync(proj, Vec2(0.0, 0.0))
        late = h._telegraph.opacity
    finally:
        _set_reduced(prev)
    assert late > early, f"ring should brighten on approach ({early} -> {late})"
    print(f"[PASS] test_telegraph_brightens_as_the_shell_comes_down passed (opacity {early} at launch, {late} at landing)")


def test_reduced_motion_freezes_the_shell():
    prev = _set_reduced(True)
    try:
        bank = ShotBank(pyglet.graphics.Batch())
        proj = _flak_shell(ttl0=1.0)
        h = _visual(bank, proj)
        seen = set()
        lifts = set()
        for ttl in (0.9, 0.61, 0.37, 0.13):
            proj.ttl = ttl
            h.sync(proj, Vec2(0.0, 0.0))
            seen.add((h._flare.opacity, tuple(s.opacity for s in h._trail[1:])))
            lifts.add(round(h._body.y - h._shadow.y, 6))
        assert len(seen) == 1, f"flicker must stop under reduced motion, saw {seen}"
        assert lifts == {0.0}, f"the arc must not lift under reduced motion, saw {lifts}"
        bank2 = ShotBank(pyglet.graphics.Batch())
        p2 = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(340.0, 0.0), damage=10, ttl=1.0, weapon_name="Rapid Fire",
                        projectile_type="bullet")
        h2 = _visual(bank2, p2)
        h2.sync(p2, Vec2(0.0, 0.0))
        before = [(s.x, s.y, s.x2, s.y2, s.opacity) for s in h2._trail]
        p2.ttl = 0.4
        h2.sync(p2, Vec2(0.0, 0.0))
        after = [(s.x, s.y, s.x2, s.y2, s.opacity) for s in h2._trail]
        assert before == after, "a straight trail with no motion must hold still"
    finally:
        _set_reduced(prev)
    print("[PASS] test_reduced_motion_freezes_the_shell passed (no flicker, no arc lift under reduced motion)")


def test_visuals_leave_the_shot_unchanged():
    bank = ShotBank(pyglet.graphics.Batch())
    for name, weapon in WEAPONS.items():
        p = Projectile(pos=Vec2(4.0, -3.0), vel=Vec2(300.0, 10.0), damage=12, ttl=1.2,
                       weapon_name=name, projectile_type=weapon.projectile_type, is_crit=True)
        h = _visual(bank, p)
        before = (p.pos.x, p.pos.y, p.vel.x, p.vel.y, p.ttl, p.damage, p.pierce, p.is_crit, p.owner)
        for _ in range(20):
            h.sync(p, Vec2(2.0, 2.0))
        after = (p.pos.x, p.pos.y, p.vel.x, p.vel.y, p.ttl, p.damage, p.pierce, p.is_crit, p.owner)
        assert before == after, f"{name} visual changed the shot"
        h.delete()
    print("[PASS] test_visuals_leave_the_shot_unchanged passed (every weapon's sync leaves the shot alone)")


# ---- window tests -----------------------------------------------------------------------------

def _pixel(img_data, width: int, height: int, x: int, y: int):
    """RGB at window pixel (x, y), y up as in GL. get_data returns rows bottom-up, so row index = y."""
    o = (y * width + x) * 4
    return img_data[o], img_data[o + 1], img_data[o + 2]


def test_rapid_trail_points_back_on_screen(g):
    """Draw one Rapid Fire shot and read the framebuffer: the trail lies behind the head, not in front."""
    batch = pyglet.graphics.Batch()
    bank = ShotBank(batch)
    g.clear()
    proj = Projectile(pos=Vec2(0.0, 0.0), vel=Vec2(340.0, 0.0), damage=10, ttl=1.5,
                      weapon_name="Rapid Fire", projectile_type="bullet")
    h = _visual(bank, proj)
    h.sync(proj, Vec2(0.0, 0.0))
    bank.flush()
    gl.glClearColor(0.0, 0.0, 0.0, 1.0)
    g.clear()
    batch.draw()
    buf = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
    w, hgt = buf.width, buf.height
    data = buf.get_data("RGBA", w * 4)
    hx, hy = to_iso(proj.pos, Vec2(0.0, 0.0))
    # Screen back for world +x is (-0.7, -0.35) normalised: sample along it and against it.
    n = math.hypot(config.ISO_SCALE_X, config.ISO_SCALE_Y)
    bx, by = -config.ISO_SCALE_X / n, -config.ISO_SCALE_Y / n
    behind = _pixel(data, w, hgt, int(round(hx + bx * 9.0)), int(round(hy + by * 9.0)))
    ahead = _pixel(data, w, hgt, int(round(hx - bx * 9.0)), int(round(hy - by * 9.0)))
    h.delete()
    bank.flush()
    assert behind[1] > 120, f"no trail behind the head: pixel {behind}"
    assert ahead[1] < 40, f"something drawn ahead of the head: pixel {ahead}"
    print(f"[PASS] test_rapid_trail_points_back_on_screen passed (behind {behind}, ahead {ahead})")


def test_flak_frame_draws_shadow_ring_and_shell(g):
    """Render a flak shell mid-flight. The ground shadow is below the shell and the ring is around the landing point."""
    batch = pyglet.graphics.Batch()
    bank = ShotBank(batch)
    prev = _set_reduced(False)  # the arc is a motion effect, so this checks it at normal motion
    try:
        proj = _flak_shell(ttl0=1.0, pos=(0.0, 0.0), vel=(300.0, 0.0))
        h = _visual(bank, proj)  # built at full ttl, so the arc starts from its launch
        proj.ttl = 0.5
        h.sync(proj, Vec2(0.0, 0.0))
        bank.flush()
        # A mid-grey ground, so the black shadow darkens it and the amber ring brightens it.
        gl.glClearColor(0.25, 0.25, 0.25, 1.0)
        g.clear()
        batch.draw()
        buf = pyglet.image.get_buffer_manager().get_color_buffer().get_image_data()
        w, hgt = buf.width, buf.height
        data = buf.get_data("RGBA", w * 4)
        hx, hy = to_iso(proj.pos, Vec2(0.0, 0.0))
        shadow_px = _pixel(data, w, hgt, int(round(hx)), int(round(hy - FLAK_LIFT_PX)))
        # The landing point is 150 px along the flight (300 px/s for half a second). The ring's band sits at
        # 0.975 of its horizontal semi-axis, so sample just inside its right edge.
        ring_x, ring_y = to_iso(Vec2(150.0, 0.0), Vec2(0.0, 0.0))
        band = 0.975 * pa.iso_ring_axes(FLAK_BLAST_RADIUS)[0]
        ring_px = _pixel(data, w, hgt, int(round(ring_x + band)), int(round(ring_y)))
        h.delete()
        bank.flush()
    finally:
        _set_reduced(prev)
    background = 64  # 0.25 of 255
    assert shadow_px[0] < background - 8, f"no shadow under the shell at mid-flight: {shadow_px}"
    assert ring_px[0] > background + 8 and ring_px[0] > ring_px[2], f"landing ring not drawn at the landing point: {ring_px}"
    print(f"[PASS] test_flak_frame_draws_shadow_ring_and_shell passed (shadow {shadow_px}, ring {ring_px})")


def run_all():
    g = Game()
    g.set_visible(False)
    try:
        test_rapid_trail_points_back_on_screen(g)
        test_flak_frame_draws_shadow_ring_and_shell(g)
    finally:
        g.close()
    test_flak_radius_is_the_farthest_real_fragment()
    test_ring_is_the_iso_image_of_the_blast_radius()
    test_ring_grows_unless_reduced_motion()
    test_fragments_get_their_own_look_and_shells_do_not()
    test_per_weapon_looks_are_distinct()
    test_impacts_leave_distinct_particles()
    test_placed_quad_writes_the_values_the_shader_reads()
    test_pool_reuses_slots_and_creates_no_pages_per_shot()
    test_steady_frames_allocate_nothing()
    test_flak_shell_arcs_over_its_shadow_and_lands_on_the_ring()
    test_telegraph_brightens_as_the_shell_comes_down()
    test_reduced_motion_freezes_the_shell()
    test_visuals_leave_the_shot_unchanged()
    print("\nALL WAVE 4 FX TESTS PASSED")


if __name__ == "__main__":
    run_all()
