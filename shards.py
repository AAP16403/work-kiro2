"""Shards: a critical hit splits the player's bullet into three shards at the point where it hits.

split_crit runs when a critical player bullet hits an enemy. It spawns three shards at the impact point (impact_point):
one on the bullet's own line and two SHARD_SPREAD_DEG either side of it. Each shard flies at SHARD_SPEED_FRACTION of the
bullet's speed for SHARD_SECONDS and deals shard_damage(), which is SHARD_DAMAGE_PERCENT of the bullet's damage rounded
half up.

Rules:
    - A shard cannot split. Shards are not projectiles and carry no crit flag, and step() never calls split_crit.
    - A shard never hits the enemy that made it (its origin). Every other live enemy can be hit.
    - A shard is spent on its first hit. It expires after SHARD_SECONDS of fixed-step time.
    - At most SHARD_CAP shards are live. A new shard takes a free slot, or else drops the oldest live shard.
    - Flak shrapnel does not split. It is already the burst of a flak shell, and copying its crit flag would stack shards.

ShardPool is a fixed set of slots. Each slot is one quad in a glow.QuadBank, so spawn, step and draw create no objects per
frame. The quad is drawn in the shot colour: the skin's player_bullet_tint, or the bullet's weapon colour when that is None. A slow shimmer runs in full motion only. Reduced motion stops the shimmer and nothing else: the shards
still move, since that is gameplay, and they still fade out over their life, since the fade carries the effect's meaning.

Every number comes from config.py. step() reads no Player field, and it uses no random number, so a run repeats for a seed.
"""

from __future__ import annotations

import math
from decimal import ROUND_HALF_UP, Decimal

import config
import motion
import utils
from glow import QuadBank, alpha_texture
from projectile_art import FRAGMENT_TTL_MAX, style_for

_EXPIRE_EPS = 1e-9   # a shard whose ttl reaches this has used its life (float error stays far below it)
_SHARD_TEX_PX = 32   # texels across the shard's dot texture
_shard_tex = None


def _shard_texture():
    """A dot with a solid core and a soft edge, built once. The core is what makes a shard read as a spark, not a haze.

    Needs a GL context, so it is built on first use (ShardPool with a batch), never at import.
    """
    global _shard_tex
    if _shard_tex is None:
        _shard_tex = alpha_texture(_SHARD_TEX_PX, lambda d: min(1.0, max(0.0, (1.0 - d) * 2.5)))
    return _shard_tex


def shard_damage(bullet_damage) -> int:
    """Shard damage for a bullet's damage: SHARD_DAMAGE_PERCENT of it, rounded half up (30 -> 11, 10 -> 4)."""
    exact = Decimal(str(bullet_damage)) * Decimal(str(config.SHARD_DAMAGE_PERCENT)) / Decimal(100)
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _is_flak_shrapnel(bullet) -> bool:
    """A flak fragment: a player bullet with no weapon name and the short ttl states.py gives burst fragments."""
    return (not getattr(bullet, "weapon_name", "")
            and str(getattr(bullet, "projectile_type", "bullet")) == "bullet"
            and float(getattr(bullet, "ttl", 0.0)) <= FRAGMENT_TTL_MAX + 1e-6)


def can_split(bullet) -> bool:
    """True for a critical player bullet that may split: not an enemy shot, and not flak shrapnel."""
    if str(getattr(bullet, "owner", "player")) != "player" or not getattr(bullet, "is_crit", False):
        return False
    return not _is_flak_shrapnel(bullet)


def shard_colour(bullet, tint):
    """The colour shards draw in: the skin's plain-shot tint, or the bullet's weapon colour when the tint is None."""
    if tint is not None:
        return (int(tint[0]), int(tint[1]), int(tint[2]))
    return style_for(getattr(bullet, "weapon_name", ""), getattr(bullet, "projectile_type", "bullet")).head


def impact_point(a, b, centre, reach: float) -> tuple[float, float]:
    """Where the path a -> b first enters the circle of radius ``reach`` round ``centre``, in world units.

    a, b and centre are anything with .x and .y. The path is clamped to its own length, so a path that starts inside
    the circle gives its start point. A path that never reaches the circle gives its nearest point to the centre.
    """
    dx = b.x - a.x
    dy = b.y - a.y
    a_coef = dx * dx + dy * dy
    if a_coef <= 1e-12:
        return (float(b.x), float(b.y))
    fx = a.x - centre.x
    fy = a.y - centre.y
    b_coef = 2.0 * (fx * dx + fy * dy)
    c_coef = fx * fx + fy * fy - float(reach) * float(reach)
    disc = b_coef * b_coef - 4.0 * a_coef * c_coef
    if disc >= 0.0:
        t = (-b_coef - math.sqrt(disc)) / (2.0 * a_coef)
    else:
        t = -b_coef / (2.0 * a_coef)
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    return (a.x + dx * t, a.y + dy * t)


def split_crit(pool, bullet, impact_x: float, impact_y: float, origin, tint=None) -> int:
    """Split a critical player bullet at (impact_x, impact_y) into three shards. Returns the number spawned.

    Returns 0 and does nothing when ENABLE_SHARDS is False, when ``pool`` is None, when the bullet may not split (see
    can_split), or when the bullet has no direction. ``origin`` is the enemy that took the hit, and its shards never hit it.
    ``tint`` is the skin's player_bullet_tint, or None to use the weapon colour.
    """
    if pool is None or not config.ENABLE_SHARDS or not can_split(bullet):
        return 0
    vx = float(bullet.vel.x)
    vy = float(bullet.vel.y)
    speed = math.hypot(vx, vy)
    if speed <= 1e-9:
        return 0
    ux = vx / speed
    uy = vy / speed
    out_speed = speed * float(config.SHARD_SPEED_FRACTION)
    dmg = shard_damage(bullet.damage)
    rgb = shard_colour(bullet, tint)
    spread = math.radians(float(config.SHARD_SPREAD_DEG))
    c = math.cos(spread)
    s = math.sin(spread)
    # One shard either side of the bullet's own direction, and one straight on.
    for dx, dy in ((ux * c + uy * s, -ux * s + uy * c), (ux, uy), (ux * c - uy * s, ux * s + uy * c)):
        pool.spawn(impact_x, impact_y, dx * out_speed, dy * out_speed, dmg, origin, rgb)
    return 3


def _segment_point_dist_sq(cx: float, cy: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Squared distance from point (cx, cy) to segment a-b, in plain floats so the hot path builds no Vec2."""
    abx = bx - ax
    aby = by - ay
    apx = cx - ax
    apy = cy - ay
    ab2 = abx * abx + aby * aby
    if ab2 <= 1e-9:
        return apx * apx + apy * apy
    t = (apx * abx + apy * aby) / ab2
    t = 0.0 if t < 0.0 else (1.0 if t > 1.0 else t)
    qx = ax + abx * t - cx
    qy = ay + aby * t - cy
    return qx * qx + qy * qy


def _streak_rotation(vx: float, vy: float) -> float:
    """Quad rotation in degrees that lays a streak along the world velocity's on-screen direction.

    The sign follows projectile_art.LinePiece: rot = -degrees(atan2(dy, dx)) for a screen-space direction.
    """
    ix = (vx - vy) * config.ISO_SCALE_X
    iy = (vx + vy) * config.ISO_SCALE_Y
    return -math.degrees(math.atan2(iy, ix))


class _Shard:
    """One pooled shard. Its fields are overwritten on every spawn, so a frame never creates one."""

    __slots__ = (
        "live", "shown", "styled", "x", "y", "vx", "vy", "ttl", "life", "dmg", "origin", "seq", "rot", "r", "g", "b", "phase",
    )

    def __init__(self) -> None:
        self.live = False
        self.shown = False          # the bank currently draws this slot, so the next draw must hide it when it ends
        self.styled = False         # the bank holds this shard's size, rotation and colour; a draw then sets only alpha
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.ttl = 0.0
        self.life = 0.0
        self.dmg = 0
        self.origin = None          # the enemy that made this shard; it is never hit by it
        self.seq = 0                # spawn order: the smallest live seq is the oldest shard
        self.rot = 0.0
        self.r = 255
        self.g = 255
        self.b = 255
        self.phase = 0.0            # shimmer phase, so the shards do not pulse in step


class ShardPool:
    """A fixed set of shard slots, drawn through one QuadBank when a batch is given.

    spawn() takes a free slot, or drops the oldest live shard when the pool is full. step() moves, expires and hits.
    draw() places and fades the slots and hides the ones that have ended. Without a batch the pool holds the logic only,
    which is what the unit tests use.
    """

    def __init__(self, batch=None, size: int | None = None, order: int | None = None) -> None:
        n = max(1, int(config.SHARD_CAP if size is None else size))
        self._slots = [_Shard() for _ in range(n)]
        self._live = 0
        self._seq = 0
        self._bank = None
        if batch is not None:
            self._bank = QuadBank(batch, n, int(config.SHARD_LAYER_ORDER if order is None else order), texture=_shard_texture())
        self._tex_px = float(self._bank.texture.width) if self._bank is not None else 64.0
        self.spawned = 0
        self.evicted = 0
        self.expired = 0
        self.hits = 0
        self.kills = 0

    @property
    def size(self) -> int:
        return len(self._slots)

    @property
    def live_count(self) -> int:
        return self._live

    def live_shards(self) -> list:
        """The live shards, oldest first. For tests and reports; the frame loop never calls it."""
        return sorted((sh for sh in self._slots if sh.live), key=lambda sh: sh.seq)

    def spawn(self, x: float, y: float, vx: float, vy: float, dmg: int, origin, rgb) -> None:
        """Start one shard at (x, y) moving (vx, vy) world units per second. The pool drops its oldest shard when full."""
        slot = None
        for sh in self._slots:
            if not sh.live:
                slot = sh
                break
        if slot is None:
            slot = self._slots[0]
            for sh in self._slots:
                if sh.seq < slot.seq:
                    slot = sh
            self.evicted += 1
            slot.live = False
            self._live -= 1
        self._seq += 1
        life = float(config.SHARD_SECONDS)
        slot.live = True
        self._live += 1
        slot.x = float(x)
        slot.y = float(y)
        slot.vx = float(vx)
        slot.vy = float(vy)
        slot.life = life
        slot.ttl = life
        slot.dmg = int(dmg)
        slot.origin = origin
        slot.seq = self._seq
        slot.rot = _streak_rotation(slot.vx, slot.vy)
        slot.r = int(rgb[0])
        slot.g = int(rgb[1])
        slot.b = int(rgb[2])
        slot.phase = (self._seq * 2.399963) % math.tau
        slot.styled = False  # the next draw writes the full style for this shard
        self.spawned += 1

    def step(self, enemies, dt: float, deal_damage, radius_of) -> int:
        """Advance every live shard by ``dt`` seconds: expire, move, and hit the first enemy its path crosses.

        ``enemies`` is the run's enemy list. ``deal_damage(enemy, amount) -> bool`` applies one hit and returns True when
        the hit killed the enemy; the callee removes and scores that enemy. ``radius_of(enemy) -> float`` gives an enemy's
        body radius. Returns the number of enemies killed in this step. The pool creates no objects here.
        """
        if self._live == 0:
            return 0
        dt = float(dt)
        shard_r = float(config.SHARD_HIT_RADIUS)
        kills = 0
        for sh in self._slots:
            if not sh.live:
                continue
            sh.ttl -= dt
            if sh.ttl <= _EXPIRE_EPS:
                self._retire(sh)
                self.expired += 1
                continue
            px = sh.x
            py = sh.y
            sh.x += sh.vx * dt
            sh.y += sh.vy * dt
            target = self._first_hit(sh, enemies, px, py, shard_r, radius_of)
            if target is not None:
                self.hits += 1
                self._retire(sh)
                if deal_damage(target, sh.dmg):
                    self.kills += 1
                    kills += 1
        return kills

    @staticmethod
    def _first_hit(sh: _Shard, enemies, px: float, py: float, shard_r: float, radius_of):
        """The first live enemy, in list order, whose body the shard's path from (px, py) to its position crosses.

        The shard's origin is skipped. Returns None when the path crosses no one.
        """
        x = sh.x
        y = sh.y
        min_x = px if px < x else x
        max_x = x if x > px else px
        min_y = py if py < y else y
        max_y = y if y > py else py
        for e in enemies:
            if e is sh.origin:
                continue
            if e.hp <= 0 or getattr(e, "_is_dead", False):
                continue
            reach = float(radius_of(e)) + shard_r
            ex = e.pos.x
            ey = e.pos.y
            if ex < min_x - reach or ex > max_x + reach or ey < min_y - reach or ey > max_y + reach:
                continue
            if _segment_point_dist_sq(ex, ey, px, py, x, y) <= reach * reach:
                return e
        return None

    def _retire(self, sh: _Shard) -> None:
        """End a live shard. Its quad stays up until the next draw hides it."""
        sh.live = False
        sh.origin = None
        self._live -= 1

    def draw(self, now: float, shake_x: float = 0.0, shake_y: float = 0.0) -> None:
        """Place and fade the live shards, and hide the slots that ended since the last draw. One GPU upload per call.

        ``now`` is run time, used only for the full-motion shimmer. ``shake_x`` and ``shake_y`` are the frame's screen
        shake in pixels, added as to_iso does. Does nothing when the pool has no bank.
        """
        bank = self._bank
        if bank is None:
            return
        reduced = motion.reduced()
        t = float(now)
        tex = self._tex_px
        dx = float(config.SHARD_STREAK_PX) / tex
        dy = float(config.SHARD_WIDTH_PX) / tex
        depth = float(config.SHARD_SHIMMER_DEPTH)
        rate = float(config.SHARD_SHIMMER_RATE)
        off_x = utils.VIEW_W * 0.5 + float(shake_x)   # read per call: utils.set_view_size changes VIEW_W at runtime
        off_y = utils.VIEW_H * 0.5 + float(shake_y)
        iso_x = config.ISO_SCALE_X
        iso_y = config.ISO_SCALE_Y
        touched = False
        for i, sh in enumerate(self._slots):
            if sh.live:
                sx = (sh.x - sh.y) * iso_x + off_x
                sy = (sh.x + sh.y) * iso_y + off_y
                fade = sh.ttl / sh.life if sh.life > 0.0 else 0.0
                fade = 0.0 if fade < 0.0 else (1.0 if fade > 1.0 else fade)
                if not reduced:
                    fade *= 1.0 - depth * 0.5 * (1.0 + math.sin(t * rate + sh.phase))
                alpha = int(255.0 * fade)
                bank.place(i, sx, sy)
                if sh.styled:
                    bank.set_alpha(i, alpha)  # size, rotation and colour were written at the first draw
                else:
                    bank.set_style(i, dx, dy, sh.rot, sh.r, sh.g, sh.b, alpha)
                    sh.styled = True
                sh.shown = True
                touched = True
            elif sh.shown:
                bank.hide(i)
                sh.shown = False
                sh.styled = False
                touched = True
        if touched:
            bank.flush()
