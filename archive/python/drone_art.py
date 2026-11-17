"""Drone companion visuals: a small glowing hull that bobs above its orbit point, turns to face its target and flashes at the muzzle.

All shapes are built once and only re-positioned per frame, so the drone adds no per-frame allocations.
The glow is made of translucent circles, which needs no shader or extra module.
"""

import math

from pyglet import shapes

from config import ISO_SCALE_X, ISO_SCALE_Y, POWERUP_COLORS
from drone import DRONE_FLASH_TIME, DRONE_MUZZLE_OFFSET
from utils import Vec2, to_iso

HULL_COLOR = (214, 248, 255)
GLOW_COLOR = POWERUP_COLORS.get("drone", (90, 255, 225))
FLASH_COLOR = (255, 240, 170)
ALTITUDE = 16.0      # screen px the hull floats above its ground point
BOB_AMPLITUDE = 2.5  # screen px of vertical bob
BOB_RATE = 5.0       # radians per second of the bob
ROTOR_RATE = 26.0    # radians per second of the rotor pulse


class DroneArt:
    """Pyglet shapes for one drone. Add ``parts`` to a RenderHandle to depth-sort them."""

    def __init__(self, batch):
        self.shadow = shapes.Ellipse(0, 0, 9, 4, color=(0, 0, 0), batch=batch)
        self.shadow.opacity = 110
        self.bloom = shapes.Circle(0, 0, 26, color=GLOW_COLOR, batch=batch)
        self.bloom.opacity = 26
        self.halo = shapes.Circle(0, 0, 16, color=GLOW_COLOR, batch=batch)
        self.halo.opacity = 80
        self.halo_core = shapes.Circle(0, 0, 9, color=GLOW_COLOR, batch=batch)
        self.halo_core.opacity = 150
        self.hull = shapes.Polygon((9, 0), (2, 5), (-7, 3.5), (-7, -3.5), (2, -5), color=HULL_COLOR, batch=batch)
        self.rotor = shapes.Line(0, 0, 0, 0, thickness=2, color=GLOW_COLOR, batch=batch)
        self.tail = shapes.Line(0, 0, 0, 0, thickness=2, color=GLOW_COLOR, batch=batch)
        self.eye = shapes.Circle(0, 0, 2.2, color=(255, 255, 255), batch=batch)
        self.flash_glow = shapes.Circle(0, 0, 6, color=FLASH_COLOR, batch=batch)
        self.flash_core = shapes.Circle(0, 0, 2.5, color=(255, 255, 255), batch=batch)
        self.parts = (
            self.shadow, self.bloom, self.halo, self.halo_core, self.hull, self.rotor, self.tail,
            self.eye, self.flash_glow, self.flash_core,
        )

    def sync(self, drone, shake: Vec2, t: float) -> float:
        """Place every part for this frame. Returns the hull's screen y, used for depth sorting."""
        visible = bool(drone.active)
        for part in self.parts:
            part.visible = visible
        if not visible:
            return 0.0

        gx, gy = to_iso(drone.pos, shake)
        cx = gx
        cy = gy + ALTITUDE + math.sin(t * BOB_RATE) * BOB_AMPLITUDE

        # Facing in screen space: project the world heading the same way the iso view does.
        hx, hy = drone.heading.x, drone.heading.y
        fx = (hx - hy) * ISO_SCALE_X
        fy = (hx + hy) * ISO_SCALE_Y
        flen = math.hypot(fx, fy)
        if flen <= 1e-9:
            fx, fy, flen = 1.0, 0.0, 1.0
        fx /= flen
        fy /= flen
        px, py = -fy, fx  # perpendicular to the facing, for the rotor bar

        pulse = 0.5 + 0.5 * math.sin(t * 4.0)
        self.shadow.x, self.shadow.y = gx, gy - 6
        self.bloom.x, self.bloom.y = cx, cy
        self.bloom.opacity = int(20 + 16 * pulse)
        self.halo.x, self.halo.y = cx, cy
        self.halo.opacity = int(70 + 40 * pulse)
        self.halo_core.x, self.halo_core.y = cx, cy
        self.hull.x, self.hull.y = cx, cy
        self.hull.rotation = -math.degrees(math.atan2(fy, fx))  # pyglet rotates clockwise

        spin = 0.5 + 0.5 * abs(math.cos(t * ROTOR_RATE))
        half = 9.0 * (0.4 + 0.6 * spin)
        self.rotor.x, self.rotor.y = cx + px * half, cy + py * half
        self.rotor.x2, self.rotor.y2 = cx - px * half, cy - py * half
        self.tail.x, self.tail.y = cx - fx * 7, cy - fy * 7
        self.tail.x2, self.tail.y2 = cx - fx * 14, cy - fy * 14
        self.eye.x, self.eye.y = cx + fx * 3, cy + fy * 3

        if drone.flash > 0.0:
            k = min(1.0, float(drone.flash) / DRONE_FLASH_TIME)
            mx = cx + fx * (DRONE_MUZZLE_OFFSET - 1.0)
            my = cy + fy * (DRONE_MUZZLE_OFFSET - 1.0)
            self.flash_glow.x, self.flash_glow.y = mx, my
            self.flash_glow.radius = 4.0 + 5.0 * k
            self.flash_glow.opacity = int(230 * k)
            self.flash_core.x, self.flash_core.y = mx, my
            self.flash_core.radius = 1.5 + 2.0 * k
            self.flash_core.opacity = int(255 * k)
            self.flash_glow.visible = True
            self.flash_core.visible = True
        else:
            self.flash_glow.visible = False
            self.flash_core.visible = False
        return cy
