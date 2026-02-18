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

    # For a world circle of radius R:
    # Max isometric width span is approx 2.828 * R (diagonal of square bounding box).
    # Previous logic assumed 4.0 * R which was too conservative.
    # We use 1.5 as divisor (approx 3.0 total span) to be safe but utilize more screen.
    max_r_x = (w * 0.5 * m) / (1.5 * ISO_SCALE_X)
    max_r_y = (h * 0.5 * m) / (1.5 * ISO_SCALE_Y)

    r = min(max_r_x, max_r_y)
    return max(150.0, min(1400.0, float(r)))


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


# Isometric conversion functions removed - handled by Panda3D Camera.


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
        # Diamond visuals = World Square.
        # Clamp to axis-aligned square box.
        limit = radius * 0.707  # R / sqrt(2) approx
        x = max(-limit, min(limit, p.x))
        y = max(-limit, min(limit, p.y))
        return Vec2(x, y)

    elif map_type == MAP_CROSS:
        # Cross: composed of two rectangles (arms).
        w = radius * 0.35
        r = radius
        
        # First clamp to outer bounding box
        rx = max(-r, min(r, p.x))
        ry = max(-r, min(r, p.y))
        
        # If inside center square or arms, we are good.
        in_v = abs(rx) <= w
        in_h = abs(ry) <= w
        
        if in_v or in_h:
            return Vec2(rx, ry)
            
        # If in corner voids, clamp to the corner of the center square.
        cx = math.copysign(w, rx)
        cy = math.copysign(w, ry)
        return Vec2(cx, cy)

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
            # Square box edges: x=+/-L or y=+/-L
            limit = radius * 0.707
            side = random.randint(0, 3)
            # 0: Top (y=L), 1: Bottom (y=-L), 2: Left (x=-L), 3: Right (x=L)
            if side == 0: return Vec2(random.uniform(-limit, limit), limit)
            if side == 1: return Vec2(random.uniform(-limit, limit), -limit)
            if side == 2: return Vec2(-limit, random.uniform(-limit, limit))
            if side == 3: return Vec2(limit, random.uniform(-limit, limit))

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
