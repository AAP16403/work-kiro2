"""Procedural room layout generation (algorithmic level design)."""

from __future__ import annotations

from dataclasses import dataclass
import math
import random

from utils import Vec2, dist


@dataclass
class Obstacle:
    """Circular obstacle in world space."""

    pos: Vec2
    radius: float
    kind: str = "pillar"  # "pillar", "crystal", "crate"


def _difficulty_layout_mult(difficulty: str) -> float:
    d = (difficulty or "normal").lower()
    if d == "easy":
        return 0.9
    if d == "hard":
        return 1.15
    return 1.0


def generate_obstacles(seed: int, segment: int, room_radius: float, difficulty: str = "normal") -> List[Obstacle]:
    """Generate a new set of obstacles for the given segment (group of waves)."""
    rng = random.Random(int(seed) + int(segment) * 1337)
    r = float(room_radius)
    mult = _difficulty_layout_mult(difficulty)

    obstacles: List[Obstacle] = []

    # Keep center and edges playable.
    center_keepout = max(70.0, r * 0.18)
    max_place_r = r * 0.72

    def can_place(p: Vec2, pr: float) -> bool:
        if dist(p, Vec2(0.0, 0.0)) < center_keepout:
            return False
        if dist(p, Vec2(0.0, 0.0)) > max_place_r:
            return False
        for o in obstacles:
            if dist(p, o.pos) < (pr + o.radius + 30.0):
                return False
        return True

    def place(p: Vec2, pr: float, kind: str):
        if can_place(p, pr):
            obstacles.append(Obstacle(pos=p, radius=pr, kind=kind))

    layouts = ["cross", "ring", "lanes", "cluster", "spiral", "maze"]
    layout = layouts[(int(seed) + segment) % len(layouts)]

    # Primary structure:
    if layout == "cross":
        base_r = min(55.0, r * 0.14)
        arm = r * 0.42
        for ang in (0.0, math.pi / 2, math.pi, 3 * math.pi / 2):
            p = Vec2(math.cos(ang) * arm, math.sin(ang) * arm)
            place(p, base_r, "pillar")
        for _ in range(3):
            ang = rng.uniform(0, math.tau)
            p = Vec2(math.cos(ang), math.sin(ang)) * rng.uniform(r * 0.25, r * 0.55)
            place(p, min(34.0, r * 0.09), "crystal")

    elif layout == "ring":
        n = 7
        ring_r = r * 0.46
        for i in range(n):
            ang = (i / n) * math.tau + rng.uniform(-0.18, 0.18)
            p = Vec2(math.cos(ang), math.sin(ang)) * ring_r
            place(p, min(44.0, r * 0.11), "pillar")
        for _ in range(2):
            ang = rng.uniform(0, math.tau)
            p = Vec2(math.cos(ang), math.sin(ang)) * rng.uniform(r * 0.25, r * 0.55)
            place(p, min(28.0, r * 0.075), "crate")

    elif layout == "lanes":
        # "Walls" made of large circles, leaving lanes to move through.
        wall_r = min(70.0, r * 0.16)
        offset = r * 0.22
        place(Vec2(-offset, 0.0), wall_r, "pillar")
        place(Vec2(offset, 0.0), wall_r, "pillar")
        place(Vec2(0.0, offset), wall_r, "pillar")
        for _ in range(3):
            ang = rng.uniform(0, math.tau)
            p = Vec2(math.cos(ang), math.sin(ang)) * rng.uniform(r * 0.28, r * 0.58)
            place(p, min(30.0, r * 0.08), rng.choice(["crate", "crystal"]))

    elif layout == "cluster":
        # Tight cluster off-center + a few small pieces elsewhere.
        cluster_center = Vec2(rng.uniform(-r * 0.25, r * 0.25), rng.uniform(-r * 0.25, r * 0.25))
        for _ in range(6):
            p = cluster_center + Vec2(rng.uniform(-120, 120), rng.uniform(-120, 120))
            place(p, min(42.0, r * 0.11), rng.choice(["pillar", "crate"]))
        for _ in range(3):
            ang = rng.uniform(0, math.tau)
            p = Vec2(math.cos(ang), math.sin(ang)) * rng.uniform(r * 0.35, r * 0.6)
            place(p, min(26.0, r * 0.07), "crystal")

    elif layout == "maze":
        # A simple maze-like structure
        grid_size = 10
        cell_size = r * 2 / grid_size
        wall_radius = cell_size * 0.3
        for i in range(grid_size):
            for j in range(grid_size):
                if rng.random() > 0.3:
                    x = -r + i * cell_size + cell_size / 2
                    y = -r + j * cell_size + cell_size / 2
                    p = Vec2(x, y)
                    if dist(p, Vec2(0.0, 0.0)) > center_keepout:
                        place(p, wall_radius, "pillar")

    else:  # spiral
        turns = 2.2
        steps = 10
        for i in range(steps):
            t = i / max(1, steps - 1)
            ang = t * math.tau * turns + rng.uniform(-0.15, 0.15)
            rad = center_keepout + t * (r * 0.52)
            p = Vec2(math.cos(ang), math.sin(ang)) * rad
            kind = "pillar" if i % 3 == 0 else rng.choice(["crystal", "crate"])
            pr = min(44.0, r * 0.11) if kind == "pillar" else min(28.0, r * 0.075)
            place(p, pr, kind)

    # Secondary fill to scale with segment, difficulty, and room size.
    target = int((4 + segment * 2) * mult + (r / 520.0))
    target = max(5, min(14, target))
    tries = 0
    while len(obstacles) < target and tries < 600:
        tries += 1
        ang = rng.uniform(0, math.tau)
        rad = rng.uniform(center_keepout, max_place_r)
        p = Vec2(math.cos(ang), math.sin(ang)) * rad
        kind = rng.choices(["crate", "crystal", "pillar"], weights=[4, 3, 2], k=1)[0]
        pr = {
            "crate": min(26.0, r * 0.07),
            "crystal": min(30.0, r * 0.075),
            "pillar": min(44.0, r * 0.11),
        }[kind]
        place(p, pr, kind)

    return obstacles

