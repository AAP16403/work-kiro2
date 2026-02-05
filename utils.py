"""Utility functions and math helpers."""

import math
import random
from dataclasses import dataclass
from typing import Tuple

from config import ISO_SCALE_X, ISO_SCALE_Y, ROOM_RADIUS, SCREEN_H, SCREEN_W


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
    return (ix + SCREEN_W / 2 + shake.x, iy + SCREEN_H / 2 + shake.y)


def iso_to_world(screen_xy: Tuple[float, float]) -> Vec2:
    """Convert isometric screen coordinates to world coordinates."""
    ix = screen_xy[0] - SCREEN_W / 2
    iy = screen_xy[1] - SCREEN_H / 2
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
