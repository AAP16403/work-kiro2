"""Per-weapon projectile looks: colour, size, trail and impact.

Visual only. Nothing in this module reads or writes projectile physics, ttl, damage or hit
results. The pieces:

- WEAPON_STYLES and TYPE_STYLES form the style table, keyed by weapon name and by projectile type.
- style_for_projectile(proj) returns the style for one shot, with the enemy and crit variants applied.
- ShotBank owns the quads for every projectile piece. It is one QuadBank per draw layer (ground, telegraph
  ring, trail line, trail disc, body, core, flare), so each layer draws in a fixed order and a frame costs one
  upload per layer. Slots are pooled: a shot takes its slots when it is built and gives them back when it is
  deleted, so no GPU object is created or destroyed per shot.
- ProjectileVisual owns the pieces for one shot. visuals.ensure_projectile builds one and visuals.sync_projectile
  calls sync() on it every frame. Pieces are shape-like handles (x, y, x2, y2, radius, color, opacity, group)
  whose setters edit the bank's arrays only.
- spawn_impact and flak_detonation play hit effects built only from existing ParticleSystem calls.

Flak Battery is a small-range bomb. Its shell arcs (a ground shadow sits below it, the gap swelling and closing
over its flight) and flickers, and a ring marks the landing point. Its detonation throws the fragments and a
shockwave ring drawn at FLAK_BLAST_RADIUS, the farthest reach of the real fragments (states.py).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from pyglet.gl import GL_ONE_MINUS_SRC_ALPHA

import config
import motion
import utils
from config import ISO_SCALE_X, ISO_SCALE_Y
from glow import QuadBank, alpha_texture
from utils import Vec2, to_iso

GOLD_TRAIL = (255, 212, 64)       # crit shots trail gold, whatever the weapon
ENEMY_HEAD = (255, 85, 45)        # enemy shots are red-orange so they never read as player fire
ENEMY_CORE = (255, 200, 160)
ENEMY_TRAIL = (255, 75, 35)
SMOKE = (150, 150, 160)
FLAK_BURST_RING = (255, 190, 90)
FRAGMENT_TRAIL = (255, 150, 60)
FRAGMENT_HEAD = (255, 205, 120)

# Flak geometry. states.PlayingState._spawn_cluster_shrapnel spawns each fragment FRAGMENT_OFFSET from the burst,
# at a speed in [340, 460] for a ttl in [0.24, 0.40]. The farthest fragment therefore reaches
# FLAK_BLAST_RADIUS world px. test_w4_fx checks these constants against the real spawn code.
FRAGMENT_OFFSET = 8.0
FRAGMENT_SPEED_MAX = 460.0
FRAGMENT_TTL_MAX = 0.40
FLAK_BLAST_RADIUS = FRAGMENT_OFFSET + FRAGMENT_SPEED_MAX * FRAGMENT_TTL_MAX   # 192 world px
FLAK_LIFT_PX = 16.0               # on-screen height of the shell's arc at its apex, drawn above its shadow

# Trail pieces are drawn behind the body. Spread dots use this many pieces.
_DOT_COUNT = 4

# Texture sizes of the three quad kinds (texels). A line is a solid square stretched to a rectangle.
_LINE_TEX = 4
_DISC_TEX = 32
_RING_TEX = 256

# Draw layers, back to front: (name, group order, texture kind). The projectile group is order 14000; the
# layers straddle it, and the glow bank (14500) and particles (15000) still draw above them.
_LAYERS = (
    ("ground", 13980, "disc"),
    ("ring", 13990, "ring"),
    ("line", 14000, "line"),
    ("trail", 14001, "disc"),
    ("body", 14002, "disc"),
    ("core", 14003, "disc"),
    ("flare", 14004, "disc"),
)


@dataclass(frozen=True)
class ProjectileStyle:
    """One projectile look. Sizes are screen pixels.

    ``trail`` names a trail painter in _TRAILS, ``length`` is its length at rest (a speed bonus is
    added per shot), and ``impact`` names the hit recipe in _IMPACTS.
    """
    label: str
    head: tuple[int, int, int]
    core: tuple[int, int, int]
    radius: float
    trail: str
    length: float
    trail_color: tuple[int, int, int]
    impact: str

    @property
    def color(self) -> tuple[int, int, int]:
        """The colour a weapon swatch shows for this style: the bright head of the shot (contract name)."""
        return self.head


# Player weapons, keyed by Weapon.name (see weapons.WEAPONS).
WEAPON_STYLES: dict[str, ProjectileStyle] = {
    "Basic Gun": ProjectileStyle(
        "Basic Gun", head=(255, 235, 120), core=(255, 255, 240), radius=3.0,
        trail="tracer", length=22.0, trail_color=(255, 250, 240), impact="tracer"),
    "Spread Shot": ProjectileStyle(
        "Spread Shot", head=(255, 215, 225), core=(255, 255, 255), radius=2.4,
        trail="dots", length=18.0, trail_color=(255, 140, 175), impact="pellet"),
    "Rapid Fire": ProjectileStyle(
        "Rapid Fire", head=(200, 255, 140), core=(250, 255, 235), radius=2.2,
        trail="dashes", length=26.0, trail_color=(170, 240, 100), impact="dash"),
    "Heavy Cannon": ProjectileStyle(
        "Heavy Cannon", head=(255, 190, 70), core=(255, 246, 205), radius=6.0,
        trail="slug", length=30.0, trail_color=(255, 150, 85), impact="slug"),
    "Plasma Rifle": ProjectileStyle(
        "Plasma Rifle", head=(175, 110, 255), core=(240, 225, 255), radius=4.5,
        trail="orb", length=24.0, trail_color=(165, 110, 255), impact="orb"),
    "Hyper Railgun": ProjectileStyle(
        "Hyper Railgun", head=(120, 245, 255), core=(245, 255, 255), radius=3.6,
        trail="streak", length=60.0, trail_color=(120, 235, 255), impact="rail"),
    "Flak Battery": ProjectileStyle(
        "Flak Battery", head=(205, 210, 220), core=(255, 235, 140), radius=4.2,
        trail="shell", length=20.0, trail_color=(230, 230, 235), impact="flak"),
}

BASIC_STYLE = WEAPON_STYLES["Basic Gun"]

# Contract name for the same table (hud_widgets reads STYLES for the weapon swatches).
STYLES = WEAPON_STYLES

# Flak fragments are plain bullets with no weapon name and a short ttl. They get their own amber streak.
FRAGMENT_STYLE = ProjectileStyle(
    "Flak Fragment", head=FRAGMENT_HEAD, core=(255, 245, 220), radius=2.0,
    trail="dashes", length=14.0, trail_color=FRAGMENT_TRAIL, impact="flak")

# Shots with no weapon name (enemy shots, flak shrapnel) fall back to their projectile type.
TYPE_STYLES: dict[str, ProjectileStyle] = {
    "bullet": BASIC_STYLE,
    "spread": WEAPON_STYLES["Spread Shot"],
    "missile": WEAPON_STYLES["Heavy Cannon"],
    "plasma": WEAPON_STYLES["Plasma Rifle"],
    "railgun": WEAPON_STYLES["Hyper Railgun"],
    "flak": WEAPON_STYLES["Flak Battery"],
    "bomb": ProjectileStyle(
        "Bomb", head=(120, 70, 45), core=(255, 145, 90), radius=6.5,
        trail="none", length=0.0, trail_color=(255, 145, 90), impact="tracer"),
}


def style_for(weapon_name: str = "", projectile_type: str = "bullet") -> ProjectileStyle:
    """Style for a weapon name. Without a known name, the projectile type decides, else the basic style."""
    style = WEAPON_STYLES.get(str(weapon_name or ""))
    if style is None:
        style = TYPE_STYLES.get(str(projectile_type or ""), BASIC_STYLE)
    return style


def _is_fragment(proj) -> bool:
    """A flak fragment: a player bullet with no weapon name and the short ttl that states.py gives shrapnel."""
    return (str(getattr(proj, "owner", "player")) == "player"
            and not getattr(proj, "weapon_name", "")
            and str(getattr(proj, "projectile_type", "bullet")) == "bullet"
            and float(getattr(proj, "ttl", 0.0)) <= FRAGMENT_TTL_MAX + 1e-6)


def style_for_projectile(proj) -> ProjectileStyle:
    """Style for one shot, with the enemy red-orange, crit gold and flak fragment variants applied."""
    if _is_fragment(proj):
        return FRAGMENT_STYLE
    style = style_for(getattr(proj, "weapon_name", ""), getattr(proj, "projectile_type", "bullet"))
    if str(getattr(proj, "owner", "player")) == "enemy":
        return replace(style, head=ENEMY_HEAD, core=ENEMY_CORE, trail_color=ENEMY_TRAIL)
    if getattr(proj, "is_crit", False):
        return replace(style, trail_color=GOLD_TRAIL)
    return style


def trail_length(style: ProjectileStyle, speed: float) -> float:
    """Trail length in screen px: the style length plus a small bonus for fast shots."""
    return style.length + min(8.0, float(speed) * 0.02)


def iso_ring_axes(world_radius: float) -> tuple[float, float]:
    """Screen (horizontal semi-axis px, width/height aspect) of a world circle on the iso ground.

    The iso map is linear, so a world circle becomes an ellipse with horizontal semi-axis
    r * sqrt(2) * ISO_SCALE_X and vertical semi-axis r * sqrt(2) * ISO_SCALE_Y.
    """
    sx = float(ISO_SCALE_X)
    return float(world_radius) * math.sqrt(2.0) * sx, (float(ISO_SCALE_Y) / sx if sx > 0.0 else 1.0)


def _screen_back(vel) -> tuple[float, float, float]:
    """Unit screen-space vector pointing back along the flight path, and the world speed.

    The iso projection is linear, so the screen direction of a world velocity is that velocity
    projected the same way as positions. A zero velocity points back along screen -x.
    """
    vx = float(getattr(vel, "x", 0.0))
    vy = float(getattr(vel, "y", 0.0))
    speed = math.hypot(vx, vy)
    ux = (vx - vy) * ISO_SCALE_X
    uy = (vx + vy) * ISO_SCALE_Y
    n = math.hypot(ux, uy)
    if n <= 1e-9:
        return -1.0, 0.0, speed
    return -ux / n, -uy / n, speed


# ---- pooled quads -----------------------------------------------------------------------------

def _line_alpha(d: float) -> float:
    return 1.0


def _disc_alpha(d: float) -> float:
    """Solid disc with a one-pixel anti-aliased edge. d is 1.0 at the half-size, so d * half px is the radius."""
    return (1.0 - d) * (_DISC_TEX * 0.5) + 0.5


def _ring_alpha(d: float) -> float:
    """Thin ring whose band sits just inside the texture edge, with a faint fill inside it."""
    band = max(0.0, 1.0 - abs(d - 0.975) / 0.012)
    fill = 0.08 * max(0.0, 1.0 - d / 0.975)
    return band + fill


_TEXTURE_ALPHA = {"line": (_LINE_TEX, _line_alpha), "disc": (_DISC_TEX, _disc_alpha), "ring": (_RING_TEX, _ring_alpha)}


class _Pool:
    """Free list of quad slots for one layer. A new page (one QuadBank) is added when the free list runs out."""

    PAGE = 128

    def __init__(self, batch, order: int, texture, tex_px: int):
        self._batch = batch
        self._order = int(order)
        self._texture = texture
        self.tex_px = int(tex_px)
        self._pages = []
        self._free = []

    @property
    def pages(self) -> int:
        return len(self._pages)

    @property
    def free_count(self) -> int:
        return len(self._free)

    def take(self):
        """A (bank, slot) pair for one piece. Creates a page only when every slot is in use."""
        if not self._free:
            self._grow()
        return self._free.pop()

    def give(self, bank, slot: int) -> None:
        bank.hide(slot)
        self._free.append((bank, slot))

    def _grow(self) -> None:
        bank = QuadBank(self._batch, self.PAGE, self._order, texture=self._texture, blend_dst=GL_ONE_MINUS_SRC_ALPHA)
        for slot in range(self.PAGE - 1, -1, -1):
            self._free.append((bank, slot))
        self._pages.append(bank)

    def warm(self) -> None:
        """Create the first page now, so the first shot of a run does not pay for it."""
        if not self._pages:
            self._grow()

    def flush(self) -> None:
        for bank in self._pages:
            bank.flush()


_TEXTURES: dict = {}   # kind -> texture, built on first use and shared by every ShotBank (one GL context)


def _texture(kind: str):
    tex = _TEXTURES.get(kind)
    if tex is None:
        size, alpha_at = _TEXTURE_ALPHA[kind]
        tex = alpha_texture(size, alpha_at)
        _TEXTURES[kind] = tex
    return tex


class ShotBank:
    """All projectile quads for one Visuals object: one pool per draw layer, textures shared and built once."""

    def __init__(self, batch):
        self._pools = {}
        for name, order, kind in _LAYERS:
            self._pools[name] = _Pool(batch, order, _texture(kind), _TEXTURE_ALPHA[kind][0])
        for pool in self._pools.values():
            pool.warm()

    def pool(self, name: str) -> _Pool:
        return self._pools[name]

    @property
    def pages(self) -> int:
        return sum(p.pages for p in self._pools.values())

    def flush(self) -> None:
        """Upload every layer. Call once a frame, after the projectile syncs."""
        for p in self._pools.values():
            p.flush()


# ---- pieces -----------------------------------------------------------------------------------

def _clamp_byte(value) -> int:
    return max(0, min(255, int(value)))


class _Piece:
    """Shape-like handle for one pooled quad. Its properties write the quad's arrays, and the bank uploads them once a frame."""

    def __init__(self, pool: _Pool, group, color, opacity):
        self.group = group
        self._pool = pool
        self._bank, self._slot = pool.take()
        self._cr = int(color[0])
        self._cg = int(color[1])
        self._cb = int(color[2])
        self._op = _clamp_byte(opacity)
        self._sx = 0.0
        self._sy = 0.0
        self._rot = 0.0
        self._restyle()  # a reused slot starts hidden until the piece sets its geometry

    @property
    def color(self) -> tuple[int, int, int, int]:
        return (self._cr, self._cg, self._cb, 255)

    @property
    def opacity(self) -> int:
        return self._op

    @opacity.setter
    def opacity(self, value) -> None:
        v = _clamp_byte(value)
        if v != self._op:
            self._op = v
            self._restyle()

    def _restyle(self) -> None:
        bank = self._bank
        if bank is not None:
            bank.set_style(self._slot, self._sx, self._sy, self._rot, self._cr, self._cg, self._cb, self._op)

    def _place(self, x: float, y: float) -> None:
        bank = self._bank
        if bank is not None:
            bank.place(self._slot, x, y)

    def delete(self) -> None:
        if self._bank is not None:
            self._pool.give(self._bank, self._slot)
            self._bank = None


class LinePiece(_Piece):
    """A straight solid line from (x, y) to (x2, y2), drawn as a rectangle of the given thickness."""

    def __init__(self, pool, group, color, thickness: float, opacity):
        super().__init__(pool, group, color, opacity)
        self._t = float(thickness)
        self._sy = self._t / _LINE_TEX  # thickness is fixed for the piece's life
        self._x = self._y = self._x2 = self._y2 = 0.0

    def set_ends(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Move both ends at once: one geometry update, however the ends are passed."""
        self._x = x0
        self._y = y0
        self._x2 = x1
        self._y2 = y1
        dx = x1 - x0
        dy = y1 - y0
        length = math.hypot(dx, dy)
        self._place(0.5 * (x0 + x1), 0.5 * (y0 + y1))
        if length > 1e-9:
            sx = length / _LINE_TEX
            rot = -math.degrees(math.atan2(dy, dx))
        else:
            sx = 0.0
            rot = 0.0
        # A straight shot keeps its length and angle, so only the translation above changes frame to frame.
        if sx != self._sx or rot != self._rot:
            self._sx = sx
            self._rot = rot
            self._restyle()

    @property
    def x(self) -> float:
        return self._x

    @x.setter
    def x(self, v) -> None:
        self.set_ends(float(v), self._y, self._x2, self._y2)

    @property
    def y(self) -> float:
        return self._y

    @y.setter
    def y(self, v) -> None:
        self.set_ends(self._x, float(v), self._x2, self._y2)

    @property
    def x2(self) -> float:
        return self._x2

    @x2.setter
    def x2(self, v) -> None:
        self.set_ends(self._x, self._y, float(v), self._y2)

    @property
    def y2(self) -> float:
        return self._y2

    @y2.setter
    def y2(self, v) -> None:
        self.set_ends(self._x, self._y, self._x2, float(v))


class DiscPiece(_Piece):
    """A disc (or, with aspect < 1, an iso ground ellipse) of the given radius, centred on (x, y)."""

    def __init__(self, pool, group, radius: float, color, opacity, aspect: float = 1.0):
        super().__init__(pool, group, color, opacity)
        self._r = float(radius)
        self._aspect = float(aspect)
        self._x = 0.0
        self._y = 0.0
        self._resize()

    def _resize(self) -> None:
        s = 2.0 * self._r / float(self._pool.tex_px)
        self._sx = s
        self._sy = s * self._aspect
        self._rot = 0.0
        self._restyle()

    @property
    def radius(self) -> float:
        return self._r

    @radius.setter
    def radius(self, v) -> None:
        self._r = float(v)
        self._resize()

    def move(self, x: float, y: float) -> None:
        self._x = x
        self._y = y
        self._place(x, y)

    @property
    def x(self) -> float:
        return self._x

    @x.setter
    def x(self, v) -> None:
        self.move(float(v), self._y)

    @property
    def y(self) -> float:
        return self._y

    @y.setter
    def y(self, v) -> None:
        self.move(self._x, float(v))

    @property
    def position(self) -> tuple[float, float]:
        return (self._x, self._y)

    @position.setter
    def position(self, value) -> None:
        self.move(float(value[0]), float(value[1]))


def _line(bank: ShotBank, group, color, thickness: float, opacity: int) -> LinePiece:
    return LinePiece(bank.pool("line"), group, color, thickness, opacity)


def _disc(bank: ShotBank, group, radius: float, color, opacity: int = 255, layer: str = "trail",
          aspect: float = 1.0) -> DiscPiece:
    # Tiny discs and big ones share the quad; the vertex count that made them costly is gone with the shapes.
    return DiscPiece(bank.pool(layer), group, radius, color, opacity, aspect)


def _fade(shape, alpha: float, step: int = 8) -> None:
    """Set opacity to alpha quantised to `step`, and write only when it changes.

    Reads the piece's stored opacity directly: this runs several times per flak shell a frame, and the
    property read is most of its cost.
    """
    a = int(round(min(255.0, max(0.0, float(alpha))) / step) * step)
    if a > 255:
        a = 255
    if shape._op != a:
        shape.opacity = a


# ---- trail painters ---------------------------------------------------------------------------
# Each builder takes pieces from the ShotBank and returns them in trail order. Each placer moves them for
# one frame: (hx, hy) is the head on screen, (bx, by) the unit back vector, length the trail length in px,
# and t the shot's ttl after motion.clock(), so reduced motion freezes flicker and wobble.

def _build_none(bank, group, st):
    return []


def _place_none(objs, hx, hy, bx, by, length, t) -> None:
    return None


def _build_tracer(bank, group, st):
    return [_line(bank, group, st.trail_color, 3, 150), _line(bank, group, (255, 255, 255), 1, 210)]


def _place_tracer(objs, hx, hy, bx, by, length, t) -> None:
    outer, inner = objs
    outer.set_ends(hx, hy, hx + bx * length, hy + by * length)
    inner.set_ends(hx, hy, hx + bx * length * 0.55, hy + by * length * 0.55)


def _build_dots(bank, group, st):
    dots = []
    for i in range(_DOT_COUNT):
        fade = 1.0 - (i + 1) / (_DOT_COUNT + 1)
        dots.append(_disc(bank, group, max(0.8, st.radius * (0.85 - 0.15 * i)), st.trail_color, int(200 * fade)))
    return dots


def _place_dots(objs, hx, hy, bx, by, length, t) -> None:
    for i, dot in enumerate(objs):
        d = length * (i + 1) / _DOT_COUNT
        dot.move(hx + bx * d, hy + by * d)


def _build_dashes(bank, group, st):
    return [_line(bank, group, st.trail_color, 1.6, 200), _line(bank, group, st.trail_color, 1.6, 110)]


def _place_dashes(objs, hx, hy, bx, by, length, t) -> None:
    near, far = objs
    near.set_ends(hx, hy, hx + bx * length * 0.5, hy + by * length * 0.5)
    far.set_ends(hx + bx * length * 0.62, hy + by * length * 0.62, hx + bx * length, hy + by * length)


def _build_slug(bank, group, st):
    halo = _disc(bank, group, st.radius * 1.9, st.trail_color, 110)
    puffs = [_disc(bank, group, r, SMOKE, a) for r, a in ((3.0, 90), (4.4, 60), (5.8, 34))]
    return [halo] + puffs


def _place_slug(objs, hx, hy, bx, by, length, t) -> None:
    halo = objs[0]
    halo.move(hx, hy)
    _fade(halo, 95 + 35 * math.sin(t * 9.0))
    px, py = -by, bx
    for i, puff in enumerate(objs[1:]):
        d = length * (0.4 + 0.3 * i)
        wobble = math.sin(t * 7.0 + i * 1.7) * 1.5
        puff.move(hx + bx * d + px * wobble, hy + by * d + py * wobble)


def _build_orb(bank, group, st):
    halo = _disc(bank, group, st.radius * 1.9, st.trail_color, 90)
    far = _disc(bank, group, st.radius * 0.5, st.trail_color, 70)
    near = _disc(bank, group, st.radius * 0.8, st.trail_color, 120)
    return [halo, far, near]


def _place_orb(objs, hx, hy, bx, by, length, t) -> None:
    halo, far, near = objs
    halo.move(hx, hy)
    _fade(halo, 55 + 45 * (0.5 + 0.5 * math.sin(t * 12.0)))
    near.move(hx + bx * length * 0.4, hy + by * length * 0.4)
    far.move(hx + bx * length * 0.75, hy + by * length * 0.75)


def _build_streak(bank, group, st):
    body = _line(bank, group, st.trail_color, 4, 120)
    shimmer = _line(bank, group, st.trail_color, 1.5, 80)
    core = _line(bank, group, (255, 255, 255), 1.5, 220)
    return [body, shimmer, core]


def _place_streak(objs, hx, hy, bx, by, length, t) -> None:
    body, shimmer, core = objs
    px, py = -by, bx
    wobble = 1.6 * math.sin(t * 23.0)
    body.set_ends(hx, hy, hx + bx * length, hy + by * length)
    shimmer.set_ends(hx + px * wobble, hy + py * wobble,
                     hx + bx * length * 0.9 + px * wobble, hy + by * length * 0.9 + py * wobble)
    core.set_ends(hx, hy, hx + bx * length * 0.7, hy + by * length * 0.7)
    _fade(shimmer, 40 + 60 * (0.5 + 0.5 * math.sin(t * 31.0)))


def _build_shell(bank, group, st):
    trail = _line(bank, group, st.trail_color, 1.8, 150)
    sparks = [_disc(bank, group, 1.6, (255, 230, 130)) for _ in range(3)]
    return [trail] + sparks


def _place_shell(objs, hx, hy, bx, by, length, t) -> None:
    trail = objs[0]
    trail.set_ends(hx, hy, hx + bx * length * 0.7, hy + by * length * 0.7)
    px, py = -by, bx
    for i, spark in enumerate(objs[1:]):
        d = length * (0.25 + 0.25 * i)
        side = 2.6 if i % 2 == 0 else -2.6
        spark.move(hx + bx * d + px * side, hy + by * d + py * side)
        _fade(spark, 255 * max(0.0, math.sin(t * 17.0 + i * 2.1)), step=32)


_TRAILS = {
    "none": (_build_none, _place_none),
    "tracer": (_build_tracer, _place_tracer),
    "dots": (_build_dots, _place_dots),
    "dashes": (_build_dashes, _place_dashes),
    "slug": (_build_slug, _place_slug),
    "orb": (_build_orb, _place_orb),
    "streak": (_build_streak, _place_streak),
    "shell": (_build_shell, _place_shell),
}


# Plain player weapons. Under a skin their heads take the skin's bullet colour; heavier weapons keep their identity colour.
PLAIN_SHOT_LABELS = ("Basic Gun", "Spread Shot", "Rapid Fire")


def skin_shot_style(style: ProjectileStyle, shot_palette) -> ProjectileStyle:
    """A player shot's look under a skin: plain heads take the bullet colour, and every trail takes the trail colour."""
    head = tuple(shot_palette["bullet"]) if style.label in PLAIN_SHOT_LABELS else style.head
    return replace(style, head=head, trail_color=tuple(shot_palette["trail"]))


class ProjectileVisual:
    """Pieces for one projectile: trail pieces first, then the body, core and flare.

    ``objs`` keeps that order, so the body disc is always ``objs[-3]``. ``_ground`` holds the pieces that
    are not part of the shot's body or trail: the flak shadow and landing ring. ``shot_palette`` is the run's
    skin palette (skin_apply.RunSkin.shot_palette), or None for the weapon colours. It only changes
    player shots that are not crits; enemy shots and crits keep their look.
    """

    def __init__(self, bank: ShotBank, group, proj, shot_palette=None):
        self.style = style_for_projectile(proj)
        player_shot = str(getattr(proj, "owner", "player")) == "player" and not getattr(proj, "is_crit", False)
        if shot_palette is not None and player_shot:
            self.style = skin_shot_style(self.style, shot_palette)
        st = self.style
        build, self._place = _TRAILS[st.trail]
        self._trail = build(bank, group, st)
        if getattr(proj, "is_crit", False):
            flare_alpha = 150
        elif str(getattr(proj, "owner", "player")) == "enemy":
            flare_alpha = 90
        else:
            flare_alpha = 120
        self._body = _disc(bank, group, st.radius, st.head, layer="body")
        self._core = _disc(bank, group, max(1.0, st.radius * 0.5), st.core, layer="core")
        self._flare = _disc(bank, group, max(2.0, st.radius * 0.55), (255, 255, 255), flare_alpha, layer="flare")
        self.objs = self._trail + [self._body, self._core, self._flare]
        # The ttl at build time is the full flight for a shot built on its first frame, so the arc starts at 0.
        self._ttl0 = max(0.05, float(getattr(proj, "ttl", 0.0) or 0.0))
        self._ground = []
        self._shadow = None
        self._telegraph = None
        if st.trail == "shell":
            radius, aspect = iso_ring_axes(FLAK_BLAST_RADIUS)
            self._shadow = _disc(bank, group, st.radius * 1.5, (0, 0, 0), 90, layer="ground", aspect=0.5)
            self._telegraph = _disc(bank, group, radius, FLAK_BURST_RING, 0, layer="ring", aspect=aspect)
            self._ground = [self._shadow, self._telegraph]

    def sync(self, proj, shake: Vec2) -> None:
        """Move every piece to the shot's shaken screen position and animate from its ttl."""
        hx, hy = to_iso(proj.pos, shake)
        bx, by, speed = _screen_back(getattr(proj, "vel", None))
        t = float(getattr(proj, "ttl", 0.0))
        tc = motion.clock(t)  # reduced motion holds every flicker and wobble at its rest pose
        self._place(self._trail, hx, hy, bx, by, trail_length(self.style, speed), tc)
        self._body.move(hx, hy)
        self._core.move(hx, hy)
        self._flare.move(hx, hy)
        if self._telegraph is not None:
            self._sync_flak(proj, shake, hx, hy, t, tc)

    def _sync_flak(self, proj, shake: Vec2, hx: float, hy: float, t: float, tc: float) -> None:
        """The shell's arc, flicker and landing ring.

        The shell is drawn at its real position. Its ground shadow sits below it by the arc height, so the gap
        opens to FLAK_LIFT_PX at the apex and closes at launch and at the landing point. The landing ring marks
        where the shell detonates: the point it reaches when its ttl runs out, and it brightens as that nears.
        """
        prog = min(1.0, max(0.0, 1.0 - t / self._ttl0))
        lift = FLAK_LIFT_PX * math.sin(math.pi * prog) * motion.factor()
        self._shadow.move(hx, hy - lift)
        rest = max(0.0, t)
        wx = proj.pos.x + proj.vel.x * rest
        wy = proj.pos.y + proj.vel.y * rest
        self._telegraph.move((wx - wy) * ISO_SCALE_X + utils.VIEW_W * 0.5 + shake.x,
                             (wx + wy) * ISO_SCALE_Y + utils.VIEW_H * 0.5 + shake.y)
        pulse = 0.5 + 0.5 * math.sin(tc * 14.0)
        _fade(self._telegraph, 40 + 110 * prog + 30 * pulse, step=8)
        # The shell flickers in flight: its white flare beats between dim and bright.
        _fade(self._flare, 120 + 110 * max(0.0, math.sin(tc * 40.0)), step=16)

    def delete(self) -> None:
        for o in self.objs:
            o.delete()
        for o in self._ground:
            o.delete()


# ---- hit effects ------------------------------------------------------------------------------
# Each recipe takes the ParticleSystem, the hit position and the enemy's colour, and calls only
# existing ParticleSystem methods.

def _impact_tracer(ps, pos, color) -> None:
    ps.add_hit_particles(pos, color)


def _impact_pellet(ps, pos, color) -> None:
    ps.add_hit_particles(pos, color)
    ps.emit(pos, (255, 240, 215), count=3, speed=90.0, life=0.18, size=1.8)


def _impact_dash(ps, pos, color) -> None:
    ps.add_hit_particles(pos, color)
    ps.emit(pos, (235, 255, 200), count=2, speed=130.0, life=0.12, size=1.6)


def _impact_slug(ps, pos, color) -> None:
    ps.add_hit_particles(pos, color)
    ps.add_shockwave(pos, (255, 190, 90), max_radius=34.0, ttl=0.22)
    ps.emit(pos, SMOKE, count=4, speed=40.0, life=0.5, size=3.2)


def _impact_orb(ps, pos, color) -> None:
    ps.add_shockwave(pos, (175, 120, 255), max_radius=38.0, ttl=0.28)
    ps.add_hit_particles(pos, color)


def _impact_rail(ps, pos, color) -> None:
    ps.add_shockwave(pos, (140, 245, 255), max_radius=28.0, ttl=0.18)
    ps.emit(pos, (240, 255, 255), count=5, speed=170.0, life=0.2, size=2.2)
    ps.add_hit_particles(pos, color)


def _impact_flak(ps, pos, color) -> None:
    ps.add_hit_particles(pos, color)
    ps.emit(pos, (255, 235, 140), count=4, speed=110.0, life=0.25, size=2.0)


_IMPACTS = {
    "tracer": _impact_tracer,
    "pellet": _impact_pellet,
    "dash": _impact_dash,
    "slug": _impact_slug,
    "orb": _impact_orb,
    "rail": _impact_rail,
    "flak": _impact_flak,
}


def spawn_impact(particles, proj, pos, color) -> None:
    """Play the hit effect for one player shot at pos, tinted with the enemy's colour."""
    _IMPACTS[style_for_projectile(proj).impact](particles, pos, color)


def flak_detonation(particles, pos) -> None:
    """Flak burst on detonation: the fragments, a shockwave ring at the real blast radius and a faint inner ring.

    The rings are ground ellipses (add_ground_ring), so they line up with the landing ring the shell drew.
    With reduced motion they hold their size and fade rather than grow.
    """
    grow = not motion.reduced()
    particles.add_flak_burst(pos)
    particles.add_ground_ring(pos, FLAK_BURST_RING, FLAK_BLAST_RADIUS, 0.32, grow=grow)
    particles.add_ground_ring(pos, (255, 245, 220), FLAK_BLAST_RADIUS * 0.6, 0.22, delay=0.05, grow=grow)
