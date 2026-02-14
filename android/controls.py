from __future__ import annotations

import math
from dataclasses import dataclass

import config
from utils import Vec2


def screen_delta_to_world(dx: float, dy: float) -> Vec2:
    """Convert an on-screen isometric delta (pixels) into a world-space delta."""
    ix = float(dx)
    iy = float(dy)
    sx = max(1e-6, float(getattr(config, "ISO_SCALE_X", 1.0)))
    sy = max(1e-6, float(getattr(config, "ISO_SCALE_Y", 0.5)))
    x = (ix / sx + iy / sy) * 0.5
    y = (iy / sy - ix / sx) * 0.5
    return Vec2(x, y)


@dataclass
class VirtualStick:
    uid: object | None = None
    origin: tuple[float, float] = (0.0, 0.0)
    pos: tuple[float, float] = (0.0, 0.0)
    max_radius_px: float = 70.0
    deadzone_px: float = 6.0

    def active(self) -> bool:
        return self.uid is not None

    def set_down(self, uid: object, x: float, y: float) -> None:
        self.uid = uid
        self.origin = (float(x), float(y))
        self.pos = (float(x), float(y))

    def set_move(self, x: float, y: float) -> None:
        self.pos = (float(x), float(y))

    def set_up(self) -> None:
        self.uid = None

    def delta(self) -> tuple[float, float]:
        if not self.active():
            return (0.0, 0.0)
        ox, oy = self.origin
        x, y = self.pos
        dx = float(x - ox)
        dy = float(y - oy)
        l = math.hypot(dx, dy)
        if l <= 1e-9:
            return (0.0, 0.0)
        if l < float(self.deadzone_px):
            return (0.0, 0.0)
        cap = max(1.0, float(self.max_radius_px))
        s = min(1.0, cap / l)
        return (dx * s, dy * s)

    def direction_world(self) -> Vec2:
        dx, dy = self.delta()
        v = screen_delta_to_world(dx, dy)
        if v.length() <= 1e-9:
            return Vec2(0.0, 0.0)
        return v.normalized()


class TouchControls:
    """Two-stick controls: left = movement, right = aiming."""

    def __init__(self, max_radius_px: float = 70.0):
        self.move = VirtualStick(max_radius_px=float(max_radius_px))
        self.aim = VirtualStick(max_radius_px=float(max_radius_px))

    def release_all(self) -> None:
        self.move.set_up()
        self.aim.set_up()

    def handle_touch_down(self, touch, width: float, height: float) -> bool:
        x, _y = touch.pos
        if x <= float(width) * 0.45 and not self.move.active():
            self.move.set_down(touch.uid, *touch.pos)
            return True
        if x >= float(width) * 0.55 and not self.aim.active():
            self.aim.set_down(touch.uid, *touch.pos)
            return True
        return False

    def handle_touch_move(self, touch) -> bool:
        if touch.uid == self.move.uid:
            self.move.set_move(*touch.pos)
            return True
        if touch.uid == self.aim.uid:
            self.aim.set_move(*touch.pos)
            return True
        return False

    def handle_touch_up(self, touch) -> bool:
        if touch.uid == self.move.uid:
            self.move.set_up()
            return True
        if touch.uid == self.aim.uid:
            self.aim.set_up()
            return True
        return False

