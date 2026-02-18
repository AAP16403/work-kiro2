"""Utility functions and math helpers."""

import math
import random
from dataclasses import dataclass

from config import ISO_SCALE_X, ISO_SCALE_Y, SCREEN_H, SCREEN_W, MAP_CIRCLE, MAP_DONUT, MAP_CROSS, MAP_DIAMOND

VIEW_W = SCREEN_W
VIEW_H = SCREEN_H

ENEMY_BEHAVIOR_ALIASES = {
    "bomber": "bomber",
    "chase": "chaser",
    "ranged": "ranged",
    "swarm": "swarm",
    "charger": "charger",
    "tank": "tank",
    "spitter": "spitter",
    "flyer": "flyer",
    "engineer": "engineer",
    "thunderboss": "boss_thunder",
    "laserboss": "boss_laser",
    "trapmasterboss": "boss_trapmaster",
    "swarmqueenboss": "boss_swarmqueen",
    "bruteboss": "boss_brute",
}


def set_view_size(width: int, height: int) -> None:
    """Set the current viewport size used for world<->screen transforms."""
    global VIEW_W, VIEW_H
    VIEW_W = int(width)
    VIEW_H = int(height)


def compute_room_radius(view_w: int, view_h: int, margin: float = 0.92) -> float:
    """Compute a room radius that fits the current viewport reasonably well."""
    w = max(1, int(view_w))
    h = max(1, int(view_h))
    m = max(0.5, min(0.98, float(margin)))

    # For a world circle of radius R: max |x-y| ~= 2R, max |x+y| ~= 2R.
    # to_iso: ix = (x-y)*ISO_SCALE_X, iy = (x+y)*ISO_SCALE_Y.
    # We fit within half-viewport with margin: 2R*ISO_SCALE <= (view/2)*margin.
    max_r_x = (w * 0.5 * m) / (2.0 * ISO_SCALE_X)
    max_r_y = (h * 0.5 * m) / (2.0 * ISO_SCALE_Y)

    r = min(max_r_x, max_r_y)
    return max(120.0, min(1200.0, float(r)))


@dataclass
class Vec2:
    """2D Vector class."""
    x: float
    y: float

    def __add__(self, other):
        return Vec2(self.x + other.x, self.y + other.y)

    def __sub__(self, other):
        return Vec2(self.x - other.x, self.y - other.y)

    def __mul__(self, s: float):
        return Vec2(self.x * s, self.y * s)

    def __rmul__(self, s: float):
        return self.__mul__(s)

    def __truediv__(self, s: float):
        if abs(s) <= 1e-12:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / s, self.y / s)

    def __neg__(self):
        return Vec2(-self.x, -self.y)

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def length_squared(self) -> float:
        return self.x * self.x + self.y * self.y

    def dot(self, other) -> float:
        return self.x * other.x + self.y * other.y

    def normalized(self):
        l = self.length()
        if l <= 1e-9:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / l, self.y / l)


def to_iso(world: Vec2, shake: Vec2) -> tuple[float, float]:
    """Convert world coordinates to isometric screen coordinates."""
    ix = (world.x - world.y) * ISO_SCALE_X
    iy = (world.x + world.y) * ISO_SCALE_Y
    return (ix + VIEW_W / 2 + shake.x, iy + VIEW_H / 2 + shake.y)


def iso_to_world(screen_xy: tuple[float, float]) -> Vec2:
    """Convert isometric screen coordinates to world coordinates."""
    ix = screen_xy[0] - VIEW_W / 2
    iy = screen_xy[1] - VIEW_H / 2
    x = (ix / ISO_SCALE_X + iy / ISO_SCALE_Y) * 0.5
    y = (iy / ISO_SCALE_Y - ix / ISO_SCALE_X) * 0.5
    return Vec2(x, y)


def clamp_to_map(p: Vec2, radius: float, map_type: str = "circle") -> Vec2:
    """Clamp a position to stay within the map boundaries."""
    if map_type == MAP_CIRCLE:
        l = p.length()
        if l <= radius:
            return p
        return p.normalized() * radius
    
    elif map_type == MAP_DONUT:
        inner = radius * 0.4
        l = p.length()
        if inner <= l <= radius:
             return p
        if l < inner:
            return p.normalized() * inner
        return p.normalized() * radius

    elif map_type == MAP_DIAMOND:
        # Diamond shape defined by |x| + |y| <= R
        # To clamp, we find the closest point on the diamond edge if outside.
        # But a simple approximation is often enough for movement: project point.
        # Strict clamp:
        limit = radius * 0.8  # Visual fix, diamond feels bigger than circle
        if abs(p.x) + abs(p.y) <= limit:
            return p
        # Project back to edge
        # sign(x)*x + sign(y)*y = limit
        # This is surprisingly tricky to do perfectly smoothly, 
        # so for gameplay fluidness, we might just block normal movement in game.py 
        # but here we return a safe spot.
        # Let's use a robust iterative approach or geometric projection.
        # Closest point on line segment concept.
        # For Game Jam speed:
        ratio = limit / (abs(p.x) + abs(p.y) + 1e-6)
        return p * ratio

    elif map_type == MAP_CROSS:
        # Cross: composed of two rectangles? 
        # Let's say: (|x| < R*0.35 and |y| < R) OR (|x| < R and |y| < R*0.35)
        w = radius * 0.35
        r = radius
        in_v = abs(p.x) < w and abs(p.y) < r
        in_h = abs(p.x) < r and abs(p.y) < w
        if in_v or in_h:
            return p
        
        # Clamping to a non-convex shape is hard. 
        # Simplified: push to closest valid axis?
        # If we are in neither, we are in a corner void.
        # Pull towards origin until valid.
        curr = p
        for _ in range(10):
            in_v = abs(curr.x) < w and abs(curr.y) < r
            in_h = abs(curr.x) < r and abs(curr.y) < w
            if in_v or in_h:
                return curr
            curr = curr * 0.9
        return curr # Fallback

    return p


def random_spawn_map_edge(center: Vec2, radius: float, map_type: str = "circle") -> Vec2:
    """Spawn a position on the edge of the map."""
    while True:
        if map_type == MAP_CIRCLE:
            ang = random.uniform(0.0, math.tau)
            return Vec2(center.x + math.cos(ang) * radius, center.y + math.sin(ang) * radius)
        
        elif map_type == MAP_DONUT:
            # Spawn on outer edge
            ang = random.uniform(0.0, math.tau)
            return Vec2(center.x + math.cos(ang) * radius, center.y + math.sin(ang) * radius)

        elif map_type == MAP_DIAMOND:
            # |x| + |y| = R * 0.8
            limit = radius * 0.8
            side = random.randint(0, 3) # 4 quadrants
            t = random.random()
            x = t * limit
            y = limit - x
            if side == 1: x = -x
            elif side == 2: y = -y
            elif side == 3: x = -x; y = -y
            return Vec2(x, y)

        elif map_type == MAP_CROSS:
            # Spawn at one of the 4 ends
            arm = random.randint(0, 3)
            w = radius * 0.35
            r = radius
            if arm == 0: return Vec2(random.uniform(-w, w), -r) # Top
            if arm == 1: return Vec2(random.uniform(-w, w), r)  # Bottom
            if arm == 2: return Vec2(-r, random.uniform(-w, w)) # Left
            if arm == 3: return Vec2(r, random.uniform(-w, w))  # Right
        
        return center # Fallback


def dist(a: Vec2, b: Vec2) -> float:
    """Calculate distance between two positions."""
    return (a - b).length()


def point_segment_distance(p: Vec2, a: Vec2, b: Vec2) -> float:
    """Distance from point p to segment ab."""
    ab = b - a
    ap = p - a
    ab_len2 = ab.x * ab.x + ab.y * ab.y
    if ab_len2 <= 1e-9:
        return ap.length()
    t = (ap.x * ab.x + ap.y * ab.y) / ab_len2
    t = max(0.0, min(1.0, t))
    closest = Vec2(a.x + ab.x * t, a.y + ab.y * t)
    return (p - closest).length()


def resolve_circle_obstacles(pos: Vec2, radius: float, obstacles, iterations: int = 4) -> Vec2:
    """Push a circle out of overlapping circular obstacles.

    `obstacles` is expected to have `pos` and `radius` attributes.
    """
    p = Vec2(pos.x, pos.y)
    for _ in range(max(1, iterations)):
        moved = False
        for o in obstacles:
            op = o.pos
            r = radius + float(o.radius)
            d = p - op
            l = d.length()
            if l >= r:
                continue
            if l <= 1e-6:
                # Nudge in a stable direction.
                d = Vec2(1.0, 0.0)
                l = 1.0
            push = (r - l) / l
            p = Vec2(p.x + d.x * push, p.y + d.y * push)
            moved = True
        if not moved:
            break
    return p


def enemy_behavior_name(enemy) -> str:
    """Normalize enemy behavior into a stable string id."""
    behavior = getattr(enemy, "behavior", "")
    if isinstance(behavior, str):
        return behavior
    cls_name = behavior.__class__.__name__.lower()
    return ENEMY_BEHAVIOR_ALIASES.get(cls_name, cls_name)
