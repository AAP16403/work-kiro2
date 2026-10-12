"""Per-weapon projectile looks: colour, size, trail and impact.

Visual only. Nothing in this module reads or writes projectile physics, ttl, damage or hit
results. The pieces:

- WEAPON_STYLES and TYPE_STYLES form the style table, keyed by weapon name and by projectile type.
- style_for_projectile(proj) returns the style for one shot, with the enemy and crit variants applied.
- ProjectileVisual owns the pooled shapes for one shot. visuals.ensure_projectile builds one and
  visuals.sync_projectile calls sync() on it every frame. Shapes are created once and only moved
  or faded afterwards, so no geometry is rebuilt per frame.
- spawn_impact and flak_detonation play hit effects built only from existing ParticleSystem calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from pyglet import shapes

from config import ISO_SCALE_X, ISO_SCALE_Y
from utils import Vec2, to_iso

GOLD_TRAIL = (255, 212, 64)       # crit shots trail gold, whatever the weapon
ENEMY_HEAD = (255, 85, 45)        # enemy shots are red-orange so they never read as player fire
ENEMY_CORE = (255, 200, 160)
ENEMY_TRAIL = (255, 75, 35)
SMOKE = (150, 150, 160)
FLAK_BURST_RING = (255, 190, 90)

# Trail pieces are drawn behind the body. Spread dots use this many pieces.
_DOT_COUNT = 4


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


def style_for_projectile(proj) -> ProjectileStyle:
    """Style for one shot, with the enemy red-orange and crit gold variants applied."""
    style = style_for(getattr(proj, "weapon_name", ""), getattr(proj, "projectile_type", "bullet"))
    if str(getattr(proj, "owner", "player")) == "enemy":
        return replace(style, head=ENEMY_HEAD, core=ENEMY_CORE, trail_color=ENEMY_TRAIL)
    if getattr(proj, "is_crit", False):
        return replace(style, trail_color=GOLD_TRAIL)
    return style


def trail_length(style: ProjectileStyle, speed: float) -> float:
    """Trail length in screen px: the style length plus a small bonus for fast shots."""
    return style.length + min(8.0, float(speed) * 0.02)


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


# ---- trail painters ---------------------------------------------------------------------------
# Each builder creates its shapes once, in the batch and group it is given. Each placer moves them
# for one frame: (hx, hy) is the head on screen, (bx, by) the unit back vector, length the trail
# length in px, and t the shot's remaining ttl, which drives flicker and pulse.

def _line(batch, group, color, thickness: float, opacity: int):
    ln = shapes.Line(0, 0, 0, 0, thickness=thickness, color=color, batch=batch, group=group)
    ln.opacity = opacity
    return ln


def _disc(batch, group, radius: float, color, opacity: int = 255):
    # Tiny discs use fewer segments: vertex count sets the cost of every colour and position write.
    segments = 10 if radius <= 4.5 else 14
    c = shapes.Circle(0, 0, radius, segments=segments, color=color, batch=batch, group=group)
    c.opacity = opacity
    return c


def _ring(batch, group, radius: float, color, thickness: float, opacity: int):
    c = shapes.Arc(0, 0, radius, segments=16, angle=360.0, thickness=thickness,
                   color=color, batch=batch, group=group)
    c.opacity = opacity
    return c


def _set_line(ln, x0: float, y0: float, x1: float, y1: float) -> None:
    ln.x, ln.y = x0, y0
    ln.x2, ln.y2 = x1, y1


def _fade(shape, alpha: float, step: int = 8) -> None:
    """Set opacity to alpha quantised to `step`, and write only when it changes.

    An opacity write rewrites every vertex colour of a disc, which costs far more than a move, so
    pulses are quantised and skipped while they hold still.
    """
    a = int(round(min(255.0, max(0.0, float(alpha))) / step) * step)
    a = min(255, a)
    if shape.opacity != a:
        shape.opacity = a


def _build_none(batch, group, st):
    return []


def _place_none(objs, hx, hy, bx, by, length, t) -> None:
    return None


def _build_tracer(batch, group, st):
    return [_line(batch, group, st.trail_color, 3, 150), _line(batch, group, (255, 255, 255), 1, 210)]


def _place_tracer(objs, hx, hy, bx, by, length, t) -> None:
    outer, inner = objs
    _set_line(outer, hx, hy, hx + bx * length, hy + by * length)
    _set_line(inner, hx, hy, hx + bx * length * 0.55, hy + by * length * 0.55)


def _build_dots(batch, group, st):
    dots = []
    for i in range(_DOT_COUNT):
        fade = 1.0 - (i + 1) / (_DOT_COUNT + 1)
        dots.append(_disc(batch, group, max(0.8, st.radius * (0.85 - 0.15 * i)), st.trail_color, int(200 * fade)))
    return dots


def _place_dots(objs, hx, hy, bx, by, length, t) -> None:
    for i, dot in enumerate(objs):
        d = length * (i + 1) / _DOT_COUNT
        dot.position = (hx + bx * d, hy + by * d)


def _build_dashes(batch, group, st):
    return [_line(batch, group, st.trail_color, 1.6, 200), _line(batch, group, st.trail_color, 1.6, 110)]


def _place_dashes(objs, hx, hy, bx, by, length, t) -> None:
    near, far = objs
    _set_line(near, hx, hy, hx + bx * length * 0.5, hy + by * length * 0.5)
    _set_line(far, hx + bx * length * 0.62, hy + by * length * 0.62, hx + bx * length, hy + by * length)


def _build_slug(batch, group, st):
    halo = _disc(batch, group, st.radius * 1.9, st.trail_color, 110)
    puffs = [_disc(batch, group, r, SMOKE, a) for r, a in ((3.0, 90), (4.4, 60), (5.8, 34))]
    return [halo] + puffs


def _place_slug(objs, hx, hy, bx, by, length, t) -> None:
    halo = objs[0]
    halo.position = (hx, hy)
    _fade(halo, 95 + 35 * math.sin(t * 9.0))
    px, py = -by, bx
    for i, puff in enumerate(objs[1:]):
        d = length * (0.4 + 0.3 * i)
        wobble = math.sin(t * 7.0 + i * 1.7) * 1.5
        puff.position = (hx + bx * d + px * wobble, hy + by * d + py * wobble)


def _build_orb(batch, group, st):
    halo = _disc(batch, group, st.radius * 1.9, st.trail_color, 90)
    far = _ring(batch, group, st.radius * 1.25, st.trail_color, 1.2, 70)
    near = _ring(batch, group, st.radius * 1.5, st.trail_color, 1.4, 120)
    return [halo, far, near]


def _place_orb(objs, hx, hy, bx, by, length, t) -> None:
    halo, far, near = objs
    halo.position = (hx, hy)
    _fade(halo, 55 + 45 * (0.5 + 0.5 * math.sin(t * 12.0)))
    near.position = (hx + bx * length * 0.4, hy + by * length * 0.4)
    far.position = (hx + bx * length * 0.75, hy + by * length * 0.75)


def _build_streak(batch, group, st):
    body = _line(batch, group, st.trail_color, 4, 120)
    shimmer = _line(batch, group, st.trail_color, 1.5, 80)
    core = _line(batch, group, (255, 255, 255), 1.5, 220)
    return [body, shimmer, core]


def _place_streak(objs, hx, hy, bx, by, length, t) -> None:
    body, shimmer, core = objs
    px, py = -by, bx
    wobble = 1.6 * math.sin(t * 23.0)
    _set_line(body, hx, hy, hx + bx * length, hy + by * length)
    _set_line(shimmer, hx + px * wobble, hy + py * wobble,
              hx + bx * length * 0.9 + px * wobble, hy + by * length * 0.9 + py * wobble)
    _set_line(core, hx, hy, hx + bx * length * 0.7, hy + by * length * 0.7)
    _fade(shimmer, 40 + 60 * (0.5 + 0.5 * math.sin(t * 31.0)))


def _build_shell(batch, group, st):
    trail = _line(batch, group, st.trail_color, 1.8, 150)
    sparks = [_disc(batch, group, 1.6, (255, 230, 130)) for _ in range(3)]
    return [trail] + sparks


def _place_shell(objs, hx, hy, bx, by, length, t) -> None:
    trail = objs[0]
    _set_line(trail, hx, hy, hx + bx * length * 0.7, hy + by * length * 0.7)
    px, py = -by, bx
    for i, spark in enumerate(objs[1:]):
        d = length * (0.25 + 0.25 * i)
        side = 2.6 if i % 2 == 0 else -2.6
        spark.position = (hx + bx * d + px * side, hy + by * d + py * side)
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


class ProjectileVisual:
    """Pooled shapes for one projectile: trail pieces first, then the body, core and flare.

    ``objs`` keeps that order, so the body disc is always ``objs[-3]``.
    """

    def __init__(self, batch, group, proj):
        self.style = style_for_projectile(proj)
        st = self.style
        build, self._place = _TRAILS[st.trail]
        self._trail = build(batch, group, st)
        if getattr(proj, "is_crit", False):
            flare_alpha = 150
        elif str(getattr(proj, "owner", "player")) == "enemy":
            flare_alpha = 90
        else:
            flare_alpha = 120
        self._body = _disc(batch, group, st.radius, st.head)
        self._core = _disc(batch, group, max(1.0, st.radius * 0.5), st.core)
        self._flare = _disc(batch, group, max(2.0, st.radius * 0.55), (255, 255, 255), flare_alpha)
        self.objs = self._trail + [self._body, self._core, self._flare]

    def sync(self, proj, shake: Vec2) -> None:
        """Move every piece to the shot's shaken screen position and animate from its ttl."""
        hx, hy = to_iso(proj.pos, shake)
        bx, by, speed = _screen_back(getattr(proj, "vel", None))
        t = float(getattr(proj, "ttl", 0.0))
        self._place(self._trail, hx, hy, bx, by, trail_length(self.style, speed), t)
        head = (hx, hy)
        self._body.position = head
        self._core.position = head
        self._flare.position = head

    def delete(self) -> None:
        for o in self.objs:
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
    """Flak burst on detonation: the existing shrapnel burst plus a short amber ring."""
    particles.add_flak_burst(pos)
    particles.add_shockwave(pos, FLAK_BURST_RING, max_radius=46.0, ttl=0.25)
