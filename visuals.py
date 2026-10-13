"""Visual rendering system."""

from __future__ import annotations

import functools
import math
import random
import time

import pyglet
from pyglet import shapes
from pyglet.graphics import Group

import config
import utils
from anim import Pool, clamp, tween
from config import ENEMY_COLORS, POWERUP_COLORS, SCREEN_H, SHIELD_MAX
from drone_art import DroneArt
from enemy import brute_charge_lane
from enemy_behaviors.chase import LUNGE_WINDUP_S
from enemy_behaviors.charger import Charger
from enemy_behaviors.flyer import Flyer
from event_visuals import ArenaEventFx
from glow import DashAfterimage, GlowPool, projectile_glow
from juice import SQUASH_STEP, JuiceOverlay, squash_level
from player_art import DEFAULT_PALETTE, PlayerArt
from powerup_art import make_pickup_art, place_pickup_art
from projectile_art import ProjectileVisual, ShotBank
from skin_apply import LEGACY_PALETTE, aura_outer, complete_palette
from starfield import Starfield
from utils import to_iso, Vec2, enemy_behavior_name
from anim import Pool
import motion

# Reduce group churn by bucketing depth values.
DEPTH_BUCKET = 16

# pyglet rebuilds a circle's or arc's vertices on every radius assignment, so a per-frame pulse that
# rewrites an unchanged radius is pure cost. Radii are quantised to this step (half a pixel, below what
# these rings resolve), and a shape is only written when its quantised radius changes.
RADIUS_STEP = 0.5


def _quantise_radius(value: float) -> float:
    """The radius a shape is written with: a RADIUS_STEP multiple, never zero for a positive value."""
    value = float(value)
    quantised = round(value / RADIUS_STEP) * RADIUS_STEP
    if quantised <= 0.0 < value:
        quantised = RADIUS_STEP
    return quantised


def _set_radius(shape, value: float) -> None:
    """Write a shape's radius only when its quantised value changes. Never writes zero for a positive value."""
    quantised = _quantise_radius(value)
    if getattr(shape, "_written_radius", None) == quantised:
        return
    shape._written_radius = quantised
    shape.radius = quantised


# Built Arc vertex lists for the scene rings, keyed by (ring index, quantised radius). pyglet builds an Arc's
# quads in pure Python (about 3 ms for 128 segments), and each ring's pulse only ever lands on a few dozen
# quantised radii, so every geometry is built once and copied into the vertex list after that. The list is what
# Arc._get_vertices() returns for that radius, so the drawn geometry is unchanged.
_SCENE_RING_VERTS: dict[tuple[int, float], list] = {}


def _set_scene_ring_radius(ring, index: int, value: float) -> None:
    """_set_radius for a scene ring, reusing the cached vertex list for a radius it has already built."""
    quantised = _quantise_radius(value)
    if getattr(ring, "_written_radius", None) == quantised:
        return
    ring._written_radius = quantised
    ring._radius = quantised  # what the radius setter stores before it rebuilds the vertices
    key = (index, quantised)
    verts = _SCENE_RING_VERTS.get(key)
    if verts is None:
        verts = _SCENE_RING_VERTS[key] = ring._get_vertices()
    ring._vertex_list.position[:] = verts


def _set_opacity(shape, value: int) -> None:
    """Write opacity only when it changes. Every opacity write re-uploads the shape's colour buffer."""
    if shape.opacity != value:
        shape.opacity = value


def _set_position(shape, x: float, y: float) -> None:
    """Write a shape's position in one upload, and only when it moved."""
    if shape.x != x or shape.y != y:
        shape.position = (x, y)


# Indexes of the eye shapes inside each enemy handle (see Visuals.ensure_enemy). The eye glows read them.
_EYE_SLOTS = {
    "boss_laser": (5, 6),  # eye, iris
    "bomber": (), "engineer": (), "egg_sac": (), "spitter": (), "swarm": (),
    "tank": (4,), "ranged": (4,), "charger": (4,), "flyer": (5,), "chaser": (6, 7),
}
_GENERIC_EYE_SLOTS = (3, 4)  # the default body: eye1, eye2


def _eye_slots(behavior: str) -> tuple:
    if behavior.startswith("boss_"):
        return _EYE_SLOTS.get(behavior, ())
    return _EYE_SLOTS.get(behavior, _GENERIC_EYE_SLOTS)


# ---------------------------------------------------------------- enemy animation
# Visual only. Everything below reads enemy state and draws it; none of it writes back to the enemy.
# Reduced motion (config.REDUCE_MOTION) stops the oscillators (motion.clock gives 0), skips the spawn
# ease and the death motes, and removes the hit squash. The windup tint and scale stay as a fixed pose,
# so the telegraph is still drawn.

SPAWN_TIME_S = 0.32          # enemy.t seconds over which a new enemy pops in
SPAWN_FROM_SCALE = 0.3       # body scale at spawn, eased up with out_back (a small overshoot, then settles)
WINDUP_SCALE_GAIN = 0.10     # body grows by up to this share over a windup
WINDUP_PULSE_GAIN = 0.04     # extra growth on each pulse
WINDUP_TINT_STEPS = 8        # tints are precomputed in this many steps, so a frame indexes a tuple
WINDUP_WARN_COLOUR = (255, 120, 70)
ATTACK_WINDOW_S = 0.3        # attack_cd inside this window (before the shot) reads as a windup
BRUTE_TELEGRAPH_S = 1.0      # brute_timer when its telegraph starts (enemy.py)
LASER_CHARGE_S = 0.75        # laser_timer during the laser's charge (enemy.py)
CHARGER_WINDUP_S = Charger().windup_time
FLYER_WINDUP_S = Flyer().windup_time

# Idle bob per enemy type: (angular speed rad/s, amplitude px). The original single bob is the default.
_BOB_DEFAULT = (6.0, 1.5)
_BOB = {
    "chaser": (7.5, 1.6),
    "charger": (9.0, 1.4),
    "flyer": (5.0, 3.0),
    "tank": (3.0, 1.0),
    "swarm": (11.0, 1.2),
    "bomber": (4.0, 2.2),
    "spitter": (4.5, 1.2),
    "ranged": (3.5, 0.9),
    "engineer": (5.5, 1.0),
    "egg_sac": (2.5, 1.0),
    "boss_thunder": (3.0, 2.2),
    "boss_laser": (3.0, 2.2),
    "boss_trapmaster": (3.0, 2.2),
    "boss_swarmqueen": (3.0, 2.2),
    "boss_brute": (3.0, 2.2),
}

DISSOLVE_CAP = 96            # pooled motes shared by every dying enemy; a death past the cap skips its motes
DISSOLVE_ORDER = 14500       # above enemies and projectiles (14000), below the Ultra flash (15500)
_MOTE_SEGMENTS = 6
_MOTE_DRAG = 2.5             # per-second drag on a mote's velocity
_MOTE_MAX_DT = 0.05          # a frame hitch must not fling motes across the screen


def _idle_bob(behavior: str, et: float) -> float:
    freq, amp = _BOB.get(behavior, _BOB_DEFAULT)
    return math.sin(et * freq) * amp


def _windup_ramp(remaining: float, duration: float) -> float:
    """0 when a windup has just started, 1 when its timer is about to release the attack."""
    if duration <= 0.0:
        return 1.0
    return clamp(1.0 - float(remaining) / duration, 0.0, 1.0)


def _windup_strength(enemy, behavior: str, ai: dict) -> float:
    """How far an enemy is into its attack windup, 0 to 1. Read-only: it reads the timers the AI already keeps."""
    if behavior == "chaser":
        w = float(ai.get("lunge_windup", 0.0))
        return _windup_ramp(w, LUNGE_WINDUP_S) if w > 0.0 else 0.0
    if behavior == "charger" and ai.get("state") == "WINDUP":
        return _windup_ramp(ai.get("state_timer", 0.0), CHARGER_WINDUP_S)
    if behavior == "flyer" and ai.get("state") == "WINDUP":
        return _windup_ramp(ai.get("state_timer", 0.0), FLYER_WINDUP_S)
    if behavior == "boss_brute" and ai.get("brute_state") == "telegraph":
        return _windup_ramp(ai.get("brute_timer", 0.0), BRUTE_TELEGRAPH_S)
    if behavior == "boss_laser" and ai.get("laser_state") == "charge":
        return _windup_ramp(ai.get("laser_timer", 0.0), LASER_CHARGE_S)
    if behavior == "bomber" and ai.get("bomber_exploding"):
        return 1.0
    # Ranged, spitter, engineer, tank and bomber fire when attack_cd runs out. The last moments before
    # that shot are their windup.
    cd = float(getattr(enemy, "attack_cd", 0.0))
    if 0.0 < cd <= ATTACK_WINDOW_S:
        return 1.0 - cd / ATTACK_WINDOW_S
    return 0.0


def _mix(a, b, f: float) -> tuple:
    """Colour f of the way from a to b, as an RGB tuple. Used only at enemy creation, to build tint tables."""
    return (
        int(round(a[0] + (b[0] - a[0]) * f)),
        int(round(a[1] + (b[1] - a[1]) * f)),
        int(round(a[2] + (b[2] - a[2]) * f)),
    )


@functools.lru_cache(maxsize=1024)
def _body_positions(segments: int, radius: float, level: int, anchor_x: float, anchor_y: float) -> tuple:
    """Vertex positions of a pyglet Circle at ``radius``, squashed by ``level`` (juice's SQUASH_STEP units).

    Same triangle-fan layout as pyglet's Circle._get_vertices, with the squash applied the way juice's
    hit squash applies it (width up, height down by the reciprocal, so the area holds). Level 0 is the rest
    shape. Cached on its inputs, so a radius or squash that comes back costs a lookup, not a rebuild.
    """
    s = level * SQUASH_STEP
    sx = 1.0 + s
    sy = 1.0 / sx
    x0 = -anchor_x
    y0 = -anchor_y
    step = math.tau / segments
    pts = [(x0 + radius * sx * math.cos(i * step), y0 + radius * sy * math.sin(i * step)) for i in range(segments)]
    verts: list[float] = []
    for i in range(segments):
        px, py = pts[i - 1]
        cx, cy = pts[i]
        verts.extend((x0, y0, px, py, cx, cy))
    return tuple(verts)


def _write_body(shape, pose, radius: float, level: int) -> None:
    """Draw a Circle body at ``radius`` with ``level`` squash, writing its vertices only when that changes.

    pyglet's radius setter rebuilds the circle with trigonometry on every call, so a scale that changes
    each frame pays that for every enemy. This writes a cached vertex tuple instead, and keeps the shape's
    ``radius`` in step, so pyglet's own readers still see the drawn size. Radii are quantised like
    _set_radius, so a pulse does not rewrite the body on every frame.
    """
    r = round(float(radius) / RADIUS_STEP) * RADIUS_STEP
    if r <= 0.0 < radius:
        r = RADIUS_STEP
    if pose.drawn_r == r and pose.drawn_level == level:
        return
    pose.drawn_r = r
    pose.drawn_level = level
    shape._radius = r
    if shape._visible:
        shape._vertex_list.position[:] = _body_positions(shape._segments, r, level, float(shape._anchor_x), float(shape._anchor_y))


class _EnemyPose:
    """Animation state kept beside an enemy's shapes. Built once in ensure_enemy; a frame only writes fields.

    ``body`` is the shape that scales and squashes. ``body_r`` is its rest radius. ``drawn_r``/``drawn_level``
    are what the body was last written with, so an unchanged frame writes nothing. ``warn_tints`` is the
    windup colour ramp for this enemy's base colour. ``col`` is the colour drawn last frame, which a death
    reuses for its motes. ``cx``/``cy`` is the body centre, and ``reach`` its radius, for the same reason.
    """

    __slots__ = ("body", "body_r", "drawn_r", "drawn_level", "warn_tints", "col", "cx", "cy", "reach")

    def __init__(self, body, base, cx: float, cy: float):
        self.body = body
        self.body_r = float(body.radius)
        self.drawn_r = None
        self.drawn_level = None
        self.warn_tints = tuple(_mix(base, WINDUP_WARN_COLOUR, i / float(WINDUP_TINT_STEPS)) for i in range(WINDUP_TINT_STEPS + 1))
        self.col = base
        self.cx = float(cx)
        self.cy = float(cy)
        self.reach = self.body_r


class _Mote:
    """One dissolve particle. Its shape is created once and reused through the pool."""

    __slots__ = ("shape", "x", "y", "vx", "vy", "age", "life", "r0", "alpha")

    def __init__(self, shape):
        self.shape = shape
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.age = 0.0
        self.life = 1.0
        self.r0 = 1.0
        self.alpha = -1


class _EnemyDissolve:
    """Death dissolve: a burst of pooled motes that drift out and fade.

    Motes are created lazily, up to DISSOLVE_CAP, and reused afterwards, so a burst allocates no shapes
    once the pool is warm. The motes move in real time on pyglet's clock. That clock only runs while
    motes are alive, so an idle game schedules nothing. A private RNG keeps the gameplay RNG untouched.
    """

    def __init__(self, batch):
        self._batch = batch
        self._group = Group(order=DISSOLVE_ORDER)
        self._rng = random.Random(0x0D155)
        self._pool = Pool(self._make_mote, DISSOLVE_CAP, reset=self._hide_mote)
        self._live: list[_Mote] = []
        self._armed = False

    @property
    def pool(self) -> Pool:
        return self._pool

    @property
    def live_count(self) -> int:
        return len(self._live)

    def _make_mote(self) -> _Mote:
        sh = shapes.Circle(0.0, 0.0, 2.0, segments=_MOTE_SEGMENTS, color=(255, 255, 255), batch=self._batch, group=self._group)
        sh.opacity = 0
        return _Mote(sh)

    @staticmethod
    def _hide_mote(m: _Mote) -> None:
        m.shape.opacity = 0
        m.alpha = -1

    def burst(self, x: float, y: float, color, count: int, reach: float, boost: float = 1.0) -> int:
        """Start up to ``count`` motes at (x, y). Returns how many the pool could give."""
        rng = self._rng
        started = 0
        for _ in range(int(count)):
            m = self._pool.acquire()
            if m is None:
                break
            theta = rng.uniform(0.0, math.tau)
            speed = rng.uniform(40.0, 120.0) * boost
            m.x = x + rng.uniform(-reach, reach) * 0.7
            m.y = y + rng.uniform(-reach, reach) * 0.7
            m.vx = math.cos(theta) * speed
            m.vy = math.sin(theta) * speed * 0.6 + 35.0
            m.age = 0.0
            m.life = rng.uniform(0.34, 0.55)
            m.r0 = rng.uniform(1.6, 3.4) * (1.25 if boost > 1.0 else 1.0)
            sh = m.shape
            sh.color = color
            sh.position = (m.x, m.y)
            _set_radius(sh, m.r0)
            sh.opacity = 255
            m.alpha = 255
            self._live.append(m)
            started += 1
        if started and not self._armed:
            pyglet.clock.schedule(self.tick)
            self._armed = True
        return started

    def tick(self, dt: float) -> None:
        """Advance every live mote by dt seconds. Scheduled on pyglet's clock while any mote is alive."""
        live = self._live
        if motion.reduced():
            self._pool.release_all()
            live.clear()
        dt = min(max(0.0, float(dt)), _MOTE_MAX_DT)
        i = 0
        while i < len(live):
            m = live[i]
            m.age += dt
            if m.age >= m.life:
                self._pool.release(m)
                last = live.pop()  # swap-remove keeps the list in place, with no new list per frame
                if i < len(live):
                    live[i] = last
                continue
            m.x += m.vx * dt
            m.y += m.vy * dt
            drag = 1.0 - _MOTE_DRAG * dt
            m.vx *= drag
            m.vy *= drag
            p = m.age / m.life
            sh = m.shape
            sh.position = (m.x, m.y)  # one translation write per frame, not one per axis
            _set_radius(sh, m.r0 * (1.0 - 0.6 * p))
            alpha = int(255.0 * (1.0 - p) * (1.0 - p)) & ~15  # 16 alpha steps: a colour rewrite is costly
            if alpha != m.alpha:
                sh.opacity = alpha
                m.alpha = alpha
            i += 1
        if not live and self._armed:
            pyglet.clock.unschedule(self.tick)
            self._armed = False


class GroupCache:
    """Cache for rendering groups for depth sorting."""

    def __init__(self):
        self._cache: dict[int, object] = {}

    def get(self, order: int):
        g = self._cache.get(order)
        if g is None:
            g = Group(order=order)
            self._cache[order] = g
        return g


# Shape attributes a pooled handle restores when it is taken again. Positions are included so a shape the sync
# code does not place each frame still starts where a new shape would.
_REST_ATTRS = ("x", "y", "x2", "y2", "x3", "y3", "rotation", "anchor_x", "anchor_y",
               "radius", "thickness", "width", "height", "opacity", "color")
_POOL_CAP = 4096  # per recipe; a pool that reaches it falls back to building an unpooled handle

# Enemy handles are pooled only when this is True. A pooled handle keeps its old place in the batch's vertex
# buffer, and pyglet draws same-depth-bucket shapes in buffer order, so pooling enemies changes which of two
# overlapping enemies' thin shapes draws on top. On the scripted runs of tools/bench_frames.py (waves 1, 8, 15,
# 22, 29; 600 frames each) that changed 161 of 3000 frames, by 13 to 21 pixels each. Off keeps every frame
# identical to the wave 4 base.
POOL_ENEMY_HANDLES = False
# Powerup handles, label included, follow the same rule: pooled handles keep their old buffer slots. Off by
# default. A pooled pickup skips about 3.5 ms of pyglet Label construction on each spawn.
POOL_POWERUP_HANDLES = False


def _rest_state(shape) -> dict:
    """The creation-time values of a shape's public state, read once when its handle is first built."""
    rest = {}
    for name in _REST_ATTRS:
        try:
            rest[name] = getattr(shape, name)
        except AttributeError:
            pass  # not a property on this shape type
    return rest


def _apply_rest(shape, rest: dict) -> None:
    """Put a shape back in its creation state. Only values that differ are written, so an unchanged geometry
    is not rebuilt. A radius a hit squash overwrote is rebuilt even when the radius itself is unchanged."""
    for name, value in rest.items():
        try:
            if getattr(shape, name) != value:
                setattr(shape, name, value)
        except AttributeError:
            pass  # a read-only property (a label's width, for one)
    if getattr(shape, "_juice_level", 0):
        shape._juice_level = 0
        shape.radius = shape.radius  # the squash wrote the vertices directly; the radius setter rebuilds them
    if "_written_radius" in vars(shape):
        del shape._written_radius  # the next _set_radius writes again, as it would on a new shape


def _hide_handle(h: RenderHandle) -> None:
    """Pool reset: make every shape draw nothing. Alpha 0 leaves the framebuffer as it was under the blend
    the shapes use, and it costs one colour write per shape. The handle is restored when it is next taken."""
    h.dirty = True
    for shape in h.objs:
        if shape.opacity != 0:
            shape.opacity = 0
    pose = getattr(h, "pose", None)
    if pose is not None:
        # The next life starts from rest: _write_body must write again, and the body's hit squash is undone
        # here, since the radius setter rebuilds the vertices that _write_body wrote directly.
        pose.drawn_r = None
        pose.drawn_level = None
        pose.body.radius = pose.body_r


def _make_pooled(build):
    """The factory for a recipe's pool: build a handle and capture its creation state."""
    def make():
        h = build()
        h.rest = [_rest_state(shape) for shape in h.objs]
        return h
    return make


class RenderHandle:
    """Handle for managing render objects."""

    def __init__(self, *objs):
        self.objs = list(objs)
        self._depth_order = None
        self.pool = None   # the anim.Pool that owns this handle, when it was taken from one
        self.rest = None   # each shape's creation state, captured once when a pooled handle is built
        self.dirty = False  # True once a pooled handle has been released and must be restored before reuse

    def set_group(self, group):
        if group is None:
            return
        for o in self.objs:
            o.group = group

    def set_depth(self, order: int, group_cache: GroupCache) -> None:
        if self._depth_order == order:
            return
        self._depth_order = order
        self.set_group(group_cache.get(order))

    def delete(self):
        for o in self.objs:
            if hasattr(o, "delete"):
                o.delete()


class Visuals:
    """Visual rendering system."""

    def __init__(self, batch, group_cache: GroupCache):
        self.batch = batch
        self.groups = group_cache
        self._scene_group = Group(order=-20000)
        self._projectile_group = Group(order=14000)
        self._overlay_group = Group(order=22000)
        self._flash_group = Group(order=15500)  # Ultra flash: above the particle rings (15000)

        self._enemy_handles: dict[int, RenderHandle] = {}
        self._handle_pools: dict[str, Pool] = {}  # one pool per enemy behaviour and per powerup kind
        self._proj_handles: dict[int, RenderHandle] = {}
        self._shot_bank = ShotBank(self.batch)  # projectile quads: pooled, so a new shot creates no GPU objects
        self._power_handles: dict[int, RenderHandle] = {}
        self._obstacle_handles: dict[int, RenderHandle] = {}
        self._trap_handles: dict[int, RenderHandle] = {}
        self._laser_handles: dict[int, RenderHandle] = {}
        self._thunder_handles: dict[int, RenderHandle] = {}
        self._arena_fx: ArenaEventFx | None = None  # created on the first arena event (event_visuals.py)
        self._player_handle: RenderHandle | None = None
        self._drone_art: DroneArt | None = None
        self._drone_handle: RenderHandle | None = None
        self._player_art: PlayerArt | None = None  # set when config.USE_PLAYER_ART built the character
        # Skin state, set by apply_skin(). The defaults are the default skin's look.
        self.player_palette = dict(DEFAULT_PALETTE)            # PlayerArt colours
        self.ship_palette = complete_palette(LEGACY_PALETTE)   # legacy ship colours
        self.shot_palette: dict | None = None                  # player shot colours; None keeps the weapon colours
        self._scene_stars: list[tuple[shapes.Circle, float, float, float]] = []
        self._scene_rings: list[shapes.Arc] = []
        self._vignette: list[shapes.Rectangle] = []
        self._init_scene_fx()
        self._juice = JuiceOverlay(self.batch, self._overlay_group, self._flash_group)
        # Graphics polish (glow.py, starfield.py). Pool and texture stay cheap when their switches are off.
        self._starfield = Starfield(batch, order=config.STARFIELD_LAYER_ORDER) if config.ENABLE_PARALLAX_STARS else None
        self._glow_pool = GlowPool(batch, cap=config.GLOW_POOL_CAP, order=config.GLOW_LAYER_ORDER)
        self._afterimage = DashAfterimage()
        self._dissolve = _EnemyDissolve(self.batch)  # enemy death motes (pooled, see _EnemyDissolve)

    def _init_scene_fx(self) -> None:
        self._scene_glows = [
            shapes.Circle(0, 0, 320, color=(30, 75, 130), batch=self.batch, group=self._scene_group),
            shapes.Circle(0, 0, 240, color=(160, 70, 120), batch=self.batch, group=self._scene_group),
            shapes.Circle(0, 0, 180, color=(70, 180, 165), batch=self.batch, group=self._scene_group),
        ]
        self._scene_glows[0].opacity = 28
        self._scene_glows[1].opacity = 18
        self._scene_glows[2].opacity = 16

        for i in range(3):
            ring = shapes.Arc(
                0,
                0,
                180 + i * 42,
                segments=128,
                thickness=2,
                color=(130, 185, 245),
                batch=self.batch,
                group=self._scene_group,
            )
            ring.opacity = 22 + i * 5
            self._scene_rings.append(ring)

        for _ in range(32):
            star = shapes.Circle(
                random.uniform(0.0, 1920.0),
                random.uniform(0.0, 1080.0),
                random.uniform(1.2, 2.6),
                color=(210, 235, 255),
                batch=self.batch,
                group=self._scene_group,
            )
            star.opacity = random.randint(20, 70)
            self._scene_stars.append((star, random.uniform(-8.0, 8.0), random.uniform(-5.0, 5.0), random.uniform(0.0, math.tau)))

        for _ in range(4):
            vg = shapes.Rectangle(0, 0, 1, 1, color=(0, 0, 0), batch=self.batch, group=self._overlay_group)
            vg.opacity = 0
            self._vignette.append(vg)
        self._vignette_placed = False  # sync_scene writes the bars' geometry once, on its first call

    def _take(self, key: str, build) -> RenderHandle:
        """A handle for ``key``: a released one from its pool when there is one, otherwise a new one.

        A reused handle is restored to its creation state, then its sync call places and colours it, exactly
        as it would place a new handle. ``build`` makes a new handle when the pool is empty or full.
        """
        pool = self._handle_pools.get(key)
        if pool is None:
            pool = self._handle_pools[key] = Pool(_make_pooled(build), cap=_POOL_CAP, reset=_hide_handle)
        h = pool.acquire()
        if h is None:
            return build()
        h.pool = pool
        if h.dirty:
            for shape, rest in zip(h.objs, h.rest):
                _apply_rest(shape, rest)
            h.dirty = False
        return h

    def _give_back(self, h: RenderHandle) -> None:
        """Release a handle: back to its pool when it has one, deleted otherwise."""
        if h.pool is None:
            h.delete()
        else:
            h.pool.release(h)

    def _set_depth(self, handle: RenderHandle, y: float, shake: Vec2) -> None:
        # ``y`` is the shaken screen y. Remove the frame's shake offset first so depth
        # follows the world position; otherwise a shaking screen keeps moving handles
        # across bucket boundaries and every crossing migrates them between batch groups.
        order = int((SCREEN_H + 1000 - (y - shake.y)) / DEPTH_BUCKET)
        handle.set_depth(order, self.groups)

    def sync_scene(self, t: float, shake: Vec2, combat_intensity: float = 0.0) -> None:
        ta = motion.clock(t)  # reduced motion freezes the pulses and the glow drift
        drift = motion.factor()  # star drift is multiplied by this, so it stops with reduced motion
        center_x, center_y = to_iso(Vec2(0.0, 0.0), shake)
        ci = max(0.0, min(1.0, float(combat_intensity)))

        # Every write below is skipped when the value is unchanged, and each shape that moves gets one position
        # write instead of two. Skipping a write that would store the same value leaves the same vertex data.
        offsets = ((-220.0, 120.0), (210.0, -60.0), (30.0, 190.0))
        for i, glow in enumerate(self._scene_glows):
            ox, oy = offsets[i]
            _set_position(glow, center_x + ox + math.sin(ta * (0.25 + i * 0.07)) * 30.0,
                          center_y + oy + math.cos(ta * (0.22 + i * 0.09)) * 24.0)
            _set_opacity(glow, int((14 + i * 6) + (16 + i * 4) * (0.5 + 0.5 * math.sin(ta * (0.7 + i * 0.2)))))

        for i, ring in enumerate(self._scene_rings):
            _set_position(ring, center_x, center_y)
            _set_scene_ring_radius(ring, i, (180 + i * 42) + 6.0 * math.sin(ta * (0.8 + i * 0.3)))
            _set_opacity(ring, int(16 + 10 * i + (8 + 10 * ci) * (0.5 + 0.5 * math.sin(ta * (1.1 + i * 0.15)))))

        for star, vx, vy, phase in self._scene_stars:
            x = star.x + vx * (0.22 + ci * 0.6) * drift
            y = star.y + vy * (0.22 + ci * 0.6) * drift
            if x < -24:
                x = 1944
            elif x > 1944:
                x = -24
            if y < -24:
                y = 1104
            elif y > 1104:
                y = -24
            _set_position(star, x, y)
            _set_opacity(star, int(14 + 64 * (0.5 + 0.5 * math.sin(ta * 1.4 + phase))))

        # The vignette bars never move or resize: their geometry is written on the first sync only.
        top, bot, left, right = self._vignette
        if not self._vignette_placed:
            top.x, top.y, top.width, top.height = 0, 1048, 1920, 32
            bot.x, bot.y, bot.width, bot.height = 0, 0, 1920, 32
            left.x, left.y, left.width, left.height = 0, 0, 38, 1080
            right.x, right.y, right.width, right.height = 1882, 0, 38, 1080
            self._vignette_placed = True
        v_op = int(22 + 18 * ci)
        _set_opacity(top, v_op)
        _set_opacity(bot, v_op)
        _set_opacity(left, int(v_op * 0.8))
        _set_opacity(right, int(v_op * 0.8))

    def apply_skin(self, run_skin) -> None:
        """Dress the character and the player's shots in the run's skin (skin_apply.RunSkin).

        Call before make_player(): the legacy ship reads ship_palette when it is built. The default
        skin gives wave 1's look exactly.
        """
        self.player_palette = dict(run_skin.palette)
        self.ship_palette = dict(run_skin.ship_palette)
        self.shot_palette = run_skin.shot_palette

    @property
    def player_bullet_tint(self):
        """The skin's plain-shot colour, or None for the weapon colours. A read-only view of shot_palette."""
        return None if self.shot_palette is None else self.shot_palette["bullet"]

    def trigger_ultra_flash(self, pos: Vec2, variant_color, radius: float, t: float) -> None:
        """Start the Ultra flash at a world position. It is layered over the shockwave ring."""
        self._juice.trigger_ultra_flash(pos, variant_color, radius, t)

    def sync_juice(self, t: float, shake: Vec2, player, view_w: int, view_h: int) -> None:
        """Per-frame low-health vignette and Ultra flash."""
        hp_max = max(1, int(getattr(player, "max_hp", 100)))
        hp_ratio = float(getattr(player, "hp", hp_max)) / float(hp_max)
        self._juice.sync(t, shake, hp_ratio, view_w, view_h)
    def sync_fx(self, state, player, shake: Vec2, t: float = 0.0, aim_dir: Vec2 | None = None) -> None:
        """Per-frame graphics polish, called after the other sync_* calls and before the batch draws:
        the parallax starfield (placed by the player's position and the window size) and the glows."""
        if self._starfield is not None:
            camera = player.pos if player is not None else None
            self._starfield.sync(t, float(utils.VIEW_W), float(utils.VIEW_H), camera=camera)
        self.sync_glow(state, player, shake, t=t, aim_dir=aim_dir)

    def sync_glow(self, state, player, shake: Vec2, t: float = 0.0, aim_dir: Vec2 | None = None) -> None:
        """Emit this frame's additive glows: projectile heads, pickups, enemy eyes, the player thruster
        and the dash afterimage. Call it after the other sync_* calls so the glows read final positions.
        ENABLE_GLOW and ENABLE_DASH_AFTERIMAGE switch the two groups off separately."""
        # Upload the projectile quads once, after every projectile sync this frame has run.
        self._shot_bank.flush()
        pool = self._glow_pool
        pool.begin_frame()
        if config.ENABLE_GLOW:
            for p in getattr(state, "projectiles", []):
                if id(p) not in self._proj_handles:
                    continue
                color, radius, opacity = projectile_glow(p)
                sx, sy = to_iso(p.pos, shake)
                pool.emit(("p", id(p)), sx, sy, radius, color, opacity)

            for pu in getattr(state, "powerups", []):
                h = self._power_handles.get(id(pu))
                if h is None:
                    continue
                halo = h.objs[0]  # outer ring, already in the pickup's colour
                sx, sy = to_iso(pu.pos, shake)
                pulse = 0.75 + 0.25 * math.sin(t * 4.0 + pu.pos.x * 0.03)
                pool.emit(("pu", id(pu)), sx, sy, 26.0, halo.color, int(120 * pulse))

            # Thruster and dash come before the eyes: when the pool is full, the eye glows are the ones dropped.
            if player is not None:
                sx, sy = to_iso(player.pos, shake)
                bob = math.sin(t * 6.0) * 1.5
                aim = aim_dir if (aim_dir is not None and aim_dir.length() > 1e-6) else Vec2(1.0, 0.0)
                boosting = bool(getattr(player, "is_boosting", False))
                pulse = 0.5 + 0.5 * math.sin(t * (30.0 if boosting else 15.0))
                color = (255, 180, 70) if boosting else (100, 220, 255)
                radius = (13.0 if boosting else 9.0) + 3.0 * pulse
                # Same spot sync_player draws the engine glow.
                pool.emit("thruster", sx - aim.x * 10.0, sy + bob - aim.y * 10.0, radius, color, int(120 + 100 * pulse))

        if config.ENABLE_DASH_AFTERIMAGE and player is not None:
            boosting = bool(getattr(player, "is_boosting", False))
            color = (255, 170, 70) if boosting else (150, 235, 255)
            self._afterimage.record(t, player.pos, player.dash_direction, bool(getattr(player, "is_dashing", False)), color)
            self._afterimage.emit(pool, t, shake)

        if config.ENABLE_GLOW:
            for e in getattr(state, "enemies", []):
                h = self._enemy_handles.get(id(e))
                if h is None:
                    continue
                behavior = enemy_behavior_name(e)
                slots = _eye_slots(behavior)
                if not slots:
                    continue
                body = h.objs[4 if behavior.startswith("boss_") else 1]
                radius = 9.0 if behavior == "boss_laser" else 6.0
                for idx in slots:
                    if idx < len(h.objs):
                        eye = h.objs[idx]
                        pool.emit(("eye", id(e), idx), eye.x, eye.y, radius, body.color, 140)
        pool.end_frame()

    def make_player(self):
        """Create player visual: PlayerArt when config.USE_PLAYER_ART is set, else the legacy ship."""
        if config.USE_PLAYER_ART:
            self._player_art = PlayerArt(self.batch, None)
            self._player_handle = RenderHandle(*self._player_art.shapes)
            return
        self._player_art = None
        pal = self.ship_palette
        sh = shapes.Ellipse(0, 0, 30, 12, color=(0, 0, 0), batch=self.batch)
        sh.opacity = 130

        glow = shapes.Circle(0, 0, 22, color=pal["glow"], batch=self.batch)
        glow.opacity = 65
        glow2 = shapes.Circle(0, 0, 28, color=aura_outer(pal), batch=self.batch)
        glow2.opacity = 28

        wing_color = (15, 22, 36)
        hull_color = pal["body"]
        cockpit_color = pal["accent"]

        wing = shapes.Polygon(
            (8, 0), (-12, 18), (-16, 18), (-10, 6), (-18, 8), (-18, -8), (-10, -6), (-16, -18), (-12, -18),
            color=wing_color, batch=self.batch
        )
        body = shapes.Polygon(
            (18, 0), (-4, 10), (-12, 8), (-8, 0), (-12, -8), (-4, -10),
            color=hull_color, batch=self.batch
        )
        cockpit = shapes.Polygon(
            (10, 0), (2, 4), (-6, 3), (-6, -3), (2, -4),
            color=cockpit_color, batch=self.batch
        )
        engine_glow = shapes.Circle(0, 0, 4, color=(100, 220, 255), batch=self.batch)
        engine_glow.opacity = 200

        # Thrusters
        thruster_l = shapes.Line(0, 0, 0, 0, thickness=4, color=pal["trail"], batch=self.batch)
        thruster_r = shapes.Line(0, 0, 0, 0, thickness=4, color=pal["trail"], batch=self.batch)
        thruster_l.opacity = 0
        thruster_r.opacity = 0

        # Gun barrel
        gun = shapes.Line(0, 0, 0, 0, thickness=3, color=(230, 230, 240), batch=self.batch)
        gun.opacity = 210
        gun_core = shapes.Line(0, 0, 0, 0, thickness=1, color=pal["eye"], batch=self.batch)
        gun_core.opacity = 220

        shield_ring = shapes.Arc(0, 0, 19, segments=48, thickness=4, color=(120, 220, 255), batch=self.batch)
        shield_ring.opacity = 0
        shield_ring2 = shapes.Arc(0, 0, 24, segments=48, thickness=2, color=(255, 255, 255), batch=self.batch)
        shield_ring2.opacity = 0
        laser_ring = shapes.Arc(0, 0, 22, segments=64, thickness=3, color=(255, 120, 255), batch=self.batch)
        laser_ring.opacity = 0
        boost_ring = shapes.Arc(0, 0, 26, segments=48, thickness=3, color=(255, 145, 45), batch=self.batch)
        boost_ring.opacity = 0

        self._player_handle = RenderHandle(
            sh, glow, glow2, shield_ring2, shield_ring, laser_ring, boost_ring,
            wing, body, cockpit, engine_glow,
            gun, gun_core, thruster_l, thruster_r
        )

    def sync_player(self, player, shake: Vec2, t: float = 0.0, aim_dir: Vec2 | None = None):
        """Update player visual position."""
        # Rebuild if config.USE_PLAYER_ART changed since the last build, so the flag switches paths at runtime.
        if self._player_handle is None or (self._player_art is not None) != bool(config.USE_PLAYER_ART):
            if self._player_handle is not None:
                self._player_handle.delete()
            self._player_handle = None
            self.make_player()
        ta = motion.clock(t)  # visual pulses only; the laser check below keeps the real time
        if self._player_art is not None:
            # PlayerArt scales its own idle pulses with motion.clock, and needs the game clock for dashes and
            # the laser. real_t is wall time, so the death dissolve runs even though the game clock stops at game over.
            self._player_art.sync(player, shake, t=t, aim_dir=aim_dir, palette=self.player_palette,
                                  real_t=time.perf_counter())
            # Depth follows the ground point. The body bobs and recoils, so sorting by its y would move the
            # handle across depth buckets on every bob near an edge, and each move migrates the handle's shapes.
            self._set_depth(self._player_handle, self._player_art.ground_y, shake)
            return
        assert self._player_handle is not None
        (
            sh, glow, glow2, shield_ring2, shield_ring, laser_ring, boost_ring,
            wing, body, cockpit, engine_glow,
            gun, gun_core, thruster_l, thruster_r
        ) = self._player_handle.objs
        sx, sy = to_iso(player.pos, shake)
        if aim_dir is None or aim_dir.length() <= 1e-6:
            aim_dir = Vec2(1, 0)
        bob = math.sin(ta * 6.0) * 1.5
        
        angle = -math.degrees(math.atan2(aim_dir.y, aim_dir.x))
        
        cx = sx
        cy = sy + bob
        
        sh.x, sh.y = sx, sy - 19
        glow.x, glow.y = cx, cy
        glow2.x, glow2.y = cx, cy + 1

        is_dashing = bool(getattr(player, "is_dashing", False))
        is_boosting = bool(getattr(player, "is_boosting", False))
        is_flashing = float(getattr(player, "damage_flash_timer", 0.0)) > 0

        if is_flashing:
            hull = (255, 120, 120)
        elif is_boosting:
            hull = (255, 215, 130)
        elif getattr(player, "invincibility_timer", 0) > 0:
            hull = (255, 236, 160)
        else:
            hull = self.ship_palette["body"]
        body.color = hull
        
        for part in (wing, body, cockpit):
            part.x, part.y = cx, cy
            part.rotation = angle
            
        bx = cx - aim_dir.x * 10
        by = cy - aim_dir.y * 10
        engine_glow.x, engine_glow.y = bx, by
            
        engine_pulse = 0.7 + 0.3 * math.sin(ta * (30.0 if is_boosting else 15.0))
        engine_glow.color = (255, 180, 70) if is_boosting else (100, 220, 255)
        engine_glow.opacity = int(255 * engine_pulse)

        # Aim direction affects gun orientation.
        gun_len = 18
        gx = cx + aim_dir.x * 8
        gy = cy + aim_dir.y * 4
        gun.x, gun.y = gx, gy
        gun.x2, gun.y2 = gx + aim_dir.x * gun_len, gy + aim_dir.y * gun_len * 0.65
        gun_core.x, gun_core.y = gun.x, gun.y
        gun_core.x2, gun_core.y2 = gun.x2, gun.y2

        back = Vec2(-aim_dir.x, -aim_dir.y)
        tx1, ty1 = cx - aim_dir.y * 4 - aim_dir.x * 9, cy + aim_dir.x * 4 - aim_dir.y * 9
        tx2, ty2 = cx + aim_dir.y * 4 - aim_dir.x * 9, cy - aim_dir.x * 4 - aim_dir.y * 9

        if is_dashing or is_boosting:
            pulse = 0.7 + 0.3 * math.sin(ta * 45.0)
            jet_len = (26.0 if is_boosting else 22.0) + 12.0 * pulse
            thruster_l.x, thruster_l.y = tx1, ty1
            thruster_l.x2, thruster_l.y2 = tx1 + back.x * jet_len, ty1 + back.y * (jet_len * 0.6)
            thruster_r.x, thruster_r.y = tx2, ty2
            thruster_r.x2, thruster_r.y2 = tx2 + back.x * (jet_len * 0.85), ty2 + back.y * (jet_len * 0.5)
            jet_color = (255, 170, 70) if is_boosting else self.ship_palette["trail"]
            thruster_l.color = jet_color
            thruster_r.color = jet_color
            thruster_l.opacity = int(140 + 110 * pulse)
            thruster_r.opacity = int(110 + 100 * pulse)
        else:
            # Active movement idle thruster
            idle_pulse = 0.5 + 0.5 * math.sin(ta * 18.0)
            jet_len = 10.0 + 4.0 * idle_pulse
            thruster_l.x, thruster_l.y = tx1, ty1
            thruster_l.x2, thruster_l.y2 = tx1 + back.x * jet_len, ty1 + back.y * (jet_len * 0.6)
            thruster_r.x, thruster_r.y = tx2, ty2
            thruster_r.x2, thruster_r.y2 = tx2 + back.x * jet_len, ty2 + back.y * (jet_len * 0.5)
            thruster_l.color = self.ship_palette["trail"]
            thruster_r.color = self.ship_palette["trail"]
            thruster_l.opacity = int(60 + 40 * idle_pulse)
            thruster_r.opacity = int(50 + 35 * idle_pulse)

        # Boost overdrive aura
        if is_boosting:
            bpulse = 0.65 + 0.35 * math.sin(ta * 22.0)
            boost_ring.x, boost_ring.y = cx, cy
            _set_radius(boost_ring, 26 + 3.0 * bpulse)
            boost_ring.opacity = int(140 + 80 * bpulse)
        else:
            boost_ring.opacity = 0

        # Shield aura
        if getattr(player, "shield", 0) > 0:
            pulse = 0.65 + 0.35 * math.sin(ta * 6.5)
            shield_ring.x, shield_ring.y = cx, cy
            shield_ring2.x, shield_ring2.y = cx, cy
            _set_radius(shield_ring, 18 + 2.0 * pulse)
            _set_radius(shield_ring2, 24 + 3.0 * pulse)
            shield_ring.opacity = int(90 + min(SHIELD_MAX, player.shield) * 1.0 * pulse)
            shield_ring2.opacity = int(60 + min(SHIELD_MAX, player.shield) * 0.5 * pulse)
        else:
            shield_ring.opacity = 0
            shield_ring2.opacity = 0

        # Laser aura
        if getattr(player, "laser_until", 0.0) > t:
            pulse = 0.6 + 0.4 * math.sin(ta * 10.0)
            laser_ring.x, laser_ring.y = cx, cy
            _set_radius(laser_ring, 22 + 3.0 * pulse)
            laser_ring.opacity = int(160 * pulse)
        else:
            laser_ring.opacity = 0

        self._set_depth(self._player_handle, cy, shake)

    def sync_drone(self, drone, shake: Vec2, t: float = 0.0) -> None:
        """Draw the deployed drone companion. Its shapes are created on first use and hidden while no drone is out."""
        if self._drone_art is None:
            self._drone_art = DroneArt(self.batch)
            self._drone_handle = RenderHandle(*self._drone_art.parts)
        cy = self._drone_art.sync(drone, shake, t)
        if drone.active:
            self._set_depth(self._drone_handle, cy, shake)

    def ensure_enemy(self, enemy):
        """Ensure enemy visual exists, with the pose that drives its spawn-in, windup and dissolve.
        With POOL_ENEMY_HANDLES the handle comes from its behaviour's pool."""
        if id(enemy) in self._enemy_handles:
            return
        behavior = enemy_behavior_name(enemy)
        if POOL_ENEMY_HANDLES:
            h = self._take("enemy:" + behavior, lambda: self._build_enemy(behavior))
        else:
            h = self._build_enemy(behavior)
        cx, cy = to_iso(enemy.pos, Vec2(0.0, 0.0))  # the death motes start here until the first sync
        h.pose.cx = float(cx)
        h.pose.cy = float(cy)
        self._enemy_handles[id(enemy)] = h

    def _build_enemy(self, behavior: str) -> RenderHandle:
        """Create one enemy's shapes and the pose that animates them. ensure_enemy hands them out through the pool."""
        base = ENEMY_COLORS.get(behavior, (200, 120, 120))
        h = self._build_enemy_shapes(behavior, base)
        body = h.objs[4 if behavior.startswith("boss_") else 1]
        h.pose = _EnemyPose(body, base, 0.0, 0.0)
        return h

    def _build_enemy_shapes(self, behavior: str, base) -> RenderHandle:
        """Create the shapes for one enemy type and return its handle (see _build_enemy)."""
        sh = shapes.Ellipse(0, 0, 20, 7, color=(0, 0, 0), batch=self.batch)
        sh.opacity = 110

        if behavior.startswith("boss_"):
            sh.width = 40
            sh.height = 14
            body = shapes.Circle(0, 0, 22, color=base, batch=self.batch)
            glow = shapes.Circle(0, 0, 30, color=base, batch=self.batch)
            glow.opacity = 45
            ring = shapes.Arc(0, 0, 28, segments=64, thickness=6, color=(20, 25, 40), batch=self.batch)
            ring.opacity = 220
            crown = shapes.Arc(0, 0, 24, segments=32, thickness=4, color=(255, 255, 255), batch=self.batch)
            crown.opacity = 60

            if behavior == "boss_thunder":
                sig = shapes.Line(0, 0, 0, 0, thickness=3, color=(200, 230, 255), batch=self.batch)
                sig.opacity = 220
                return RenderHandle(sh, glow, ring, crown, body, sig)
            elif behavior == "boss_laser":
                eye = shapes.Circle(0, 0, 6, color=(255, 255, 255), batch=self.batch)
                eye.opacity = 200
                iris = shapes.Circle(0, 0, 3, color=(255, 120, 255), batch=self.batch)
                iris.opacity = 220
                return RenderHandle(sh, glow, ring, crown, body, eye, iris)
            elif behavior == "boss_trapmaster":
                gear = shapes.Arc(0, 0, 26, segments=32, thickness=5, color=(255, 210, 120), batch=self.batch)
                gear.opacity = 120
                return RenderHandle(sh, glow, ring, crown, body, gear)
            elif behavior == "boss_swarmqueen":
                orb1 = shapes.Circle(0, 0, 6, color=(255, 255, 255), batch=self.batch)
                orb2 = shapes.Circle(0, 0, 6, color=(255, 255, 255), batch=self.batch)
                orb3 = shapes.Circle(0, 0, 6, color=(255, 255, 255), batch=self.batch)
                orb1.opacity = 90
                orb2.opacity = 90
                orb3.opacity = 90
                return RenderHandle(sh, glow, ring, crown, body, orb1, orb2, orb3)
            elif behavior == "boss_brute":
                horn = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(255, 250, 240), batch=self.batch)
                horn.opacity = 220
                scar = shapes.Line(0, 0, 0, 0, thickness=4, color=(40, 10, 10), batch=self.batch)
                scar.opacity = 200
                # Charge lane: hidden except while the brute telegraphs its charge. Kept last so body_idx stays 4.
                lane = shapes.Line(0, 0, 0, 0, thickness=4, color=(255, 70, 70), batch=self.batch)
                lane.opacity = 0
                return RenderHandle(sh, glow, ring, crown, body, horn, scar, lane)
            else:
                return RenderHandle(sh, glow, ring, crown, body)

        if behavior == "bomber":
            body = shapes.Circle(0, 0, 14, color=base, batch=self.batch)
            core = shapes.Circle(0, 0, 8, color=(255, 255, 255), batch=self.batch)
            core.opacity = 200
            # Orbiting fuse spark
            fuse = shapes.Circle(0, 0, 3, color=(255, 200, 60), batch=self.batch)
            fuse.opacity = 220
            fuse_trail = shapes.Arc(0, 0, 16, segments=20, thickness=2, color=(255, 180, 80), batch=self.batch)
            fuse_trail.opacity = 60
            return RenderHandle(sh, body, core, fuse, fuse_trail)

        if behavior == "tank":
            sh.width = 28
            sh.height = 10
            body = shapes.Circle(0, 0, 16, color=base, batch=self.batch)
            armor = shapes.Arc(0, 0, 18, segments=40, thickness=5, color=(30, 40, 55), batch=self.batch)
            armor.opacity = 220
            plate = shapes.Rectangle(0, 0, 18, 10, color=(45, 70, 65), batch=self.batch)
            plate.anchor_x = 9
            plate.anchor_y = 5
            plate.opacity = 220
            eye = shapes.Circle(0, 0, 3, color=(20, 20, 20), batch=self.batch)
            # Rotating outer shield ring
            shield_ring = shapes.Arc(0, 0, 22, segments=24, thickness=3, color=(80, 180, 80), batch=self.batch)
            shield_ring.opacity = 70
            return RenderHandle(sh, body, armor, plate, eye, shield_ring)

        if behavior == "ranged":
            body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
            cannon = shapes.Rectangle(0, 0, 18, 6, color=(30, 40, 55), batch=self.batch)
            cannon.anchor_x = 4
            cannon.anchor_y = 3
            cannon.opacity = 230
            muzzle = shapes.Circle(0, 0, 3, color=(255, 255, 255), batch=self.batch)
            muzzle.opacity = 160
            eye = shapes.Circle(0, 0, 2.5, color=(20, 20, 20), batch=self.batch)
            # Scope crosshair lines
            scope_h = shapes.Line(0, 0, 0, 0, thickness=1, color=(180, 220, 255), batch=self.batch)
            scope_v = shapes.Line(0, 0, 0, 0, thickness=1, color=(180, 220, 255), batch=self.batch)
            scope_h.opacity = 100
            scope_v.opacity = 100
            return RenderHandle(sh, body, cannon, muzzle, eye, scope_h, scope_v)

        if behavior == "charger":
            body = shapes.Circle(0, 0, 13, color=base, batch=self.batch)
            horn1 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 240, 220), batch=self.batch)
            horn2 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 240, 220), batch=self.batch)
            horn1.opacity = 220
            horn2.opacity = 220
            eye = shapes.Circle(0, 0, 2.5, color=(20, 20, 20), batch=self.batch)
            # Speed trail lines
            trail1 = shapes.Line(0, 0, 0, 0, thickness=2, color=(255, 200, 100), batch=self.batch)
            trail2 = shapes.Line(0, 0, 0, 0, thickness=2, color=(255, 200, 100), batch=self.batch)
            trail1.opacity = 0
            trail2.opacity = 0
            return RenderHandle(sh, body, horn1, horn2, eye, trail1, trail2)

        if behavior == "flyer":
            body = shapes.Circle(0, 0, 11, color=base, batch=self.batch)
            wing1 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=base, batch=self.batch)
            wing2 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=base, batch=self.batch)
            wing1.opacity = 170
            wing2.opacity = 170
            tail = shapes.Line(0, 0, 0, 0, thickness=2, color=(230, 230, 240), batch=self.batch)
            tail.opacity = 200
            eye = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
            # Jet trail
            jet = shapes.Line(0, 0, 0, 0, thickness=3, color=(150, 200, 255), batch=self.batch)
            jet.opacity = 90
            return RenderHandle(sh, body, wing1, wing2, tail, eye, jet)

        if behavior == "spitter":
            body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
            sac1 = shapes.Circle(0, 0, 5, color=(255, 240, 170), batch=self.batch)
            sac2 = shapes.Circle(0, 0, 4, color=(255, 240, 170), batch=self.batch)
            sac1.opacity = 160
            sac2.opacity = 140
            mouth = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(30, 30, 30), batch=self.batch)
            mouth.opacity = 210
            # Pulsing acid glow
            acid_glow = shapes.Circle(0, 0, 16, color=(180, 255, 80), batch=self.batch)
            acid_glow.opacity = 25
            return RenderHandle(sh, body, sac1, sac2, mouth, acid_glow)

        if behavior == "swarm":
            sh.width = 16
            sh.height = 6
            body = shapes.Circle(0, 0, 9, color=base, batch=self.batch)
            dot1 = shapes.Circle(0, 0, 2.5, color=(255, 255, 255), batch=self.batch)
            dot2 = shapes.Circle(0, 0, 2.5, color=(255, 255, 255), batch=self.batch)
            dot3 = shapes.Circle(0, 0, 2.5, color=(255, 255, 255), batch=self.batch)
            dot1.opacity = 120
            dot2.opacity = 120
            dot3.opacity = 120
            # Flickering antenna lines
            ant1 = shapes.Line(0, 0, 0, 0, thickness=1, color=(255, 200, 255), batch=self.batch)
            ant2 = shapes.Line(0, 0, 0, 0, thickness=1, color=(255, 200, 255), batch=self.batch)
            ant1.opacity = 110
            ant2.opacity = 110
            return RenderHandle(sh, body, dot1, dot2, dot3, ant1, ant2)

        if behavior == "chaser":
            body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
            # Pulsing aura ring
            aura = shapes.Arc(0, 0, 18, segments=32, thickness=2, color=base, batch=self.batch)
            aura.opacity = 50
            spike1 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 250, 250), batch=self.batch)
            spike2 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 250, 250), batch=self.batch)
            spike3 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(250, 250, 250), batch=self.batch)
            spike1.opacity = 160
            spike2.opacity = 160
            spike3.opacity = 160
            eye1 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
            eye2 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
            return RenderHandle(sh, body, aura, spike1, spike2, spike3, eye1, eye2)

        if behavior == "engineer":
            body = shapes.Circle(0, 0, 13, color=base, batch=self.batch)
            backpack = shapes.Rectangle(0, 0, 12, 10, color=(40, 60, 70), batch=self.batch)
            backpack.anchor_x = 6
            backpack.anchor_y = 5
            backpack.opacity = 220
            visor = shapes.Rectangle(0, 0, 10, 4, color=(230, 255, 245), batch=self.batch)
            visor.anchor_x = 5
            visor.anchor_y = 2
            visor.opacity = 210
            tool = shapes.Line(0, 0, 10, 10, thickness=2, color=(240, 240, 240), batch=self.batch)
            tool2 = shapes.Line(0, 0, 10, -10, thickness=2, color=(240, 240, 240), batch=self.batch)
            # Rotating gear arc
            gear = shapes.Arc(0, 0, 17, segments=16, thickness=2, color=(80, 240, 180), batch=self.batch)
            gear.opacity = 60
            return RenderHandle(sh, body, backpack, visor, tool, tool2, gear)

        if behavior == "egg_sac":
            # Organic pulsating sac
            sh.width = 18
            sh.height = 8
            body = shapes.Circle(0, 0, 15, color=(200, 180, 190), batch=self.batch)
            vein1 = shapes.Arc(0, 0, 14, segments=16, thickness=2, color=(160, 60, 80), batch=self.batch)
            vein1.opacity = 140
            vein2 = shapes.Arc(0, 0, 10, segments=16, thickness=2, color=(160, 60, 80), batch=self.batch)
            vein2.rotation = 90
            vein2.opacity = 140
            core = shapes.Circle(0, 0, 6, color=(255, 100, 120), batch=self.batch)
            core.opacity = 180
            return RenderHandle(sh, body, vein1, vein2, core)

        body = shapes.Circle(0, 0, 12, color=base, batch=self.batch)
        shine = shapes.Circle(0, 0, 7, color=(255, 255, 255), batch=self.batch)
        shine.opacity = 60
        eye1 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
        eye2 = shapes.Circle(0, 0, 2, color=(20, 20, 20), batch=self.batch)
        return RenderHandle(sh, body, shine, eye1, eye2)

    def sync_enemy(self, enemy, shake: Vec2):
        """Update enemy visual position."""
        et = motion.clock(enemy.t)  # every enemy animation reads this, so reduced motion freezes it
        h = self._enemy_handles[id(enemy)]
        pose = h.pose
        ai = getattr(enemy, "ai", None) or {}
        behavior = enemy_behavior_name(enemy)
        base = ENEMY_COLORS.get(behavior, (200, 120, 120))
        sx, sy = to_iso(enemy.pos, shake)
        bob = _idle_bob(behavior, et)

        # Egg sacs breathe, so their body's nominal radius follows the same pulse their veins and core use.
        if behavior == "egg_sac":
            pulse = 0.8 + 0.2 * math.sin(et * 8.0)
            if ai.get("hatch_timer", 0) < 1.0:
                pulse = 0.8 + 0.3 * math.sin(et * 18.0)  # fast pulse before hatching
            nominal = max(0.1, 15 * pulse)
        else:
            nominal = pose.body_r

        # Spawn-in: the body eases up from SPAWN_FROM_SCALE over SPAWN_TIME_S of enemy time (gameplay time, so
        # a paused or slowed frame does not pop it early). Reduced motion skips the ease.
        k_spawn = 1.0
        if enemy.t < SPAWN_TIME_S and not motion.reduced():
            k_spawn = tween(SPAWN_FROM_SCALE, 1.0, clamp(float(enemy.t) / SPAWN_TIME_S, 0.0, 1.0), "out_back")

        # Attack windup: a scale swell and a warning tint that grow as the attack nears. The tint and the
        # scale stay on the body under reduced motion (only the pulse is removed), so the telegraph reads.
        windup = _windup_strength(enemy, behavior, ai)
        k_wind = 1.0
        warn_idx = 0
        if windup > 0.0:
            wpulse = 0.5 + 0.5 * math.sin(et * 18.0)  # et is 0 under reduced motion, so this holds at 0.5
            k_wind = 1.0 + WINDUP_SCALE_GAIN * windup + WINDUP_PULSE_GAIN * windup * wpulse
            warn_idx = int((windup * (0.45 + 0.25 * wpulse)) * WINDUP_TINT_STEPS + 0.5)

        # Hit flash & elite visual feedback. A hit always flashes white, and a windup tints the body.
        is_flashing = float(getattr(enemy, "hit_flash_timer", 0.0)) > 0
        is_elite = bool(getattr(enemy, "is_elite", False))
        if is_flashing:
            render_col = (255, 255, 255)
        elif windup > 0.0:
            render_col = pose.warn_tints[warn_idx]
        elif is_elite:
            render_col = (255, 215, 75)
        else:
            render_col = base
        if not is_flashing:
            pose.col = render_col  # a death's motes take the body's colour, not the white hit flash
        pose.cx = sx
        pose.cy = sy + bob
        pose.reach = nominal

        body_idx = 4 if behavior.startswith("boss_") else 1
        if len(h.objs) > body_idx:
            body_obj = h.objs[body_idx]
            # body.color is RGBA and render_col is RGB, so compare the channels or every body is rewritten each frame.
            if hasattr(body_obj, "color") and body_obj.color[:3] != render_col:
                body_obj.color = render_col
            # Hit reaction: the squash level is juice's own curve over hit_flash_timer, so it springs back to rest.
            # Reduced motion passes a zero timer. The radius (spawn and windup scale) and the squash share one
            # cached vertex write, see _write_body.
            hit_t = float(getattr(enemy, "hit_flash_timer", 0.0))
            level = squash_level(hit_t * motion.factor()) if hit_t > 0.0 else 0
            _write_body(body_obj, pose, nominal * k_spawn * k_wind, level)

        if behavior.startswith("boss_"):
            sh = h.objs[0]
            sh.x, sh.y = sx, sy - 26

            if behavior == "boss_thunder":
                sh, glow, ring, crown, body, sig = h.objs
                sig.x, sig.y = sx - 10, sy + 20 + bob
                sig.x2, sig.y2 = sx + 10, sy + 10 + bob
            elif behavior == "boss_laser":
                sh, glow, ring, crown, body, eye, iris = h.objs
                eye.x, eye.y = sx + 6, sy + 8 + bob
                iris.x, iris.y = sx + 6 + 2.0 * math.sin(et * 9.0), sy + 8 + bob
            elif behavior == "boss_trapmaster":
                sh, glow, ring, crown, body, gear = h.objs
                gear.x, gear.y = sx, sy + bob
                _set_radius(gear, 26 + 1.5 * math.sin(et * 3.2))
            elif behavior == "boss_swarmqueen":
                sh, glow, ring, crown, body, orb1, orb2, orb3 = h.objs
                r = 20
                orb1.x, orb1.y = sx + math.cos(et * 2.2) * r, sy + bob + math.sin(et * 2.2) * r
                orb2.x, orb2.y = sx + math.cos(et * 2.2 + 2.1) * r, sy + bob + math.sin(et * 2.2 + 2.1) * r
                orb3.x, orb3.y = sx + math.cos(et * 2.2 + 4.2) * r, sy + bob + math.sin(et * 2.2 + 4.2) * r
            elif behavior == "boss_brute":
                sh, glow, ring, crown, body, horn, scar, lane = h.objs
                horn.x, horn.y = sx, sy + bob + 26
                horn.x2, horn.y2 = sx + 18, sy + bob + 16
                horn.x3, horn.y3 = sx - 18, sy + bob + 16
                scar.x, scar.y, scar.x2, scar.y2 = sx - 10, sy + bob + 2, sx + 10, sy + bob - 6
                lane_geom = brute_charge_lane(enemy)
                if lane_geom is None:
                    lane.opacity = 0
                else:
                    lane_dir, lane_len = lane_geom
                    lx, ly = to_iso(enemy.pos + lane_dir * lane_len, shake)
                    lane.x, lane.y, lane.x2, lane.y2 = sx, sy, lx, ly
                    lane.opacity = int(145 + 55 * math.sin(et * 10.0))
            else:
                sh, glow, ring, crown, body = h.objs

            glow.x, glow.y = sx, sy + bob
            ring.x, ring.y = sx, sy + bob
            crown.x, crown.y = sx, sy + bob
            body.x, body.y = sx, sy + bob
            _set_radius(crown, 24 + 2.0 * (0.5 + 0.5 * math.sin(et * 4.0)))

            self._set_depth(h, sy, shake)
            return

        if behavior == "bomber":
            sh, body, core, fuse, fuse_trail = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            core.x, core.y = sx, sy + bob
            fuse_trail.x, fuse_trail.y = sx, sy + bob
            exploding = bool(getattr(enemy, "ai", {}).get("bomber_exploding", False))
            if exploding:
                pulse = 0.5 + 0.5 * math.sin(et * 30)
                _set_radius(core, 8 + 4 * pulse)
                core.opacity = 255
                fuse_speed = 18.0
            else:
                _set_radius(core, 8)
                core.opacity = 200
                fuse_speed = 4.0
            # Fuse spark orbits the body
            fr = 16
            fuse.x = sx + math.cos(et * fuse_speed) * fr
            fuse.y = sy + bob + math.sin(et * fuse_speed) * fr
            fuse.opacity = 160 + int(95 * (0.5 + 0.5 * math.sin(et * 12.0)))
            self._set_depth(h, sy, shake)
            return

        if behavior == "engineer":
            sh, body, backpack, visor, tool, tool2, gear = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            backpack.x, backpack.y = sx - 12, sy + 2 + bob
            visor.x, visor.y = sx + 1, sy + 2 + bob
            tool.x, tool.y, tool.x2, tool.y2 = sx + 10, sy + 6 + bob, sx + 16, sy + 0 + bob
            tool2.x, tool2.y, tool2.x2, tool2.y2 = sx + 10, sy + 6 + bob, sx + 16, sy + 12 + bob
            # Rotating gear arc
            gear.x, gear.y = sx - 12, sy + 2 + bob
            _set_radius(gear, 17 + 1.5 * math.sin(et * 5.0))
            gear.opacity = 40 + int(30 * (0.5 + 0.5 * math.sin(et * 3.0)))
            self._set_depth(h, sy, shake)
            return

        if behavior == "egg_sac":
            sh, body, vein1, vein2, core = h.objs
            sh.x, sh.y = sx, sy - 18
            
            # The heartbeat pulse is computed above; the body's radius comes from the pose (nominal above).
            body.x, body.y = sx, sy + bob

            vein1.x, vein1.y = sx, sy + bob
            _set_radius(vein1, max(0.1, 14 * pulse))
            
            vein2.x, vein2.y = sx, sy + bob
            _set_radius(vein2, max(0.1, 10 * pulse))

            core.x, core.y = sx, sy + bob
            _set_radius(core, max(0.1, 6 * pulse + 2 * math.sin(et * 12.0)))
            
            self._set_depth(h, sy, shake)
            return

        if behavior == "tank":
            sh, body, armor, plate, eye, shield_ring = h.objs
            sh.x, sh.y = sx, sy - 19
            body.x, body.y = sx, sy + bob * 0.4
            armor.x, armor.y = sx, sy + bob * 0.4
            plate.x, plate.y = sx + 8, sy + 1 + bob * 0.4
            eye.x, eye.y = sx + 6, sy + 2 + bob * 0.4
            # Rotating shield ring
            shield_ring.x, shield_ring.y = sx, sy + bob * 0.4
            _set_radius(shield_ring, 22 + 1.0 * math.sin(et * 2.0))
            shield_ring.opacity = 50 + int(30 * (0.5 + 0.5 * math.sin(et * 1.5)))
            self._set_depth(h, sy, shake)
            return

        if behavior == "ranged":
            sh, body, cannon, muzzle, eye, scope_h, scope_v = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            cannon.x, cannon.y = sx + 6, sy + 2 + bob
            muzzle.x, muzzle.y = sx + 18, sy + 2 + bob
            eye.x, eye.y = sx + 1, sy + 2 + bob
            # Scope crosshairs rotate slowly
            sr = 20
            sa = et * 1.2
            scope_h.x, scope_h.y = sx + 18 - math.cos(sa) * sr, sy + 2 + bob
            scope_h.x2, scope_h.y2 = sx + 18 + math.cos(sa) * sr, sy + 2 + bob
            scope_v.x, scope_v.y = sx + 18, sy + 2 + bob - math.sin(sa) * sr
            scope_v.x2, scope_v.y2 = sx + 18, sy + 2 + bob + math.sin(sa) * sr
            scope_h.opacity = 60 + int(40 * (0.5 + 0.5 * math.sin(et * 3.0)))
            scope_v.opacity = scope_h.opacity
            self._set_depth(h, sy, shake)
            return

        if behavior == "charger":
            sh, body, horn1, horn2, eye, trail1, trail2 = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            # Horns
            horn1.x, horn1.y = sx + 2, sy + 16 + bob
            horn1.x2, horn1.y2 = sx + 12, sy + 10 + bob
            horn1.x3, horn1.y3 = sx + 6, sy + 4 + bob
            horn2.x, horn2.y = sx - 2, sy + 16 + bob
            horn2.x2, horn2.y2 = sx - 12, sy + 10 + bob
            horn2.x3, horn2.y3 = sx - 6, sy + 4 + bob
            eye.x, eye.y = sx + 2, sy + 2 + bob
            # Speed trails — visible when charging
            is_charging = bool(getattr(enemy, "ai", {}).get("charger_dashing", False))
            if is_charging:
                trail1.x, trail1.y = sx - 12, sy + 6 + bob
                trail1.x2, trail1.y2 = sx - 32, sy + 10 + bob
                trail2.x, trail2.y = sx - 12, sy - 2 + bob
                trail2.x2, trail2.y2 = sx - 32, sy + 2 + bob
                trail1.opacity = 140
                trail2.opacity = 110
            else:
                trail1.opacity = 0
                trail2.opacity = 0
            self._set_depth(h, sy, shake)
            return

        if behavior == "flyer":
            sh, body, wing1, wing2, tail, eye, jet = h.objs
            sh.x, sh.y = sx, sy - 17
            body.x, body.y = sx, sy + bob
            flap = 6 + 4 * math.sin(et * 10.0)
            wing1.x, wing1.y = sx, sy + bob + 6
            wing1.x2, wing1.y2 = sx + 22, sy + bob + flap
            wing1.x3, wing1.y3 = sx + 10, sy + bob - 2
            wing2.x, wing2.y = sx, sy + bob + 6
            wing2.x2, wing2.y2 = sx - 22, sy + bob + flap
            wing2.x3, wing2.y3 = sx - 10, sy + bob - 2
            tail.x, tail.y, tail.x2, tail.y2 = sx - 3, sy + bob - 6, sx - 14, sy + bob - 14
            eye.x, eye.y = sx + 2, sy + bob + 2
            # Jet trail behind
            jet.x, jet.y = sx - 4, sy + bob - 4
            jet.x2, jet.y2 = sx - 18, sy + bob - 16
            jet.opacity = 50 + int(40 * (0.5 + 0.5 * math.sin(et * 8.0)))
            self._set_depth(h, sy, shake)
            return

        if behavior == "spitter":
            sh, body, sac1, sac2, mouth, acid_glow = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            sac1.x, sac1.y = sx - 9, sy + 2 + bob
            sac2.x, sac2.y = sx + 8, sy + 4 + bob
            mouth.x, mouth.y = sx + 8, sy + bob
            mouth.x2, mouth.y2 = sx + 18, sy + 4 + bob
            mouth.x3, mouth.y3 = sx + 18, sy - 4 + bob
            # Pulsing acid glow
            acid_glow.x, acid_glow.y = sx, sy + bob
            _set_radius(acid_glow, 14 + 3 * math.sin(et * 4.0))
            acid_glow.opacity = 18 + int(14 * (0.5 + 0.5 * math.sin(et * 5.0)))
            self._set_depth(h, sy, shake)
            return

        if behavior == "swarm":
            sh, body, dot1, dot2, dot3, ant1, ant2 = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            r = 8
            dot1.x, dot1.y = sx + math.cos(et * 6.0) * r, sy + bob + math.sin(et * 6.0) * r
            dot2.x, dot2.y = sx + math.cos(et * 6.0 + 2.1) * r, sy + bob + math.sin(et * 6.0 + 2.1) * r
            dot3.x, dot3.y = sx + math.cos(et * 6.0 + 4.2) * r, sy + bob + math.sin(et * 6.0 + 4.2) * r
            # Flickering antenna
            jitter = math.sin(et * 20.0) * 3.0
            ant1.x, ant1.y = sx - 3, sy + bob + 8
            ant1.x2, ant1.y2 = sx - 5 + jitter, sy + bob + 15
            ant2.x, ant2.y = sx + 3, sy + bob + 8
            ant2.x2, ant2.y2 = sx + 5 - jitter, sy + bob + 15
            ant1.opacity = 70 + int(50 * (0.5 + 0.5 * math.sin(et * 14.0)))
            ant2.opacity = 70 + int(50 * (0.5 + 0.5 * math.sin(et * 14.0 + 1.5)))
            self._set_depth(h, sy, shake)
            return

        if behavior == "chaser":
            sh, body, aura, spike1, spike2, spike3, eye1, eye2 = h.objs
            sh.x, sh.y = sx, sy - 18
            body.x, body.y = sx, sy + bob
            # Pulsing aura ring
            aura.x, aura.y = sx, sy + bob
            _set_radius(aura, 16 + 4 * math.sin(et * 3.5))
            aura.opacity = 30 + int(30 * (0.5 + 0.5 * math.sin(et * 2.5)))
            # Rotating spikes
            t_rot = et * 1.8
            for i, spike in enumerate((spike1, spike2, spike3)):
                a = t_rot + i * (math.tau / 3)
                sr = 18
                tip_x = sx + math.cos(a) * sr
                tip_y = sy + bob + math.sin(a) * sr
                base_a1 = a + 0.35
                base_a2 = a - 0.35
                br = 10
                spike.x, spike.y = tip_x, tip_y
                spike.x2, spike.y2 = sx + math.cos(base_a1) * br, sy + bob + math.sin(base_a1) * br
                spike.x3, spike.y3 = sx + math.cos(base_a2) * br, sy + bob + math.sin(base_a2) * br
            eye1.x, eye1.y = sx - 3, sy + bob + 2
            eye2.x, eye2.y = sx + 3, sy + bob + 2
            self._set_depth(h, sy, shake)
            return

        sh, body, shine, eye1, eye2 = h.objs
        sh.x, sh.y = sx, sy - 18
        body.x, body.y = sx, sy
        shine.x, shine.y = sx - 3, sy + 3
        eye1.x, eye1.y = sx - 4, sy + 1
        eye2.x, eye2.y = sx + 2, sy + 1
        self._set_depth(h, sy, shake)

    def drop_enemy(self, enemy):
        """Remove enemy visual. Unless reduced motion is on, the body breaks into pooled motes where it died."""
        h = self._enemy_handles.pop(id(enemy), None)
        if h:
            pose = getattr(h, "pose", None)
            if pose is not None and not motion.reduced():
                boss = enemy_behavior_name(enemy).startswith("boss_")
                self._dissolve.burst(
                    pose.cx,
                    pose.cy,
                    pose.col,
                    count=14 if boss else 8,
                    reach=pose.reach,
                    boost=1.3 if boss else 1.0,
                )
            self._give_back(h)  # a pooled handle goes back to its pool; calling delete() here would strand it

    def ensure_projectile(self, proj):
        """Ensure projectile visual exists. The look comes from projectile_art, keyed by weapon."""
        if id(proj) in self._proj_handles:
            return
        # Pieces are pooled quads in the shot bank, in fixed draw layers, so projectiles never join the depth
        # groups and a new shot takes free slots instead of creating GPU objects.
        self._proj_handles[id(proj)] = ProjectileVisual(self._shot_bank, self._projectile_group, proj, shot_palette=self.shot_palette)

    def sync_projectile(self, proj, shake: Vec2):
        """Update projectile visual position and animation."""
        self._proj_handles[id(proj)].sync(proj, shake)

    def drop_projectile(self, proj):
        """Remove projectile visual."""
        h = self._proj_handles.pop(id(proj), None)
        if h:
            h.delete()

    def ensure_powerup(self, p):
        """Ensure powerup visual exists. Its handle, label included, comes from the kind's pool when one is free."""
        if id(p) in self._power_handles:
            return
        kind = str(p.kind)
        if POOL_POWERUP_HANDLES:
            self._power_handles[id(p)] = self._take("power:" + kind, lambda: self._build_powerup(kind))
        else:
            self._power_handles[id(p)] = self._build_powerup(kind)

    def _build_powerup(self, kind: str) -> RenderHandle:
        """Create one pickup's shapes and label. The look depends only on the kind, so the pool keeps one set per kind."""
        
        # Powerup type - distinct bright colors
        color, glyph, size = {
            "heal": ((100, 255, 150), "+", 14),      # Bright green
            "damage": ((255, 100, 100), "!", 14),    # Bright red  
            "speed": ((100, 200, 255), ">", 14),     # Bright blue
            "firerate": ((255, 220, 100), "*", 14),  # Bright yellow/gold
            "shield": ((120, 220, 255), "O", 14),    # Cyan shield
            "laser": ((255, 120, 255), "=", 14),     # Magenta beam
            "vortex": ((180, 140, 255), "@", 14),    # Vortex
            "weapon": ((220, 230, 255), "W", 14),    # Weapon pickup
            "ultra": ((255, 230, 170), "U", 14),     # Ultra ability charge
            "boost": ((255, 145, 45), "B", 14),      # Overdrive Boost
            "drone": ((90, 255, 225), "D", 14),      # Rare drone companion (teal)
            "ricochet": (POWERUP_COLORS["ricochet"], "<>", 14),
            "homing": (POWERUP_COLORS["homing"], "H", 14),
            "time_slow": (POWERUP_COLORS["time_slow"], "~", 14),
            "magnet": (POWERUP_COLORS["magnet"], "M", 14),
        }.get(kind, ((200, 200, 200), "?", 12))

        # Large, glowing center orb
        orb = shapes.Circle(0, 0, size, color=color, batch=self.batch)
        
        # Inner bright core
        core = shapes.Circle(0, 0, size // 2, color=(255, 255, 255), batch=self.batch)
        core.opacity = 200
        
        # Outer pulsing rings for visibility
        ring1 = shapes.Circle(0, 0, size + 4, color=(255, 255, 255), batch=self.batch)
        ring1.opacity = 200
        
        ring2 = shapes.Circle(0, 0, size + 10, color=color, batch=self.batch)
        ring2.opacity = 80
        
        # Symbol label - larger and more visible
        label = pyglet.text.Label(
            glyph,
            font_name="Consolas",
            font_size=16,
            x=0,
            y=0,
            anchor_x="center",
            anchor_y="center",
            batch=self.batch,
            color=(255, 255, 255, 255),
        )
        art_shapes, art_offsets = make_pickup_art(kind, self.batch, color, size)
        handle = RenderHandle(ring2, ring1, orb, core, label, *art_shapes)
        handle.art_offsets = art_offsets
        return handle

    def sync_powerup(self, p, shake: Vec2):
        """Update powerup visual position."""
        h = self._power_handles[id(p)]
        ring2, ring1, orb, core, label = h.objs[:5]
        sx, sy = to_iso(p.pos, shake)
        ring2.x, ring2.y = sx, sy
        ring1.x, ring1.y = sx, sy
        orb.x, orb.y = sx, sy
        core.x, core.y = sx, sy
        label.x, label.y = sx, sy
        place_pickup_art(h.objs[5:], h.art_offsets, sx, sy)
        self._set_depth(h, sy, shake)

    def drop_powerup(self, p):
        """Remove powerup visual."""
        h = self._power_handles.pop(id(p), None)
        if h:
            self._give_back(h)

    def ensure_obstacle(self, ob):
        if id(ob) in self._obstacle_handles:
            return
        r = float(getattr(ob, "radius", 28.0))
        kind = getattr(ob, "kind", "pillar")

        shadow = shapes.Ellipse(0, 0, r * 2.2, max(6.0, r * 0.75), color=(0, 0, 0), batch=self.batch)
        shadow.opacity = 110

        if kind == "crystal":
            base = shapes.Circle(0, 0, r * 0.9, color=(120, 90, 180), batch=self.batch)
            base.opacity = 200
            shard1 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(210, 190, 255), batch=self.batch)
            shard1.opacity = 200
            shard2 = shapes.Triangle(0, 0, 0, 0, 0, 0, color=(170, 140, 230), batch=self.batch)
            shard2.opacity = 180
            glow = shapes.Circle(0, 0, r * 1.25, color=(180, 140, 255), batch=self.batch)
            glow.opacity = 40
            self._obstacle_handles[id(ob)] = RenderHandle(shadow, glow, base, shard1, shard2)
            return

        if kind == "crate":
            base = shapes.Rectangle(0, 0, r * 1.9, r * 1.35, color=(95, 75, 55), batch=self.batch)
            base.anchor_x = base.width / 2
            base.anchor_y = base.height / 2
            base.opacity = 220
            border = shapes.Rectangle(0, 0, r * 1.9, r * 1.35, color=(160, 140, 120), batch=self.batch)
            border.anchor_x = border.width / 2
            border.anchor_y = border.height / 2
            border.opacity = 60
            strap = shapes.Line(0, 0, 0, 0, thickness=3, color=(50, 40, 30), batch=self.batch)
            strap.opacity = 170
            self._obstacle_handles[id(ob)] = RenderHandle(shadow, base, border, strap)
            return

        # pillar
        base = shapes.Circle(0, 0, r, color=(80, 90, 110), batch=self.batch)
        base.opacity = 230
        top = shapes.Circle(0, 0, max(6.0, r * 0.65), color=(140, 155, 180), batch=self.batch)
        top.opacity = 200
        ring = shapes.Arc(0, 0, r * 1.05, segments=40, thickness=3, color=(255, 255, 255), batch=self.batch)
        ring.opacity = 35
        self._obstacle_handles[id(ob)] = RenderHandle(shadow, base, top, ring)

    def sync_obstacle(self, ob, shake: Vec2):
        h = self._obstacle_handles[id(ob)]
        r = float(getattr(ob, "radius", 28.0))
        kind = getattr(ob, "kind", "pillar")
        sx, sy = to_iso(ob.pos, shake)

        if kind == "crystal":
            shadow, glow, base, shard1, shard2 = h.objs
            shadow.x, shadow.y = sx, sy - 18
            glow.x, glow.y = sx, sy + 6
            base.x, base.y = sx, sy + 2
            shard1.x, shard1.y = sx - r * 0.6, sy + 6
            shard1.x2, shard1.y2 = sx, sy + r * 1.55
            shard1.x3, shard1.y3 = sx + r * 0.35, sy + 6
            shard2.x, shard2.y = sx + r * 0.25, sy + 2
            shard2.x2, shard2.y2 = sx + r * 0.9, sy + r * 1.25
            shard2.x3, shard2.y3 = sx + r * 0.55, sy + 2
            self._set_depth(h, sy, shake)
            return

        if kind == "crate":
            shadow, base, border, strap = h.objs
            shadow.x, shadow.y = sx, sy - 18
            base.x, base.y = sx, sy + 4
            border.x, border.y = sx, sy + 4
            strap.x, strap.y, strap.x2, strap.y2 = sx - r * 0.9, sy + 4, sx + r * 0.9, sy + 4
            self._set_depth(h, sy, shake)
            return

        shadow, base, top, ring = h.objs
        shadow.x, shadow.y = sx, sy - 18
        base.x, base.y = sx, sy + 2
        top.x, top.y = sx, sy + 12
        ring.x, ring.y = sx, sy + 2
        _set_radius(ring, r * (1.02 + 0.03 * math.sin(sy * 0.02)))
        self._set_depth(h, sy, shake)

    def drop_obstacle(self, ob):
        h = self._obstacle_handles.pop(id(ob), None)
        if h:
            h.delete()

    def ensure_trap(self, tr):
        if id(tr) in self._trap_handles:
            return
        kind = getattr(tr, "kind", "")
        if kind in ("slam", "slam_warn", "womb_warn", "meteor"):
            # Ring-style hazard. Womb warnings reuse it in a violet tint, so they never read as slam red.
            # Meteor zones (arena events) use amber, so they never read as slam red either.
            if kind == "womb_warn":
                tint, core_tint = (150, 110, 255), (235, 215, 255)
            elif kind == "meteor":
                tint, core_tint = (255, 150, 60), (255, 240, 200)
            else:
                tint, core_tint = (255, 80, 80), (255, 220, 200)
            base = shapes.Circle(0, 0, tr.radius, color=tint, batch=self.batch)
            base.opacity = 40 if kind in ("slam_warn", "womb_warn", "meteor") else 65
            ring = shapes.Arc(0, 0, tr.radius * 1.05, segments=48, thickness=5, color=(255, 255, 255), batch=self.batch)
            ring.opacity = 170
            core = shapes.Circle(0, 0, max(10, tr.radius * 0.2), color=core_tint, batch=self.batch)
            core.opacity = 200
            self._trap_handles[id(tr)] = RenderHandle(base, ring, core)
        else:
            base = shapes.Circle(0, 0, tr.radius, color=(220, 120, 60), batch=self.batch)
            base.opacity = 80
            core = shapes.Circle(0, 0, max(6, tr.radius * 0.25), color=(255, 220, 180), batch=self.batch)
            core.opacity = 200
            spike = shapes.Line(0, 0, 0, 0, thickness=3, color=(255, 210, 170), batch=self.batch)
            spike2 = shapes.Line(0, 0, 0, 0, thickness=3, color=(255, 210, 170), batch=self.batch)
            self._trap_handles[id(tr)] = RenderHandle(base, core, spike, spike2)

    def sync_trap(self, tr, shake: Vec2):
        h = self._trap_handles[id(tr)]
        kind = getattr(tr, "kind", "")
        if kind in ("slam", "slam_warn", "womb_warn", "meteor"):
            base, ring, core = h.objs
            sx, sy = to_iso(tr.pos, shake)
            base.x, base.y = sx, sy
            ring.x, ring.y = sx, sy
            core.x, core.y = sx, sy
            pulse = 0.6 + 0.4 * math.sin(motion.clock(tr.t) * 16.0)
            ring.opacity = int(110 + 110 * pulse)
            if kind in ("slam_warn", "womb_warn"):
                base.opacity = int(40 + 60 * pulse)
            elif kind == "meteor":
                # A marked zone is faint with a dim ring. A live zone is solid with a bright ring, so the moment it hits reads.
                live = tr.t >= tr.armed_delay
                base.opacity = 190 if live else int(36 + 40 * pulse)
                ring.opacity = int(210 + 45 * pulse) if live else int(80 + 50 * pulse)
            self._set_depth(h, sy, shake)
            return

        base, core, spike, spike2 = h.objs
        sx, sy = to_iso(tr.pos, shake)
        base.x, base.y = sx, sy
        core.x, core.y = sx, sy
        arm = tr.radius * 0.75
        spike.x, spike.y, spike.x2, spike.y2 = sx - arm, sy - 2, sx + arm, sy + 2
        spike2.x, spike2.y, spike2.x2, spike2.y2 = sx - 2, sy - arm, sx + 2, sy + arm
        # Telegraph arming: faint until armed.
        if tr.t < getattr(tr, "armed_delay", 0.0):
            base.opacity = 40
            core.opacity = 120
            spike.opacity = 0
            spike2.opacity = 0
        else:
            base.opacity = 80
            core.opacity = 200
            spike.opacity = 220
            spike2.opacity = 220
        self._set_depth(h, sy, shake)

    def drop_trap(self, tr):
        h = self._trap_handles.pop(id(tr), None)
        if h:
            h.delete()

    def ensure_laser(self, lb):
        if id(lb) in self._laser_handles:
            return
        line = shapes.Line(0, 0, 0, 0, thickness=lb.thickness, color=lb.color, batch=self.batch)
        line.opacity = 200
        core = shapes.Line(0, 0, 0, 0, thickness=max(2, lb.thickness * 0.35), color=(255, 255, 255), batch=self.batch)
        core.opacity = 180
        self._laser_handles[id(lb)] = RenderHandle(line, core)

    def sync_laser(self, lb, shake: Vec2):
        h = self._laser_handles[id(lb)]
        line, core = h.objs
        line.color = lb.color
        x1, y1 = to_iso(lb.start, shake)
        x2, y2 = to_iso(lb.end, shake)
        line.x, line.y, line.x2, line.y2 = x1, y1, x2, y2
        core.x, core.y, core.x2, core.y2 = x1, y1, x2, y2
        # Telegraph: visible warning line before firing.
        warn = float(getattr(lb, "warn", 0.0))
        lb_t = float(getattr(lb, "t", 0.0))
        if lb_t < warn:
            if getattr(lb, "owner", "") == "telegraph":
                # Windup aim line (no damage): brightens as the windup runs down to the moment it resolves.
                progress = min(1.0, max(0.0, lb_t / warn))
                line.opacity = int(90 + 50 * progress)
                core.opacity = int(50 + 30 * progress)
            else:
                # Boss and enemy beams: the warning has to be readable before the beam hits.
                line.opacity = 120
                core.opacity = 80
        else:
            line.opacity = 200
            core.opacity = 180
        self._set_depth(h, max(y1, y2), shake)

    def drop_laser(self, lb):
        h = self._laser_handles.pop(id(lb), None)
        if h:
            h.delete()

    def ensure_thunder(self, th):
        if id(th) in self._thunder_handles:
            return
        outer = shapes.Line(0, 0, 0, 0, thickness=th.thickness, color=th.color, batch=self.batch)
        outer.opacity = 160
        core = shapes.Line(0, 0, 0, 0, thickness=max(2, th.thickness * 0.35), color=(255, 255, 255), batch=self.batch)
        core.opacity = 200
        self._thunder_handles[id(th)] = RenderHandle(outer, core)

    def sync_thunder(self, th, shake: Vec2):
        h = self._thunder_handles[id(th)]
        outer, core = h.objs
        outer.color = th.color
        x1, y1 = to_iso(th.start, shake)
        x2, y2 = to_iso(th.end, shake)
        outer.x, outer.y, outer.x2, outer.y2 = x1, y1, x2, y2
        core.x, core.y, core.x2, core.y2 = x1, y1, x2, y2
        if getattr(th, "t", 0.0) < getattr(th, "warn", 0.0):
            # Warning line: steady, and visible enough to dodge before the strike lands.
            outer.opacity = 110
            core.opacity = 50
        else:
            outer.opacity = int(140 + 70 * (0.5 + 0.5 * math.sin(motion.clock(th.t) * 40.0)))
            core.opacity = int(200 + 40 * (0.5 + 0.5 * math.sin(motion.clock(th.t) * 55.0)))
        self._set_depth(h, max(y1, y2), shake)

    def drop_thunder(self, th):
        h = self._thunder_handles.pop(id(th), None)
        if h:
            h.delete()

    def sync_arena_event(self, ev, shake: Vec2) -> None:
        if self._arena_fx is None:
            self._arena_fx = ArenaEventFx(self.batch, self.groups)
        self._arena_fx.sync(ev, shake)

    def drop_arena_event(self, ev) -> None:
        if self._arena_fx is not None:
            self._arena_fx.drop(ev)
