"""Parallax starfield: three layers of soft stars drifting in screen space behind the arena.

Every star has a home position as a fraction of the window. Each frame its position is the home
position plus a drift term (game time times the layer speed) plus a parallax term (the player's screen
offset times the layer factor), wrapped to the window. Nothing is integrated, so the same game time
gives the same picture, a paused game holds still, and near layers move further than far ones.

The stars are quads in a ``QuadBank`` (see glow.py), so a frame costs one GPU upload. The starfield
uses its own random generator, so it never changes the run's RNG.
"""

from __future__ import annotations

import math
import random

from glow import GLOW_TEXTURE_SIZE, QuadBank
from utils import Vec2, to_iso

# (star count, drift speed in px/s, parallax factor, diameter in px, opacity range)
LAYERS = (
    (28, 5.0, 0.03, 2.0, (60, 120)),
    (16, 12.0, 0.09, 3.0, (90, 160)),
    (8, 26.0, 0.18, 4.5, (150, 225)),
)
DRIFT_X, DRIFT_Y = -0.94, -0.33  # stars drift to the lower left; the direction is normalised in __init__
STAR_COLOR = (205, 228, 255)
TWINKLE_LAYERS = 1  # only the last (nearest) layer twinkles, so far stars stay steady and the frame does less work


class Starfield:
    """Screen-space star layers. Create once per Visuals, then call ``sync`` every draw."""

    def __init__(self, batch, order: int = -19980, seed: int = 0x51A4) -> None:
        rng = random.Random(seed)
        length = math.hypot(DRIFT_X, DRIFT_Y)
        self._drift = (DRIFT_X / length, DRIFT_Y / length)
        total = sum(count for count, _speed, _par, _diam, _range in LAYERS)
        self._bank = QuadBank(batch, total, order)
        self._layers: list[tuple[float, float, bool, list]] = []
        slot = 0
        for idx, (count, speed, parallax, diameter, opacity_range) in enumerate(LAYERS):
            stars = []
            lo, hi = opacity_range
            scale = float(diameter) / GLOW_TEXTURE_SIZE  # the quad is one texture wide at scale 1
            for _ in range(count):
                fx = rng.random()
                fy = rng.random()
                opacity = rng.randint(lo, hi)
                phase = rng.uniform(0.0, math.tau)
                self._bank.style(slot, scale, scale, 0.0, (STAR_COLOR[0], STAR_COLOR[1], STAR_COLOR[2], opacity))
                stars.append((slot, fx, fy, opacity, phase, scale))
                slot += 1
            twinkle = idx >= len(LAYERS) - TWINKLE_LAYERS
            self._layers.append((float(speed), float(parallax), twinkle, stars))
        self._bank.flush()

    @property
    def layer_count(self) -> int:
        return len(self._layers)

    @property
    def star_count(self) -> int:
        return sum(len(stars) for _speed, _par, _tw, stars in self._layers)

    def layer_speeds(self) -> list[float]:
        return [speed for speed, _par, _tw, _stars in self._layers]

    def sync(self, t: float, width: float, height: float, camera: Vec2 | None = None) -> None:
        """Place every star for game time ``t`` in a window of ``width`` x ``height`` px."""
        w = max(1.0, float(width))
        h = max(1.0, float(height))
        cam_x = cam_y = 0.0
        if camera is not None:
            origin = to_iso(Vec2(0.0, 0.0), Vec2(0.0, 0.0))
            here = to_iso(camera, Vec2(0.0, 0.0))
            cam_x = here[0] - origin[0]
            cam_y = here[1] - origin[1]
        bank = self._bank
        dir_x, dir_y = self._drift
        # Twinkle is sampled at 12 Hz: the eye cannot tell, and the colours then upload only on those steps.
        twinkle_t = math.floor(t * 12.0) / 12.0
        for speed, parallax, twinkle, stars in self._layers:
            off_x = dir_x * speed * t - parallax * cam_x
            off_y = dir_y * speed * t - parallax * cam_y
            for slot, fx, fy, opacity, phase, scale in stars:
                bank.place(slot, (fx * w + off_x) % w, (fy * h + off_y) % h)
                if twinkle:
                    level = int(opacity * (0.75 + 0.25 * math.sin(twinkle_t * 1.7 + phase)))
                    bank.style(slot, scale, scale, 0.0, (STAR_COLOR[0], STAR_COLOR[1], STAR_COLOR[2], level))
        bank.flush()
