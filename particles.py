"""Particle system for visual effects."""

from dataclasses import dataclass
import random
import math

import pyglet
from pyglet import image
from pyglet import shapes
from pyglet.sprite import Sprite

import config
from utils import to_iso, Vec2

@dataclass
class Particle:
    pos: Vec2
    vel: Vec2
    life: float
    max_life: float
    color: tuple[int, int, int]
    size: float
    decay: bool = True
    # "dot" = pooled circle (default), "ring" = expanding shockwave,
    # "glow" = soft flash disc. Rings and glows use `size` as their max radius.
    kind: str = "dot"
    # Rings/glows: seconds before the effect becomes visible (for staggering).
    delay: float = 0.0

_RING_TEX_SIZE = 128
_GLOW_TEX_SIZE = 64
_RING_PEAK_PX = 0.9 * _RING_TEX_SIZE / 2.0  # texture radius (px) of the ring band
_GLOW_PEAK_PX = _GLOW_TEX_SIZE / 2.0        # glow fades to zero at the texture edge


def _ring_alpha(d: float) -> float:
    """Thin gaussian band at 0.9 of the half-size, plus a faint inner fill."""
    if d > 1.0:
        return 0.0
    band = math.exp(-(((d - 0.9) / 0.016) ** 2))
    inner = 0.12 * max(0.0, 1.0 - d / 0.9) ** 2
    return min(1.0, band + inner)


def _glow_alpha(d: float) -> float:
    """Bright core fading into a soft halo."""
    if d >= 1.0:
        return 0.0
    core = max(0.0, 1.0 - d / 0.4) ** 2
    halo = 0.55 * (1.0 - d) ** 2
    return min(1.0, core + halo)


def _radial_texture(size: int, alpha_at):
    """Build a white RGBA radial texture once; sprites tint it with their color."""
    half = size / 2.0
    steps = 512  # alpha lookup resolution over distance 0..1.5 (in half-sizes)
    scale = steps / 1.5
    lut = [int(255 * alpha_at(i / scale)) for i in range(steps + 1)]
    chunks = [bytes((255, 255, 255, a)) for a in range(256)]
    xs = [(col + 0.5 - half) / half for col in range(size)]
    rows = []
    for row in range(size):
        dy2 = ((row + 0.5 - half) / half) ** 2
        rows.append(b"".join([chunks[lut[min(steps, int(math.sqrt(dx * dx + dy2) * scale))]] for dx in xs]))
    img = image.ImageData(size, size, "RGBA", b"".join(rows))
    img.anchor_x = size // 2
    img.anchor_y = size // 2
    return img.get_texture()


def _mix(a, b, t: float) -> tuple[int, int, int]:
    """Linear blend of two RGB colors (t=0 gives a, t=1 gives b)."""
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

class ParticleSystem:
    """Manages transient visual particles."""

    def __init__(self, batch=None):
        self.batch = batch or pyglet.graphics.Batch()
        self.group = pyglet.graphics.Group(order=15000)
        self.particles: list[Particle] = []
        self._shapes: list[shapes.Circle] = []
        self._ring_sprites: list[Sprite] = []
        self._glow_sprites: list[Sprite] = []
        self._ring_tex = None
        self._glow_tex = None
        self._last_active = 0

    def _capped_count(self, count: int) -> int:
        """How many new particles may be spawned now, applying the soft/hard caps."""
        if count <= 0:
            return 0
        soft_cap = int(getattr(config, "PARTICLE_SOFT_CAP", 550))
        hard_cap = int(getattr(config, "PARTICLE_HARD_CAP", 800))
        current = len(self.particles)
        if current >= hard_cap:
            return 0
        if current > soft_cap:
            headroom = max(1, hard_cap - soft_cap)
            overload = min(headroom, current - soft_cap)
            scale = max(0.15, 1.0 - (overload / float(headroom)))
            count = int(count * scale)
            if count <= 0:
                return 0
        if current + count > hard_cap:
            count = max(0, hard_cap - current)
        return count

    def emit(
        self,
        pos: Vec2,
        color: tuple[int, int, int],
        count: int = 5,
        speed: float = 100.0,
        life: float = 0.6,
        size: float = 3.0,
        spread: float = 6.28,
        direction: Vec2 = None,
        spread_angle: float = None,
        decay: bool = True,
    ):
        if count <= 0:
            return
        count = self._capped_count(count)
        if count <= 0:
            return
        base_angle = 0.0
        if direction:
            base_angle = math.atan2(direction.y, direction.x)

        limit_angle = spread_angle if spread_angle is not None else spread

        for _ in range(count):
            angle = base_angle + random.uniform(-limit_angle * 0.5, limit_angle * 0.5) if direction else random.uniform(0, limit_angle)
            sp = random.uniform(speed * 0.5, speed * 1.5)
            vel = Vec2(math.cos(angle) * sp, math.sin(angle) * sp)
            life_val = random.uniform(life * 0.7, life * 1.3)
            p = Particle(
                pos=Vec2(pos.x, pos.y),
                vel=vel,
                life=life_val,
                max_life=life_val,
                color=color,
                size=random.uniform(size * 0.7, size * 1.3),
                decay=decay,
            )
            self.particles.append(p)

    def add_death_explosion(self, pos: Vec2, color: tuple[int, int, int], behavior_name: str = ""):
        count = 12
        if behavior_name.startswith("boss"):
            count = 40
        elif behavior_name == "tank":
            count = 20
        self.emit(pos, color, count=count, speed=150.0, life=0.8, size=4.0)

    def add_hit_particles(self, pos: Vec2, color: tuple[int, int, int]):
        self.emit(pos, color, count=4, speed=80.0, life=0.4, size=2.5)

    def add_muzzle_flash(self, pos: Vec2, direction: Vec2):
        self.emit(pos, (255, 255, 200), count=6, speed=120.0, life=0.15, size=2.0, direction=direction, spread_angle=0.5)

    def add_step_dust(self, pos: Vec2, move_dir: Vec2):
        # Dust kicks up opposite to movement
        self.emit(pos, (200, 200, 200), count=2, speed=30.0, life=0.3, size=2.0, direction=-move_dir, spread_angle=1.0)

    def add_powerup_collection(self, pos: Vec2, color: tuple[int, int, int]):
        self.emit(pos, color, count=16, speed=120.0, life=0.8, size=3.5)

    def add_shield_hit(self, pos: Vec2, amount: int):
        strength = max(4, min(18, int(amount) // 4))
        self.emit(pos, (120, 210, 255), count=strength, speed=90.0, life=0.35, size=2.6)

    def add_dash_effect(self, pos: Vec2, dash_dir: Vec2):
        back = -dash_dir
        self.emit(pos, (160, 220, 255), count=8, speed=140.0, life=0.25, size=2.4, direction=back, spread_angle=0.4)

    def add_laser_beam(self, start: Vec2, end: Vec2, color: tuple[int, int, int]):
        # Emit particles along the line
        d = dist(start, end)
        steps = max(3, int(d / 15.0))
        delta = (end - start) / float(steps)
        curr = start
        for _ in range(steps):
            self.emit(curr, color, count=2, speed=40.0, life=0.3, size=2.0)
            curr += delta

    def add_vortex_swirl(self, center: Vec2, time: float, radius: float):
        # Spiral particles
        angle = time * 4.0
        offset = Vec2(math.cos(angle) * radius, math.sin(angle) * radius)
        p = Particle(
            pos=center + offset,
            vel=-offset.normalized() * 50.0, # Suck in
            life=0.4,
            max_life=0.4,
            color=(180, 140, 255),
            size=3.0,
            decay=False
        )
        self.particles.append(p)

    def add_boost_flame(self, pos: Vec2, move_dir: Vec2):
        """Add high-velocity overdrive flames behind the ship."""
        back = -move_dir
        # Blue core + orange flame envelope
        self.emit(pos, (130, 220, 255), count=3, speed=160.0, life=0.22, size=3.0, direction=back, spread_angle=0.35)
        self.emit(pos, (255, 140, 40), count=4, speed=130.0, life=0.30, size=3.8, direction=back, spread_angle=0.55)

    def add_crit_spark(self, pos: Vec2):
        """Emit brilliant golden starburst sparks on critical strike."""
        self.emit(pos, (255, 235, 90), count=10, speed=180.0, life=0.35, size=3.5)
        self.emit(pos, (255, 255, 240), count=4, speed=220.0, life=0.20, size=2.5)

    def add_railgun_trail(self, start: Vec2, end: Vec2):
        """Emit electric ionized spiral particles along the railgun beam."""
        d = dist(start, end)
        steps = max(4, int(d / 22.0))
        delta = (end - start) / float(steps)
        curr = start
        for _ in range(steps):
            self.emit(curr, (140, 240, 255), count=1, speed=50.0, life=0.25, size=2.8)
            curr += delta

    def add_flak_burst(self, pos: Vec2):
        """Explosive shrapnel burst on flak detonation."""
        self.emit(pos, (255, 160, 50), count=12, speed=170.0, life=0.45, size=3.2)
        self.emit(pos, (255, 220, 140), count=6, speed=120.0, life=0.25, size=2.2)

    def add_elite_aura(self, pos: Vec2, color: tuple[int, int, int]):
        """Subtle orbiting energy spark for elite enemies."""
        if random.random() < 0.35:
            ang = random.uniform(0, math.tau)
            r = 18.0
            p = pos + Vec2(math.cos(ang) * r, math.sin(ang) * r)
            self.emit(p, color, count=1, speed=25.0, life=0.35, size=2.0)

    def _add_ring(self, pos: Vec2, color: tuple[int, int, int], max_radius: float, ttl: float, delay: float = 0.0):
        """Queue one expanding ring. It takes a single particle slot and never moves."""
        if self._capped_count(1) <= 0:
            return
        ttl = max(0.05, float(ttl))
        delay = max(0.0, float(delay))
        life = ttl + delay
        self.particles.append(Particle(
            pos=Vec2(pos.x, pos.y),
            vel=Vec2(0.0, 0.0),
            life=life,
            max_life=life,
            color=color,
            size=max(1.0, float(max_radius)),
            decay=False,
            kind="ring",
            delay=delay,
        ))

    def _add_glow(self, pos: Vec2, color: tuple[int, int, int], radius: float, ttl: float):
        """Queue one short soft glow disc (flash). It takes a single particle slot."""
        if self._capped_count(1) <= 0:
            return
        ttl = max(0.05, float(ttl))
        self.particles.append(Particle(
            pos=Vec2(pos.x, pos.y),
            vel=Vec2(0.0, 0.0),
            life=ttl,
            max_life=ttl,
            color=color,
            size=max(1.0, float(radius)),
            decay=False,
            kind="glow",
        ))

    def add_shockwave(self, pos: Vec2, color: tuple[int, int, int], max_radius: float = 110.0, ttl: float = 0.35):
        """Expanding energy ring that grows from pos to max_radius (ease-out) and fades."""
        self._add_ring(pos, color, max_radius, ttl)

    def add_boss_death(self, pos: Vec2, color: tuple[int, int, int]):
        """Multi-stage boss explosion (about 70 new particles, capped)."""
        white = (255, 255, 240)
        hot = _mix(color, (255, 255, 255), 0.5)
        # Stage 1: colored halo first, then the blinding white core on top
        self._add_glow(pos, color, 200.0, 0.40)
        self._add_glow(pos, white, 130.0, 0.22)
        # Stage 2: three staggered shockwave rings
        self._add_ring(pos, color, 150.0, 0.45, delay=0.0)
        self._add_ring(pos, hot, 230.0, 0.55, delay=0.06)
        self._add_ring(pos, color, 320.0, 0.70, delay=0.14)
        # Stage 3: white-hot core sparks and a dense radial debris burst
        self.emit(pos, white, count=14, speed=300.0, life=0.22, size=2.4)
        self.emit(pos, color, count=36, speed=260.0, life=0.7, size=3.6)
        # Stage 4: slow embers drifting upward that linger
        self.emit(pos, (255, 180, 70), count=14, speed=45.0, life=1.2, size=2.6,
                  direction=Vec2(1.0, 1.0), spread_angle=2.4)

    def add_pickup_ring(self, pos: Vec2, color: tuple[int, int, int]):
        """Quick upward sparkle ring for rare pickups: sparks fan out in a ring and rise."""
        self._add_glow(pos, (255, 255, 240), 26.0, 0.25)
        self._add_ring(pos, color, 46.0, 0.30)
        count = self._capped_count(14)
        if count <= 0:
            return
        # Screen-up is world (1, 1) under the iso projection; ~110 px/s in world units.
        rise = 110.0 / (2.0 * float(getattr(config, "ISO_SCALE_Y", 0.35)))
        base = random.uniform(0.0, math.tau)
        sparkle = _mix(color, (255, 255, 255), 0.5)
        for i in range(count):
            ang = base + i * math.tau / 14.0
            c = math.cos(ang)
            s = math.sin(ang)
            life_val = random.uniform(0.35, 0.5)
            self.particles.append(Particle(
                pos=Vec2(pos.x + c * 14.0, pos.y + s * 14.0),
                vel=Vec2(c * 30.0 + rise, s * 30.0 + rise),
                life=life_val,
                max_life=life_val,
                color=sparkle if i % 2 else color,
                size=2.0,
                decay=False,
            ))

    def add_kill_burst(self, pos: Vec2, color: tuple[int, int, int], big: bool = False):
        """Small extra spark spray for kills (bigger when big=True). Call with add_death_explosion."""
        if big:
            self.emit(pos, color, count=12, speed=230.0, life=0.34, size=2.8)
            self.emit(pos, (255, 255, 240), count=5, speed=280.0, life=0.20, size=2.0)
        else:
            self.emit(pos, color, count=6, speed=190.0, life=0.26, size=2.4)
            self.emit(pos, (255, 255, 240), count=2, speed=230.0, life=0.16, size=2.0)

    def dist(self, a, b):
         return math.sqrt((a.x-b.x)**2 + (a.y-b.y)**2)

    def update(self, dt: float):
        if not self.particles:
            return
        keep = []
        decay_factor = max(0.0, 1.0 - 2.0 * dt)
        for p in self.particles:
            p.life -= dt
            if p.life > 0:
                p.pos = p.pos + p.vel * dt
                if p.decay:
                    p.vel = p.vel * decay_factor
                keep.append(p)
        self.particles = keep

    def _pooled_sprite(self, pool: list, index: int, kind: str) -> Sprite:
        """Reuse the pooled sprite at index; only create one when the pool grows."""
        if index >= len(pool):
            if kind == "ring":
                if self._ring_tex is None:
                    self._ring_tex = _radial_texture(_RING_TEX_SIZE, _ring_alpha)
                tex = self._ring_tex
            else:
                if self._glow_tex is None:
                    self._glow_tex = _radial_texture(_GLOW_TEX_SIZE, _glow_alpha)
                tex = self._glow_tex
            pool.append(Sprite(tex, batch=self.batch, group=self.group))
        return pool[index]

    def render(self, shake: Vec2):
        if not self.particles:
            if self._last_active:
                for sh in self._shapes:
                    sh.opacity = 0
                for sp in self._ring_sprites:
                    sp.opacity = 0
                for sp in self._glow_sprites:
                    sp.opacity = 0
                self._last_active = 0
            return

        needed = len(self.particles)
        self._last_active = needed
        # Pre-allocate pooled shapes with fixed default radius (3.0) to prevent
        # expensive vertex list rebuilds on every frame.
        if len(self._shapes) < needed:
            diff = needed - len(self._shapes)
            for _ in range(diff):
                self._shapes.append(shapes.Circle(0, 0, 3, color=(255, 255, 255), batch=self.batch, group=self.group))

        # Fast position, color, and opacity update (no radius mutation = no vertex reallocation!)
        # Dots use pooled circles. Rings and glows use pooled textured sprites, where only
        # position, scale and color change per frame.
        dot_i = 0
        ring_i = 0
        glow_i = 0
        for p in self.particles:
            kind = p.kind
            if kind == "dot":
                sh = self._shapes[dot_i]
                dot_i += 1
                sx, sy = to_iso(p.pos, shake)
                sh.x = sx
                sh.y = sy
                ratio = max(0.0, p.life / p.max_life)
                new_opacity = max(0, min(255, int(255 * ratio)))
                sh.opacity = new_opacity
                if sh.color != p.color:
                    sh.color = p.color
            elif kind == "ring" or kind == "glow":
                age = p.max_life - p.life - p.delay
                if age < 0.0:
                    continue  # staggered effect has not started yet
                ttl = max(1e-6, p.max_life - p.delay)
                prog = min(1.0, age / ttl)
                fade = 1.0 - prog
                sx, sy = to_iso(p.pos, shake)
                if kind == "ring":
                    radius = p.size * (1.0 - fade * fade)  # ease-out growth
                    sp = self._pooled_sprite(self._ring_sprites, ring_i, "ring")
                    ring_i += 1
                    scale = radius / _RING_PEAK_PX
                    alpha = fade ** 0.8
                else:
                    radius = p.size * (0.55 + 0.45 * prog)  # quick swell
                    sp = self._pooled_sprite(self._glow_sprites, glow_i, "glow")
                    glow_i += 1
                    scale = radius / _GLOW_PEAK_PX
                    alpha = fade ** 1.5
                sp.x = sx
                sp.y = sy
                sp.scale = max(0.02, scale)
                sp.opacity = int(255 * alpha)
                sp.color = p.color

        # Hide unused shapes efficiently
        for i in range(dot_i, len(self._shapes)):
            if self._shapes[i].opacity > 0:
                self._shapes[i].opacity = 0
        for i in range(ring_i, len(self._ring_sprites)):
            if self._ring_sprites[i].opacity > 0:
                self._ring_sprites[i].opacity = 0
        for i in range(glow_i, len(self._glow_sprites)):
            if self._glow_sprites[i].opacity > 0:
                self._glow_sprites[i].opacity = 0

def dist(a: Vec2, b: Vec2) -> float:
    return (a - b).length()
