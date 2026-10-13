"""Chain Lightning: each enemy the player kills throws one arc to the nearest other live enemy.

The pickup is a timed powerup: start_chain gives CHAIN_DURATION seconds, and picking it up again refreshes the timer
without stacking. powerup.py calls start_chain, expire_chain and the HUD label. While the timer runs, a kill made by
the player calls resolve_chain:

    - the arc goes to the nearest other live enemy within CHAIN_RANGE of the killed enemy that this chain has
      not hit yet, and deals CHAIN_DAMAGE_PERCENT of the player's damage, rounded half up (10 -> 3, 15 -> 5);
    - each kill throws at most one arc. If the arc kills its target, that kill throws the next arc, so a chain can
      run through a pack. An enemy the chain has already hit is never hit again by the same chain.

ChainArcPool draws the arcs. Each arc is two quad strips (a bright core and a soft glow) in vertex lists built once
and reused, so a frame writes positions and alpha in place. An arc keeps its jagged shape with REDUCE_MOTION on;
otherwise the shape re-rolls every CHAIN_FLICKER_SECONDS. Every arc fades out over CHAIN_ARC_SECONDS in both modes.
make_chain_pickup_art builds the pickup decoration, a zigzag ring of dots, with the same contract as
powerup_art.make_pickup_art.

Every number comes from config.py. Nothing here reads a Player field other than damage and chain_until.
"""

from __future__ import annotations

import math
import random
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from pyglet import shapes
from pyglet.gl import GL_TRIANGLES

import config

# Chain Lightning's Player field: the run-clock expiry (0.0 = inactive). Read with a default, so a Player without
# the attribute reads as inactive. powerup.py calls start_chain and expire_chain; it is not in TIMED_POWERUPS.
CHAIN_FIELD = "chain_until"


def chain_damage(player_damage) -> int:
    """Arc damage for a player damage value: CHAIN_DAMAGE_PERCENT of it, rounded half up."""
    exact = Decimal(str(player_damage)) * Decimal(str(config.CHAIN_DAMAGE_PERCENT)) / Decimal(100)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def chain_active(player, now: float) -> bool:
    """True while the Chain Lightning pickup runs at run time ``now``."""
    return float(now) < float(getattr(player, CHAIN_FIELD, 0.0))


def start_chain(player, now: float) -> None:
    """Pick up Chain Lightning: CHAIN_DURATION seconds from ``now``. A pickup while it runs restarts the timer."""
    until = float(now) + float(config.CHAIN_DURATION)
    setattr(player, CHAIN_FIELD, max(float(getattr(player, CHAIN_FIELD, 0.0)), until))


def expire_chain(player, now: float) -> None:
    """Clear the expiry once it has passed, so the state reads as inactive again."""
    until = float(getattr(player, CHAIN_FIELD, 0.0))
    if until > 0.0 and float(now) >= until:
        setattr(player, CHAIN_FIELD, 0.0)


def _is_live(e) -> bool:
    return e.hp > 0 and not getattr(e, "_is_dead", False)


def nearest_chain_target(src, enemies, hit_ids, reach: float | None = None):
    """Nearest live enemy within CHAIN_RANGE of ``src`` whose id is not in ``hit_ids``. None when there is none.

    ``src`` is anything with .x and .y. A distance exactly equal to the range counts as in range.
    """
    limit = float(config.CHAIN_RANGE if reach is None else reach)
    limit_sq = limit * limit
    best = None
    best_sq = limit_sq
    for e in enemies:
        if id(e) in hit_ids or not _is_live(e):
            continue
        dx = e.pos.x - src.x
        dy = e.pos.y - src.y
        d_sq = dx * dx + dy * dy
        if d_sq <= limit_sq and (best is None or d_sq < best_sq):
            best = e
            best_sq = d_sq
    return best


def resolve_chain(killed, enemies, player, now: float, deal_damage: Callable, pool=None) -> int:
    """Run the chain for one kill made by the player. Returns the number of arcs thrown (0 when no chain runs).

    ``killed`` is the enemy just killed; it needs a .pos and is never hit by its own chain. ``enemies`` is the list
    of enemies to search. ``deal_damage(enemy, amount) -> bool`` applies the arc damage and returns True when that
    hit killed the enemy. The caller removes the enemy and scores the kill; this function does not. ``pool`` is a
    ChainArcPool to draw the arcs in, or None.

    Each kill throws at most one arc: an arc that kills its target continues the chain from that target, and an arc
    that leaves its target alive ends the chain. The hit set makes each enemy get at most one arc per chain.
    """
    if not chain_active(player, now):
        return 0
    amount = chain_damage(player.damage)
    hit_ids = {id(killed)}
    src = killed.pos
    arcs = 0
    while True:
        target = nearest_chain_target(src, enemies, hit_ids)
        if target is None:
            break
        hit_ids.add(id(target))
        arcs += 1
        if pool is not None:
            pool.spawn(src, target.pos, now)
        if not deal_damage(target, amount):
            break
        src = target.pos
    return arcs


class _Arc:
    """One pooled arc: its endpoints in world units, its jitter, and its two vertex lists. Built once, reused."""

    __slots__ = (
        "sx", "sy", "dx", "dy", "ux", "uy", "off", "pts", "t0", "jit_t", "live", "shown",
        "core_vl", "core_pos", "core_col", "glow_vl", "glow_pos", "glow_col",
    )


class ChainArcPool:
    """A fixed set of arcs. spawn() takes a free slot, or the oldest busy one. update() places and fades them.

    Each arc layer is one triangle-list vertex list with a quad per segment. The lists are created once in
    ``batch``; update() writes their positions and alpha in place, so a frame creates no shapes or vertex lists.
    Call spawn() during the frame's logic and update(now, project) once per frame before drawing. project is a
    callable (world_x, world_y) -> (screen_x, screen_y).
    """

    def __init__(self, batch, group=None, size: int | None = None, segments: int | None = None, rng=None):
        n = int(config.CHAIN_ARC_POOL if size is None else size)
        self._segs = max(1, int(config.CHAIN_ARC_SEGMENTS if segments is None else segments))
        self._rng = rng if rng is not None else random.Random()
        self._batch = batch
        # A probe shape gives the program and the blend group pyglet uses for shapes (SRC_ALPHA blending).
        probe = shapes.Circle(0, 0, 1.0, color=tuple(config.CHAIN_COLOR), batch=None, group=group)
        self._program = probe.program
        self._group = probe.get_shape_group()
        probe.delete()
        self._arcs: list[_Arc] = []
        for _ in range(n):
            arc = _Arc()
            arc.sx = arc.sy = arc.dx = arc.dy = 0.0
            arc.ux = arc.uy = 0.0
            arc.off = [0.0] * (self._segs + 1)  # sideways offset per point; the two ends stay at 0
            arc.pts = [0.0] * (2 * (self._segs + 1))  # scratch: projected centre-line points, reused every frame
            arc.t0 = 0.0
            arc.jit_t = 0.0
            arc.live = False
            arc.shown = False
            arc.core_vl, arc.core_pos, arc.core_col = self._make_layer(config.CHAIN_ARC_COLOR)
            arc.glow_vl, arc.glow_pos, arc.glow_col = self._make_layer(config.CHAIN_COLOR)
            self._arcs.append(arc)

    def _make_layer(self, rgb):
        """One vertex list for an arc layer: six vertices (two triangles) per segment, alpha 0 to start."""
        count = 6 * self._segs
        pos = [0.0] * (12 * self._segs)
        col = []
        r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
        for _ in range(count):
            col.extend((r, g, b, 0))
        vl = self._program.vertex_list(
            count, GL_TRIANGLES, self._batch, self._group,
            position=("f", pos), colors=("Bn", col),
        )
        return vl, pos, col

    @property
    def size(self) -> int:
        return len(self._arcs)

    @property
    def live_count(self) -> int:
        return sum(1 for arc in self._arcs if arc.live)

    def spawn(self, src, dst, now: float) -> None:
        """Start an arc from ``src`` to ``dst`` (anything with .x and .y, in world units) at run time ``now``."""
        arc = None
        for a in self._arcs:
            if not a.live:
                arc = a
                break
        if arc is None:
            arc = min(self._arcs, key=lambda a: a.t0)  # every slot busy: the oldest arc gives way
        arc.sx = float(src.x)
        arc.sy = float(src.y)
        arc.dx = float(dst.x)
        arc.dy = float(dst.y)
        vx = arc.dx - arc.sx
        vy = arc.dy - arc.sy
        length = math.hypot(vx, vy)
        if length > 1e-6:
            arc.ux = -vy / length
            arc.uy = vx / length
        else:
            arc.ux = 0.0
            arc.uy = 1.0
        arc.t0 = float(now)
        arc.jit_t = float(now)
        self._roll(arc)
        arc.live = True

    def _roll(self, arc: _Arc) -> None:
        jitter = float(config.CHAIN_ARC_JITTER)
        off = arc.off
        for i in range(1, self._segs):
            off[i] = self._rng.uniform(-jitter, jitter)

    @staticmethod
    def _set_alpha(col, alpha: int) -> None:
        for j in range(3, len(col), 4):
            col[j] = alpha

    def _hide(self, arc: _Arc) -> None:
        """Make both layers transparent. The vertex lists stay in the batch, so nothing is created or freed."""
        if arc.shown:
            self._set_alpha(arc.core_col, 0)
            arc.core_vl.colors[:] = arc.core_col
            self._set_alpha(arc.glow_col, 0)
            arc.glow_vl.colors[:] = arc.glow_col
            arc.shown = False

    def _write_layer(self, vl, pos, col, pts, half: float, alpha: int) -> None:
        """Write one layer's quads: each segment is a strip ``half`` px either side of its centre line."""
        k = 0
        for i in range(self._segs):
            x0 = pts[2 * i]
            y0 = pts[2 * i + 1]
            x1 = pts[2 * i + 2]
            y1 = pts[2 * i + 3]
            dx = x1 - x0
            dy = y1 - y0
            length = math.hypot(dx, dy)
            if length > 1e-9:
                nx = -dy / length * half
                ny = dx / length * half
            else:
                nx = 0.0
                ny = half
            ax = x0 + nx
            ay = y0 + ny
            bx = x0 - nx
            by = y0 - ny
            cx = x1 - nx
            cy = y1 - ny
            ex = x1 + nx
            ey = y1 + ny
            # Triangle a-b-c, then a-c-e.
            pos[k] = ax
            pos[k + 1] = ay
            pos[k + 2] = bx
            pos[k + 3] = by
            pos[k + 4] = cx
            pos[k + 5] = cy
            pos[k + 6] = ax
            pos[k + 7] = ay
            pos[k + 8] = cx
            pos[k + 9] = cy
            pos[k + 10] = ex
            pos[k + 11] = ey
            k += 12
        self._set_alpha(col, alpha)
        vl.position[:] = pos
        vl.colors[:] = col

    def update(self, now: float, project) -> None:
        """Place every live arc through ``project``, fade it, and hide the ones that have finished."""
        now = float(now)
        secs = float(config.CHAIN_ARC_SECONDS)
        still = bool(config.REDUCE_MOTION)
        flicker = float(config.CHAIN_FLICKER_SECONDS)
        glow_max = int(config.CHAIN_ARC_GLOW_OPACITY)
        core_half = float(config.CHAIN_ARC_CORE_WIDTH) * 0.5
        glow_half = float(config.CHAIN_ARC_GLOW_WIDTH) * 0.5
        segs = self._segs
        for arc in self._arcs:
            if not arc.live:
                continue
            age = now - arc.t0
            if age < 0.0 or age >= secs:
                arc.live = False
                self._hide(arc)
                continue
            # REDUCE_MOTION keeps the shape fixed for the whole arc. Otherwise it re-rolls at the flicker rate.
            if not still and now - arc.jit_t >= flicker:
                arc.jit_t = now
                self._roll(arc)
            fade = 1.0 - age / secs
            pts = arc.pts
            span_x = arc.dx - arc.sx
            span_y = arc.dy - arc.sy
            for i in range(segs + 1):
                t = i / segs
                off = arc.off[i]
                sx, sy = project(arc.sx + span_x * t + arc.ux * off, arc.sy + span_y * t + arc.uy * off)
                pts[2 * i] = sx
                pts[2 * i + 1] = sy
            self._write_layer(arc.core_vl, arc.core_pos, arc.core_col, pts, core_half, int(255.0 * fade))
            self._write_layer(arc.glow_vl, arc.glow_pos, arc.glow_col, pts, glow_half, int(glow_max * fade))
            arc.shown = True

    def reset(self) -> None:
        """Hide every arc at once, e.g. when a run ends."""
        for arc in self._arcs:
            arc.live = False
            self._hide(arc)


def make_chain_pickup_art(batch, color, size: float, group=None):
    """Pickup decoration for Chain Lightning: six dots in a zigzag ring round the orb.

    Dots alternate between CHAIN_PICKUP_RING_NEAR and CHAIN_PICKUP_RING_FAR past the orb edge, so the ring reads as
    a crackle, not a plain ring like Ricochet's. Returns (shapes, offsets) like powerup_art.make_pickup_art:
    offsets[i] is the (dx, dy) of shapes[i] from the orb centre.
    """
    r = float(size)
    out = []
    offsets = []
    for i in range(6):
        ang = math.tau * i / 6.0
        ring = r + (float(config.CHAIN_PICKUP_RING_FAR) if i % 2 else float(config.CHAIN_PICKUP_RING_NEAR))
        dot = shapes.Circle(0, 0, float(config.CHAIN_PICKUP_DOT), color=color, batch=batch, group=group)
        dot.opacity = 235
        out.append(dot)
        offsets.append((math.cos(ang) * ring, math.sin(ang) * ring))
    return out, offsets
