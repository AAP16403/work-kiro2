"""Utility functions and math helpers."""

import math
import random
from dataclasses import dataclass
from typing import Tuple

from config import ISO_SCALE_X, ISO_SCALE_Y, SCREEN_H, SCREEN_W

VIEW_W = SCREEN_W
VIEW_H = SCREEN_H


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

    def length(self) -> float:
        return math.hypot(self.x, self.y)

    def normalized(self):
        l = self.length()
        if l <= 1e-9:
            return Vec2(0.0, 0.0)
        return Vec2(self.x / l, self.y / l)


def to_iso(world: Vec2, shake: Vec2) -> Tuple[float, float]:
    """Convert world coordinates to isometric screen coordinates."""
    ix = (world.x - world.y) * ISO_SCALE_X
    iy = (world.x + world.y) * ISO_SCALE_Y
    return (ix + VIEW_W / 2 + shake.x, iy + VIEW_H / 2 + shake.y)


def iso_to_world(screen_xy: Tuple[float, float]) -> Vec2:
    """Convert isometric screen coordinates to world coordinates."""
    ix = screen_xy[0] - VIEW_W / 2
    iy = screen_xy[1] - VIEW_H / 2
    x = (ix / ISO_SCALE_X + iy / ISO_SCALE_Y) * 0.5
    y = (iy / ISO_SCALE_Y - ix / ISO_SCALE_X) * 0.5
    return Vec2(x, y)


def clamp_to_room(p: Vec2, max_r: float) -> Vec2:
    """Clamp a position to stay within the room radius."""
    l = p.length()
    if l <= max_r:
        return p
    return p.normalized() * max_r


def random_spawn_edge(center: Vec2, radius: float) -> Vec2:
    """Spawn a position on the edge of a circle."""
    ang = random.uniform(0.0, math.tau)
    return Vec2(center.x + math.cos(ang) * radius, center.y + math.sin(ang) * radius)


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
